# MBPP self-training study

This study is the next user-authorized coding experiment under the existing $250 Modal cap. The user's Mini-RSI Lab v0.2 document is a design reference, not authorization for its $500 budget, different model, publication schedule, or assumed local GPU.

The first implementation goal is a reusable, installable Python framework exercised by a real dataset experiment: immutable tasks/manifests, isolated execution, baseline preservation, a verified-data operator, matched comparisons, and a trusted retain-parent decision. Nano-LM, heuristic optimization, DPO, harness evolution, and Level-2 improver tests remain future work.

Dataset candidate: Google Research MBPP at immutable Hugging Face revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c`, CC BY 4.0. Use source train and validation splits with explicit unsupported-test, duplicate, and reference-audit exclusions. The final protocol and exact subset must be frozen before model generation. Scores describe that filtered subset, not the standard MBPP leaderboard.

This study uses dataset-native splits. Broad algorithm categories can overlap between train and validation; it is not the synthetic pilot's family-held-out design. Remove detected exact/near duplicates across splits and report the remaining semantic-overlap and pretraining-contamination limitations. Public source validation is development data, not a sealed final benchmark. Do not use MBPP test/prompt rows as labels or evaluation tasks in this experiment.

Budget at entry: $45 in conservative job reservations and $25 overhead holdback; $180 available for new reservations. A read-only Modal dashboard check on November 4 showed $0.30 workspace usage for the current billing period, covered by credits. This is an account-level observation, not a per-job invoice; prior reservations remain unchanged. The project's $250 ceiling counts compute use even when paid by credits. Kaggle is secondary capacity; any result from different hardware/precision is labeled separately from the paired Modal comparison.
