# Pilot experiment record — November 4, 2026

This record describes measured pilot results, not sustained recursive self-improvement. Full reports are saved on the SSD in `runs/<run-id>/report.json` and uploaded as explicit W&B report artifacts. Source hashes, model revision, package versions, settings, outputs, and verifier results are recorded there.

## Setup and integration

Model: `openbmb/MiniCPM5-2B`, revision `f97400052a43d642bbc6e9975e2397e3ae6a6b52`. Quantization: NF4 double quantization, bfloat16 computation. Hardware: one Modal A10-class GPU. The baseline reported NVIDIA A10G; the candidate evaluation reported NVIDIA A10. Verifier: `python-json-v2`, independent CPU Modal Sandboxes without credentials, network, or project mounts.

Two initial smoke attempts failed: one L4 request had no capacity and was stopped; the first A10 call loaded the model but exposed a Transformers 5 tokenizer return-type mismatch. Both encoding paths were fixed and checked with the actual pinned tokenizer on CPU. All 51 tests then passed; two subsequent comparison-integrity tests also passed.

The corrected smoke completed in 27.35 seconds of controller wall time. It generated an addition function that passed both sandbox cases. Worker execution took 11.21 seconds, including 1.20 seconds for generation; peak allocated GPU memory was 1.98 GiB. These times exclude some provider billing overhead and are not invoice totals.

Run: `20261104T070830Z-smoke-0679af`. [W&B smoke evidence](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/tfcuffg4).

## Frozen baseline

Suite `pilot-v2`, seed 42, four variants per family: 16 train-family tasks and 8 development-family tasks. One greedy attempt per task, 512 new tokens maximum, thinking disabled. Final-test families were not evaluated.

| Split/family | Passed | Total |
| --- | ---: | ---: |
| Train: masked mean | 4 | 4 |
| Train: stable softmax | 0 | 4 |
| Train: gradient clipping | 0 | 4 |
| Train: sequence padding | 0 | 4 |
| **Train overall** | **4** | **16** |
| Development: grouped reduction | 3 | 4 |
| Development: interval union | 4 | 4 |
| **Development overall** | **7** | **8** |

Generation took 239.94 seconds; total worker execution took 255.31 seconds and peak allocated GPU memory was 2.00 GiB. Three responses hit the token limit. Inspected failures include references to `math` without importing it, incorrect algorithms, and truncated commentary-heavy code. No repairs or manual answer changes were applied to the baseline.

The four verified training examples all come from masked mean. Development successes are excluded from training. This narrow dataset is enough to exercise the training implementation but does not support a broad learning claim. The two development families are different tasks from training; the higher development score does not imply generalization caused by learning.

Run: `20261104T070918Z-baseline-14df3d`. [W&B baseline evidence](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/kvfvak05).

## First adapter

A single 20-step rank-8 QLoRA compatibility run completed on the four verified training outputs (550 supervised tokens across the dataset). Completion-only loss, learning rate 0.0001, gradient accumulation 4, seed 42. Worker execution took 76.21 seconds and peak allocated GPU memory was 3.82 GiB. Training loss fell from 0.22184 to 0.00006124; fitting four repeated examples does not establish generalization.

The adapter and optimizer/RNG checkpoints were committed to the Modal Volume. The adapter and latest checkpoint were also exported to SSD-local `artifacts/adapters/20261104T071521Z-train-b77c8e/`: 12 files, 211,517,997 bytes. All five checkpoint payload hashes match `complete.json`. The Modal CLI directory export requires an existing destination directory; a nonexistent destination initially produced incomplete files, which were replaced and verified.

The first evaluation attempt stopped before model generation because the worker compared a canonical adapter path with a noncanonical root. A CPU-only diagnostic confirmed `/artifacts` is a symlink into `/__modal/volumes/`. Both adapter and checkpoint-parent validation now resolve both sides, while rejecting escapes. Seven new path tests passed; the integrated suite passed all 60 tests. The first CPU diagnostic failed before execution due to a serialized-function Python-version mismatch; the corrected diagnostic completed. All reservations remain in the ledger.

The existing adapter completed matched evaluation after the path fix. Interrupted-run recovery and resumed-training equivalence have not been tested. The worker source-fingerprint check correctly blocks resuming the pre-fix checkpoint under changed code; no bypass or checkpoint migration was performed. The exact training worker source was preserved under `artifacts/provenance/c06d4331d0cff442221b29bf9c8d79d3ce269d94f783b39e333a7a99794ba199/modal_workers.py` and verified against the original report hash.

Run: `20261104T071521Z-train-b77c8e`. [W&B training evidence and loss curve](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/g0tw2hjk).

## Matched comparison and decision

| Measure | Original parent | Trained adapter | Paired change |
| --- | ---: | ---: | --- |
| Training families | 4/16 (25%) | 6/16 (37.5%) | 2 wins, 0 losses |
| Development families | 7/8 (87.5%) | 5/8 (62.5%) | 0 wins, 2 losses |

The two gains were sequence-padding tasks. The two regressions were grouped-reduction tasks. Masked mean stayed 4/4, stable softmax and gradient clipping stayed 0/4, and interval union stayed 4/4. The adapter produced one token-limited response, versus three in the parent baseline.

The task dictionaries/hash, inference settings, installed package inventory, and base revision match. A later framework audit found different observed GPU names: baseline NVIDIA A10G, candidate NVIDIA A10, both requested through Modal A10. This is not an exact-hardware matched comparison, and the strict framework comparator rejects it. The new MBPP study uses explicit L40S hardware and checks reported identity. The worker code difference fixes artifact path handling; it does not change prompts, sampling, quantization, or scoring. Adapter generation took 276.04 seconds; total worker execution took 287.99 seconds, with 2.05 GiB peak allocated GPU memory.

**Decision: retain the original parent; do not promote the adapter.** Training loss reduction and two training-family gains were accompanied by worse development performance. The tiny correlated suite and one seed cannot establish a general learning effect, and this experiment does not test successor-improvement ability. No final-test tasks were used. The next useful work is a frozen, costed redesign with broader verified training yield and harder development tasks, as proposed in [NEXT_EVALUATION.md](NEXT_EVALUATION.md).

Run: `20261104T072356Z-evaluate-92cbe2`. [W&B matched evaluation](https://forge.coreweave.com/wandb/ashu-na/rsi/runs/ivo3034e). The W&B API confirmed the training run's 20 loss points/report artifact and the evaluation's completed status, both pass-rate metrics, and report artifact.

## Budget and handoff

Nine stage attempts reserved **$45** in the cumulative ledger, including failed attempts and two CPU diagnostics. **$25** remains held for overhead, leaving **$180** available for further job reservations under the unchanged **$250** total cap. These are conservative planning reservations, not charges; actual Modal invoice totals have not been reconciled. Do not automatically refund failed or short runs. Persistent Volume storage is retained and must be included in later billing reconciliation.

The first cycle is complete, with no automatic repeat or promotion. A final Modal status read confirmed all nine project apps stopped with zero tasks; the snapshot is saved in `work/modal-final-app-status.json`. Code and experiment documentation are backed up to GitHub; full reports are on the SSD and in W&B; the adapter/checkpoint are on the Modal Volume and SSD with verified checksums. Existing visible chats remain the owners of future GPU, task/evaluation, and sandbox work; main chat coordinates paid launches.
