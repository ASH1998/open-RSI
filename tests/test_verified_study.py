import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rsi import verified_study as s

class VerifiedStudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=s.ROOT/'work',prefix='verified-study-test-')
        self.root=Path(self.tmp.name);(self.root/'budget').mkdir();(self.root/'runs').mkdir()
        self.plan={'sha256':'x','policy':{'stages':['collect'],'per_stage_usd':5,'reservation_cap_usd':20}}
    def tearDown(self):self.tmp.cleanup()
    def test_prefix_cap_counts_failed_reservations_before_launch(self):
        (self.root/'budget/ledger.json').write_text(json.dumps({'reservations':[{'stage':s.PREFIX+'old','reserved_usd':20,'status':'failed'}]}))
        with patch.object(s,'ROOT',self.root),patch.object(s,'load_plan',return_value=(self.plan,{})),patch.object(s,'stage') as paid:
            with self.assertRaisesRegex(ValueError,'envelope'):
                with s.bounded_stage('collect'):pass
            paid.assert_not_called()
    def test_failed_stage_is_never_implicitly_retried(self):
        p=self.root/'runs/a';p.mkdir();(p/'report.json').write_text(json.dumps({'stage':s.PREFIX+'collect','status':'failed'}))
        with patch.object(s,'ROOT',self.root),patch.object(s,'load_plan',return_value=(self.plan,{})),patch.object(s,'stage') as paid:
            with self.assertRaisesRegex(ValueError,'already attempted'):
                with s.bounded_stage('collect'):pass
            paid.assert_not_called()
    def test_original_reference_failure_blocks_mutation_probes(self):
        task={'id':'a','cases':[{}]};item={'id':'a','task':task,'reference_code':'not executed','proposal':{},'reference_sha256':'x','review':{}}
        calls=[]
        def remote(items,**kw):calls.append(items);return [{'passed':False}] if items else []
        with patch.object(s,'verify_records',side_effect=remote),patch.object(s,'persist'),patch('rsilab.coding_data.audit_reference_task',return_value={'eligible':False}) as audit:
            result=s.reference_audit({'reference_items':[item]}, {},None)
        self.assertEqual(calls[1],[]);self.assertEqual(audit.call_args.kwargs['mutation_results'],[])
        self.assertFalse(result[0]['eligible'])
    def test_actual_adapter_must_match_trained_adapter(self):
        report={'rows':[],'rows_batches':[{'generation':{'gpu_name':'NVIDIA L40S','adapter_path':'/wrong'}}],
                'training':{'adapter_path':'/expected'}}
        with patch.object(s,'load_plan',return_value=({},{})):
            with self.assertRaisesRegex(ValueError,'adapter identity'):
                s.comparison_envelope(report,'rows',[],candidate=True)
    def test_parent_generation_must_not_use_an_adapter(self):
        report={'rows':[],'rows_batches':[{'generation':{'gpu_name':'NVIDIA L40S','adapter_path':'/unexpected'}}]}
        with patch.object(s,'load_plan',return_value=({},{})):
            with self.assertRaisesRegex(ValueError,'adapter identity'):
                s.comparison_envelope(report,'rows',[])
    def test_source_results_cannot_be_rewritten(self):
        path=self.root/'frozen.json';path.write_text('{"a": 1}')
        with self.assertRaisesRegex(ValueError,'overwrite'):s.save_immutable(path,{'a':2})
    def test_truncation_cannot_be_marked_successful(self):
        row={'generation':{'hit_token_limit':True},'verification':{'passed':True}}
        with self.assertRaisesRegex(ValueError,'Truncated'):s.trusted_rows([row])

if __name__=='__main__':unittest.main()
