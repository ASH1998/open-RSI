import ast
import copy
import inspect
import json
import types
import unittest
from unittest.mock import Mock, patch

from rsi import verification as verifier
from rsi.verification import extract_code, score_outputs, validate_code, values_match, verify_candidate


class VerificationTests(unittest.TestCase):
    def test_extract_reasoning_and_code(self):
        code = extract_code('<think>analysis</think>\n```python\ndef solve(x):\n    return x\n```')
        validate_code(code, 'solve')

    def test_reject_ambiguous_or_incomplete_response(self):
        for text in ['```python\ndef solve(): pass\n```\n```python\nx=1\n```', '<think>unfinished', 'This is prose']:
            with self.assertRaises((ValueError, SyntaxError)):
                validate_code(extract_code(text), 'solve')

    def test_reject_io_and_introspection(self):
        for code in ['import os\ndef solve(x): return x',
                     'def solve(x): return open(x).read()',
                     'def solve(x): return x.__class__',
                     'from math import *\ndef solve(x): return x']:
            with self.assertRaises(ValueError):
                validate_code(code, 'solve')

    def test_allow_numeric_function(self):
        validate_code('import math\ndef solve(xs):\n    return [math.exp(x) for x in xs]', 'solve')

    def test_mbpp_import_extension_does_not_change_original_policy(self):
        for module in ('re', 'string', 'operator', 'array'):
            with self.assertRaises(verifier.CandidatePolicyError):
                validate_code(f'import {module}\ndef solve(x): return x', 'solve')

    def test_nested_json_and_numeric_tolerance(self):
        self.assertTrue(values_match({'a': [1, 0.25]}, {'a': [1.0, 0.25000001]}))
        self.assertFalse(values_match([1], [1, 2]))
        self.assertFalse(values_match({'a': 1}, {'b': 1}))
        self.assertFalse(values_match(True, 1))
        self.assertFalse(values_match(0, False))
        self.assertFalse(values_match(float('nan'), float('nan')))
        self.assertFalse(values_match(float('inf'), float('inf')))

    def test_parent_scoring_rejects_forged_pass_flag(self):
        result = score_outputs([{'ok': True, 'value': 8, 'passed': True}], [{'args': [], 'expected': 9}])
        self.assertFalse(result['passed'])
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['errors'], ['case_0:wrong_output'])

    def test_output_count_is_exact(self):
        self.assertFalse(score_outputs([], [{'args': [], 'expected': 0}])['passed'])
        self.assertFalse(score_outputs({'passed': True}, [{'args': [], 'expected': 0}])['passed'])

    def test_missing_result_does_not_match_null(self):
        cases = [{'args': [], 'expected': None}]
        self.assertFalse(score_outputs([{'ok': True}], cases)['passed'])
        self.assertTrue(score_outputs([{'ok': True, 'value': None}], cases)['passed'])

    def test_integer_expectations_are_exact(self):
        self.assertFalse(values_match(1_000_001, 1_000_000))
        self.assertFalse(values_match(1_000_000.1, 1_000_000))
        self.assertTrue(values_match(3.0, 3))
        self.assertTrue(values_match(10 ** 400, 10 ** 400))
        self.assertFalse(values_match(10 ** 400 + 1, 10 ** 400))
        self.assertTrue(values_match(1.0000001, 1.0))

    def test_task_tolerance_is_used(self):
        cases = [{'args': [], 'expected': 1.0}]
        outputs = [{'ok': True, 'value': 1.01}]
        self.assertFalse(score_outputs(outputs, cases)['passed'])
        self.assertTrue(score_outputs(outputs, cases, abs_tol=0.02)['passed'])


