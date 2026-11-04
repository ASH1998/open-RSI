"""Diagnostic integration and paid-boundary failure tests, without cloud calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rsi import robustness_study as s
from rsilab.execution import ExecutionAborted

class RobustnessControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=s.ROOT/'work',prefix='robustness-test-')
        self.root=Path(self.temp.name);(self.root/'runs').mkdir()
    def tearDown(self):self.temp.cleanup()
    def test_infrastructure_result_saved_before_failure(self):
        report={};snapshots=[]
        result={'passed':False,'infrastructure_error':True,'error_kind':'infrastructure','sandbox_id':'test-safe-id'}
        with patch.object(s,'persist',side_effect=lambda r:snapshots.append(json.loads(json.dumps(r)))):
            with self.assertRaises(ExecutionAborted):
                s.run_group([{'id':'a'}],report,'candidates',lambda x:result)
        self.assertEqual(snapshots[0]['candidates'][0]['result'],result)
        self.assertEqual(report['candidates_execution']['issues'][0]['phase'],'validate')
    def test_raised_exception_retained_without_sensitive_message(self):
        def fail(x):raise ConnectionError('sensitive-provider-token')
        report={}
        with patch.object(s,'persist'):
            with self.assertRaises(ExecutionAborted):s.run_group([{'id':'a'}],report,'candidates',fail)
        self.assertEqual(report['candidates'][0]['exception_type'],'ConnectionError')
        self.assertNotIn('sensitive-provider-token',json.dumps(report))
    def test_reference_failure_is_recorded_and_blocks_success(self):
        report={}
        with patch.object(s,'persist'):
            with self.assertRaises(ExecutionAborted):
                s.run_group([{'id':'ref'}],report,'references',lambda x:{'passed':False},reference=True)
        self.assertFalse(report['references'][0]['result']['passed'])
        self.assertFalse(report.get('reference_audit_passed',False))
    def test_existing_failed_attempt_prevents_paid_duplicate(self):
        p=self.root/'runs'/'old';p.mkdir();(p/'report.json').write_text(json.dumps({'stage':s.STAGE,'status':'failed'}))
        with patch.object(s,'ROOT',self.root),patch.object(s,'load_plan',return_value={'sha256':'fixed'}),patch.object(s,'stage') as paid:
            with self.assertRaisesRegex(ValueError,'already exists'):s.run()
            paid.assert_not_called()
    def test_protocol_drift_rejected(self):
        plan={'fixed':True};plan['sha256']=s.digest(plan)
        p=self.root/'protocol.json';p.write_text(json.dumps(plan))
        with patch.object(s,'PLAN',p),patch.object(s,'expected_plan',return_value={'fixed':False}):
            with self.assertRaisesRegex(ValueError,'changed'):s.load_plan()
    def test_incomplete_summary_cannot_count_missing_as_failure(self):
        with patch.object(s,'inputs',return_value=([],[{'id':'ref'}],[],None,None)):
            with self.assertRaisesRegex(ValueError,'coverage'):
                s.summarize({'reference_audit_passed':True,'tasks':[],'reference_inputs':[{'id':'ref'}],'candidate_inputs':[],'references':[]},{})
    def test_result_persistence_failure_retains_summary_fallback(self):
        report={};calls=[]
        def persist(r):
            calls.append(1)
            if len(calls)==1:raise OSError('disk error')
        with patch.object(s,'persist',side_effect=persist):
            with self.assertRaises(ExecutionAborted):
                s.run_group([{'id':'a'}],report,'candidates',lambda x:{'passed':True})
        self.assertEqual(report['candidates_execution']['unpersisted_ids'],('a',))
        self.assertEqual(report['candidates_execution']['records'][0]['result'],{'passed':True})

if __name__=='__main__':unittest.main()
