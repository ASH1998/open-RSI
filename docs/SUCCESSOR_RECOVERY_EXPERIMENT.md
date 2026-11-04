# Successor recovery: completed paired teacher probe

Completed November 5, 2026 (Asia/Kolkata). The learned teacher produced **9/20**
unique verified targets versus **10/20** for the original teacher. Both failed
the frozen data gate; no children were trained and the original parent remains
selected. This small cohort shows no improvement in teaching-data yield. It does
not measure child performance or demonstrate sustained RSI.

| Measure | Original teacher | Learned teacher |
| --- | ---: | ---: |
| Greedy passes | 9/20 | 9/20 |
| Independent sampled passes | 7/20 | 6/20 |
| Unique verified targets | 10/20 | 9/20 |
| Collections / numeric / text | 4 / 6 / 0 | 4 / 5 / 0 |
| Child training gate | Failed | Failed |

Eight tasks pass in both arms; learned-only success is 610, original-only
successes are 633 and 789. Both miss the minimum 16 targets and three categories;
both meet the maximum 60% category-share condition. All 80 attempts are preserved.
The fresh starting model scored **11/32 development and 8/16 retention**, with
all 48 completions, typed outputs and outcomes exactly matching the historical
parent baseline. These evaluation sets have prior exposure.

The learned teacher uses the unpromoted earlier SFT adapter, not a newly trained
model. Its byte SHA is `6c5d5f5df6701757a2e34cdfa229921fa03f27610b745c18b7ce8c222d55c772`.
Its previous development gain came with a retention regression.

The study uses 20 strictly never-generated native-training tasks, selected in
the original frozen order after replaying 24 original/probe reference audits.
A category-only correction produces nine collections, eight numeric and three
text tasks without changing their prompts or tests. All 261 accepted additional
reference cases remain preserved across the 24-task pool. Raw source evidence
and derived task hashes are explicitly linked by the reusable library API.

Plan SHA: `e04df37d5b23a30c4fb5f88821a5cd0ae6440fa070e893b49a65c7c7d7b80b26`.
Measured protocol SHA:
`0cba1d12bb4f06c051566ac9e9d58923d1ad108475a34f6b04aa4cb3aa0060ba`.
[Protocol and commands](../studies/successor_recovery_v3/README.md).

## Deployment findings and preservation

Two startup failures produced no model outputs. V1 configured volume cache paths
before dependency installation; v2 moved them afterward, but the ENV image layer
still produced a nonempty `/artifacts` mount. Both reports and $9 in reservations
remain preserved. V3 configures these paths only inside workers after mount.

A mandatory CPU-only diagnostic on the identical image, volume and source bundle
succeeded: mounted directory present, source inventory matched, and 71 installed
distributions recorded. It requested no GPU and inspected metadata only. The
subsequent GPU baseline and both teachers successfully generated and verified
all 128 outputs in isolated sandboxes. Their inventories matched all 71 CPU
probe packages. These results validate this deployed inference path; checkpoint resume
and portable training have not yet been exercised in this study.

## Public library

The current Apache-2.0 library is `rsilab 0.4.2`. It includes explicit category
preflight, immutable reference-evidence reuse, successor audits, durable provider
calls and a portable Modal factory with the CPU diagnostic. Code is available
from GitHub; no PyPI publication is claimed.

Validation: 436 unique integrated tests covered (433 default passes and three
separately enabled real-tokenizer checks), 155 isolated installed-wheel tests,
offline examples, real SDK definitions and actual saved-reference replay.
[Hosted CI](https://github.com/ASH1998/open-RSI/actions/runs/41895485530) passed on
Python 3.11 and 3.13.

The immutable wheel is
`work/successor-recovery-v3-framework-dist/rsilab-0.4.2-py3-none-any.whl`, SHA-256
`b15bf2c7afd369e9eb4392e44c40605706359628a4afec7dfd2c7f14a54bf953`.
Its audit, installed checks and source inventory are saved alongside it. Earlier
wheels, factories, failed reports and experiment controllers remain available.

## Budget contract

The recovery family is capped at $25 including the two failed startups ($9),
the successful CPU diagnostic ($1), and five model stages at $3 each. Both
teachers must meet the 16-target/three-category/60%-maximum-share gate before
any child training. No automatic promotion or further replication is allowed.
The original $250 total Modal cap and $25 overhead hold remain unchanged.
Reservations are allocations, not invoice totals; reconcile provider billing
without treating lagging estimates as refunds of failed reservations.

Actual reservations for this recovery are **$19**: failed startups $9, CPU
probe $1, baseline $3, and each teacher $3. Neither child was reserved or launched.
Cumulative project reservations are **$194 plus $25 overhead, leaving $31
unallocated**. These are conservative allocations, not actual spending.

At 2026-11-04 19:34:36 UTC, the workspace month-to-date billing snapshot showed
$2.62101049 metered and $0 billed after credits. The project-filtered report had
no rows; this lagging workspace snapshot is not a finalized project invoice and
does not release reservations. All seven listed successor apps were stopped
with zero tasks. See [tracked reconciliation](../studies/successor_recovery_v3/reconciliation.json).

## Evidence and validation

Independent review reproduced every teacher outcome, raw-call identity, adapter
hash, inference control, source identity and package inventory. The installed
0.4.2 library reproduced the final report exactly with networking blocked and
checkout imports excluded. Source/configuration inventories remain frozen.

Stage reports and explicit input artifacts are saved to W&B and downloaded back
for checksum comparison. Completed runs:

- [CPU startup probe](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/s0kj17ws)
- [Starting-model baseline](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/gtg7b413)
- [Original teacher](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/yj8n2c5s)
- [Learned teacher](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/kdo223jx)

Compact results are [tracked in Git](../studies/successor_recovery_v3/results.json).
Full raw reports remain under SSD `runs/`; derived evidence and readbacks are
under `artifacts/successor-recovery-v3/`. The additional combined W&B closure upload is pending specific approval: automatic
approval review rejected its billing/internal-path payload and existing-run update.
The bundle remains on the SSD; individual stage reports already passed W&B readback.

## Limits and next executable milestone

[Detailed failure analysis](SUCCESSOR_RECOVERY_FAILURE_ANALYSIS.md) separates
logic errors, output-contract mismatches and candidate exceptions. For task 675,
both selected solutions differ from the reference at the upper endpoint, but
none of the 13 frozen cases covers that boundary. Passing finite tests is not
proof of correctness; the recorded scores and tests remain unchanged.

Do not retry this completed protocol or relax its gate after seeing outcomes.
The next proposed milestone is an offline, separately versioned task-contract
and boundary-coverage audit, followed by a preregistered data/repair strategy
that can supply text examples and enough diverse verified targets. Include these
20 attempted tasks in the exposure registry before selecting another fresh
cohort. Evaluate resulting students only after the new data gate passes, while
retaining the original parent and untouched final-test evaluation. Portable
training/resume and repeated successor-improvement remain unvalidated. No further
paid job is scheduled by this closure.
