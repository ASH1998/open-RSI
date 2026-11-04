"""Synthetic data and mocked SDK only; no saved candidate execution."""
import ast
from collections import Counter, OrderedDict, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

from rsi import mbpp_verification as v1
from rsi import mbpp_verification_v2 as v2
from rsi import verification as base


class CodecTests(unittest.TestCase):
    def roundtrip(self, value):
        return v2.decode_value(json.loads(json.dumps(v2.encode_value(value), allow_nan=False)))

    def test_original_values_have_identical_wire_encoding(self):
        fixtures = [None, True, False, 0, 1.5, 'café', [], (), set(), frozenset(), {},
                    {1: ['a', (2, False)], (3, 4): {5, 6}}]
        for value in fixtures:
            with self.subTest(value=value):
                self.assertEqual(v1.encode_value(value), v2.encode_value(value))
                self.assertEqual(self.roundtrip(value), value)
                self.assertIs(type(self.roundtrip(value)), type(value))

    def test_exact_mapping_types_survive_roundtrip(self):
        for value in [OrderedDict([(2, 'b'), (1, 'a')]), defaultdict(list, {3: [4]}),
                      Counter({1: 2, 3: 0, 4: -1})]:
            restored = self.roundtrip(value)
            self.assertIs(type(restored), type(value))
            self.assertEqual(restored, value)
            self.assertEqual(list(restored), list(value))

    def test_nested_mapping_types_and_nonstring_keys(self):
        value = (OrderedDict([((1, 2), Counter({3: 2}))]),
                 [defaultdict(list, {False: OrderedDict([(7, [8])])})])
        restored = self.roundtrip(value)
        self.assertEqual(restored, value)
        self.assertIs(type(restored[0]), OrderedDict)
        self.assertIs(type(restored[0][(1, 2)]), Counter)
        self.assertIs(type(restored[1][0]), defaultdict)
        self.assertIs(type(restored[1][0][False]), OrderedDict)

    def test_ordered_dict_uses_current_order_after_move(self):
        value = OrderedDict([(1, 'a'), (2, 'b'), (3, 'c')])
        value.move_to_end(1)
        self.assertEqual(list(self.roundtrip(value)), [2, 3, 1])

    def test_ordered_dict_equality_is_type_sensitive_as_in_python(self):
        first = self.roundtrip(OrderedDict([(1, 'a'), (2, 'b')]))
        second = self.roundtrip(OrderedDict([(2, 'b'), (1, 'a')]))
        self.assertNotEqual(first, second)
        self.assertEqual(first, {2: 'b', 1: 'a'})
        self.assertEqual(second, {1: 'a', 2: 'b'})

    def test_default_factory_is_not_called_serialized_or_restored(self):
        def factory():
            self.fail('default factory must never execute')
        value = defaultdict(factory, {'a': 1})
        wire = v2.encode_value(value)
        self.assertEqual(wire, ['default_dict', [[['str', 'a'], ['int', 1]]]])
        restored = self.roundtrip(value)
        self.assertIsNone(restored.default_factory)
        self.assertEqual(restored, {'a': 1})
        with self.assertRaises(KeyError):
            restored['missing']

    def test_counter_zero_and_negative_counts_are_not_normalized_away(self):
        full = self.roundtrip(Counter(a=1, b=0, c=-2))
        self.assertEqual(dict(full), {'a': 1, 'b': 0, 'c': -2})
        zero = self.roundtrip(Counter(a=1, b=0))
        self.assertEqual(zero, Counter(a=1))
        self.assertNotEqual(zero, {'a': 1})
        self.assertEqual(zero, {'a': 1, 'b': 0})

    def test_counter_counts_are_mapping_values_not_counted_pairs(self):
        value = Counter({(1, 2): 3, 'x': -4})
        restored = self.roundtrip(value)
        self.assertEqual(dict(restored), {(1, 2): 3, 'x': -4})

    def test_non_numeric_counter_values_remain_python_compatible(self):
        value = Counter({'x': [1, 2]})
        self.assertEqual(self.roundtrip(value), {'x': [1, 2]})

    def test_counter_instance_method_overrides_are_not_traversed(self):
        value = Counter(a=2)
        value.items = lambda: self.fail('untrusted instance items method called')
        self.assertEqual(self.roundtrip(value), {'a': 2})

    def test_custom_subclasses_and_metaclass_hooks_are_rejected_without_calls(self):
        class TrapMeta(type):
            def __hash__(self):
                raise AssertionError('metaclass hash hook called')

            def __eq__(self, other):
                raise AssertionError('metaclass equality hook called')

        class CustomDict(dict, metaclass=TrapMeta):
            def items(self):
                raise AssertionError('items hook called')

            def __len__(self):
                raise AssertionError('len hook called')

        class CustomOrdered(OrderedDict):
            def __iter__(self):
                raise AssertionError('iterator hook called')

        class CustomCounter(Counter):
            pass

        class CustomDefault(defaultdict):
            pass

        class CustomList(list):
            pass

        for value in [CustomDict(a=1), CustomOrdered(a=1), CustomCounter(a=1),
                      CustomDefault(list), CustomList([1]), lambda: 1, object(), {}.keys()]:
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                v2.encode_value(value)

    def test_unknown_tags_and_factory_payloads_are_rejected(self):
        for wire in [['collections.OrderedDict', []], ['object', {'class': 'Counter'}],
                     ['default_dict', [], 'factory'], ['default_dict', {'factory': 'eval'}],
                     ['counter', {'items': []}], ['ordered_dict', [[['str', 'x']]]]]:
            with self.subTest(wire=wire), self.assertRaises((ValueError, TypeError)):
                v2.decode_value(wire)

    def test_duplicate_mapping_keys_are_rejected_for_all_tags(self):
        pairs = [[['int', 1], ['int', 2]], [['bool', True], ['int', 3]]]
        for tag in ('dict', 'ordered_dict', 'default_dict', 'counter'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                v2.decode_value([tag, pairs])

    def test_depth_node_numeric_and_string_limits_are_unchanged(self):
        self.assertEqual(v2.MAX_VALUE_DEPTH, v1.MAX_VALUE_DEPTH)
        self.assertEqual(v2.MAX_VALUE_NODES, v1.MAX_VALUE_NODES)
        self.assertEqual(v2.MAX_INTEGER_BITS, v1.MAX_INTEGER_BITS)
        self.assertEqual(v2.MAX_TEST_BYTES, v1.MAX_TEST_BYTES)
        cycle = defaultdict(list)
        cycle['cycle'] = cycle
        for value in [cycle, Counter({i: 1 for i in range(v2.MAX_VALUE_NODES)}),
                      1 << v2.MAX_INTEGER_BITS, 'x' * (v2.MAX_TEST_BYTES + 1),
                      float('nan'), float('inf'), b'bytes', 1j]:
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                v2.encode_value(value)

    def test_maximum_nested_mapping_depth_fits_transport(self):
        value = 1
        for _ in range(v2.MAX_VALUE_DEPTH):
            value = OrderedDict([('nested', value)])
        raw = json.dumps([{'ok': True, 'value': v2.encode_value(value)}])
        parsed = base._parse_output(raw)
        self.assertEqual(v2.decode_value(parsed[0]['value']), value)


class ScoringTests(unittest.TestCase):
    def score(self, source, actual):
        cases = v1.convert_mbpp_tests([source])['cases']
        return v2.score_mbpp_outputs([{'ok': True, 'value': v2.encode_value(actual)}], cases)

    def test_mapping_subclasses_match_builtin_expectations(self):
        for value in [OrderedDict(a=1), defaultdict(list, {'a': 1}), Counter(a=1)]:
            self.assertTrue(self.score('assert solve(0) == {"a": 1}', value)['passed'])
        self.assertTrue(self.score('assert solve(0) == [{}, {}]', [OrderedDict(), OrderedDict()])['passed'])

    def test_wrong_mapping_values_still_fail(self):
        for value in [OrderedDict(a=2), defaultdict(list, {'a': 2}), Counter(a=2)]:
            self.assertFalse(self.score('assert solve(0) == {"a": 1}', value)['passed'])

    def test_counter_zero_keys_do_not_relax_dict_equality(self):
        self.assertFalse(self.score('assert solve(0) == {"a": 1}', Counter(a=1, b=0))['passed'])
        self.assertTrue(self.score('assert solve(0) == {"a": 1, "b": 0}', Counter(a=1, b=0))['passed'])

    def test_projections_use_parent_decoded_values_and_preserve_order(self):
        value = OrderedDict([(3, 'c'), (1, 'a'), (2, 'b')])
        self.assertTrue(self.score('assert list(solve(0)) == [3, 1, 2]', value)['passed'])
        self.assertTrue(self.score('assert tuple(sorted(solve(0))) == (1, 2, 3)', value)['passed'])
        self.assertTrue(self.score('assert set(solve(0)) == {1, 2, 3}', value)['passed'])

    def test_original_equality_rules_unchanged(self):
        self.assertFalse(self.score('assert solve(0) == [1, 2]', (1, 2))['passed'])
        self.assertFalse(self.score('assert solve(0) == 1.0', 1.00000001)['passed'])
        self.assertTrue(self.score('assert solve(0) == True', 1)['passed'])

    def test_forged_pass_missing_value_and_invalid_count_never_pass(self):
        cases = v1.convert_mbpp_tests(['assert solve(0) == None'])['cases']
        for outputs in [[], {'passed': True}, [{'ok': True}],
                        [{'ok': True, 'value': ['str', 'wrong'], 'passed': True}],
                        [{'ok': True, 'value': ['object', 'arbitrary']}]]:
            self.assertFalse(v2.score_mbpp_outputs(outputs, cases)['passed'])

    def test_error_stages_distinguish_decode_projection_and_wrong_value(self):
        cases = v1.convert_mbpp_tests(['assert set(solve(0)) == {1, 2}'])['cases']
        malformed = v2.score_mbpp_outputs([{'ok': True, 'value': ['object', []]}], cases)
        self.assertEqual(malformed['case_diagnostics'][0]['error_stage'], 'decode')
        projection = v2.score_mbpp_outputs([{'ok': True, 'value': v2.encode_value([[1]])}], cases)
        self.assertEqual(projection['case_diagnostics'], [
            {'case_index': 0, 'error_stage': 'projection_comparison', 'error': 'TypeError'}])
        wrong = v2.score_mbpp_outputs([{'ok': True, 'value': v2.encode_value([3])}], cases)
        self.assertEqual(wrong['case_diagnostics'][0]['error'], 'wrong_output')

    def test_raw_stage_diagnostics_are_allowlisted_and_messages_not_copied(self):
        cases = v1.convert_mbpp_tests(['assert solve(0) == 0'])['cases']
        output = {'ok': False, 'error': 'SECRET: path /credential', 'error_stage': 'unknown-private-detail'}
        result = v2.score_mbpp_outputs([output], cases)
        self.assertEqual(result['case_diagnostics'], [
            {'case_index': 0, 'error_stage': 'output', 'error': 'ExecutionError'}])
        self.assertNotIn('SECRET', str(result))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.task = v1.convert_mbpp_tests(['assert solve(2) == [{}, {}]'])
        self.code = 'from collections import OrderedDict\ndef solve(x): return [OrderedDict()] * x'
        self.sandbox = Mock(object_id='sb-v2-mock', returncode=0)
        self.sandbox.stdout = iter([json.dumps([{'ok': True, 'value': v2.encode_value([OrderedDict(), OrderedDict()])}])])
        self.create = Mock(return_value=self.sandbox)
        modal = types.SimpleNamespace(Sandbox=types.SimpleNamespace(create=self.create),
                                     Image=types.SimpleNamespace(debian_slim=Mock()))
        patcher = patch.dict('sys.modules', {'modal': modal})
        patcher.start()
        self.addCleanup(patcher.stop)

    def verify(self, **kwargs):
        return v2.verify_mbpp_candidate(self.code, self.task, 'mock-app', **kwargs)

    def test_original_task_unchanged_and_result_independently_versioned(self):
        before = copy.deepcopy(self.task)
        result = self.verify()
        self.assertTrue(result['passed'])
        self.assertEqual(self.task, before)
        self.assertEqual(result['verifier_version'], 'mbpp-typed-v2')
        self.assertEqual(result['source_compiler_version'], 'mbpp-typed-v1')
        self.assertEqual(result['source_tests_sha256'], self.task['source_tests_sha256'])
        self.assertEqual(result['candidate_sha256'], hashlib.sha256(self.code.encode()).hexdigest())
        self.assertEqual(result['evaluator_source_hashes'], v2.evaluator_source_hashes())

    def test_expected_tests_metadata_and_factory_are_absent_from_payload(self):
        self.task.update(test_list=['DO-NOT-SEND-TESTS'], prompt='DO-NOT-SEND-PROMPT',
                         code='DO-NOT-SEND-REFERENCE', metadata={'private': 'DO-NOT-SEND-METADATA'})
        self.verify()
        args, kwargs = self.create.call_args
        payload = json.loads(args[5])
        self.assertEqual(set(payload), {'code', 'entry_point', 'inputs'})
        self.assertEqual(set(payload['inputs'][0]), {'args', 'kwargs'})
        for value in ('DO-NOT-SEND', 'expected', 'projections', 'test_list', 'metadata'):
            self.assertNotIn(value, args[5])
        self.assertTrue(kwargs['block_network'])
        self.assertFalse(kwargs['include_oidc_identity_token'])
        self.assertEqual(kwargs['secrets'], [])
        self.assertEqual(kwargs['env'], {})
        self.assertEqual(kwargs['volumes'], {})
        self.assertEqual(kwargs['network_file_systems'], {})
        self.assertEqual(kwargs['runtime'], 'gvisor')
        self.assertEqual(kwargs['timeout'], 30)
        self.assertEqual(kwargs['cpu'], (0.125, 0.125))
        self.assertEqual(kwargs['memory'], (512, 512))
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_candidate_policy_still_blocks_dangerous_imports(self):
        self.code = 'import os\ndef solve(x): return x'
        self.assertEqual(self.verify()['error_kind'], 'candidate_policy')
        self.create.assert_not_called()

    def test_invalid_task_or_timeout_rejects_without_spending(self):
        self.assertEqual(self.verify(timeout=31)['error_kind'], 'invalid_task')
        self.task['cases'].clear()
        self.assertEqual(self.verify()['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_task_modes_are_not_silently_rewritten(self):
        for mode in ('python_assertions', 'mbpp_typed_v2'):
            self.task['verification_mode'] = mode
            self.assertEqual(self.verify()['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_oversized_output_stops_and_terminates(self):
        self.sandbox.stdout = iter(['x' * (base.MAX_OUTPUT_BYTES + 2)])
        self.assertEqual(self.verify()['errors'], ['output_too_large'])
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_forged_counter_wire_tag_is_only_untrusted_data(self):
        self.sandbox.stdout = iter([json.dumps([{'ok': True, 'value': ['counter', []], 'passed': True}])])
        self.assertFalse(self.verify()['passed'])
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_phase_diagnostics_do_not_override_scoring(self):
        self.sandbox.stdout = iter(['[{"ok":false,"error":"ValueError","error_stage":"encode","passed":true}]'])
        result = self.verify()
        self.assertFalse(result['passed'])
        self.assertEqual(result['outputs'][0]['error_stage'], 'encode')
        self.assertEqual(result['case_diagnostics'][0]['error_stage'], 'encode')

    def test_custom_subclass_calibration_reaches_transport_not_policy_rejection(self):
        fixture = next(c for c in v2.calibration_cases() if c['id'] == 'custom_subclass_rejected')
        self.code, self.task = fixture['code'], fixture['task']
        self.sandbox.stdout = iter(['[{"ok":false,"error":"ValueError","error_stage":"encode"}]'])
        result = self.verify()
        self.create.assert_called_once()
        self.assertFalse(result['passed'])
        self.assertEqual(result['error_kind'], 'candidate_execution')
        self.assertEqual(result['count'], fixture['expected_count'])
        self.assertEqual(result['case_diagnostics'][0]['error_stage'], fixture['expected_error_stage'])

    def test_provider_failure_is_sanitized_and_not_retried(self):
        self.create.side_effect = RuntimeError('secret provider detail')
        result = self.verify()
        self.assertEqual(result['error_kind'], 'infrastructure')
        self.assertNotIn('secret provider detail', str(result))
        self.create.assert_called_once()

    def test_termination_error_prevents_success(self):
        self.sandbox.terminate.side_effect = RuntimeError('secret')
        result = self.verify()
        self.assertFalse(result['passed'])
        self.assertEqual(result['count'], 1)
        self.assertTrue(result['infrastructure_error'])
        self.assertNotIn('secret', str(result))


class CalibrationAndProvenanceTests(unittest.TestCase):
    def test_v1_sources_remain_byte_identical(self):
        expected = {'rsi/verification.py': 'b6cd4334adf34678f7f35f908a38a14329ca9a81b6b4d557eb4de270868b0db4',
                    'rsi/mbpp_verification.py': '47efce04acdef807e54a49f1ecbd64942a31baa2ce9e7d7404fd62326e660bc4'}
        root = Path(__file__).resolve().parents[1]
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)

    def test_evaluator_inventory_includes_both_dependencies_and_child(self):
        hashes = v2.evaluator_source_hashes()
        self.assertEqual(set(hashes), {'rsi/mbpp_verification_v2.py', 'rsi/mbpp_verification.py',
                                      'rsi/verification.py', 'child_source'})
        self.assertTrue(all(len(h) == 64 for h in hashes.values()))
        self.assertEqual(hashes['child_source'], hashlib.sha256(v2._child_source().encode()).hexdigest())

    def test_child_is_static_python311_source_with_original_limits(self):
        source = v2._child_source()
        ast.parse(source, feature_version=(3, 11))
        for fragment in ['resource.RLIMIT_CPU, (5, 5)', 'resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)',
                         'resource.RLIMIT_FSIZE, (65536, 65536)', 'resource.RLIMIT_NOFILE, (32, 32)',
                         'resource.RLIMIT_NPROC, (16, 16)', 'candidate_call', '"error_stage": "encode"']:
            self.assertIn(fragment, source)
        self.assertNotIn('case["expected"]', source)
        self.assertNotIn('pickle', source.split('def decode_value')[0])

    def test_calibration_cases_are_static_valid_and_have_positive_negative_controls(self):
        cases = v2.calibration_cases()
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        self.assertEqual(sum(c['expected_passed'] for c in cases), 6)
        for case in cases:
            v1._validate_task(case['task'], 30)
            base.validate_code(base.extract_code(case['code']), 'solve', allowed_imports=v2.MBPP_ALLOWED_IMPORTS)
            self.assertEqual(case['expected_count'], len(case['task']['cases']) if case['expected_passed'] else 0)
        # No calibration source is exec'd here. Its behavior is audited remotely.


if __name__ == '__main__':
    unittest.main()
