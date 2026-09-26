"""6-45 Shorts 후보 준비 상태 검증(임시 디렉터리, 네트워크 없음).

- Production Archive 없음 + MEDIA LLM 자격증명 없음 -> Operator가 정확한 사람 행동을 안내
- generation pool이 있으면 Dashboard에서 후보를 검토할 수 있다(필드 표시, 승인 폼)
- MEDIA 생성은 사람 승인 없이 approved를 만들지 않고 Production Archive를 건드리지 않는다
- 승인된 valid Shorts만 ShortsScript 대상 - invalid/미승인/superseded는 제외
- 이 모든 과정에서 YouTube API 호출 0회
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine import MockRewriteProvider, archive_generation_report, run_media_batch_file
from content_engine.media_archive import MediaArchiveRecord, load_archive, save_archive
from content_engine.operator_summary import OperatorInputs, build_human_actions, build_pipeline
import scripts.generate_approved_shorts_script as generate_cli
from scripts.run_scout_dashboard import render_generation_pool_html

ROOT = Path(__file__).resolve().parents[1]


def _record(content_id: str, **overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id=content_id, knowledge_id="k1", platform="shorts", generation_status="valid",
        original_title="은행이 먼저 보는 것", original_body="첫째 문단입니다.\n\n마지막 문단입니다.",
        rewritten_title=None, rewritten_body=None, source_url="https://example.test/src",
        evidence=(), evidence_unit_ids=(), created_at="2026-09-26T00:00:00Z",
        review_status="unreviewed", generation_id="gen-645",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class _NoYouTube(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("content_engine.youtube_publisher.urlopen", side_effect=AssertionError("YouTube API 호출 금지"))
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)


class OperatorReadinessTests(_NoYouTube):
    def test_absent_archive_and_missing_llm_credentials_name_exact_action(self) -> None:
        inputs = OperatorInputs(generated_at="t", media_llm_credentials_present=False)
        action = next(a for a in build_human_actions(inputs) if a.label == "MEDIA LLM")
        self.assertIn("TAK_MEDIA_LLM_API_KEY", action.why)
        self.assertIn("--as-generation", action.action)
        media = next(s for s in build_pipeline(inputs, {}) if s.label == "MEDIA")
        self.assertIn("TAK_MEDIA_LLM_*", media.why)
        archive = next(s for s in build_pipeline(inputs, {}) if s.label == "PRODUCTION ARCHIVE")
        self.assertEqual(archive.status, "NOT_PRESENT")

    def test_no_llm_action_when_credentials_present_or_unchecked(self) -> None:
        for flag in (True, None):
            labels = {a.label for a in build_human_actions(OperatorInputs(generated_at="t", media_llm_credentials_present=flag))}
            self.assertNotIn("MEDIA LLM", labels)

    def test_generation_pool_available_turns_into_media_review_action(self) -> None:
        inputs = OperatorInputs(generated_at="t", generation_pool_found=True, generation_pool_records=(_record("c1"),),
                                media_llm_credentials_present=False)
        labels = {a.label for a in build_human_actions(inputs)}
        self.assertIn("MEDIA REVIEW", labels)
        self.assertNotIn("MEDIA LLM", labels)


class GenerationWithoutAutoApprovalTests(_NoYouTube):
    def test_media_generation_stays_unreviewed_and_never_touches_production(self) -> None:
        knowledge = ROOT / "data" / "tak_brain_knowledge.json"  # 읽기만 한다
        before = knowledge.read_bytes()
        pool = self.tmp / "tak_media_generation_test.json"
        production = self.tmp / "tak_media_archive.json"
        report = run_media_batch_file(input_path=knowledge, output_path=None, provider=MockRewriteProvider(), limit=1)
        archived = archive_generation_report(report, pool)
        self.assertTrue(archived)
        self.assertEqual({r.review_status for r in load_archive(pool)}, {"unreviewed"})
        self.assertTrue(all(r.generation_id for r in archived))
        self.assertFalse(production.exists())
        self.assertEqual(knowledge.read_bytes(), before)

    def test_pool_candidate_is_reviewable_in_dashboard(self) -> None:
        record = _record("content-645", validation_errors=())
        html = render_generation_pool_html([record])
        for expected in ("content-645", "gen-645", "은행이 먼저 보는 것", "첫째 문단입니다.", "https://example.test/src", "approve"):
            self.assertIn(expected, html)


class ApprovedShortsSelectionTests(_NoYouTube):
    def test_only_valid_approved_active_shorts_become_scripts(self) -> None:
        archive = self.tmp / "tak_media_archive.json"
        out_dir = self.tmp / "shorts_scripts"
        save_archive([
            _record("ok", review_status="approved"),
            _record("invalid", review_status="approved", generation_status="rejected"),
            _record("pending"),
            _record("old", review_status="superseded", superseded_by="ok"),
            _record("blog", platform="blog", review_status="approved"),
        ], archive)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = generate_cli.main(["--archive", str(archive), "--output-dir", str(out_dir)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(sorted(p.stem for p in out_dir.glob("*.json")), ["ok"])
        self.assertEqual(json.loads((out_dir / "ok.json").read_text(encoding="utf-8"))["content_id"], "ok")
        # 스크립트 생성은 archive를 읽기만 한다(승인 상태를 바꾸지 않음)
        self.assertEqual({r.content_id: r.review_status for r in load_archive(archive)}["pending"], "unreviewed")

    def test_absent_archive_yields_no_candidates(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            generate_cli.main(["--archive", str(self.tmp / "missing.json"), "--output-dir", str(self.tmp / "s")])
        self.assertFalse((self.tmp / "s").exists() and any((self.tmp / "s").iterdir()))


if __name__ == "__main__":
    unittest.main()
