# Auditing the MBPP v2 rescore

`rsilab.rescore.audit_rescores` is an offline lineage and verification-envelope
audit of the saved MBPP experiment. It does not execute candidate code, generate
new answers, train models, modify historical reports, or import the evaluator.
The v1 reporting helpers remain unchanged.

## Inputs and controller responsibilities

Supply the frozen study, all 13 original generation reports (six parent, three
per adapter, one Kaggle), the two original training reports, and 13 logical
rescore records. The controller groups these into four completed stage reports:
parent, seed 42, seed 43, and Kaggle. Check every grouped stage is completed and
the independent reference audit passed before flattening its `rescores` list.

Each logical rescore must contain:

```python
{
    "stage": "mbpp-rescore-v2",
    "status": "completed",
    "source_run_id": original_report["run_id"],
    "source_report_sha256": digest(original_report),
    "study_sha256": study["sha256"],
    "rescore_protocol_sha256": expected_rescore_protocol_sha256,
    "evaluator_version": evaluator_version,
    "evaluator_source_hashes": evaluator_source_hashes,
    "records": [
        {
            "task": original_record["task"],
            "generation": original_record["generation"],
            "original_verification": original_record["verification"],
            "verification": new_verification,
        },
        # Same records, in the original order.
    ],
}
```

`digest` is `rsilab.digest`: SHA-256 of canonical JSON, **not file bytes**.
Logical rescores need no `run_id`. Their evaluator version and complete source
inventory must match across all 13 reports. Every non-truncated verification must
declare that version and exactly the same `evaluator_source_hashes` inventory.
The protocol can separately bind execution sources such as the controller and
audit helper; do not mix those into only some evaluator inventories.

Preserve generation-token-limit failures by copying their entire original
verification unchanged, including its absent v2 version/source fields. Do not
execute these truncated answers. The audit rejects their promotion or alteration.

The caller must independently verify the expected rescore protocol digest and
evaluator correctness. Before publishing, the controller must recompute outcomes
from saved evaluator outputs using its trusted scorer and reject contradictions.
The helper checks declared counts and flags; it cannot establish that candidate
execution or output scoring was correct. A reference gate and completed grouped
reports are external prerequisites, not facts inferred by this function.

## Calling the audit

```python
from rsilab.rescore import audit_rescores

assert all(group["status"] == "completed" for group in grouped_reports)
# Independently check the reference gate and trusted output scoring here.
logical_rescores = [item for group in grouped_reports for item in group["rescores"]]
summary = audit_rescores(
    study,
    original_reports,
    logical_rescores,
    training_reports=[training_seed_42, training_seed_43],
    rescore_protocol_sha256=expected_rescore_protocol_sha256,
)
```

Missing, duplicated, changed, incomplete, or inconsistent evidence is rejected.
The audit checks exact original tasks, generated text and metadata, record order,
model and adapter provenance, frozen settings, and matched Modal runtime/source
controls. It requires complete verification envelopes without infrastructure
failures. Original reports and logical rescore inputs are not mutated.

## Output and interpretation

The returned dictionary retains all 368 outcomes with original/new verification
evidence, source lineage digests, and pass/fail transitions. It includes:

- The full parent result on 176 tasks, separated by original split.
- Each adapter on 80 tasks, with paired parent comparisons on 48 development and
  32 training-retention tasks under both evaluator versions.
- Net success gains and lost parent successes for each paired comparison.
- The 32-task Kaggle result separately; it is not pooled with matched Modal arms.
- Source report, logical rescore, generation, model provenance, training report,
  evaluator inventory, original protocol, and rescore protocol digests.

This is a post-hoc evaluator correction on saved generations. It establishes no
new learning, checkpoint promotion, or RSI result. Dataset-native development
and training-retention results do not establish family-held-out generalization.
Keep immutable original reports alongside the separate rescore reports and audit
summary so both successes and failures remain inspectable.

## Local verification

Run from the SSD project root:

```sh
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p test_rescore.py -v
```

The fixtures are synthetic and execute no candidate code. Their tests cover all
368 outcomes, matched comparisons, immutability, source/text/order tampering,
evaluator inventory drift, missing/incomplete/duplicate reports, infrastructure
failures, and preservation of generation-limit failures. Test scratch files stay
under the project `work/` directory.

Implementation handoff: 11 offline tests passed. A read-only compatibility check
also accepted the 13 saved generation reports and two training reports using
synthetic new-version envelopes, covering 368 outcomes and all four existing
token-limit failures. That check was not a real v2 rescore and produced no saved
result. The next executable milestone is the main controller's reference audit,
v2 execution, trusted output scoring, and final call to this helper. This helper
does not certify those steps in advance.

## Local package 0.1.1

The correction is packaged and installed as `rsilab 0.1.1` in the SSD-local
`.venv`. Only the package version declarations changed during packaging; the
evaluator, controller, and audit helper still match the frozen rescore protocol.
This is a local artifact, with no PyPI release or dependency installation.

- Wheel: `work/rescore-framework-dist/rsilab-0.1.1-py3-none-any.whl` (83,850 bytes).
- SHA-256: `3b72462b4b0a33101101831a9a2dec38ba335ca4bc97f6f44283719958af66ba`.
- Explicit source staging: `work/rescore-framework-source/`; the exact allowlist,
  source hashes, archive inventory, and validation results are recorded in
  `work/rescore-framework-dist/wheel-audit.json`.
- The previous `work/framework-dist/rsilab-0.1.0-py3-none-any.whl` is unchanged,
  retaining SHA-256 `985a5a2a7b27874057a62ae862b1ebc306148cd373a26a30cd2c523538593551`.

Isolated Python checks verified installed core/rescore/v2 imports, version
metadata, every installed package file's checksum, and the frozen evaluator
inventory. All 11 rescore tests passed against the installed package with network
access blocked and no provider or ML-library imports. The shared fixture's
checkout script adds the project root to Python's import path; the validation
harness removed that entry before running tests and verified that every loaded
`rsi`/`rsilab` module came from `.venv` site-packages. The test log is
`work/rescore-framework-dist/installed-tests.log`.

Packaging alone does not validate remote candidate execution. Main subsequently
completed the 18 remote calibration checks, 176 reference audit, and all 368 saved
outcome rescoring. See [the completed correction](MBPP_RESCORE_V2.md). No cloud
job or training was launched by this package build.
