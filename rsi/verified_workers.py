"""Fresh study app; reuses the pinned, tested quantized inference/training worker."""
import modal
from . import modal_workers as implementation
app=modal.App('open-rsi-verified-sft-v1',include_source=False)
resources={**implementation.RESOURCES,'gpu':'L40S'}
@app.function(**resources)
def generate(request):return implementation._generate(request)
@app.function(**resources)
def train(request):return implementation.train.local(request)
