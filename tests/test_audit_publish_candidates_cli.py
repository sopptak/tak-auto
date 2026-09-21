"""scripts/audit_publish_candidates.py CLI 검증(6-14).

실제 Threads/YouTube/Naver API는 이 스크립트가 애초에 import조차 하지 않는다
(스크립트 자체 docstring 참고) - 이 테스트는 그 사실을 전제로 순수 로컬 파일
입출력만으로 CLI를 검증한다.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord, upsert_archive
from scripts.audit_publish_candidates import main


_KNOWLEDGE_RECORD = {
    "id": "knowledge-audit-cli-1",
    "source_raw_id": "https://blog.example.test/1",
    "source_url": "https://blog.example.test/1",
    "title": "원문 기사 제목",
    "article_type": "experience",
    "domain": "자기계발",
    "category": "자기계발",
    "knowledge_type": "경험",
    "knowledge_review_status": "approved",
}


def _record(**overrides) -> MediaArchiveRecord:
    fields = dict(
        content_id="content-audit-cli-1",
        knowledge_id="knowledge-audit-cli-1",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="AI 재작성 제목",
        rewritten_body="AI가 재작성한 본문입니다.",
        source_url="https://blog.example.test/1",
        evidence=(),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-21T00:00:00+00:00",
        review_status="approved",
    )
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


class AuditPublishCandidatesCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8"
        )
        self.archive_path = self.tmp_path / "archive.json"
        self.threads_pending_path = self.tmp_path / "threads_pending.json"
        self.blog_history_path = self.tmp_path / "blog_publish_log.json"
        self.threads_history_path = self.tmp_path / "threads_publish_log.json"
        self.youtube_history_path = self.tmp_path / "youtube_publish_log.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"
        self.shorts_dir = self.tmp_path / "shorts"
        self.report_path = self.tmp_path / "publish_readiness_latest.md"

    def _base_args(self, extra: list[str] | None = None) -> list[str]:
        return [
            "--archive", str(self.archive_path),
            "--knowledge", str(self.knowledge_path),
            "--threads-pending", str(self.threads_pending_path),
            "--blog-history", str(self.blog_history_path),
            "--threads-history", str(self.threads_history_path),
            "--youtube-history", str(self.youtube_history_path),
            "--shorts-scripts-dir", str(self.shorts_scripts_dir),
            "--shorts-dir", str(self.shorts_dir),
            "--report-output", str(self.report_path),
            *(extra or []),
        ]

    def _run(self, extra: list[str] | None = None) -> tuple[int, str]:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(self._base_args(extra))
        return exit_code, stdout.getvalue()

    def test_empty_archive_runs_cleanly_and_writes_report(self):
        upsert_archive(self.archive_path, [])
        exit_code, stdout = self._run()

        self.assertEqual(exit_code, 0)
        self.assertIn("전체 Production 콘텐츠: 0", stdout)
        self.assertTrue(self.report_path.exists())
        self.assertIn("# Publish Readiness", self.report_path.read_text(encoding="utf-8"))

    def test_approved_ready_content_is_listed(self):
        upsert_archive(self.archive_path, [_record(review_status="approved")])
        exit_code, stdout = self._run()

        self.assertEqual(exit_code, 0)
        self.assertIn("게시 가능(READY): 1", stdout)
        self.assertIn("content-audit-cli-1", stdout)

    def test_unreviewed_content_is_not_listed_as_ready(self):
        upsert_archive(self.archive_path, [_record(review_status="unreviewed")])
        exit_code, stdout = self._run()

        self.assertEqual(exit_code, 0)
        self.assertIn("게시 가능(READY): 0", stdout)
        self.assertIn("게시 차단(BLOCKED): 1", stdout)

    def test_no_report_flag_skips_writing_file(self):
        upsert_archive(self.archive_path, [_record(review_status="approved")])
        exit_code, _stdout = self._run(["--no-report"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.report_path.exists())

    def test_fail_on_error_returns_nonzero_when_duplicate_content_id_exists(self):
        # upsert_archive는 content_id 단독 키라 중복을 만들 수 없으므로, 파일에
        # 직접 같은 content_id 2건을 써서 구조적 이상(ERROR) 상황을 재현한다.
        duplicate_payload = [_record().to_dict(), _record().to_dict()]
        self.archive_path.write_text(json.dumps(duplicate_payload, ensure_ascii=False), encoding="utf-8")

        exit_code, stdout = self._run(["--fail-on-error"])
        self.assertEqual(exit_code, 1)
        self.assertIn("오류(ERROR): 2", stdout)

    def test_without_fail_on_error_flag_error_does_not_change_exit_code(self):
        duplicate_payload = [_record().to_dict(), _record().to_dict()]
        self.archive_path.write_text(json.dumps(duplicate_payload, ensure_ascii=False), encoding="utf-8")

        exit_code, _stdout = self._run()
        self.assertEqual(exit_code, 0)

    def test_missing_archive_file_treated_as_empty_not_error(self):
        # load_archive()는 파일이 없으면 빈 목록을 반환한다(기존 관례) - CLI가
        # 이를 오류로 취급하지 않는지 확인.
        exit_code, stdout = self._run()
        self.assertEqual(exit_code, 0)
        self.assertIn("전체 Production 콘텐츠: 0", stdout)


if __name__ == "__main__":
    unittest.main()
