"""Recovery boundary checks: no provider work or reservations."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
from unittest.mock import patch
from rsilab import digest
from rsilab.successor import SuccessorPolicy
from rsi import successor_recovery_v2 as recovery
from test_successor import protocol_fixture


class RecoveryTests(unittest.TestCase):
    def fixture(self):
        policy=SuccessorPolicy(train_count=20)
        protocol=protocol_fixture(policy)
        data={k:protocol['registries'][k] for k in ('train','dev','retention')}
        prepared={'sealed_final':protocol['registries']['sealed_final'][0],'prior_exposure_tasks':[]}
        frozen={'model':{'model_id':'test/model','revision':'a'*40},'source_hashes':{'worker.py':digest('worker')},'learned_adapter_sha256':digest('adapter')}
        return frozen,prepared,data,policy

    def preflight(self,frozen,prepared,data,policy):
        with patch.object(recovery,'plan',return_value=(frozen,prepared)),patch.object(recovery,'policy',return_value=policy):
            recovery.static_preflight(frozen,prepared,data)

    def test_valid_protocol_preflight_requires_no_provider(self):
        with patch.object(recovery,'workers',side_effect=AssertionError('Provider called')):
            self.preflight(*self.fixture())

    def test_wrong_categories_fail_before_reservation(self):
        frozen,prepared,data,policy=self.fixture()
        for t in data['train']:t['category']='text'
        with self.assertRaisesRegex(ValueError,'categories'):self.preflight(frozen,prepared,data,policy)

    def test_prior_exposure_rejected_before_reservation(self):
        frozen,prepared,data,policy=self.fixture();prepared['prior_exposure_tasks']=[deepcopy(data['train'][0])]
        with self.assertRaisesRegex(ValueError,'fresh'):self.preflight(frozen,prepared,data,policy)

    def test_duplicate_native_identity_rejected(self):
        frozen,prepared,data,policy=self.fixture()
        data['train'][1]['metadata']['source_id']=data['train'][0]['metadata']['source_id']
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.preflight(frozen,prepared,data,policy)

    def test_bad_evaluation_split_rejected(self):
        frozen,prepared,data,policy=self.fixture();data['dev'][0]['metadata']['source_split']='test'
        with self.assertRaisesRegex(ValueError,'split'):self.preflight(frozen,prepared,data,policy)

    def test_baseline_preflight_precedes_stage(self):
        frozen,prepared,data,policy=self.fixture();prepared.update(deepcopy(data),reuse={'sha256':'x'});data['reuse_sha256']='x'
        with patch.object(recovery,'plan',return_value=(frozen,prepared)),patch.object(recovery,'read',return_value=data),patch.object(recovery,'static_preflight',side_effect=ValueError('blocked')),patch.object(recovery,'stage',side_effect=AssertionError('reserved')):
            with self.assertRaisesRegex(ValueError,'blocked'):recovery.baseline()

    def test_dataset_edit_rejected_before_preflight(self):
        frozen,prepared,data,policy=self.fixture();prepared.update(deepcopy(data),reuse={'sha256':'x'});data['reuse_sha256']='x';data['train'][0]['prompt']='changed'
        with patch.object(recovery,'plan',return_value=(frozen,prepared)),patch.object(recovery,'read',return_value=data),patch.object(recovery,'stage',side_effect=AssertionError('reserved')):
            with self.assertRaisesRegex(ValueError,'dataset differs'):recovery.baseline()

    def test_worker_request_control_change_rejected(self):
        frozen,prepared,data,policy=self.fixture();cfg=recovery.config();cfg['generation']['max_new_tokens']=10000
        with patch.object(recovery,'config',return_value=cfg):
            with self.assertRaises(ValueError):self.preflight(frozen,prepared,data,policy)

    def test_namespace_and_budget_are_new_but_bounded(self):
        cfg=recovery.config()
        self.assertEqual(cfg['prefix'],recovery.PREFIX)
        self.assertNotEqual(cfg['prefix'],'successor-v1-')
        self.assertEqual(cfg['reservation_cap_usd'],20)
        self.assertEqual(cfg['per_stage_usd'],4)
        self.assertEqual(cfg['recovery_family_cap_usd'],25)
        self.assertEqual(cfg['max_gpu_calls_per_stage'],2)
        self.assertEqual(cfg['previous_failed_reservation_usd'],5)
        self.assertEqual(cfg['stages'],['baseline','teacher-original','teacher-learned','child-original','child-learned'])
        run_id='20261105T000000Z-'+recovery.PREFIX+'child-original-12345678'
        self.assertLessEqual(len(run_id),80)


class RecoveryFamilyBudgetTests(unittest.TestCase):
    def test_other_recovery_versions_count_toward_family_cap(self):
        import tempfile
        work=Path(__file__).resolve().parents[1]/'work'
        with tempfile.TemporaryDirectory(dir=work) as folder:
            with patch.object(recovery,'ROOT',Path(folder)),patch.object(recovery,'plan',return_value=({'source_hashes':{}},{})),patch.object(recovery,'reports',return_value=[]),patch.object(recovery,'read',return_value={'reservations':[{'stage':'successor-r1-baseline','reserved_usd':5},{'stage':'successor-r-other','reserved_usd':17}]}),patch.object(recovery,'config',return_value={'stages':['baseline'],'per_stage_usd':4,'reservation_cap_usd':20}),patch.object(recovery,'ws',side_effect=AssertionError('Reserved despite cap')):
                with self.assertRaisesRegex(ValueError,'family reservation cap'):
                    with recovery.stage('baseline'):pass

if __name__=='__main__':unittest.main()
