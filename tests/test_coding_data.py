"""Synthetic data/evidence only; no candidate or reference source is executed."""
from collections import Counter
from copy import deepcopy
import unittest
from unittest.mock import patch

from rsilab.core import digest
from rsilab import coding_data as cd
from rsi.datasets import SOURCE_HASHES
from rsi.mbpp_verification import convert_mbpp_task, convert_mbpp_tests, decode_value
from rsi.mbpp_verification_v2 import encode_value as encode_output


def task_fixture(tid='synthetic', tests=None, challenge=()):
    tests = tests or ['assert solve(3) == 5', 'assert solve(7) == 5']
    task = {'id': tid, 'family': 'cluster-' + tid, 'split': 'train', 'prompt': 'Calculate an integer result.',
            'test_list': tests, 'challenge_test_list': list(challenge), 'test_setup_code': '',
            'test_imports': [], 'entry_point': 'solve', 'metadata': {'source_row_sha256': 'b' * 64},
            **convert_mbpp_tests(tests, 'solve', challenge_test_list=challenge)}
    task['category'] = cd.category(task['prompt'])
    return task


def evidence(task, proposal, *, error_ids=(), review_excluded=()):
    reference_hash = 'e' * 64
    evaluator = {'synthetic_evaluator': 'f' * 64}
    original = {'candidate_sha256': reference_hash, 'source_tests_sha256': task['source_tests_sha256'],
                'verifier_version': 'mbpp-typed-v2', 'sandbox_id': 'synthetic-only',
                'evaluator_source_hashes': evaluator, 'passed': True, 'count': len(task['cases']),
                'total': len(task['cases']),
                'outputs': [{'ok': True, 'value': deepcopy(c['expected'])} for c in task['cases']]}
    results = [{'id': m['id'], 'reference_sha256': reference_hash, 'proposal_sha256': proposal['sha256'],
                'evaluator_source_hashes': evaluator, 'sandbox_id': 'synthetic-only',
                'output': {'ok': False, 'error': 'ValueError'} if m['id'] in error_ids
                else {'ok': True, 'value': ['int', 5]}}
               for m in proposal['mutations'] if m['id'] not in review_excluded]
    review = {'approved': True, 'task_sha256': digest(task), 'proposal_sha256': proposal['sha256'],
              'reference_sha256': reference_hash, 'reviewer': 'unit-test-fixture',
              'notes': 'Synthetic manually supplied evidence, no reference execution.',
              'approved_mutation_ids': [m['id'] for m in proposal['mutations'] if m['id'] not in review_excluded]}
    return dict(reference_sha256=reference_hash, original_result=original, mutation_results=results, review=review)


def pool_fixture():
    prompts = {'collections': 'Find an item in a list.', 'text': 'Count characters in a string.',
               'numeric': 'Calculate an integer result.', 'other': 'Return the supplied object.'}
    pool = {'dataset': cd.DATASET_ID, 'revision': cd.REVISION, 'config': 'full',
            'importer_version': cd.IMPORTER_VERSION, 'source_sha256': SOURCE_HASHES,
            'source_counts': {'train': 12, 'validation': 12, 'test': 500, 'prompt': 10},
            'pools': {'train': [], 'dev': []}, 'duplicate_clusters': []}
    number = 1000
    for split, source in [('train', 'train'), ('dev', 'validation')]:
        for category, prompt in prompts.items():
            for i in range(3):
                number += 1
                tid = f'fixture-{split}-{category}-{i}'
                t = task_fixture(tid)
                for k in ['cases', 'mbpp_compiler_version', 'source_tests_sha256', 'source_test_count', 'challenge_test_count', 'category']:
                    del t[k]
                t.update(verification_mode='python_assertions', prompt=prompt, split=split)
                t['metadata'].update(dataset=cd.DATASET_ID, revision=cd.REVISION, config='full',
                                     source_split=source, source_id=number, source_row_sha256=digest(tid))
                pool['pools'][split].append(t)
                pool['duplicate_clusters'].append({'id': t['family'], 'source_splits': [source], 'source_ids': [number]})
    pool['manifest_sha256'] = digest(pool)
    return pool


