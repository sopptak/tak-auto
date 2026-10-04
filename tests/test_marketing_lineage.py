"""6-82 (content_id, generation_id) -> brief_id lineage."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from content_engine.marketing import (
    MarketingBrief, MarketingError, MediaGenerationRef, append_briefs, collect_marketing_insights,
    derive_platform_brief, link_media_generation, load_briefs, resolve_brief, update_element,
)
from content_engine.media_archive import MediaArchiveRecord
from content_engine.performance.models import PerformanceRecord
from tests.test_marketing_generation import approved_brief


def snapshot(content_id, generation_id=None, views=100, clicks=5):
    return PerformanceRecord(content_id=content_id, knowledge_id="k", platform="youtube",
                             published_at="2026-10-04T00:00:00+00:00", metric_collected_at="2026-10-05T00:00:00+00:00",
                             metrics={"views": views, "clicks": clicks}, source="manual", generation_id=generation_id)


def archive_record(content_id, generation_id):
    return MediaArchiveRecord(content_id=content_id, knowledge_id="k", platform="shorts", generation_status="valid",
                              original_title="t", original_body="b", rewritten_title=None, rewritten_body=None,
                              source_url="https://x", evidence=("e",), evidence_unit_ids=("u",),
                              created_at="2026-10-04T00:00:00Z", review_status="approved", generation_id=generation_id)


class ModelTests(unittest.TestCase):
    def test_roundtrip_and_backward_compatible(self):
        brief = replace(approved_brief("youtube"), content_ids=("content-a",),
                        media_generations=(MediaGenerationRef("content-a", "gen-1"),))
        data = brief.to_dict()
        self.assertEqual(data["media_generations"], [{"content_id": "content-a", "generation_id": "gen-1"}])
        self.assertEqual(MarketingBrief.from_dict(data), brief)
        data.pop("media_generations")
        self.assertEqual(MarketingBrief.from_dict(data).media_generations, ())
        with self.assertRaises(MarketingError):
            MediaGenerationRef("content-a", "")

    def test_derived_platform_brief_starts_without_lineage(self):
        brief = replace(approved_brief("youtube"), platform="", media_generations=(MediaGenerationRef("c", "g"),))
        self.assertEqual(derive_platform_brief(brief, "blog").media_generations, ())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "b.json"
        self.brief = approved_brief("youtube")
        append_briefs(self.path, [self.brief])

    def test_link_is_idempotent_and_links_content(self):
        for _ in range(2):
            stored = link_media_generation(self.path, self.brief.brief_id, "content-a", "gen-1")
        self.assertEqual(stored.content_ids, ("content-a",))
        self.assertEqual(stored.media_generations, (MediaGenerationRef("content-a", "gen-1"),))
        stored = link_media_generation(self.path, self.brief.brief_id, "content-a", "gen-2")
        self.assertEqual(stored.content_ids, ("content-a",))
        self.assertEqual(stored.generation_ids_for("content-a"), {"gen-1", "gen-2"})
        raw = json.loads(self.path.read_text(encoding="utf-8"))[0]
        self.assertEqual(len(raw["media_generations"]), 2)

    def test_lineage_survives_human_edit(self):
        link_media_generation(self.path, self.brief.brief_id, "content-a", "gen-1")
        edited = update_element(self.path, self.brief.brief_id, "sales.offer", "사람이 고친 오퍼 문구입니다")
        self.assertEqual(edited.status, "draft")
        self.assertEqual(edited.generation_ids_for("content-a"), {"gen-1"})

    def test_unknown_brief(self):
        with self.assertRaises(MarketingError):
            link_media_generation(self.path, "brief-missing", "content-a", "gen-1")


class ResolveAndInsightTests(unittest.TestCase):
    def setUp(self):
        self.brief = replace(approved_brief("youtube"), content_ids=("content-a",),
                             media_generations=(MediaGenerationRef("content-a", "gen-marketing"),))
        self.legacy = replace(approved_brief("blog"), content_ids=("content-b",))  # lineage 없는 기존 연결

    def test_resolve_brief(self):
        briefs = [self.brief, self.legacy]
        self.assertEqual(resolve_brief(briefs, "content-a", "gen-marketing"), self.brief.brief_id)
        self.assertIsNone(resolve_brief(briefs, "content-a", "gen-batch"))
        self.assertIsNone(resolve_brief(briefs, "content-b", "gen-marketing"))

    def test_snapshot_generation_id_decides_attribution(self):
        ours = collect_marketing_insights([self.brief], {"content-a": snapshot("content-a", "gen-marketing")})
        self.assertEqual([(i.brief_id, i.generation_id) for i in ours], [(self.brief.brief_id, "gen-marketing")])
        other = collect_marketing_insights([self.brief], {"content-a": snapshot("content-a", "gen-batch")})
        self.assertEqual(other, [])

    def test_archive_active_generation_used_when_snapshot_has_none(self):
        snaps = {"content-a": snapshot("content-a")}
        ours = collect_marketing_insights([self.brief], snaps, [archive_record("content-a", "gen-marketing")])
        self.assertEqual(ours[0].generation_id, "gen-marketing")
        self.assertEqual(collect_marketing_insights([self.brief], snaps, [archive_record("content-a", "gen-batch")]), [])
        self.assertEqual(collect_marketing_insights([self.brief], snaps, []), [])  # 승격되지 않은 콘텐츠

    def test_backward_compatible_matching(self):
        snaps = {"content-a": snapshot("content-a"), "content-b": snapshot("content-b")}
        # 근거가 없으면(archive 미지정 + 스냅샷 generation 없음) 기존처럼 content_id로 귀속
        self.assertEqual(len(collect_marketing_insights([self.brief], snaps)), 1)
        # lineage가 없는 기존 연결은 generation과 무관하게 기존 동작 유지
        legacy = collect_marketing_insights([self.legacy], snaps, [archive_record("content-b", "gen-x")])
        self.assertEqual([i.content_id for i in legacy], ["content-b"])


if __name__ == "__main__":
    unittest.main()
