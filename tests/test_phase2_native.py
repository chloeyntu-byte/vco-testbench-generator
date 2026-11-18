"""Opt-in real setup and caller-owned session integration.

TBGEN_NATIVE=1 TBGEN_PHASE2_NATIVE=1 TBGEN_PHASE2_ROOT=/owned/run/root
TBGEN_EXISTING_SPEC=/path/to/add-spec.json TBGEN_NATIVE_SPEC=/path/to/create-spec.json
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest
import uuid
from vco_tbgen import materialize,plan,run
from vco_tbgen import native
from vco_tbgen.api import setup_snapshot

ROOT=Path(__file__).resolve().parents[1]


def copy_fixture(work):
    from vco_tbgen.transaction import check_unlocked

    if shutil.disk_usage(work.parent).free < 2 * 1024**3:
        raise RuntimeError('DISK_LOW')
    spec = json.loads(Path(os.environ['TBGEN_EXISTING_SPEC']).read_text())
    source = Path(spec['library_path']).resolve()
    target = work / 'oa' / spec['maestro']['lib']
    cell = Path(spec['maestro']['cell']) / spec['maestro']['view']
    check_unlocked(source / cell)

    def ignore(folder, names):
        return [name for name in names if name == 'results' or '.bak-' in name
                or '.cdslck' in name or name.startswith(('.oa-lock', 'libInit.il'))]

    shutil.copytree(source, target, ignore=ignore)
    spec.update(workspace=str(work), library_path=str(target))
    return spec, target / cell


@unittest.skipUnless(os.environ.get('TBGEN_NATIVE')=='1' and os.environ.get('TBGEN_PHASE2_NATIVE')=='1','phase 2 private native fixtures are opt-in')
class Phase2Native(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    cls.root=Path(os.environ['TBGEN_PHASE2_ROOT'])/('phase2_'+uuid.uuid4().hex[:8]);cls.root.mkdir(parents=True)
 def test_real_b_with_noise_and_complex_wave(self):
    s,setup=copy_fixture(self.root/'B');before=setup_snapshot(setup)
    wave_node = os.environ['TBGEN_EXISTING_WAVE_NODE']
    waveform = dict(name='REQUIRED_WAVE', expression='getData('+native.sq(wave_node)+' ?result "hb_fd")')
    s.setdefault('outputs', []).append(waveform)
    s['required']['outputs'].append(dict(name=waveform['name'], kind='waveform'))
    m=materialize(s,plan(s));self.assertEqual(m['status'],'prepared',m)
    r=run(m);(self.root/'real-b.json').write_text(json.dumps(r,indent=2));self.assertEqual(r['status'],'completed',r)
    self.assertGreater(r['coverage']['matched'], 0)
    for p in r['points']:
        self.assertIn('noise',p['analyses']);self.assertTrue(any(v['name']=='noise' and v['finite_data'] for v in p['preserved_results']))
        self.assertEqual(p['output_qualification']['REQUIRED_WAVE']['status'],'verified')
        self.assertTrue(any(v['status']=='unverified' for v in p['output_qualification'].values()))
        curve=p['output_waveforms']['REQUIRED_WAVE']['curves'][0]
        self.assertGreater(len(curve['samples']),3);self.assertEqual(curve['x_unit'],'Hz');self.assertEqual(curve['y_unit'],'V')
    after=setup_snapshot(setup)
    for name in ['maestro.sdb','active.state']:
        for k,v in before[name].items():self.assertEqual(after[name][k],v)
    self.assertEqual(before['global'],after['global'])
 def test_session_add_readback_rollback_and_dirty_policy(self):
    for case in ['add','rollback','dirty-save','dirty-reject']:
      with self.subTest(case=case):
        w=self.root/case;s,setup=copy_fixture(w);s['maestro']['test']='SESSION_ADDED'
        (w/'spec.json').write_text(json.dumps(s,indent=2));b=native.open_setup(s)
        b+='unless(maeSaveSetup(?session s) error("private fixture save failed"))\n'
        if case.startswith('dirty'):b+='maeSetVar("SESSION_DIRTY" "42" ?session s)\n'
        b+='o=outfile('+native.sq(w/'context-native.json')+') fprintf(o "{\\\"session\\\":\\\"%s\\\",\\\"setup_handle\\\":%d,\\\"dirty\\\":%s}" s axlGetMainSetupDB(s) if(maeIsSetupModified(?session s) then "true" else "false")) close(o)\n'
        command='PYTHONPATH='+shlex.quote(str(ROOT))+' '+shlex.join([sys.executable,'-B',str(ROOT/'tests/native_session_driver.py'),str(w),case])
        b+='unless(system('+native.sq(command)+')==0 error("runtime plan failed"))\nload('+native.sq(w/'invoke.il')+')\nunless(maeIsValidMaestroSession(s) error("session closed"))\n'
        expected='nil' if case in ['rollback','dirty-reject'] else 't'
        b+='unless(equal(if(member("SESSION_ADDED" maeGetSetup(?session s)) then t else nil) '+expected+') error("test readback mismatch"))\n'
        b+='o=outfile('+native.sq(w/'readback.txt')+') fprintf(o "SESSION %s VALID %L TESTS %L\\n" s maeIsValidMaestroSession(s) maeGetSetup(?session s)) close(o)\n'
        native.execute(b,w/'native',s['cds_lib'],s['maestro']['lib'],s['library_path'])
        receipt=w/'receipt.json' if case=='dirty-reject' else Path(json.loads((w/'prepared.json').read_text())['receipt_path'])
        r=json.loads(receipt.read_text());self.assertEqual(r['status'],{'add':'added','dirty-save':'added','rollback':'rolled_back','dirty-reject':'rejected'}[case],r)
        if case!='dirty-reject':self.assertFalse(r['session_closed']);self.assertTrue(r['original_tests_verified'])
        self.assertIn('VALID t',(w/'readback.txt').read_text())
 def test_new_tb_steady_state(self):
    s=json.loads(Path(os.environ['TBGEN_NATIVE_SPEC']).read_text());w=self.root/'steady';w.mkdir()
    s.update(workspace=str(w),library_path=str(w/'oa/TBGEN_HB_STEADY'))
    s['maestro'].update(lib='TBGEN_HB_STEADY',cell='Steady_'+uuid.uuid4().hex[:8])
    m=materialize(s,plan(s));self.assertEqual(m['status'],'prepared',m)
    r=run(m);(w/'run.json').write_text(json.dumps(r,indent=2));self.assertEqual(r['status'],'completed',r)
    for p in r['points']:
        text=(Path(p['psf_dir'])/'spectre.out').read_text().lower()
        self.assertNotIn('steady-state has not been detected',text)
        self.assertTrue(p['steady_state']['detected'])
        self.assertEqual(p['steady_state']['basis'],'two_tier_hb_residuals')
        self.assertFalse(p['steady_state']['transient_detected'])
        self.assertTrue(all(0<=v<1 for v in p['steady_state']['normalized_residuals'].values()))
