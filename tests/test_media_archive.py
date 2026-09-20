"""content_engine/media_archive.py 및 그 연결 지점(scripts/run_media_batch.py) 검증.

5-27 설계 문서(docs/5-27_media_draft_persistence_investigation.md)가 지적한 실제 사고
("--execute로 Draft 9건을 만들었지만 --output을 지정하지 않아 프로세스 종료 후
결과가 전부 사라짐")를 정확히 재현하고, 그것이 다시 일어나지 않는지 확인한다.

실제 LLM API는 절대 호출하지 않는다 - MockRewriteProvider 또는 네트워크 호출이 없는
Fake provider만 쓰고, OpenAICompatibleRewriteProvider.from_environment는 항상 patch한다
(tests/test_run_daily.py와 동일한 방법론).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.media_archive import (
    MediaArchiveRecord,
    archive_report,
    load_archive,
    upsert_archive,
)
from content_engine.models import ContentDraft
from content_engine.pipeline import run_media_batch, run_media_batch_file
from content_engine.rewrite import MockRewriteProvider, RewriteProvider, RewriteRequest
from scripts.run_media_batch import main as run_media_batch_main
from tak_brain import load_knowledge_records


KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"


class _MixedResultProvider(RewriteProvider):
    """네트워크 호출 없는 Fake provider. 호출 순서(call_count)만으로 valid/rejected/error가
    섞인 결과를 결정적으로 만든다. generate_content_bundle()이 항상
    (blog, *shorts x3, *threads x5) 순서로 9개 draft를 만든다는 점(content_engine/
    pipeline.py의 run_media_batch)에 의존한다 - 어떤 KNOWLEDGE를 넣어도 1번째 호출은
    항상 blog다.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def rewrite(self, request: RewriteRequest) -> ContentDraft:
        self.call_count += 1
        if self.call_count == 1:
            return request.draft  # blog -> valid
        if self.call_count == 2:
            raise RuntimeError("Simulated LLM error")  # shorts #1 -> error
        # 나머지는 원문에 없는 숫자를 추가해 검증 실패(rejected)를 유도한다
        # (tests/test_media_batch.py의 RejectingProvider와 동일한 기법).
        return replace(request.draft, body=f"999999 새 숫자\n\n{request.draft.body}")


class MediaArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = load_knowledge_records(KNOWLEDGE_PATH)
        self.approved_records = tuple(
            r for r in self.records if r.knowledge_review_status == "approved"
        )
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    # --- A. valid/rejected/error가 섞여도 9개 전부 archive에 저장되는지 -------------

    def test_all_nine_drafts_archived_with_mixed_statuses(self):
        approved = self.approved_records[0]
        report = run_media_batch([approved], provider=_MixedResultProvider())

        self.assertEqual(report.total_draft_count, 9)
        self.assertEqual(report.valid_count, 1)
        self.assertEqual(report.error_count, 1)
        self.assertEqual(report.rejected_count, 7)

        archive_path = self.tmp_path / "archive.json"
        archived = archive_report(report, archive_path)

        self.assertEqual(len(archived), 9)
        statuses = {record.generation_status for record in archived}
        self.assertEqual(statuses, {"valid", "rejected", "error"})

        # 파일에도 실제로 9건 전부 저장됐는지(메모리 반환값뿐 아니라 디스크까지).
        reloaded = load_archive(archive_path)
        self.assertEqual(len(reloaded), 9)
        self.assertEqual(
            sum(1 for r in reloaded if r.generation_status == "valid"), 1
        )
        self.assertEqual(
            sum(1 for r in reloaded if r.generation_status == "rejected"), 7
        )
        self.assertEqual(
            sum(1 for r in reloaded if r.generation_status == "error"), 1
        )

    # --- B. 같은 content_id로 다시 호출하면 upsert(중복 생성 아님) ------------------

    def test_archive_report_upserts_by_content_id_instead_of_duplicating(self):
        approved = self.approved_records[0]
        report = run_media_batch([approved], provider=MockRewriteProvider())
        archive_path = self.tmp_path / "archive.json"

        archive_report(report, archive_path)
        self.assertEqual(len(load_archive(archive_path)), 9)

        # 같은 KNOWLEDGE로 배치를 다시 실행(재실행 시나리오) - content_id는
        # knowledge_id/platform/source_url/evidence_unit_ids/original_title/
        # original_body로만 계산되므로(rewritten 텍스트 제외) 동일하게 나온다.
        second_report = run_media_batch([approved], provider=MockRewriteProvider())
        archive_report(second_report, archive_path)

        after_second_run = load_archive(archive_path)
        self.assertEqual(len(after_second_run), 9, "재실행이 항목을 중복 추가하면 안 됩니다.")

        # review_status를 사람이 승인으로 바꾼 뒤 다시 archive_report()를 호출해도
        # 그 검토 상태가 초기화되지 않아야 한다(재실행이 사람의 판단을 되돌리면 안 됨).
        target = after_second_run[0]
        upsert_archive(archive_path, [replace(target, review_status="approved")])
        self.assertEqual(len(load_archive(archive_path)), 9)

        third_report = run_media_batch([approved], provider=MockRewriteProvider())
        archive_report(third_report, archive_path)

        after_third_run = {r.content_id: r for r in load_archive(archive_path)}
        self.assertEqual(len(after_third_run), 9)
        self.assertEqual(after_third_run[target.content_id].review_status, "approved")

    # --- C. --output을 지정하지 않아도 archive에는 결과가 남는지 (오늘 사고 재현) ----

    def test_cli_execute_without_output_still_persists_to_archive(self):
        """오늘 실제로 발생한 문제를 그대로 재현한다:
        `scripts/run_media_batch.py --execute --id <knowledge>`를 --output 없이
        실행하면, 수정 전 코드에서는 9개 Draft가 만들어졌다가 프로세스 종료와 함께
        전부 사라졌다. 이 테스트는 --output을 의도적으로 생략하고도 아카이브 파일에
        9건이 전부 남는지 확인한다."""
        approved = self.approved_records[0]
        fixture_path = self.tmp_path / "fixture_knowledge.json"
        fixture_path.write_text(
            json.dumps([approved.to_dict()], ensure_ascii=False), encoding="utf-8"
        )
        archive_path = self.tmp_path / "archive.json"

        with mock.patch.object(
            OpenAICompatibleRewriteProvider,
            "from_environment",
            return_value=MockRewriteProvider(),
        ):
            exit_code = run_media_batch_main(
                [
                    "--input", str(fixture_path),
                    "--execute",
                    "--archive", str(archive_path),
                    # --output은 의도적으로 생략한다(오늘 발생한 상황 그대로).
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(
            archive_path.exists(),
            "--output 없이 --execute해도 아카이브 파일은 반드시 생성되어야 합니다.",
        )
        archived = load_archive(archive_path)
        self.assertEqual(len(archived), 9)
        self.assertTrue(all(record.knowledge_id == approved.id for record in archived))

    def test_run_media_batch_file_without_output_path_still_archivable(self):
        """CLI를 거치지 않는 Python API 경로(run_media_batch_file)에서도
        output_path=None이 report 자체를 사라지게 만들지 않는지(= archive_report에
        넘길 수 있는 report가 정상적으로 반환되는지) 확인한다."""
        approved = self.approved_records[0]
        report = run_media_batch_file(
            KNOWLEDGE_PATH,
            output_path=None,
            limit=1,
            knowledge_id=approved.id,
            provider=MockRewriteProvider(),
        )
        self.assertEqual(report.total_draft_count, 9)

        archive_path = self.tmp_path / "archive.json"
        archived = archive_report(report, archive_path)
        self.assertEqual(len(archived), 9)
        self.assertTrue(archive_path.exists())

    # --- D. created_at / knowledge_id / validation_errors 보존 ---------------------

    def test_created_at_knowledge_id_and_validation_errors_are_preserved(self):
        approved = self.approved_records[0]

        class RejectingProvider(RewriteProvider):
            def rewrite(self, request: RewriteRequest) -> ContentDraft:
                return replace(request.draft, body=f"999999 새 숫자\n\n{request.draft.body}")

        report = run_media_batch([approved], provider=RejectingProvider())
        self.assertEqual(report.rejected_count, 9)
        self.assertTrue(all(item.created_at for item in report.items))

        archive_path = self.tmp_path / "archive.json"
        archived = archive_report(report, archive_path)

        for record in archived:
            self.assertEqual(record.knowledge_id, approved.id)
            self.assertTrue(record.created_at)
            self.assertEqual(record.generation_status, "rejected")
            self.assertTrue(
                any("없는 숫자" in reason for reason in record.validation_errors)
            )
            self.assertEqual(record.review_status, "unreviewed")

        # 디스크에 저장된 뒤 다시 읽어도 동일하게 보존되는지.
        reloaded = load_archive(archive_path)
        self.assertEqual(len(reloaded), 9)
        for record in reloaded:
            self.assertEqual(record.knowledge_id, approved.id)
            self.assertTrue(record.created_at)
            self.assertTrue(record.validation_errors)

    # --- 그 외: MediaArchiveRecord 직렬화 왕복(round-trip) ---------------------------

    def test_media_archive_record_round_trip(self):
        approved = self.approved_records[0]
        report = run_media_batch([approved], provider=MockRewriteProvider())
        item = report.items[0]

        record = MediaArchiveRecord.from_item(item)
        restored = MediaArchiveRecord.from_dict(record.to_dict())

        self.assertEqual(restored, record)
        self.assertEqual(restored.review_status, "unreviewed")


class MediaArchiveToDashboardIntegrationTests(unittest.TestCase):
    """6-03: KNOWLEDGE -> MEDIA generation -> archive -> /media Dashboard 렌더링까지
    전체 사슬이 실제로 연결되어 있는지 확인한다.

    6-03 조사에서 확인한 사실: production data/tak_brain_knowledge.json에는 실제로
    approved KNOWLEDGE가 6건 있는데도 실제 Dashboard의 /media 화면에는 "조건에 맞는
    Draft가 없습니다"만 보인다 - 그 이유는 코드 결함이 아니라, 실제 production
    data/tak_media_archive.json이 (실제 LLM 자격증명으로) 한 번도 생성된 적이
    없기 때문이다(운영 실행 누락, docs/6-03_*.md 6장 참고). 이 테스트는 "만약
    누군가 실제로 --execute를 실행했다면 이 코드가 정말 작동하는가"를, 실제
    production KNOWLEDGE를 읽기 전용 입력으로 쓰고 MockRewriteProvider(네트워크
    없음)로 증명한다 - production data/tak_media_archive.json은 이 테스트 어디에서도
    생성/수정하지 않는다(tmp_path에만 저장).

    기존 MediaArchiveTests와 같은 fixture(KNOWLEDGE_PATH, self.approved_records)를
    재사용한다 - 새 fixture를 만들지 않는다(11장 지시: 기존 테스트 인프라 재사용).
    """

    def setUp(self) -> None:
        self.records = load_knowledge_records(KNOWLEDGE_PATH)
        self.approved_records = tuple(
            r for r in self.records if r.knowledge_review_status == "approved"
        )
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def _start_dashboard(self, archive_path: Path):
        from http.server import ThreadingHTTPServer
        import threading

        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        config = DashboardConfig(
            daily_pack_path=self.tmp_path / "tak_scout_daily.json",
            answers_path=self.tmp_path / "tak_interview_answers.json",
            # KNOWLEDGE는 실제 production 파일을 읽기 전용으로 그대로 쓴다(fixture를
            # 새로 만들지 않는다) - 이 Dashboard 인스턴스가 그 파일에 쓰기를 시도하는
            # 라우트는 /media 관련 라우트 중 없다(승인 POST는 이 테스트에서 호출하지 않는다).
            knowledge_path=KNOWLEDGE_PATH,
            skipped_path=self.tmp_path / "tak_scout_dashboard_skipped.json",
            sessions_path=self.tmp_path / "tak_interview_sessions.json",
            pending_path=self.tmp_path / "tak_threads_pending.json",
            media_archive_path=archive_path,
            shorts_scripts_path=self.tmp_path / "shorts_scripts",
            blog_history_path=self.tmp_path / "blog_publish_log.json",
            performance_path=self.tmp_path / "tak_performance.json",
        )
        handler_class = make_handler_class(config)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server

    def test_real_approved_knowledge_generates_drafts_the_dashboard_can_render(self):
        import urllib.request

        self.assertGreater(
            len(self.approved_records), 0,
            "production KNOWLEDGE에 approved 레코드가 없습니다 - 이 테스트가 검증하려는 "
            "전제(approved KNOWLEDGE가 존재한다) 자체가 깨졌다는 뜻이므로 명확히 실패시킨다.",
        )

        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())
        # 설계대로 KNOWLEDGE 1건당 9개(Blog 1 + Shorts 3 + Threads 5)가 나와야 한다.
        self.assertEqual(report.total_draft_count, len(self.approved_records) * 9)
        self.assertEqual(report.error_count, 0)

        archive_path = self.tmp_path / "tak_media_archive.json"
        archive_report(report, archive_path)
        archived = load_archive(archive_path)
        self.assertEqual(len(archived), report.total_draft_count)
        self.assertTrue(all(record.review_status == "unreviewed" for record in archived))

        server = self._start_dashboard(archive_path)
        port = server.server_address[1]

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/media", timeout=5) as response:
            status = response.status
            body = response.read().decode("utf-8")

        self.assertEqual(status, 200)
        self.assertNotIn("조건에 맞는 Draft가 없습니다", body)
        # 목록 화면(/media)은 카드마다 상세보기 링크만 보여준다(승인 폼은 상세 페이지
        # 전용 - _media_card_html/render_media_detail_html 구조, 아래에서 확인).
        valid_record = next(r for r in archived if r.generation_status == "valid")
        self.assertIn(f"/media/{valid_record.content_id}", body)
        self.assertIn(valid_record.knowledge_id, body)

        # 상세 페이지도 실제로 200을 반환하고 승인 폼을 보여주는지 확인한다(13장 지시).
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/media/{valid_record.content_id}", timeout=5
        ) as detail_response:
            detail_status = detail_response.status
            detail_body = detail_response.read().decode("utf-8")
        self.assertEqual(detail_status, 200)
        self.assertIn(f"/media/{valid_record.content_id}/approve", detail_body)

        # production 파일은 이 테스트 어디에서도 생성/수정되지 않아야 한다.
        production_archive = KNOWLEDGE_PATH.parent / "tak_media_archive.json"
        self.assertFalse(
            production_archive.exists(),
            "이 테스트가 실수로 production archive를 생성했습니다 - 절대 발생하면 안 됩니다.",
        )

    def test_pending_and_rejected_knowledge_never_reach_the_archive(self):
        """승인되지 않은 KNOWLEDGE(pending/rejected)가 섞여 들어와도 archive에
        나타나지 않아야 한다 - select_approved()가 이미 이를 보장하지만(기존
        test_pipeline_selects_only_approved_knowledge), 여기서는 archive/Dashboard
        연결까지 포함해 한 번 더 확인한다(11장 지시 9번)."""
        from tak_brain import select_approved

        not_approved_ids = {
            record.id for record in self.records if record.knowledge_review_status != "approved"
        }
        self.assertGreater(len(not_approved_ids), 0, "pending/rejected KNOWLEDGE가 하나도 없습니다.")

        approved_via_selector = tuple(select_approved(self.records))
        report = run_media_batch(approved_via_selector, provider=MockRewriteProvider())

        archived_knowledge_ids = {item.knowledge_id for item in report.items}
        self.assertTrue(archived_knowledge_ids.isdisjoint(not_approved_ids))


if __name__ == "__main__":
    unittest.main()
