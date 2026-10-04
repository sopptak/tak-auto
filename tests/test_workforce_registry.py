import json
from pathlib import Path
import tempfile
import unittest

from tak_workforce.models import Task
from tak_workforce.registry import (
    EXPECTED_AGENT_IDS,
    EXPECTED_TOOL_IDS,
    HUMAN_APPROVAL_ACTIONS,
    RegistryError,
    load_agents,
    load_tools,
    requires_human_approval,
    route_agent,
    select_tools_for_task,
    validate_agent_registry,
    validate_tool_registry,
)


class WorkforceRegistryTests(unittest.TestCase):
    def test_loads_exact_12_agents_with_valid_graph_and_actions(self):
        agents = load_agents()
        self.assertEqual(len(agents), 12)
        self.assertEqual({agent.agent_id for agent in agents}, set(EXPECTED_AGENT_IDS))
        for agent in agents:
            self.assertTrue(agent.department)
            self.assertTrue(agent.role)
            self.assertTrue(agent.responsibilities)
            self.assertFalse(set(agent.allowed_actions) & set(agent.forbidden_actions))

    def test_registry_rejects_missing_or_duplicate_agent_ids(self):
        agents = load_agents()
        with self.assertRaises(RegistryError):
            validate_agent_registry(agents[:-1])
        with self.assertRaises(RegistryError):
            validate_agent_registry((*agents[:-1], agents[0]))
        invalid_role = type(agents[0])(**{**agents[0].__dict__, "role": "Other"})
        with self.assertRaises(RegistryError):
            validate_agent_registry((invalid_role, *agents[1:]))

    def test_loads_exact_16_candidate_tools_and_valid_agent_assignments(self):
        agents = load_agents()
        tools = load_tools(agents=agents)
        self.assertEqual(len(tools), 16)
        self.assertEqual({tool.tool_id for tool in tools}, set(EXPECTED_TOOL_IDS))
        self.assertEqual({tool.status for tool in tools}, {"CANDIDATE"})
        self.assertTrue(all(tool.approval_required for tool in tools))
        self.assertTrue(all(tool.api_available is None for tool in tools))
        global_tools = {tool.tool_id for tool in tools if "AGENT-07" in tool.assigned_agents}
        self.assertTrue({"TOOL-04", "TOOL-05", "TOOL-06", "TOOL-07", "TOOL-15", "TOOL-16"}.issubset(global_tools))

    def test_tool_registry_rejects_unknown_agent_assignment(self):
        tools = list(load_tools())
        tools[0] = type(tools[0])(**{**tools[0].__dict__, "assigned_agents": ("AGENT-99",)})
        with self.assertRaises(RegistryError):
            validate_tool_registry(tools)
        tools = list(load_tools())
        tools[0] = type(tools[0])(**{**tools[0].__dict__, "category": "unknown"})
        with self.assertRaises(RegistryError):
            validate_tool_registry(tools)

    def test_routes_rnd_strategy_writer_shorts_performance_and_ceo(self):
        expected = {
            "executive_coordination": "AGENT-01", "rnd_discovery": "AGENT-03",
            "rnd_analysis": "AGENT-03", "market_case_analysis": "AGENT-03",
            "idea_strategy": "AGENT-04", "content_writing": "AGENT-05",
            "shorts_production": "AGENT-06", "localization": "AGENT-07",
            "marketing_strategy": "AGENT-08", "publish_preparation": "AGENT-09",
            "engineering": "AGENT-10", "automation": "AGENT-11",
            "performance_analysis": "AGENT-12",
        }
        self.assertEqual({task_type: route_agent(task_type) for task_type in expected}, expected)
        with self.assertRaises(RegistryError):
            route_agent("unknown_task")

    def test_every_sensitive_action_is_approval_gated(self):
        for action in HUMAN_APPROVAL_ACTIONS:
            with self.subTest(action=action):
                self.assertTrue(requires_human_approval([action]))

    def test_tool_selection_only_returns_candidates_and_never_executable(self):
        task = Task(
            task_id="task-test",
            created_at="2026-10-04T00:00:00+00:00",
            created_by="AGENT-01",
            assigned_to="AGENT-02",
            department="R&D",
            task_type="rnd_analysis",
            priority="NORMAL",
            input_refs=("rnd:test",),
            output_refs=(),
            status="ASSIGNED",
            approval_required=False,
            approval_status="NOT_REQUIRED",
            parent_task_id=None,
            retry_count=0,
            result_summary="",
            error="",
        )
        selections = select_tools_for_task(task)
        self.assertEqual({tool.tool_id for tool in selections}, {"TOOL-01", "TOOL-02"})
        self.assertTrue(all(not tool.executable for tool in selections))
        self.assertTrue(all(tool.approval_required for tool in selections))
        analyst_task = Task(
            **{
                **task.__dict__,
                "assigned_to": "AGENT-03",
                "department": "Market Analysis",
                "task_type": "rnd_discovery",
            }
        )
        analyst_tools = select_tools_for_task(analyst_task)
        self.assertEqual({tool.tool_id for tool in analyst_tools}, {"TOOL-02"})


if __name__ == "__main__":
    unittest.main()