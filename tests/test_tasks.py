import copy
from functools import lru_cache
import itertools
import json
import math
import unittest

from rsi.tasks import SPLIT_FAMILIES, TASK_IMPORTS, build_tasks, reference_solution
from rsi.verification import ALLOWED_IMPORTS, score_outputs, validate_code


def trusted_function(task):
    namespace = {}
    # Only repository-authored references are executed by these local tests.
    exec(reference_solution(task), namespace)
    return namespace[task['entry_point']]


class TaskManifestTests(unittest.TestCase):
    def test_deterministic_and_json_serializable(self):
        for split in SPLIT_FAMILIES:
            first = build_tasks(split, 8, seed=17)
            self.assertEqual(first, build_tasks(split, 8, seed=17))
            self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
            self.assertNotEqual(first, build_tasks(split, 8, seed=18))
            self.assertEqual(len(first), 8 * len(SPLIT_FAMILIES[split]))

    def test_family_disjointness_and_unique_prompts(self):
        groups = [set(value) for value in SPLIT_FAMILIES.values()]
        for a, b in itertools.combinations(groups, 2):
            self.assertFalse(a & b)
        tasks = sum((build_tasks(split, 8) for split in SPLIT_FAMILIES), [])
        self.assertEqual(len({task['id'] for task in tasks}), len(tasks))
        self.assertEqual(len({task['prompt'] for task in tasks}), len(tasks))

    def test_public_inputs_do_not_reappear_in_hidden_cases(self):
        for split in SPLIT_FAMILIES:
            for task in build_tasks(split, 8):
                public = [example['args'] for example in task['examples']]
                self.assertGreaterEqual(len(task['cases']), 4)
                self.assertNotIn('_ref_', task['prompt'])
                for case in task['cases']:
                    self.assertIsInstance(case['args'], list)
                    self.assertNotIn(case['args'], public)

    def test_trusted_solutions_match_all_manifest_cases(self):
        for split in SPLIT_FAMILIES:
            for task in build_tasks(split, 8, seed=5):
                solve = trusted_function(task)
                for case in task['examples'] + task['cases']:
                    before = copy.deepcopy(case['args'])
                    arguments = copy.deepcopy(before)
                    self.assertEqual(solve(*arguments), case['expected'])
                    self.assertEqual(arguments, before)
                    self.assertEqual(case['args'], before)

    def test_import_contract_and_reference_policy(self):
        self.assertEqual(set(TASK_IMPORTS), ALLOWED_IMPORTS)
        for split in SPLIT_FAMILIES:
            for task in build_tasks(split, 8):
                self.assertIn(', '.join(TASK_IMPORTS), task['prompt'])
                self.assertIn('No other imports are permitted.', task['prompt'])
                validate_code(reference_solution(task), task['entry_point'])

    def test_reference_outputs_pass_controller_scoring(self):
        for split in SPLIT_FAMILIES:
            for task in build_tasks(split, 8):
                solve = trusted_function(task)
                outputs = [{'ok': True, 'value': solve(*copy.deepcopy(case['args']))}
                           for case in task['cases']]
                result = score_outputs(outputs, task['cases'], **task['tolerance'])
                self.assertTrue(result['passed'], task['id'])
                self.assertEqual(result['count'], len(task['cases']))

    def test_task_tolerances_preserve_discrete_values(self):
        for split in SPLIT_FAMILIES:
            for task in build_tasks(split, 8):
                floating = task['family'] in ('masked_mean', 'stable_softmax', 'gradient_clip') or (
                    task['family'] == 'group_reduce' and task['metadata']['config']['operation'] == 'mean')
                self.assertEqual(task['tolerance'],
                                 {'rel_tol': 1e-6, 'abs_tol': 1e-7} if floating else
                                 {'rel_tol': 0.0, 'abs_tol': 0.0})
                result = score_outputs([{'ok': True, 'value': [1.00000005]}],
                                       [{'args': [], 'expected': [1.0]}], **task['tolerance'])
                self.assertEqual(result['passed'], floating)
                integer_result = score_outputs([{'ok': True, 'value': [1.00000005]}],
                                               [{'args': [], 'expected': [1]}], **task['tolerance'])
                self.assertFalse(integer_result['passed'])

    def test_invalid_requests(self):
        for split in ('validation', '', None, [], {}):
            with self.assertRaises(ValueError):
                build_tasks(split)
        for count in (0, 9, -1, True, 1.5):
            with self.assertRaises(ValueError):
                build_tasks('train', count)
        with self.assertRaises(ValueError):
            build_tasks('train', seed='1')


