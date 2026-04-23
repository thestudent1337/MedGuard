from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Principal:
    id: str
    name: str
    role: str
    linked_patient_id: str | None = None
    authorized_patients: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolCall:
    tool: str
    raw_message: str
    target_patient_id: str | None = None
    scope: str = "single"
    requested_fields: list[str] = field(default_factory=list)
    updates: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    is_write: bool = False
    confidence: float = 0.5
    planner_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MonitorResult:
    risk_level: str
    score: int
    attack_type: str
    reasons: list[str]
    recommended_action: str
    source: str = "heuristic"
    heuristic_score: int | None = None
    llm_score: int | None = None
    llm_used: bool = False
    llm_model: str | None = None
    llm_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PolicyDecision:
    action: str
    user_message: str
    should_log: bool
    should_alert: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionEvent:
    actor: str
    message: str
    tool: str
    decision: str
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
