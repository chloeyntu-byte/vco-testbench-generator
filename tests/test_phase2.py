"""Required contracts and caller-owned session safety, without Cadence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_result_qualification import saved_setup,fixture,CONTRACT
from test_contract import sample
from vco_tbgen.effective import literal,native_flag,effective_spec
from vco_tbgen.runner import verify_point,read_points,steady_state_reading
from vco_tbgen.session import plan_session_add,materialize_session_add,disk_revision,logical_snapshot,_main
from vco_tbgen.native import validate_skill
from vco_tbgen.spec import validate


class RequiredContract(unittest.TestCase):
 def test_zero_error_is_not_steady_state_detection(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'spectre.out';p.write_text('Spectre completes with 0 errors.\n')
   self.assertEqual(steady_state_reading(p)['status'],'unverified')
   p.write_text('WARNING (SPCRTRF-15311): Steady-state has not been detected after 60 ns.\nSpectre completes with 0 errors.\n')
   self.assertEqual(steady_state_reading(p)['warning'],'HB_STEADY_STATE_NOT_DETECTED')
   self.assertFalse(steady_state_reading(p)['detected'])
 def test_two_tier_requires_complete_converged_residuals(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'spectre.out'
   text=("Harmonic Balance Steady State Analysis `hb'\n"
         "Resd Norm=4.14e-3 at node OUTP\n"
         "-> Outer iter= 4: Probe Current=(1e-9,1e-9), norm =2.25e-5\n"
         "-> Outer iter= 4: Frequency=1.317e10 Hz, norm=8.76e-3\n"
         "-> Outer iter= 4: ProbeVol=(0.74,0), norm=1.35e-2, Damping factor=1\n"
         "Fundamental frequency is 13.1732 GHz.\n"
         "Total time required for hb analysis `hb': CPU = 4 s.\n"
         "Spectre completes with 0 errors.\n")
   p.write_text(text);r=steady_state_reading(p)
   self.assertTrue(r['detected']);self.assertFalse(r['transient_detected'])
   self.assertEqual(r['basis'],'two_tier_hb_residuals')
   for bad in [text.replace('norm=1.35e-2','norm=1.35'),text.replace('norm=8.76e-3','norm=nan'),
               text.replace('Probe Current=','Missing='),text.replace('0 errors','1 error'),
               text.replace('Total time required for hb analysis','Incomplete HB analysis'),
               text+'Steady-state has not been detected after 60 ns.\n']:
    p.write_text(bad);self.assertFalse(steady_state_reading(p)['detected'])
 def test_lc_defaults_are_explicit_and_do_not_rewrite_b(self):
  from vco_tbgen import lc_hb_defaults
  settings=lc_hb_defaults('9G')
  self.assertEqual(settings['oscmethod'],'twotier');self.assertEqual(settings['pinnode'],'/OUTP')
  self.assertEqual(settings['pinnodeminus'],'/OUTN');self.assertEqual(settings['oscic'],'lin')
  self.assertNotIn('tstab',settings)
  for invalid in ['0','-1G','nan']:
   with self.assertRaises(ValueError):lc_hb_defaults(invalid)
  s=sample();s['mode']='add_test_to_existing';s['maestro']['source_test']='BASE'
  for k in ['variables','corners','sweeps','models','simulator_options','initial_conditions','supplies','controls','registers','probes']:s.pop(k,None)
  s['analyses']=[]
  from vco_tbgen.native import test_setup
  self.assertNotIn('twotier',test_setup(s));self.assertNotIn('pinnode',test_setup(s))
 def test_native_flags_are_strict(self):
  for text in ['',None,'nil','()']:self.assertFalse(native_flag(text))
  for text in ['t','(t)']:self.assertTrue(native_flag(text))
  for text in ['yes','1','(1)','(nil)','t nil','false']:
   with self.subTest(text=text),self.assertRaises(ValueError):native_flag(text)
  for text in ['', '(',')','t nil']:
   with self.assertRaises(ValueError):literal(text)
 def test_empty_native_fields_and_disabled_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   saved_setup(d);p=Path(d)/'active.state';s=p.read_text().replace('<field Name="enable">(t)</field>','<field Name="enable"></field>',1)
   s=s.replace('<field Name="expression">VAR("VDD")</field>','<field Name="expression"></field>').replace('<field Name="signal">"/P"</field>','<field Name="signal"></field>');p.write_text(s)
   e=effective_spec({'mode':'add_test_to_existing','maestro':{'test':'COPY'},'analyses':[]},d)
   self.assertEqual(e['outputs'],[]);self.assertEqual(e['saves'],[])
   self.assertNotIn('hb',[a['kind'] for a in e['analyses']]);self.assertFalse(e['preserved']['analyses'][0]['enabled'])
 def test_global_overrides_local_unless_disabled(self):
  with tempfile.TemporaryDirectory() as d:
   saved_setup(d);p=Path(d)/'maestro.sdb';s=p.read_text().replace('<var>CODE<value>10 11</value>','<var>VDD<value>0.8</value>');p.write_text(s)
   spec={'mode':'add_test_to_existing','maestro':{'test':'COPY'},'analyses':[]}
   self.assertEqual(effective_spec(spec,d)['variables']['VDD'],'1.8')
   p.write_text(s.replace('<var>VDD<value>1.8</value>','<var>VDD<value>1.8</value><dependentTests><dependentTest enabled="0">COPY</dependentTest></dependentTests>'))
   self.assertEqual(effective_spec(spec,d)['variables']['VDD'],'0.8')
 def test_old_noise_and_expression_do_not_fail_required(self):
  with tempfile.TemporaryDirectory() as d:
   p=fixture(d);p['analyses'].append('noise');p['outputs']['OLD']={'type':'expr','value':'wave'}
   c=copy.deepcopy(CONTRACT);c['analyses'].append({'kind':'noise','parameters':{}});c['outputs'].append({'name':'OLD','expression':'missing()'})
   c['required']={'schema':'vco-tbgen.required.v1','analyses':['hb'],'outputs':[{'name':'VDD','kind':'scalar'}],'saves':[]}
   self.assertEqual(verify_point(p,['hb'],c),[])
   self.assertEqual(p['output_qualification']['OLD']['status'],'unverified')
   self.assertIn({'name':'noise','finite_data':False},p['preserved_results'])
 def test_required_waveform_is_complete_complex_and_finite(self):
  with tempfile.TemporaryDirectory() as d:
   p=fixture(d);c=copy.deepcopy(CONTRACT);c['required']={'schema':'vco-tbgen.required.v1','analyses':[],'outputs':[{'name':'W','kind':'waveform'}],'saves':[]}
   self.assertTrue(verify_point(p,[],c))
   curve={'x_unit':'Hz','y_unit':'V','coordinates_native':'(("harmonic" 1))','samples':[[1.,2.,3.],[2.,4.,5.]]}
   p['output_waveforms']={'W':{'curves':[curve]}};self.assertEqual(verify_point(p,[],c),[])
   for value in [None,float('nan'),float('inf')]:
    curve['samples'][1][2]=value;self.assertTrue(verify_point(p,[],c))
   curve['samples'][1][2]=5.;curve['x_unit']=None;self.assertTrue(verify_point(p,[],c))
 def test_required_save_checks_later_samples(self):
  with tempfile.TemporaryDirectory() as d:
   p=fixture(d);c=copy.deepcopy(CONTRACT);c['required']={'schema':'vco-tbgen.required.v1','analyses':[],'outputs':[],'saves':['/P']}
   curve={'x_unit':'Hz','y_unit':'V','coordinates_native':'nil','samples':[[1.,2.,3.],[2.,4.,5.]]}
   p['output_waveforms']={'__save__/P':{'curves':[curve]}};self.assertEqual(verify_point(p,[],c),[])
   curve['samples'].append([3.,None,0.]);self.assertTrue(verify_point(p,[],c))
 def test_required_dc_save_is_a_finite_scalar(self):
  with tempfile.TemporaryDirectory() as d:
   p=fixture(d);c=copy.deepcopy(CONTRACT);c['required']={'schema':'vco-tbgen.required.v1','analyses':[],'outputs':[],'saves':['/P']}
   p['output_scalars']={'__save__/P':[[0.,0.]]}
   self.assertEqual(verify_point(p,[],c),[])
   p['output_scalars']['__save__/P'][0][1]=None;self.assertTrue(verify_point(p,[],c))
 def test_required_schema_version_and_kind(self):
  s=sample();s.pop('completeness');s['required']={'schema':'vco-tbgen.required.v1','analyses':['hb'],'outputs':[{'name':'W','kind':'waveform'}],'saves':[]};self.assertEqual(validate(s),[])
  s['required']['schema']='v2';self.assertTrue(validate(s))
 def test_b_default_requires_only_increment(self):
  with tempfile.TemporaryDirectory() as d:
   saved_setup(d);s={'mode':'add_test_to_existing','maestro':{'test':'COPY'},'analyses':[{'kind':'hbxf','parameters':{}}]}
   e=effective_spec(s,d);self.assertEqual(e['required']['analyses'],['hbxf']);self.assertEqual(e['required']['outputs'],[])
 def test_full_waveform_tsv_keeps_units_family_and_all_samples(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'p.tsv';p.write_text('POINT\t1\tTT\tCOPY\tdone\t/P\nWAVE_META\tW\t(("harmonic" 2))\t"Hz"\t"V"\n'+''.join('WAVE_SAMPLE\tW\t%d\t2\t3\n'%i for i in range(10)))
   wave=read_points(p)[2][0]['output_waveforms']['W']['curves'][0]
   self.assertEqual(len(wave['samples']),10);self.assertEqual(wave['x_unit'],'Hz');self.assertIn('harmonic',wave['coordinates_native'])


class SessionContract(unittest.TestCase):
 def prepare(self,d,dirty=False):
  s=sample();s.update(workspace=d,library_path=str(Path(d)/'oa/L'),mode='add_test_to_existing');s['maestro'].update(lib='L',cell='C',view='maestro',test='ADDED',source_test='COPY');s['ports']=[]
  for k in ['variables','corners','sweeps','models','simulator_options','initial_conditions','supplies','controls','registers','probes']:s.pop(k,None)
  setup=Path(s['library_path'])/'C/maestro';saved_setup(setup)
  c={'schema':'vco-tbgen.session-context.v1','session':'fnxSession0','window_id':12,'setup_handle':1001,'lcv':{'lib':'L','cell':'C','view':'maestro'},'dirty':dirty,'save_policy':'save','revision':disk_revision(setup),'generation':'window12-v1'}
  return s,c,setup
 def test_emission_preserves_caller_lifecycle(self):
  with tempfile.TemporaryDirectory() as d:
   s,c,setup=self.prepare(d);p=plan_session_add(s,c);m=materialize_session_add(p,c);b=Path(m['skill_path']).read_text();validate_skill(b)
   self.assertNotIn('maeOpenSetup',b);self.assertNotIn('maeCloseSession',b);self.assertNotIn('exit(',b)
   self.assertIn('session library path mismatch',b);self.assertIn('axlGetWindowSession(12)',b);self.assertIn('axlGetMainSetupDB(s) 1001',b);self.assertIn('?sourceTest "COPY"',b)
   self.assertLess(b.index('session backup failed'),b.index('maeCreateTest'))
   self.assertIn('maeLoadSetupState',b);self.assertIn('native-before.txt',b);self.assertIn('native-after.txt',b)
 def test_dirty_requires_explicit_policy(self):
  with tempfile.TemporaryDirectory() as d:
   s,c,_=self.prepare(d,True);c['save_policy']='reject'
   with self.assertRaisesRegex(ValueError,'UNSAVED'):plan_session_add(s,c)
   c['save_policy']='implicit'
   with self.assertRaises(ValueError):plan_session_add(s,c)
 def test_stale_context_and_tampered_plan_fail(self):
  with tempfile.TemporaryDirectory() as d:
   s,c,setup=self.prepare(d);p=plan_session_add(s,c)
   changed=copy.deepcopy(c);changed['window_id']=13
   with self.assertRaises(ValueError):materialize_session_add(p,changed)
   p['spec']['maestro']['test']='OTHER'
   with self.assertRaises(ValueError):materialize_session_add(p,c)
   (setup/'maestro.sdb').write_text((setup/'maestro.sdb').read_text()+'\n')
   with self.assertRaisesRegex(ValueError,'stale'):plan_session_add(s,c)
 def test_unknown_dirty_and_lcv_fail(self):
  with tempfile.TemporaryDirectory() as d:
   s,c,_=self.prepare(d);c['dirty']=None
   with self.assertRaises(ValueError):plan_session_add(s,c)
   c['dirty']=False;c['lcv']['cell']='WRONG'
   with self.assertRaises(ValueError):plan_session_add(s,c)
 def test_disk_verifier_rejects_original_output_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   s,c,setup=self.prepare(d);m=materialize_session_add(plan_session_add(s,c),c);f=Path(m['skill_path']).parent
   _main('backup',f);_main('baseline',f)
   (f/'native-before.txt').write_text('same');(f/'native-after.txt').write_text('same')
   p=setup/'active.state';p.write_text(p.read_text().replace('VAR("VDD")','VAR("CHANGED")'))
   with self.assertRaises(ValueError):_main('rollback',f)
   self.assertEqual(json.loads((f/'receipt.json').read_text())['status'],'failed')
