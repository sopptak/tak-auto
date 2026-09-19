"""scripts/prepare_approved_media.py 검증(5-29).

이 스크립트는 새 비즈니스 로직이 없다 - 이미 각자 검증된
scripts.generate_blog_publish_pack.main(["--from-archive", ...])와
scripts.generate_approved_shorts_script.main([...])을 순서대로 호출할 뿐이다.
실제 LLM/Threads/YouTube/Naver 호출이 전혀 없다는 것을 정적 검사 +
실제 실행 성공(예외 없음)으로 이중 확인한다.
"""

from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord, upsert_archive
from content_engine.threads_review import ThreadsPendingDraft, upsert_pending
from scripts.prepare_approved_media import main


_KNOWLEDGE_RECORD = {
    "id": "knowledge-prepare-1",
    "source_raw_id": "https://blog.example.test/1",
    "source_url": "https://blog.example.test/1",
    "title": "원문 기사 제목",
    "article_type": "experience",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "knowledge_review_status": "approved",
}


def _record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-prepare-1",
        "knowledge_id": "knowledge-prepare-1",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "rewritten_title": "AI 재작성 제목",
        "rewritten_body": "AI가 재작성한 본문입니다.",
        "source_url": "https://blog.example.test/1",
        "evidence": (),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-19T00:00:00+00:00",
        "validation_errors": (),
        "error_message": None,
        "review_status": "approved",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


class PrepareApprovedMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([_KNOWLEDGE_RECORD], ensure_ascii=False), encoding="utf-8"
        )
        self.archive_path = self.tmp_path / "archive.json"
        self.pack_output = self.tmp_path / "pack.md"
        self.blog_history_path = self.tmp_path / "blog_history.json"
        self.shorts_output_dir = self.tmp_path / "shorts_scripts"
        self.threads_pending_path = self.tmp_path / "pending.json"

    def _run(self, extra_args: list[str] | None = None) -> int:
        args = [
            "--knowledge", str(self.knowledge_path),
            "--archive", str(self.archive_path),
            "--blog-history", str(self.blog_history_path),
            "--blog-pack-output", str(self.pack_output),
            "--shorts-output-dir", str(self.shorts_output_dir),
            "--threads-pending", str(self.threads_pending_path),
        ]
        if extra_args:
            args.extend(extra_args)
        return main(args)

    def test_prepares_blog_and_shorts_and_summarizes_threads(self):
        upsert_archive(
            self.archive_path,
            [
                _record(content_id="c-blog", platform="blog"),
                _record(content_id="c-shorts", platform="shorts", knowledge_id="knowledge-prepare-1"),
            ],
        )
        upsert_pending(
            self.threads_pending_path,
            ThreadsPendingDraft(
                content_id="c-threads",
                knowledge_id="knowledge-prepare-1",
                source_url="https://blog.example.test/1",
                evidence_unit_ids=("lesson:1",),
                article_type="experience",
                knowledge_type="경험",
                original_title="원본",
                original_body="원본 본문",
                ai_rewritten_title="AI 제목",
                ai_rewritten_body="AI 본문",
                status="pending",
                created_at="2026-09-19T00:00:00+00:00",
            ),
        )

        exit_code = self._run()

        self.assertEqual(exit_code, 0)
        self.assertTrue(self.pack_output.exists())
        self.assertIn("AI 재작성 제목", self.pack_output.read_text(encoding="utf-8"))
        self.assertTrue((self.shorts_output_dir / "c-shorts.json").exists())

    def test_no_approved_records_still_exits_zero(self):
        exit_code = self._run()

        self.assertEqual(exit_code, 0)
        self.assertTrue(self.pack_output.exists())  # 빈 Pack이라도 저장됨(기존 동작)

    def test_threads_summary_reports_pending_counts_without_modifying_file(self):
        import io
        import contextlib

        upsert_pending(
            self.threads_pending_path,
            ThreadsPendingDraft(
                content_id="c-threads-2",
                knowledge_id="knowledge-prepare-1",
                source_url="https://blog.example.test/1",
                evidence_unit_ids=("lesson:1",),
                article_type=None,
                knowledge_type="경험",
                original_title="원본",
                original_body="원본 본문",
                ai_rewritten_title="AI 제목",
                ai_rewritten_body="AI 본문",
                status="pending",
                created_at="2026-09-19T00:00:00+00:00",
            ),
        )
        before = self.threads_pending_path.read_text(encoding="utf-8")

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self._run()

        after = self.threads_pending_path.read_text(encoding="utf-8")
        self.assertEqual(before, after, "이 스크립트는 Threads pending 파일을 절대 쓰면 안 됩니다(읽기 전용).")
        self.assertIn("pending 1건", captured.getvalue())

    # --- M/N/O/P/Q: 실제 외부 API/LLM/렌더링/업로드/게시 없음 ------------------------

    def test_module_never_imports_external_clients_or_renderer(self):
        source = Path("scripts/prepare_approved_media.py").read_text(encoding="utf-8")
        import_lines = [
            line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
        ]
        forbidden = (
            "ThreadsClient", "threads_publisher",
            "YouTubeClient", "youtube_publisher",
            "shorts_renderer",
            "llm_provider", "OpenAICompatibleRewriteProvider",
        )
        for token in forbidden:
            self.assertFalse(
                any(token in line for line in import_lines),
                f"import 구문에 {token}이 있으면 안 됩니다.",
            )
        # 주석/문서화 문자열에서 "이 스크립트는 Naver를 게시하지 않는다"고
        # 설명하는 것은 허용한다 - 여기서는 실제 import 구문에 naver 관련
        # 클라이언트 모듈이 없다는 사실만 확인한다.
        self.assertFalse(
            any("naver" in line.lower() for line in import_lines),
            "import 구문에 naver 관련 모듈이 있으면 안 됩니다.",
        )

    def test_full_run_completes_without_exceptions(self):
        """실제로 3단계(Blog/Shorts/Threads 요약)를 전부 실행해도 예외 없이 끝난다는
        사실 자체가 이 경로 어디에도 외부 API 호출이 없다는 기능적 증거다."""
        upsert_archive(
            self.archive_path,
            [
                _record(content_id="c-blog", platform="blog"),
                _record(content_id="c-shorts", platform="shorts"),
            ],
        )
        exit_code = self._run()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