class SandboxContractTests(unittest.TestCase):
    """Only mocked SDK objects: candidate/harness strings are never executed."""

    def setUp(self):
        self.task = {'entry_point': 'solve', 'cases': [{'args': [3], 'expected': 9}]}
        self.code = 'def solve(x):\n    return x * x'
        self.sandbox = Mock(object_id='sb-local-mock', returncode=0)
        self.sandbox.stdout = iter(['[{"ok":true,', '"value":9}]\n'])
        self.create = Mock(return_value=self.sandbox)
        self.image = Mock()
        self.modal = types.SimpleNamespace(
            Sandbox=types.SimpleNamespace(create=self.create),
            Image=types.SimpleNamespace(debian_slim=Mock(return_value=self.image)))
        self.patch = patch.dict('sys.modules', {'modal': self.modal})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_candidate(self, **kwargs):
        return verify_candidate(self.code, self.task, app='mock-app', **kwargs)

    def test_isolation_arguments_and_parent_only_expected_values(self):
        self.task['cases'][0]['expected'] = 'EXPECTED-ONLY-IN-PARENT'
        result = self.run_candidate()
        self.assertFalse(result['passed'])
        args, kwargs = self.create.call_args
        payload = json.loads(args[5])
        self.assertEqual(set(payload), {'code', 'entry_point', 'inputs'})
        self.assertEqual(payload['inputs'], [[3]])
        self.assertNotIn('EXPECTED-ONLY-IN-PARENT', '\n'.join(args))
        self.assertEqual(kwargs['cpu'], (0.125, 0.125))
        self.assertEqual(kwargs['memory'], (512, 512))
        self.assertEqual(kwargs['timeout'], 30)
        self.assertTrue(kwargs['block_network'])
        self.assertFalse(kwargs['include_oidc_identity_token'])
        self.assertEqual(kwargs['secrets'], [])
        self.assertEqual(kwargs['volumes'], {})
        self.assertEqual(kwargs['network_file_systems'], {})
        self.assertEqual(kwargs['env'], {})
        self.assertEqual(kwargs['runtime'], 'gvisor')
        self.assertEqual(kwargs['app'], 'mock-app')
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_success_preserves_bounded_outputs_and_provenance(self):
        result = self.run_candidate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['outputs'], [{'ok': True, 'value': 9}])
        self.assertEqual(result['sandbox_id'], 'sb-local-mock')
        self.assertEqual(result['verifier_version'], verifier.VERIFIER_VERSION)
        self.assertEqual(len(result['candidate_sha256']), 64)
        self.assertGreaterEqual(result['duration_seconds'], 0)
        self.sandbox.wait.assert_called_once()

    def test_invalid_tasks_never_create_a_sandbox(self):
        valid = copy.deepcopy(self.task)
        bad_tasks = [None, {}, {'entry_point': 'solve', 'cases': None}]
        for change in [
            {'cases': []}, {'cases': [{}]}, {'cases': [None]},
            {'cases': [{'args': [], 'expected': float('nan')}]},
            {'cases': [{'args': {}, 'expected': 0}]},
            {'cases': [{'args': [float('inf')], 'expected': 0}]},
            {'entry_point': None}, {'tolerance': None},
            {'tolerance': {'rel_tol': -1}}, {'tolerance': {'abs_tol': float('inf')}},
            {'tolerance': {'abs_tol': True}}, {'tolerance': {'typo': 1}},
            {'tolerance': {'rel_tol': 10 ** 400}},
        ]:
            bad_tasks.append({**valid, **change})
        for task in bad_tasks:
            with self.subTest(task=task):
                result = verify_candidate(self.code, task, 'mock-app')
                self.assertEqual(result['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_raw_assertions_and_unknown_modes_never_launch(self):
        for mode in ('python_assertions', 'unknown'):
            self.task['verification_mode'] = mode
            self.assertEqual(self.run_candidate()['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_invalid_timeouts_never_create_a_sandbox(self):
        for timeout in [True, 9, 31, 30.0, None]:
            self.assertEqual(self.run_candidate(timeout=timeout)['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_policy_and_syntax_errors_are_distinct_and_free(self):
        self.code = 'import os\ndef solve(x): return x'
        self.assertEqual(self.run_candidate()['error_kind'], 'candidate_policy')
        self.code = 'def solve('
        self.assertEqual(self.run_candidate()['error_kind'], 'invalid_candidate')
        self.create.assert_not_called()

    def test_payload_limit_precedes_creation(self):
        self.task['cases'][0]['args'] = ['x' * verifier.MAX_PAYLOAD_BYTES]
        self.assertEqual(self.run_candidate()['error_kind'], 'invalid_candidate')
        self.create.assert_not_called()

    def test_provider_value_error_is_infrastructure_not_candidate_failure(self):
        self.create.side_effect = ValueError('secret-provider-error')
        result = self.run_candidate()
        self.assertTrue(result['infrastructure_error'])
        self.assertEqual(result['error_kind'], 'infrastructure')
        self.assertNotIn('secret-provider-error', str(result))
        self.create.assert_called_once()
        self.sandbox.terminate.assert_not_called()

    def test_wait_error_still_terminates(self):
        self.sandbox.wait.side_effect = RuntimeError('secret')
        result = self.run_candidate()
        self.assertFalse(result['passed'])
        self.assertTrue(result['infrastructure_error'])
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_read_error_still_terminates(self):
        def broken_stream():
            yield '['
            raise RuntimeError('secret')
        self.sandbox.stdout = broken_stream()
        self.assertTrue(self.run_candidate()['infrastructure_error'])
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_cleanup_failure_cannot_report_success(self):
        self.sandbox.terminate.side_effect = RuntimeError('secret')
        result = self.run_candidate()
        self.assertFalse(result['passed'])
        self.assertEqual(result['count'], 1)
        self.assertTrue(result['infrastructure_error'])
        self.assertNotIn('secret', str(result))

    def test_output_limit_stops_reading_and_terminates(self):
        def oversized_stream():
            yield 'x' * (verifier.MAX_OUTPUT_BYTES + 2)
            self.fail('oversized stream should not be consumed further')
        self.sandbox.stdout = oversized_stream()
        result = self.run_candidate()
        self.assertEqual(result['errors'], ['output_too_large'])
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_invalid_output_is_candidate_failure(self):
        for raw in ['not json', '[NaN]', '[' * 1000 + '0' + ']' * 1000,
                    '{"error": []}', '{"passed":true}', '[]']:
            with self.subTest(raw=raw[:40]):
                self.sandbox.stdout = iter([raw])
                result = self.run_candidate()
                self.assertFalse(result['passed'])
                self.assertEqual(result['error_kind'], 'candidate_execution')
                self.assertNotIn('infrastructure_error', result)

    def test_supervisor_failures_are_preserved(self):
        for error in ['candidate_process_failed', 'candidate_timeout']:
            self.sandbox.stdout = iter([json.dumps({'error': error})])
            self.assertEqual(self.run_candidate()['errors'], [error])

    def test_nonzero_exit_never_scores_stdout(self):
        self.sandbox.returncode = 1
        result = self.run_candidate()
        self.assertFalse(result['passed'])
        self.assertEqual(result['errors'], ['sandbox_process_failed'])

    def test_per_task_tolerance_reaches_scoring(self):
        self.task['cases'][0]['expected'] = 9.0
        self.task['tolerance'] = {'abs_tol': 0.1, 'rel_tol': 0}
        self.sandbox.stdout = iter(['[{"ok":true,"value":9.05}]'])
        self.assertTrue(self.run_candidate()['passed'])


class StaticCompatibilityTests(unittest.TestCase):
    def test_task_suite_manifests_and_reference_sources_fit_policy(self):
        from rsi.tasks import SPLIT_FAMILIES, TASK_IMPORTS, build_tasks, reference_solution
        self.assertEqual(set(TASK_IMPORTS), verifier.ALLOWED_IMPORTS)
        for split in SPLIT_FAMILIES:
            for task in build_tasks(split, count_per_family=8):
                with self.subTest(task=task['id']):
                    verifier._validate_task(task, 30)
                    # Parse trusted source strings; never exec candidate code locally.
                    validate_code(extract_code(reference_solution(task)), task['entry_point'])

    def test_harness_sources_parse_without_execution(self):
        ast.parse(verifier._CHILD, feature_version=(3, 11))
        ast.parse(verifier._SUPERVISOR, feature_version=(3, 11))

    def test_installed_modal_sdk_accepts_call_shape_without_rpc(self):
        try:
            import modal
            from modal.io_streams import StreamReader
        except ImportError:
            self.skipTest('Modal SDK not installed')
        inspect.signature(modal.Sandbox.create).bind(
            'python', '-I', '-S', '-c', verifier._SUPERVISOR, '{}', verifier._CHILD,
            app=object(), image=object(), cpu=(0.125, 0.125), memory=(512, 512),
            timeout=30, block_network=True, secrets=[], volumes={},
            network_file_systems={}, env={}, runtime='gvisor', include_oidc_identity_token=False)
        inspect.signature(modal.Sandbox.wait).bind(object())
        inspect.signature(modal.Sandbox.terminate).bind(object(), wait=True)
        self.assertTrue(hasattr(StreamReader, '__iter__'))


if __name__ == '__main__':
    unittest.main()
