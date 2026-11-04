"""Controller boundary checks; all provider execution is excluded."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rsilab import digest
from rsi import successor_study as study


class ControllerTests(unittest.TestCase):
    def fixture(self):
        agent={'agent_id':'base','adapter_sha256':None}
        task={'id':'one','prompt':'public prompt'}
        output={'id':'one','text':'def answer(): return 1'}
        settings={'seed':42,'adapter_path':None,'adapter_sha256':None}
        generation={'outputs':[output],'adapter_sha256':None}
        request={**settings,'prompts':[{'id':'one','prompt':'public prompt'}]}
        batch={'settings':settings,'generation':generation,'request_sha256':digest(request)}
        report={'baseline':[{'task':task,'generation':output}],'baseline_batches':[batch],
                'remote_calls':[{'operation':'generate','request_sha256':digest(request),'status':'completed','result':deepcopy(generation)}]}
        controls={'effective_seeds':[42]}
        return report,agent,controls

    def envelope(self,report,agent,controls):
        with patch.object(study,'trusted_rows',side_effect=lambda rows:rows),patch.object(study,'infer_controls',return_value=controls):
            return study.collect_envelope(report,'baseline',agent)

    def test_saved_output_matches_worker_and_call(self):
        report,agent,controls=self.fixture()
        result=self.envelope(report,agent,controls)
        self.assertEqual(result['records'][0]['effective_seed'],42)

    def test_edited_raw_output_rejected(self):
        report,agent,controls=self.fixture();report['baseline'][0]['generation']=dict(report['baseline'][0]['generation'],text='changed')
        with self.assertRaisesRegex(ValueError,'Raw generation'):self.envelope(report,agent,controls)

    def test_missing_or_duplicate_provider_call_rejected(self):
        for change in ('missing','duplicate'):
            report,agent,controls=self.fixture()
            report['remote_calls']=[] if change=='missing' else report['remote_calls']*2
            with self.assertRaisesRegex(ValueError,'provider call'):self.envelope(report,agent,controls)

    def test_agent_substitution_rejected(self):
        report,agent,controls=self.fixture();agent['adapter_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'Agent adapter'):self.envelope(report,agent,controls)

    def test_changed_actual_generation_controls(self):
        settings={'model_id':'a/b','revision':'a'*40,'seed':42,'temperature':0.0,'max_new_tokens':512,'max_input_tokens':2048,'adapter_path':None,'adapter_sha256':None}
        actual={**settings,'seed':43,'enable_thinking':False}
        with self.assertRaisesRegex(ValueError,'seed'):study.infer_controls(actual,settings,1)

    def test_mutated_protocol_summary_rejected_before_providers(self):
        p={'sha256':'a'*64};compact={'full_protocol_sha256':'a'*64,'plan_sha256':'b'*64,'sha256':'c'*64}
        def read(path):return p if path.startswith('data/') else compact
        with patch.object(study,'read',side_effect=read):
            with self.assertRaisesRegex(ValueError,'summary identity'):study.protocol()

    def test_frozen_save_refuses_replacement(self):
        work=Path(__file__).resolve().parents[1]/'work';work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as directory,patch.object(study,'ROOT',Path(directory)):
            p=Path(directory)/'saved.json';p.write_text('{"value":1}')
            with self.assertRaisesRegex(ValueError,'overwrite'):study.save('saved.json',{'value':2})
            self.assertEqual(json.loads(p.read_text()),{'value':1})

if __name__=='__main__':unittest.main()
