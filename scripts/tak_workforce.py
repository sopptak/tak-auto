#!/usr/bin/env python3
"""Inspect workforce registries and manage approval-gated local Tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_workforce import (
    DEFAULT_TASK_PATH,
    TASK_PRIORITIES,
    TASK_ROUTES,
    TASK_STATUSES,
    RegistryError,
    TaskStoreError,
    create_task,
    get_agent,
    get_task,
    get_tool,
    load_agents,
    load_tasks,
    load_tools,
    route_task,
    select_tools_for_task,
    set_task_approval,
    set_task_status,
)


def _json(record: Any) -> None:
    data = record.to_dict() if hasattr(record, "to_dict") else record.__dict__
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TAK AUTO AI Workforce + Tool Registry")
    parser.add_argument("--task-store", type=Path, default=DEFAULT_TASK_PATH, help="Task JSON 저장 경로")
    commands = parser.add_subparsers(dest="group", required=True)

    agents = commands.add_parser("agent", help="AI Agent Registry")
    agent_commands = agents.add_subparsers(dest="action", required=True)
    agent_commands.add_parser("list", help="12명 Agent 목록")
    agent_show = agent_commands.add_parser("show", help="Agent 상세 정보")
    agent_show.add_argument("agent_id")

    tools = commands.add_parser("tool", help="Tool Registry")
    tool_commands = tools.add_subparsers(dest="action", required=True)
    tool_commands.add_parser("list", help="16개 후보 도구 목록")
    tool_show = tool_commands.add_parser("show", help="도구 상세 정보")
    tool_show.add_argument("tool_id")
    tool_select = tool_commands.add_parser("select", help="Task에 맞는 후보 도구 조회(실행하지 않음)")
    tool_select.add_argument("task_id")

    tasks = commands.add_parser("task", help="Task Contract and approval lifecycle")
    task_commands = tasks.add_subparsers(dest="action", required=True)
    task_commands.add_parser("list", help="Task 목록")
    task_show = task_commands.add_parser("show", help="Task 상세")
    task_show.add_argument("task_id")
    task_create = task_commands.add_parser("create", help="라우팅 대기 Task 생성")
    task_create.add_argument("--type", dest="task_type", choices=tuple(TASK_ROUTES), required=True)
    task_create.add_argument("--created-by", default="AGENT-01")
    task_create.add_argument("--assigned-to", default="")
    task_create.add_argument("--priority", choices=TASK_PRIORITIES, default="NORMAL")
    task_create.add_argument("--input-ref", action="append", default=[])
    task_create.add_argument("--parent-task-id")
    task_create.add_argument("--capability", action="append", default=[])
    task_create.add_argument("--action", dest="requested_actions", action="append", default=[])
    task_route = task_commands.add_parser("route", help="task_type에 지정된 Agent로 라우팅")
    task_route.add_argument("task_id")
    task_status = task_commands.add_parser("status", help="Task 상태 변경 및 실행 결과 기록")
    task_status.add_argument("task_id")
    task_status.add_argument("--status", choices=TASK_STATUSES, required=True)
    task_status.add_argument("--summary")
    task_status.add_argument("--error")
    task_status.add_argument("--output-ref", action="append")
    task_approval = task_commands.add_parser("approval", help="승인 대기 Task에 사람의 결정 기록")
    task_approval.add_argument("task_id")
    task_approval.add_argument("--decision", choices=("APPROVED", "REJECTED"), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.group == "agent":
            agents = load_agents()
            if args.action == "list":
                for agent in agents:
                    print(f"{agent.agent_id} | {agent.department} | {agent.name} | {agent.role} | {agent.status}")
            else:
                _json(get_agent(args.agent_id, agents))
        elif args.group == "tool":
            tools = load_tools()
            if args.action == "list":
                for tool in tools:
                    print(
                        f"{tool.tool_id} | {tool.category} | {tool.name} | {tool.status} | "
                        f"approval={'yes' if tool.approval_required else 'no'}"
                    )
            elif args.action == "show":
                _json(get_tool(args.tool_id, tools))
            else:
                task = get_task(args.task_id, args.task_store)
                selections = select_tools_for_task(task, tools)
                if not selections:
                    print("적합한 후보 도구가 없습니다.")
                for selection in selections:
                    print(
                        f"{selection.tool_id} | {selection.name} | {selection.status} | "
                        f"approval={'yes' if selection.approval_required else 'no'} | executable=no"
                    )
        elif args.group == "task":
            if args.action == "list":
                for task in load_tasks(args.task_store):
                    assigned = task.assigned_to or "unassigned"
                    print(
                        f"{task.task_id} | {task.status} | {task.task_type} | {assigned} | "
                        f"approval={task.approval_status}"
                    )
            elif args.action == "show":
                _json(get_task(args.task_id, args.task_store))
            elif args.action == "create":
                task = create_task(
                    args.task_type,
                    created_by=args.created_by,
                    assigned_to=args.assigned_to,
                    priority=args.priority,
                    input_refs=args.input_ref,
                    parent_task_id=args.parent_task_id,
                    required_capabilities=args.capability,
                    requested_actions=args.requested_actions,
                    path=args.task_store,
                )
                print(f"Task 생성: {task.task_id} | {task.status} | approval={task.approval_status}")
            elif args.action == "route":
                task = route_task(args.task_id, args.task_store)
                print(
                    f"Task 라우팅: {task.task_id} -> {task.assigned_to} | {task.status} | "
                    f"approval={task.approval_status}"
                )
            elif args.action == "status":
                task = set_task_status(
                    args.task_id,
                    args.status,
                    result_summary=args.summary,
                    error=args.error,
                    output_refs=args.output_ref,
                    path=args.task_store,
                )
                print(f"{task.task_id}: {task.status}")
            else:
                task = set_task_approval(args.task_id, args.decision, args.task_store)
                print(f"{task.task_id}: approval={task.approval_status}, status={task.status}")
        return 0
    except (OSError, RegistryError, TaskStoreError, ValueError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())