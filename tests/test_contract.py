import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from vco_tbgen import plan, validate, classify_ports, materialize
from vco_tbgen.spec import expand_bus
from vco_tbgen.native import sq, sl, create_tb, test_setup, register_source
from vco_tbgen.api import check_unlocked, setup_snapshot, _target
from vco_tbgen.runner import read_points, verify_point, run_script

ROOT=Path(__file__).resolve().parents[1]
def sample():
    spec = json.loads((ROOT/'examples/generic-request.json').read_text())
    binding = json.loads((ROOT/'examples/generic-binding.json').read_text())
    if spec['models'] != binding['model_includes']:
        raise AssertionError('Example model includes differ from the generic binding')
    return spec

class Contract(unittest.TestCase):
 def test_example(self):self.assertEqual(validate(sample()),[]);self.assertEqual(plan(sample())['status'],'ready')
 def test_version(self):
  s=sample();s['schema']='vco-tbgen.spec.v2';self.assertTrue(validate(s))
 def test_unknown(self):
  s=sample();s['made_up']=1;self.assertTrue(validate(s))
 def test_nested_unknown(self):
  s=sample();s['dut']['wrong']=1;self.assertTrue(validate(s))
 def test_type_bool_is_not_integer(self):
  s=sample();s['registers'][0]['width']=True;self.assertTrue(validate(s))
 def test_code_range(self):
  for value in [-1,16,1.5,True,'10']:
   s=sample();s['variables']['MAIN_CODE']=value;self.assertTrue(validate(s),value)
 def test_register_width(self):
  s=sample();s['registers'][0]['members_lsb_first'].pop();self.assertTrue(validate(s))
 def test_duplicate_ports(self):
  s=sample();s['ports'].append(s['ports'][0]);self.assertTrue(validate(s))
 def test_duplicate_instance(self):
  s=sample();s['supplies'][0]['name']='DUT';self.assertTrue(validate(s))
 def test_probe_short(self):
  s=sample();s['probes'][0]['internal_net']=s['probes'][0]['net'];self.assertTrue(validate(s))
 def test_missing_driver(self):
  s=sample();s['controls']=[];self.assertEqual(plan(s)['status'],'needs_input')
 def test_frequency(self):
  s=sample();del s['analyses'][0]['parameters']['fundfreqs'];self.assertEqual(plan(s)['status'],'needs_input')
 def test_unknown_role(self):
  s=sample();s['ports'][0]['role']='unknown';self.assertEqual(plan(s)['status'],'needs_input')
 def test_stale_plan(self):
  s=sample();p=plan(s);s['variables']['VDD']=1.7
  with self.assertRaisesRegex(ValueError,'stale'):materialize(s,p)
 def test_add_inherits(self):
  s=sample();s['mode']='add_test_to_existing';s['maestro']['source_test']='BASE'
  self.assertEqual(plan(s)['status'],'needs_input')
  for k in ['variables','corners','sweeps','models','simulator_options','initial_conditions','supplies','controls','registers','probes']:s.pop(k,None)
  self.assertEqual(plan(s)['status'],'ready')
 def test_escape(self):
  self.assertEqual(sq('a"b\n'),'"a\\"b\\n"');self.assertEqual(sl(['1',True]),'list("1" t)')
 def test_ascending_bus(self):self.assertEqual(expand_bus('code<0:2>'),['code<0>','code<1>','code<2>'])
 def test_descending_bus(self):self.assertEqual(expand_bus('code[2:0]'),['code[2]','code[1]','code[0]'])
 def test_classification(self):
  names=['VDD!','VSS','OUTP','OUTN','VTUNE','EN','main_B0','main_B1','mystery']
  c=classify_ports({'ports':[{'name':n,'direction':'input' if n=='EN' else 'inputOutput'} for n in names]})
  self.assertEqual([p['suggested_role'] for p in c['ports']],['supply','ground','output_p','output_n','bias','control','register','register','unknown'])
  self.assertEqual(c['registers'][0]['members_lsb_first'],['main_B0','main_B1'])
  self.assertTrue(all(p['requires_confirmation'] for p in c['ports']))
 def test_external_root(self):
  s=sample();s['library_path']='/path/to/another-lib'
  with self.assertRaisesRegex(ValueError,'owned'): _target(s)
 def test_lock_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   lock=Path(tmp)/'maestro.sdb.cdslck';lock.write_text('owned elsewhere')
   with self.assertRaisesRegex(RuntimeError,'OPEN_OR_LOCKED'):check_unlocked(tmp)
   self.assertTrue(lock.exists())
 def test_snapshot_original_change(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'test_states').mkdir();(p/'maestro.sdb').write_text('<setupdb><active><tests><test>A<vars/></test></tests></active></setupdb>');(p/'active.state').write_text('<statedb><Test Name="A"><x>1</x></Test></statedb>')
   before=setup_snapshot(p);(p/'active.state').write_text('<statedb><Test Name="A"><x>2</x></Test></statedb>')
   self.assertNotEqual(before['active.state'],setup_snapshot(p)['active.state'])
 def test_va_validates_before_shift(self):
  text=register_source(4);self.assertIn('$fatal',text);self.assertIn('*V(vdd,vss)',text);self.assertIn('DEC_CODE>=16',text)
 def test_script_snapshot(self):
  s=sample();work=Path(s['workspace'])
  schematic,_=create_tb(s,work/'transaction')
  actual=schematic+'\n'+test_setup(s)+'\n'+run_script(s,work/'run')
  self.assertEqual(actual,(ROOT/'tests/snapshots/maestro.il').read_text())
 def test_missing_spectre_terminal_is_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   p={'psf_dir':tmp,'rdb':str(Path(tmp)/'rdb'),'native_status':'done','analyses':['hb_fd']}
   self.assertTrue(verify_point(p,['hb']));self.assertEqual(p['completion']['state'],'failed')
 def test_parse_point_identity(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'points.tsv';path.write_text('HISTORY\tInteractive.0\nRDB\t/private/run.rdb\nPOINT\t1\tTT\tISF\tdone\t/private/point\nPARAM\tCODE\t10\nRAW\thbxf\tVDD_SRC\t10000\t2\t-3\n')
   history,rdb,points=read_points(path);self.assertEqual(points[0]['corner'],'TT');self.assertEqual(points[0]['variables']['CODE'],10);self.assertEqual(points[0]['raw_samples'][0]['imag'],-3)


class SafetyAndResults(unittest.TestCase):
 def test_all_generated_skill_balanced(self):
  from vco_tbgen.native import validate_skill
  s=sample();b,_=create_tb(s,Path('/WORK'))
  validate_skill(b);validate_skill(test_setup(s));validate_skill(run_script(s,Path('/WORK')))
  with self.assertRaises(ValueError):validate_skill('(unclosed(')
 def test_dc_pseudo_oscillation(self):
  from vco_tbgen.runner import carrier_reading
  p={'raw_samples':[{'analysis':'hb_fd','signal':'/P','x':1e9,'real':1e-16,'imag':0},{'analysis':'hb_fd','signal':'/N','x':1e9,'real':-1e-16,'imag':0}]}
  self.assertLess(carrier_reading(p,{'p':'/P','n':'/N'})['magnitude_v'],1e-5)
 def test_actual_point_parameters(self):
  from vco_tbgen.runner import read_design_parameters
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'designParamVals.info').write_text('TYPE\n"top-level" STRUCT(\n"CODE" FLOAT DOUBLE\n"VDD" FLOAT DOUBLE\n) PROP(\n"key" "parameters"\n)\nVALUE\n"top-level" "top-level" (\n10\n1.8\n)\nEND\n')
   values,evidence=read_design_parameters(tmp,['CODE','VDD']);self.assertEqual(values,{'CODE':10.0,'VDD':1.8});self.assertEqual(evidence['status'],'read')
 def test_serializer_preserves_old_bytes(self):
  from vco_tbgen.preservation import preserve_original,fragments
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);a=p/'backup';b=p/'setup';a.mkdir();b.mkdir()
   old=b'<setupdb version="6"><active><vars>KEEP</vars><tests><test>A<vars>1</vars></test></tests></active></setupdb>'
   state=b'<statedb version="5"><Test Name="A"><field>KEEP</field></Test></statedb>'
   (a/'maestro.sdb').write_bytes(old);(a/'active.state').write_bytes(state)
   (b/'maestro.sdb').write_bytes(old.replace(b'<vars>1</vars>',b'<vars>CHANGED</vars>').replace(b'</tests>',b'<test>B<vars>2</vars></test></tests>'))
   (b/'active.state').write_bytes(state.replace(b'KEEP',b'CHANGED').replace(b'</statedb>',b'<Test Name="B"><field>NEW</field></Test></statedb>'))
   preserve_original(a,b,'B')
   self.assertIn(b'<test>A<vars>1</vars></test>',(b/'maestro.sdb').read_bytes())
   self.assertIn(b'<Test Name="A"><field>KEEP</field></Test>',(b/'active.state').read_bytes())
 def test_serializer_unknown_version_refused(self):
  from vco_tbgen.preservation import qualify
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'maestro.sdb').write_text('<setupdb version="999"/>');Path(tmp,'active.state').write_text('<statedb version="5"/>')
   with self.assertRaisesRegex(ValueError,'unsupported'):qualify(tmp)

