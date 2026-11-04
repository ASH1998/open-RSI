# MBPP dataset preparation

Updated November 4, 2026. Dataset preparation and the main-chat reference audit are complete; 128 train and 48 development tasks are frozen, with 32 train tasks designated for retention checks. Baseline generation remains under main-chat coordination; no MBPP model score or training outcome is claimed here. This study uses the dataset-native split exception documented in `AGENTS.md` and [the MBPP study](../studies/mbpp_v1/README.md). It does not claim family-held-out generalization.

## Source choice and provenance

Use `google-research-datasets/mbpp`, configuration **full**, pinned to Hugging Face revision **`4bb6404fdc6cacfda99d4ac4205087b89d32030c`**. Counts below were checked against the pinned Parquet files and dataset-card metadata. The card's older illustrative snippets combine rows into one split; they are not the current split layout. [Pinned dataset card](https://huggingface.co/datasets/google-research-datasets/mbpp/blob/4bb6404fdc6cacfda99d4ac4205087b89d32030c/README.md)

| Configuration | Train | Validation | Test | Prompt | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| full | 374 | 90 | 500 | 10 | 974 |
| sanitized | 120 | 43 | 257 | 7 | 427 |

Sanitized is a hand-reviewed subset, but cannot provide 128 train/64 dev while preserving source splits. Full is the larger candidate pool and needs explicit unsupported-test exclusions and reference audits. Original tasks contain descriptions, reference solutions, and small test lists; passing those tests is weak evidence of general correctness. [Google Research MBPP source](https://github.com/google-research/google-research/tree/master/mbpp)

The dataset is marked **CC BY 4.0**; Google's repository distinguishes dataset licensing from its Apache-licensed repository source files. Preserve attribution to Google Research and Austin et al., *Program Synthesis with Large Language Models* (2021), and identify filtering/prompt modifications. No dataset contents are added to Git here. [Google Research licensing statement](https://github.com/google-research/google-research/blob/master/README.md)

| Alternative | Fit for this experiment |
| --- | --- |
| [OpenAI HumanEval](https://huggingface.co/datasets/openai/openai_humaneval/blob/main/README.md) | 164 tasks, test split only, MIT metadata. Useful as a separately planned evaluation source, not a native 128/64 train/dev pool. Do not repurpose its test tasks as training labels here. |
| [APPS](https://huggingface.co/datasets/codeparrot/apps/blob/main/README.md) | 5,000 train and 5,000 test problems, MIT metadata, with difficulty labels and input/output data. Offers much greater scale but requires broader function/stdin harness support and a separately designed development split. Defer until the small-model pipeline and verifier are validated. The [authors' repository](https://github.com/hendrycks/apps) links this HF distribution. |

MBPP has been public since its 2021 release. Neither source-split separation nor our deduplication establishes absence from MiniCPM pretraining. Treat contamination as unresolved, and report results as a **filtered MBPP development comparison**, never a standard leaderboard score, an unseen benchmark guarantee, or evidence of recursive improvement. Do not mix full and sanitized configurations as if their overlapping IDs were independent tasks.

## Local artifacts and interface

`rsi/datasets.py` downloads immutable public bytes using ordinary HTTPS without HF credentials, checks hard-coded SHA-256 digests, and reads Parquet as data with PyArrow. It never runs dataset solutions, setup strings, tests, or remote loader scripts. All eight original Parquet files and the source README are preserved in `data/mbpp/raw/`; `source.json` records URLs/checksums/byte counts. Original Parquet retains every raw field, including reference code. The loader verifies checksums again before parsing. `data/` is ignored by Git.

The preparation-only PyArrow 23.0.1 installation is under `data/mbpp/.reader`; its cache and temporary files also remain under `data/mbpp`. It is not a model-worker dependency or a global installation. Run from the project root:

```sh
PYTHONPATH=data/mbpp/.reader .venv/bin/python -m rsi.datasets --config full --seed 42
# Add --download only when public pinned source assets must be fetched.
.venv/bin/python -m unittest discover -s tests -p 'test_datasets.py' -v
```

Python API:

```python
from rsi.datasets import load_mbpp, build_mbpp_pools, select_tasks, model_input

raw = load_mbpp(config="full")
pools = build_mbpp_pools(raw, config="full", seed=42)
# Main controller first converts/tests eligibility and audits references remotely.
# supported_ids must be IDs from this particular split, after those exclusions.
selected = select_tasks(pools, "train", 128, eligible_ids=supported_ids)
public = [model_input(task) for task in selected]
```

`build_mbpp_pools` returns **all eligible rows**, not only the first 128/64. Its train/dev pools are deterministically ranked by SHA-256 of importer version, seed, and task ID; source row order cannot change selection. `select_tasks` preserves that order after an external ID allowlist and raises on insufficient counts or wrong-split IDs. It never borrows test/prompt rows. `model_input` returns only `prompt` and `entry_point`.

Each task carries `id`, `family` (duplicate-cluster identifier, **not an algorithm category**), project `split`, `prompt`, original `entry_point`, and `verification_mode="python_assertions"`. Hidden fields are original `test_list`, `test_setup_code`, `test_imports`, and `challenge_test_list`. Metadata records source ID/split/config/revision, row and task hashes, import policy, license, and review status. The task omits reference code. The controller can obtain that code for remote gold audits only by looking up the raw row using `metadata.source_id`.

Prompts contain the source description and a signature extracted statically from the reference function, with no function body or source tests. Literal defaults are permitted; dynamic defaults, decorators, ambiguous entry points, and unsupported syntax are excluded. Prompts request concise self-contained Python code, required imports, no explanation or long comments. Allowed modules match the coordinated MBPP policy: `math`, `collections`, `itertools`, `functools`, `bisect`, `heapq`, `statistics`, `re`, `string`, `operator`, `array`.

The raw assertion manifest requires conversion; do not pass it directly to the original JSON-case verifier. The completed study audit used static AST conversion and `mbpp-typed-v1` for independently scored typed cases, with explicit unsupported exclusions. Unsupported setup, assertions, imports, or challenge tests must not be silently dropped. Keep converted cases/expected outputs in the trusted controller. Never send full manifests or raw reference rows to a model or candidate-writable sandbox. Remote reference success is a verifier compatibility audit, not an SFT label.

## Duplicate exclusions and reserved domains

Screen all four source splits before selecting candidates. Link rows on normalized description equality, canonical reference-AST equality (renames/literal changes normalized), or description token Jaccard ≥0.70 plus normalized-text similarity ≥0.80. Use connected components, so indirect duplicate chains are handled. Quarantine every train/dev member of a component spanning multiple source splits. Within a single split, keep only its lowest source ID. Duplicate screening reads test/prompt source data statically; neither split enters model prompts, labels, or evaluation sampling.

The keyword quarantine also excludes explicit graph/reachability/traversal and edit-distance/Levenshtein tasks where detected in descriptions or source code, to preserve the earlier pilot's final domains as far as practical. Review selected descriptions before freezing: this is not full semantic sealing. Duplicate thresholds are conservative heuristics, with false positives and false negatives; algorithm categories still overlap between dataset-native train/dev. Do not call cluster counts independent task families or independent statistical replications.

Observed full-pool preparation: **272 train / 68 dev candidates**. Across source train/validation, 107 rows were quarantined for cross-split duplicate components, 16 for within-split duplicates, and one for unsupported signature/test syntax. No additional row was removed by the reserved-domain rule after those exclusions. These counts precede conversion, gold audits, and manual review. `ready_for_training` remains false; required gates are included in the manifest. Each exclusion retains a reason/source ID/cluster ID.

The finalized preparation pool is `data/mbpp/pools-full-seed42.json`, canonical manifest SHA-256 `13907d86dc89f61a1bfb06d691415984b6efd0304d5b321b914d787d8873b49f`. This is a hash of the canonical JSON payload excluding its own hash field, not the pretty-printed file bytes. The earlier seven-import/prompt draft is retained as `pools-full-seed42-initial-candidate.json`; do not use it for new generation.

## Completed audit and frozen subset

The [completed reference audit](../runs/20261104T094331Z-mbpp-reference-audit-32abb6/report.json) records a passing verifier preflight and 334 reference checks using `mbpp-typed-v1`. These are source-reference checks, **not model-generation accuracy**.

| Preparation stage | Train | Development |
| --- | ---: | ---: |
| Importer candidates | 272 | 68 |
| Convertible candidates audited | 269 | 65 |
| References passing audit | 258 | 64 |
| Passing candidates after manual duplicate exclusions | 256 | 62 |
| Frozen study tasks | 128 | 48 |

Six conversion exclusions (three per split) cover unsupported literal calls, setup/imports, nonliteral values, or mismatched entry points. Twelve further reference checks failed: eleven candidate-policy rejections and one task with execution errors. No excluded reference was used to fill the frozen subset. Manual review then quarantined two missed cross-split pairs: abundant-number predicates (`955`/`541`) and even/odd parity filters (`629`/`554`). [Review record](../studies/mbpp_v1/manual-exclusions.json)

The [frozen summary](../studies/mbpp_v1/frozen-manifest-summary.json) lists all 176 selected task IDs and 32 retention IDs. The retention set is the first 32 selected training tasks, not an additional held-out split. Source rows remain train→train and validation→dev; no source test/prompt task was selected. Broad category counts are train: text 21, collections 70, numeric 30, other 7; dev: text 7, collections 27, numeric 11, other 3. These are task counts, not verified model-label yield.

The full converted manifest is `data/mbpp/study-v1.json`, hash `cde70ffcd2bc5e243587a0c32f4f084457ac446a67c00adbd3522303ec3029ca`. Its frozen analysis-plan hash is `afac675cae3c23e83ceef4bffdc274aa6a9e0d26c37c0899c3b2cdf10322c59c`. Both agree with the public frozen summary. Preserve these artifacts and the importer/prompts during baseline collection.

## Frozen study protocol

Main chat froze [the prospective protocol](../studies/mbpp_v1/protocol.json) before model generation: audit candidates, then select the first **128 train / 48 dev tasks** in importer order after exclusions and preselect 32 training-retention tasks. Those counts and IDs are now frozen as recorded above. The importer and prompts remain unchanged; this documentation review makes no code, data, or protocol changes.

Preserve the original base checkpoint and its baseline outputs. Predeclare one generation/repair policy, output cap, seed, precision, and hardware class; apply identical inference budgets to base and adapter. Missing imports, truncation, and wrong outputs remain failures. A changed prompt or cap requires a fresh matched base baseline, not selective repairs to previously scored outputs. Kaggle experiments may use the same frozen artifacts but remain a separate hardware/precision stratum unless matched comparability is demonstrated.

The frozen SFT gate is **at least 32 unique verified targets across at least three descriptive categories, with no category above 60%**. Main chat uses broad text/collections/numeric/other reporting categories; these do not establish semantic family independence. This supersedes the earlier advisory four-category/40% suggestion. Deduplicate exact completion text; labels are model completions only. Repetition does not increase diversity. If yield misses the gate, stop and report yield/failure categories; do not substitute references or validation answers. The protocol specifies two fresh adapters with seeds 42/43, learning rate 2e-5, and approximately two epochs under its 64-step cap.

Use development only for the frozen decisions; do not call it sealed final evidence. The protocol marks a result replication-worthy only if both seeds gain at least four net development successes, each loses at most one parent retention success, and no integrity mismatch remains. No automatic promotion follows. Keep MBPP test/prompt splits and the pilot final families unused in this experiment. Measuring a better improver requires the separate fixed-improvee experiment described in the user's design reference; its $500 plan does not override the project's $250 Modal cap, reservations, or main-chat launch coordination.

## Remaining limitations and handoff

Sparse source tests and passing references do not establish arbitrary-input correctness. Automated and manual duplicate review cannot prove semantic separation or preserve every related pilot-final task; dataset-native splits share broad categories. Pretraining contamination is unresolved. Filtering selects a supported subset rather than the standard MBPP benchmark. Retention is a training diagnostic; two adapter seeds share one generated dataset and do not provide independent dataset replication. Task-solving gains would not establish better successor-improvement ability.

Earlier preparation changed `rsi/datasets.py`, `tests/test_datasets.py`, this document, and ignored `data/mbpp/` assets; its 13 local tests passed. This follow-up changed **only this document**, checking saved audit records, selected counts/categories/retention IDs, and frozen manifest/protocol hashes. No dataset code was executed locally, credentials read, jobs launched, or Git commit/push performed by this chat. The main-chat remote reference audit is complete. Model-label yield, training eligibility, baseline/adapter outcomes, and statistical interpretation remain pending main-chat results. Next milestone: complete the frozen base collection, apply the predeclared label-diversity gate, and retain the base if that gate fails.
