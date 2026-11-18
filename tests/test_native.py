import json
import os
from pathlib import Path
import unittest
import uuid
from vco_tbgen import browse_libraries,describe_cell,materialize,plan,run,results

def create_spec(prefix):
    spec = json.loads(Path(os.environ['TBGEN_NATIVE_SPEC']).read_text())
    spec['maestro']['cell'] = prefix + '_' + uuid.uuid4().hex[:8]
    return spec


def grid_spec(prefix):
    spec = create_spec(prefix)
    for field in ('completeness', 'analysis_bundle', 'required', 'hbxf_injection'):
        spec.pop(field, None)
    register = spec['registers'][0]
    code_name = register['code_variable']
    vdd_name = spec['supplies'][0]['value']
    vdd = float(spec['variables'][vdd_name])
    codes = [0, 1]
    supply_values = [vdd, 0.95*vdd]
    spec['analyses'] = [{'kind': 'dc', 'parameters': {}}]
    spec['outputs'] = [dict(name='GRID_CODE', expression=f'VAR("{code_name}")')]
    spec['sweeps'] = [dict(variable=code_name, values=codes, scope='test')]
    spec['corners'] = [dict(name=name, enabled=True, variables={vdd_name: value})
                       for name, value in zip(('NOMINAL', 'LOWER_SUPPLY'), supply_values)]
    expected = {(corner['name'], code) for corner in spec['corners'] for code in codes}
    return spec, code_name, expected


@unittest.skipUnless(os.environ.get('TBGEN_NATIVE')=='1','native integration requires TBGEN_NATIVE=1')
class NativeIntegration(unittest.TestCase):
 def test_browser_and_ports(self):
  s=json.loads(Path(os.environ['TBGEN_NATIVE_SPEC']).read_text())
  catalog=browse_libraries(s['cds_lib']);self.assertTrue(catalog['libraries'])
  desc=describe_cell(dict(s['dut'],view='symbol'),s['cds_lib']);self.assertTrue(desc['ports'])
 def test_end_to_end(self):
  s=create_spec('NativeTest')
  m=materialize(s,plan(s));self.assertEqual(m['status'],'prepared',m)
  r=run(m);self.assertEqual(r['status'],'completed',r)
  self.assertTrue(results(r)['points'])

 def test_existing_maestro_and_history_preservation(self):
  from vco_tbgen.api import setup_snapshot
  s=create_spec('ExistingTest')
  vdd_name=s['supplies'][0]['value']
  expected_vdd=s['variables'][vdd_name]
  s.setdefault('outputs', []).append(dict(name='SOURCE_SUPPLY_VALUE', expression=f'VAR("{vdd_name}")'))
  base=materialize(s,plan(s));self.assertEqual(base['status'],'prepared',base)
  first=run(base);self.assertEqual(first['status'],'completed',first)
  before=setup_snapshot(base['setup_dir'])
  original=s['maestro']['test'];s['mode']='add_test_to_existing'
  s['maestro'].update(test='HB_ISF_ADDED',source_test=original)
  for k in ['variables','corners','sweeps','models','simulator_options','initial_conditions','supplies','controls','registers','probes']:s.pop(k,None)
  for key in ('completeness', 'analysis_bundle', 'required', 'hbxf_injection'):s.pop(key,None)
  s['analyses']=[a for a in s['analyses'] if a['kind']=='hbxf']
  s['ports']=[];s['saves']=[]
  s['outputs']=[{'name':'B_CHECK','expression':f'VAR("{vdd_name}")'}]
  added=materialize(s,plan(s));self.assertEqual(added['status'],'prepared',added)
  second=run(added);self.assertEqual(second['status'],'completed',second)
  after=setup_snapshot(base['setup_dir'])
  for filename in ['maestro.sdb','active.state']:self.assertEqual(before[filename][original],after[filename][original])
  self.assertEqual([p['test'] for p in second['points']],['HB_ISF_ADDED'])
  self.assertEqual(second['points'][0]['outputs']['B_CHECK']['value'],expected_vdd)
  point=second['points'][0]
  self.assertGreater(point['carrier']['magnitude_v'],1e-5)
  self.assertTrue({'hb_fd','hbnoise_pm','hbxf'}.issubset(point['analyses']))
  self.assertTrue({'hb_fd','hbnoise_pm','hbxf'}.issubset({r['analysis'] for r in point['raw_samples']}))
  self.assertIn('SOURCE_SUPPLY_VALUE',point['outputs'])

 def test_corner_and_discrete_sweep(self):
  s,code_name,expected=grid_spec('CornerTest')
  m=materialize(s,plan(s));self.assertEqual(m['status'],'prepared',m)
  r=run(m);self.assertEqual(r['status'],'completed',r)
  self.assertEqual(r['coverage'],{'expected':4,'actual':4,'matched':4,'missing':[],'unexpected':[]})
  self.assertEqual({(p['corner'],p['variables'][code_name]) for p in r['points']},expected)

@unittest.skipUnless(os.environ.get('TBGEN_NATIVE')=='1','native integration requires TBGEN_NATIVE=1')
class InheritedGrid(unittest.TestCase):
 def test_b_inherits_corner_and_sweep(self):
  from vco_tbgen.api import setup_snapshot
  s,code_name,expected=grid_spec('InheritedGrid')
  m=materialize(s,plan(s));self.assertEqual(m['status'],'prepared',m)
  before=setup_snapshot(m['setup_dir']);original=s['maestro']['test']
  s['mode']='add_test_to_existing';s['maestro'].update(test='DC_ADDED',source_test=original)
  for k in ['variables','corners','sweeps','models','simulator_options','initial_conditions','supplies','controls','registers','probes']:s.pop(k,None)
  s['analyses']=[];s['ports']=[];s['saves']=[]
  s['outputs']=[{'name':'B_CODE','expression':f'VAR("{code_name}")'}]
  added=materialize(s,plan(s));self.assertEqual(added['status'],'prepared',added)
  r=run(added);self.assertEqual(r['status'],'completed',r)
  self.assertEqual(r['coverage'],{'expected':4,'actual':4,'matched':4,'missing':[],'unexpected':[]})
  self.assertEqual({(p['corner'],p['variables'][code_name]) for p in r['points']},expected)
  for p in r['points']:self.assertEqual(p['outputs']['B_CODE']['value'],p['variables'][code_name])
  after=setup_snapshot(m['setup_dir'])
  for filename in ['maestro.sdb','active.state']:self.assertEqual(before[filename][original],after[filename][original])
