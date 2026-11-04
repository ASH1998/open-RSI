# Using rsilab

`rsilab` records verified-learning experiments and compares results under matching controls. Its offline core needs Python 3.11+ and the standard library. Cloud execution is optional. There is no claim that installing it provides an agent capable of recursive self-improvement.

Version 0.4.0 adds category preflight and reference-evidence reuse. See
[release validation](FRAMEWORK.md#local-recovery-release-040) for the installed
checks and preserved earlier artifacts. No package has been published to PyPI.

Install from a checkout into your own project environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/rsilab --help
.venv/bin/python -I examples/offline_comparison.py
```

The example uses explicitly synthetic evidence. It demonstrates immutable identities, matched comparison and retaining the parent; it starts no compute and loads no credentials. For recorded evidence, use the manifest/CLI contracts in [FRAMEWORK.md](FRAMEWORK.md).

For optional integrations, install the corresponding extra (`.[modal]`, `.[tracking]`, or `.[data]`). Keep credentials in your project's environment. The core import never reads them. Project-specific `Workspace.stage()` currently enforces the research project's conservative $250/$25/$5 policy; it is not a universal billing service.

- [Portable Modal worker](PORTABLE_MODAL.md): explicit factory, immutable model revision and persistent remote storage.
- [Verified learning](LEARNING.md): preserve attempts, construct bounded repairs and select verified labels.
- [Successor measurement](SUCCESSOR_MEASUREMENT.md): distinguish solving more tasks from producing better students.
- [Dataset auditing](VERIFIED_DATA.md): independent tests and split separation.
- [Category preflight](PREFLIGHT.md): check explicit task labels and the exact
  first-N selection against independently reviewed categories before spending.
- [Reference reuse](REFERENCE_REUSE.md): replay pinned saved reference evidence
  and derive category-only task copies with explicit lineage.

For example, a category check uses the task records themselves:

```python
from rsilab.preflight import preflight_task_categories

tasks = [
    {"id": "a", "category": "collections"},
    {"id": "b", "category": "numeric"},
    {"id": "c", "category": "text"},
]
reviewed = {"a": "collections", "b": "numeric", "c": "text"}
summary = preflight_task_categories(
    tasks, first_n=3, min_categories=3, expected_categories=reviewed,
)
```

This check does not infer or repair labels. If reference calibration later
changes eligibility, check the resulting ordered pool again. Use
`rsilab.reference_reuse.reuse_reference_audits` only with independently pinned
source and evaluator identities. Reuse validates saved evidence; it does not
mean a historical experiment was rerun.

Use `rsilab.dataset_io.read_development_splits` to read only pinned train/validation Parquet files. This reader rejects test/prompt splits before decoding and checks source hashes first. A final evaluation requires its own explicitly authorized reader and frozen protocol.

Generated code must run in an isolated executor with authoritative tests outside its write scope. Offline score comparison trusts the supplied scoring evidence; it is not a sandbox or a substitute for verifier auditing.

Repository source is Apache-2.0 licensed; see [LICENSE](../LICENSE). Model weights, datasets and external dependencies keep their own licenses. Model weights, datasets, credentials and experiment outputs are not bundled in the wheel. Package publication status and tested capabilities are recorded in the release notes; do not infer a PyPI release from a version number.
