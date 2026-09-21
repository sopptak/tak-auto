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
import hashlib
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
from scripts.run_scout_dashboard import DashboardConfig, load_knowledge_titles, make_handler_class
from tak_brain import load_knowledge_records


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

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
        전혀 바뀌지 않았어야 한다.

        예외: category/domain은 6-15에서 "금융"->"기타"로 정정됐다 - 이 KNOWLEDGE의
        실제 내용(Mustafa Suleyman의 AI 의식 가능성 발언)은 금융/대출/경매/부동산과
        무관한데, SCOUT 수집 당시 출처 RSS 피드(BBC Business)의 블랭킷 category가
        그대로 복사되어 있었다(tak_scout/knowledge_bridge.py의 구조적 한계,
        docs/6-15_data_integrity_and_publish_readiness_report.md 3장 참고). 다른
        모든 필드(승인 상태, 검토 메모, 시각, 본문 등)는 그대로 유지된다."""
        self.assertEqual(self.knowledge.title, "Uncontrolled AI could lead to 'silicon species' rivalling humans, warns Microsoft")
        self.assertEqual(
            self.knowledge.source_url,
            "https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo?at_medium=RSS&at_campaign=rss",
        )
        self.assertEqual(self.knowledge.category, "기타")
        self.assertEqual(self.knowledge.domain, "기타")
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

    def test_corrected_knowledge_no_longer_requires_finance_review(self):
        """6-15에서 category/domain이 "금융"->"기타"로 정정된 뒤에는
        is_review_required()가 False여야 한다 - 이 콘텐츠는 실제로 금융/대출/
        경매/부동산과 무관하므로, 정확한 category가 반영되면 금융 전용 안전장치가
        더 이상 걸리지 않는 것이 의도된 동작이다(review_required 판정 로직 자체는
        바뀌지 않았다 - 입력 category가 정확해졌을 뿐이다).
        Production Archive의 이 knowledge_id 레코드 9건 전부 stale finance-template
        잔재가 없다는 사실은 docs/6-15_data_integrity_and_publish_readiness_report.md
        6장에서 별도로 확인했다."""
        self.assertFalse(is_review_required(self.knowledge))

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

    def test_all_nine_are_approved_after_6_12_review(self):
        """6-07 직후에는 이 9건이 전부 unreviewed였지만, 6-12
        (docs/6-12_media_generation_promotion_execution.md)에서 사람이 실제로
        Dashboard에서 검토하고 approve-all을 실행해 전부 approved로 전이했다 -
        이 파일 자체(generation pool)는 promotion 이후에도 그 상태 그대로
        보존된다(promote_media_generation.py는 generation pool을 읽기만 하고
        쓰지 않는다). 그래서 이제는 "생성 직후 unreviewed"가 아니라 "6-12 검토
        완료 후 approved"가 이 실제 파일의 고정된 현재 상태다."""
        for record in self.records:
            self.assertEqual(record.review_status, "approved")

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

    def test_content_ids_are_now_promoted_into_production_archive(self):
        """6-07 시점에는 이 pool의 content_id 9건이 production archive와 겹치지
        않아야 했다(승격 전이므로). 6-12에서 사람이 이 9건을 승인하고 실제로
        promote_media_generation.py --execute로 production archive에 승격했으므로,
        이제는 정반대로 "pool의 9건이 production archive의 부분집합"이어야
        정상이다 - 겹치지 않으면 오히려 6-12 promotion이 사라졌다는 뜻이므로
        경고 신호다. 승격된 production 레코드는 이 pool 레코드와 동일한
        generation_id(gen-20260920T033856-6e8d98fb)를 가져야 한다(promotion이
        내용을 바꾸지 않고 그대로 복사했는지 확인)."""
        production_records = {
            record.content_id: record for record in load_archive(PRODUCTION_ARCHIVE_PATH)
        }
        pool_content_ids = {record.content_id for record in self.records}
        self.assertTrue(pool_content_ids.issubset(production_records.keys()))
        for record in self.records:
            promoted = production_records[record.content_id]
            self.assertEqual(promoted.generation_id, record.generation_id)
            self.assertEqual(promoted.review_status, "approved")

    def test_production_archive_still_has_the_original_nine_plus_promoted_nine(self):
        """6-07 실행(실제 LLM 호출 포함) 자체는 production archive를 건드리지
        않았다 - 다만 그 이후 6-12에서 사람이 명시적으로 이 9건을 승격시켰으므로,
        지금 production archive는 "6-05가 기록한 legacy 9건" + "6-12가 승격한
        신규 9건" = 18건이어야 한다. legacy 9건의 content_id 집합은 6-12
        promotion과 무관하게 그대로 유지되어야 한다(정확히 일치, 추가/삭제 없음)."""
        production_records = load_archive(PRODUCTION_ARCHIVE_PATH)
        legacy_content_ids = {
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
        promoted_content_ids = {record.content_id for record in self.records}

        self.assertEqual(len(production_records), 18)
        self.assertEqual(
            {record.content_id for record in production_records},
            legacy_content_ids | promoted_content_ids,
        )
        for record in production_records:
            if record.content_id in legacy_content_ids:
                self.assertIsNone(record.generation_id)
            else:
                self.assertEqual(record.generation_id, "gen-20260920T033856-6e8d98fb")

    # --- 6-11 3/10/12(G)장: 이 세션(6-11)이 실제 9건/production archive를 --
    # 절대 쓰지 않는다는 것을 파일 해시로 재확인한다. 이 클래스의 다른 모든
    # 테스트도 load_archive()만 호출하고 어떤 저장 함수도 부르지 않는다
    # (upsert_generation_archive/save_archive/upsert_archive를 이 클래스
    # 전체에서 import조차 하지 않는다) - 이 두 테스트는 그 사실을 실제
    # 파일 해시 비교로 다시 한번 못박는다.

    def test_real_generation_pool_file_hash_unchanged_by_this_test_run(self):
        before = _file_hash(GENERATION_POOL_PATH)
        # 같은 클래스의 다른 테스트들과 동일하게 읽기만 한다.
        load_archive(GENERATION_POOL_PATH)
        after = _file_hash(GENERATION_POOL_PATH)
        self.assertEqual(before, after)

    def test_real_production_archive_file_hash_unchanged_by_this_test_run(self):
        before = _file_hash(PRODUCTION_ARCHIVE_PATH)
        load_archive(PRODUCTION_ARCHIVE_PATH)
        after = _file_hash(PRODUCTION_ARCHIVE_PATH)
        self.assertEqual(before, after)

    # --- 6-11 8장: 실제 knowledge_id에 대해 KNOWLEDGE 제목 조회가 정상 동작 --

    def test_knowledge_title_lookup_resolves_for_the_real_target_knowledge(self):
        """실제 9건이 전부 참조하는 knowledge_id(TARGET_KNOWLEDGE_ID)에 대해
        load_knowledge_titles()가 올바른 제목을 돌려주는지 확인한다(6-11 8장:
        Generation Pool 화면에서 "KNOWLEDGE: <제목>"을 보여주기 위한 조회) -
        데이터를 전혀 쓰지 않는다."""
        titles = load_knowledge_titles(KNOWLEDGE_PATH)
        self.assertEqual(
            titles.get(TARGET_KNOWLEDGE_ID),
            "Uncontrolled AI could lead to 'silicon species' rivalling humans, warns Microsoft",
        )


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
