"""Research -> pending KNOWLEDGE bridge tests. No live API calls."""
import json
from pathlib import Path
import tempfile
import unittest

from tak_scout.research import ResearchRecord
from tak_scout.research_knowledge import build_knowledge_from_research, upsert_research_knowledge


def record(status="completed"):
    return ResearchRecord(
        scout_id="scout-abc123",
        candidate_title="부동산 경매 제도 변경",
        candidate_url="https://example.test/article",
        source_name="Example News",
        candidate_published_at="2026-11-15",
        researched_at="2026-11-16T10:00:00+00:00",
        query="조사 쿼리",
        answer="확인된 사실과 불확실성을 구분한 조사 결과입니다.",
        citations=("https://example.test/official",),
        model="sonar-pro",
        status=status,
    )


class ResearchKnowledgeTests(unittest.TestCase):
    def test_builds_external_information_pending_not_personal_opinion(self):
        knowledge = build_knowledge_from_research(record())
        self.assertEqual(knowledge.knowledge_review_status, "pending")
        self.assertEqual(knowledge.knowledge_type, "정보")
        self.assertEqual(knowledge.inference_method, "rule_based_template")
        self.assertIsNone(knowledge.opinion)
        self.assertIsNone(knowledge.experience)
        self.assertTrue(knowledge.verification_required)
        self.assertIn("PERPLEXITY CITATION: https://example.test/official", knowledge.evidence)

    def test_rejects_failed_research(self):
        with self.assertRaises(ValueError):
            build_knowledge_from_research(record("failed"))

    def test_create_then_research_updates_same_pending_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            created, status = upsert_research_knowledge(record(), path)
            self.assertEqual(status, "created")
            revised = ResearchRecord(**{**record().__dict__, "answer": "갱신된 조사 결과"})
            updated, status = upsert_research_knowledge(revised, path)
            self.assertEqual(status, "updated_pending")
            self.assertEqual(created.id, updated.id)
            self.assertEqual(updated.lesson, "갱신된 조사 결과")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 1)

    def test_approved_record_is_never_overwritten_by_research(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            created, _ = upsert_research_knowledge(record(), path)
            data = json.loads(path.read_text(encoding="utf-8"))
            data[0]["knowledge_review_status"] = "approved"
            data[0]["lesson"] = "사람이 승인한 내용"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result, status = upsert_research_knowledge(
                ResearchRecord(**{**record().__dict__, "answer": "새로운 조사 결과"}), path
            )
            self.assertEqual(status, "already_approved")
            self.assertEqual(result.lesson, "사람이 승인한 내용")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["lesson"], "사람이 승인한 내용")


if __name__ == "__main__":
    unittest.main()
