# Running the first pilot

The controller is `rsi/pilot.py`. It reads the SSD-local `.env`, reserves a budget allowance before remote work, logs to `ashu-na/rsi`, and saves reports under ignored `runs/<run-id>/report.json`.

## Ordered stages

```sh
.venv/bin/python -m rsi.pilot budget
.venv/bin/python -m rsi.pilot smoke
.venv/bin/python -m rsi.pilot baseline --count-per-family 4
.venv/bin/python -m rsi.pilot train --parent-run BASELINE_RUN_ID --max-steps 20
.venv/bin/python -m rsi.pilot evaluate --training-run TRAIN_RUN_ID
```

Replace the uppercase IDs with completed report IDs; do not rerun blindly. Each stage creates a separate real-model W&B run and reserves $5. Authentication-only checks use the separate `scripts/check_services.py` tool.

The smoke stage loads the pinned NF4 model on an A10, generates an addition function, and verifies it in a disposable CPU sandbox. The default baseline contains 16 train-family tasks and 8 development-family tasks, with one greedy attempt per task and a 512-token output limit. Expected answers and hidden cases are not model inputs.

Training selects only verified train-split completions from that saved baseline. It requires at least four examples, uses completion-only QLoRA, and never uses development targets or reference implementations as labels. The first short run is primarily an end-to-end training check. Small, correlated data can overfit, so its outcome is not evidence of sustained improvement.

Evaluation uses the same tasks, prompts, seed, decoding limits, quantization, and hardware class as the parent. Report training-task retention separately from development-family performance. Final-test families are not called by this controller. No automatic promotion is implemented: the first result needs replication and a frozen acceptance protocol before promotion is justified.

## Budget behavior

`config/budget.json` records the user-authorized $250 total Modal cap. The ledger at `budget/ledger.json` is cumulative and backed up with Git. $25 stays reserved for build/startup/egress/storage overhead, leaving $225 for stage reservations. Failed and interrupted stages keep their reservation; the controller does not refund estimates automatically. Do not delete/reset the ledger to retry a job.

The worker constrains GPU type, CPU/RAM requests and maxima, concurrency, startup/execution timeouts, idle duration, and input sizes. Functions have no configured input retries. Sandbox count is bounded by the task count and each sandbox has a 30-second maximum lifetime. The controller cancels its function call on client timeout and terminates verification sandboxes after use.

This is a conservative application-level guard, not an account billing limit. Provider-initiated infrastructure behavior, image builds, retained Volume storage, and unrelated account workloads are not precisely measured by it. Reconcile actual billing before sustained campaigns and account for storage retention. Do not claim that reserved dollars are an invoice. A budget increase requires a separate user decision.

## Recovery and evidence

Reports store the source-file hashes as well as the Git commit because the first integration may use uncommitted reviewed files. They also store model revision, task hash, decoding settings, call/app IDs, generated outputs, verification results, package versions, and W&B links. Each task result is persisted as it completes. Infrastructure failures stop the comparison rather than being treated as model mistakes.

Inspect persisted call IDs and Modal status after an interruption before retrying. Reserve a new allowance for an intentional retry. Completed model/optimizer checkpoints live on the Modal Volume; reports and W&B metadata do not replace checkpoint backups.
