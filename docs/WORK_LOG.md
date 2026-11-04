# Work log and chat assignments

## November 4, 2026

The user authorized a **$250 total Modal budget** and asked to begin implementation. They subsequently requested visible parallel project chats instead of transient sub-agents so the work remains in the sidebar.

All chats share `/Volumes/DevSSDWD/openbmb/rsi`. Initial sub-agent drafts were saved and handed off without paid calls. The main chat owns integration, budget accounting, Git backup, and every paid launch.

| Visible chat | Chat ID | Owned files |
| --- | --- | --- |
| RSI — Modal GPU worker | `01a1a552-f621-7bb3-8195-e42427521abc` | `rsi/modal_workers.py`, `requirements-gpu.txt`, `docs/GPU_WORKER.md` |
| RSI — task suite and evaluation | `01a1a551-f0b9-7ff2-9861-215c53bf3689` | `rsi/tasks.py`, `tests/test_tasks.py`, `docs/TASKS.md` |
| RSI — sandbox verifier | `01a1a551-b053-74a2-9f37-28e18d9b5de1` | `rsi/verification.py`, `tests/test_verification.py`, `docs/VERIFIER.md` |

Initial task suite: 13 local tests passed before handoff. Initial worker and verifier drafts require review. No model results exist at this checkpoint.

The first target is a budgeted model-load smoke test, followed by a small verified-data training cycle. Task results on this tiny suite are pilot evidence only; final-test families remain reserved until a protocol is frozen.

All three visible reviews completed. The integrated local suite passed 46 tests. First Modal image build succeeded; its L4 function remained queued for capacity. Main chat stopped that app and selected A10 for the next attempt. The original reservation is retained conservatively.

The A10 loaded the model but exposed a Transformers 5 tokenizer return-type mismatch. The GPU chat fixed both inference and training encoding with explicit `return_dict=False`, adding `tests/test_tokenizer.py` to its scope. Main reran all 51 tests, including cached real-tokenizer checks; all passed. Both failed attempts retain their $5 reservations. A third bounded smoke attempt is underway.

The corrected smoke passed. The baseline completed with 4/16 training and 7/8 development tasks passed. Only the four verified masked-mean training outputs were used in one 20-step QLoRA compatibility run, which completed and saved adapter/optimizer/RNG state. W&B readback confirmed all 20 loss points and the report artifact. Main exported the adapter/latest checkpoint to the SSD and verified all payload checksums.

The GPU chat then fixed adapter containment checks after a CPU diagnostic confirmed Modal's mount is a symlink. It added seven tests in `tests/test_worker_paths.py`; all 60 integrated tests passed. Evaluation is retrying with the existing adapter, without retraining. Main owns the two comparison-integrity tests in `tests/test_pilot.py`. The task/evaluation chat drafted `docs/NEXT_EVALUATION.md`, a prospective redesign addressing single-family training yield and the near-ceiling development suite. See `docs/EXPERIMENTS.md` for measured evidence and remaining validation limits.

The corrected evaluation completed: training families 4/16 → 6/16, development families 7/8 → 5/8. Two sequence-padding gains were offset by two grouped-reduction regressions; the original parent is retained. No final-test tasks or further training runs were used. The ledger reserves $45 for nine attempts and $25 overhead, leaving $180 in planning headroom; actual invoices are unconfirmed. The completed cycle and next experiment proposal are recorded for handoff; there is no automatic repeat loop.

### MBPP v1 and framework follow-up

Main froze and locally committed (`cb2babe`) a 128-train/48-development MBPP study after independent reference execution, automatic duplicate filtering, and manual review. The proposal supplied by the user is retained under `docs/design/`; its larger budget and hardware assumptions are not adopted. All paid launches remain main-chat-only, with a $100 reservation ceiling for this study inside the $250 project cap.

Parallel assignments for this study: the GPU chat owns `rsilab/**`, framework tests, `pyproject.toml`, and `docs/FRAMEWORK.md`; the dataset chat owns importer/tests and `docs/DATASETS.md`; the verifier chat owns typed MBPP verification/tests and `docs/VERIFIER.md`. Main owns `rsi/study.py`, Kaggle/backend orchestration, budget integration, protocol and final experiment reporting. Source and protocol were frozen before generation; subsequent parallel tasks are read-only reviews or documentation within those scopes. The integrated prelaunch suite passed 138 tests, including the cached real tokenizer.

The private Kaggle kernel `ashutoshmishra1998/open-rsi-mbpp-baseline-v1` completed 32 development generations on an actual Tesla T4 (requested NvidiaL4). Results were downloaded to SSD and submitted to the same isolated Modal verifier. This is a separate provider benchmark, not the matched L40S comparison.

A conversation interruption stopped the baseline batch-0 local controller after GPU work. Main recovered the completed original Modal function result (`fc-01M6JZHWTQC0FKSXAPY3Y4VNQP`) and resumed verification under its existing reservation and W&B run; no regeneration was launched. Batch 1 completed at 9/32 train tasks passed; remaining baseline batches continue with at most two GPU jobs in flight. Initial Git pushes reported public-key errors. A subsequent direct SSH check authenticated successfully and a push reached GitHub but failed with Internal Server Error. GitHub Status confirmed an active Git Operations incident beginning 09:49 UTC on November 4; no key replacement or credential/configuration change was made. Local commits remain preserved pending service recovery.

All six Modal baseline batches completed: train 46/128 (35.94%), development 17/48 (35.42%), with three token-limit failures and no infrastructure failures. The 46 verified training targets are unique and span collections 25, text 11, numeric 9, other 1; maximum share 54.35%, so the preregistered gate passes. Both fresh adapters (seeds 42/43) completed 23 optimizer steps on 2,725 supervised tokens. Adapter and optimizer/RNG checkpoint exports reached SSD and all checkpoint payload hashes matched. Paired evaluations run two GPU batches at a time. The dataset chat independently confirmed all six baseline task/source/model/hardware/package identities and selected-label lineage.

Final MBPP outcome: parent development 17/48; seed 42 16/48 (3 wins, 4 losses); seed 43 15/48 (2 wins, 4 losses). Both retain 12/32 versus parent 13/32 (0 wins, 1 loss). Strict framework checks match controls for both arms; original parent retained, neither seed meets the replication gate. All 145 integrated tests and 23 isolated installed-wheel checks passed. The latest wheel SHA256 is `985a5a2a7b27874057a62ae862b1ebc306148cd373a26a30cd2c523538593551`. All Modal project apps stopped with zero tasks and Kaggle completed. Cumulative reservations: $125 jobs + $25 overhead; $100 remains. Provider workspace metered usage snapshot: $1.50054595, covered by credits, subject to billing lag; no refunds. Next milestone is offline failure/verifier analysis and a newly frozen protocol, not an automatic training repeat. Full handoff: `docs/MBPP_EXPERIMENT.md`.

Final W&B readback found that the conversation interruption had also stopped baseline batch 1's report upload, although its local compute/verification report was complete. Main resumed the original tracking run `2dscs4sc`, uploaded the unchanged report, restored its completed status and metrics, and resumed the same aggregate run. No generation, verification or training was repeated. The dataset chat independently checked final paired outcomes against all raw reports and confirmed the retain-parent decision. Credential scanning passed for 66 tracked/candidate source and documentation files; `.env` remains ignored.
