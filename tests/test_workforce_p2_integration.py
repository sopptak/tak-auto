from pathlib import Path
import tempfile
import unittest

from tak_rnd import add_rnd_item, load_ideas, promote_rnd_to_idea
from tak_workforce import create_task, route_task, set_task_status


class P2FoundationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.rnd_path = root / "rnd.json"
        self.idea_path = root / "ideas.json"
        self.task_path = root / "tasks.json"

    def test_rnd_idea_content_performance_ceo_reference_chain(self):
        rnd = add_rnd_item(
            {"source": "web", "url": "https://example.test/agent", "title": "Browser agent case"},
            self.rnd_path,
        )
        analysis = create_task("rnd_analysis", input_refs=[f"rnd:{rnd.id}"], path=self.task_path)
        analysis = route_task(analysis.task_id, self.task_path)
        self.assertEqual(analysis.assigned_to, "AGENT-03")

        idea = promote_rnd_to_idea(
            rnd.id,
            {
                "title": "TAK AUTO browser research adapter",
                "description": "Use a browser agent as a research adapter.",
                "why_important": "Reduce manual research effort.",
                "application_areas": ["browser_automation"],
                "expected_impact": "Faster public-source research.",
            },
            self.rnd_path,
            self.idea_path,
        )
        self.assertEqual(load_ideas(self.idea_path)[0].source_rnd_ids, (rnd.id,))
        analysis = set_task_status(
            analysis.task_id, "RUNNING", path=self.task_path
        )
        analysis = set_task_status(
            analysis.task_id, "COMPLETED", output_refs=[f"idea:{idea.id}"], path=self.task_path
        )

        strategy = create_task(
            "idea_strategy", created_by="AGENT-03", input_refs=[f"idea:{idea.id}"],
            parent_task_id=analysis.task_id, path=self.task_path,
        )
        strategy = route_task(strategy.task_id, self.task_path)
        self.assertEqual(strategy.assigned_to, "AGENT-04")
        strategy = set_task_status(strategy.task_id, "RUNNING", path=self.task_path)
        strategy = set_task_status(
            strategy.task_id, "COMPLETED", output_refs=["brief:strategy-1"], path=self.task_path
        )

        writer = create_task(
            "content_writing", created_by="AGENT-04", input_refs=["brief:strategy-1"],
            parent_task_id=strategy.task_id, path=self.task_path,
        )
        writer = route_task(writer.task_id, self.task_path)
        self.assertEqual(writer.assigned_to, "AGENT-05")
        writer = set_task_status(writer.task_id, "RUNNING", path=self.task_path)
        writer = set_task_status(
            writer.task_id, "COMPLETED", output_refs=["content:draft-1"], path=self.task_path
        )

        shorts = create_task(
            "shorts_production", created_by="AGENT-05", input_refs=["content:draft-1"],
            parent_task_id=writer.task_id, path=self.task_path,
        )
        shorts = route_task(shorts.task_id, self.task_path)
        self.assertEqual(shorts.assigned_to, "AGENT-06")
        shorts = set_task_status(shorts.task_id, "RUNNING", path=self.task_path)
        shorts = set_task_status(
            shorts.task_id, "COMPLETED", output_refs=["content:shorts-local-draft"], path=self.task_path
        )

        performance = create_task(
            "performance_analysis", created_by="AGENT-06",
            input_refs=["content:shorts-local-draft"], parent_task_id=shorts.task_id, path=self.task_path,
        )
        performance = route_task(performance.task_id, self.task_path)
        self.assertEqual(performance.assigned_to, "AGENT-12")
        performance = set_task_status(performance.task_id, "RUNNING", path=self.task_path)
        performance = set_task_status(
            performance.task_id, "COMPLETED", output_refs=["performance:content-1"], path=self.task_path
        )

        executive = create_task(
            "executive_coordination", created_by="AGENT-12",
            input_refs=["performance:content-1"], parent_task_id=performance.task_id,
            path=self.task_path,
        )
        executive = route_task(executive.task_id, self.task_path)
        self.assertEqual(executive.assigned_to, "AGENT-01")
        self.assertEqual((executive.status, executive.approval_status), ("WAITING_APPROVAL", "PENDING"))
        self.assertEqual(len([analysis, strategy, writer, shorts, performance, executive]), 6)


if __name__ == "__main__":
    unittest.main()