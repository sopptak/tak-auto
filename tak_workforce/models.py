"""Typed contracts for the TAK AUTO AI workforce, tools, tasks, and DNA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


TASK_STATUSES = (
    "PENDING", "ASSIGNED", "RUNNING", "WAITING_INPUT", "WAITING_APPROVAL",
    "COMPLETED", "FAILED", "CANCELLED",
)
APPROVAL_STATUSES = ("NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED")
TASK_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")
TOOL_STATUSES = ("CANDIDATE", "EVALUATING", "CONNECTED", "DISABLED")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, name: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name}은 문자열이어야 합니다.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name}은 필수입니다.")
    return value


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name}은 문자열 목록이어야 합니다.")
    return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name}은 boolean이어야 합니다.")
    return value


def _optional_bool(value: Any, name: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{name}은 boolean 또는 null이어야 합니다.")
    return value


def _timestamp(value: Any, name: str) -> str:
    text = _text(value, name, required=True)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name}은 ISO 8601 시각이어야 합니다.") from error
    return text


@dataclass(frozen=True)
class Agent:
    agent_id: str
    name: str
    department: str
    role: str
    mission: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    upstream_agents: tuple[str, ...]
    downstream_agents: tuple[str, ...]
    human_approval_required: bool
    status: str
    version: str
    recommended_internal_resources: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Agent":
        return cls(
            agent_id=_text(data.get("agent_id"), "agent_id", required=True),
            name=_text(data.get("name"), "name", required=True),
            department=_text(data.get("department"), "department", required=True),
            role=_text(data.get("role"), "role", required=True),
            mission=_text(data.get("mission"), "mission", required=True),
            responsibilities=_text_tuple(data.get("responsibilities"), "responsibilities"),
            inputs=_text_tuple(data.get("inputs"), "inputs"),
            outputs=_text_tuple(data.get("outputs"), "outputs"),
            allowed_actions=_text_tuple(data.get("allowed_actions"), "allowed_actions"),
            forbidden_actions=_text_tuple(data.get("forbidden_actions"), "forbidden_actions"),
            upstream_agents=_text_tuple(data.get("upstream_agents"), "upstream_agents"),
            downstream_agents=_text_tuple(data.get("downstream_agents"), "downstream_agents"),
            human_approval_required=_bool(data.get("human_approval_required"), "human_approval_required"),
            status=_text(data.get("status"), "status", required=True),
            version=_text(data.get("version"), "version", required=True),
            recommended_internal_resources=_text_tuple(
                data.get("recommended_internal_resources"), "recommended_internal_resources"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "department": self.department,
            "role": self.role,
            "mission": self.mission,
            "responsibilities": list(self.responsibilities),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "allowed_actions": list(self.allowed_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "upstream_agents": list(self.upstream_agents),
            "downstream_agents": list(self.downstream_agents),
            "human_approval_required": self.human_approval_required,
            "status": self.status,
            "version": self.version,
            "recommended_internal_resources": list(self.recommended_internal_resources),
        }


@dataclass(frozen=True)
class Tool:
    tool_id: str
    name: str
    category: str
    provider: str
    purpose: str
    assigned_agents: tuple[str, ...]
    input_type: str
    output_type: str
    capabilities: tuple[str, ...]
    api_available: bool | None
    browser_required: bool | None
    cost_type: str
    approval_required: bool
    status: str
    version: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Tool":
        return cls(
            tool_id=_text(data.get("tool_id"), "tool_id", required=True),
            name=_text(data.get("name"), "name", required=True),
            category=_text(data.get("category"), "category", required=True),
            provider=_text(data.get("provider"), "provider", required=True),
            purpose=_text(data.get("purpose"), "purpose", required=True),
            assigned_agents=_text_tuple(data.get("assigned_agents"), "assigned_agents"),
            input_type=_text(data.get("input_type"), "input_type", required=True),
            output_type=_text(data.get("output_type"), "output_type", required=True),
            capabilities=_text_tuple(data.get("capabilities"), "capabilities"),
            api_available=_optional_bool(data.get("api_available"), "api_available"),
            browser_required=_optional_bool(data.get("browser_required"), "browser_required"),
            cost_type=_text(data.get("cost_type"), "cost_type", required=True),
            approval_required=_bool(data.get("approval_required"), "approval_required"),
            status=_text(data.get("status"), "status", required=True),
            version=_text(data.get("version"), "version", required=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "category": self.category,
            "provider": self.provider,
            "purpose": self.purpose,
            "assigned_agents": list(self.assigned_agents),
            "input_type": self.input_type,
            "output_type": self.output_type,
            "capabilities": list(self.capabilities),
            "api_available": self.api_available,
            "browser_required": self.browser_required,
            "cost_type": self.cost_type,
            "approval_required": self.approval_required,
            "status": self.status,
            "version": self.version,
        }


@dataclass(frozen=True)
class Task:
    task_id: str
    created_at: str
    created_by: str
    assigned_to: str
    department: str
    task_type: str
    priority: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    status: str
    approval_required: bool
    approval_status: str
    parent_task_id: str | None
    retry_count: int
    result_summary: str
    error: str
    required_capabilities: tuple[str, ...] = ()
    requested_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _timestamp(self.created_at, "created_at")
        for name in ("task_id", "created_by", "task_type", "priority", "department"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name}은 필수입니다.")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"status는 {TASK_STATUSES} 중 하나여야 합니다.")
        if self.approval_status not in APPROVAL_STATUSES:
            raise ValueError(f"approval_status는 {APPROVAL_STATUSES} 중 하나여야 합니다.")
        if self.priority not in TASK_PRIORITIES:
            raise ValueError(f"priority는 {TASK_PRIORITIES} 중 하나여야 합니다.")
        if not isinstance(self.approval_required, bool):
            raise ValueError("approval_required는 boolean이어야 합니다.")
        if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int):
            raise ValueError("retry_count는 0 이상의 정수여야 합니다.")
        if self.retry_count < 0:
            raise ValueError("retry_count는 0 이상의 정수여야 합니다.")
        if self.approval_required != (self.approval_status != "NOT_REQUIRED"):
            raise ValueError("approval_required와 approval_status가 일치하지 않습니다.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Task":
        if not isinstance(data, Mapping):
            raise ValueError("Task 입력은 객체여야 합니다.")
        return cls(
            task_id=_text(data.get("task_id"), "task_id", required=True),
            created_at=_timestamp(data.get("created_at"), "created_at"),
            created_by=_text(data.get("created_by"), "created_by", required=True),
            assigned_to=_text(data.get("assigned_to", ""), "assigned_to"),
            department=_text(data.get("department", "Unassigned"), "department", required=True),
            task_type=_text(data.get("task_type"), "task_type", required=True),
            priority=_text(data.get("priority", "NORMAL"), "priority", required=True),
            input_refs=_text_tuple(data.get("input_refs"), "input_refs"),
            output_refs=_text_tuple(data.get("output_refs"), "output_refs"),
            status=_text(data.get("status", "PENDING"), "status", required=True),
            approval_required=_bool(data.get("approval_required", False), "approval_required"),
            approval_status=_text(
                data.get("approval_status", "NOT_REQUIRED"), "approval_status", required=True
            ),
            parent_task_id=(
                _text(data["parent_task_id"], "parent_task_id")
                if data.get("parent_task_id") is not None
                else None
            ),
            retry_count=data.get("retry_count", 0),
            result_summary=_text(data.get("result_summary", ""), "result_summary"),
            error=_text(data.get("error", ""), "error"),
            required_capabilities=_text_tuple(data.get("required_capabilities"), "required_capabilities"),
            requested_actions=_text_tuple(data.get("requested_actions"), "requested_actions"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "department": self.department,
            "task_type": self.task_type,
            "priority": self.priority,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "status": self.status,
            "approval_required": self.approval_required,
            "approval_status": self.approval_status,
            "parent_task_id": self.parent_task_id,
            "retry_count": self.retry_count,
            "result_summary": self.result_summary,
            "error": self.error,
            "required_capabilities": list(self.required_capabilities),
            "requested_actions": list(self.requested_actions),
        }


@dataclass(frozen=True)
class ToolSelection:
    tool_id: str
    name: str
    status: str
    approval_required: bool
    executable: bool = False


@dataclass(frozen=True)
class ContentDNA:
    content_id: str
    platform: str | None = None
    language: str | None = None
    format: str | None = None
    hook_type: str | None = None
    structure_type: str | None = None
    length: str | None = None
    pacing: str | None = None
    information_density: str | None = None
    question_usage: bool | None = None
    controversy: bool | None = None
    storytelling: bool | None = None
    how_to: bool | None = None
    timeline: bool | None = None
    listicle: bool | None = None
    case_study: bool | None = None
    before_after: bool | None = None
    curiosity: bool | None = None
    emotional_trigger: str | None = None
    cta_type: str | None = None

    def __post_init__(self) -> None:
        _text(self.content_id, "content_id", required=True)
        for name in ("platform", "language", "format", "hook_type", "structure_type", "length", "pacing", "information_density", "emotional_trigger", "cta_type"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        for name in ("question_usage", "controversy", "storytelling", "how_to", "timeline", "listicle", "case_study", "before_after", "curiosity"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name}은 boolean 또는 null이어야 합니다.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContentDNA":
        if not isinstance(data, Mapping):
            raise ValueError("ContentDNA 입력은 객체여야 합니다.")
        text_fields = (
            "platform", "language", "format", "hook_type", "structure_type", "length", "pacing",
            "information_density", "emotional_trigger", "cta_type",
        )
        bool_fields = (
            "question_usage", "controversy", "storytelling", "how_to", "timeline", "listicle",
            "case_study", "before_after", "curiosity",
        )
        values = {name: (_text(data[name], name) if data.get(name) is not None else None) for name in text_fields}
        values.update({name: _optional_bool(data.get(name), name) for name in bool_fields})
        return cls(content_id=_text(data.get("content_id"), "content_id", required=True), **values)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class MarketingDNA:
    content_id: str
    platform: str | None = None
    language: str | None = None
    curiosity_hook: bool | None = None
    discovery: bool | None = None
    click: bool | None = None
    share: bool | None = None
    comment: bool | None = None
    conversion: bool | None = None
    free_trial: bool | None = None
    product_connection: bool | None = None
    community_spread: bool | None = None
    cta: str | None = None
    funnel_stage: str | None = None

    def __post_init__(self) -> None:
        _text(self.content_id, "content_id", required=True)
        for name in ("platform", "language", "cta", "funnel_stage"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)
        for name in ("curiosity_hook", "discovery", "click", "share", "comment", "conversion", "free_trial", "product_connection", "community_spread"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name}은 boolean 또는 null이어야 합니다.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MarketingDNA":
        if not isinstance(data, Mapping):
            raise ValueError("MarketingDNA 입력은 객체여야 합니다.")
        bool_fields = (
            "curiosity_hook", "discovery", "click", "share", "comment", "conversion", "free_trial",
            "product_connection", "community_spread",
        )
        values = {name: _optional_bool(data.get(name), name) for name in bool_fields}
        for name in ("platform", "language", "cta", "funnel_stage"):
            values[name] = _text(data[name], name) if data.get(name) is not None else None
        return cls(content_id=_text(data.get("content_id"), "content_id", required=True), **values)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}