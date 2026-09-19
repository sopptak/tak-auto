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


if __name__ == "__main__":
    unittest.main()
