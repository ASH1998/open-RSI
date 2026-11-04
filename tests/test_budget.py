import json
from pathlib import Path
import tempfile
import unittest

from rsi.budget import Budget, BudgetExceeded
from rsi.config import ROOT


class BudgetTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'work').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'work')
        root = Path(self.tmp.name)
        (root / 'config').mkdir()
        (root / 'budget').mkdir()
        (root / 'config/budget.json').write_text(json.dumps({
            'project_cap': 12, 'overhead_reserve': 2, 'max_stage_reservation': 5}))
        (root / 'budget/ledger.json').write_text('{"reservations": []}')
        self.budget = Budget(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_failure_does_not_release_reserved_spend(self):
        first = self.budget.reserve('first')
        self.budget.finish(first, 'failed')
        self.budget.reserve('second')
        with self.assertRaises(BudgetExceeded):
            self.budget.reserve('third', .01)
        self.assertEqual(self.budget.summary()['available_for_jobs_usd'], 0)

    def test_invalid_values_and_double_finalization(self):
        for value in [0, -1, 6, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                self.budget.reserve('invalid', value)
        reservation = self.budget.reserve('valid')
        self.budget.finish(reservation, 'completed')
        with self.assertRaises(ValueError):
            self.budget.finish(reservation, 'completed')


if __name__ == '__main__':
    unittest.main()
