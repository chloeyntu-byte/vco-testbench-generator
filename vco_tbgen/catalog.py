"""Read-only OA catalog and port interpretation."""
import os
import re
from pathlib import Path
from . import native

RUN_ROOT=Path(os.environ['TBGEN_RUN_ROOT']) if 'TBGEN_RUN_ROOT' in os.environ else Path.home() / '.cache' / 'vco-tbgen'

def _read_worker(body,cds_lib,kind,workspace):
    folder=native.new_folder(workspace or RUN_ROOT,kind)
    return folder,native.execute(body(folder),folder,cds_lib,'TBGEN_READER')

def browse_libraries(cds_lib, *, workspace=None):
    def body(f):return 'o=outfile('+native.sq(f/'catalog.tsv')+')\nforeach(lib ddGetLibList() fprintf(o "LIB\\t%s\\t%s\\n" lib~>name lib~>readPath) foreach(cell lib~>cells foreach(view cell~>views fprintf(o "VIEW\\t%s\\t%s\\t%s\\n" lib~>name cell~>name view~>name)))) close(o)\n'
    f,receipt=_read_worker(body,cds_lib,'browse',workspace);libs={}
    for line in (f/'catalog.tsv').read_text().splitlines():
        p=line.split('\t')
        if p[0]=='LIB':libs[p[1]]={'name':p[1],'path':p[2],'cells':{}}
        elif p[0]=='VIEW':libs[p[1]]['cells'].setdefault(p[2],[]).append(p[3])
    return {'schema':'vco-tbgen.catalog.v1','cds_lib':str(Path(cds_lib).resolve()),'libraries':list(libs.values()),'evidence':receipt}

def describe_cell(lcv,cds_lib, *, workspace=None):
    if not all(isinstance(lcv.get(k),str) and lcv[k] for k in ['lib','cell','view']):raise ValueError('explicit lib/cell/view required')
    def body(f):
        args=' '.join(native.sq(lcv[k]) for k in ['lib','cell','view'])
        return 'cv=dbOpenCellViewByType('+args+' "" "r")\nunless(cv error("cell view unavailable"))\no=outfile('+native.sq(f/'ports.tsv')+')\nforeach(tm cv~>terminals fprintf(o "%s\\t%s\\n" tm~>name tm~>direction)) close(o) dbClose(cv)\n'
    f,receipt=_read_worker(body,cds_lib,'describe',workspace)
    ports=[{'name':name,'direction':direction,'members':expand_bus(name)} for name,direction in (l.split('\t') for l in (f/'ports.tsv').read_text().splitlines())]
    return {'schema':'vco-tbgen.cell.v1','lcv':lcv,'ports':ports,'evidence':receipt}


def expand_bus(name):
    m=re.fullmatch(r'(.*)([<\[])(\d+):(\d+)[>\]]',name)
    if not m:return [name]
    base,op,a,b=m.groups();a,b=int(a),int(b)
    return [f'{base}{op}{i}{">" if op=="<" else "]"}' for i in range(a,b+(1 if b>=a else -1),1 if b>=a else -1)]


def classify_ports(descriptor):
    rows=[];groups={}
    for p in descriptor.get('ports',[]):
        name=p['name'];n=name.upper().rstrip('!');role='unknown'
        if re.fullmatch(r'(VDD|VDDA|VDDD|AVDD|DVDD|VCC)(_[A-Z0-9]+)?',n):role='supply'
        elif re.fullmatch(r'(VSS|VSSA|VSSD|AVSS|DVSS|GND|0)(_[A-Z0-9]+)?',n):role='ground'
        elif re.fullmatch(r'(OUTP|OP|VOP|.*_P|.*\+)',n):role='output_p'
        elif re.fullmatch(r'(OUTN|ON|VON|.*_N|.*-)',n):role='output_n'
        elif re.match(r'^(VBIAS|IBIAS|VDC|VB$|BIAS|VCM|VTUNE|VCTRL)',n):role='bias'
        elif re.fullmatch(r'(EN|ENABLE|RESET|MODE|SEL|SW)',n) and p.get('direction')=='input':role='control'
        elif len(expand_bus(name))>1:role='register'
        m=re.fullmatch(r'(.*?)(?:_?[Bb]|_?[Cc][Oo][Dd][Ee])(\d+)',name)
        if m:groups.setdefault(m.group(1),[]).append((int(m.group(2)),name));role='register'
        rows.append(dict(p,suggested_role=role,requires_confirmation=True))
    registers=[]
    for key,members in groups.items():
        bits=sorted(members)
        registers.append({'name':key,'members_lsb_first':[v for _,v in bits],'contiguous':[i for i,_ in bits]==list(range(len(bits))),'requires_confirmation':True})
    return {'schema':'vco-tbgen.classification.v1','ports':rows,'registers':registers,'ask':[p['name'] for p in rows]}




def dut_only(dut, cds_lib, *, workspace, runtime=None):
    """L-a handoff for an exported DUT. Read back both views in one batch."""
    for key in ('lib', 'cell', 'view'):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', dut.get(key, '')):
            raise ValueError('Explicit DUT lib/cell/view identifiers are required')
    folder = native.new_folder(workspace, 'dut-only')
    interface = folder / 'interface.tsv'
    body = 'o=outfile('+native.sq(interface)+')\n'
    for view in ('schematic', 'symbol'):
        args = ' '.join(native.sq(value) for value in (dut['lib'], dut['cell'], view))
        body += 'cv=dbOpenCellViewByType('+args+' "" "r")\n'
        body += native.guard('cv', 'Exported DUT '+view+' is unavailable')
        body += 'fprintf(o "VIEW %s\\n" '+native.sq(view)+')\n'
        body += 'foreach(tm cv~>terminals fprintf(o "%s\\t%s\\t%s\\n" '+native.sq(view)+' tm~>name tm~>direction)) dbClose(cv)\n'
    receipt = native.execute(body+'close(o)\n', folder/'native', cds_lib, dut['lib'], runtime=runtime)
    rows = [line.split('\t') for line in interface.read_text().splitlines() if not line.startswith('VIEW ')]
    ports = {}
    for view in ('schematic', 'symbol'):
        ports[view] = sorted((name, direction) for kind, name, direction in rows if kind == view)
    if ports['schematic'] != ports['symbol']:
        raise RuntimeError('DUT schematic and symbol ports differ')
    return dict(schema='vco-tbgen.dut.v1', status='dut_ready', completeness='L-a', dut=dut,
                views=['schematic', 'symbol'],
                ports=[dict(name=name, direction=direction) for name, direction in ports['schematic']],
                receipt=receipt, interface_path=str(interface))
