"""Launch guards protect the paid rescore boundary; no cloud calls here."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rsi import rescore_study as s

class RescoreLaunchGuards(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=s.ROOT/'work',prefix='rescore-guard-')
        self.root=Path(self.temp.name);(self.root/'runs').mkdir()
    def tearDown(self):self.temp.cleanup()
    def record(self,value):
        p=self.root/'runs'/'existing';p.mkdir();(p/'report.json').write_text(json.dumps(value))
    def test_duplicate_incomplete_stage_never_reserves(self):
        plan={'sha256':'protocol'}
        self.record({'stage':'mbpp-rescore-v2','arm':'parent','rescore_protocol_sha256':'protocol'})
        with patch.object(s,'ROOT',self.root),patch.object(s,'load_plan',return_value=(plan,{})),patch.object(s,'stage') as paid:
            with self.assertRaisesRegex(ValueError,'already exists'):s.run_arm('parent')
            paid.assert_not_called()
    def test_adapter_requires_completed_parent_reference_gate(self):
        plan={'sha256':'protocol'}
        self.record({'stage':'mbpp-rescore-v2','arm':'parent','rescore_protocol_sha256':'protocol','status':'completed','reference_audit_passed':False})
        with patch.object(s,'ROOT',self.root),patch.object(s,'load_plan',return_value=(plan,{})),patch.object(s,'stage') as paid:
            with self.assertRaisesRegex(ValueError,'Reference gate'):s.run_arm('seed-42')
            paid.assert_not_called()
    def test_concurrent_arm_lock_rejects_second_controller(self):
        with patch.object(s,'ROOT',self.root):
            with s.arm_lock('parent'):
                with self.assertRaisesRegex(ValueError,'active controller'):
                    with s.arm_lock('parent'):pass
    def test_source_drift_rejected_before_input_loading(self):
        value={'execution_source_hashes':{'x':'old'},'source_reports':{}}
        value['sha256']=s.digest(value)
        path=self.root/'protocol.json';path.write_text(json.dumps(value))
        with patch.object(s,'PLAN_PATH',path),patch.object(s,'source_hashes',return_value={'x':'new'}),patch.object(s,'original_reports') as read:
            with self.assertRaisesRegex(ValueError,'changed after freeze'):s.load_plan()
            read.assert_not_called()
    def test_original_report_tampering_rejected(self):
        value={'execution_source_hashes':{'x':'fixed'},'evaluator_source_hashes':{'e':'f'},'source_reports':{'parent':[{'run_id':'parent-run','sha256':'original'}]}}
        value['sha256']=s.digest(value)
        path=self.root/'protocol.json';path.write_text(json.dumps(value))
        with patch.object(s,'PLAN_PATH',path),patch.object(s,'source_hashes',return_value={'x':'fixed'}),patch('rsi.mbpp_verification_v2.evaluator_source_hashes',return_value={'e':'f'}),patch.object(s,'original_reports',return_value={'parent':[{'run_id':'parent-run','changed':True}]}):
            with self.assertRaisesRegex(ValueError,'evidence changed'):s.load_plan()

if __name__=='__main__':unittest.main()
