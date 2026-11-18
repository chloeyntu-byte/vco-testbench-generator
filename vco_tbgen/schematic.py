"""Emit and verify owned OA fixture schematics, registers and config views."""
from pathlib import Path
from .native import sq, guard

def symbol(lib,cell,ports):
    b='cv=dbOpenCellViewByType('+sq(lib)+' '+sq(cell)+' "symbol" "schematicSymbol" "w")\n'
    height=max(1,len(ports)*.5)
    b+='dbCreateRect(cv list("device" "drawing") list(list(0 -0.5) list(2 '+str(height)+')))\n'
    for i,(name,direction) in enumerate(ports):
        y=i*.5
        b+='n=dbCreateNet(cv '+sq(name)+') tm=dbCreateTerm(n '+sq(name)+' '+sq(direction)+')\n'
        b+='f=dbCreateRect(cv list("pin" "drawing") list(list(-0.025 '+str(y-.025)+') list(0.025 '+str(y+.025)+')))\ndbCreatePin(n f '+sq(name)+')\n'
        b+='dbCreateLabel(cv list("device" "label") list(0.1 '+str(y)+') '+sq(name)+' "centerLeft" "R0" "roman" 0.0625)\n'
    b+='dbReplaceProp(cv "instNamePrefix" "string" "I")\n'+guard('dbSave(cv)','symbol save failed')+'dbClose(cv)\n'
    return b


def register_cell(width):return 'isf_decimal_register' if width==4 else 'isf_decimal_register_w'+str(width)

def register_source(width):
    # WIDTH is elaborated in the view identity, avoiding a misleading variable-width OA symbol.
    return '''`include "constants.vams"
`include "disciplines.vams"
module %(module)s(bits,vdd,vss);
 parameter integer WIDTH=%(w)s;
 parameter integer DEC_CODE=0;
 parameter integer INVERT=0 from [0:1];
 output [%(top)s:0] bits;
 inout vdd,vss;
 electrical [%(top)s:0] bits;
 electrical vdd,vss;
 genvar i;
 analog begin
  @(initial_step) if (WIDTH!=%(w)s || DEC_CODE<0 || DEC_CODE>=%(limit)s)
    $fatal(1,"Invalid WIDTH or DEC_CODE");
  for(i=0;i<%(w)s;i=i+1) begin
   V(bits[i],vss) <+ (((DEC_CODE>>i)&1)^INVERT)*V(vdd,vss);
  end
 end
endmodule
''' % {'w':width,'top':width-1,'limit':2**width,'module':register_cell(width)}


def register_view(lib,width):
    cell=register_cell(width)
    b='unless(ddGetObj('+sq(lib)+' '+sq(cell)+')\n'
    b+='f=ddGetObj('+sq(lib)+' '+sq(cell)+' "veriloga" "veriloga.va" nil "w")\n'+guard('f','VA view create failed')
    b+='o=outfile(f~>writePath) fprintf(o "%s" '+sq(register_source(width))+') close(o) ddReleaseObj(f)\n'
    b+=guard('ahdlUpdateViewInfo('+sq(lib)+' ?cell '+sq(cell)+' ?view "veriloga")','VA interface extraction failed')
    b+=symbol(lib,cell,[(f'bits<{width-1}:0>','output'),('vdd','inputOutput'),('vss','inputOutput')])
    b+='c=cdfGetBaseCellCDF(ddGetObj('+sq(lib)+' '+sq(cell)+'))\nunless(c c=cdfCreateBaseCellCDF(ddGetObj('+sq(lib)+' '+sq(cell)+')))\n'
    for name,val in [('WIDTH',width),('DEC_CODE',0),('INVERT',0)]:
        b+='unless(cdfFindParamByName(c '+sq(name)+') cdfCreateParam(c ?name '+sq(name)+' ?type "string" ?defValue '+sq(val)+' ?parseAsCEL "yes" ?parseAsNumber "yes"))\n'
    b+='cdfSaveCDF(c)\n)\n'
    return b


