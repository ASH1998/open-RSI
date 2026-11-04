"""Bounded Modal workers; launch through the budget-aware controller only.

Importing this module defines resources but does not start compute. No local
environment file, credentials, generated code, or external judge is used here.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import time
import uuid

import modal

MODEL_ID = "openbmb/MiniCPM5-2B"
MODEL_REVISION = "f97400052a43d642bbc6e9975e2397e3ae6a6b52"
GPU_PACKAGES = (
    "torch==2.8.0", "transformers==5.22.1", "peft==0.21.2",
    "accelerate==1.15.0", "bitsandbytes==0.50.2", "safetensors==0.8.0",
)
REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / "requirements-gpu.txt"
app = modal.App("open-rsi", include_source=False)
volume = modal.Volume.from_name("open-rsi-artifacts", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(REQUIREMENTS_PATH))
    .env({"HF_HOME": "/artifacts/hf-cache", "TORCH_HOME": "/artifacts/torch-cache",
          "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_python_source("rsi")
    .add_local_file(str(REQUIREMENTS_PATH), "/root/requirements-gpu.txt")
)
RESOURCES = dict(
    image=image, gpu="A10", cpu=(2, 2), memory=(16384, 16384),
    volumes={"/artifacts": volume}, min_containers=0, max_containers=1,
    buffer_containers=0, scaledown_window=15, timeout=1800,
    startup_timeout=600, retries=0, include_source=False,
)


def _identity(request: dict) -> tuple[str, str]:
    if not isinstance(request, dict):
        raise ValueError("request must be a dictionary")
    model = request.get("model_id", MODEL_ID)
    revision = request.get("revision", MODEL_REVISION)
    if model != MODEL_ID or revision != MODEL_REVISION:
        raise ValueError("This pilot only supports the reviewed, pinned MiniCPM5 checkpoint")
    return model, revision


def _bounded_int(request: dict, key: str, default: int, low: int, high: int) -> int:
    value = request.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key} must be an integer between {low} and {high}")
    return value


def _adapter_path(value: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/artifacts/adapters/"):
        raise ValueError("Adapter must be an absolute path under /artifacts/adapters")
    path = Path(value).resolve()
    if not path.is_relative_to(Path("/artifacts/adapters")) or not path.is_dir():
        raise ValueError("Adapter must be an existing directory under /artifacts/adapters")
    return path


def _bounded_float(request: dict, key: str, default: float, low: float, high: float) -> float:
    value = request.get(key, default)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{key} must be a finite number between {low} and {high}")
    return float(value)


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 30000:
        raise ValueError(f"{field} must be a nonempty string of at most 30000 characters")
    return value


def _metadata(started: float) -> dict:
    import torch

    torch.cuda.synchronize()
    return {
        "elapsed_seconds": time.monotonic() - started,
        "gpu_name": torch.cuda.get_device_name(0),
        "peak_gpu_memory_bytes": torch.cuda.max_memory_allocated(),
        "packages": {dist.metadata["Name"]: dist.version
                     for dist in importlib.metadata.distributions() if dist.metadata["Name"]},
        "cuda_version": torch.version.cuda,
        "model_id": MODEL_ID, "revision": MODEL_REVISION,
    }


def _load(request: dict, *, training: bool = False):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed

    model_id, revision = _identity(request)
    set_seed(_bounded_int(request, "seed", 42, 0, 2**31 - 1))
    torch.cuda.reset_peak_memory_stats()
    common = dict(revision=revision, trust_remote_code=False, token=False)
    tokenizer = AutoTokenizer.from_pretrained(model_id, **common)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    # Keep inference and training bases in the same quantization regime.
    quantization = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id, **common, dtype=torch.bfloat16, device_map={"": 0},
        quantization_config=quantization, attn_implementation="sdpa",
    )
    if request.get("adapter_path"):
        if training:
            raise ValueError("Continued-adapter training is not implemented; use resume_checkpoint")
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(_adapter_path(request["adapter_path"])))
    return model, tokenizer


def _prompt_ids(tokenizer, prompt: str) -> list[int]:
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=True,
        add_generation_prompt=True, enable_thinking=False,
    )


def _encode_example(tokenizer, example: dict, max_length: int) -> dict:
    prompt = _text(example.get("prompt"), "prompt")
    completion = _text(example.get("completion"), "completion")
    prefix = _prompt_ids(tokenizer, prompt)
    tokens = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt},
         {"role": "assistant", "content": completion}],
        tokenize=True, add_generation_prompt=False, enable_thinking=False,
    )
    if tokens[:len(prefix)] != prefix:
        raise ValueError("Training template does not preserve the inference token prefix")
    if len(tokens) > max_length:
        raise ValueError("Training example exceeds max_length; do not truncate verified targets")
    if len(tokens) <= len(prefix):
        raise ValueError("Training example has no supervised tokens")
    return {"input_ids": tokens, "labels": [-100] * len(prefix) + tokens[len(prefix):]}


def _generate(request: dict) -> dict:
    import torch

    started = time.monotonic()
    _identity(request)
    prompts = request.get("prompts", [])
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 64:
        raise ValueError("Supply between 1 and 64 prompts")
    max_new_tokens = _bounded_int(request, "max_new_tokens", 512, 1, 768)
    max_input_tokens = _bounded_int(request, "max_input_tokens", 2048, 32, 4096)
    seed = _bounded_int(request, "seed", 42, 0, 2**31 - 1)
    temperature = _bounded_float(request, "temperature", 0.0, 0.0, 1.5)
    for item in prompts:
        if not isinstance(item, dict):
            raise ValueError("Each prompt must be a dictionary")
        _text(item.get("prompt"), "prompt")
        if "id" in item and (not isinstance(item["id"], str) or len(item["id"]) > 200):
            raise ValueError("Prompt id must be a string of at most 200 characters")
    volume.reload()
    if request.get("adapter_path") is not None:
        _adapter_path(request["adapter_path"])
    model, tokenizer = _load(request)
    model.eval()
    outputs = []
    status = "completed"
    generation_started = time.monotonic()
    for index, item in enumerate(prompts):
        remaining = 1500 - (time.monotonic() - started)
        if remaining <= 0:
            status = "generation_time_limit"
            break
        tokens = _prompt_ids(tokenizer, item["prompt"])
        if len(tokens) > max_input_tokens:
            raise ValueError("Prompt exceeds max_input_tokens; truncation is disabled")
        torch.manual_seed(seed + index)
        torch.cuda.manual_seed_all(seed + index)
        ids = torch.tensor([tokens], device="cuda")
        kwargs = dict(max_new_tokens=max_new_tokens, max_time=remaining, do_sample=temperature > 0,
                      pad_token_id=tokenizer.pad_token_id)
        if temperature > 0:
            kwargs.update(temperature=float(temperature), top_p=0.95)
        item_started = time.monotonic()
        with torch.inference_mode():
            result = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), **kwargs)
        new_tokens = result[0, len(tokens):].tolist()
        hit_time_limit = time.monotonic() - started >= 1500
        outputs.append({
            "id": item.get("id", str(index)),
            "text": tokenizer.decode(new_tokens, skip_special_tokens=True),
            "input_tokens": len(tokens), "output_tokens": len(new_tokens),
            "hit_token_limit": len(new_tokens) == max_new_tokens,
            "hit_time_limit": hit_time_limit,
            "elapsed_seconds": time.monotonic() - item_started,
        })
        if hit_time_limit:
            status = "generation_time_limit"
            break
    response = {"status": status, "outputs": outputs,
                "generation_seconds": time.monotonic() - generation_started,
                "total_output_tokens": sum(x["output_tokens"] for x in outputs),
                "adapter_path": request.get("adapter_path"),
                "enable_thinking": False, "temperature": temperature,
                "max_new_tokens": max_new_tokens, "seed": seed, **_metadata(started)}
    volume.commit()
    return response


@app.function(**RESOURCES)
def generate(request: dict) -> dict:
    """Generate bounded text only; controller verifies outputs elsewhere."""
    return _generate(request)


@app.function(**RESOURCES)
def smoke(request: dict | None = None) -> dict:
    """Load the pinned quantized model and generate one short response."""
    request = dict(request or {})
    request["prompts"] = [{"id": "smoke", "prompt": "Write a Python function add(a, b) returning their sum. Return only Python code."}]
    request["max_new_tokens"] = 96
    return _generate(request)


@app.function(**RESOURCES)
def train(request: dict) -> dict:
    """Fit one fresh QLoRA adapter to externally verified completions."""
    import random
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training

    started = time.monotonic()
    _identity(request)
    examples = request.get("examples", [])
    if not isinstance(examples, list) or not 1 <= len(examples) <= 256:
        raise ValueError("Training accepts between 1 and 256 verified examples")
    if any(not isinstance(x, dict) or x.get("verified") is not True for x in examples):
        raise ValueError("Every example must explicitly carry verified=true")
    for item in examples:
        _text(item.get("prompt"), "prompt")
        _text(item.get("completion"), "completion")
    # Exclude unrelated caller metadata from persistence and reproducibility hashes.
    examples = [{key: item[key] for key in ("prompt", "completion", "verified")} for item in examples]
    if sum(len(x["prompt"]) + len(x["completion"]) for x in examples) > 2_000_000:
        raise ValueError("Training text exceeds the 2000000-character request limit")
    run_id = request.get("run_id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("run_id must contain 1–80 alphanumeric, hyphen, or underscore characters")
    max_steps = _bounded_int(request, "max_steps", 40, 1, 200)
    accumulation = _bounded_int(request, "gradient_accumulation", 4, 1, 8)
    max_length = _bounded_int(request, "max_length", 1536, 64, 2048)
    checkpoint_every = _bounded_int(request, "checkpoint_every", 10, 1, 50)
    seed = _bounded_int(request, "seed", 42, 0, 2**31 - 1)
    learning_rate = _bounded_float(request, "learning_rate", 1e-4, 1e-8, 5e-4)
    if request.get("adapter_path") is not None:
        raise ValueError("Continued-adapter training is not implemented; use resume_checkpoint")
    fingerprint_data = {"examples": examples, "max_length": max_length,
                        "gradient_accumulation": accumulation, "learning_rate": learning_rate,
                        "seed": seed, "model_id": MODEL_ID, "revision": MODEL_REVISION,
                        "worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "packages": {name: importlib.metadata.version(name) for name in
                                     ("torch", "transformers", "peft", "accelerate", "bitsandbytes", "safetensors")}}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
    directory = Path("/artifacts/adapters") / run_id
    checkpoint = None
    resume = request.get("resume_checkpoint")
    state = None
    volume.reload()
    if resume is not None:
        checkpoint = _adapter_path(resume)
        if checkpoint.parent != directory / "checkpoints" or not (checkpoint / "complete.json").is_file():
            raise ValueError("Resume requires a completed checkpoint belonging to this run_id")
        manifest = json.loads((checkpoint / "complete.json").read_text())
        files = {p.name for p in checkpoint.iterdir() if p.is_file() and p.name != "complete.json"}
        if files != set(manifest["sha256"]):
            raise ValueError("Checkpoint file inventory changed")
        for name, digest in manifest["sha256"].items():
            if Path(name).name != name or hashlib.sha256((checkpoint / name).read_bytes()).hexdigest() != digest:
                raise ValueError("Checkpoint checksum mismatch")
        state = torch.load(checkpoint / "training_state.pt", map_location="cpu", weights_only=True)
        if state["fingerprint"] != fingerprint:
            raise ValueError("Resume data, worker, packages, or training settings changed")
        if not 0 <= state["step"] <= max_steps:
            raise ValueError("max_steps is a total target and must be at least the saved step")
    if directory.exists() and not resume:
        raise ValueError("run_id already exists; choose a fresh ID or explicitly resume")
    model, tokenizer = _load(request, training=True)
    rows = [_encode_example(tokenizer, item, max_length) for item in examples]
    random.Random(seed).shuffle(rows)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model.config.use_cache = False
    if resume:
        model = PeftModel.from_pretrained(model, str(checkpoint), is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(
            r=8, lora_alpha=16, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        ))
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=learning_rate)
    step = 0
    losses = []
    if resume:
        optimizer.load_state_dict(state["optimizer"])
        # AdamW's scalar step stays on CPU (non-capturable/non-fused); moments
        # follow each parameter. Do not blindly move every state tensor to CUDA.
        for parameter, parameter_state in optimizer.state.items():
            for key in ("exp_avg", "exp_avg_sq", "max_exp_avg_sq"):
                if key in parameter_state:
                    parameter_state[key] = parameter_state[key].to(parameter.device)
        step, losses = state["step"], state["losses"]
        torch.set_rng_state(state["torch_rng"])
        torch.cuda.set_rng_state_all(state["cuda_rng"])
    directory.mkdir(parents=True, exist_ok=bool(resume))
    (directory / "checkpoints").mkdir(exist_ok=True)

    def save_checkpoint():
        nonlocal checkpoint
        # Each snapshot is immutable. An interrupted upload cannot overwrite
        # the adapter/state pair in a previously committed snapshot.
        snapshot_id = f"step-{step:06d}-{uuid.uuid4().hex}"
        temporary = directory / "checkpoints" / (".pending-" + snapshot_id)
        temporary.mkdir()
        model.save_pretrained(temporary)
        torch.save({"optimizer": optimizer.state_dict(), "step": step, "losses": losses,
                    "fingerprint": fingerprint, "torch_rng": torch.get_rng_state(),
                    "cuda_rng": torch.cuda.get_rng_state_all()}, temporary / "training_state.pt")
        (temporary / "metadata.json").write_text(json.dumps(fingerprint_data | {"fingerprint": fingerprint}, indent=2))
        checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in temporary.iterdir() if p.is_file()}
        (temporary / "complete.json").write_text(json.dumps({"step": step, "sha256": checksums}))
        checkpoint = directory / "checkpoints" / snapshot_id
        temporary.rename(checkpoint)
        # Commit data before publishing the pointer. Recovery can scan complete
        # snapshot directories if a kill happens between these two commits.
        volume.commit()
        pointer = directory / "latest_checkpoint.json.tmp"
        pointer.write_text(json.dumps({"checkpoint_path": str(checkpoint), "step": step}))
        pointer.replace(directory / "latest_checkpoint.json")
        volume.commit()

    model.train()
    status = "completed"
    if not resume:
        save_checkpoint()
    while step < max_steps:
        if time.monotonic() - started > 1400:
            status = "checkpointed_time_limit"
            break
        optimizer.zero_grad(set_to_none=True)
        step_loss = 0.0
        step_cpu_rng = torch.get_rng_state()
        step_cuda_rng = torch.cuda.get_rng_state_all()
        for micro in range(accumulation):
            if time.monotonic() - started > 1400:
                status = "checkpointed_time_limit"
                break
            row = rows[(step * accumulation + micro) % len(rows)]
            ids = torch.tensor([row["input_ids"]], device="cuda")
            labels = torch.tensor([row["labels"]], device="cuda")
            loss = model(input_ids=ids, attention_mask=torch.ones_like(ids), labels=labels).loss
            if not torch.isfinite(loss):
                raise FloatingPointError("Non-finite training loss")
            (loss / accumulation).backward()
            step_loss += float(loss.detach()) / accumulation
        if status != "completed":
            # Discard partial accumulation; the saved step always means a full
            # optimizer update. Zero dropout makes recomputation deterministic.
            optimizer.zero_grad(set_to_none=True)
            torch.set_rng_state(step_cpu_rng)
            torch.cuda.set_rng_state_all(step_cuda_rng)
            break
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        step += 1
        losses.append({"step": step, "loss": step_loss})
        if step % checkpoint_every == 0:
            save_checkpoint()
    save_checkpoint()
    final = directory / ("adapter-" + checkpoint.name)
    model.save_pretrained(final)
    # Preserve the original template: training does not install a replacement.
    tokenizer.save_pretrained(final)
    metadata = {"status": status, "adapter_path": str(final), "checkpoint_path": str(checkpoint),
                "steps_completed": step, "losses": losses, "examples_count": len(rows),
                "supervised_tokens": sum(sum(x != -100 for x in row["labels"]) for row in rows),
                "dataset_sha256": fingerprint, "quantization": "nf4-double-bfloat16",
                "lora_rank": 8, "gradient_accumulation": accumulation,
                "max_length": max_length, "learning_rate": learning_rate,
                "seed": seed, "max_steps": max_steps, **_metadata(started)}
    (directory / "result.json").write_text(json.dumps(metadata, indent=2))
    volume.commit()
    return metadata