def selection_fixture():
    pool = pool_fixture()
    previous = [deepcopy(pool['pools']['dev'][0])]
    return cd.select_mbpp_tasks(pool, previous_tasks=previous, train_count=4, dev_count=4,
                                expected_pool_sha256=pool['manifest_sha256'])


class SelectionTests(unittest.TestCase):
    def test_balanced_deterministic_bounded_and_no_test_prompts(self):
        s = selection_fixture()
        self.assertEqual(s, selection_fixture())
        self.assertEqual(Counter(t['split'] for t in s['tasks']), {'train': 4, 'dev': 4})
        for split in ['train', 'dev']:
            self.assertEqual({t['category'] for t in s['tasks'] if t['split'] == split}, set(cd.CATEGORIES))
        self.assertEqual(len(cd.audit_pool(s)), 24)
        self.assertEqual(s['sealed_final']['count'], 500)
        self.assertEqual(s['sealed_final']['file_sha256'], SOURCE_HASHES['full/test-00000-of-00001.parquet'])
        self.assertFalse(s['sealed_final']['prompts_included'])
        self.assertFalse(s['ready_for_generation'])
        self.assertFalse(any(t['metadata']['coding_data']['previously_generated'] for t in s['tasks'] if t['split'] == 'dev'))

    def test_history_retention_diagnostic_duplicate_and_sealed_exclusions(self):
        pool = pool_fixture()
        historical = deepcopy(pool['pools']['train'][0]); historical['split'] = 'dev'
        retention = pool['pools']['train'][1]['id']
        pool['pools']['dev'][0]['id'] = 'mbpp-full-512'
        pool['pools']['train'][3]['id'] = 'mbpp-full-955'
        pool['pools']['train'][6]['prompt'] = 'Find graph reachability.'
        pool['manifest_sha256'] = digest({k:v for k,v in pool.items() if k != 'manifest_sha256'})
        s = cd.select_mbpp_tasks(pool, previous_tasks=[historical], train_excluded_ids=[retention],
                                train_count=4, dev_count=4, expected_pool_sha256=pool['manifest_sha256'])
        reasons = {r['id']: r['reason'] for r in s['exclusions']}
        self.assertEqual(reasons[historical['id']], 'historical_evaluation_leakage')
        self.assertEqual(reasons[retention], 'reserved_retention_task')
        self.assertEqual(reasons['mbpp-full-512'], 'posthoc_diagnostic_task')
        self.assertEqual(reasons['mbpp-full-955'], 'manual_cross_split_near_duplicate')
        self.assertNotIn(retention, {t['id'] for t in cd.audit_pool(s)})

    def test_pool_pin_and_duplicate_cluster_are_fail_closed(self):
        p = pool_fixture()
        with self.assertRaises(ValueError):
            cd.select_mbpp_tasks(p, previous_tasks=[p['pools']['dev'][0]], train_count=4, dev_count=4)
        p['duplicate_clusters'][0]['source_splits'] = ['train', 'test']
        p['manifest_sha256'] = digest({k:v for k,v in p.items() if k != 'manifest_sha256'})
        with self.assertRaises(ValueError):
            cd.select_mbpp_tasks(p, previous_tasks=[p['pools']['dev'][0]], train_count=4, dev_count=4,
                                 expected_pool_sha256=p['manifest_sha256'])


