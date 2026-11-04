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

### Evaluator v2 and failure audit (authorized November 4)

The user authorized failure analysis, an evaluator fix, and rescoring every saved model before any further training. The original v1 study, tasks, generations, checkpoints and scores remain immutable. Main owns a new rescore controller, protocol, budget, execution, tracking and integration. The existing dataset chat owns `docs/MBPP_FAILURE_ANALYSIS.md` and optional `scripts/analyze_mbpp_failures.py`; the verifier chat owns new `rsi/mbpp_verification_v2.py`, its tests and `docs/VERIFIER_V2.md`; the framework chat owns new `rsilab/rescore.py`, its tests and `docs/RESCORING.md`. Each chat has disjoint files, and only main may launch paid work.

Scope: re-execute saved parent (176), both adapters (80 each), and separate Kaggle (32) outputs with the same versioned evaluator. Preserve truncation failures and every original record. No new model generation, label selection, parameter updates or training. Plan at most four $5 CPU verification stages ($20 total), with reference compatibility checks inside the first stage. Post-hoc evaluator corrections are explicitly labeled; they cannot turn this study into a prospective improvement claim.

The v2 protocol and code were frozen in commit `27c8f92` and pushed successfully to GitHub, including the previously pending MBPP commits. All 199 integrated tests passed. Independent controller review found no launch blocker. Main reserved the first $5 CPU stage: all 18 remote positive/negative calibrations and all 176 reference solutions passed before saved parent outputs were executed. Original generated answers and source assertions remain unchanged.

The framework chat built/installed local `rsilab 0.1.1`; its isolated imports and 11 audit tests passed, with old wheel and frozen code preserved. The wheel checksum is `3b72462b4b0a33101101831a9a2dec38ba335ca4bc97f6f44283719958af66ba`. No PyPI release or GPU work was performed.

The completed v2 correction accounts for all 368 outcomes. Exactly four failures became passes: parent and Kaggle task 568, and both adapters task 512. Development scores are parent 18/48, seed 42 17/48, seed 43 16/48; separate Kaggle 9/32. Retention remains parent 13/32 versus both adapters 12/32, and all 46 training targets remain eligible. Original parent retained; no generation or training.

Seed 43 aborted at the infrastructure/invalid-task guard after saving 77/80 rows. The exact exception detail was not persisted by the frozen controller. Main preserved the failed report/artifact v0 and failed $5 reservation, froze an explicit recovery protocol, and reserved a separate $5 stage to execute only tasks 648, 582 and 557. The verifier chat independently checked all original 77 rows stayed unchanged and the three new scores reproduce from saved typed outputs. The correction therefore reserved $25 total, not the initial $20 plan. Project reservations are $150 + $25 overhead, leaving $75 within the unchanged $250 cap. All five correction apps stopped with zero tasks. The aggregate retains its historical $145 snapshot; completion metadata records the current $150 total.

Consolidated W&B run `gyzdo33g` finished. Remote readback matched all four grouped reports, the recovery report, preserved failed v0 report, aggregate summary, completion metadata and recovery protocol; all five expected original-study/stage dependencies are present. Read-only billing reconciliation is in `budget/reconciliation-mbpp-v2-2026-11-04.json`; provisional workspace metering is not a finalized project invoice. Full report: `docs/MBPP_RESCORE_V2.md`; compact tracked evidence: `studies/mbpp_rescore_v2/results.json`.

Next executable milestone: make a new controller version that saves infrastructure diagnostics before raising and harvests finished futures on abort, then preregister stronger test coverage before any new training. Keep this study's frozen source, original failures and corrected outcomes unchanged. Current evidence establishes an evaluator correction and adapter regressions, not recursive self-improvement.
