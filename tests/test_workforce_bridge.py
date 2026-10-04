"""Tests for content_engine.workforce_bridge - the pipeline <-> AI Workforce
task sync. Verifies: correct task_type/agent routing per pipeline stage,
idempotency (re-sync never duplicates open tasks), skipping of items that
already moved past a stage, and the human-approval safety guarantee for
publish-preparation tasks.
"""

from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord
from content_engine.workforce_bridge import (
    TASK_TYPE_BLOG_OR_THREADS_DRAFT,
    TASK_TYPE_KNOWLEDGE_REVIEW,
    TASK_TYPE_PERFORMANCE_ANALYSIS,
    TASK_TYPE_PUBLISH_PREP,
    TASK_TYPE_SHORTS_DRAFT,
    sync_pipeline_tasks,
)
from tak_brain.models import KnowledgeRecord
from tak_workforce.tasks import load_tasks


def _knowledge(knowledge_id: str, status: str = "pending") -> KnowledgeRecord:
    return KnowledgeRecord(
        id=knowledge_id,
        source_raw_id="raw-1",
        source_url="https://example.com/a",
        title="테스트 지식",
        created_at="2026-10-04T00:00:00+00:00",
        knowledge_review_status=status,
    )


def _media(content_id: str, knowledge_id: str, platform: str, review_status: str = "unreviewed") -> MediaArchiveRecord:
    return MediaArchiveRecord(
        content_id=content_id,
        knowledge_id=knowledge_id,
        platform=platform,
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문",
        source_url="https://example.com/a",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-10-04T00:00:00+00:00",
        review_status=review_status,
    )


class WorkforceBridgeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.task_path = Path(self._tmpdir.name) / "tak_ai_tasks.json"

    def test_pending_knowledge_creates_idea_strategy_task_for_agent_04(self):
        result = sync_pipeline_tasks(
            knowledge_records=(_knowledge("knowledge-1"),),
            path=self.task_path,
        )
        self.assertEqual(len(result.created_task_ids), 1)
        tasks = load_tasks(self.task_path)
        self.assertEqual(tasks[0].task_type, TASK_TYPE_KNOWLEDGE_REVIEW)
        self.assertEqual(tasks[0].assigned_to, "AGENT-04")
        self.assertIn("knowledge-1", tasks[0].input_refs)

    def test_approved_or_rejected_knowledge_is_skipped_as_terminal(self):
        result = sync_pipeline_tasks(
            knowledge_records=(_knowledge("knowledge-2", status="approved"), _knowledge("knowledge-3", status="rejected")),
            path=self.task_path,
        )
        self.assertEqual(result.created_task_ids, ())
        self.assertEqual(len(result.skipped_terminal_refs), 2)
        self.assertEqual(load_tasks(self.task_path), [])

    def test_blog_and_threads_drafts_route_to_writer_shorts_to_producer(self):
        result = sync_pipeline_tasks(
            generation_pool_records=(
                _media("content-blog", "knowledge-1", "blog"),
                _media("content-shorts", "knowledge-1", "shorts"),
            ),
            path=self.task_path,
        )
        self.assertEqual(len(result.created_task_ids), 2)
        tasks = {task.task_type: task for task in load_tasks(self.task_path)}
        self.assertEqual(tasks[TASK_TYPE_BLOG_OR_THREADS_DRAFT].assigned_to, "AGENT-05")
        self.assertEqual(tasks[TASK_TYPE_SHORTS_DRAFT].assigned_to, "AGENT-06")

    def test_already_reviewed_generation_drafts_are_skipped(self):
        result = sync_pipeline_tasks(
            generation_pool_records=(_media("content-promoted", "knowledge-1", "blog", review_status="approved"),),
            path=self.task_path,
        )
        self.assertEqual(result.created_task_ids, ())
        self.assertEqual(result.skipped_terminal_refs, ("generation:content-promoted",))

    def test_approved_production_record_creates_publish_task_requiring_human_approval(self):
        result = sync_pipeline_tasks(
            production_records=(_media("content-ready", "knowledge-1", "threads", review_status="approved"),),
            path=self.task_path,
        )
        self.assertEqual(len(result.created_task_ids), 1)
        task = load_tasks(self.task_path)[0]
        self.assertEqual(task.task_type, TASK_TYPE_PUBLISH_PREP)
        self.assertEqual(task.assigned_to, "AGENT-09")
        self.assertEqual(task.status, "WAITING_APPROVAL")
        self.assertEqual(task.approval_status, "PENDING")

    def test_performance_due_content_ids_create_analysis_tasks(self):
        result = sync_pipeline_tasks(
            performance_due_content_ids=("content-due-1",),
            path=self.task_path,
        )
        self.assertEqual(len(result.created_task_ids), 1)
        task = load_tasks(self.task_path)[0]
        self.assertEqual(task.task_type, TASK_TYPE_PERFORMANCE_ANALYSIS)
        self.assertEqual(task.assigned_to, "AGENT-12")

    def test_rerunning_sync_is_idempotent_for_every_stage(self):
        kwargs = dict(
            knowledge_records=(_knowledge("knowledge-1"),),
            generation_pool_records=(_media("content-blog", "knowledge-1", "blog"),),
            production_records=(_media("content-ready", "knowledge-1", "threads", review_status="approved"),),
            performance_due_content_ids=("content-due-1",),
            path=self.task_path,
        )
        first = sync_pipeline_tasks(**kwargs)
        second = sync_pipeline_tasks(**kwargs)
        self.assertEqual(len(first.created_task_ids), 4)
        self.assertEqual(second.created_task_ids, ())
        self.assertEqual(len(second.skipped_existing_refs), 4)
        self.assertEqual(len(load_tasks(self.task_path)), 4)


if __name__ == "__main__":
    unittest.main()
