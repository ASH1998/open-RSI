import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from rsilab.dataset_io import read_development_splits


class DevelopmentReads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'full').mkdir()
        self.hashes = {}
        for split in ('train','validation','test'):
            key=f'full/{split}-00000-of-00001.parquet'
            data=split.encode();(self.root/key).write_bytes(data)
            self.hashes[key]=hashlib.sha256(data).hexdigest()
        self.calls=[]
        def read_table(path):
            self.calls.append(Path(path).name)
            if 'test-' in str(path):raise AssertionError('Final split was decoded')
            return types.SimpleNamespace(to_pylist=lambda:[{'id':1}])
        self.mock=types.SimpleNamespace(read_table=read_table)
        self.modules={'pyarrow':types.SimpleNamespace(parquet=self.mock),'pyarrow.parquet':self.mock}

    def read(self, **kwargs):
        with patch.dict('sys.modules',self.modules):
            return read_development_splits(self.root,source_hashes=self.hashes,expected_counts={'train':1,'validation':1},**kwargs)

    def test_only_requested_splits_are_opened(self):
        self.assertEqual(set(self.read(splits=('train',))),{'train'})
        self.assertEqual(self.calls,['train-00000-of-00001.parquet'])

    def test_final_split_forbidden_before_decode(self):
        with self.assertRaises(ValueError):self.read(splits=('train','test'))
        self.assertEqual(self.calls,[])

    def test_hash_failure_prevents_all_decoding(self):
        (self.root/'full/validation-00000-of-00001.parquet').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.read()
        self.assertEqual(self.calls,[])

    def test_config_traversal_and_duplicate_splits(self):
        for kw in ({'config':'../full'},{'splits':('train','train')}):
            with self.assertRaises(ValueError):self.read(**kw)
        self.assertEqual(self.calls,[])

    def test_symlink_rejected(self):
        target=self.root/'full/train-00000-of-00001.parquet';target.unlink();target.symlink_to(self.root/'full/test-00000-of-00001.parquet')
        with self.assertRaises(ValueError):self.read()
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
