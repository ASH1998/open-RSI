"""CPU-only artifact containment checks, including a symlinked Volume mount."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi import modal_workers as worker


class AdapterPathTests(unittest.TestCase):
    def setUp(self):
        work = Path(__file__).resolve().parents[1] / "work"
        work.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="worker-paths-", dir=work)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.storage = self.base / "volume-storage"
        self.root = self.storage / "adapters"
        self.adapter = self.root / "run-one" / "adapter-final"
        self.adapter.mkdir(parents=True)

    def test_normal_directory(self):
        with patch.object(worker, "ADAPTER_ROOT", self.root):
            self.assertEqual(worker._adapter_path(str(self.adapter)), self.adapter.resolve())

    def test_symlinked_mount_parent(self):
        mount = self.base / "artifacts"
        mount.symlink_to(self.storage, target_is_directory=True)
        exposed_root = mount / "adapters"
        exposed_adapter = exposed_root / "run-one" / "adapter-final"
        # This was the old check: canonical candidate versus lexical root.
        self.assertFalse(exposed_adapter.resolve().is_relative_to(exposed_root))
        with patch.object(worker, "ADAPTER_ROOT", exposed_root):
            self.assertEqual(worker._adapter_path(str(exposed_adapter)), self.adapter.resolve())

    def test_symlinked_adapter_root_and_checkpoint_parent(self):
        exposed_root = self.base / "adapters-link"
        exposed_root.symlink_to(self.root, target_is_directory=True)
        checkpoint = self.root / "run-one" / "checkpoints" / "step-000020"
        checkpoint.mkdir(parents=True)
        with patch.object(worker, "ADAPTER_ROOT", exposed_root):
            resolved = worker._adapter_path(str(exposed_root / "run-one" / "checkpoints" / checkpoint.name))
            self.assertEqual(resolved.parent, (exposed_root / "run-one" / "checkpoints").resolve())

    def test_symlink_inside_root_is_allowed(self):
        alias = self.root / "alias"
        alias.symlink_to(self.adapter, target_is_directory=True)
        with patch.object(worker, "ADAPTER_ROOT", self.root):
            self.assertEqual(worker._adapter_path(str(alias)), self.adapter.resolve())

    def test_symlink_escape_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        escape = self.root / "escape"
        escape.symlink_to(outside, target_is_directory=True)
        with patch.object(worker, "ADAPTER_ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "resolves outside"):
                worker._adapter_path(str(escape))

    def test_traversal_root_and_wrong_prefix_are_rejected(self):
        with patch.object(worker, "ADAPTER_ROOT", self.root):
            for value in (str(self.root) + "/../", str(self.root) + "/.",
                          str(self.root) + "-other/run", "relative/run", None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    worker._adapter_path(value)

    def test_missing_file_and_dangling_link_are_rejected(self):
        file = self.root / "file"
        file.write_text("not a directory")
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "missing", target_is_directory=True)
        with patch.object(worker, "ADAPTER_ROOT", self.root):
            for path in (file, self.root / "missing", dangling):
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "does not exist"):
                    worker._adapter_path(str(path))


if __name__ == "__main__":
    unittest.main()
