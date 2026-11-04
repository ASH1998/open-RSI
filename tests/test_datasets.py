import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi.datasets import (ALLOWED_IMPORTS, DEFAULT_ROOT, REVISION, SOURCE_SPLITS,
                          build_mbpp_pools, digest, download_mbpp, model_input, select_tasks)


def row(i, text, code, test):
    return {"task_id": i, "text": text, "code": code, "test_list": [test],
            "test_setup_code": "", "challenge_test_list": []}


def fixture():
    return {
        "train": [row(1, "Count vowels in a string.",
                      "def vowels(word):\n return sum(c in 'aeiou' for c in word)",
                      "assert vowels('hello') == 2"),
                  row(2, "Multiply two numbers.", "def product(a, b):\n return a * b",
                      "assert product(2, 3) == 6")],
        "validation": [row(3, "Sort the list of names.",
                           "def names(xs):\n return sorted(xs)",
                           "assert names(['z', 'a']) == ['a', 'z']")],
        "test": [], "prompt": [],
    }


class DatasetTests(unittest.TestCase):
    def test_deterministic_input_order_independent_and_json(self):
        raw = fixture()
        before = copy.deepcopy(raw)
        first = build_mbpp_pools(raw)
        reordered = {s: list(reversed(raw[s])) for s in reversed(SOURCE_SPLITS)}
        self.assertEqual(first, build_mbpp_pools(reordered))
        self.assertEqual(raw, before)
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        expected_hash = first.pop('manifest_sha256')
        self.assertEqual(expected_hash, digest(first))

    def test_every_eligible_row_available_and_source_splits_preserved(self):
        manifest = build_mbpp_pools(fixture())
        self.assertEqual(manifest['eligible_counts'], {'train': 2, 'dev': 1})
        for split, source in [('train', 'train'), ('dev', 'validation')]:
            for task in manifest['pools'][split]:
                self.assertEqual(task['split'], split)
                self.assertEqual(task['metadata']['source_split'], source)
                self.assertEqual(task['metadata']['revision'], REVISION)
        self.assertFalse(manifest['ready_for_training'])

    def test_model_projection_excludes_reference_and_hidden_tests(self):
        raw = fixture()
        raw['train'][0]['test_setup_code'] = "secret_setup_marker = 31337"
        raw['train'][0]['challenge_test_list'] = ["assert vowels('secret_challenge') == 5"]
        task = next(t for t in build_mbpp_pools(raw)['pools']['train'] if t['entry_point'] == 'vowels')
        public = model_input(task)
        self.assertEqual(set(public), {'prompt', 'entry_point'})
        self.assertIn('def vowels(word):', public['prompt'])
        self.assertIn('no explanation or long comments', public['prompt'])
        self.assertIn(', '.join(ALLOWED_IMPORTS), public['prompt'])
        self.assertNotIn(raw['train'][0]['code'], public['prompt'])
        self.assertNotIn('secret_', public['prompt'])
        self.assertNotIn('hello', public['prompt'])
        self.assertEqual(task['verification_mode'], 'python_assertions')
        self.assertNotIn('code', task)
        self.assertEqual(task['test_setup_code'], raw['train'][0]['test_setup_code'])
        self.assertEqual(task['challenge_test_list'], raw['train'][0]['challenge_test_list'])

    def test_no_execution_of_dataset_code_or_tests(self):
        raw = fixture()
        raw['train'][0]['code'] = "raise RuntimeError('must never run')\n" + raw['train'][0]['code']
        raw['train'][0]['test_setup_code'] = "raise RuntimeError('must never run')"
        with patch('builtins.exec', side_effect=AssertionError('execution forbidden')):
            self.assertEqual(build_mbpp_pools(raw)['eligible_counts']['train'], 2)

    def test_cross_split_renamed_literal_variant_quarantined(self):
        raw = fixture()
        raw['validation'].append(row(4, "Different wording for multiplication.",
                                      "def times(x, y):\n return x * y",
                                      "assert times(8, 9) == 72"))
        manifest = build_mbpp_pools(raw)
        self.assertEqual({e['source_id'] for e in manifest['exclusions']}, {2, 4})
        self.assertTrue(all(e['reason'] == 'cross_split_duplicate_cluster' for e in manifest['exclusions']))

    def test_near_description_and_transitive_components(self):
        raw = fixture()
        raw['train'][0]['text'] = 'Count unique alphabet vowels within lowercase words ignoring punctuation'
        raw['train'].append(row(4, 'Count unique alphabet vowels within lowercase words ignoring punctuation marks',
                                'def other(x):\n return x[::-1]', "assert other('ab') == 'ba'"))
        raw['test'].append(row(5, 'Completely distinct description',
                               'def reverse(y):\n return y[::-1]', "assert reverse('cd') == 'dc'"))
        manifest = build_mbpp_pools(raw)
        self.assertEqual({e['source_id'] for e in manifest['exclusions']}, {1, 4})
        self.assertTrue(all(e['reason'] == 'cross_split_duplicate_cluster' for e in manifest['exclusions']))

    def test_within_split_duplicates_keep_lowest_id(self):
        raw = fixture()
        duplicate = copy.deepcopy(raw['train'][1])
        duplicate['task_id'] = 9
        raw['train'].insert(0, duplicate)
        manifest = build_mbpp_pools(raw)
        self.assertEqual(manifest['exclusions'][0]['source_id'], 9)
        self.assertEqual(manifest['exclusions'][0]['reason'], 'within_split_duplicate_cluster')

    def test_test_and_prompt_are_never_sampled(self):
        raw = fixture()
        raw['test'] = [row(8, 'Raise a number to an exponent.',
                           'def power(x, y):\n return x ** y', 'assert power(2, 3) == 8')]
        raw['prompt'] = [row(9, 'Check membership of an item.',
                             'def member(x, xs):\n return x in xs', 'assert member(1, [1])')]
        manifest = build_mbpp_pools(raw)
        self.assertEqual(set(manifest['pools']), {'train', 'dev'})
        self.assertFalse({8, 9} & {t['metadata']['source_id'] for p in manifest['pools'].values() for t in p})
        for split in ('test', 'prompt', 'validation'):
            with self.assertRaises(ValueError):
                select_tasks(manifest, split, 1)

    def test_protected_final_domain_and_unsupported_signature(self):
        raw = fixture()
        raw['train'][0]['text'] = 'Compute graph reachability.'
        raw['train'][1]['code'] = 'def product(a, b=unknown()):\n return a * b'
        manifest = build_mbpp_pools(raw)
        self.assertEqual({e['reason'] for e in manifest['exclusions']},
                         {'protected_pilot_final_domain', 'unsupported_signature_or_test_syntax'})

    def test_exact_count_after_external_filter_and_copy_isolation(self):
        manifest = build_mbpp_pools(fixture())
        ids = [t['id'] for t in manifest['pools']['train']]
        selected = select_tasks(manifest, 'train', 1, eligible_ids=ids[1:])
        self.assertEqual(selected[0]['id'], ids[1])
        selected[0]['test_list'].clear()
        self.assertTrue(manifest['pools']['train'][1]['test_list'])
        for count in (0, True, 3):
            with self.assertRaises(ValueError):
                select_tasks(manifest, 'train', count)
        with self.assertRaises(ValueError):
            select_tasks(manifest, 'train', 1, eligible_ids=['mbpp-full-3'])

    def test_malformed_rows_and_missing_split_rejected(self):
        for mutate in (lambda d: d.pop('test'),
                       lambda d: d['train'][0].update(task_id=True),
                       lambda d: d['train'][0].update(test_list=[]),
                       lambda d: d['train'][0].update(challenge_test_list='not a list'),
                       lambda d: d['train'][1].update(task_id=1)):
            raw = fixture()
            mutate(raw)
            with self.assertRaises(ValueError):
                build_mbpp_pools(raw)

    def test_cached_source_corruption_rejected_without_network(self):
        temporary = DEFAULT_ROOT / '.tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            path = Path(directory) / 'raw'
            path.mkdir()
            (path / 'README.md').write_text('tampered')
            with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network')):
                with self.assertRaisesRegex(ValueError, 'source checksum mismatch'):
                    download_mbpp(directory)

    def test_literal_defaults_only_and_annotations_not_leaked(self):
        raw = fixture()
        raw['train'][1]['code'] = 'def product(a: SecretType, b=2):\n return a * b'
        task = next(t for t in build_mbpp_pools(raw)['pools']['train'] if t['entry_point'] == 'product')
        self.assertIn('def product(a, b=2):', task['prompt'])
        self.assertNotIn('SecretType', task['prompt'])


if __name__ == '__main__':
    unittest.main()