class HistoryPreservation(unittest.TestCase):
 def test_native_test_insertion_does_not_touch_history_tests(self):
  from vco_tbgen.preservation import preserve_original
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);a=p/'backup';b=p/'setup';a.mkdir();b.mkdir()
   old=b'<setupdb version="6"><active><tests><test>A<x>original</x></test></tests></active><history><checkpoint><tests><test>A<x>history</x></test></tests></checkpoint></history></setupdb>'
   state=b'<statedb version="5"><Test Name="A"><x>original</x></Test></statedb>'
   (a/'maestro.sdb').write_bytes(old);(a/'active.state').write_bytes(state)
   saved=old.replace(b'</tests></active>',b'<test>B<x>new</x></test></tests></active>')
   (b/'maestro.sdb').write_bytes(saved);(b/'active.state').write_bytes(state.replace(b'</statedb>',b'<Test Name="B"><x>new</x></Test></statedb>'))
   preserve_original(a,b,'B')
   result=(b/'maestro.sdb').read_bytes();self.assertIn(b'<checkpoint><tests><test>A<x>history</x></test></tests></checkpoint>',result);self.assertEqual(result.count(b'<test>B'),1)
 def test_run_preserves_active_and_retains_new_history(self):
  from vco_tbgen.preservation import preserve_run_settings
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);a=p/'backup';b=p/'setup';a.mkdir();b.mkdir()
   (a/'maestro.sdb').write_text('<setupdb version="6"><active>Active<tests><test>A</test></tests></active><history>old</history></setupdb>')
   (a/'active.state').write_text('<statedb version="5"><Test Name="A"><x>original</x></Test></statedb>')
   (b/'maestro.sdb').write_text('<setupdb version="6"><active>Active<tests><test>A<x>changed</x></test></tests></active><history>old<new>new</new></history></setupdb>')
   (b/'active.state').write_text('<statedb version="5"><Test Name="A"><x>changed</x></Test></statedb>')
   preserve_run_settings(a,b)
   self.assertIn('<test>A</test>',(b/'maestro.sdb').read_text());self.assertIn('<new>new</new>',(b/'maestro.sdb').read_text());self.assertEqual((a/'active.state').read_bytes(),(b/'active.state').read_bytes())