class MutationTests(unittest.TestCase):
    def test_proposals_distinct_bounded_deterministic_and_expectation_free(self):
        task = task_fixture(); before = deepcopy(task)
        proposal = cd.propose_mutations(task)
        self.assertEqual(proposal, cd.propose_mutations(task))
        self.assertEqual(task, before)
        self.assertTrue(3 <= len(proposal['mutations']) <= 12)
        identities = [digest([m['args'], m['kwargs']]) for m in proposal['mutations']]
        self.assertEqual(len(identities), len(set(identities)))
        originals = {digest([c['args'], c['kwargs']]) for c in task['cases']}
        self.assertFalse(set(identities) & originals)
        self.assertTrue(all('expected' not in m for m in proposal['mutations']))
        self.assertFalse(proposal['expectations_present'])
        with self.assertRaises(ValueError):
            cd.propose_mutations(task, max_mutations=24)

    def test_preserves_lengths_indices_sorted_tuples_sign_and_alphabet(self):
        task = task_fixture(tests=['assert solve([(1, 3, 7), (2, 4, 8)], 2) == 5'])
        for m in cd.propose_mutations(task)['mutations']:
            values, index = decode_value(m['args'])
            self.assertEqual(index, 2)
            self.assertEqual(len(values), 2)
            for row in values:
                self.assertIs(type(row), tuple)
                self.assertEqual(len(row), 3)
                self.assertEqual(list(row), sorted(row))
                self.assertTrue(all(x > 0 for x in row))
        task = task_fixture(tests=["assert solve('abc-ABC 123!') == 5"])
        for m in cd.propose_mutations(task)['mutations']:
            text = decode_value(m['args'])[0]
            self.assertEqual(len(text), 12)
            self.assertEqual(set(text), set('abc-ABC 123!'))

    def test_coupled_arrays_negative_floats_and_bools_are_not_mutated(self):
        for source in ['assert solve([1,2,3], [1,2], 2) == 5',
                       'assert solve(-2, True, 1.5) == 5']:
            self.assertEqual(cd.propose_mutations(task_fixture(tests=[source]))['mutations'], [])

    def test_probe_is_explicitly_non_authoritative_and_maps_outputs(self):
        task = task_fixture(); proposal = cd.propose_mutations(task)
        excluded = [proposal['mutations'][0]['id']]
        probe = cd.build_probe_task(task, proposal, approved_mutation_ids=[m['id'] for m in proposal['mutations'][1:]])
        self.assertTrue(probe['metadata']['reference_probe_only'])
        self.assertFalse(probe['metadata']['expectations_authoritative'])
        self.assertEqual(len(probe['cases']), len(proposal['mutations'])-1)
        self.assertTrue(all(c['expected'] == ['none', None] for c in probe['cases']))
        self.assertNotIn(excluded[0], probe['metadata']['probe_mutation_ids'])
        for c, m in zip(probe['cases'], proposal['mutations'][1:]):
            for k in ('args', 'kwargs', 'projections'):
                self.assertEqual(c[k], m[k])


