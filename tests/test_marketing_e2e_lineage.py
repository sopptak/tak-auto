"""6-82 E2E: MarketingBrief -> generation -> MEDIA generation pool -> 사람의 검토 -> promotion
-> performance content_id -> marketing insight lineage가 끊기지 않는지 확인한다.

임시 디렉터리만 쓰고 네트워크를 쓰지 않는다. 사람의 승인은 기존 대시보드 handler로, 승격은 기존
promote_media_generation CLI로 수행한다(marketing 코드는 승인/승격하지 않는다).
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.marketing import (
    append_briefs, collect_marketing_insights, load_briefs, load_candidates, pool_path_for, resolve_brief,
)
from content_engine.media_archive import archive_generation_report, load_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot, latest_snapshot_per_content
from content_engine.pipeline import run_media_batch
from content_engine.rewrite import MockRewriteProvider
from scripts import marketing_brief as marketing_cli
from scripts import promote_media_generation as promote_cli
from scripts.promote_media_generation import plan_batch_promotion
from scripts.run_scout_dashboard import discover_generation_pool_paths, handle_generation_review_submission
from tests.test_marketing_generation import approved_brief, knowledge


def _run(main, argv):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = main(argv)
    return code, out.getvalue()


class MarketingToInsightLineageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.production = self.data / "tak_media_archive.json"
        self.performance = self.data / "tak_performance.json"
        self.knowledge = knowledge()
        (self.data / "tak_brain_knowledge.json").write_text(
            json.dumps([self.knowledge.to_dict()], ensure_ascii=False), encoding="utf-8")
        self.brief = approved_brief("youtube")
        append_briefs(self.data / "tak_marketing_briefs.json", [self.brief])
        # 같은 KNOWLEDGE의 기존 배치 generation(같은 content_id 슬롯을 공유한다).
        self.batch_pool = self.data / "tak_media_generation_batch.json"
        archive_generation_report(run_media_batch([self.knowledge], provider=MockRewriteProvider()), self.batch_pool,
                                  generation_id="gen-batch")

        self.urlopen = mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")).start()
        self.addCleanup(mock.patch.stopall)
        self.cli(["--write", "generate", self.brief.brief_id, "--rewrite", "mock"])
        self.cli(["--write", "bridge", self.brief.brief_id])
        self.pool = pool_path_for(self.data, self.brief.brief_id)
        self.records = load_archive(self.pool)
        self.generation_id = self.records[0].generation_id

    def cli(self, argv):
        code, out = _run(marketing_cli.main, ["--data-dir", str(self.data), *argv])
        self.assertEqual(code, 0, out)
        return out

    def approve_and_promote(self, pool, record):
        updated, error = handle_generation_review_submission(
            discover_generation_pool_paths(self.data), record.content_id, record.generation_id, "approved")
        self.assertIsNone(error)
        self.assertEqual(updated.review_status, "approved")
        code, out = _run(promote_cli.main, ["--archive", str(pool), "--production-archive", str(self.production),
                                            "--content-id", record.content_id, "--generation-id",
                                            record.generation_id, "--execute"])
        self.assertEqual(code, 0, out)

    def record_performance(self, content_id):
        append_snapshot(self.performance, PerformanceRecord(
            content_id=content_id, knowledge_id=self.knowledge.id, platform="youtube",
            published_at="2026-10-04T00:00:00+00:00", metric_collected_at="2026-10-05T00:00:00+00:00",
            metrics={"views": 1000, "likes": 40, "clicks": 12}, source="manual"))

    def insights(self):
        return collect_marketing_insights(load_briefs(self.data / "tak_marketing_briefs.json"),
                                          latest_snapshot_per_content(self.performance), load_archive(self.production))

    def test_lineage_from_brief_to_insight(self):
        # generation -> pool: youtube 브리프가 MEDIA shorts 레코드로, 기존 배치와 같은 content_id 슬롯에 들어간다.
        candidates = load_candidates(self.data / "tak_marketing_contents.json", self.brief.brief_id)
        self.assertEqual(len(self.records), 3)
        self.assertEqual({r.platform for r in self.records}, {"shorts"})
        self.assertEqual({r.content_id for r in self.records}, {c["content_id"] for c in candidates})
        batch_shorts = {r.content_id for r in load_archive(self.batch_pool) if r.platform == "shorts"}
        self.assertEqual({r.content_id for r in self.records}, batch_shorts)
        self.assertIn(self.pool, discover_generation_pool_paths(self.data))

        # bridge는 승인/승격하지 않는다: 사람의 승인 전에는 promotion 대상이 없고 production도 없다.
        self.assertTrue(all(r.review_status == "unreviewed" for r in self.records))
        plan = plan_batch_promotion(self.pool, self.production, self.generation_id)
        self.assertEqual({item.action for item in plan}, {"skip"})
        self.assertFalse(self.production.exists())

        # 사람의 승인(기존 대시보드 handler) -> promotion 대상 -> 기존 CLI로 승격
        target = self.records[0]
        handle_generation_review_submission((self.pool,), target.content_id, target.generation_id, "approved")
        plan = {item.record.content_id: item.action for item in plan_batch_promotion(
            self.pool, self.production, self.generation_id)}
        self.assertEqual(plan[target.content_id], "promote")
        self.assertFalse(self.production.exists())  # 계획만으로는 쓰지 않는다
        code, out = _run(promote_cli.main, ["--archive", str(self.pool), "--production-archive", str(self.production),
                                            "--content-id", target.content_id, "--generation-id",
                                            target.generation_id, "--execute"])
        self.assertEqual(code, 0, out)
        promoted = load_archive(self.production)
        self.assertEqual([(r.content_id, r.generation_id) for r in promoted], [(target.content_id, self.generation_id)])

        # production (content_id, generation_id) -> brief_id
        briefs = load_briefs(self.data / "tak_marketing_briefs.json")
        self.assertEqual(resolve_brief(briefs, promoted[0].content_id, promoted[0].generation_id), self.brief.brief_id)
        self.assertIsNone(resolve_brief(briefs, promoted[0].content_id, "gen-batch"))

        # performance content_id -> marketing insight
        self.record_performance(promoted[0].content_id)
        insights = self.insights()
        self.assertEqual(len(insights), 1)
        insight = insights[0]
        self.assertEqual((insight.brief_id, insight.content_id, insight.generation_id),
                         (self.brief.brief_id, target.content_id, self.generation_id))
        self.assertEqual(insight.platform, "youtube")
        self.assertIn("platform.youtube", insight.attributes)
        self.assertEqual(insight.observed["conversion_rate"], 0.012)
        self.urlopen.assert_not_called()

    def test_same_slot_from_batch_generation_is_not_attributed(self):
        batch_record = next(r for r in load_archive(self.batch_pool)
                            if r.content_id == self.records[0].content_id)
        self.approve_and_promote(self.batch_pool, batch_record)
        self.record_performance(batch_record.content_id)
        self.assertEqual(load_archive(self.production)[0].generation_id, "gen-batch")
        self.assertEqual(self.insights(), [])

    def test_lineage_persisted_only_in_tracked_brief_file(self):
        briefs = load_briefs(self.data / "tak_marketing_briefs.json")
        refs = {(ref.content_id, ref.generation_id) for ref in briefs[0].media_generations}
        self.assertEqual(refs, {(r.content_id, r.generation_id) for r in self.records})
        # 무시 대상인 후보/풀 파일이 없어져도(새 환경) Git 추적 브리프 파일만으로 역참조가 된다.
        with tempfile.TemporaryDirectory() as other:
            fresh_path = Path(other) / "tak_marketing_briefs.json"
            fresh_path.write_bytes((self.data / "tak_marketing_briefs.json").read_bytes())
            fresh = load_briefs(fresh_path)
        for record in self.records:
            self.assertEqual(resolve_brief(fresh, record.content_id, record.generation_id), self.brief.brief_id)


if __name__ == "__main__":
    unittest.main()
