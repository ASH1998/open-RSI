"""Local AST/data checks and mocked transport only; no dataset/candidate exec."""
import ast
import copy
import json
import types
import unittest
from unittest.mock import Mock, patch

from rsi import mbpp_verification as mbpp
from rsi import verification as base


class CodecTests(unittest.TestCase):
    def test_builtin_round_trips_preserve_container_types(self):
        values = [None, True, False, 0, -77, 1.25, 'café', [], (), set(), frozenset(), {},
                  [1, (2, 3), {4, 5}], {1: 'int key', (2, 3): frozenset({False, 'x'})}]
        for value in values:
            with self.subTest(value=value):
                restored = mbpp.decode_value(json.loads(json.dumps(mbpp.encode_value(value))))
                self.assertEqual(restored, value)
                self.assertIs(type(restored), type(value))

    def test_list_and_tuple_wire_values_differ(self):
        self.assertNotEqual(mbpp.encode_value([1, 2]), mbpp.encode_value((1, 2)))

    def test_set_encoding_is_deterministic(self):
        self.assertEqual(mbpp.encode_value({1, 'a', (2, 3)}), mbpp.encode_value({(2, 3), 'a', 1}))

    def test_no_custom_python_object_methods_run(self):
        class Trap:
            def __eq__(self, other):
                raise AssertionError('untrusted comparison called')

            def __iter__(self):
                raise AssertionError('untrusted iterator called')
        with self.assertRaises(ValueError):
            mbpp.encode_value(Trap())
        with self.assertRaises(ValueError):
            mbpp.decode_value(['object', Trap()])

    def test_malformed_wire_values_are_rejected(self):
        for value in [None, {}, ['int', True], ['bool', 1], ['float', float('inf')],
                      ['unknown', []], ['dict', [[['int', 1]]]],
                      ['dict', [[['int', 1], ['int', 2]], [['bool', True], ['int', 3]]]],
                      ['set', [['int', 1], ['int', 1]]], ['tuple', {}],
                      ['int', 1, 2], ['str', 3], ['none', 0]]:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                mbpp.decode_value(value)

    def test_complexity_and_finiteness_limits(self):
        cycle = []
        cycle.append(cycle)
        for value in [cycle, list(range(mbpp.MAX_VALUE_NODES + 1)),
                      1 << mbpp.MAX_INTEGER_BITS, 'x' * (mbpp.MAX_TEST_BYTES + 1),
                      float('nan'), float('inf'), complex(1, 2), b'bytes']:
            with self.subTest(kind=type(value)), self.assertRaises(ValueError):
                mbpp.encode_value(value)

    def test_maximum_typed_depth_fits_shared_json_transport(self):
        value = 1
        for _ in range(mbpp.MAX_VALUE_DEPTH):
            value = {'nested': value}
        raw = json.dumps([{'ok': True, 'value': mbpp.encode_value(value)}])
        parsed = base._parse_output(raw)
        self.assertEqual(mbpp.decode_value(parsed[0]['value']), value)


