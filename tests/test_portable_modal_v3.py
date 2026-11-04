"""Offline resource, request, and frozen-kernel parity checks; no GPU jobs."""
import ast
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

from rsilab.providers import portable_modal_v3 as portable
from rsilab.providers.modal import ModalBackend
from rsilab.resources import gpu_worker_v1 as worker

ROOT = Path(__file__).resolve().parents[1]
MODEL = "openbmb/MiniCPM5-2B"
REVISION = "f97400052a43d642bbc6e9975e2397e3ae6a6b52"


def config(**kwargs):
    return portable.PortableModalConfig("portable-test", "existing-test-volume", MODEL, REVISION, **kwargs)


class FakeFunction:
    def __init__(self, function):
        self.function, self.calls = function, []
    def spawn(self, *args):
        self.calls.append(args)
        return types.SimpleNamespace(object_id="fake-call", get=lambda timeout: {"status": "completed"}, cancel=Mock())


class FakeSDK:
    def __init__(self):
        self.operations, self.options, self.functions = [], [], []
        self.Image = types.SimpleNamespace(debian_slim=lambda **kwargs: self.record("debian_slim", kwargs))
        self.Volume = types.SimpleNamespace(from_name=lambda name, **kwargs: self.record("volume", (name, kwargs)))
        self.App = lambda name, **kwargs: self.record("app", (name, kwargs))
    def record(self, name, value): self.operations.append((name, value)); return self
    def env(self, value): return self.record("env", value)
    def pip_install(self, *pins): return self.record("pip_install", pins)
    def add_local_python_source(self, name, **kwargs): return self.record("source", (name, kwargs))
    def function(self, **kwargs):
        self.options.append(kwargs)
        def wrap(function):
            bound = FakeFunction(function); self.functions.append(bound); return bound
        return wrap


