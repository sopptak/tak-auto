"""Load and validate the versioned Agent and Tool registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import Agent, TOOL_STATUSES, Task, Tool, ToolSelection


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_PATH = ROOT / "data" / "tak_ai_agents.json"
DEFAULT_TOOL_PATH = ROOT / "data" / "tak_ai_tools.json"
EXPECTED_AGENT_IDS = tuple(f"AGENT-{index:02d}" for index in range(1, 13))
EXPECTED_TOOL_IDS = tuple(f"TOOL-{index:02d}" for index in range(1, 17))
EXPECTED_AGENT_DEPARTMENTS = {
    "AGENT-01": "Executive",
    "AGENT-02": "R&D",
    "AGENT-03": "Market Analysis",
    "AGENT-04": "Content Strategy",
    "AGENT-05": "Content",
    "AGENT-06": "Shorts Production",
    "AGENT-07": "Global Localization",
    "AGENT-08": "Marketing",
    "AGENT-09": "PR & Distribution",
    "AGENT-10": "Engineering",
    "AGENT-11": "Operations & Automation",
    "AGENT-12": "Data & Performance",
}
EXPECTED_AGENT_ROLES = {
    "AGENT-01": "AI General Manager",
    "AGENT-02": "소재발굴팀장",
    "AGENT-03": "시장·사례 분석가",
    "AGENT-04": "콘텐츠 전략가",
    "AGENT-05": "콘텐츠 작가",
    "AGENT-06": "쇼츠 제작팀",
    "AGENT-07": "글로벌 콘텐츠팀",
    "AGENT-08": "마케팅팀",
    "AGENT-09": "홍보·게시팀",
    "AGENT-10": "개발팀",
    "AGENT-11": "운영·자동화팀",
    "AGENT-12": "데이터·성과분석팀",
}
TOOL_CATEGORIES = frozenset(
    {"research", "image", "video", "audio", "distribution", "operations", "automation", "media"}
)

TASK_ROUTES = {
    "executive_coordination": "AGENT-01",
    "rnd_discovery": "AGENT-03",
    "rnd_analysis": "AGENT-03",
    "market_case_analysis": "AGENT-03",
    "idea_strategy": "AGENT-04",
    "content_writing": "AGENT-05",
    "shorts_production": "AGENT-06",
    "localization": "AGENT-07",
    "marketing_strategy": "AGENT-08",
    "publish_preparation": "AGENT-09",
    "engineering": "AGENT-10",
    "automation": "AGENT-11",
    "performance_analysis": "AGENT-12",
}

TASK_CAPABILITIES = {
    "rnd_discovery": ("web_research",),
    "rnd_analysis": ("web_research",),
    "market_case_analysis": ("web_research", "social_analytics"),
    "shorts_production": ("image_generation", "video_generation", "video_editing", "audio_generation"),
    "localization": ("audio_generation", "video_editing"),
    "marketing_strategy": ("social_analytics", "workflow_automation"),
    "publish_preparation": ("social_publishing",),
    "automation": ("workflow_automation",),
    "performance_analysis": ("social_analytics",),
}

HUMAN_APPROVAL_ACTIONS = frozenset(
    {
        "threads_publish", "actual_threads_publish", "youtube_upload", "actual_youtube_upload",
        "external_write", "external_site_write", "paid_api", "paid_api_call", "incur_cost",
        "cost_incurred", "ad_campaign", "account_permission_change", "secret_change",
        "secret_read", "destructive_data_change", "irreversible_data_change",
    }
)


class RegistryError(ValueError):
    """Raised when registry JSON is invalid or inconsistent."""


def _load_json_list(path: Path | str) -> list[dict[str, Any]]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError(f"Registry를 읽을 수 없습니다: {target}") from error
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RegistryError(f"Registry는 객체 목록이어야 합니다: {target}")
    return payload


def validate_agent_registry(agents: Iterable[Agent]) -> tuple[Agent, ...]:
    records = tuple(agents)
    identifiers = [agent.agent_id for agent in records]
    if len(identifiers) != len(set(identifiers)):
        raise RegistryError("agent_id가 중복되었습니다.")
    if set(identifiers) != set(EXPECTED_AGENT_IDS) or len(records) != len(EXPECTED_AGENT_IDS):
        raise RegistryError("Agent Registry는 AGENT-01~AGENT-12를 정확히 한 번 포함해야 합니다.")
    known = set(identifiers)
    for agent in records:
        if agent.status != "ACTIVE" or not agent.responsibilities or not agent.role or not agent.mission:
            raise RegistryError(f"Agent 필수 값이 없거나 ACTIVE가 아닙니다: {agent.agent_id}")
        if (
            agent.department != EXPECTED_AGENT_DEPARTMENTS[agent.agent_id]
            or agent.role != EXPECTED_AGENT_ROLES[agent.agent_id]
        ):
            raise RegistryError(f"Agent department/role이 정의와 다릅니다: {agent.agent_id}")
        if set(agent.allowed_actions).intersection(agent.forbidden_actions):
            raise RegistryError(f"allowed/forbidden action이 충돌합니다: {agent.agent_id}")
        if not set(agent.upstream_agents + agent.downstream_agents).issubset(known):
            raise RegistryError(f"Agent graph가 알 수 없는 agent를 참조합니다: {agent.agent_id}")
        if agent.agent_id in agent.upstream_agents or agent.agent_id in agent.downstream_agents:
            raise RegistryError(f"Agent graph가 자기 자신을 참조합니다: {agent.agent_id}")
    return records


def load_agents(path: Path | str = DEFAULT_AGENT_PATH) -> tuple[Agent, ...]:
    try:
        return validate_agent_registry(Agent.from_mapping(item) for item in _load_json_list(path))
    except (TypeError, ValueError) as error:
        if isinstance(error, RegistryError):
            raise
        raise RegistryError(f"Agent Registry schema 오류: {error}") from error


def validate_tool_registry(tools: Iterable[Tool], agents: Iterable[Agent] | None = None) -> tuple[Tool, ...]:
    records = tuple(tools)
    identifiers = [tool.tool_id for tool in records]
    if len(identifiers) != len(set(identifiers)):
        raise RegistryError("tool_id가 중복되었습니다.")
    if set(identifiers) != set(EXPECTED_TOOL_IDS) or len(records) != len(EXPECTED_TOOL_IDS):
        raise RegistryError("Tool Registry는 TOOL-01~TOOL-16을 정확히 한 번 포함해야 합니다.")
    known_agents = {agent.agent_id for agent in (agents if agents is not None else load_agents())}
    for tool in records:
        if tool.status not in TOOL_STATUSES:
            raise RegistryError(f"지원하지 않는 Tool status입니다: {tool.tool_id}")
        if tool.category not in TOOL_CATEGORIES:
            raise RegistryError(f"지원하지 않는 Tool category입니다: {tool.tool_id}")
        if not tool.assigned_agents or not set(tool.assigned_agents).issubset(known_agents):
            raise RegistryError(f"Tool assigned_agents가 비었거나 잘못되었습니다: {tool.tool_id}")
        if not tool.capabilities:
            raise RegistryError(f"Tool capabilities가 비었습니다: {tool.tool_id}")
        if tool.status == "CANDIDATE" and tool.api_available is True:
            raise RegistryError(f"미연결 후보 Tool의 API를 확인된 상태로 표시할 수 없습니다: {tool.tool_id}")
    return records


def load_tools(
    path: Path | str = DEFAULT_TOOL_PATH, agents: Iterable[Agent] | None = None
) -> tuple[Tool, ...]:
    try:
        return validate_tool_registry(
            (Tool.from_mapping(item) for item in _load_json_list(path)), agents=agents
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, RegistryError):
            raise
        raise RegistryError(f"Tool Registry schema 오류: {error}") from error


def get_agent(agent_id: str, agents: Iterable[Agent] | None = None) -> Agent:
    found = next((agent for agent in (agents if agents is not None else load_agents()) if agent.agent_id == agent_id), None)
    if found is None:
        raise RegistryError(f"알 수 없는 agent_id입니다: {agent_id}")
    return found


def get_tool(tool_id: str, tools: Iterable[Tool] | None = None) -> Tool:
    found = next((tool for tool in (tools if tools is not None else load_tools()) if tool.tool_id == tool_id), None)
    if found is None:
        raise RegistryError(f"알 수 없는 tool_id입니다: {tool_id}")
    return found


def route_agent(task_type: str) -> str:
    try:
        return TASK_ROUTES[task_type]
    except KeyError as error:
        raise RegistryError(f"라우팅 규칙이 없는 task_type입니다: {task_type}") from error


def requires_human_approval(
    requested_actions: Iterable[str], assigned_agent: Agent | None = None
) -> bool:
    actions = {action.strip().lower() for action in requested_actions}
    return bool(actions.intersection(HUMAN_APPROVAL_ACTIONS)) or bool(
        assigned_agent and assigned_agent.human_approval_required
    )


def select_tools_for_task(
    task: Task,
    tools: Iterable[Tool] | None = None,
) -> tuple[ToolSelection, ...]:
    if not task.assigned_to:
        return ()
    agent = get_agent(task.assigned_to)
    required = set(task.required_capabilities or TASK_CAPABILITIES.get(task.task_type, ()))
    if not required:
        return ()
    candidates = tools if tools is not None else load_tools()
    return tuple(
        ToolSelection(
            tool_id=tool.tool_id,
            name=tool.name,
            status=tool.status,
            approval_required=task.approval_required or tool.approval_required,
            executable=False,
        )
        for tool in candidates
        if tool.status != "DISABLED"
        and task.assigned_to in tool.assigned_agents
        and required.intersection(tool.capabilities)
    )