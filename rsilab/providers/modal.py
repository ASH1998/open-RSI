"""Durable bounded Modal calls using caller-owned functions and persistence."""
from __future__ import annotations
from rsilab.core import digest

class ModalBackend:
    """Run functions in a caller-owned app context; credentials stay with the caller.

    This adapter does not reserve money. The caller must acquire its stage budget
    before constructing it. Results and call IDs are persisted before returning.
    """
    def __init__(self, *, generate_function, train_function, report, persist,
                 max_calls=3, timeout_seconds=1850):
        if type(max_calls) is not int or not 1 <= max_calls <= 3:
            raise ValueError('max_calls must be between 1 and 3')
        self.functions={'generate':generate_function,'train':train_function}
        self.report=report;self.persist=persist;self.max_calls=max_calls;self.timeout=timeout_seconds
        report.setdefault('remote_calls',[])

    def call(self, kind, request):
        if kind not in self.functions:raise ValueError('Unknown remote operation')
        if len(self.report['remote_calls'])>=self.max_calls:
            raise ValueError('Stage remote call limit exhausted')
        entry={'index':len(self.report['remote_calls']),'operation':kind,
               'request_sha256':digest(request),'status':'submitting'}
        self.report['remote_calls'].append(entry);self.persist(self.report)
        call=None
        try:
            call=self.functions[kind].spawn(request)
            entry.update(call_id=call.object_id,status='running');self.persist(self.report)
            result=call.get(timeout=self.timeout)
            entry.update(status='completed',result=result);self.persist(self.report)
            return result
        except BaseException as error:
            entry.update(status='failed',error_type=type(error).__name__)
            if call is not None:
                try:call.cancel(terminate_containers=True)
                except Exception as cancel_error:entry['cancel_error_type']=type(cancel_error).__name__
            self.persist(self.report)
            raise

    def generate(self,request):return self.call('generate',request)
    def train(self,request):return self.call('train',request)