class PortableModalV3Tests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "work", prefix="portable-modal-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_no_image_environment_layer_or_volume_paths_in_build(self):
        class NoEnvSDK(FakeSDK):
            def env(self, value):
                raise AssertionError("V3 must never call image.env, even after pip")
        sdk = NoEnvSDK()
        portable.create_modal_workers(config(), sdk=sdk)
        self.assertEqual([name for name, value in sdk.operations],
                         ["debian_slim", "pip_install", "source", "volume", "app"])
        for name, value in sdk.operations[:2]:
            self.assertNotIn("/artifacts", json.dumps(value))
        self.assertNotIn(".env(", Path(portable.__file__).read_text())

    def test_probe_is_cpu_only_bounded_and_shares_actual_image_and_volume(self):
        sdk = FakeSDK(); bundle = portable.create_modal_workers(config(), sdk=sdk)
        generate, train, probe = sdk.options
        self.assertIs(probe["image"], generate["image"])
        self.assertIs(probe["image"], train["image"])
        self.assertIs(probe["volumes"]["/artifacts"], generate["volumes"]["/artifacts"])
        self.assertNotIn("gpu", probe)
        self.assertEqual(probe["cpu"], (2, 2))
        self.assertEqual(probe["memory"], (2048, 2048))
        self.assertEqual(probe["timeout"], 120)
        self.assertEqual((probe["min_containers"], probe["max_containers"], probe["buffer_containers"]), (0, 1, 0))
        self.assertEqual(probe["secrets"], [])
        self.assertEqual(probe["retries"], 0)
        self.assertFalse(probe["include_source"])
        self.assertFalse(any(function.calls for function in sdk.functions))
        self.assertEqual(bundle.probe.spawn().object_id, "fake-call")
        self.assertEqual(sdk.functions[2].calls, [(config().to_dict(), bundle.provenance["worker"])])
        with self.assertRaises(TypeError): bundle.probe.spawn({"prompts": []})

    def test_versioned_entrypoints_and_inventory_exclude_previous_factories(self):
        sdk = FakeSDK(); bundle = portable.create_modal_workers(config(), sdk=sdk)
        self.assertEqual(bundle.provenance["worker"]["worker_version"], "portable-qlora-v3")
        self.assertEqual(bundle.provenance["worker"]["kernel_version"], "portable-qlora-v1")
        self.assertIn("providers/portable_modal_v3.py", portable.SOURCE_ALLOWLIST)
        self.assertNotIn("providers/portable_modal_v2.py", portable.SOURCE_ALLOWLIST)
        self.assertNotIn("providers/portable_modal.py", portable.SOURCE_ALLOWLIST)
        self.assertEqual([f.function.__module__ for f in sdk.functions], [portable.__name__] * 3)
        self.assertEqual([f.function.__name__ for f in sdk.functions],
                         ["_generate_entry_v3", "_train_entry_v3", "_probe_entry_v3"])

    def test_probe_initializes_runtime_after_mount_without_loading_model(self):
        cfg = config(volume_mount=str(self.root / "remote"))
        volume = Mock()
        def reload(): Path(cfg.volume_mount).mkdir()
        volume.reload.side_effect = reload
        fake_modal = types.SimpleNamespace(Volume=types.SimpleNamespace(from_name=Mock(return_value=volume)))
        inventory = portable.resource_inventory()
        pins = dict(pin.split("==") for pin in inventory["requirements"])
        packages = {**pins, "transitive-package": "1.2.3"}
        distributions = [types.SimpleNamespace(metadata={"Name": name}, version=value)
                         for name, value in packages.items()]
        distributions.append(types.SimpleNamespace(metadata={"Name": None}, version="unused"))
        old_tempdir = tempfile.tempdir
        imports = set(sys.modules)
        try:
            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"modal": fake_modal}), patch("importlib.metadata.distributions", return_value=distributions) as inspect, patch.object(portable, "_bound_runtime", side_effect=AssertionError("Model runtime must not bind")):
                result = portable._probe_entry_v3(cfg.to_dict(), inventory)
                volume.reload.assert_called_once_with()
                volume.commit.assert_called_once_with()
                self.assertEqual(result["status"], "completed")
                self.assertTrue(result["mounted_volume_is_dir"])
                self.assertFalse(result["gpu_requested"])
                self.assertEqual(result["packages"], packages)
                self.assertEqual(result["portable_worker"], {"worker": inventory, "config": cfg.to_dict(), "config_sha256": cfg.sha256})
                self.assertEqual(result["dependency_inspection"], "distribution_metadata_only")
                inspect.assert_called_once_with()
                self.assertTrue(all(Path(p).is_dir() for p in result["cache_directories"]))
                self.assertEqual(os.environ["TMPDIR"], str(Path(cfg.volume_mount) / "tmp"))
                self.assertEqual(tempfile.tempdir, os.environ["TMPDIR"])
        finally: tempfile.tempdir = old_tempdir
        self.assertFalse({"torch", "transformers", "peft", "bitsandbytes"} & (set(sys.modules) - imports))

    def test_probe_inventory_and_missing_mount_fail_before_cache_creation(self):
        cfg = config(volume_mount=str(self.root / "absent"))
        volume = Mock(); from_name = Mock(return_value=volume)
        fake_modal = types.SimpleNamespace(Volume=types.SimpleNamespace(from_name=from_name))
        with patch.dict(sys.modules, {"modal": fake_modal}):
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                portable._probe_entry_v3(cfg.to_dict(), {})
            from_name.assert_not_called()
            with self.assertRaisesRegex(ValueError, "volume directory is missing"):
                portable._probe_entry_v3(cfg.to_dict(), portable.resource_inventory())
            volume.commit.assert_not_called()
            self.assertFalse(Path(cfg.volume_mount).exists())

    def test_config_is_immutable_and_requires_pinned_explicit_identity(self):
        value = config()
        with self.assertRaises(FrozenInstanceError): value.gpu = "other"
        self.assertEqual(portable.PortableModalConfig(**value.to_dict()), value)
        self.assertEqual(len(value.sha256), 64)
        for change in ({"model_revision": "main"}, {"model_id": "https://model"}, {"gpu": "unbounded"},
                       {"python_version": "3.13"}, {"volume_mount": "/"}, {"volume_mount": "/root/data"},
                       {"volume_mount": "/artifacts/../outside"}, {"create_volume": 1}):
            with self.subTest(change=change), self.assertRaises(ValueError): replace(value, **change)

    def test_packaged_requirements_and_origin_are_pinned(self):
        inventory = portable.resource_inventory()
        self.assertEqual(inventory["historical_source"]["sha256"], hashlib.sha256((ROOT / "rsi/modal_workers.py").read_bytes()).hexdigest())
        self.assertEqual(inventory["historical_requirements"]["sha256"], hashlib.sha256((ROOT / "requirements-gpu.txt").read_bytes()).hexdigest())
        self.assertEqual(set(inventory["source_hashes"]), set(portable.SOURCE_ALLOWLIST))
        historical = ast.parse((ROOT / "rsi/modal_workers.py").read_text())
        pins = next(ast.literal_eval(node.value) for node in historical.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "GPU_PACKAGES" for target in node.targets))
        self.assertEqual(inventory["requirements"], list(pins))

    def test_resource_tampering_is_rejected_before_sdk_definition(self):
        staging = self.root / "package"
        package = portable.resources.files("rsilab")
        for name in portable.SOURCE_ALLOWLIST:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.joinpath(*name.split("/")).read_bytes())
        (staging / "resources/gpu_requirements_v1.txt").write_text("torch==0.0.0\n")
        sdk = FakeSDK()
        with patch.object(portable.resources, "files", return_value=staging):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                portable.create_modal_workers(config(), sdk=sdk)
        self.assertEqual(sdk.operations, [])

    def test_all_eleven_kernel_functions_match_frozen_source_after_declared_edits(self):
        source = (ROOT / "rsi/modal_workers.py").read_text()
        historical = ast.parse(source)
        resource_dir = portable.resources.files("rsilab.resources")
        manifest = json.loads(resource_dir.joinpath(portable.PROVENANCE_RESOURCE).read_text())
        actual = {node.name: node for node in ast.parse(resource_dir.joinpath("gpu_worker_v1.py").read_text()).body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(set(actual), set(manifest["parity_functions"]))
        for node in historical.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in actual: continue
            text = ast.get_source_segment(source, node)
            for before, after in manifest["replacements"].items(): text = text.replace(before, after)
            expected = ast.parse(text).body[0]
            self.assertEqual(ast.dump(actual[node.name], include_attributes=False), ast.dump(expected, include_attributes=False), node.name)
        # This includes the full optimizer/RNG checkpoint and restore algorithm.
        self.assertIn('"training_state.pt"', source)

    def test_prompt_and_supervised_mask_preserve_historical_token_contract(self):
        runtime = portable._bound_runtime(config(), None, "a" * 64)
        tokenizer = Mock()
        tokenizer.apply_chat_template.side_effect = [[1, 2], [1, 2, 3, 4]]
        self.assertEqual(runtime["_encode_example"](tokenizer, {"prompt": "p", "completion": "c"}, 64),
                         {"input_ids": [1, 2, 3, 4], "labels": [-100, -100, 3, 4]})
        self.assertTrue(all(call.kwargs["return_dict"] is False for call in tokenizer.apply_chat_template.call_args_list))
        tokenizer.apply_chat_template.side_effect = [[1, 2], [1, 2, 3, 4]]
        with self.assertRaisesRegex(ValueError, "exceeds max_length"):
            runtime["_encode_example"](tokenizer, {"prompt": "p", "completion": "c"}, 3)
        tokenizer.apply_chat_template.side_effect = [[1, 2], [9, 3, 4]]
        with self.assertRaisesRegex(ValueError, "prefix"):
            runtime["_encode_example"](tokenizer, {"prompt": "p", "completion": "c"}, 64)

    def test_runtime_binding_is_per_call_and_keeps_keyword_defaults(self):
        a = portable._bound_runtime(config(), object(), "a" * 64)
        changed = replace(config(), model_id="another/public-model", model_revision="b" * 40)
        b = portable._bound_runtime(changed, object(), "b" * 64)
        self.assertEqual(a["_identity"]({}), (MODEL, REVISION))
        self.assertEqual(b["_identity"]({}), (changed.model_id, changed.model_revision))
        self.assertIsNone(worker.MODEL_ID)
        self.assertEqual(a["_load"].__kwdefaults__, {"training": False})
        self.assertIsNot(a["train"].__globals__, b["train"].__globals__)

    def test_existing_adapter_and_symlinked_mount_work_but_escape_does_not(self):
        storage = self.root / "storage"; adapter = storage / "adapters/old-run/adapter"
        adapter.mkdir(parents=True)
        mount = self.root / "mounted"; mount.symlink_to(storage, target_is_directory=True)
        runtime = portable._bound_runtime(config(volume_mount=str(mount)), None, "a" * 64)
        self.assertEqual(runtime["_adapter_path"](str(mount / "adapters/old-run/adapter")), adapter.resolve())
        outside = self.root / "outside"; outside.mkdir()
        (storage / "adapters/escape").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outside"):
            runtime["_adapter_path"](str(mount / "adapters/escape"))

    def test_factory_only_defines_lazy_resources_and_explicit_source_allowlist(self):
        sdk = FakeSDK(); bundle = portable.create_modal_workers(config(), sdk=sdk)
        self.assertEqual(len(sdk.functions), 3)
        self.assertTrue(all(not function.calls for function in sdk.functions))
        for option in sdk.options[:2]:
            self.assertEqual(option["retries"], 0)
            self.assertEqual(option["secrets"], [])
            self.assertEqual((option["min_containers"], option["max_containers"], option["timeout"]), (0, 1, 1800))
            self.assertFalse(option["include_source"])
            self.assertEqual(set(option["volumes"]), {"/artifacts"})
            self.assertNotIn("serialized", option)
        name, options = next(value for operation, value in sdk.operations if operation == "source")
        self.assertEqual(name, "rsilab")
        for path in portable.SOURCE_ALLOWLIST: self.assertFalse(options["ignore"](Path(path)), path)
        for path in (".env", "learning.py", "credentials.json", "resources/unlisted.py"):
            self.assertTrue(options["ignore"](Path(path)), path)
        self.assertEqual(bundle.provenance["config_sha256"], config().sha256)
        copied = bundle.provenance; copied["worker"]["requirements"].clear()
        self.assertTrue(bundle.provenance["worker"]["requirements"])

    def test_bound_functions_are_compatible_with_durable_modal_backend(self):
        sdk = FakeSDK(); bundle = portable.create_modal_workers(config(), sdk=sdk)
        report, saved = {}, []
        backend = ModalBackend(generate_function=bundle.generate, train_function=bundle.train,
                               report=report, persist=lambda report: saved.append(json.loads(json.dumps(report))), max_calls=1)
        request = {"prompts": [{"id": "task", "prompt": "public task"}], "adapter_path": "/artifacts/adapters/old/adapter", "adapter_sha256": "a" * 64}
        self.assertEqual(backend.generate(request), {"status": "completed"})
        passed_request, passed_config, passed_inventory = sdk.functions[0].calls[0]
        self.assertEqual(passed_request["model_id"], MODEL)
        self.assertEqual(passed_request["adapter_path"], request["adapter_path"])
        self.assertEqual(passed_config, config().to_dict())
        self.assertEqual(passed_inventory, bundle.provenance["worker"])
        self.assertNotIn("model_id", request)
        self.assertEqual(saved[1]["remote_calls"][0]["call_id"], "fake-call")

    def test_invalid_requests_never_reach_spawn(self):
        sdk = FakeSDK(); bundle = portable.create_modal_workers(config(), sdk=sdk)
        valid = {"prompts": [{"id": "task", "prompt": "p"}]}
        for extra in ({"revision": "main"}, {"max_new_tokens": 769}, {"seed": True},
                      {"temperature": float("nan")}, {"MODAL_TOKEN_SECRET": "never-send"},
                      {"adapter_path": "/artifacts/adapters/old/adapter"},
                      {"adapter_path": "/artifacts/adapters/old/adapter", "adapter_sha256": "invalid"},
                      {"adapter_sha256": "a" * 64},
                      {"adapter_path": "/outside/adapter"}, {"adapter_path": "/artifacts/adapters/x/../outside"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError): bundle.generate.spawn({**valid, **extra})
        with self.assertRaises(ValueError): bundle.generate.spawn({"prompts": [{"id": "x", "prompt": "p", "reference_code": "private"}]})
        with self.assertRaises(ValueError): bundle.generate.spawn({"prompts": valid["prompts"] * 2})
        self.assertEqual(sdk.functions[0].calls, [])

    def test_train_only_verified_targets_fresh_or_explicit_resume(self):
        sdk = FakeSDK(); bundle = portable.create_modal_workers(config(), sdk=sdk)
        value = {"run_id": "fresh-run", "examples": [{"prompt": "p", "completion": "c", "verified": True}]}
        bundle.train.spawn(value)
        bundle.train.spawn({**value, "resume_checkpoint": "/artifacts/adapters/fresh-run/checkpoints/step-000001"})
        self.assertEqual(len(sdk.functions[1].calls), 2)
        for extra in ({"adapter_path": "/artifacts/adapters/old/adapter"}, {"max_steps": 201},
                      {"examples": [{"prompt": "p", "completion": "c", "verified": False}]},
                      {"run_id": "../escape"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError): bundle.train.spawn({**value, **extra})
        self.assertEqual(len(sdk.functions[1].calls), 2)

    def test_remote_inventory_check_precedes_worker_execution(self):
        with patch.dict(sys.modules, {"modal": types.SimpleNamespace()}), patch.object(portable, "_bound_runtime") as runtime:
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                portable._execute("generate", {}, config().to_dict(), {"incorrect": True})
            runtime.assert_not_called()

    def test_remote_binding_records_provenance_without_gpu_imports(self):
        cfg = config(volume_mount=str(self.root / "remote"))
        inventory = portable.resource_inventory(); real_bind = portable._bound_runtime
        volume = Mock(); fake_modal = types.SimpleNamespace(Volume=types.SimpleNamespace(from_name=Mock(return_value=volume)))
        seen = {}
        def bind(config, passed_volume, fingerprint):
            if passed_volume is None: return real_bind(config, None, fingerprint)
            volume.reload.assert_called_once_with()
            volume.commit.assert_called_once_with()
            self.assertTrue((self.root / "remote/tmp").is_dir())
            seen.update(volume=passed_volume, fingerprint=fingerprint)
            runtime = {"_metadata": lambda started: {"gpu_name": "fake-gpu"}}
            runtime["_generate"] = lambda request: {"request": request, **runtime["_metadata"](0)}
            return runtime
        old_tempdir = tempfile.tempdir
        try:
            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"modal": fake_modal}), patch.object(portable, "_bound_runtime", side_effect=bind):
                result = portable._execute("generate", {"prompts": [{"prompt": "p"}]}, cfg.to_dict(), inventory)
                self.assertEqual(os.environ["HF_HOME"], str(self.root / "remote/hf-cache"))
                self.assertEqual(tempfile.tempdir, str(self.root / "remote/tmp"))
                self.assertEqual(os.environ["WANDB_MODE"], "disabled")
        finally:
            tempfile.tempdir = old_tempdir
        self.assertIs(seen["volume"], volume)
        self.assertEqual(result["portable_worker"]["worker"], inventory)
        self.assertEqual(result["portable_worker"]["config_sha256"], cfg.sha256)
        self.assertEqual(seen["fingerprint"], portable._digest(result["portable_worker"]))
        self.assertIsNone(result["adapter_sha256"])

    def test_remote_adapter_digest_is_verified_after_reload_before_model_loading(self):
        cfg = config(volume_mount=str(self.root / "remote"))
        adapter = Path(cfg.volume_mount) / "adapters/old/adapter"
        adapter.mkdir(parents=True)
        weights = adapter / "adapter_model.safetensors"
        weights.write_bytes(b"frozen adapter bytes")
        checksum = hashlib.sha256(weights.read_bytes()).hexdigest()
        real_bind = portable._bound_runtime
        volume = Mock(); load = Mock(return_value="model")
        fake_modal = types.SimpleNamespace(Volume=types.SimpleNamespace(from_name=Mock(return_value=volume)))
        def bind(config, passed_volume, fingerprint):
            runtime = real_bind(config, passed_volume, fingerprint)
            if passed_volume is None: return runtime
            runtime["_metadata"] = lambda started: {}
            runtime["_load"] = load
            def generate(request):
                volume.reload()
                runtime["_load"](request)
                return runtime["_metadata"](0)
            runtime["_generate"] = generate
            return runtime
        request = {"prompts": [{"prompt": "p"}], "adapter_path": str(adapter)}
        old_tempdir = tempfile.tempdir
        try:
            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"modal": fake_modal}), patch.object(portable, "_bound_runtime", side_effect=bind):
                with self.assertRaisesRegex(ValueError, "mismatch before model loading"):
                    portable._execute("generate", {**request, "adapter_sha256": "0" * 64}, cfg.to_dict(), portable.resource_inventory())
                load.assert_not_called()
                self.assertEqual(volume.reload.call_count, 2)
                result = portable._execute("generate", {**request, "adapter_sha256": checksum}, cfg.to_dict(), portable.resource_inventory())
                load.assert_called_once()
                self.assertEqual(result["adapter_sha256"], checksum)
        finally: tempfile.tempdir = old_tempdir

    def test_training_return_hashes_saved_weights_and_rejects_symlink_weights(self):
        cfg = config(volume_mount=str(self.root / "remote"))
        adapter = Path(cfg.volume_mount) / "adapters/new/adapter"
        adapter.mkdir(parents=True)
        weights = adapter / "adapter_model.safetensors"
        real_bind = portable._bound_runtime
        volume = Mock()
        fake_modal = types.SimpleNamespace(Volume=types.SimpleNamespace(from_name=Mock(return_value=volume)))
        def bind(config, passed_volume, fingerprint):
            runtime = real_bind(config, passed_volume, fingerprint)
            if passed_volume is None: return runtime
            runtime["_metadata"] = lambda started: {}
            def train(request):
                weights.write_bytes(b"newly saved weights")
                return {"adapter_path": str(adapter), **runtime["_metadata"](0)}
            runtime["train"] = train
            return runtime
        request = {"run_id": "new", "examples": [{"prompt": "p", "completion": "c", "verified": True}]}
        old_tempdir = tempfile.tempdir
        try:
            with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"modal": fake_modal}), patch.object(portable, "_bound_runtime", side_effect=bind):
                result = portable._execute("train", request, cfg.to_dict(), portable.resource_inventory())
            self.assertEqual(result["adapter_sha256"], hashlib.sha256(weights.read_bytes()).hexdigest())
            weights.unlink(); outside = self.root / "outside-weights"; outside.write_bytes(b"outside")
            weights.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                portable._adapter_digest(real_bind(cfg, None, "test"), str(adapter))
        finally: tempfile.tempdir = old_tempdir

    def test_package_resources_load_without_checkout_or_optional_dependencies(self):
        staging = self.root / "installed"
        package = portable.resources.files("rsilab")
        for name in portable.SOURCE_ALLOWLIST:
            destination = staging / "rsilab" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(package.joinpath(*name.split("/")).read_bytes())
        archive = self.root / "resources.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for path in staging.rglob("*"):
                if path.is_file(): zipped.write(path, path.relative_to(staging))
        code = '''
import importlib.abc, json, pathlib, socket, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'rsi','modal','torch','transformers','peft','wandb','dotenv'}:
            raise AssertionError('Optional provider/checkout import: '+fullname)
sys.meta_path.insert(0, Block())
def blocked(*args, **kwargs): raise AssertionError('No networking')
socket.socket.connect=blocked;socket.create_connection=blocked
sys.path.insert(0,sys.argv[1])
from rsilab.providers.portable_modal_v3 import resource_inventory, PortableModalConfig
value=resource_inventory()
assert len(value['source_hashes'])==10 and len(value['requirements'])==6
assert sys.argv[1] in __import__('rsilab').__file__
print(json.dumps({'version':value['worker_version'],'resources':len(value['source_hashes'])}))
'''
        for location in (staging, archive):
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(location)], cwd=ROOT,
                                    env={"PATH": "/usr/bin:/bin", "TMPDIR": str(self.root)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["resources"], 10)


if __name__ == "__main__": unittest.main()
