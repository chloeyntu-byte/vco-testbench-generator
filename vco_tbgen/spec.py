"""Dependency-free validation of the shipped draft-07 schema and TB semantics."""
import hashlib
import json
import math
import re
from pathlib import Path
from .catalog import classify_ports, expand_bus

ROOT = Path(__file__).resolve().parents[1]

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()

def validate(spec):
    schema=json.loads((Path(__file__).resolve().parent/'resources/tb-spec-v1.schema.json').read_text())
    errors=[]
    def check(value,node,path):
        if '$ref' in node:
            node=schema['definitions'][node['$ref'].rsplit('/',1)[1]]
        kinds=node.get('type',[]);kinds=[kinds] if isinstance(kinds,str) else kinds
        tests={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'number':isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value),'integer':isinstance(value,int) and not isinstance(value,bool),'boolean':isinstance(value,bool),'null':value is None}
        if kinds and not any(tests[k] for k in kinds): errors.append(path+': invalid type');return
        if 'const' in node and value!=node['const']:errors.append(path+': unsupported version')
        if 'enum' in node and value not in node['enum']:errors.append(path+': invalid choice')
        if isinstance(value,str) and len(value)<node.get('minLength',0):errors.append(path+': empty')
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            if value<node.get('minimum',-math.inf) or value>node.get('maximum',math.inf):errors.append(path+': out of range')
        if isinstance(value,dict):
            for key in node.get('required',[]):
                if key not in value:errors.append(path+'/'+key+': required')
            for key,val in value.items():
                rule=node.get('properties',{}).get(key,node.get('additionalProperties',True))
                if rule is False:errors.append(path+'/'+key+': unknown field')
                elif isinstance(rule,dict):check(val,rule,path+'/'+key)
        if isinstance(value,list):
            for i,val in enumerate(value):check(val,node.get('items',{}),path+'/'+str(i))
    check(spec,schema,'')
    if errors:return errors
    for key in ['workspace','cds_lib','library_path']:
        if not Path(spec[key]).is_absolute():errors.append('/'+key+': absolute path required')
    for row in [spec['dut'],spec['maestro']]:
        for k in ['lib','cell','view']:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',row[k]):errors.append('/'+k+': unsafe OA identifier')
    names=[p['name'] for p in spec['ports']]
    if len(names)!=len(set(names)):errors.append('/ports: duplicate name')
    for key in ['supplies','controls','registers','probes','outputs']:
        ns=[r['name'] for r in spec.get(key,[])]
        if len(ns)!=len(set(ns)):errors.append('/'+key+': duplicate name')
    instance_names=['DUT']+[r['name'] for k in ['supplies','controls','registers','probes'] for r in spec.get(k,[])]
    if len(instance_names)!=len(set(instance_names)):errors.append('duplicate instance names across categories')
    drive_nets=[v['positive'] for category in ['supplies','controls'] for v in spec.get(category,[])]+[m for r in spec.get('registers',[]) for m in r['members_lsb_first']]
    if len(drive_nets)!=len(set(drive_nets)):errors.append('/drivers: multiple excitations drive the same net')
    probe_ports=[p['dut_port'] for p in spec.get('probes',[])]
    if len(probe_ports)!=len(set(probe_ports)):errors.append('/probes: repeated DUT port requires an explicit composed fixture')
    variables=spec.get('variables',{})
    positive={p['net'] for p in spec['ports'] if p['role']=='output_p'}
    negative={p['net'] for p in spec['ports'] if p['role']=='output_n'}
    if positive & negative:errors.append('/ports: positive and negative output nets must differ')
    for sweep in spec.get('sweeps',[]):
        if not sweep['values']:errors.append('/sweeps: empty values')
    for r in spec.get('registers',[]):
        if len(r['members_lsb_first'])!=r['width'] or len(set(r['members_lsb_first']))!=r['width']:errors.append('/registers/'+r['name']+': width/member mismatch')
        codes=[variables.get(r['code_variable'])]
        for sweep in spec.get('sweeps',[]):
            if sweep['variable']==r['code_variable']:codes+=sweep['values']
        for corner in spec.get('corners',[]):
            if r['code_variable'] in corner.get('variables',{}):codes.append(corner['variables'][r['code_variable']])
        if any(not isinstance(c,int) or isinstance(c,bool) or not 0<=c<2**r['width'] for c in codes):errors.append('/registers/'+r['name']+': code must be an integer in range')
    for p in spec.get('probes',[]):
        if p['dut_port'] not in names:errors.append('/probes: unknown DUT port')
        else:
            bound=next(port['net'] for port in spec['ports'] if port['name']==p['dut_port'])
            normalize=lambda n:'0' if n=='gnd!' else n
            if normalize(p['net'])!=normalize(bound):errors.append('/probes: outer net must match the explicit port binding')
        if p['net']==p['internal_net']:errors.append('/probes: shorted probe')
    injection=spec.get('hbxf_injection')
    if injection:
        name = injection['name']
        reserved = {name, name+'_PROBE', name+'_RETURN'} if injection.get('probe') else {name}
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or reserved.intersection(instance_names):
            errors.append('/hbxf_injection/name: invalid or colliding source name')
        for key in ('positive','negative','target_instance'):
            if not re.fullmatch(r'[A-Za-z0-9_!<>]+(?:\.[A-Za-z0-9_!<>]+)*',injection[key]):
                errors.append('/hbxf_injection/'+key+': explicit Spectre hierarchy required')
        if injection['positive']==injection['negative']:errors.append('/hbxf_injection: shorted injection')
        if 'drain_terminal' in injection and not re.fullmatch(r'[1-9][0-9]*', injection['drain_terminal']):
            errors.append('/hbxf_injection/drain_terminal: a positive Spectre terminal number is required')
    if spec.get('analysis_bundle'):
        from .isf import bundle_errors
        errors.extend(bundle_errors(spec))
    level = spec.get('completeness')
    kinds = {a['kind'] for a in spec['analyses'] if a.get('enabled', True)}
    if level == 'L-b':
        if spec['mode'] != 'create_new' or kinds or injection or spec.get('analysis_bundle'):
            errors.append('/completeness: L-b creates a new fixture without an analysis or injection')
    elif level == 'L-c':
        if kinds != {'hb', 'hbnoise'} or injection or spec.get('analysis_bundle'):
            errors.append('/completeness: L-c requires HB and HBNOISE without ISF')
        required = spec.get('required', {})
        if set(required.get('analyses', [])) != {'hb', 'hbnoise'}:
            errors.append('/required/analyses: L-c requires qualified HB and HBNOISE')
        names = {row['name'] for row in required.get('outputs', []) if row['kind'] == 'scalar'}
        outputs = {row['name'] for row in spec.get('outputs', []) if row.get('plot', True)}
        if not (names <= outputs and 'VCO_HB_F0_Hz' in names
                and any(name.startswith('VCO_HBNOISE_PN_') for name in names)
                and any(name.endswith('_PDC_W') for name in names)):
            errors.append('/required/outputs: L-c requires enabled f0, phase noise and supply power')
    elif level == 'L-d' and (not injection or not spec.get('analysis_bundle')):
        errors.append('/completeness: L-d requires an ISF bundle with a selected D-S injection')
    unsupported = {a['kind'] for a in spec['analyses']} & {'pss', 'pnoise', 'tran'}
    if unsupported:
        errors.append('/analyses: authoring '+', '.join(sorted(unsupported))+' is unsupported; inherited tests are preserved')
    if spec['mode']=='add_test_to_existing' and not spec['maestro'].get('source_test'):errors.append('/maestro/source_test: required for add mode')
    return errors


