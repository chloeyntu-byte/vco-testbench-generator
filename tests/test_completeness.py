"""Completeness routing and opt-in multi-PDK replay."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vco_tbgen import from_design_lab, materialize, plan, run
from vco_tbgen.isf import analysis_bundle, injection_for_device, install_isf, write_stimulus


def fixture(root, separate_bank=False, level='L-b'):
    ports = [{'name': name, 'direction': 'inputOutput'} for name in
             ('VDD', 'VDC', 'VSS', 'OUTP', 'OUTN', 'main_B0')]
    parameters = dict(vdd=1.0, vdc=0.6, frequency_guess_ghz=9)
    if separate_bank:
        ports.append(dict(name='VDDB', direction='inputOutput'))
        parameters['vdd_bank'] = 1.2
    example = Path(__file__).resolve().parents[1] / 'examples/generic-binding.json'
    binding = json.loads(example.read_text())
    files = dict(manifest={}, graph=dict(ports=ports, parameters=parameters),
                 binding=binding,
                 registers=[dict(name='main', bits=1, pins_msb_first=['main_B0'], default=1)])
    for name, value in files.items():
        (root/f'{name}.json').write_text(json.dumps(value))
    return from_design_lab(root, dut=dict(lib='DUT', cell='VCO', view='schematic'),
                           workspace=root, cds_lib=root/'cds.lib', library_path=root/'OWNED',
                           maestro=dict(lib='OWNED', cell='TB', view='maestro', test='RF'),
                           completeness=level)


class CompletenessTests(unittest.TestCase):
    def test_fixture_stops_before_maestro_and_uses_bank_supply(self):
        with tempfile.TemporaryDirectory() as work:
            spec = fixture(Path(work), separate_bank=True)
            self.assertEqual(spec['analyses'], [])
            binding = json.loads((Path(work)/'binding.json').read_text())
            self.assertEqual(spec['models'], binding['model_includes'])
            self.assertEqual(spec['registers'][0]['vdd'], 'VDDB')
            self.assertEqual(spec['variables']['VDDB'], 1.2)
            self.assertEqual([row['positive'] for row in spec['supplies']], ['VDD', 'VDDB'])
            proposal = plan(spec)
            self.assertEqual(proposal['status'], 'ready')
            self.assertEqual(proposal['operations'][-1]['field'], 'schematic/config')
            with patch('vco_tbgen.completion._locked', return_value={'status': 'fixture_ready'}) as call:
                self.assertEqual(materialize(spec, proposal)['status'], 'fixture_ready')
                call.assert_called_once_with('fixture', spec, {'plan': proposal})
            with self.assertRaisesRegex(ValueError, 'prepared materialization'):
                run({'status': 'fixture_ready'})

    def test_oscillator_has_only_hb_hbnoise_and_runs_through_public_api(self):
        with tempfile.TemporaryDirectory() as work:
            spec = fixture(Path(work), level='L-c')
            self.assertEqual(['hb', 'hbnoise'], [row['kind'] for row in spec['analyses']])
            self.assertEqual(plan(spec)['status'], 'ready')
            names = {row['name'] for row in spec['required']['outputs']}
            self.assertIn('VCO_HB_F0_Hz', names)
            self.assertIn('VCO_HB_VDD_SRC_PDC_W', names)
            self.assertIn('VCO_HBNOISE_PN_10000Hz_dBc_Hz', names)
            with patch('vco_tbgen.completion._locked') as native:
                materialize(spec)
                self.assertEqual(native.call_args.args[0], 'materialize')
            materialized = dict(status='prepared', spec=spec, spec_hash=plan(spec)['spec_hash'])
            with patch('vco_tbgen.runner._locked', return_value={'status': 'running'}) as native:
                self.assertEqual(run(materialized, wait=False)['status'], 'running')
                native.assert_called_once_with('run', spec, {'materialized': materialized}, wait=False)
            spec['required']['outputs'] = []
            self.assertEqual(plan(spec)['status'], 'needs_input')

    def test_isf_defers_loading_and_uses_proven_numbered_drain(self):
        code = ('import sys; from vco_tbgen import classify_ports; classify_ports({}); '
                'assert "vco_tbgen.isf" not in sys.modules; assert "vco_tbgen.maestro" not in sys.modules')
        subprocess.run([sys.executable, '-B', '-c', code], check=True)
        device = dict(target_instance='DUT.M1', terminals={
            'D': dict(formal='1', resolved_net='OUTP'), 'S': dict(formal='3', resolved_net='0')})
        with tempfile.TemporaryDirectory() as work:
            spec = fixture(Path(work))
            spec['simulator_options'] = {}
            bundle = analysis_bundle([], frequency='9G', positive='OUTP', negative='OUTN',
                                     offsets_hz=[10000.], conditions=dict(variables=spec['variables']),
                                     initial_conditions=spec['initial_conditions'])
            injection = injection_for_device(device)
            spec = install_isf(spec, bundle, injection=injection, device=device, supplies=spec['supplies'])
            self.assertEqual(spec['completeness'], 'L-d')
            self.assertEqual(plan(spec)['status'], 'ready')
            self.assertIn('/DUT/M1/1', spec['required']['saves'])
            write_stimulus(spec)
            stimulus, = Path(work).glob('hbxf-injection-*.scs')
            self.assertIn('ISF_TB_INJECT (OUTP ISF_TB_INJECT_RETURN) isource dc=0', stimulus.read_text())
            self.assertIn('ISF_TB_INJECT_PROBE (ISF_TB_INJECT_RETURN 0) iprobe', stimulus.read_text())
            self.assertIn('save DUT.M1:1', stimulus.read_text())


@unittest.skipUnless(os.environ.get('TBGEN_NATIVE') == '1' and os.environ.get('TBGEN_PDK_SPECS'),
                     'set TBGEN_NATIVE=1 and TBGEN_PDK_SPECS to a JSON map of private L-d specs')
class MultiPdkNative(unittest.TestCase):
    def test_native_rf_contract_per_profile(self):
        profiles = json.loads(Path(os.environ['TBGEN_PDK_SPECS']).read_text())
        self.assertTrue(profiles)
        for pdk, path in profiles.items():
            with self.subTest(pdk=pdk):
                if shutil.disk_usage('/').free < 2 * 1024**3:
                    self.fail('Native qualification requires 2 GiB of free disk capacity')
                spec = json.loads(Path(path).read_text())
                self.assertEqual(spec.get('completeness'), 'L-d')
                self.assertEqual(spec.get('mode'), 'create_new')
                self.assertTrue(spec.get('hbxf_injection'))
                import uuid
                spec['maestro']['cell'] = 'Qualification_' + uuid.uuid4().hex[:12]
                receipt = materialize(spec)
                self.assertEqual(receipt['status'], 'prepared', receipt.get('error'))
                result = run(receipt)
                for point in result.get('points', []):
                    psf = Path(point['psf_dir']).resolve()
                    workspace = Path(spec['workspace']).resolve()
                    self.assertTrue(psf.is_relative_to(workspace))
                    # Keep the complete JSON qualification and Spectre terminal
                    # evidence while releasing the generated waveform payload.
                    evidence = Path(result['manifest_path']).parent
                    shutil.copy2(psf/'spectre.out', evidence/f"point-{point['point_id']}-spectre.out")
                    shutil.rmtree(psf)
                self.assertEqual(result['status'], 'completed', result.get('issues'))
                self.assertTrue(result['points'])
                for point in result['points']:
                    self.assertTrue({'hb_fd', 'hbnoise_pm', 'hbxf'} <= set(point['analyses']))
                    self.assertTrue(point['hbxf_injection_qualification']['verified'])
