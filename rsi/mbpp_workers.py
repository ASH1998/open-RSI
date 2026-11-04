"""Study-specific hardware with the same reviewed model/QLoRA implementation."""
import modal
from . import modal_workers as implementation

app = modal.App('open-rsi-mbpp-v1', include_source=False)
resources = {**implementation.RESOURCES, 'gpu': 'L40S'}


@app.function(**resources)
def generate(request):
    return implementation._generate(request)


@app.function(**resources)
def train(request):
    return implementation.train.local(request)
