# Successor teaching probe v1

Prospective study, no measured results yet. Main alone coordinates paid launches. The plan permits at most five $5 reservations ($25), inside the existing $250 project cap; no automatic retries, replication or promotion.

Question: does the experimental verified-SFT adapter produce training material that creates a better successor than material from the original model, when both students start from the same original base and use matching training/evaluation controls? The adapter previously failed retention and remains unpromoted.

Reviewed data: 24 strictly never-generated native-train candidates, 261 approved mutation calls, three categories. Audit originals and approved probes, then select the first 20 eligible tasks in the recorded order. Four candidates are reference-only fallbacks; stop if fewer than 20 tasks or three categories survive. The review rejects ambiguous/faulty references and known semantic overlaps. It is not proof of reference correctness or pretraining disjointness.

Stages:

1. Calibrate references and stronger cases; freeze data; generate a fresh starting-student baseline on the existing 32 development and 16 retention tasks. Freeze actual runtime and full successor protocol before teacher generation.
2. Original teacher: greedy and independent sampled attempts on all 20 training tasks.
3. Learned experimental teacher: identical tasks, controls and attempts. Recompute both verified selections. Require at least 16 unique targets and three categories per teacher, none over 60%; preserve failures. Identical final training data also stops child training.
4. Original-teacher child: fresh original base, seed42, 16 optimizer steps, matched evaluation and full checkpoint export.
5. Learned-teacher child: same starting student/seed/steps, its teacher's verified data, matched evaluation and export. Both child stages run only if the paired data gate passes.

Teacher yield is not successor-improvement evidence. For a promising child comparison, the learned-teacher child must gain at least three development successes over both the other child and starting student, and lose no individual retention successes relative to either. Always retain the original parent. Repeated generations and replication require a future protocol.

The final native 500-task file is hash-checked only: no decoding, model use, scoring or selection. Development is previously exposed, not fresh held-out evidence. Final-test rows had been eagerly decoded by a historical loader, which is explicitly avoided here.

`plan.json` binds source/config/review inputs before calibration. The full task-bearing protocol lives in ignored `data/successor-v1/protocol.json`; the tracked `protocol.json` contains its digest, control inventory and task IDs. Durable reports, adapters, checkpoints and full evidence remain outside Git and are tracked with explicit W&B artifact allowlists.

Library interfaces and limitations: `docs/SUCCESSOR_MEASUREMENT.md`, `docs/PORTABLE_MODAL.md`, `docs/QUICKSTART.md`. Research and library goals remain recorded in `AGENTS.md` and `docs/PROJECT_PLAN.md`.
