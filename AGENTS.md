# Instructions for agents working on Open RSI

## Start here

Read `README.md`, `docs/PROJECT_PLAN.md`, and `docs/SETUP.md` before implementation. Treat documented proposals as proposals, not completed work or measured results. Keep these documents updated when decisions or implementation status change.

## Workspace constraint

The user explicitly requires all local project work to stay under:

`/Volumes/DevSSDWD/openbmb/rsi`

- Run commands from this directory. If the SSD is unavailable, report it; do not silently create an alternative checkout on the internal disk.
- Keep virtual environments, package caches, model downloads, datasets, run outputs, temporary files, and logs here. Use the paths in `.env.example` and create directories before use.
- Do not install project packages globally or write project credentials into home-directory configuration files. Prefer environment variables and a project-local `.venv`.
- Cloud workers necessarily use remote paths. Configure their cache/output locations explicitly and persist results before worker termination; downloaded results return to this SSD folder.
- Use `work/` for scratch files. Git tracks source, configuration templates, and documentation; large artifacts belong in ignored directories and persistent remote storage.

## Project decisions

- Modal is the primary compute provider. Use GPU Functions for defined training/inference/evaluation jobs and Sandboxes for executing generated code. A GPU Sandbox is available when an experiment needs it.
- Kaggle is optional secondary capacity for small experiments on GPUs or TPUs. Never make the main controller depend on Kaggle availability. TPU training needs a separately validated backend; CUDA QLoRA code is not automatically portable.
- Prefer OpenBMB 2B-class text models. `openbmb/MiniCPM5-2B` is provisional. Verify exact revision, tokenizer, license, trainability, and baseline capability before adopting it.
- Use W&B for run tracking and artifact lineage across providers. Do not infer a need to migrate compute to CoreWeave.
- Begin with verified SFT and LoRA/QLoRA. Keep the first experiment small and compare models under the same inference budget.

## Experimental integrity

- Keep training, development, and final evaluation task families separate. Near-duplicate variants must not cross splits.
- Verifiers must be independent of the candidate's proposed answer. Candidate code must not modify authoritative tests or the evaluator.
- Preserve raw successes and failures. Only selected verified targets become SFT labels; failed actions may appear as context.
- Record exact model/code/data/evaluator versions, seeds, settings, hardware, tokens, time, and cost. Keep the parent checkpoint and support rollback.
- Preserve resumable checkpoints, including optimizer/scheduler and RNG state when training resume requires them. An adapter alone is not a complete training-state checkpoint.
- Do not claim sustained RSI from a task-score improvement. Test successor-improvement ability separately.
- Log metrics and selected examples to W&B, not credentials or entire environment dumps. Keep an explicit allowlist for uploaded code and files.

## Credentials and scope

Never commit `.env`, provider credential files, model weights, or raw run data. Inject only each worker's required secrets; generated-code sandboxes should not receive provider control credentials or tracking credentials.

The current request establishes documentation and a GitHub backup. It does not establish a paid experiment budget. Record runtime and cost limits when a future experiment is requested; do not treat the planning estimates as approved spending.

For each handoff, record what was changed, what was actually verified, unresolved assumptions, and the next executable milestone. Do not repeatedly ask the user to reconfirm the settled provider and SSD decisions.
