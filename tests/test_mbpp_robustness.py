"""Static task data only: never execute saved candidate/reference implementations."""
import copy
import hashlib
import json
import math
import unittest
from unittest.mock import patch

from rsi import mbpp_robustness as robustness
from rsi import mbpp_verification as v1
from rsi import mbpp_verification_v2 as v2


# Exact original source assertions, reproduced with MBPP CC-BY-4.0 attribution
# and immutable revision in docs/MBPP_ROBUSTNESS_CASES.md. No reference code.
ORIGINAL_TESTS = {
    512: [
        'assert count_element_freq((5, 6, (5, 6), 7, (8, 9), 9) ) == {5: 2, 6: 2, 7: 1, 8: 1, 9: 2}',
        'assert count_element_freq((6, 7, (6, 7), 8, (9, 10), 10) ) == {6: 2, 7: 2, 8: 1, 9: 1, 10: 2}',
        'assert count_element_freq((7, 8, (7, 8), 9, (10, 11), 11) ) == {7: 2, 8: 2, 9: 1, 10: 1, 11: 2}',
    ],
    520: ['assert get_lcm([2, 7, 3, 9, 4]) == 252',
          'assert get_lcm([1, 2, 8, 3]) == 24',
          'assert get_lcm([3, 8, 4, 10, 5]) == 120'],
    557: ['assert toggle_string("Python")==("pYTHON")',
          'assert toggle_string("Pangram")==("pANGRAM")',
          'assert toggle_string("LIttLE")==("liTTle")'],
    558: ['assert digit_distance_nums(1,2) == 1',
          'assert digit_distance_nums(23,56) == 6',
          'assert digit_distance_nums(123,256) == 7'],
    568: ['assert empty_list(5)==[{},{},{},{},{}]',
          'assert empty_list(6)==[{},{},{},{},{},{}]',
          'assert empty_list(7)==[{},{},{},{},{},{},{}]'],
    576: ['assert is_Sub_Array([1,4,3,5],[1,2],4,2) == False',
          'assert is_Sub_Array([1,2,1],[1,2,1],3,3) == True',
          'assert is_Sub_Array([1,0,2,2],[2,2,0],4,3) ==False'],
    928: ["assert change_date_format('2026-01-02')=='02-01-2026'",
          "assert change_date_format('2021-01-04')=='04-01-2021'",
          "assert change_date_format('2030-06-06')=='06-06-2030'"],
}


def fixtures():
    tasks = []
    for number, (entry, row_hash, _) in robustness.SOURCE_CONTRACTS.items():
        tests = ORIGINAL_TESTS[number].copy()
        tasks.append({
            'id': f'mbpp-full-{number}', 'prompt': f'fixture prompt for {entry}',
            'split': 'train' if number == 928 else 'dev', 'family': f'fixture-{number}',
            'test_list': tests, 'test_setup_code': '', 'test_imports': [],
            'challenge_test_list': [],
            'metadata': {'dataset': robustness.DATASET, 'revision': robustness.REVISION,
                         'config': 'full', 'source_id': number, 'source_row_sha256': row_hash,
                         'license': 'CC-BY-4.0', 'task_sha256': 'a' * 64},
            **v1.convert_mbpp_tests(tests, entry),
        })
    return tasks