class ReferenceSemanticsTests(unittest.TestCase):
    """Hand calculations and independent properties avoid only testing round trips."""

    def tasks(self, family):
        split = next(s for s, families in SPLIT_FAMILIES.items() if family in families)
        return [t for t in build_tasks(split, 8) if t['family'] == family]

    def test_masked_means(self):
        for task in self.tasks('masked_mean'):
            config = task['metadata']['config']
            solve = trusted_function(task)
            expected = [0.0, 2.0] if config['axis'] == 'row' else [2.0, -2.0]
            self.assertEqual(solve([[2, -2], [2, None]]), expected)
            self.assertEqual(solve([[None, None]]),
                             [config['empty']] if config['axis'] == 'row' else [config['empty']] * 2)

    def test_softmax_stability_and_shift_invariance(self):
        for task in self.tasks('stable_softmax'):
            solve = trusted_function(task)
            values = solve([10000, 10001, 9998])
            shifted = solve([0, 1, -2])
            for left, right in zip(values, shifted):
                self.assertAlmostEqual(left, right)
            self.assertTrue(all(math.isfinite(x) for x in solve([10000, -10000])))
            if task['metadata']['config']['output'] == 'log':
                self.assertAlmostEqual(sum(math.exp(x) for x in values), 1)
                self.assertEqual(solve([5]), [0.0])
            else:
                self.assertAlmostEqual(sum(values), 1)
                self.assertEqual(solve([5]), [1.0])

    def test_gradient_norm_and_direction(self):
        for task in self.tasks('gradient_clip'):
            config = task['metadata']['config']
            solve = trusted_function(task)
            vector = solve([3, -4])
            expected_norm = {'l1': 7, 'l2': 5, 'linf': 4}[config['norm']]
            scale = min(1, config['limit'] / expected_norm)
            self.assertAlmostEqual(vector[0], 3 * scale)
            self.assertAlmostEqual(vector[1], -4 * scale)
            self.assertEqual(solve([0, 0]), [0, 0])

    def test_padding_direction_and_cropping(self):
        for task in self.tasks('sequence_pad'):
            c = task['metadata']['config']
            solve = trusted_function(task)
            width = c['width']
            long = list(range(10))
            expected_crop = list(range(width)) if c['keep'] == 'first' else list(range(10 - width, 10))
            expected_short = [-1] * (width - 1) + [9] if c['side'] == 'left' else [9] + [-1] * (width - 1)
            self.assertEqual(solve([long, [9], []]), [expected_crop, expected_short, [-1] * width])

    def test_group_reductions(self):
        for task in self.tasks('group_reduce'):
            c = task['metadata']['config']
            solve = trusted_function(task)
            if c['lowercase']:
                expected = {'sum': 2, 'max': 5, 'count': 2, 'mean': 1}[c['operation']]
                self.assertEqual(solve([['a', -3], ['A', 5]]), [['a', expected]])
            else:
                expected = [['A', 1], ['a', 1]] if c['operation'] == 'count' else [['A', 5], ['a', -3]]
                self.assertEqual(solve([['a', -3], ['A', 5]]), expected)

    def test_interval_merge_bridge(self):
        for task in self.tasks('interval_union'):
            c = task['metadata']['config']
            solve = trusted_function(task)
            spans = [[0, 1], [2, 3]] if c['gap'] == 0 else [[0, 3]]
            expected = sum(b - a for a, b in spans) if c['output'] == 'length' else spans
            self.assertEqual(solve([[2, 3], [0, 1], [0, 0]]), expected)

    def test_edit_distance_against_exhaustive_recursion(self):
        words = ['', 'a', 'b', 'ab', 'ba', 'aab', 'é']
        for task in self.tasks('edit_distance'):
            c = task['metadata']['config']
            solve = trusted_function(task)
            @lru_cache(None)
            def brute(a, b):
                if not a:
                    return len(b) * c['insert']
                if not b:
                    return len(a) * c['delete']
                return min(c['delete'] + brute(a[1:], b),
                           c['insert'] + brute(a, b[1:]),
                           (0 if a[0] == b[0] else c['replace']) + brute(a[1:], b[1:]))
            for a, b in itertools.product(words, repeat=2):
                self.assertEqual(solve(a, b), brute(a, b))

    def test_graph_reachability_order_and_direction(self):
        for task in self.tasks('graph_reachability'):
            c = task['metadata']['config']
            solve = trusted_function(task)
            expected = ({'distances': [-1, 0, 1, -1], 'count': 2, 'nodes': [1, 2], 'layers': [[1], [2]]}
                        if c['directed'] else
                        {'distances': [1, 0, 1, -1], 'count': 3, 'nodes': [0, 1, 2], 'layers': [[1], [0, 2]]})
            self.assertEqual(solve(4, [[0, 1], [1, 2], [1, 1], [1, 2]], 1), expected[c['output']])


if __name__ == '__main__':
    unittest.main()
