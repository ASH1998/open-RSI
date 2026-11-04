import unittest
from copy import deepcopy
from unittest.mock import Mock
from rsilab.workflow import VerifiedCollector,verify_records
from rsilab.execution import ExecutionAborted
from rsilab.providers.modal import ModalBackend

class WorkflowTests(unittest.TestCase):
    def test_only_public_prompts_sent_and_truncation_never_executed(self):
        task={'id':'x','prompt':'public','cases':[{}],'reference_code':'secret'}
        output={'id':'x','text':'unfinished','hit_token_limit':True,'hit_time_limit':False}
        backend=Mock();backend.generate.return_value={'status':'completed','outputs':[output]}
        verifier=Mock();report={}
        rows=VerifiedCollector(backend=backend,verify=verifier,extract_code=lambda x:x,report=report,persist=lambda x:None).collect([task],settings={},key='a')
        verifier.assert_not_called();self.assertNotIn('secret',str(backend.generate.call_args))
        self.assertEqual(rows[0]['verification']['error_kind'],'generation_limit')
    def test_raw_generation_saved_before_order_error(self):
        backend=Mock();backend.generate.return_value={'status':'completed','outputs':[{'id':'wrong'}]}
        report={};saved=[]
        with self.assertRaisesRegex(ValueError,'identity'):
            VerifiedCollector(backend=backend,verify=Mock(),extract_code=lambda x:x,report=report,persist=lambda x:saved.append(deepcopy(x))).collect([{'id':'a','prompt':'p'}],settings={},key='a')
        self.assertEqual(saved[-1]['a_batches'][0]['generation']['outputs'][0]['id'],'wrong')
    def test_durable_verifier_infrastructure_failure(self):
        report={};saved=[]
        with self.assertRaises(ExecutionAborted):verify_records([{'id':'a'}],execute=lambda x:{'infrastructure_error':True},report=report,key='a',persist=lambda x:saved.append(deepcopy(x)))
        self.assertTrue(saved[0]['a'][0]['result']['infrastructure_error'])
        self.assertTrue(report['a_execution']['issues'])
    def test_provider_call_id_saved_before_get_and_result_before_return(self):
        report={};snap=[];fn=Mock();call=fn.spawn.return_value;call.object_id='fc-test';call.get.return_value={'ok':True}
        backend=ModalBackend(generate_function=fn,train_function=fn,report=report,persist=lambda x:snap.append(deepcopy(x)),max_calls=1)
        self.assertEqual(backend.generate({'x':1}),{'ok':True})
        self.assertEqual(snap[1]['remote_calls'][0]['call_id'],'fc-test')
        self.assertEqual(snap[-1]['remote_calls'][0]['result'],{'ok':True})
        with self.assertRaisesRegex(ValueError,'limit'):backend.generate({})
        self.assertEqual(fn.spawn.call_count,1)
    def test_failed_provider_call_preserves_id_and_cancels(self):
        report={};fn=Mock();call=fn.spawn.return_value;call.object_id='fc-failed';call.get.side_effect=TimeoutError('sensitive text')
        backend=ModalBackend(generate_function=fn,train_function=fn,report=report,persist=lambda x:None)
        with self.assertRaises(TimeoutError):backend.generate({})
        self.assertEqual(report['remote_calls'][0]['error_type'],'TimeoutError')
        self.assertNotIn('sensitive',str(report));call.cancel.assert_called_once_with(terminate_containers=True)

if __name__=='__main__':unittest.main()