def create_tb(spec,folder):
    lib=spec['maestro']['lib'];cell=spec['maestro']['cell'];lp=spec['library_path']
    b=(Path(__file__).resolve().parent/'resources/connectivity.il').read_text()+'\nsimulator(\'spectre)\n'
    b+='unless(ddGetObj('+sq(lib)+') '+guard('ddCreateLib('+sq(lib)+' '+sq(lp)+')','create library failed')+')\n'
    b+='unless(equal(ddGetObj('+sq(lib)+')~>readPath '+sq(str(Path(lp).resolve()))+') error("Target library path mismatch"))\n'
    b+='when(ddGetObj('+sq(lib)+' '+sq(cell)+') error("Refusing existing TB cell"))\n'
    for width in sorted(set(r['width'] for r in spec.get('registers',[]))):b+=register_view(lib,width)
    b+='cv=dbOpenCellViewByType('+sq(lib)+' '+sq(cell)+' "schematic" "schematic" "w")\n'+guard('cv','TB create failed')
    expected=[];counter=0
    def instance(ml,mc,mv,name,nets,props):
        nonlocal b,counter
        x=(counter%5)*10;y=-(counter//5)*max(12,len(spec['ports'])*.6);counter+=1
        b+='master=dbOpenCellViewByType('+sq(ml)+' '+sq(mc)+' '+sq(mv)+' "" "r")\n'+guard('master','missing master '+mc)
        b+='i=dbCreateInst(cv master '+sq(name)+' list('+str(x)+' '+str(y)+') "R0")\n'+guard('i','instance create failed')
        for term,net in nets.items():
            net='gnd!' if net in ['0','gnd!'] else net
            b+='vcoStub(cv i '+sq(term)+' '+sq(net)+')\n';expected.append([name,term,net])
        for key,value in props.items():b+='dbReplaceProp(i '+sq(key)+' "string" '+sq(value)+')\n'
    nets={p['name']:p['net'] for p in spec['ports']}
    for p in spec.get('probes',[]):nets[p['dut_port']]=p['internal_net']
    dut=spec['dut'];instance(dut['lib'],dut['cell'],'symbol','DUT',nets,{})
    for src in spec.get('supplies',[])+spec.get('controls',[]):
        is_current=src.get('kind')=='current'
        instance('analogLib','isource' if is_current else 'vsource','symbol',src['name'],{'PLUS':src['positive'],'MINUS':src['negative']},{'srcType':'dc','idc' if is_current else 'vdc':src['value']})
    for r in spec.get('registers',[]):
        instance(lib,register_cell(r['width']),'symbol',r['name'],{'bits<'+str(r['width']-1)+':0>':','.join(reversed(r['members_lsb_first'])),'vdd':r['vdd'],'vss':r['vss']},{'WIDTH':r['width'],'DEC_CODE':r['code_variable'],'INVERT':r.get('invert',0)})
    for p in spec.get('probes',[]):
        instance('analogLib','iprobe' if p['kind']=='iprobe' else 'vdc','symbol',p['name'],{'PLUS':p['net'],'MINUS':p['internal_net']},{} if p['kind']=='iprobe' else {'vdc':'0'})
    b+='schCheck(cv)\n'+guard('dbSave(cv)','TB save failed')+'dbClose(cv)\n'
    b+='cv=dbOpenCellViewByType('+sq(lib)+' '+sq(cell)+' "schematic" "" "r")\no=outfile('+sq(Path(folder)/'connectivity.tsv')+')\nforeach(inst cv~>instances foreach(it inst~>instTerms fprintf(o "%s\\t%s\\t%s\\n" inst~>name it~>name it~>net~>name))) close(o) dbClose(cv)\n'
    b+='h=hdbOpen('+sq(lib)+' '+sq(cell)+' "config" "w")\n'+guard('h','config create failed')
    for call in ['hdbSetTopCellViewName(h '+sq(lib)+' '+sq(cell)+' "schematic")','hdbSetDefaultViewListString(h "spectre veriloga schematic")','hdbSetDefaultStopListString(h "spectre veriloga")','hdbSave(h)']:b+=guard(call,'config write failed')
    # Explicit occurrence binding honors dut.view without changing other leaves.
    b+='hdbClose(h)\n'
    b+='h=hdbOpen('+sq(lib)+' '+sq(cell)+' "config" "a")\n'
    b+=guard('hdbSetObjBindRule(h list(list('+sq(lib)+' '+sq(cell)+' "schematic" "DUT")) list(\'hdbcBindingRule list('+sq(dut['lib'])+' '+sq(dut['cell'])+' '+sq(dut['view'])+')))','DUT view binding failed')
    b+=guard('hdbSave(h)','bound config save failed')+'hdbClose(h)\n'
    return b,expected


def verify_connectivity(folder, expected):
    actual = [row.split('\t') for row in (Path(folder) / 'connectivity.tsv').read_text().splitlines()]
    for row in expected:
        if row not in actual:
            raise RuntimeError('connectivity mismatch: ' + repr(row))
    if len(actual) != len(expected):
        raise RuntimeError('unexpected connected terminal count')


def prepare_fixture(spec, folder):
    from .transaction import _target

    setup = _target(spec)
    if setup.parent.exists():
        raise FileExistsError('TB cell already exists')
    Path(spec['library_path']).parent.mkdir(parents=True, exist_ok=True)
    return create_tb(spec, folder)


def materialize_fixture(spec, extra, folder):
    from .native import execute
    from .spec import digest
    from .transaction import _save, _target

    body, expected = prepare_fixture(spec, folder)
    receipt = execute(body, folder/'native', spec['cds_lib'], spec['maestro']['lib'],
                      spec['library_path'], spec.get('runtime'), locked=True)
    verify_connectivity(folder, expected)
    cell = _target(spec).parent
    result = dict(schema='vco-tbgen.materialized.v1', status='fixture_ready',
                  completeness='L-b', spec=spec, spec_hash=digest(spec), plan=extra['plan'],
                  workspace=spec['workspace'], schematic_dir=str(cell/'schematic'),
                  config_dir=str(cell/'config'), setup_dir=None, receipt=receipt,
                  manifest_path=str(folder/'materialized.json'))
    _save(folder/'materialized.json', result)
    return result