def plan(spec):
    errors=validate(spec)
    operations=[{'op':'ask','field':'validation','reason':e} for e in errors]
    if not errors:
        existing=spec['mode']=='add_test_to_existing'
        operations+=[{'op':'keep' if existing else 'add','field':k,'reason':'preserve native setup' if existing else 'explicit spec'} for k in ['dut','ports','variables','corners','sweeps']]
        if spec.get('completeness') == 'L-b':
            operations.append({'op':'add','field':'schematic/config','reason':'create fixture'})
        else:
            operations.append({'op':'add','field':'maestro/test','reason':'copy source test' if existing else 'create new test'})
        for port in spec['ports']:
            if port['role']=='unknown':operations.append({'op':'ask','field':'ports/'+port['name'],'reason':'role unresolved'})
        if not existing:
            driven=[s['positive'] for k in ['supplies','controls'] for s in spec.get(k,[])]+[m for r in spec.get('registers',[]) for m in r['members_lsb_first']]
            for p in spec['ports']:
                if p['role'] in ['supply','bias','control','register'] and p['net'] not in driven:operations.append({'op':'ask','field':'ports/'+p['name'],'reason':'missing driver'})
        for a in spec['analyses']:
            if a['kind']=='hb' and a.get('enabled',True):
                for required in ['fundfreqs','maxharms']:
                    if not a['parameters'].get(required):operations.append({'op':'ask','field':'analyses/hb/'+required,'reason':'native emitted frequency/harmonics required'})
        if existing:
            for k in ['variables','corners','sweeps','models','simulator_options','initial_conditions','supplies','controls','registers','probes']:
                if spec.get(k):operations.append({'op':'ask','field':k,'reason':'add mode inherits source settings; overrides unsupported'})
    return {'schema':'vco-tbgen.plan.v1','spec_hash':digest(spec),'status':'needs_input' if any(o['op']=='ask' for o in operations) else 'ready','operations':operations}
