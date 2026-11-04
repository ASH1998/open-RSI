# Portable optional Modal GPU workers

`rsilab.providers.portable_modal_v2` defines a separate worker factory that uses
packaged Python code and dependency resources. It does not import or mutate the
historical `rsi.modal_workers` module and does not look for a requirements file
beside a checkout. Importing it loads no Modal/ML SDK, credentials, or `.env` and
starts no job. The existing frozen workers and experiment results are unchanged.

Version 0.4.1 introduces this V2 factory after a remote startup failure in V1:
setting the runtime `PIP_CACHE_DIR` before image dependency installation created
`/artifacts/cache/pip` inside the image, and Modal rejected the nonempty volume
mount. V2 calls `pip_install` first, then sets runtime environment paths, then
attaches the explicit source bundle. No image build command follows that
environment assignment. The original `portable_modal.py` and resource kernel
remain unchanged; importing V1 does not silently switch to V2.

## API and lifecycle

```python
from rsilab.providers.portable_modal_v2 import PortableModalConfig, create_modal_workers
from rsilab.providers.modal import ModalBackend

config = PortableModalConfig(
    app_name="my-reviewed-experiment",
    volume_name="open-rsi-artifacts",
    model_id="openbmb/MiniCPM5-2B",
    model_revision="f97400052a43d642bbc6e9975e2397e3ae6a6b52",
    gpu="L40S",
)
workers = create_modal_workers(config)

# The controller first obtains its authorized stage reservation and report.
# This context and these method calls are explicit paid actions:
with workers.app.run():
    backend = ModalBackend(
        generate_function=workers.generate, train_function=workers.train,
        report=report, persist=persist, max_calls=3,
    )
    result = backend.generate({
        "prompts": [{"id": "task-1", "prompt": public_prompt}],
        "seed": 42, "temperature": 0.0, "max_new_tokens": 512,
        "max_input_tokens": 2048,
    })
```

