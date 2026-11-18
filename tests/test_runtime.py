"""Offline checks for optional native command wrapping."""
import os
import unittest
from unittest.mock import patch

from vco_tbgen.native import wrap_command


class CommandTemplateTests(unittest.TestCase):
    def test_default_returns_original_arguments(self):
        command = ['python', 'worker.py', 'path with spaces/request.json']
        with patch.dict(os.environ, {'TBGEN_COMMAND_TEMPLATE': ''}):
            self.assertEqual(wrap_command(command, 'example_tb'), command)

    def test_wrapper_preserves_argument_boundaries(self):
        template = '["wrapper", "--library", "{library}", "--", "{command}"]'
        with patch.dict(os.environ, {'TBGEN_COMMAND_TEMPLATE': template}):
            self.assertEqual(
                wrap_command(['bash', 'path with spaces/job.sh'], 'example_tb'),
                ['wrapper', '--library', 'example_tb', '--', 'bash', 'path with spaces/job.sh'],
            )

    def test_invalid_templates_are_rejected(self):
        for template in ('invalid', '"wrapper"', '[]', '["{command}"]',
                         '["wrapper"]', '["wrapper", "{command}", "{command}"]'):
            with self.subTest(template=template), patch.dict(
                os.environ, {'TBGEN_COMMAND_TEMPLATE': template}
            ):
                with self.assertRaisesRegex(ValueError, 'TBGEN_COMMAND_TEMPLATE'):
                    wrap_command(['worker'], 'example_tb')