class CompilerTests(unittest.TestCase):
    def compile(self, source):
        return mbpp.convert_mbpp_tests([source])

    def test_direct_literal_arguments_and_expectation(self):
        task = self.compile('assert solve((1, 2), {3, 4}, key={7: -2.5}) == {1: (3, 4)}')
        self.assertEqual(task['entry_point'], 'solve')
        case = task['cases'][0]
        self.assertEqual(mbpp.decode_value(case['args']), ((1, 2), {3, 4}))
        self.assertEqual(mbpp.decode_value(case['kwargs']), {'key': {7: -2.5}})
        self.assertEqual(mbpp.decode_value(case['expected']), {1: (3, 4)})
        self.assertEqual(case['projections'], [])

    def test_reversed_equality(self):
        task = self.compile('assert (1, 2) == solve([1, 2])')
        self.assertEqual(mbpp.decode_value(task['cases'][0]['expected']), (1, 2))

    def test_safe_literal_constructors(self):
        task = self.compile('assert solve(set(), tuple([1, 2]), dict([(1, 2)])) == frozenset([3, 4])')
        self.assertEqual(mbpp.decode_value(task['cases'][0]['args']), (set(), (1, 2), {1: 2}))
        self.assertEqual(mbpp.decode_value(task['cases'][0]['expected']), frozenset({3, 4}))

    def test_parent_projections_preserve_order(self):
        task = self.compile('assert tuple(sorted(set(solve([1, 2])))) == (1, 2)')
        self.assertEqual(task['cases'][0]['projections'], ['set', 'sorted', 'tuple'])

    def test_all_tests_including_challenges_are_kept(self):
        task = mbpp.convert_mbpp_tests(['assert solve(1) == 2', 'assert solve(2) == 3'],
                                      challenge_test_list=['assert solve(0) == 1'])
        self.assertEqual(len(task['cases']), 3)
        self.assertEqual(task['source_test_count'], 2)
        self.assertEqual(task['challenge_test_count'], 1)
        self.assertEqual([c['source_test_kind'] for c in task['cases']], ['test', 'test', 'challenge'])

    def test_one_unsupported_challenge_rejects_whole_task(self):
        with self.assertRaises(mbpp.UnsupportedTest):
            mbpp.convert_mbpp_tests(['assert solve(1) == 2'], challenge_test_list=['assert solve(2) > 0'])

    def test_manifest_provenance_is_preserved_without_modifying_input(self):
        raw = {'verification_mode': 'python_assertions', 'entry_point': 'solve',
               'test_list': ['assert solve(1) == 2'], 'id': 'task-1',
               'metadata': {'revision': 'pinned'}, 'code': 'THIS MUST NEVER BE EXECUTED'}
        before = copy.deepcopy(raw)
        task = mbpp.convert_mbpp_task(raw)
        self.assertEqual(raw, before)
        self.assertEqual(task['metadata'], raw['metadata'])
        self.assertEqual(task['id'], raw['id'])
        self.assertEqual(task['verification_mode'], mbpp.VERIFICATION_MODE)
        self.assertEqual(task['code'], raw['code'])

    def test_source_hash_changes_with_challenge_tests(self):
        one = mbpp.convert_mbpp_tests(['assert solve(1) == 2'])
        two = mbpp.convert_mbpp_tests(['assert solve(1) == 2'], challenge_test_list=['assert solve(0) == 1'])
        self.assertNotEqual(one['source_tests_sha256'], two['source_tests_sha256'])

    def test_setup_and_imports_reject_without_execution(self):
        for options in [{'test_setup_code': 'raise RuntimeError("never")'},
                        {'test_setup_code': 'import math'},
                        {'test_imports': ['import math']}, {'test_imports': None}]:
            with self.subTest(options=options), self.assertRaises(mbpp.UnsupportedTest):
                mbpp.convert_mbpp_tests(['assert solve(1) == 2'], **options)

    def test_malicious_and_nonliteral_expressions_are_rejected(self):
        sources = [
            'assert solve(1) == __import__("os").getcwd()',
            'assert solve(open("/tmp/forbidden")) == 1',
            'assert solve(1) == solve(2)',
            'assert solve(x) == 1', 'assert solve(int) == 1',
            'assert solve([x for x in range(9)]) == []',
            'assert solve(1) == [0] * 999999999',
            'assert solve(1) == 2 ** 999999999',
            'assert solve(1) == eval("2")', 'assert solve(1) == (lambda: 2)()',
            'assert solve(1) == 1e999', 'assert solve(1) == object()',
            'assert solve(1) == {**{1:2}}', 'assert solve(*[1]) == 2',
            'assert solve(**{"x":1}) == 2', 'assert solve(1) == (x := 2)',
            'assert [solve(1)] == [2]', 'assert solve(1).real == 2',
            'assert getattr(solve(1), "x") == 2',
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(mbpp.UnsupportedTest):
                self.compile(source)

    def test_unsupported_assertion_shapes_are_rejected(self):
        for source in ['assert solve(1)', 'assert not solve(1)', 'assert solve(1) is True',
                       'assert solve(1) != 2', 'assert 0 < solve(1) < 3',
                       'assert solve(1) == 2, "message"',
                       'assert solve(1) == 2\nprint("side effect")',
                       'x = 2\nassert solve(1) == x', 'assert solve(1) == 2 == 2',
                       'assert sorted(solve(1), reverse=True) == [2]', 'not valid !!!']:
            with self.subTest(source=source), self.assertRaises(mbpp.UnsupportedTest):
                self.compile(source)

    def test_entry_point_must_agree_for_every_case(self):
        with self.assertRaises(mbpp.UnsupportedTest):
            mbpp.convert_mbpp_tests(['assert first(1) == 2', 'assert second(1) == 2'])
        with self.assertRaises(mbpp.UnsupportedTest):
            mbpp.convert_mbpp_tests(['assert first(1) == 2'], entry_point='second')

    def test_empty_and_oversized_tests_reject(self):
        for tests in [[], None, 'assert solve(1) == 2', [1],
                      ['assert solve(1) == 2'] * (base.MAX_CASES + 1),
                      ['assert solve(1) == ' + repr('x' * mbpp.MAX_TEST_BYTES)]]:
            with self.assertRaises(mbpp.UnsupportedTest):
                mbpp.convert_mbpp_tests(tests)

    def test_no_code_evaluation_functions_in_compiler(self):
        # The compiler entry points and literal walker contain no dynamic exec.
        import inspect
        for fn in (mbpp._literal, mbpp._parse_test, mbpp.convert_mbpp_tests, mbpp.convert_mbpp_task):
            tree = ast.parse(inspect.getsource(fn))
            calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
            self.assertTrue({'eval', 'exec', 'compile'}.isdisjoint(calls))


class ScoringTests(unittest.TestCase):
    def score(self, test, actual):
        task = mbpp.convert_mbpp_tests([test])
        return mbpp.score_mbpp_outputs([{'ok': True, 'value': mbpp.encode_value(actual)}], task['cases'])

    def test_python_container_equality_preserved(self):
        self.assertTrue(self.score('assert solve(0) == (1, 2)', (1, 2))['passed'])
        self.assertFalse(self.score('assert solve(0) == (1, 2)', [1, 2])['passed'])
        self.assertTrue(self.score('assert solve(0) == {1: "x"}', {1: 'x'})['passed'])
        self.assertFalse(self.score('assert solve(0) == {1: "x"}', {'1': 'x'})['passed'])

    def test_assertion_numeric_equality_has_no_added_tolerance(self):
        self.assertTrue(self.score('assert solve(0) == True', 1)['passed'])
        self.assertTrue(self.score('assert solve(0) == 2', 2.0)['passed'])
        self.assertFalse(self.score('assert solve(0) == 1.0', 1.00000001)['passed'])

    def test_result_projection_happens_in_parent(self):
        self.assertTrue(self.score('assert tuple(sorted(set(solve(0)))) == (1, 2)', [2, 1, 2])['passed'])
        self.assertFalse(self.score('assert set(solve(0)) == {1, 2}', [[1], [2]])['passed'])

    def test_forged_pass_missing_value_and_count_do_not_pass(self):
        cases = mbpp.convert_mbpp_tests(['assert solve(0) == None'])['cases']
        for outputs in [[{'ok': True}], {'passed': True}, [],
                        [{'ok': True, 'value': ['none', None], 'passed': True}] * 2,
                        [{'ok': True, 'value': ['object', '__import__("os")'], 'passed': True}]]:
            self.assertFalse(mbpp.score_mbpp_outputs(outputs, cases)['passed'])
        self.assertTrue(mbpp.score_mbpp_outputs([{'ok': True, 'value': ['none', None]}], cases)['passed'])

    def test_wrong_value_cannot_override_parent_verdict(self):
        cases = mbpp.convert_mbpp_tests(['assert solve(0) == 9'])['cases']
        result = mbpp.score_mbpp_outputs([{'ok': True, 'value': ['int', 8], 'passed': True}], cases)
        self.assertFalse(result['passed'])
        self.assertEqual(result['errors'], ['case_0:wrong_output'])


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.task = mbpp.convert_mbpp_tests(['assert sorted(solve((1, 2))) == [1, 2]'])
        self.code = 'def solve(x): return x'
        self.sandbox = Mock(object_id='sb-mbpp-mock', returncode=0)
        self.sandbox.stdout = iter([json.dumps([{'ok': True, 'value': mbpp.encode_value((2, 1))}])])
        self.create = Mock(return_value=self.sandbox)
        self.modal = types.SimpleNamespace(Sandbox=types.SimpleNamespace(create=self.create),
                                          Image=types.SimpleNamespace(debian_slim=Mock()))
        patcher = patch.dict('sys.modules', {'modal': self.modal})
        patcher.start()
        self.addCleanup(patcher.stop)

    def verify(self):
        return base.verify_candidate(self.code, self.task, 'mock-app')

    def test_dispatch_and_payload_exclude_tests_expected_and_projection(self):
        self.task['prompt'] = 'PROMPT-NEVER-SENT'
        self.task['test_list'] = ['SOURCE-TEST-NEVER-SENT']
        self.task['code'] = 'REFERENCE-NEVER-SENT'
        self.task['metadata'] = {'secret': 'METADATA-NEVER-SENT'}
        result = self.verify()
        self.assertTrue(result['passed'])
        self.assertEqual(result['verifier_version'], mbpp.MBPP_VERIFIER_VERSION)
        args, kwargs = self.create.call_args
        payload = json.loads(args[5])
        self.assertEqual(set(payload), {'code', 'entry_point', 'inputs'})
        self.assertEqual(set(payload['inputs'][0]), {'args', 'kwargs'})
        self.assertEqual(mbpp.decode_value(payload['inputs'][0]['args']), ((1, 2),))
        for token in ['NEVER-SENT', 'expected', 'projections', 'source_test']:
            self.assertNotIn(token, args[5])
        self.assertTrue(kwargs['block_network'])
        self.assertEqual(kwargs['secrets'], [])
        self.assertEqual(kwargs['volumes'], {})
        self.assertEqual(kwargs['network_file_systems'], {})
        self.assertEqual(kwargs['env'], {})
        self.assertFalse(kwargs['include_oidc_identity_token'])
        self.assertEqual(kwargs['cpu'], (0.125, 0.125))
        self.assertEqual(kwargs['memory'], (512, 512))
        self.assertEqual(kwargs['runtime'], 'gvisor')
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_broader_pure_library_imports_allowed_only_in_mbpp(self):
        for module in ['re', 'string', 'operator', 'array']:
            base.validate_code(f'import {module}\ndef solve(x): return x', 'solve',
                               allowed_imports=mbpp.MBPP_ALLOWED_IMPORTS)
        for module in ['os', 'sys', 'subprocess', 'socket', 'pickle', 'pathlib']:
            self.code = f'import {module}\ndef solve(x): return x'
            self.assertEqual(self.verify()['error_kind'], 'candidate_policy')
        self.create.assert_not_called()

    def test_bad_compiled_manifest_rejects_before_spending(self):
        original = copy.deepcopy(self.task)
        changes = [{'mbpp_compiler_version': 'wrong'}, {'cases': []}, {'cases': [None]},
                   {'entry_point': 'class'}]
        for change in changes:
            self.task = {**original, **change}
            self.assertEqual(self.verify()['error_kind'], 'invalid_task')
        self.task = copy.deepcopy(original)
        self.task['cases'][0]['projections'] = ['eval']
        self.assertEqual(self.verify()['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_dropped_challenge_or_changed_case_identity_rejects(self):
        self.task = mbpp.convert_mbpp_tests(['assert solve(1) == 1'],
                                           challenge_test_list=['assert solve(2) == 2'])
        self.task['cases'].pop()
        self.assertEqual(self.verify()['error_kind'], 'invalid_task')
        self.task = mbpp.convert_mbpp_tests(['assert solve(1) == 1'])
        self.task['cases'][0]['source_test_index'] = 3
        self.assertEqual(self.verify()['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_cleanup_failure_remains_fail_closed(self):
        self.sandbox.terminate.side_effect = RuntimeError('secret')
        result = self.verify()
        self.assertFalse(result['passed'])
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['error_kind'], 'infrastructure')
        self.assertNotIn('secret', str(result))

    def test_malformed_typed_output_fails_and_terminates(self):
        self.sandbox.stdout = iter(['[{"ok":true,"value":["class", "arbitrary"]}]'])
        result = self.verify()
        self.assertFalse(result['passed'])
        self.assertEqual(result['error_kind'], 'candidate_execution')
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_oversized_output_stops_and_terminates(self):
        self.sandbox.stdout = iter(['x' * (base.MAX_OUTPUT_BYTES + 2)])
        self.assertEqual(self.verify()['errors'], ['output_too_large'])
        self.sandbox.terminate.assert_called_once_with(wait=True)

    def test_raw_assertions_cannot_use_typed_entrypoint(self):
        self.task['verification_mode'] = 'python_assertions'
        result = mbpp.verify_mbpp_candidate(self.code, self.task, 'mock-app')
        self.assertEqual(result['error_kind'], 'invalid_task')
        self.create.assert_not_called()

    def test_remote_source_parses_and_keeps_resource_limits(self):
        source = mbpp._child_source()
        ast.parse(source, feature_version=(3, 11))
        self.assertIn('resource.RLIMIT_CPU, (5, 5)', source)
        self.assertIn('resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)', source)
        self.assertIn('resource.RLIMIT_FSIZE, (65536, 65536)', source)
        self.assertNotIn('expected', source)
        self.assertNotIn('test_list', source)


if __name__ == '__main__':
    unittest.main()
