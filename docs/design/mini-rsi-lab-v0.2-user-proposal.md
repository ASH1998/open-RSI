# Mini-RSI Lab v0.2: An Open Framework for Measurable Recursive Self-Improvement

Nov 1, 2026 · @Ashutosh

## What changed from v0.1

v0.2 turns Mini-RSI from one experiment into an open framework for running and measuring recursive self-improvement, with one flagship study as its first user. The study is sized to finish in four weeks on a $500 Modal credit plus a local RTX 4070 Ti SUPER.

1. **Framework first.** The contribution is the measurement harness: a trusted controller, matched budgets, operational tests for each RSI level, and full provenance. Weight-harness co-evolution itself is no longer claimed as new, because Evo² and CoTrace already cover it.
2. **Scoped to what the budget can answer.** Three learning arms instead of five, Level 1 and Level 2 tests only, and noise measured before any arm runs.
3. **Hardware-independent budgets.** The main task family budgets training tokens with a parameter cap instead of wall-clock time. Results then hold across the local GPU and Modal, and the "shrink the model, train longer" shortcut stops dominating.
4. **Optima that move.** Evaluation tasks vary the token budget, dataset and parameter cap, so a researcher that memorises one recipe fails on the next task.
5. **A cheap second environment.** A CPU-scored heuristic-optimisation suite lets the framework iterate in seconds and doubles as the transfer test.
6. **Level 2 measured directly.** Each generation's model is handed the same improvement job on the same frozen agent, so "better improver" becomes a paired measurement rather than an impression.

## Thesis and positioning

RSI claims are hard to compare today because every system defines its own budgets, evaluators and success bar. Mini-RSI Lab supplies one protocol: any agent, any environment and any improvement operator can be plugged in, and every claim is scored against the same matched-budget, sealed-holdout tests.

The flagship study then asks one question the recent systems leave open at small scale: **does training a researcher's weights on its own verified experiment history make it a better improver, not just a better solver?**