class FailureReporting(unittest.TestCase):
 def test_failed_run_keeps_reason(self):
  from vco_tbgen import results
  r=results({'schema':'vco-tbgen.failure.v1','status':'failed','error':'source is locked'})
  self.assertEqual(r['issues'],['source is locked']);self.assertEqual(r['points'],[])
 def test_source_setup_cannot_escape_library_through_symlink(self):
  with tempfile.TemporaryDirectory() as tmp:
   w=Path(tmp);lib=w/'oa'/'LIB';lib.mkdir(parents=True);outside=w/'outside';outside.mkdir();(lib/'CELL').symlink_to(outside,target_is_directory=True)
   s=sample();s['workspace']=str(w);s['library_path']=str(lib);s['maestro'].update(lib='LIB',cell='CELL')
   with self.assertRaisesRegex(ValueError,'symlink'): _target(s)

class FixtureConflicts(unittest.TestCase):
 def test_duplicate_register_driver_is_rejected(self):
  s=sample();s['controls'].append({'name':'CONFLICT','positive':'main_B0','negative':'0','value':0})
  self.assertTrue(any('multiple excitations' in e for e in validate(s)))
 def test_probe_cannot_silently_rebind_external_net(self):
  s=sample();s['probes'][0]['net']='ANOTHER_RAIL'
  self.assertTrue(any('port binding' in e for e in validate(s)))

if __name__=='__main__':unittest.main()