def decoded_cases(task):
    return [(v1.decode_value(c['args']), v1.decode_value(c['expected'])) for c in task['cases']]


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.originals = fixtures()
        self.tasks = robustness.build_tasks(self.originals)
        self.by_number = {t['metadata']['source_id']: t for t in self.tasks}

    def test_combined_counts_and_original_case_prefix(self):
        counts = {512: 6, 520: 6, 557: 6, 558: 6, 568: 4, 576: 10, 928: 5}
        self.assertEqual(len(self.tasks), 7)
        self.assertEqual(sum(len(t['cases']) for t in self.tasks), 64)
        for old, task in zip(self.originals, self.tasks):
            self.assertEqual(task['cases'][:3], old['cases'])
            self.assertEqual(task['test_list'][:3], old['test_list'])
            self.assertEqual(len(task['cases']), 3 + counts[task['metadata']['source_id']])
            v1._validate_task(task, 30)  # v2 uses exactly this task validator
            self.assertEqual(task['cases'], v1.convert_mbpp_tests(
                task['test_list'], task['entry_point'])['cases'])
            self.assertNotEqual(task['source_tests_sha256'], old['source_tests_sha256'])

    def test_deterministic_deep_copies_and_no_execution(self):
        before = copy.deepcopy(self.originals)
        with patch.object(v1.base, '_run_sandbox', side_effect=AssertionError('no execution')):
            self.assertEqual(self.tasks, robustness.build_tasks(reversed(self.originals)))
        self.assertEqual(self.originals, before)
        self.tasks[0]['cases'][0]['expected'].append('mutation')
        self.tasks[0]['metadata']['license'] = 'mutation'
        self.assertEqual(self.originals, before)

    def test_provenance_hashes_and_diagnostic_only_flags(self):
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        for old, task in zip(self.originals, self.tasks):
            info = task['metadata']['robustness']
            self.assertEqual(task['id'], old['id'] + '-robustness-v1')
            self.assertEqual(task['metadata']['original_task_id'], old['id'])
            self.assertEqual(info['original_task_sha256'], digest(old))
            self.assertEqual(info['original_source_tests_sha256'], old['source_tests_sha256'])
            self.assertEqual(info['combined_cases_sha256'], digest(task['cases']))
            self.assertEqual(info['additional_assertions_sha256'], digest(task['test_list'][3:]))
            self.assertEqual(info['original_imported_task_sha256'], 'a' * 64)
            self.assertNotIn('task_sha256', task['metadata'])
            self.assertFalse(info['held_out_evidence'])
            self.assertFalse(info['training_label_eligible'])
            for field in ['prompt', 'entry_point', 'split', 'family']:
                self.assertEqual(task[field], old[field])

    def test_v2_scores_static_expectations_and_detects_changed_values(self):
        for task in self.tasks:
            # Transport hand-authored expected values, not a function invocation.
            outputs = [{'ok': True, 'value': v2.encode_value(expected)}
                       for _, expected in decoded_cases(task)]
            self.assertTrue(v2.score_mbpp_outputs(outputs, task['cases'])['passed'])
            outputs[-1]['value'] = v2.encode_value(None)
            score = v2.score_mbpp_outputs(outputs, task['cases'])
            self.assertFalse(score['passed'])
            self.assertEqual(score['count'], len(outputs) - 1)

    def test_rejects_missing_duplicate_and_altered_originals(self):
        for inputs in [self.originals[:-1], self.originals + self.originals[:1]]:
            with self.assertRaises(ValueError):
                robustness.build_tasks(inputs)
        for field in ['revision', 'source_row_sha256', 'source_id']:
            bad = copy.deepcopy(self.originals)
            bad[0]['metadata'][field] = 'changed'
            with self.subTest(field=field), self.assertRaises(ValueError):
                robustness.build_tasks(bad)
        for field in ['test_list', 'cases', 'source_tests_sha256', 'entry_point']:
            bad = copy.deepcopy(self.originals)
            if field == 'cases':
                bad[0][field][0]['expected'] = ['none', None]
            elif field == 'test_list':
                bad[0][field][0] = 'assert count_element_freq(()) == {}'
            else:
                bad[0][field] = 'changed'
            with self.subTest(field=field), self.assertRaises(ValueError):
                robustness.build_tasks(bad)

    def test_subarray_cases_have_independent_contiguous_window_answers(self):
        cases = decoded_cases(self.by_number[576])[3:]
        for (array, pattern, n, m), expected in cases:
            self.assertEqual((n, m), (len(array), len(pattern)))
            self.assertGreater(m, 0)
            # Independent specification check over static data, no saved code.
            self.assertEqual(expected, any(array[i:i + m] == pattern
                                           for i in range(max(0, n - m + 1))))
        answers = {tuple(args[0]) + ('/',) + tuple(args[1]): expected for args, expected in cases}
        self.assertFalse(answers[(1, 2, '/', 2, 1)])  # order, not multiset equality
        self.assertFalse(answers[(1, 9, 2, '/', 1, 2)])  # subsequence is insufficient
        self.assertTrue(answers[(8, 9, 1, 2, '/', 1, 2)])  # final possible start

    def test_numeric_static_answers_against_independent_math(self):
        for (values,), expected in decoded_cases(self.by_number[520])[3:]:
            self.assertGreaterEqual(len(values), 2)
            self.assertTrue(all(type(x) is int and x > 0 for x in values))
            self.assertEqual(expected, math.lcm(*values))
        for (left, right), expected in decoded_cases(self.by_number[558])[3:]:
            # Arithmetic digits rather than the reference's str/map approach.
            value, total = abs(left - right), 0
            while value:
                value, digit = divmod(value, 10)
                total += digit
            self.assertEqual(expected, total)

    def test_nested_tuple_manual_tallies(self):
        for (nested,), expected in decoded_cases(self.by_number[512])[3:]:
            pending, leaves = [nested], []
            while pending:
                value = pending.pop()
                if type(value) is tuple:
                    pending.extend(value)
                else:
                    leaves.append(value)
            self.assertEqual(expected, {value: leaves.count(value) for value in set(leaves)})

    def test_remaining_contracts_stay_in_bounded_unambiguous_domain(self):
        for (length,), expected in decoded_cases(self.by_number[568])[3:]:
            self.assertTrue(0 <= length <= 8)
            self.assertIs(type(expected), list)
            self.assertEqual(len(expected), length)
            self.assertTrue(all(type(value) is dict and not value for value in expected))
        for (text,), expected in decoded_cases(self.by_number[557])[3:]:
            self.assertTrue(text.isascii())
            translation = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz',
                                       'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
            self.assertEqual(text.translate(translation), expected)
        for (text,), expected in decoded_cases(self.by_number[928])[3:]:
            year, month, day = text.split('-')
            self.assertEqual((len(year), len(month), len(day)), (4, 2, 2))
            self.assertEqual(expected, day + '-' + month + '-' + year)


if __name__ == '__main__':
    unittest.main()