The factory returns `PortableModalWorkers` with `app`, `generate`, `train`,
`config`, and a copy-returning `provenance` property. Both function adapters expose
`.spawn(request)` and return the underlying Modal call object; they plug into the
existing durable `ModalBackend`. They bind immutable configuration and expected
source inventory alongside the validated request. No serialized nested function
is used, so the local controller need not share the remote Python minor version.
The remote entrypoints are ordinary top-level module functions registered on the
explicit app. Modal's function registration supports explicit names and source
inclusion controls. [Modal App reference](https://modal.com/docs/sdk/py/latest/App)
V2 registers `generate_v2` and `train_v2`, backed by the V2 module's
`_generate_entry_v2` and `_train_entry_v2`. The caller-facing attributes remain
`workers.generate` and `workers.train`.

Construction imports the optional Modal SDK and defines lazy app/image/volume
objects, but calls no `app.run`, image build, deploy, `.spawn`, or credential
lookup. Volume creation defaults to disabled; `create_volume=True` only permits
creation when a later explicit app lifecycle resolves that resource. The caller
owns authorization, budget reservation, stage/job concurrency, durable call IDs,
failure handling, and remote resource cleanup. There is no automatic training,
retry, promotion, tracking, or budget allocation in this factory.

## Explicit configuration and boundaries

`PortableModalConfig` is a frozen dataclass. Required fields are `app_name`,
`volume_name`, `model_id`, and a 40-hex `model_revision`. Defaults are:

| Field | Default / accepted behavior |
| --- | --- |
| `gpu` | `L40S`; this version permits `L4`, `A10`, or `L40S`. |
| `volume_mount` | `/artifacts`; configurable non-system absolute POSIX path. |
| `python_version` | `3.12`, fixed for this dependency bundle. |
| `requirements_version` | `gpu-v1`, fixed for this worker version. |
| `create_volume` | `False`. |

The factory sets two CPU cores, 16 GiB host memory, zero warm/buffer containers,
one maximum container per function, a 1,800-second timeout, 600-second startup
timeout, and zero retries. Two functions can still run concurrently if the
controller submits both; its budget/concurrency policy remains authoritative.
Internal historical work limits remain 1,500 seconds for generation and 1,400
seconds for training, leaving time for persistence.

All runtime model, Torch, pip, XDG, and temporary caches live under the configured
volume mount. Adapters/checkpoints live under `<mount>/adapters`. The worker
image installs dependencies before these runtime paths exist in its environment;
build-time pip uses the image's normal paths outside the future volume mount.
The worker
commits newly created cache/temp directories before the preserved kernels reload
the volume, so a first-run reload cannot discard those directories. The worker
requests public pinned model bytes with `trust_remote_code=False` and
`token=False`; it receives no user control/tracking secrets. Image environment
values come only from the explicit path configuration, not a controller
environment dump. W&B is disabled in the GPU worker. The controller records
tracking and independently verifies generated programs elsewhere.

Other explicitly pinned public model IDs can be configured, but this copied
algorithm retains Llama-style LoRA target modules, NF4 double quantization,
bfloat16 compute, and SDPA. Historical real GPU evidence applies to the pinned
MiniCPM5 checkpoint, not arbitrary models. A different model requires separate
tokenizer/architecture/trainability validation before a paid experiment.

## Existing teachers, fresh children, and resume

Generation accepts `adapter_path` beneath the configured adapter root and requires
`adapter_sha256`, the lowercase 64-hex SHA-256 of `adapter_model.safetensors`, whenever
that path is non-null. Base generation accepts an omitted or null digest. Thus an
existing teacher such as `/artifacts/adapters/<historical-run>/<adapter-dir>` can
load from the shared `open-rsi-artifacts` volume. Both lexical prefix checks and
canonical containment are enforced, including symlinked mounts; links escaping
the adapter root are rejected. No local model weights are uploaded by the factory.
After the kernel reloads the volume and before model loading, the wrapper hashes
the remote weights and rejects a mismatch. Weight-file symlinks are rejected.
Generation returns the verified `adapter_sha256`, or `None` for the base model.
Training returns the actual digest of its final saved weights; controllers can
pass that digest into child evaluation and independently compare an SSD export.
This added training digest is in the returned response and controller report;
the preserved kernel's volume `result.json` predates that return-field addition.

Training accepts only `prompt`, `completion`, and `verified: True` per example.
The flag is a controller assertion: independent verification and train/dev/final
separation must happen before submission. Extra provider credentials, reference
answers, or unrelated metadata are not accepted as request fields. Training
creates a fresh LoRA adapter on the configured base and rejects `adapter_path`.
It can resume only through an explicit completed `resume_checkpoint` belonging
to the same run ID. Inference may use an old teacher while child training starts
from the original base; the factory does not conflate those operations.

The historical full-state checkpoint algorithm is retained: adapter weights,
optimizer state, step/loss history, Torch CPU and CUDA RNG state, source/data/
settings fingerprint, checksummed completion manifest, immutable snapshot
directories, and a latest-checkpoint pointer. Data is committed before publishing
the pointer. Learning rate is constant; there is no scheduler state to omit.
Partial gradient accumulation is discarded with RNG restored before checkpointing.
The tokenizer template and prompt-only loss masking remain unchanged.

Portable checkpoints bind the new source/config/requirements inventory in their
training fingerprint. They are deliberately not presented as resumable from
historical training-state checkpoints. Historical adapters remain supported for
inference. Resume must retain the exact portable configuration, source inventory,
training examples/settings and installed packages; only the total target step
count can increase as allowed by the original worker.

The request bounds remain at most 64 prompts, 768 new tokens, 4,096 input tokens,
256 verified training examples, 200 optimizer steps, accumulation up to eight,
and training length up to 2,048. Training run IDs are limited to 80 safe characters.
Tokenized prompts and verified completions are rejected when oversized rather
than silently truncated. Host preflight adds strict field/ID checks and validates
static bounds before `.spawn`; remote checks still enforce model/path identities.

## Package and image resource contract

The release build must include these new files:

```text
rsilab/providers/portable_modal_v2.py
rsilab/resources/__init__.py
rsilab/resources/gpu_worker_v1.py
rsilab/resources/gpu_requirements_v1.txt
rsilab/resources/gpu_worker_v1.provenance.json
```

Main owns adding `resources/*.txt` and `resources/*.json` to package-data and the
release allowlist. Python modules alone are insufficient. The factory reads
resources through `importlib.resources`, validates resource checksums, and passes
the six exact direct dependency pins to `Image.pip_install`. It does not pass a
checkout-relative requirements path. Transitive dependencies are not fully
locked; each result records the actual installed package inventory.

The image uses `add_local_python_source("rsilab", ignore=...)` with an explicit
ten-file allowlist: `__init__.py`, `core.py`, `comparison.py`, `artifacts.py`, the
provider package initializer/factory, and the four resource files above. The
filter includes the required non-Python resources and excludes every other file,
including symlinks, credentials, tests, runs, and unrelated modules. Automatic
source inclusion is disabled on both app and functions. Modal supports this
explicit source filter, including non-Python resources when the default filter
is overridden. [Modal Image reference](https://modal.com/docs/sdk/py/latest/Image)

Resource reading works from both extracted packages and zipimport. Constructing
the actual Modal source mount requires a normal filesystem-installed package,
as produced by wheel installation; zipimport factory construction is rejected.
No `rsi` module, project configuration, or root requirements file is part of the
remote bundle.

The factory inventory reports `worker_version: portable-qlora-v2` and
`kernel_version: portable-qlora-v1`. Its ten-file source allowlist contains only
the V2 factory, not V1. Its unchanged kernel provenance resource
records the historical `rsi/modal_workers.py` SHA-256
`d289e78ae99a40831810285d42c0b4ee73cd4bd3446bda0505e4905a70a45d95`,
the original requirement-file digest, copied function names, and exact portability
edits. Those edits remove SDK/decorator globals, inject per-call model/storage
bindings, use the portable fingerprint instead of historical `__file__`, and
generalize error wording. The full eleven-function kernel otherwise matches
the frozen source AST. Generated code is never executed in this module.

Each response and persisted training result includes `portable_worker` with
source inventory, direct requirements, historical lineage, configuration, and
configuration digest. Remote execution rejects an inventory different from the
one bound by the factory. These are integrity checks, not signatures; controllers
still freeze and audit the package/source versions used for an experiment.

## Verified status and next milestone

Nineteen V2 offline tests cover image build order, absence of volume-backed
cache paths during pip installation, V2 inventory/entrypoint identities,
resource pinning/tampering, all eleven function ASTs,
tokenizer masking/bounds, separate runtime bindings, existing adapter paths and
symlink containment, lazy resource definitions, explicit source filtering,
preflight rejection, `ModalBackend` compatibility, metadata binding, required
adapter identities, mismatch rejection before model loading, and final saved
weight hashing. Minimal
package copies load from a directory and ZIP with checkout/provider/ML imports
blocked. An additional check successfully constructed real installed Modal SDK
`App`/`Function` objects with networking blocked and a nonexistent project-local
credential-config path. It did not enter an app context, build an image, or
submit work.

```sh
env -i PATH=/usr/bin:/bin .venv/bin/python -B -m unittest discover -s tests -p test_portable_modal_v2.py -v
```

The V1 remote call failed before outputs at volume attachment. V2 has not yet
completed a remote GPU job or resumed training remotely.
Offline parity and historical-worker GPU evidence do not substitute for that
test. Main's next milestones are packaging the resources in the new wheel,
isolated installed-factory validation, and an explicitly budgeted remote smoke
and checkpoint/resume check before relying on portable training results. No paid
job, publication, dependency installation, or frozen-source edit was performed
for this implementation.
