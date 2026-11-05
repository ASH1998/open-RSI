# Native MBPP cohort for repair v1

**Native-only selection is ineligible for launch.** Of the 27 accepted native training rows, 19 were assigned to training and eight held back for development evaluation. The training group contains 11 collections, six numeric and two text tasks. The holdout contains five collections and three numeric tasks. The native shortfalls are five training tasks and four text tasks against the 24-task and six-text minimums. The holdout supports no text-specific evaluation.

| Source | Project role | Source assertions | Additional private checks |
|---|---|---:|---:|
| MBPP full train | train | 57 | 65 |
| MBPP full train | evaluation | 24 | 26 |

All 172 cases passed a reference calibration bound to revision `4bb6404fdc6cacfda99d4ac4205087b89d32030c` of `google-research-datasets/mbpp`. Raw references came exclusively from the pinned full native training Parquet. The source and derived descriptions are attributed to Google Research and Austin et al., *Program Synthesis with Large Language Models* (2021), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The underlying data license applies to the modified wording and additional cases.

## Selection and exclusions

The [selection record](selection.json) binds the importer manifest, prior domain review, exposure registry, source Parquet, preparation code, contract scorer, and per-task source and output evidence. The original importer clustered normalized prompts, canonical reference ASTs and similar descriptions using all source splits. This study reads only its existing train/dev pools and cluster metadata. No final or prompt rows are read. For each candidate the script checks source revision and split, single-native-split cluster, representative ID, and disjointness against the 284 exposure records and all earlier choices using IDs, original source identities, prompt identities and duplicate groups. Broad categories overlap across splits. Public model pretraining exposure is unknown.

Of the 272/68 previously screened native train/validation rows, 69/11 survive the exposure filter. After applying the fixed manual exclusions (including 541/955 and 554/629), diagnostic exclusions and typed-test conversion, there are 64/6. The selection record gives a disposition for each of these 70 rows. The 27 selected rows have a reviewed domain, separately worked private expected outputs, and an explicit project role. Fixed reviewed IDs are sorted numerically in each role. No model attempts or outcomes were used in selection. The two plausible remaining validation candidates, 531 and 575, do not meet the eight-task target. The fixed holdout uses eight disjoint native training rows. Both roles keep their original source split; the enclosing manifest determines the experimental role.

The text screen is particularly restrictive. Rows 631, 806 and 967 have defective native full references. The native 773 task overlaps 607's substring-location task, which lies in a quarantined multi-split component, and its earlier specification leaves missing matches ambiguous. Row 900 specializes exposed prefix task 823. Row 829 projects frequency-rank tasks 862/946. Only 759 (decimal-string validation) and 832 (maximum parsed decimal run) remain. Row 944, unlike 832, returns the *position* of the first run. The shared parsing step does not determine the maximum. New cases for 832 distinguish numeric ordering from lexicographic or longest-run ordering. Numeric task 840 was quarantined as a quadratic-root template variant of 636. Prior review excluded 664 for out-of-domain generic mutations; its original assertions are consistent, so this study uses even inputs only. No alternate configuration, synthetic examples as tasks, or supplemental dataset enters the native cohort.

## Contracts and reference checks

[Reviewed contracts](reviews.py) give independently specified positional calls and typed expected values. The [builder](prepare.py) preserves the inherited assertions, applies and replays the public task-contract APIs, and validates the generation-only projection. Native tasks 644 and 832 use the parameter name `input`. Reading this name would violate candidate policy. Before contract derivation, the builder verifies that every inherited call is positional and renames only that parameter to `values`, recording the original task digest and both signature lines. Native identity, entry point, arity, raw reference code and positional assertions stay bound to the source.

The [reference worker](reference.py) accepts only reviewed identities and arguments in a separate CPU-limited interpreter with an empty credential environment. It compares the pinned native row digest and runs the named reference without receiving expected values. A small allowlist covers reference-only standard-library imports and exact-byte local-parameter or list-addition exceptions; the generated candidate policy is unchanged. Every inherited and new case required an exact typed value match in addition to the library scorer. Each task was also checked by replacing one saved boundary output and confirming rejection. These finite checks do not establish full semantic independence or arbitrary-input correctness.

From the SSD root:

```sh
.venv/bin/python -m studies.repair_v1.data.prepare
```

On a checkout containing the pinned inputs and no saved outputs, add `--freeze`. The builder first verifies all existing files and creates only missing files. `data/repair-v1/cohort.json` includes full train/evaluation arrays, both manifest paths and seals, raw typed reference checks, and the explicit native-only shortfalls. The native cohort seal is `e9db7f08d3025527344271ca72d8af174d6545bdfd196fda10bbc66e00812cfd`. The ordered native training sources and reviews can independently regenerate the training manifest. A supplement, if separately approved, must preserve these native files, bind its own source and comparisons, and produce a new selection and seal before any model work.

The root ignore rule for `data/` also matches this study's source folder. When the main chat records the study, include this README, `selection.json`, and the three Python sources explicitly, while keeping the root-level raw data and generated manifests ignored.
