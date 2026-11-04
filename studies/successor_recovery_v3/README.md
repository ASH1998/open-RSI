# Successor recovery v3: runtime-only cache setup

Authorized November 5, 2026. This is a new versioned study, preserving the failed
`successor-v1-calibrate` report and its $5 reservation. The two startup failures retain $9 of the $25 recovery allocation. This version
allows a $1 CPU probe and five $3 stages ($16 total) within the unchanged $250 project cap and $25 overhead.
Only the main project chat starts paid work. No automatic retries or promotion.

The recovery replays all 24 saved original/probe audits locally and applies only
the independently reviewed task category correction. It binds old and derived
task hashes without rewriting historical reviews. The first 20 tasks retain the
frozen order and contain nine collections, eight numeric and three text tasks.
Reference tests and outputs, prompts and executable content remain unchanged.
The final-test parquet is checksum-only; no final prompts are decoded.

1. Baseline: fresh base-model evaluation on the existing 32 development and 16
   retention tasks. These have prior exposure and are not fresh held-out tests.
   Freeze the actual GPU/package runtime before teacher generation.
2. Original teacher: two attempts on 20 fresh native-training tasks, greedy
   seed 42 and sampled seed 31415/temperature 0.7, each 512 new/2,048 input tokens.
3. Learned experimental teacher: the identical tasks and settings, using the
   unpromoted verified-SFT adapter with byte-hash verification.
4. Original-teacher child, only if both teachers yield at least 16 unique verified
   targets, at least three categories, no category above 60%, and different data.
5. Learned-teacher child under the same gate. Both students start fresh from the
   same base, seed 42, 16 optimizer steps, accumulation four, LoRA rank eight,
   learning rate 0.00002 and maximum sequence length 2,048.

Preserve all attempts, including failures. Teacher yield is not evidence of
successor improvement. A promising child needs at least three development gains
against both the other child and starting student, with no individual retention
success lost against either. Even then, retain the parent and report preliminary
development evidence only; repeated generations and replication are future work.

Commands from the SSD checkout:

```sh
.venv/bin/python -m rsi.successor_recovery_v3 prepare
.venv/bin/python -m rsi.successor_recovery_v3 worker-probe
.venv/bin/python -m rsi.successor_recovery_v3 baseline
.venv/bin/python -m rsi.successor_recovery_v3 teacher-original
.venv/bin/python -m rsi.successor_recovery_v3 teacher-learned
# Only after inspecting the paired feasibility gate:
.venv/bin/python -m rsi.successor_recovery_v3 child-original
.venv/bin/python -m rsi.successor_recovery_v3 child-learned
.venv/bin/python -m rsi.successor_recovery_v3 report
```

Never rerun a paid stage already attempted. Inspect saved reports and the ledger
first. The source/config/reuse plan is frozen before baseline; the full task and
actual runtime protocol is frozen before either teacher. Static protocol and
category checks run before baseline reservation. W&B input artifacts are explicit
allowlists and link the original calibration and teacher checkpoint reports.

Reusable category preflight and reference-reuse APIs ship in rsilab 0.4.2.
Historical 0.3.0 source remains in Git and its immutable wheel. Existing frozen
controllers and replay-critical evaluator/data modules remain unchanged.

Image construction must not set any volume cache environment variables. Worker
entrypoints create caches and set environment variables only after the mounted
volume is available. Before any GPU call, a separate CPU-only function on the
same image, volume and source bundle verifies startup, source imports and package
distribution inventory. Its $1 reservation remains counted whether it succeeds or fails.
GPU stages require that completed probe and compare their package inventories
with it. No ML-runtime imports, model downloads, model loading or candidate execution occur in the
probe. A failed probe stops dependent work.

The family budget sums every ledger reservation whose stage starts `successor-r`,
including failed r1 ($5) and r2 ($4), and never exceeds $25. This version allows
at most $16: $1 plus five $3 stages. Two maximum-duration GPU function calls cost
about $2.17 at the frozen compute rates; cold startup, builds and storage retain
the existing project overhead allocation. These are planning bounds, not invoices.
