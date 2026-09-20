"""6-07 회귀 테스트: knowledge-scout-6d1d0e2fa762의 article_type 정정과
generation pool 조회 화면(/media/generations).

docs/6-07_second_knowledge_regeneration.md 참고. 실제 LLM은 호출하지 않는다
(MockRewriteProvider만 사용) - 실제 LLM 호출 결과 자체는 이 세션에서 실행한
1회 실행(data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json)으로만
존재하며, 회귀 테스트가 그 정확한 텍스트에 의존하면 재현 불가능해지므로
구조/안전장치만 고정한다.

이 파일이 다루는 범위(6-06의 tests/test_media_versioning_and_promotion.py와
중복되지 않는 것만):
    - 실제 production KNOWLEDGE 레코드(knowledge-scout-6d1d0e2fa762) 자체의 정정 검증
    - 이 KNOWLEDGE로 실제 생성한 generation pool 파일이 안전 조건을 만족하는지
      (production archive와 content_id가 겹치지 않음, 전부 unreviewed 등)
    - 6-07에서 새로 추가한 Dashboard 읽기 전용 라우트
      (/media/generations, /media/generations/<knowledge_id>)
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import unittest
import urllib.request

from content_engine.blog_publish_pack import is_review_required
from content_engine.generator import generate_content_bundle
from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_generation_archive
from content_engine.pipeline import run_media_batch
from content_engine.rewrite import MockRewriteProvider
from scripts.run_scout_dashboard import DashboardConfig, make_handler_class
from tak_brain import load_knowledge_records

KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"
PRODUCTION_ARCHIVE_PATH = Path(__file__).parents[1] / "data" / "tak_media_archive.json"
GENERATION_POOL_PATH = (
    Path(__file__).parents[1] / "data" / "tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json"
)
TARGET_KNOWLEDGE_ID = "knowledge-scout-6d1d0e2fa762"

_FINANCE_TEMPLATE_MARKERS = (
    "재무 판단에서 함께 볼 기준",
    "재무 판단의 출발점",
    "금융기관의 공식 심사 기준",
    "심사 기준",
    "대출 판단",
    "투자 판단",
)


def _load_target():
    records = load_knowledge_records(KNOWLEDGE_PATH)
    return next(r for r in records if r.id == TARGET_KNOWLEDGE_ID)


class SecondKnowledgeCorrectionTests(unittest.TestCase):
    """정정된 실제 production KNOWLEDGE 레코드(합성 fixture가 아님) 검증."""

    def setUp(self) -> None:
        self.knowledge = _load_target()

    def test_article_type_was_corrected_to_none(self):
        self.assertIsNone(self.knowledge.article_type)

    def test_other_fields_are_unchanged_from_6_05_report(self):
        """6-05 보고서(3장)가 기록한 정정 전 값과 비교해, article_type 외 필드는
        전혀 바뀌지 않았어야 한다."""
        self.assertEqual(self.knowledge.title, "Uncontrolled AI could lead to 'silicon species' rivalling humans, warns Microsoft")
        self.assertEqual(
            self.knowledge.source_url,
            "https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss",
        )
        self.assertEqual(self.knowledge.category, "금융")
        self.assertEqual(self.knowledge.domain, "금융")
        self.assertEqual(self.knowledge.knowledge_type, "의견")
        self.assertEqual(self.knowledge.knowledge_review_status, "approved")
        self.assertEqual(self.knowledge.review_note, "SCOUT 인터뷰 테스트 승인")
        self.assertEqual(self.knowledge.reviewed_at, "2026-09-19T04:56:09.685072+00:00")
        self.assertEqual(self.knowledge.created_at, "2026-09-19T04:49:15.737804+00:00")
        self.assertIn("Mustafa Suleyman", self.knowledge.lesson)

    def test_corrected_knowledge_produces_no_finance_template_leakage(self):
        bundle = generate_content_bundle(self.knowledge)
        all_text = bundle.blog.title + " " + bundle.blog.body
        for short in bundle.shorts:
            all_text += " " + short.title + " " + short.body
        for thread in bundle.threads:
            all_text += " " + thread.title + " " + thread.body

        for marker in _FINANCE_TEMPLATE_MARKERS:
            self.assertNotIn(marker, all_text)

    def test_corrected_knowledge_still_requires_human_review(self):
        """category/domain="금융"이 남아 있으므로 article_type 정정 후에도
        is_review_required()는 여전히 True여야 한다(6-05/6-06과 동일한 안전장치)."""
        self.assertTrue(is_review_required(self.knowledge))

    def test_mock_generation_produces_nine_drafts(self):
        report = run_media_batch([self.knowledge], provider=MockRewriteProvider())
        self.assertEqual(report.total_draft_count, 9)
        platforms = [item.platform for item in report.items]
        self.assertEqual(platforms.count("blog"), 1)
        self.assertEqual(platforms.count("shorts"), 3)
        self.assertEqual(platforms.count("threads"), 5)


@unittest.skipUnless(GENERATION_POOL_PATH.exists(), "6-07 실제 LLM 실행 결과 파일이 없습니다.")
class RealGenerationPoolResultTests(unittest.TestCase):
    """이번 세션에서 실제로 1회 실행한 LLM generation 결과
    (data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json)가 안전
    조건을 만족하는지 확인한다. 이 파일 자체는 재현 불가능한 실제 LLM 출력이므로,
    텍스트 내용이 아니라 구조적 안전 조건만 검증한다."""

    def setUp(self) -> None:
        self.records = load_archive(GENERATION_POOL_PATH)

    def test_exactly_nine_records_for_this_knowledge(self):
        self.assertEqual(len(self.records), 9)
        for record in self.records:
            self.assertEqual(record.knowledge_id, TARGET_KNOWLEDGE_ID)

    def test_all_nine_share_the_same_generation_id(self):
        generation_ids = {record.generation_id for record in self.records}
        self.assertEqual(len(generation_ids), 1)
        self.assertIsNotNone(next(iter(generation_ids)))
        self.assertTrue(next(iter(generation_ids)).startswith("gen-"))

    def test_all_nine_start_as_unreviewed(self):
        for record in self.records:
            self.assertEqual(record.review_status, "unreviewed")

    def test_generation_status_values_are_faithfully_stored(self):
        """generation_status가 valid/rejected/error 중 하나로 정확히 저장되고
        임의로 valid로 바뀌지 않았는지 확인한다(6-07 절대 원칙: rejected를
        valid로 바꾸지 않는다)."""
        for record in self.records:
            self.assertIn(record.generation_status, ("valid", "rejected", "error"))

    def test_no_finance_template_leakage_in_real_llm_output(self):
        all_text = " ".join(
            (record.rewritten_title or "") + " " + (record.rewritten_body or "") for record in self.records
        )
        for marker in _FINANCE_TEMPLATE_MARKERS:
            self.assertNotIn(marker, all_text)

    def test_source_url_preserved_across_all_nine(self):
        source_urls = {record.source_url for record in self.records}
        self.assertEqual(
            source_urls,
            {"https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss"},
        )

    def test_no_content_id_collision_with_production_archive(self):
        production_content_ids = {record.content_id for record in load_archive(PRODUCTION_ARCHIVE_PATH)}
        pool_content_ids = {record.content_id for record in self.records}
        self.assertEqual(production_content_ids & pool_content_ids, set())

    def test_production_archive_still_has_only_the_original_nine_records(self):
        """6-07 실행(실제 LLM 호출 포함) 전체가 production archive를 전혀
        건드리지 않았는지 - 6-05가 기록한 content_id 9개와 정확히 같아야 한다."""
        production_records = load_archive(PRODUCTION_ARCHIVE_PATH)
        self.assertEqual(len(production_records), 9)
        expected_content_ids = {
            "content-5971ed5204437cdd",
            "content-e787c9201b94a948",
            "content-3ae2d78568210164",
            "content-cabd37f3a2745724",
            "content-dbf0fb4eb5cfd791",
            "content-81d4e7c5723598f6",
            "content-4015df0692e0bcc4",
            "content-5a6b175ac6023db1",
            "content-cbcf705b6056c9fc",
        }
        self.assertEqual({record.content_id for record in production_records}, expected_content_ids)
        for record in production_records:
            self.assertIsNone(record.generation_id)


def _generation_record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-gen-pool-test-1",
        "knowledge_id": "knowledge-gen-pool-test",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "rewritten_title": "재작성 제목",
        "rewritten_body": "재작성 본문",
        "source_url": "https://example.test/article",
        "evidence": ("SOURCE FACT: 예시",),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-20T00:00:00+00:00",
        "review_status": "unreviewed",
        "generation_id": "gen-test-a",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


class GenerationPoolDashboardRouteTests(unittest.TestCase):
    """6-07이 추가한 읽기 전용 /media/generations, /media/generations/<knowledge_id>
    라우트를 실제 HTTP 요청으로 검증한다(기존 test_media_dashboard.py와 동일한
    ThreadingHTTPServer + urllib 방법론)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.knowledge_path.write_text("[]", encoding="utf-8")
        self.archive_path = self.directory / "tak_media_archive.json"
        self.generation_pool_a = self.directory / "pool_a.json"
        self.generation_pool_b = self.directory / "pool_b.json"

        upsert_generation_archive(
            self.generation_pool_a,
            [
                _generation_record(
                    content_id="content-shared-slot", knowledge_id="knowledge-A", generation_id="gen-old"
                ),
                _generation_record(
                    content_id="content-shared-slot", knowledge_id="knowledge-A", generation_id="gen-new"
                ),
            ],
        )
        upsert_generation_archive(
            self.generation_pool_b,
            [_generation_record(content_id="content-other-slot", knowledge_id="knowledge-B", generation_id="gen-b1")],
        )

        self.config = DashboardConfig(
            daily_pack_path=self.directory / "tak_scout_daily.json",
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.knowledge_path,
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            pending_path=self.directory / "tak_threads_pending.json",
            media_archive_path=self.archive_path,
            shorts_scripts_path=self.directory / "shorts_scripts",
            blog_history_path=self.directory / "blog_publish_log.json",
            generation_archive_paths=(self.generation_pool_a, self.generation_pool_b),
        )
        self._start_server()

    def _start_server(self) -> None:
        handler_class = make_handler_class(self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _get(self, path: str) -> tuple[int, str]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.read().decode("utf-8")

    def test_generations_page_lists_all_configured_pools(self):
        status, body = self._get("/media/generations")

        self.assertEqual(status, 200)
        self.assertIn("gen-old", body)
        self.assertIn("gen-new", body)
        self.assertIn("gen-b1", body)
        self.assertIn("content-shared-slot", body)
        self.assertIn("content-other-slot", body)

    def test_generations_page_forms_only_target_generation_pool_routes(self):
        """6-08: 이 화면은 이제 승인/보류 폼을 갖지만(6-08에서 추가), 그 폼들은
        전부 /media/generations/ 하위 경로만 가리켜야 한다 - production archive를
        갱신하는 기존 /media/{content_id}/approve 같은 경로를 가리키는 폼은
        하나도 없어야 한다(6-08 절대 원칙: Generation Pool 승인 != Production
        Promotion). promotion을 실행하는 폼/링크도 없어야 한다(promotion은
        여전히 CLI 전용)."""
        _, body = self._get("/media/generations")

        self.assertIn("<form", body)
        for line in body.splitlines():
            if '<form method="post" action="' not in line:
                continue
            action = line.split('action="', 1)[1].split('"', 1)[0]
            self.assertTrue(
                action.startswith("/media/generations/"),
                f"generation pool 화면의 폼이 production 경로를 가리킵니다: {action}",
            )
        # 설명 문구(예: "scripts/promote_media_generation.py를 CLI로 실행하세요")는
        # 허용하되, promotion을 실행하는 폼/링크는 없어야 한다.
        self.assertNotIn('action="/promote', body)
        self.assertNotIn("/approve-all-and-promote", body)

    def test_generations_filtered_by_knowledge_id(self):
        status, body = self._get("/media/generations/knowledge-A")

        self.assertEqual(status, 200)
        self.assertIn("content-shared-slot", body)
        self.assertNotIn("content-other-slot", body)

    def test_generations_page_with_no_configured_pool_shows_empty_state(self):
        empty_config = DashboardConfig(
            daily_pack_path=self.directory / "tak_scout_daily.json",
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.knowledge_path,
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            pending_path=self.directory / "tak_threads_pending.json",
            media_archive_path=self.archive_path,
            shorts_scripts_path=self.directory / "shorts_scripts",
            blog_history_path=self.directory / "blog_publish_log.json",
        )
        handler_class = make_handler_class(empty_config)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/media/generations", timeout=5) as response:
                status = response.status
                body = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(status, 200)
        self.assertIn("없습니다", body)

    def test_existing_media_route_still_works(self):
        """6-07의 변경이 기존 /media 라우트를 깨지 않았는지 회귀 확인."""
        status, body = self._get("/media")

        self.assertEqual(status, 200)
        self.assertIn("TAK MEDIA", body)


if __name__ == "__main__":
    unittest.main()
