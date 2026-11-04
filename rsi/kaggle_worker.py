"""Standalone, credential-free Kaggle generation worker; never executes completions."""
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REQUEST = None  # Replaced with a JSON-only payload by kaggle_backend.prepare_kernel.


def main(request):
    output = Path('/kaggle/working/open-rsi-result.json')
    started = time.monotonic()
    report = {'status': 'initializing', 'request': request, 'outputs': [], 'provider': 'kaggle'}

    def save():
        report['wall_seconds'] = time.monotonic() - started
        output.with_suffix('.tmp').write_text(json.dumps(report, indent=2))
        output.with_suffix('.tmp').replace(output)

    save()
    try:
        os.environ.update(HF_HOME='/kaggle/temp/rsi-hf', PIP_CACHE_DIR='/kaggle/temp/rsi-pip',
                          HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TOKENIZERS_PARALLELISM='false')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet',
                        'transformers==5.22.1', 'accelerate==1.15.0',
                        'bitsandbytes==0.50.2', 'safetensors==0.8.0'], check=True, timeout=600)
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
        if not torch.cuda.is_available():
            raise RuntimeError('Kaggle did not allocate a CUDA accelerator')
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        report.update(gpu_name=torch.cuda.get_device_name(0), dtype=str(dtype),
                      packages={name: importlib.metadata.version(name) for name in
                                ('torch', 'transformers', 'accelerate', 'bitsandbytes', 'safetensors', 'tokenizers')})
        common = dict(revision=request['revision'], trust_remote_code=False, token=False)
        tokenizer = AutoTokenizer.from_pretrained(request['model_id'], **common)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            request['model_id'], **common, dtype=dtype, device_map={'': 0}, attn_implementation='sdpa',
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                                   bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype))
        model.eval()
        report['status'] = 'running'
        save()
        for index, item in enumerate(request['prompts']):
            if time.monotonic() - started > 3000:
                raise TimeoutError('Kaggle generation deadline reached')
            set_seed(request['seed'] + index)
            tokens = tokenizer.apply_chat_template([{'role': 'user', 'content': item['prompt']}],
                        tokenize=True, add_generation_prompt=True, enable_thinking=False, return_dict=False)
            if len(tokens) > 2048:
                raise ValueError('Prompt exceeds 2048 tokens; truncation is disabled')
            ids = torch.tensor([tokens], device='cuda')
            item_start = time.monotonic()
            with torch.inference_mode():
                generated = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                            max_new_tokens=request['max_new_tokens'], do_sample=False,
                            pad_token_id=tokenizer.pad_token_id, max_time=3000-(time.monotonic()-started))
            new = generated[0, len(tokens):].tolist()
            report['outputs'].append({'id': item['id'], 'text': tokenizer.decode(new, skip_special_tokens=True),
                         'input_tokens': len(tokens), 'output_tokens': len(new),
                         'hit_token_limit': len(new) == request['max_new_tokens'],
                         'hit_time_limit': time.monotonic()-started > 3000,
                         'elapsed_seconds': time.monotonic()-item_start})
            save()
            print(json.dumps({'completed': len(report['outputs']), 'total': len(request['prompts']),
                              'task': item['id'], 'output_tokens': len(new)}), flush=True)
        report.update(status='completed', peak_gpu_memory_bytes=torch.cuda.max_memory_allocated())
    except BaseException as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        save()


if __name__ == '__main__':
    if REQUEST is None:
        raise SystemExit('Build this standalone script with kaggle_backend.prepare_kernel first')
    main(REQUEST)
