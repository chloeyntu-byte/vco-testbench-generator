"""Read-only adapter for Design Lab projects and exported DUT metadata."""
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from .catalog import classify_ports
from .oscillator import lc_hb_defaults


def from_design_lab(generated_dir,*,dut,workspace,cds_lib,library_path,maestro,design_lab_root=None, completeness=None):
    """Consume generated manifest/graph/binding/registers plus an exported DUT LCV.

    A project input is generated into this owned workspace using an explicitly
    selected Design Lab checkout. The supplied DUT must match that project.
    """
    if completeness not in (None, 'L-b', 'L-c'):
        raise ValueError('Design Lab fixture spec accepts L-b or L-c. Use the DUT export for L-a and ISF Explorer for L-d.')
    project=generated_dir if isinstance(generated_dir,dict) else None
    generated=Path(generated_dir).resolve() if project is None else None
    if project is not None or generated.is_file():
        if project is None:project=json.loads(generated.read_text())
        root=design_lab_root or os.environ.get('VCO_DESIGN_LAB_ROOT')
        if not root:raise ValueError('project input requires design_lab_root or VCO_DESIGN_LAB_ROOT')
        generated=Path(workspace).resolve()/('design-lab-source_'+uuid.uuid4().hex[:12])
        generated.parent.mkdir(parents=True,exist_ok=True)
        code='import json,sys;sys.path.insert(0,sys.argv[1]);from vco_studio.generator import generate;generate(json.load(sys.stdin),sys.argv[2])'
        subprocess.run([sys.executable,'-B','-c',code,str(Path(root).resolve()),str(generated)],input=json.dumps(project),text=True,check=True,cwd=generated.parent,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    files={name:json.loads((generated/name).read_text()) for name in ['manifest.json','graph.json','binding.json','registers.json']}
    graph=files['graph.json'];params=graph.get('parameters',{});variables={'VDD':params.get('vdd'),'VDC':params.get('vdc')}
    if variables['VDD'] is None or variables['VDC'] is None:raise ValueError('Design Lab supply/bias values missing')
    classification=classify_ports({'ports':graph['ports']})
    ports=[{'name':p['name'],'net':'0' if p['suggested_role']=='ground' else p['name'],'role':p['suggested_role'],'direction':p.get('direction','inputOutput')} for p in classification['ports']]
    # VDDB is an optional Design Lab graph interface. Its value comes from
    # the generated binding/graph, independent of the process name.
    supplies = [dict(name='VDD_SRC', positive='VDD', negative='0', value='VDD', domain='core')]
    bank_supply = 'VDD'
    for port in ports:
        if port['name'] == 'VDDB':
            if params.get('vdd_bank') is None:
                raise ValueError('Design Lab VDDB port requires the generated vdd_bank value')
            port['role'] = 'supply'
            variables['VDDB'] = params['vdd_bank']
            supplies.append(dict(name='VDDB_SRC', positive='VDDB', negative='0', value='VDDB', domain='bank'))
            bank_supply = 'VDDB'
    registers=[]
    for r in files['registers.json']:
        name=r['name'];variable=name.upper()+'_CODE';variables[variable]=r['default']
        registers.append({'name':'REG_'+name,'width':r['bits'],'members_lsb_first':list(reversed(r['pins_msb_first'])),'code_variable':variable,'vdd':bank_supply,'vss':'0','implementation':'veriloga','invert':0})
        for p in ports:
            if p['name'] in r['pins_msb_first']:p['role']='register'
    frequency=params.get('frequency_guess_ghz')
    if frequency is None and completeness != 'L-b':raise ValueError('Design Lab frequency guess missing')
    hashes={name:hashlib.sha256((generated/name).read_bytes()).hexdigest() for name in files}
    spec = {'schema':'vco-tbgen.spec.v1','mode':'create_new','workspace':str(Path(workspace).resolve()),'cds_lib':str(Path(cds_lib).resolve()),'library_path':str(Path(library_path).resolve()),'dut':dut,'ports':ports,
    'supplies':supplies,
    'controls':[{'name':'VBIAS_SRC','positive':'VDC','negative':'0','value':'VDC','kind':'voltage'}],
    'registers':registers,'variables':variables,'models':files['binding.json']['model_includes'],
    'analyses':[],
    'outputs':[{'name':'VDD_VALUE','expression':'VAR("VDD")'}],
    'saves':[{'name':'/OUTP','kind':'net'},{'name':'/OUTN','kind':'net'}]+[save for row in supplies for save in (dict(name='/'+row['positive'],kind='net'), dict(name='/'+row['name']+'/PLUS',kind='terminal'))],
    'probes':[],'corners':[],'sweeps':[],'simulator_options':{'temp':str(params.get('temp_c',27)),'reltol':'1e-4'},
    'initial_conditions':{'OUTP':variables['VDD']+.0005,'OUTN':variables['VDD']-.0005},'maestro':maestro,
    'source':{'kind':'design_lab','generated_dir':str(generated),'manifest':files['manifest.json'],'hashes':hashes,'qualification':'generated_not_simulation_qualified'}}

    if completeness == 'L-b':
        spec['completeness'] = completeness
        if frequency is not None:
            spec['source']['frequency_guess_hz'] = float(frequency)*1e9
        return spec
    if completeness == 'L-c':
        from .oscillator import install_oscillator
        return install_oscillator(spec, frequency=str(frequency)+'G', positive='/OUTP', negative='/OUTN')

    # Compatibility for callers of the original factory without a level.
    from .isf import analysis_bundle, install_bundle
    bundle=analysis_bundle(spec['analyses'],frequency=str(frequency)+'G',positive='/OUTP',negative='/OUTN',offsets_hz=[10000.],sidebands=15,conditions=dict(temperature_c=params.get('temp_c',27),variables=variables),initial_conditions=spec['initial_conditions'])
    return install_bundle(spec,bundle)