| System | What evolves | Who proposes changes | Gap this project targets |
| --- | --- | --- | --- |
| [AIDE²](https://arxiv.org/abs/2609.26457) (Weco, Sep 2026) | Research-agent code | A fixed frontier model in the outer loop | Weights never change; authors did not claim Level 2, partly because extra seeds were too costly |
| [ScienceBuddy](https://github.com/Gen-Verse/ScienceBuddy) (Sep 2026) | Harness (inner loop), model via RL (outer loop) | Nested loops | Built as a research workspace, not a measurement protocol |
| [Evo²](https://arxiv.org/abs/2610.13025) (Oct 2026) | Harness and a shared proposer–reflector model | The trained model itself | Coding and memory tasks; read its evaluation before claiming any difference |
| [CoTrace](https://arxiv.org/abs/2610.10426) (Oct 2026) | Terminal-agent harness and policy | Alternating loop with per-component promotion | Focus is the data recipe, not RSI-level measurement |
| [autoresearch](https://github.com/karpathy/autoresearch) | `train.py` of a small LM | An external coding agent | Base environment only; no learning researcher |

The defensible contribution is therefore an open, cheap, evaluation-first framework, plus a well-powered small-scale Level 2 test on ML-training research. A clean null result is still publishable.

## RSI levels the framework measures

The framework turns the RSI ladder into three paired tests; v0.2 runs Level 1 and Level 2. The level names follow [Weco's framing](https://noqta.tn/en/blog/weco-aide2-recursive-self-improvement-rsi-2026), where Level 2 means the improved agent becomes a better improver.

An agent at generation k is A\_k = (M\_k, H\_k, E\_k): model weights, harness code and verified experience. S\_t(A, B) is agent A's best score on task t after research budget B.

| Level | Claim | Operational test | In v0.2 |
| --- | --- | --- | --- |
| 1 · Net positive | A\_k+1 is a better researcher than A\_k | Paired score gain on sealed tasks at equal budget B | Yes |
| 2 · Ignition | A\_k+1 is a better improver than A\_k | Each model improves the same frozen agent; compare the gains its edits produce | Yes, headline |
| 3 · Acceleration | Gains per generation grow at fixed budget | Slope of per-generation gains over 5+ generations | No; needs more generations than four weeks allow |

Level 1 is the paired gain on a sealed task t:

```latex
\Delta_1(k) = \mathbb{E}_t\left[ S_t(A_{k+1}, B) - S_t(A_k, B) \right]
```

Level 2 fixes an improvee agent A° = (M\_0, H\_0) and gives each improver model M\_j the same job: propose edits to H\_0 under improvement budget B'. The edit it selects is scored on fresh tasks, so the measure is the gain it produces for someone else:

```latex
I(M_j) = \mathbb{E}_{t \in \text{fresh}}\left[ S_t\big(M_0, H_0 \oplus \text{edit}_{M_j}, B\big) - S_t\big(M_0, H_0, B\big) \right]
```

Level 2 holds when I(M\_final) − I(M\_0) > 0 with a confidence interval that excludes zero. Holding the improvee fixed separates the improver's skill from the improvee's starting strength.

## Framework architecture

Everything that scores, records or promotes sits in a trusted zone the agent cannot write to; the agent only proposes.

&#91;embedded content: framework architecture · trusted zone between agent and environments\]

Read it as a loop: the agent's proposals run in sandboxes, the evaluator scores the outputs, the ledger keeps the verified record, the operators build a candidate from it, and only the gate can turn that candidate into the next agent.

The four interfaces a new study implements:

```python
class Environment(Protocol):
    def tasks(self, split: Split) -> list[Task]: ...
    def run(self, task: Task, patch: Patch, seed: int) -> RunResult: ...  # sandboxed

class Evaluator(Protocol):  # trusted
    def score(self, task: Task, result: RunResult) -> Score: ...

class Operator(Protocol):
    def propose(self, agent: Agent, ledger: LedgerView) -> list[Agent]: ...

class PromotionGate(Protocol):  # trusted
    def decide(self, parent: Agent, candidates: list[Agent]) -> Decision: ...
```

## Reference environments

v0.2 ships two environments behind the same interface: one slow and realistic, one fast and cheap. Both expose dev, promotion and sealed splits, and both are scored only by the trusted evaluator.

| Environment | What the researcher changes | Score | Budget per run | Runs on | Role |
| --- | --- | --- | --- | --- | --- |
| `nano-lm` (from autoresearch) | `train.py`: optimiser, schedule, architecture, init | Validation bits per byte (lower is better) | Fixed training tokens + parameter cap; about 2 min on an L40S | Local GPU for development and rollouts; Modal L40S for every comparison | Main research task |
| `nano-lm-wallclock` | Same file | Validation bits per byte | Fixed 90 s wall-clock | One device only (Modal L40S) | Efficiency family; never mixed across devices |
| `heuristic-opt` | A solver file for small combinatorial problems (packing, routing, scheduling) | Deterministic objective | Seconds on CPU | Local or Modal CPU | Framework iteration and transfer test |

**How the optima move.** Each `nano-lm` task draws a token budget, a dataset and a parameter cap from a manifest. A recipe that wins at one setting is not the winner at the next, so memorised answers stop transferring.

**The default autoresearch config needs about 45 GB of VRAM**, so `nano-lm` uses a scaled-down model of roughly 10–30M parameters that fits on 16 GB. The findings at this scale are not the point; the testbed only has to be fair, cheap and measurable.

**Splits.** Dev tasks select harness candidates. Promotion tasks decide whether a generation is accepted. The sealed split is opened once, after the analysis plan is committed.

## Improvement operators

An operator takes an agent and verified experience and returns a candidate successor; the controller, never the operator, decides whether it is promoted. Every operator in v0.2 is proposed and run by the current model, so later generations improve themselves rather than relying on a fixed outside helper.

| Operator | Changes | Input data | Compute | v0.2 |
| --- | --- | --- | --- | --- |
| `MemoryUpdate` | E\_k: summaries of verified findings and failures, with retrieval | Ledger of past runs | Negligible | Yes |
| `HarnessEvolve` | H\_k: diffs to the `researcher/` package (planning, search, pilot runs, failure handling) | Recent trajectories + current harness | Inference + dev-split evaluation | Yes, 3 candidates per generation |
| `WeightSFT` | M\_k: LoRA adapter (rank 16) | Successful trajectories and correct failure diagnoses | A100 80GB, about 1–2 h | Yes |
| `WeightDPO` | M\_k: same adapter | Proposal pairs from one state whose outcomes differ by more than 2σ over at least 2 seeds | A100 80GB, about 1 h | Yes |
| `WeightGRPO` | M\_k with execution-verified reward | Online rollouts | High | Stretch goal only |

**Adapters.** Each generation trains a fresh adapter on the frozen base from all verified data so far (cumulative replay). This avoids stacking adapters; continual training from the previous adapter is an ablation only if budget remains.

**Labels.** Preference pairs use measured outcomes only, with the noise threshold above. Rewarding informative but losing experiments is a known gap in v0.2 and is listed as future work rather than approximated.

## Promotion gates and statistics

No arm runs until seed noise is measured, and no generation is promoted on a single lucky campaign.

1. **Calibrate noise first.** Run the baseline 20 times per `nano-lm` setting to estimate σ, the seed-to-seed spread of the score.
2. **Size every comparison from σ.** All comparisons are paired: the same tasks and seeds across arms. The campaigns needed per cell follow the formula below; if that number is unaffordable for the effect that matters, lengthen runs or drop an arm before starting, not after.
3. **Promotion rule.** A candidate is accepted when the lower bound of the 90% confidence interval on its paired gain over the parent is above zero on the promotion split. It also needs no sandbox violations and no more than a 20% rise in compute per run. Otherwise the parent is kept, or the better validated single change.
4. **Seal the final split.** The analysis plan, stopping rule and selection procedure are committed to the repo, with their hash in the manifest, before the sealed split is touched.
5. **Report everything.** Effect sizes with intervals, seed-level data, rejected generations and failed runs are all published.

```latex
n \approx \frac{(z_{1-\alpha/2} + z_{1-\beta})^2 \, \sigma_d^2}{\delta^2}
```

Here n is campaigns per cell, δ the smallest gain worth detecting, σ\_d the spread of paired differences, α = 0.05 and power 1 − β = 0.8.

## Flagship study

**Question:** does LoRA-training a small researcher on its own verified experiment history make it a better researcher (Level 1) and a better improver (Level 2) than giving the same model the same history as memory?

| Arm | Memory | Harness evolves | Weights update | Isolates |
| --- | --- | --- | --- | --- |
| Fixed | No | No | No | Generation 0 reference; no separate loop needed |
| Memory | Yes | No | No | Value of accumulated experience alone |
| Weights | Yes | No | Yes | Weight learning beyond memory (Weights − Memory) |
| Joint (RSI) | Yes | Yes | Yes | Full self-improvement loop |

A code-only arm is a stretch goal for week 4 if credit remains.

**Researcher model.** Start with a 4B-class instruct model (Qwen3.5-4B, as in v0.1), served with vLLM. It must pass a capability gate in week 1: at least 60% of proposed `train.py` patches run, and at least 1 in 10 beats the baseline beyond 2σ. If it fails, move to an 8B-class model. If that fails too, restrict actions to structured config and template edits and say so in the report.

**Generations.** Three: M\_0 → M\_1 → M\_2 → M\_3 for the Weights and Joint arms, with the promotion rule applied at each step.

**Level 2 protocol.** The improvee is frozen at (M\_0, H\_0). M\_0 and the final promoted model each run the same improvement job four times: propose 3 harness edits, pick one on dev tasks, then score the pick on fresh `nano-lm` tasks with 5 campaigns. The same job on `heuristic-opt` tests transfer.

**Primary outcomes.** Δ\_1 on sealed `nano-lm` tasks (Weights vs Memory, Joint vs Memory) and I(M\_final) − I(M\_0). Everything else is secondary.

## Compute plan and the $500 budget

The plan spends about $330 on Modal and keeps about $170 in reserve, because the cheap, high-volume work runs on the local GPU. The rule: anything that feeds a comparison runs on Modal L40S, and anything that only generates training data or tries out code runs locally.

| Line item | Where | Volume | Estimate (USD) |
| --- | --- | --- | --- |
| Researcher inference (vLLM, scale to zero, batched rounds) | Modal L40S | \~50 GPU-h | 98 |
| Level 2 test (2 improvers × 4 repeats) | Modal L40S | \~1,100 runs, \~46 GPU-h | 90 |
| Level 1 sealed evaluation (8 configurations × 8 campaigns) | Modal L40S | \~770 runs, \~32 GPU-h | 62 |
| LoRA training (6 adapters + capability tests) | Modal A100 80GB | \~15 GPU-h | 38 |
| Promotion checks (2 arms × 3 generations) | Modal L40S | \~430 runs, \~18 GPU-h | 35 |
| Noise calibration on the comparison device | Modal L40S | \~80 runs | 7 |
| Rollouts for training data, harness dev selection, all development | Local 4070 Ti SUPER | Thousands of runs | 0 |
| **Reserve:** reruns, CPU/RAM and storage billing, stretch arm | — | — | 170 |

A campaign is 12 runs; a run is about 2.5 minutes including startup. GPU rates are the v0.1 figures (L40S $1.95/h, A100 80GB $2.50/h) and should be checked against Modal's pricing page before week 1.

**Keeping inference cheap.** Campaigns run in lockstep: the controller collects the next proposal from 16 campaigns at once, starts one vLLM container, generates them all, and lets it scale to zero. An always-on L40S for four weeks would cost more than the entire credit.

**Credit deadline.** The credit expires around 1 December, so every Modal-heavy evaluation must finish by 29 November, leaving two days for reruns. If spending is more than 25% over plan at the end of week 2, the Joint arm's harness evolution is cut first.

## Repository layout

The repo is a pip-installable package, `rsilab`, with the flagship study as one folder under `studies/`. Anything under `rsilab/core/` is trusted and read-only during a run; agents may only change `agents/researcher/` and an environment's patchable file.

```
mini-rsi-lab/
├── rsilab/
│   ├── core/                 # trusted: controller, budget ledger, promotion, provenance
│   │   ├── controller.py
│   │   ├── budget.py
│   │   ├── promotion.py
│   │   ├── ledger.py         # content-addressed runs, manifests, hashes
│   │   └── evaluator.py      # calls each env's trusted scorer
│   ├── agents/
│   │   ├── base.py           # Agent = (Model, Harness, Memory)
│   │   └── researcher/       # evolvable harness H_k
│   ├── operators/            # memory_update, harness_evolve, weight_sft, weight_dpo
│   ├── envs/
│   │   ├── base.py           # Environment: tasks(split), run(patch, seed), score()
│   │   ├── nano_lm/          # train.py patchable; scorer trusted
│   │   └── heuristic_opt/
│   ├── backends/             # local GPU, Modal sandbox, Modal vLLM, Modal trainer
│   ├── levels/               # Level 1 and Level 2 test protocols
│   └── stats/                # noise calibration, power, paired intervals
├── studies/
│   └── flagship_v02/
│       ├── config.yaml
│       ├── preregistration.md  # committed before the sealed split opens
│       └── report/
└── tests/
```

Each accepted generation writes a manifest with the base-model hash, adapter hash, harness commit, training-data hash, evaluator version, preregistration hash, promotion decision and run ids, as in v0.1.

## Four-week plan

Four phases, each ending in a gate whose criteria are fixed now; every Modal-heavy run finishes by 29 November.

&#91;embedded content: four-week plan · 4 phases, 4 gates\]

A missed gate triggers the matching response in the risk table below, never an extra week.

## Risks and kill criteria

Each risk has a signal that is checked at a gate and a decision made in advance, so nothing is rescued by moving the goalposts.

| Risk | Signal | Response |
| --- | --- | --- |
| 4B researcher cannot make useful patches | Capability gate missed at end of week 1 | Switch to an 8B-class model; if still missed, structured edits only, stated in the report |
| Noise swamps the effects that matter | Required campaigns per cell exceed budget | Lengthen runs or cut the Joint arm before arms start |
| Weights arm only memorises recipes | Gains on dev tasks vanish on shifted-optima sealed tasks | Report it as the finding; it is a real result |
| Agent games the evaluator or file handling | Diff audit or sandbox log flags evaluator access | Reject the generation; fix the boundary; rerun its promotion check |
| Infrastructure eats the month | `heuristic-opt` loop not end to end by day 5 | Freeze framework scope and drop `nano-lm-wallclock` |
| Credit overspend | More than 25% over plan at end of week 2 | Cut Joint harness evolution, then reduce Level 1 campaigns; Level 2 is protected |
| Credit expires before final runs | Sealed evaluation not started by 25 November | Run Level 2 first; Level 1 can finish on the local GPU with the device noted |

## Deliverables for the resume

The project ships as five public artifacts by 30 November, each usable on its own.

- [ ] `mini-rsi-lab` on GitHub: pip-installable, two environments, documented interfaces for adding agents, environments and operators
- [ ] Technical report (arXiv-style, about 8 pages): framework, Level 1 and Level 2 results with intervals, all failed generations
- [ ] Hugging Face release: the trajectory dataset and the promoted LoRA adapters
- [ ] Blog post and a short video walking through the Level 2 result
- [ ] One-command reproduction of the flagship study on Modal, with its cost printed

**Resume line (fill in the result):** Built Mini-RSI Lab, an open framework for measuring recursive self-improvement in AI research agents; ran a pre-registered study on whether LoRA-trained researcher models become better improvers, finding \[result\] at a total cost under $500.
