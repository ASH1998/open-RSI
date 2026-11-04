# Successor probe v1: stopped at data preflight

On November 5, 2026 local time, the first stage stopped before model generation.
This is an engineering failure with preserved reference evidence, not a model
performance result. No teacher attempts or child training ran. The original
parent remains selected; sustained RSI has not been demonstrated.

The frozen plan was committed in `1dc5271f4a737d58e65873fbfea4b2a868e7ca47`.
Its calibration run is `20261104T183006Z-successor-v1-calibrate-a33b28fc`.
[W&B evidence](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/95x0qgew)
and [compact results](../studies/successor_v1/results.json) preserve the outcome.

## What ran and why it stopped

All 24 original reference programs passed their 72 original cases. Remote
reference probes produced 261 approved additional outputs, all accepted by the
audit. Every task met the reference eligibility rule. This does not prove that
the references implement every aspect of their natural-language specifications.

The review inventory had two category fields: a reviewed outer category and a
nested task category. The reviewed pool covered collections, numeric and text,
but every serialized nested task was labelled `text`. Preparation checked hashes
and split identities without checking these two category fields agreed. The
controller used the nested field and correctly stopped when its first 20 tasks
failed the required three-category gate. The error was not a provider startup
failure. GPU call count was zero.

The original plan, inputs, code and failed report remain unchanged. No labels,
thresholds or outcomes were rewritten to turn this attempt into a success. The
frozen controller deliberately disallows retry. A category correction must use
new, explicitly versioned inputs and a new protocol; reference evidence can only
be reused after proving the executed code, cases and evaluator identities agree.

## Library and verification

The repository now includes Apache-2.0 `LICENSE` and `NOTICE`, an installation
quickstart, a dependency-free example, optional provider dependencies, a portable
Modal worker factory and reusable successor-comparison audits. The immutable
0.3.0 wheel is at `work/successor-framework-dist/rsilab-0.3.0-py3-none-any.whl`,
SHA-256 `1ec7dcca910e023b405e3f3367866af8732b1de12e1baa20235bada388c92952`.
Its audit is saved alongside it. Validation covered 342 unique integrated tests
(including the separately enabled real-tokenizer checks), plus 49 isolated
installed-wheel tests. The offline example and lazy factory construction also
passed. [GitHub CI](https://github.com/ASH1998/open-RSI/actions/runs/41887767083)
passed the package workflow on Python 3.11 and 3.13.

The source is public on GitHub; no PyPI release has been published. The portable
factory entered a real Modal app lifecycle, but its GPU inference and training
functions were never called. Remote portable training, inference and checkpoint
resume therefore remain unvalidated. Historical worker results and offline
parity tests do not establish that validation.

An additive preflight helper is implemented as an unreleased source follow-up
to reject category mismatches and inadequate prefix diversity before any budget
reservation. Its 12 tests pass, including isolated checks with networking blocked.
It is separate from the immutable tested 0.3.0 wheel. The command
`python -m scripts.check_successor_categories` reproduces the actual failure
offline and verifies that the proposed categories restore nine collections,
eight numeric and three text tasks in the unchanged first-20 order. It changes
no saved task, test, reference, report or protocol. See [the API](PREFLIGHT.md).

## Cost and durable evidence

This attempt retained its $5 reservation. Cumulative job reservations are $175,
with $25 held for overhead and $50 unallocated inside the $250 cap. Reservations
are conservative allocations, not invoices, and failed stages are not refunded
in the ledger based on runtime estimates.

The November 4 18:35 UTC billing snapshot reported workspace month-to-date
metered usage of $2.12085022 and billed usage of $0 after adjustments. This is a
lagging workspace snapshot, not the finalized project invoice. It does not
release reservations. The raw snapshot is under `artifacts/successor-v1/`.

Modal app `ap-nIuraWLp9QImopB8Bd15cw` was observed stopped with zero tasks.
The W&B report was downloaded and its full canonical content matched the SSD
report. Source hashes still match the frozen plan. Raw references, probes,
failures and tracking evidence remain on the SSD and in the run artifact;
credentials and raw datasets are not committed to Git.

## Next executable milestone

The offline category correction proposal and reusable preflight tests are complete.
Next prepare a new versioned protocol that binds corrected categories, proves
which reference evidence can be reused, and preserves the original task order,
thresholds and budget controls. Only that new protocol can authorize another
baseline/teacher comparison. The failed v1 stage must not be rerun.

The research question remains whether learned teachers produce better successors
under matching budgets. Teacher yield alone, a single task-score gain, and the
engineering work reported here are not evidence of sustained RSI.
