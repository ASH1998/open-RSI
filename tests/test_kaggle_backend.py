import json
from pathlib import Path
import tempfile
import unittest
from rsi.kaggle_backend import prepare_kernel, MODEL_ID, MODEL_REVISION


class KaggleUploadTests(unittest.TestCase):
    def request(self):
        return {'model_id': MODEL_ID, 'revision': MODEL_REVISION, 'seed': 42,
                'max_new_tokens': 512, 'manifest_hash': 'frozen',
                'prompts': [{'id': 'one', 'prompt': 'Return a string containing quotes: \' and ".'}]}

    def test_private_script_contains_only_explicit_public_inputs(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work') as temp:
            dest = Path(temp) / 'kernel'
            audit = prepare_kernel(self.request(), dest, 'example')
            metadata = json.loads((dest / 'kernel-metadata.json').read_text())
            self.assertIs(metadata['is_private'], True)
            self.assertEqual(metadata['dataset_sources'], [])
            compile((dest / 'worker.py').read_text(), 'worker.py', 'exec')
            self.assertEqual(audit['session_timeout_seconds'], 3600)

    def test_hidden_tests_or_credentials_are_rejected(self):
        request = self.request()
        request['prompts'][0]['test_list'] = ['hidden']
        with self.assertRaises(ValueError):
            prepare_kernel(request, '/unused', 'example')
        request = self.request()
        request['HF_TOKEN'] = 'must-not-upload'
        with self.assertRaises(ValueError):
            prepare_kernel(request, '/unused', 'example')
