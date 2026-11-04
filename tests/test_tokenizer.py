"""CPU regression checks; opt in to cached real-model checks with RSI_TEST_REAL_TOKENIZER=1.

The real checks never download weights or contact the Hub. Populate the pinned
tokenizer in the project's .cache/huggingface/hub before enabling them.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import Mock

from rsi.modal_workers import MODEL_ID, MODEL_REVISION, _encode_example, _prompt_ids


class TokenizerContractTests(unittest.TestCase):
    def test_prompt_explicitly_requests_flat_ids(self):
        tokenizer = Mock()
        tokenizer.apply_chat_template.return_value = [1, 2, 3]
        self.assertEqual(_prompt_ids(tokenizer, "prompt"), [1, 2, 3])
        tokenizer.apply_chat_template.assert_called_once_with(
            [{"role": "user", "content": "prompt"}], tokenize=True,
            add_generation_prompt=True, enable_thinking=False, return_dict=False,
        )

    def test_training_uses_flat_ids_and_masks_only_prompt(self):
        tokenizer = Mock()
        tokenizer.apply_chat_template.side_effect = [[1, 2, 3], [1, 2, 3, 4, 5]]
        row = _encode_example(tokenizer, {"prompt": "p", "completion": "c"}, 64)
        self.assertEqual(row, {"input_ids": [1, 2, 3, 4, 5], "labels": [-100, -100, -100, 4, 5]})
        for call in tokenizer.apply_chat_template.call_args_list:
            self.assertIs(call.kwargs["return_dict"], False)


@unittest.skipUnless(os.environ.get("RSI_TEST_REAL_TOKENIZER") == "1", "opt-in cached tokenizer check")
class RealTokenizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from transformers import AutoTokenizer
        cache = Path(__file__).resolve().parents[1] / ".cache/huggingface/hub"
        cls.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, trust_remote_code=False,
            token=False, cache_dir=str(cache), local_files_only=True,
        )
        cls.prompt = "Write a Python function add(a, b) returning their sum. Return only Python code."

    def test_prompt_is_flat_int_list_not_batch_encoding(self):
        tokenizer = self.tokenizer
        messages = [{"role": "user", "content": self.prompt}]
        default = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
        )
        ids = _prompt_ids(tokenizer, self.prompt)
        self.assertIsInstance(ids, list)
        self.assertTrue(ids)
        self.assertTrue(all(type(token) is int for token in ids))
        self.assertEqual(ids, default["input_ids"])
        self.assertTrue(tokenizer.decode(ids).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n"))

    def test_real_completion_prefix_and_loss_mask(self):
        for completion in (
            "def add(a, b):\n    return a + b",
            "\ndef add(a, b):\n    return a + b",
            "```python\ndef add(a, b):\n    return a + b\n```",
            "def greeting():\n    return 'नमस्ते 🌍'",
        ):
            with self.subTest(completion=completion):
                prefix = _prompt_ids(self.tokenizer, self.prompt)
                row = _encode_example(self.tokenizer, {"prompt": self.prompt, "completion": completion}, 1536)
                self.assertTrue(all(type(token) is int for token in row["input_ids"]))
                self.assertEqual(row["input_ids"][:len(prefix)], prefix)
                self.assertEqual(row["labels"][:len(prefix)], [-100] * len(prefix))
                target = row["input_ids"][len(prefix):]
                self.assertEqual(row["labels"][len(prefix):], target)
                self.assertEqual(self.tokenizer.decode(target), completion.lstrip("\n") + "<|im_end|>\n")

    def test_real_oversized_example_is_rejected(self):
        example = {"prompt": self.prompt, "completion": "def add(a, b):\n    return a + b"}
        length = len(_encode_example(self.tokenizer, example, 1536)["input_ids"])
        with self.assertRaisesRegex(ValueError, "exceeds max_length"):
            _encode_example(self.tokenizer, example, length - 1)


if __name__ == "__main__":
    unittest.main()
