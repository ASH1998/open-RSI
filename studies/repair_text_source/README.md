# APPS text contingency

Eight native APPS training tasks are ready for main to review for a separately frozen study. The MBPP-only cohort has 19 training tasks and eight evaluation tasks. Adding these eight in memory produced 27 training tasks, comprising 11 collections, six numeric and ten text tasks. The eight native MBPP evaluation tasks cover numeric and collections only. This combination could measure training-label yield on text, but its fresh evaluation block cannot measure transfer to text. Main owns the cohort decision and paid launch.

## Source and attribution

The APPS file is Hugging Face `codeparrot/apps` at revision `21e74ddf8de1a21436da12e3e653065c5213e9d1`. The train object is 107,101,272 bytes. Hub metadata identifies its LFS SHA-256 as `45e82ef22ed8e7c0c04d881a21b923e9dd233157896b0b8d5b3493e887499cae`. Bounded public HTTPS requests located the selected rows. A second retrieval requested only their precise ranges, totaling 42,126 bytes. Each response returned HTTP 206 with the expected Content-Range and matched the local SHA-256 of that complete JSONL row, including its LF. The whole-object hash comes from Hub metadata. The [slice inventory](slice.json) gives inclusive byte offsets, row hashes, titles, authors, creation dates and original URLs. The parsed source row has its own canonical JSON digest. The APPS test file was never requested.

APPS was introduced by Dan Hendrycks and colleagues, *Measuring Coding Challenge Competence With APPS*, NeurIPS 2021. The pinned dataset card declares MIT and describes collecting tasks from external programming sites. All eight chosen rows originate from Codewars. Its terms identify contributed Kata Data under the FreeBSD 2-Clause license, with author and year notices. Keep those notices and terms with any permitted redistribution. Individual submitted solutions may have other contributors. Only the ignored raw SSD rows contain those solutions, retained for their byte hashes. No loader, model, or downloaded solution code ran. [APPS paper](https://arxiv.org/abs/2105.09938) · [Pinned dataset card](https://huggingface.co/datasets/codeparrot/apps/blob/21e74ddf8de1a21436da12e3e653065c5213e9d1/README.md) · [Codewars terms, sections 5–6](https://www.codewars.com/about/terms-of-service).

## Calibration and overlap

Every row has native call-based I/O. The adapter retains the starter function's name and argument order. Each input is the argument vector. Each output is a singleton envelope around the return value. Unwrapping once preserves list returns for 3080 and booleans for 4211. The compiled source contains every original case in native order. Reviewed prompts use explicit ASCII domains where punctuation or case behavior could otherwise be ambiguous. Four new cases per task were specified independently of downloaded solutions. A separate hand-written oracle was run on every input and its tagged output was checked against the native or reviewer-specified expectation. The production scorer passed all 52 native cases and 32 added boundaries. A control substituting integer one for a true boolean failed the reviewed boundary.

| APPS train ID | Original author | Call | Native cases | New boundaries |
| --- | --- | --- | ---: | ---: |
| [3038](https://www.codewars.com/kata/5dd5128f16eced000e4c42ba) | KenKamau, 2019 | `solve(st)` | 10 | 4 |
| [3041](https://www.codewars.com/kata/5a02e9c19f8e2dbd50000167) | boxer, 2017 | `vowel_start(st)` | 5 | 4 |
| [3052](https://www.codewars.com/kata/57faefc42b531482d5000123) | myjinxin2015, 2016 | `remove(s)` | 6 | 4 |
| [3080](https://www.codewars.com/kata/58bf9bd943fadb2a980000a7) | mamafrantz, 2017 | `who_is_paying(name)` | 6 | 4 |
| [4189](https://www.codewars.com/kata/5840586b5225616069000001) | ArtOfCode, 2016 | `highest_value(a, b)` | 4 | 4 |
| [4194](https://www.codewars.com/kata/56c0ca8c6d88fdb61b00005d) | AzariasB, 2016 | `next_version(version)` | 5 | 4 |
| [4211](https://www.codewars.com/kata/56786a687e9a88d1cf00005d) | Shivo, 2015 | `validate_word(word)` | 10 | 4 |
| [4256](https://www.codewars.com/kata/5ad1e412cc2be1dbfb000016) | MicheleCarbone, 2018 | `insert_missing_letters(st)` | 6 | 4 |

The [semantic review](overlap.md) records nearest MBPP operations and omitted candidates. The 284 exposures and all 464 train/validation MBPP descriptions were screened. A separate check against the actual 19+8 MBPP cohort found no shared leak key or family. I rebuilt the example combined train manifest from both aligned source/review sets and rescored all eight APPS output records against it. The compatibility receipt binds both inventories and the resulting example order. Finite cases and manual semantic review leave room for erroneous programs or unrecognized paraphrases. Pretraining contamination and generalization are unmeasured. [Compatibility receipt](compatibility.json)

## Offline replay

From the SSD project root, use `.venv/bin/python -B -m studies.repair_text_source.prepare`. On a fresh SSD workspace with the pinned MBPP train/validation files and exposure registry, add `--fetch` to retrieve only missing APPS rows. The script verifies all existing artifacts before writing missing outputs under `data/repair-text-source/`. It fails on differing saved artifacts. The APPS manifest seal is `1582afe626224f80522064a5ef08af2167c8d305089418780a44a9fb57a087ff`. The canonical JSON digest of the validation receipt is `64bf3b54f59d261b902bc10d5a4480a89d64091fbbc00ad642de9d3d38bb607e`.

| Local artifact | Purpose |
| --- | --- |
| `train-sources.json`, `train-reviews.json` | Ordered inputs to `apply_task_contracts`; private to study preparation. |
| `train-manifest.json` | Replayed contracts, cases, lineage and generation-only `prompts` projection. |
| `reference-outputs.json` | Rows with `id`, `reference_sha256` and typed `outputs` in original-then-boundary order. |
| `validation.json` | Per-task identity, pass counts, oracle digests, code/data pins and manifest seal. |

Each reference digest hashes the UTF-8 function definition returned by `inspect.getsource` for the named function in `oracles.py`, including its trailing newline. The receipt separately binds the whole oracle module with its standard-library imports. No APPS solution was used as an oracle or a label. Main's next executable step is to replay the receipt and decide on the source mix and evaluation limitations before freezing a new study. This work used local CPU and public read-only HTTPS. It made no reservations or paid launches.
