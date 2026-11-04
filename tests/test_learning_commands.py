"""Saved-ledger CLI/API roundtrip tests with synthetic trusted evidence."""
import copy
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from rsilab.cli import main
from rsilab.learning_commands import select_from_saved_ledger
from rsilab.learning import select_verified_targets
from test_learning import ledger_fixture,task

class LearningCommandTests(unittest.TestCase):
    def test_saved_ledger_replays_exact_selection(self):
        ledger=ledger_fixture()
        result=select_from_saved_ledger(ledger.to_dict(),[task(0,'dev'),task(0,'final')])
        self.assertEqual(result,select_verified_targets(ledger))
    def test_altered_attempt_hash_is_rejected(self):
        payload=ledger_fixture().to_dict();payload['attempts'][0]['attempt_id']='bad'
        with self.assertRaisesRegex(ValueError,'lineage'):select_from_saved_ledger(payload,[task(0,'dev'),task(0,'final')])
    def test_cli_uses_identical_offline_selection(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root/'work',prefix='learning-cli-') as directory:
            path=Path(directory);ledger=ledger_fixture()
            (path/'ledger.json').write_text(json.dumps(ledger.to_dict()))
            (path/'excluded.json').write_text(json.dumps([task(0,'dev'),task(0,'final')]))
            output=StringIO()
            with redirect_stdout(output):code=main(['learning-select',str(path/'ledger.json'),str(path/'excluded.json')])
            self.assertEqual(code,0);self.assertEqual(json.loads(output.getvalue()),select_verified_targets(ledger))

if __name__=='__main__':unittest.main()
