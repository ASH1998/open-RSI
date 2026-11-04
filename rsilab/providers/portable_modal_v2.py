"""Version 2 Modal factory: install dependencies before runtime cache paths.

No credentials, SDK, image build, or provider call is loaded at import. The
controller owns reservations and app.run(); factory construction only defines
resources. Returned function adapters support ModalBackend's spawn(request).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from importlib import resources
import json
from pathlib import Path, PurePosixPath
import re
import types

WORKER_VERSION = "portable-qlora-v2"
KERNEL_VERSION = "portable-qlora-v1"
REQUIREMENTS_RESOURCE = "gpu_requirements_v1.txt"
PROVENANCE_RESOURCE = "gpu_worker_v1.provenance.json"
SOURCE_ALLOWLIST = (
    "__init__.py", "core.py", "comparison.py", "artifacts.py",
    "providers/__init__.py", "providers/portable_modal_v2.py", "resources/__init__.py",
    "resources/gpu_worker_v1.py", "resources/gpu_requirements_v1.txt",
    "resources/gpu_worker_v1.provenance.json",
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class PortableModalConfig:
    app_name: str
    volume_name: str
    model_id: str
    model_revision: str
    gpu: str = "L40S"
    volume_mount: str = "/artifacts"
    python_version: str = "3.12"
    requirements_version: str = "gpu-v1"
    create_volume: bool = False

    def __post_init__(self):
        for field in ("app_name", "volume_name"):
            if not isinstance(getattr(self, field), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", getattr(self, field)):
                raise ValueError(f"Invalid explicit {field}")
        if not isinstance(self.model_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.model_id):
            raise ValueError("model_id must name an explicit public Hub repository")
        if not isinstance(self.model_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", self.model_revision):
            raise ValueError("Model revision must be an immutable 40-character commit")
        if self.gpu not in {"L4", "A10", "L40S"}:
            raise ValueError("Unsupported GPU configuration")
        if self.python_version != "3.12" or self.requirements_version != "gpu-v1":
            raise ValueError("This worker version requires Python 3.12 and the gpu-v1 pins")
        if (not isinstance(self.volume_mount, str) or not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", self.volume_mount)
                or PurePosixPath(self.volume_mount).parts[1] in {"root", "home", "etc", "usr", "dev", "proc", "sys", "tmp"}):
            raise ValueError("Volume mount must be an explicit non-system absolute POSIX path")
        if type(self.create_volume) is not bool:
            raise ValueError("create_volume must be boolean")

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return _digest(self.to_dict())


def resource_inventory() -> dict:
    """Read/check packaged resources with no checkout, SDK, or filesystem writes."""
    package = resources.files("rsilab")
    manifest = json.loads(package.joinpath("resources", PROVENANCE_RESOURCE).read_text(encoding="utf-8"))
    if manifest["worker_version"] != KERNEL_VERSION:
        raise ValueError("Portable resource version mismatch")
    sources = {name: hashlib.sha256(package.joinpath(*name.split("/")).read_bytes()).hexdigest()
               for name in SOURCE_ALLOWLIST}
    for name, expected in manifest["resource_sha256"].items():
        if sources.get("resources/" + name) != expected:
            raise ValueError("Portable worker resource checksum mismatch")
    text = package.joinpath("resources", REQUIREMENTS_RESOURCE).read_text(encoding="utf-8")
    pins = tuple(line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))
    if (not pins or len(set(pin.split("==")[0] for pin in pins)) != len(pins)
            or any(not re.fullmatch(r"[A-Za-z0-9_-]+==[0-9]+(?:\.[0-9]+)+", pin) for pin in pins)):
        raise ValueError("Packaged GPU dependencies must use exact ordinary version pins")
    result = {"worker_version": WORKER_VERSION, "kernel_version": KERNEL_VERSION, "source_hashes": sources,
              "requirements": list(pins), "historical_source": manifest["historical_source"],
              "historical_requirements": manifest["historical_requirements"]}
    result["sha256"] = _digest(result)
    return result


def _bound_runtime(config, volume, worker_sha256):
    from rsilab.resources import gpu_worker_v1 as worker
    # Each call receives its own globals. Training's nested checkpoint function
    # inherits this namespace; separate configurations never mutate the module.
    namespace = dict(vars(worker))
    namespace.update(MODEL_ID=config.model_id, MODEL_REVISION=config.model_revision,
                     ADAPTER_ROOT=Path(config.volume_mount) / "adapters", volume=volume,
                     WORKER_SOURCE_SHA256=worker_sha256)
    for name, function in tuple(namespace.items()):
        if isinstance(function, types.FunctionType) and function.__module__ == worker.__name__:
            bound = types.FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            bound.__kwdefaults__ = function.__kwdefaults__
            bound.__annotations__ = function.__annotations__
            namespace[name] = bound
    return namespace


def validate_request(operation: str, request: dict, config: PortableModalConfig) -> dict:
    """Fail before spawn on bad identities/bounds; accept no provider secrets."""
    if operation not in {"generate", "train"} or not isinstance(request, dict):
        raise ValueError("Expected a generation or training request dictionary")
    allowed = {"model_id", "revision", "seed"}
    allowed |= ({"prompts", "max_new_tokens", "max_input_tokens", "temperature", "adapter_path", "adapter_sha256"}
                if operation == "generate" else
                {"examples", "run_id", "max_steps", "gradient_accumulation", "max_length", "checkpoint_every",
                 "learning_rate", "resume_checkpoint"})
    if set(request) - allowed:
        raise ValueError("Request contains fields outside the explicit worker allowlist")
    value = json.loads(json.dumps(request, allow_nan=False))
    value.setdefault("model_id", config.model_id)
    value.setdefault("revision", config.model_revision)
    runtime = _bound_runtime(config, None, "preflight")
    runtime["_identity"](value)
    integer, number, text = runtime["_bounded_int"], runtime["_bounded_float"], runtime["_text"]
    integer(value, "seed", 42, 0, 2**31 - 1)
    path_key = "adapter_path" if operation == "generate" else "resume_checkpoint"
    if value.get(path_key) is not None:
        candidate = value[path_key]
        root = PurePosixPath(config.volume_mount) / "adapters"
        if (not isinstance(candidate, str) or ".." in PurePosixPath(candidate).parts
                or not PurePosixPath(candidate).is_relative_to(root) or PurePosixPath(candidate) == root):
            raise ValueError("Adapter/checkpoint path is outside the configured volume")
    if operation == "generate":
        checksum = value.get("adapter_sha256")
        if value.get("adapter_path") is not None:
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError("Adapter generation requires an immutable adapter_sha256")
        elif checksum is not None:
            raise ValueError("Base generation cannot declare an adapter_sha256")
        prompts = value.get("prompts")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 64:
            raise ValueError("Supply between 1 and 64 prompts")
        ids = []
        for index, item in enumerate(prompts):
            if not isinstance(item, dict) or set(item) - {"id", "prompt"}:
                raise ValueError("Prompts may contain only public id and prompt fields")
            text(item.get("prompt"), "prompt")
            item.setdefault("id", str(index))
            if not isinstance(item["id"], str) or not item["id"] or len(item["id"]) > 200 or item["id"] in ids:
                raise ValueError("Prompt IDs must be unique nonempty strings of at most 200 characters")
            ids.append(item["id"])
        integer(value, "max_new_tokens", 512, 1, 768)
        integer(value, "max_input_tokens", 2048, 32, 4096)
        number(value, "temperature", 0.0, 0.0, 1.5)
    else:
        examples = value.get("examples")
        if not isinstance(examples, list) or not 1 <= len(examples) <= 256:
            raise ValueError("Supply between 1 and 256 verified examples")
        for item in examples:
            if (not isinstance(item, dict) or set(item) != {"prompt", "completion", "verified"}
                    or item["verified"] is not True):
                raise ValueError("Training requires only prompt/completion/verified=true fields")
            text(item["prompt"], "prompt"); text(item["completion"], "completion")
        if sum(len(item["prompt"]) + len(item["completion"]) for item in examples) > 2_000_000:
            raise ValueError("Training text exceeds the bounded request size")
        if not isinstance(value.get("run_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value["run_id"]):
            raise ValueError("Training run ID must contain 1-80 safe characters")
        for key, default, low, high in (("max_steps", 40, 1, 200), ("gradient_accumulation", 4, 1, 8),
                                        ("max_length", 1536, 64, 2048), ("checkpoint_every", 10, 1, 50)):
            integer(value, key, default, low, high)
        number(value, "learning_rate", 1e-4, 1e-8, 5e-4)
    return value


def _remote_environment(config):
    mount = config.volume_mount
    return {"HF_HOME": mount + "/hf-cache", "HF_HUB_CACHE": mount + "/hf-cache/hub",
            "XDG_CACHE_HOME": mount + "/cache", "TORCH_HOME": mount + "/torch-cache",
            "PIP_CACHE_DIR": mount + "/cache/pip", "TMPDIR": mount + "/tmp",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "TOKENIZERS_PARALLELISM": "false",
            "WANDB_MODE": "disabled"}


def _adapter_digest(runtime, adapter_path):
    weights = runtime["_adapter_path"](adapter_path) / "adapter_model.safetensors"
    if weights.is_symlink() or not weights.is_file():
        raise ValueError("Adapter weights must be a regular non-symlink safetensors file")
    checksum = hashlib.sha256()
    with weights.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _execute(operation, request, config_payload, expected_inventory):
    """Remote entry only. Model code executes here; generated candidate code never does."""
    import os
    import tempfile
    import modal
    config = PortableModalConfig(**config_payload)
    inventory = resource_inventory()
    if inventory != expected_inventory:
        raise ValueError("Remote portable worker/source inventory changed")
    request = validate_request(operation, request, config)
    volume = modal.Volume.from_name(config.volume_name, create_if_missing=False)
    volume.reload()
    environment = _remote_environment(config)
    for key in ("HF_HOME", "HF_HUB_CACHE", "XDG_CACHE_HOME", "TORCH_HOME", "PIP_CACHE_DIR", "TMPDIR"):
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    (Path(config.volume_mount) / "adapters").mkdir(parents=True, exist_ok=True)
    # The preserved kernels reload their Volume before model/adapter access.
    # Commit new cache/temp directories so that reload cannot discard them.
    volume.commit()
    os.environ.update(environment)
    tempfile.tempdir = environment["TMPDIR"]
    provenance = {"worker": inventory, "config": config.to_dict(), "config_sha256": config.sha256}
    fingerprint = _digest(provenance)
    runtime = _bound_runtime(config, volume, fingerprint)
    metadata = runtime["_metadata"]
    verified = {"adapter_sha256": None}
    if operation == "generate" and request.get("adapter_path") is not None:
        load = runtime["_load"]
        def checked_load(value, *, training=False):
            # _generate reloads the volume immediately before calling _load.
            actual = _adapter_digest(runtime, value["adapter_path"])
            if actual != value["adapter_sha256"]:
                raise ValueError("Remote adapter_sha256 mismatch before model loading")
            verified["adapter_sha256"] = actual
            return load(value, training=training)
        runtime["_load"] = checked_load
    runtime["_metadata"] = lambda started: {**metadata(started), "portable_worker": provenance,
                                           **(verified if operation == "generate" else {})}
    result = runtime["_generate" if operation == "generate" else "train"](request)
    if operation == "train":
        result["adapter_sha256"] = _adapter_digest(runtime, result["adapter_path"])
    return result


def _generate_entry_v2(request, config_payload, expected_inventory):
    return _execute("generate", request, config_payload, expected_inventory)


def _train_entry_v2(request, config_payload, expected_inventory):
    return _execute("train", request, config_payload, expected_inventory)


@dataclass(frozen=True)
class _BoundFunction:
    function: object
    operation: str
    config: PortableModalConfig
    inventory_json: str

    def spawn(self, request):
        validated = validate_request(self.operation, request, self.config)
        return self.function.spawn(validated, self.config.to_dict(), json.loads(self.inventory_json))


@dataclass(frozen=True)
class PortableModalWorkers:
    app: object
    generate: _BoundFunction
    train: _BoundFunction
    config: PortableModalConfig
    inventory_json: str

    @property
    def provenance(self):
        return {"worker": json.loads(self.inventory_json), "config": self.config.to_dict(), "config_sha256": self.config.sha256}


def create_modal_workers(config: PortableModalConfig, *, sdk=None) -> PortableModalWorkers:
    """Define lazy resources only. Caller must reserve budget before app.run/spawn.

    sdk injection supports offline tests. No image build, deployment, secrets,
    local .env loading, run(), spawn(), or credential lookup is requested here.
    """
    if not isinstance(config, PortableModalConfig):
        raise TypeError("Supply an immutable PortableModalConfig")
    inventory = resource_inventory()
    if sdk is None:
        import modal as sdk
    package = resources.files("rsilab")
    if not isinstance(package, Path):
        raise ValueError("Modal source mounting requires a filesystem-installed package, not zipimport")
    package_root = package.resolve()
    allowed = frozenset(SOURCE_ALLOWLIST)

    def exclude(path):
        path = Path(path)
        if not path.is_absolute():
            path = package_root / path
        if path.is_symlink():
            return True
        try:
            relative = str(path.resolve().relative_to(package_root))
        except ValueError:
            return True
        return not path.is_dir() and relative not in allowed

    # Image build steps must not inherit Volume-backed cache/TMPDIR paths.
    # Pip would populate the future mount and Modal rejects nonempty mounts.
    # Set runtime environment only after the final package-install layer.
    image = (sdk.Image.debian_slim(python_version=config.python_version)
             .pip_install(*inventory["requirements"]).env(_remote_environment(config))
             .add_local_python_source("rsilab", ignore=exclude))
    volume = sdk.Volume.from_name(config.volume_name, create_if_missing=config.create_volume)
    app = sdk.App(config.app_name, include_source=False)
    options = dict(image=image, gpu=config.gpu, cpu=(2, 2), memory=(16384, 16384),
                   volumes={config.volume_mount: volume}, secrets=[], min_containers=0, max_containers=1,
                   buffer_containers=0, scaledown_window=15, timeout=1800, startup_timeout=600,
                   retries=0, include_source=False)
    generate = app.function(name="generate_v2", **options)(_generate_entry_v2)
    train = app.function(name="train_v2", **options)(_train_entry_v2)
    payload = json.dumps(inventory, sort_keys=True)
    return PortableModalWorkers(app, _BoundFunction(generate, "generate", config, payload),
                                _BoundFunction(train, "train", config, payload), config, payload)
