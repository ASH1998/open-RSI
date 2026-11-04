"""Immutable records and extension contracts. These types do not provide isolation."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping, Protocol, Sequence


def _json_value(value: Any) -> Any:
    if isinstance(value, FrozenJSON):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Records require finite JSON values")


def canonical_json(value: Any) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _hash(value: str, name: str, length: int = 64) -> None:
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", value):
        raise ValueError(f"{name} must be an immutable {length}-character lowercase hex digest")


@dataclass(frozen=True, init=False)
class FrozenJSON:
    """Deep snapshot of a JSON object; access returns copies, never mutable internals."""
    _canonical: str

    def __init__(self, value: Mapping[str, Any]):
        if not isinstance(value, Mapping):
            raise ValueError("Expected a JSON object")
        object.__setattr__(self, "_canonical", canonical_json(value))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical)


class Split(str, Enum):
    TRAIN = "train"
    DEV = "dev"
    PROMOTION = "promotion"
    SEALED = "sealed"
    TEST = "test"  # Existing pilot label; not automatically a sealed protocol.


@dataclass(frozen=True)
class Agent:
    id: str
    model_id: str
    model_revision: str
    harness_sha256: str
    memory_sha256: str
    adapter_sha256: str | None = None

    def __post_init__(self):
        _text(self.id, "agent id")
        _text(self.model_id, "model id")
        _hash(self.model_revision, "model revision", 40)
        for name in ("harness_sha256", "memory_sha256", "adapter_sha256"):
            value = getattr(self, name)
            if value is not None or name != "adapter_sha256":
                _hash(value, name)


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    split: Split
    prompt: str
    trusted: FrozenJSON

    def __post_init__(self):
        for name in ("id", "family", "prompt"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "split", Split(self.split))
        if not isinstance(self.trusted, FrozenJSON):
            raise ValueError("trusted must be FrozenJSON")

    def agent_input(self) -> dict[str, str]:
        """Only this view is sent to the candidate; trusted data stays with the evaluator."""
        return {"id": self.id, "prompt": self.prompt}


@dataclass(frozen=True)
class Provenance:
    code_sha256: str
    data_sha256: str
    evaluator_sha256: str
    analysis_plan_sha256: str
    packages: FrozenJSON
    hardware: str

    def __post_init__(self):
        for name in ("code_sha256", "data_sha256", "evaluator_sha256", "analysis_plan_sha256"):
            _hash(getattr(self, name), name)
        if not isinstance(self.packages, FrozenJSON) or not self.packages.to_dict():
            raise ValueError("packages must record a nonempty installed package inventory")
        _text(self.hardware, "hardware")


@dataclass(frozen=True)
class Manifest:
    run_id: str
    agent: Agent
    tasks: tuple[Task, ...]
    seeds: tuple[int, ...]
    budget: FrozenJSON
    settings: FrozenJSON
    provenance: Provenance
    schema_version: int = 1

    def __post_init__(self):
        _text(self.run_id, "run id")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported manifest schema")
        if not isinstance(self.agent, Agent) or not isinstance(self.provenance, Provenance):
            raise ValueError("Manifest requires typed agent and provenance")
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "seeds", tuple(self.seeds))
        if not self.tasks or any(not isinstance(task, Task) for task in self.tasks):
            raise ValueError("Manifest needs typed tasks")
        if len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Duplicate task IDs")
        families: dict[str, Split] = {}
        for task in self.tasks:
            if task.family in families and families[task.family] != task.split:
                raise ValueError("Task family crosses splits")
            families[task.family] = task.split
        if (not self.seeds or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in self.seeds)
                or len(set(self.seeds)) != len(self.seeds)):
            raise ValueError("Seeds must be distinct integers in 0..2**31-1")
        for name in ("budget", "settings"):
            value = getattr(self, name)
            if not isinstance(value, FrozenJSON) or not value.to_dict():
                raise ValueError(f"{name} must be a nonempty FrozenJSON object")

    @property
    def sha256(self) -> str:
        return digest(self)

    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Manifest:
        data = dict(value)
        data["agent"] = Agent(**data["agent"])
        data["tasks"] = tuple(Task(**{**task, "trusted": FrozenJSON(task["trusted"])}) for task in data["tasks"])
        data["provenance"] = Provenance(**{**data["provenance"], "packages": FrozenJSON(data["provenance"]["packages"])})
        for name in ("budget", "settings"):
            data[name] = FrozenJSON(data[name])
        return cls(**data)


@dataclass(frozen=True)
class Score:
    value: float
    details: FrozenJSON

    def __post_init__(self):
        if type(self.value) not in (int, float) or not math.isfinite(self.value):
            raise ValueError("Score must be finite")
        if not isinstance(self.details, FrozenJSON):
            raise ValueError("Score details must be FrozenJSON")


@dataclass(frozen=True)
class RunResult:
    run_id: str
    agent_id: str
    task_id: str
    seed: int
    status: str
    evidence: FrozenJSON
    score: float | None = None
    tokens: int = 0
    elapsed_seconds: float = 0.0
    cost_usd: float | None = None

    def __post_init__(self):
        for name in ("run_id", "agent_id", "task_id"):
            _text(getattr(self, name), name)
        if self.status not in {"completed", "failed", "incomplete"}:
            raise ValueError("Unknown result status")
        if not isinstance(self.evidence, FrozenJSON):
            raise ValueError("evidence must be FrozenJSON")
        if type(self.seed) is not int or not 0 <= self.seed < 2**31:
            raise ValueError("Invalid seed")
        if type(self.tokens) is not int or self.tokens < 0:
            raise ValueError("Invalid token count")
        for name in ("score", "elapsed_seconds", "cost_usd"):
            value = getattr(self, name)
            if value is None and name != "elapsed_seconds":
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or (name != "score" and value < 0):
                raise ValueError(f"Invalid {name}")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RunResult:
        return cls(**{**value, "evidence": FrozenJSON(value["evidence"])})


class Environment(Protocol):
    def tasks(self, split: Split) -> Sequence[Task]: ...
    def run(self, task: Task, patch: str, seed: int) -> RunResult: ...


class Evaluator(Protocol):
    def score(self, task: Task, result: RunResult) -> Score: ...


class Operator(Protocol):
    def propose(self, agent: Agent, ledger: Sequence[RunResult]) -> Sequence[Agent]: ...


@dataclass(frozen=True)
class Decision:
    selected_agent_id: str
    promoted: bool
    reason: str


class PromotionGate(Protocol):
    def decide(self, parent: Agent, candidates: Sequence[Agent]) -> Decision: ...


class RetainParentGate:
    """Default gate: reported score gains alone never authorize promotion."""
    def decide(self, parent: Agent, candidates: Sequence[Agent]) -> Decision:
        return Decision(parent.id, False, "Retain parent: no validated, preregistered promotion gate configured.")
