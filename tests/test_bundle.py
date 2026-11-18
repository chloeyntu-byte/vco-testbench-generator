import copy
import unittest
from vco_tbgen.bundle import analysis_bundle, install_bundle, bundle_errors
from vco_tbgen.output_templates import bundle_outputs
from vco_tbgen.native import validate_skill

class BundleTests(unittest.TestCase):
 def bundle(self, analyses=(), **kw):
  args=dict(frequency='1G',positive='OP',negative='/ON',offsets_hz=[10000.,23000.],isf_harmonic=3,hb_harmonics=5,sidebands=4)
  args.update(kw)
  return analysis_bundle(analyses,**args)
 def test_missing_set_and_exact_offsets(self):
  b=self.bundle();self.assertFalse(b['pending']);self.assertEqual(b['missing'],['hb','hbnoise','hbxf'])
  self.assertEqual([r['kind'] for r in b['analyses']],b['missing'])
  for r in b['analyses'][1:]:self.assertEqual(r['parameters']['values'],['10000.0','23000.0'])
 def test_alignment_is_pure_and_reports_every_difference(self):
  a=[dict(kind='hb',parameters=dict(fundfreqs=['900M'],maxharms=['2'],p='/OLD',n='/ON',oscic='lin',oscmethod='onetier',tstab='2u')),dict(kind='hbnoise',parameters=dict(maxsideband='6',p='/BAD',start='1M')),dict(kind='hbxf',parameters=dict(maxsideband='10',freqaxis='in'))]
  before=copy.deepcopy(a);b=self.bundle(a)
  self.assertEqual(a,before);self.assertEqual(b['shared']['sidebands'],10)
  self.assertEqual(b['shared']['solver']['oscmethod'],'onetier');self.assertEqual(b['shared']['solver']['tstab'],'2u')
  self.assertEqual(b['analyses'][0]['parameters']['maxharms'],['5'])
  self.assertIn('hbnoise/p',[v['field'] for v in b['changes']])
  for r in b['analyses'][1:]:self.assertEqual(r['parameters']['maxsideband'],'10')
 def test_unknown_and_multitone_require_input(self):
  for params in (dict(maxharms=['Nh']),dict(fundfreqs=['1G','2G'],maxharms=['5','5'])):
   self.assertTrue(self.bundle([dict(kind='hb',parameters=params)])['pending'])
  for kw in (dict(offsets_hz=[0]),dict(frequency=float('nan')),dict(positive='ON'),dict(isf_harmonic=True)):
   self.assertTrue(self.bundle(**kw)['pending'])
 def test_templates_and_required_contract(self):
  b=self.bundle();outputs=bundle_outputs(b,supplies=[dict(name='VDD_SRC',positive='VDD',negative='0')])
  for o in outputs:validate_skill(o['expression']);self.assertTrue(o['unit']);self.assertTrue(o['description'])
  pn=[o for o in outputs if 'HBNOISE_PN' in o['name']];self.assertEqual(len(pn),2)
  self.assertTrue(all('getData("out" ?result "hbnoise_pm")' in o['expression'] for o in pn))
  s=install_bundle(dict(analyses=[],hbxf_injection=dict(name='ISF_TB_INJECT',positive='DUT.D',negative='0',target_instance='DUT.M1'),outputs=[dict(name='CUSTOM',expression='1')]),b)
  self.assertEqual(len(s['analyses']),3);self.assertEqual(s['outputs'][0]['name'],'CUSTOM')
  self.assertIn(dict(name='ISF_HBXF_RAW_INJECTION',kind='waveform'),s['required']['outputs'])
 def test_singleton_native_extra_does_not_add_metric(self):
  b=self.bundle(offsets_hz=[1e4]);self.assertEqual(b['shared']['native_offsets_hz'],[1e4,2e4])
  self.assertEqual(len([o for o in bundle_outputs(b) if 'HBNOISE_PN' in o['name']]),1)

 def test_stale_shared_fields_and_weakened_outputs_rejected(self):
  s=install_bundle(dict(analyses=[]),self.bundle())
  self.assertEqual(bundle_errors(s),[])
  for mutation in ('shared','expression','required'):
   changed=copy.deepcopy(s)
   if mutation=='shared':changed['analysis_bundle']['shared']['sidebands']=1
   elif mutation=='expression':changed['outputs'][0]['expression']='1'
   else:changed['required']['outputs']=[]
   self.assertTrue(bundle_errors(changed),mutation)
 def test_explicit_solver_override_is_shared_and_unknown_fields_ask(self):
  b=self.bundle(solver_options=dict(oscmethod='onetier',tstab='300n'))
  self.assertEqual(b['shared']['solver']['tstab'],'300n');self.assertEqual(b['analyses'][0]['parameters']['oscmethod'],'onetier')
  self.assertTrue(self.bundle(solver_options=dict(unknown='x'))['pending'])

 def test_actual_conditions_drift_is_rejected_without_resealing(self):
  from vco_tbgen import validate
  from pathlib import Path
  import json
  tb=json.loads((Path(__file__).resolve().parents[1]/'examples/generic-request.json').read_text())
  tb.pop('completeness')  # Exercise the unlevelled bundle API.
  conditions=dict(temperature_c=tb['simulator_options']['temp'],variables=tb.get('variables',{}))
  b=self.bundle(conditions=conditions,initial_conditions=tb.get('initial_conditions',{}))
  tb=install_bundle(tb,b)
  self.assertEqual(validate(tb),[])
  for field,change in [('simulator_options',{'temp':'99'}),('initial_conditions',{'OUTP':0}),('variables',{'VDD':2.7}),('corners',[{'name':'changed'}]),('sweeps',[{'variable':'VDD','values':[1,2]}])]:
   mutated=copy.deepcopy(tb);mutated[field]=change
   self.assertTrue(any('analysis_bundle' in e for e in validate(mutated)),field)
  mutated=copy.deepcopy(tb);mutated['analysis_bundle']['shared']['conditions']['temperature_c']='99'
  self.assertTrue(bundle_errors(mutated))
 def test_current_injection_identity_units_and_stimulus(self):
  import tempfile
  from pathlib import Path
  from vco_tbgen.injection import write_stimulus,stimulus_path
  from vco_tbgen.native import test_setup
  injection=dict(name='ISF_TB_INJECT',positive='DUT.OUTP',negative='DUT.S',target_instance='DUT.M1')
  b=self.bundle();rows=bundle_outputs(b,supplies=[dict(name='VDD',positive='VDD',negative='0')],injection=injection)
  raw=[r for r in rows if 'HBXF' in r['name']]
  self.assertEqual(len(raw),1);self.assertEqual(raw[0]['unit'],'V/A')
  self.assertEqual(raw[0]['expression'],'getData("/ISF_TB_INJECT" ?result "hbxf")')
  with tempfile.TemporaryDirectory() as tmp:
   spec=dict(workspace=tmp,hbxf_injection=injection,mode='add_test_to_existing',maestro=dict(lib='L',cell='C',view='maestro',test='NEW',source_test='OLD'),analyses=[])
   write_stimulus(spec);write_stimulus(spec)
   self.assertIn('ISF_TB_INJECT (DUT.OUTP DUT.S) isource dc=0 type=dc',stimulus_path(spec).read_text())
   emitted=test_setup(spec);validate_skill(emitted)
   self.assertIn('append(tbgenStimuli list(',emitted)
   self.assertIn('maeGetEnvOption("NEW" ?option "stimulusFile"',emitted)
   stimulus_path(spec).write_text('wrong source')
   with self.assertRaises(FileExistsError):write_stimulus(spec)

 def test_native_gate_rejects_voltage_transfer_or_missing_isf_sideband(self):
  import tempfile
  from pathlib import Path
  from vco_tbgen.runner import verify_point
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'spectre.out').write_text('Spectre completes with 0 errors.')
   rdb=root/'history.rdb';rdb.write_text('owned fixture')
   name='ISF_HBXF_RAW_INJECTION'
   contract=dict(analyses=[dict(kind='hbxf',parameters={})],hbxf_injection=dict(name='ISF_TB_INJECT'),
       required=dict(analyses=['hbxf'],outputs=[dict(name=name,kind='waveform')],saves=[]))
   point=dict(psf_dir=tmp,native_status='done',rdb=str(rdb),analyses=['hbxf'],
       raw_samples=[dict(analysis='hbxf',x=1,real=1,imag=1,coordinates_native='harmonic -1')],
       output_waveforms={name:dict(curves=[dict(family=[['harmonic',h]],x_unit='Hz',y_unit='V/A',samples=[[1,1,1]]) for h in (-2,-1,0,1)])})
   self.assertEqual(verify_point(copy.deepcopy(point),['hbxf'],contract),[])
   for mutation in ('units','sideband'):
    changed=copy.deepcopy(point)
    if mutation=='units':changed['output_waveforms'][name]['curves'][0]['y_unit']='V/V'
    else:changed['output_waveforms'][name]['curves'].pop(0)
    self.assertTrue(verify_point(changed,['hbxf'],contract),mutation)

 def test_b_summary_cannot_override_inherited_temperature(self):
  b=self.bundle(conditions=dict(temperature_c='27',inherited=dict(temperature_c='27')))
  tb=install_bundle(dict(mode='add_test_to_existing',analyses=[]),b)
  self.assertEqual(bundle_errors(tb),[])
  tb['analysis_bundle']['shared']['conditions']['temperature_c']='99'
  self.assertTrue(bundle_errors(tb))
