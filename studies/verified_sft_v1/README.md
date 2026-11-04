# Verified-data SFT v1

Prospective experiment authorized after the stronger diagnostic study. Total reservation envelope: $20, in at most four $5 stages. Global Modal cap remains $250; historical reservations are not refunded.

The frozen protocol binds source, model, policy, candidate-pool and domain-review identities. There are 154 reviewed reference candidates (116 train, 38 development), with a deterministic reference-only fallback order selecting 96 train and 32 development tasks. Sixteen previously selected original training tasks are reserved for retention and excluded from the new training pool. Some development tasks were previously generated; prior exposure is recorded. The native 500-task final split remains untouched.

Stages: (1) reference calibration, approved input probes, audited data freeze, initial training attempts and parent evaluation; (2) independent sampled attempts plus one feedback repair for at most 32 tasks failing both attempts; (3) one fresh seed-42 QLoRA adapter and matched evaluation; (4) seed-43 replication only if net development gain is at least three and no previously passing retention task is lost. No automatic promotion or final-test use.

Only independently verified model outputs become SFT labels. Reference code supplies test expectations and never training targets. The minimum gate is 24 unique labels spanning three categories, none above 60%. Reference-derived tests are not proof of reference correctness. Domain review rejected invalid input mutations, ambiguous tasks and identified faulty references before generation.

Reusable components live in `rsilab.coding_data`, `rsilab.learning`, `rsilab.workflow`, `rsilab.execution`, `rsilab.project`, and `rsilab.providers.modal`. The SSD-specific experiment adapter is `rsi.verified_study`; frozen historical controllers remain unchanged. Offline CLI commands expose dataset freezing, target selection and matched comparison. The historical GPU implementation still requires the project checkout and pinned requirements file.

Run commands from the canonical SSD with `.venv/bin/python -m rsi.verified_study`. Never duplicate an attempted stage or bypass the gates. The protocol and data are frozen before model generation; raw evidence and checkpoints remain in ignored SSD/provider storage. Results will be recorded after completion.
