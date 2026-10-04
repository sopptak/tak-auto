"""Append-preserving JSON Task storage and guarded lifecycle operations."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from .models import TASK_PRIORITIES, TASK_STATUSES, Task, utc_now
from .registry import RegistryError, get_agent, requires_human_approval, route_agent


DEFAULT_TASK_PATH = Path(__file__).resolve().parents[1] / "data" / "tak_ai_tasks.json"
TASK_TRANSITIONS = {
    "PENDING": {"ASSIGNED", "WAITING_APPROVAL", "CANCELLED"},
    "ASSIGNED": {"RUNNING", "WAITING_INPUT", "WAITING_APPROVAL", "CANCELLED"},
    "RUNNING": {"WAITING_INPUT", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"},
    "WAITING_INPUT": {"ASSIGNED", "RUNNING", "CANCELLED"},
    "WAITING_APPROVAL": {"ASSIGNED", "CANCELLED"},
    "FAILED": {"ASSIGNED", "RUNNING", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


class TaskStoreError(ValueError):
    """Raised when Task data or a lifecycle transition is invalid."""


def load_tasks(path: Path | str = DEFAULT_TASK_PATH) -> list[Task]:
    target = Path(path)
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaskStoreError(f"Task 저장소를 읽을 수 없습니다: {target}") from error
    if not isinstance(payload, list):
        raise TaskStoreError("Task 저장소 최상위 값은 목록이어야 합니다.")
    try:
        tasks = [Task.from_mapping(item) for item in payload]
        identifiers = {task.task_id for task in tasks}
        if len(identifiers) != len(tasks):
            raise TaskStoreError("task_id가 중복되었습니다.")
        for task in tasks:
            get_agent(task.created_by)
            if task.assigned_to:
                get_agent(task.assigned_to)
            if task.parent_task_id and task.parent_task_id not in identifiers:
                raise TaskStoreError(f"parent_task_id가 저장소에 없습니다: {task.parent_task_id}")
        return tasks
    except (TypeError, ValueError) as error:
        if isinstance(error, TaskStoreError):
            raise
        raise TaskStoreError(f"Task 저장소 schema 오류: {error}") from error


def _save(tasks: list[Task], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump([task.to_dict() for task in tasks], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def get_task(task_id: str, path: Path | str = DEFAULT_TASK_PATH) -> Task:
    task = next((item for item in load_tasks(path) if item.task_id == task_id), None)
    if task is None:
        raise KeyError(f"Task를 찾을 수 없습니다: {task_id}")
    return task


def create_task(
    task_type: str,
    *,
    created_by: str = "AGENT-01",
    assigned_to: str = "",
    priority: str = "NORMAL",
    input_refs: tuple[str, ...] | list[str] = (),
    parent_task_id: str | None = None,
    required_capabilities: tuple[str, ...] | list[str] = (),
    requested_actions: tuple[str, ...] | list[str] = (),
    path: Path | str = DEFAULT_TASK_PATH,
) -> Task:
    tasks = load_tasks(path)
    get_agent(created_by)
    if assigned_to:
        agent = get_agent(assigned_to)
        department = agent.department
    else:
        agent = None
        department = "Unassigned"
    if priority not in TASK_PRIORITIES:
        raise TaskStoreError(f"priority는 {TASK_PRIORITIES} 중 하나여야 합니다.")
    if parent_task_id and not any(task.task_id == parent_task_id for task in tasks):
        raise TaskStoreError(f"parent_task_id가 저장소에 없습니다: {parent_task_id}")
    try:
        route_agent(task_type)
    except RegistryError as error:
        raise TaskStoreError(str(error)) from error
    approval_required = requires_human_approval(requested_actions, agent)
    approval_status = "PENDING" if approval_required else "NOT_REQUIRED"
    status = "WAITING_APPROVAL" if assigned_to and approval_required else (
        "ASSIGNED" if assigned_to else "PENDING"
    )
    task = Task(
        task_id=f"task-{uuid4().hex[:12]}",
        created_at=utc_now(),
        created_by=created_by,
        assigned_to=assigned_to,
        department=department,
        task_type=task_type,
        priority=priority,
        input_refs=tuple(input_refs),
        output_refs=(),
        status=status,
        approval_required=approval_required,
        approval_status=approval_status,
        parent_task_id=parent_task_id,
        retry_count=0,
        result_summary="",
        error="",
        required_capabilities=tuple(required_capabilities),
        requested_actions=tuple(requested_actions),
    )
    tasks.append(task)
    _save(tasks, path)
    return task


def route_task(task_id: str, path: Path | str = DEFAULT_TASK_PATH) -> Task:
    tasks = load_tasks(path)
    for index, task in enumerate(tasks):
        if task.task_id != task_id:
            continue
        if task.status not in {"PENDING", "ASSIGNED", "WAITING_INPUT", "WAITING_APPROVAL", "FAILED"}:
            raise TaskStoreError(f"현재 상태의 Task는 라우팅할 수 없습니다: {task.status}")
        agent_id = route_agent(task.task_type)
        agent = get_agent(agent_id)
        approval_required = requires_human_approval(task.requested_actions, agent)
        approval_status = task.approval_status
        if approval_required and approval_status == "NOT_REQUIRED":
            approval_status = "PENDING"
        if not approval_required:
            approval_status = "NOT_REQUIRED"
        status = "WAITING_APPROVAL" if approval_required and approval_status != "APPROVED" else "ASSIGNED"
        updated = replace(
            task,
            assigned_to=agent.agent_id,
            department=agent.department,
            status=status,
            approval_required=approval_required,
            approval_status=approval_status,
            retry_count=task.retry_count + (1 if task.status == "FAILED" else 0),
        )
        tasks[index] = updated
        _save(tasks, path)
        return updated
    raise KeyError(f"Task를 찾을 수 없습니다: {task_id}")


def set_task_approval(
    task_id: str, decision: str, path: Path | str = DEFAULT_TASK_PATH
) -> Task:
    normalized = decision.upper()
    if normalized not in {"APPROVED", "REJECTED"}:
        raise TaskStoreError("approval decision은 APPROVED 또는 REJECTED여야 합니다.")
    tasks = load_tasks(path)
    for index, task in enumerate(tasks):
        if task.task_id != task_id:
            continue
        if not task.approval_required or task.approval_status != "PENDING":
            raise TaskStoreError("현재 승인 대기 중인 approval-required Task가 아닙니다.")
        updated = replace(
            task,
            approval_status=normalized,
            status="ASSIGNED" if normalized == "APPROVED" and task.assigned_to else (
                "PENDING" if normalized == "APPROVED" else "CANCELLED"
            ),
        )
        tasks[index] = updated
        _save(tasks, path)
        return updated
    raise KeyError(f"Task를 찾을 수 없습니다: {task_id}")


def set_task_status(
    task_id: str,
    status: str,
    *,
    result_summary: str | None = None,
    error: str | None = None,
    output_refs: tuple[str, ...] | list[str] | None = None,
    path: Path | str = DEFAULT_TASK_PATH,
) -> Task:
    if status not in TASK_STATUSES:
        raise TaskStoreError(f"status는 {TASK_STATUSES} 중 하나여야 합니다.")
    tasks = load_tasks(path)
    for index, task in enumerate(tasks):
        if task.task_id != task_id:
            continue
        if status not in TASK_TRANSITIONS[task.status]:
            raise TaskStoreError(f"허용되지 않는 Task 상태 전이입니다: {task.status} -> {status}")
        if status == "ASSIGNED" and task.approval_required and task.approval_status != "APPROVED":
            raise TaskStoreError("승인 대기 Task는 approval API에서 승인된 뒤에만 할당할 수 있습니다.")
        if status in {"ASSIGNED", "RUNNING", "WAITING_INPUT"} and not task.assigned_to:
            raise TaskStoreError("라우팅되지 않은 Task는 할당/실행 상태가 될 수 없습니다.")
        if status in {"RUNNING", "COMPLETED"} and task.approval_required and task.approval_status != "APPROVED":
            raise TaskStoreError("Human approval 완료 전에는 Task를 실행하거나 완료할 수 없습니다.")
        if status == "WAITING_APPROVAL" and (
            not task.approval_required or task.approval_status != "PENDING"
        ):
            raise TaskStoreError("approval-required pending 상태의 Task만 승인 대기로 전환할 수 있습니다.")
        updated = replace(
            task,
            status=status,
            retry_count=task.retry_count + (1 if task.status == "FAILED" and status in {"ASSIGNED", "RUNNING"} else 0),
            result_summary=task.result_summary if result_summary is None else result_summary,
            error=task.error if error is None else error,
            output_refs=task.output_refs if output_refs is None else tuple(output_refs),
        )
        tasks[index] = updated
        _save(tasks, path)
        return updated
    raise KeyError(f"Task를 찾을 수 없습니다: {task_id}")


def task_to_agent_route(task: Task) -> str:
    return route_agent(task.task_type)