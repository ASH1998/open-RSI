"""An incomplete provider result must never become a model-comparison score."""
import unittest
from unittest.mock import patch

from rsi.pilot import score_generation, scores


class ComparisonIntegrityTests(unittest.TestCase):
    def test_incomplete_generation_never_launches_verification(self):
        tasks = [{'id': 'task-1'}]
        for generation in (
            {'status': 'generation_time_limit', 'outputs': []},
            {'status': 'completed', 'outputs': [{'id': 'task-1', 'hit_time_limit': True}]},
            {'status': 'completed', 'outputs': [{'id': 'wrong-task'}]},
        ):
            with self.subTest(generation=generation), patch('rsi.verification.verify_candidate') as verify:
                with self.assertRaises(ValueError):
                    score_generation(tasks, generation, None, {})
                verify.assert_not_called()

    def test_training_success_does_not_inflate_development_score(self):
        records = [
            {'task': {'split': 'train'}, 'verification': {'passed': True}},
            {'task': {'split': 'train'}, 'verification': {'passed': True}},
            {'task': {'split': 'dev'}, 'verification': {'passed': False}},
            {'task': {'split': 'dev'}, 'verification': {'passed': True}},
        ]
        self.assertEqual(scores(records), {
            'train': {'passed': 2, 'total': 2, 'rate': 1.0},
            'dev': {'passed': 1, 'total': 2, 'rate': 0.5},
        })


if __name__ == '__main__':
    unittest.main()
