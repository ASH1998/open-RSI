# Successor recovery v2: image setup correction

Authorized November 5, 2026. This is a new versioned study, preserving the failed
`successor-v1-calibrate` report and its $5 reservation. The first recovery baseline failed before model execution because image-build
package caches populated the future volume mount. Its $5 reservation remains.
This version permits at most $20 in five new $4 stages; all recovery versions
together remain capped at $25 within the unchanged $250 project cap and $25 overhead.
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
.venv/bin/python -m rsi.successor_recovery_v2 prepare
.venv/bin/python -m rsi.successor_recovery_v2 baseline
.venv/bin/python -m rsi.successor_recovery_v2 teacher-original
.venv/bin/python -m rsi.successor_recovery_v2 teacher-learned
# Only after inspecting the paired feasibility gate:
.venv/bin/python -m rsi.successor_recovery_v2 child-original
.venv/bin/python -m rsi.successor_recovery_v2 child-learned
.venv/bin/python -m rsi.successor_recovery_v2 report
```

Never rerun a paid stage already attempted. Inspect saved reports and the ledger
first. The source/config/reuse plan is frozen before baseline; the full task and
actual runtime protocol is frozen before either teacher. Static protocol and
category checks run before baseline reservation. W&B input artifacts are explicit
allowlists and link the original calibration and teacher checkpoint reports.

Reusable category preflight and reference-reuse APIs ship in rsilab 0.4.1.
Historical 0.3.0 source remains in Git and its immutable wheel. Existing frozen
controllers and replay-critical evaluator/data modules remain unchanged.

The new portable factory installs dependencies before assigning runtime cache
paths under `/artifacts`. This prevents the image build from populating the
volume mount. The old factory and failed reports remain unchanged. Each stage
allows at most two GPU calls. At frozen rates, two 1,800-second calls with two
CPU cores and 16 GiB RAM cost about $2.17 before startup; $4 is reserved per
stage and the project retains its separate $25 overhead hold. This is a planning
bound, not billing. No model outputs were observed in the failed startup, and
no tasks, test cases, inference settings or acceptance gates changed.

Outcome: v2 baseline `20261104T190729Z-successor-r2-baseline-62d0e308` also stopped before any model outputs. Its cloud logs show the dependency build succeeded but the later ENV image layer still resulted in a nonempty volume mount. Preserve its $4 reservation and frozen source; do not rerun v2. V3 moves all runtime cache environment setup inside the worker after mount and requires a CPU-only probe before GPU work.
