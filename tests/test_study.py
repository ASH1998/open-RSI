import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from rsi.budget import Budget, BudgetExceeded
from rsi.study import verify_outputs, category


class StudyIntegrityTests(unittest.TestCase):
    def test_categories_exclude_shared_import_policy(self):
        prefix='Allowed imports include string, array and collections.\n\n'
        self.assertEqual(category(prefix+'Find the area of a tetrahedron.'),'numeric')
        self.assertEqual(category(prefix+'Sort a list of integers.'),'collections')
        self.assertEqual(category(prefix+'Reverse words in a string.'),'text')

    def test_truncated_valid_code_cannot_be_a_training_label(self):
        task = {'id':'one', 'cases':[{'args':[], 'expected':1}]}
        result = {'status':'completed', 'outputs':[{'id':'one', 'text':'def solve(): return 1', 'hit_token_limit':True}]}
        report = {}
        with patch('rsi.study.persist'), patch('rsi.verification.verify_candidate') as verifier:
            rows = verify_outputs([task],result,None,report)
        verifier.assert_not_called()
        self.assertFalse(rows[0]['verification']['passed'])
        self.assertNotIn('verified_code',rows[0])

    def test_concurrent_reservations_cannot_exceed_study_cap(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work') as temp:
            root=Path(temp);(root/'config').mkdir();(root/'budget').mkdir()
            (root/'config/budget.json').write_text(json.dumps({'max_stage_reservation':5,'project_cap':250,
                'overhead_reserve':25,'prefix_reservation_caps':{'mbpp-':5}}))
            (root/'budget/ledger.json').write_text(json.dumps({'reservations':[]}))
            def reserve(_):
                try: Budget(root).reserve('mbpp-baseline'); return True
                except BudgetExceeded: return False
            with ThreadPoolExecutor(max_workers=2) as executor:
                results=list(executor.map(reserve,range(2)))
            self.assertEqual(sum(results),1)
            self.assertEqual(Budget(root).summary()['reserved_for_jobs_usd'],5)
