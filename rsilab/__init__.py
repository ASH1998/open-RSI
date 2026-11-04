"""Trusted, offline experiment records; importing rsilab never starts compute."""
from .core import (
    Agent, Decision, Environment, Evaluator, FrozenJSON, Manifest, Operator,
    PromotionGate, Provenance, RetainParentGate, RunResult, Score, Split, Task, digest, canonical_json,
)
from .comparison import compare
from .artifacts import artifact_manifest

__version__ = "0.1.2"
__all__ = [
    "Agent", "Decision", "Environment", "Evaluator", "FrozenJSON", "Manifest",
    "Operator", "PromotionGate", "Provenance", "RetainParentGate", "RunResult",
    "Score", "Split", "Task", "compare", "digest", "canonical_json", "artifact_manifest",
]