class AuditTests(unittest.TestCase):
    def test_original_prefix_and_challenges_preserved_no_code_execution(self):
        task = task_fixture(tests=['assert solve(3) == 5'], challenge=['assert solve(7) == 5'])
        p = cd.propose_mutations(task); e = evidence(task,p)
        with patch('rsi.verification._run_sandbox', side_effect=AssertionError('no execution')):
            audit = cd.audit_reference_task(task,p,**e)
        self.assertTrue(audit['eligible'])
        self.assertEqual(audit['task']['cases'][:2], task['cases'])
        self.assertEqual(audit['task']['test_list'], task['test_list'])
        self.assertEqual(audit['task']['challenge_test_list'][0], task['challenge_test_list'][0])
        self.assertNotEqual(audit['task']['source_tests_sha256'], task['source_tests_sha256'])

    def test_failed_calibration_is_excluded_and_cannot_run_probes(self):
        t = task_fixture(); p = cd.propose_mutations(t); e = evidence(t,p)
        e['original_result'].update(passed=False,count=0,
                                   outputs=[{'ok':True,'value':['int',99]} for _ in t['cases']])
        with self.assertRaises(ValueError):
            cd.audit_reference_task(t,p,**e)
        e['mutation_results']=[]
        a=cd.audit_reference_task(t,p,**e)
        self.assertFalse(a['eligible'])
        self.assertEqual(a['rejected'][0]['reason'],'original_reference_calibration_failed')

    def test_review_exclusions_missing_evidence_and_infrastructure(self):
        t=task_fixture(); p=cd.propose_mutations(t)
        excluded=[p['mutations'][0]['id']]; e=evidence(t,p,review_excluded=excluded)
        a=cd.audit_reference_task(t,p,**e)
        self.assertEqual(a['rejected'][0]['reason'],'input_domain_review_exclusion')
        for mutate in ['missing','duplicate','infrastructure','wrong_reference','wrong_review']:
            bad=deepcopy(e)
            if mutate=='missing':bad['mutation_results'].pop()
            elif mutate=='duplicate':bad['mutation_results'].append(deepcopy(bad['mutation_results'][0]))
            elif mutate=='infrastructure':bad['mutation_results'][0]['infrastructure_error']=True
            elif mutate=='wrong_reference':bad['mutation_results'][0]['reference_sha256']='0'*64
            else:bad['review']['proposal_sha256']='0'*64
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):cd.audit_reference_task(t,p,**bad)

    def test_minimum_three_valid_distinct_inputs_is_not_relaxed(self):
        t=task_fixture();p=cd.propose_mutations(t)
        e=evidence(t,p,error_ids=[m['id'] for m in p['mutations'][2:]])
        a=cd.audit_reference_task(t,p,**e)
        self.assertEqual(len(a['accepted']),2)
        self.assertFalse(a['eligible']);self.assertIsNone(a['task'])
        self.assertEqual(len(a['mutation_results']),len(p['mutations']))

    def test_extended_mapping_and_type_changes_are_rejected_without_coercion(self):
        t=task_fixture(tests=['assert solve(3) == {1: 5}', 'assert solve(7) == {1: 5}'])
        p=cd.propose_mutations(t);e=evidence(t,p)
        for r in e['mutation_results']:r['output']={'ok':True,'value':encode_output(Counter({1:5}))}
        a=cd.audit_reference_task(t,p,**e)
        self.assertFalse(a['eligible']);self.assertEqual(a['accepted'],[])
        for r in e['mutation_results']:r['output']={'ok':True,'value':['int',5]}
        self.assertFalse(cd.audit_reference_task(t,p,**e)['eligible'])

    def test_projection_applied_before_expectation_and_set_rendering_deterministic(self):
        t=task_fixture(tests=['assert sorted(solve(3)) == [1, 2]', 'assert sorted(solve(7)) == [1, 2]'])
        p=cd.propose_mutations(t);e=evidence(t,p)
        for r in e['mutation_results']:r['output']={'ok':True,'value':encode_output({2,1})}
        a=cd.audit_reference_task(t,p,**e)
        self.assertTrue(a['eligible'])
        self.assertTrue(all(decode_value(x['expected'])==[1,2] for x in a['accepted']))
        literal=cd._literal_text({'c','a','b'})
        self.assertEqual(literal,cd._literal_text(set(['b','c','a'])))


class FreezeTests(unittest.TestCase):
    def test_full_pool_required_and_prospective_fallback_replaces_failed_task(self):
        s=selection_fixture();pool=cd.audit_pool(s);audits=[]
        rejected=pool[0]['id']
        for t in pool:
            p=cd.propose_mutations(t);e=evidence(t,p)
            if t['id']==rejected:
                e['review']['approved']=False;e['mutation_results']=[]
            audits.append(cd.audit_reference_task(t,p,**e))
        with self.assertRaises(ValueError):cd.freeze_verified_dataset(s,audits[:-1])
        frozen=cd.freeze_verified_dataset(s,audits)
        self.assertEqual(frozen['split_counts'],{'train':4,'dev':4})
        self.assertNotIn(rejected,{t['id'] for t in frozen['tasks']})
        self.assertEqual(frozen['audit_exclusions'][0]['id'],rejected)
        self.assertTrue(frozen['ready_for_generation']);self.assertFalse(frozen['ready_for_training'])
        self.assertEqual(frozen['sealed_final'],s['sealed_final'])
        self.assertEqual(frozen,cd.freeze_verified_dataset(s,reversed(audits)))
        tampered=deepcopy(audits);tampered[-1]['task']['cases'][0]['expected']=['int',77]
        tampered[-1]['sha256']=digest({k:v for k,v in tampered[-1].items() if k!='sha256'})
        with self.assertRaises(ValueError):cd.freeze_verified_dataset(s,tampered)

    def test_insufficient_valid_cohort_fails_without_shrinking(self):
        s=selection_fixture();audits=[]
        for t in cd.audit_pool(s):
            p=cd.propose_mutations(t);e=evidence(t,p)
            e['review']['approved']=False;e['mutation_results']=[]
            audits.append(cd.audit_reference_task(t,p,**e))
        with self.assertRaises(ValueError):cd.freeze_verified_dataset(s,audits)


if __name__ == '__main__':
    unittest.main()
