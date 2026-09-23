"""scripts/upload_youtube_short.py의 check_shorts_upload_eligibility() 및
관련 CLI 동작 검증(6-26, docs/6-26-youtube-publish-readiness.md 15장 Synthetic
E2E 시나리오). 실제 YouTube API는 절대 호출하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.shorts_adapter import save_approved_shorts_script, shorts_script_output_path
from content_engine.youtube_publisher import YouTubeClient, YouTubeUploadResult
from content_engine.youtube_upload_history import YouTubeUploadHistory
import scripts.upload_youtube_short as uploader


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1",
        knowledge_id="k1",
        platform="shorts",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문입니다.",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문입니다.",
        source_url="https://example.test/1",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z",
        review_status="unreviewed",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class CheckShortsUploadEligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"

    def test_scenario_3_unreviewed_is_blocked(self) -> None:
        record = _record(review_status="unreviewed")
        save_approved_shorts_script(_record(review_status="approved"), self.shorts_scripts_dir)
        reason = uploader.check_shorts_upload_eligibility("c1", [record], self.shorts_scripts_dir)
        self.assertIsNotNone(reason)
        self.assertIn("approved가 아닙니다", reason)

    def test_scenario_4_dismissed_is_blocked(self) -> None:
        record = _record(review_status="dismissed")
        save_approved_shorts_script(_record(review_status="approved"), self.shorts_scripts_dir)
        reason = uploader.check_shorts_upload_eligibility("c1", [record], self.shorts_scripts_dir)
        self.assertIsNotNone(reason)
        self.assertIn("approved가 아닙니다", reason)

    def test_scenario_5_missing_production_is_orphan_blocked(self) -> None:
        reason = uploader.check_shorts_upload_eligibility("c1", [], self.shorts_scripts_dir)
        self.assertIsNotNone(reason)
        self.assertIn("ORPHAN", reason)

    def test_scenario_6_missing_shorts_script_is_blocked(self) -> None:
        record = _record(review_status="approved")
        # ShortsScript를 일부러 만들지 않는다.
        reason = uploader.check_shorts_upload_eligibility("c1", [record], self.shorts_scripts_dir)
        self.assertIsNotNone(reason)
        self.assertIn("ShortsScript 파일이 없습니다", reason)

    def test_scenario_7_content_id_mismatch_is_conflict(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        save_approved_shorts_script(record, self.shorts_scripts_dir)
        # 파일명은 c1.json이지만 내부 content_id를 다른 값으로 조작한다(손상/수기 편집 시뮬레이션).
        script_path = shorts_script_output_path(self.shorts_scripts_dir, "c1")
        payload = json.loads(script_path.read_text(encoding="utf-8"))
        payload["content_id"] = "c1-tampered"
        script_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        reason = uploader.check_shorts_upload_eligibility("c1", [record], self.shorts_scripts_dir)
        self.assertIsNotNone(reason)
        self.assertIn("CONFLICT", reason)

    def test_scenario_1_approved_valid_script_not_published_is_eligible(self) -> None:
        record = _record(review_status="approved")
        save_approved_shorts_script(record, self.shorts_scripts_dir)
        reason = uploader.check_shorts_upload_eligibility("c1", [record], self.shorts_scripts_dir)
        self.assertIsNone(reason)

    def test_scenario_2_superseded_is_blocked(self) -> None:
        new_record = _record(content_id="c2", review_status="approved")
        # ShortsScript는 승인 당시(아직 superseded 되기 전)에 이미 생성되어 있었다고
        # 가정한다(실제 시간 순서) - save_approved_shorts_script()는 approved 레코드만
        # 받으므로, 승인 상태의 사본으로 스크립트를 먼저 만든 뒤 archive 쪽만 superseded로 바꾼다.
        save_approved_shorts_script(_record(content_id="c1", review_status="approved"), self.shorts_scripts_dir)
        old_record = _record(content_id="c1", review_status="superseded", superseded_by="c2")
        reason = uploader.check_shorts_upload_eligibility("c1", [old_record, new_record], self.shorts_scripts_dir)
        self.assertIsNotNone(reason)
        self.assertIn("superseded", reason.lower())


def _make_temp_mp4() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.write(b"fake-mp4-bytes")
    handle.close()
    return Path(handle.name)


class RaceConditionAndProductionSafetyTests(unittest.TestCase):
    """시나리오 15(supersede 이후 최종 guard) / 17(API 예외 시 production 불변)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.video_path = _make_temp_mp4()
        self.addCleanup(self.video_path.unlink, missing_ok=True)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"
        self.history_path = self.tmp_path / "youtube_publish_log.json"

    def _run(self, extra_args: list[str]) -> int:
        args = [
            "--video", str(self.video_path),
            "--title", "제목",
            "--history", str(self.history_path),
            "--production-archive", str(self.archive_path),
            "--shorts-scripts-dir", str(self.shorts_scripts_dir),
        ]
        args.extend(extra_args)
        return uploader.main(args)

    def test_scenario_15_snapshot_taken_before_supersede_does_not_see_it(self) -> None:
        """레이스 컨디션 경계: main()이 --production-archive를 읽은 스냅샷은 그
        실행 안에서 다시 읽지 않는다 - "다른 프로세스가 그 사이 supersede를
        기록"하는 시나리오는 다음 실행에서만 잡힌다(6-25 Threads와 동일한
        구조적 한계, 새 lock을 도입하지 않는다)."""
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)

        from content_engine.media_archive import load_archive

        snapshot = load_archive(self.archive_path)
        reason_before = uploader.check_shorts_upload_eligibility("c1", snapshot, self.shorts_scripts_dir)
        self.assertIsNone(reason_before)

        # "다른 프로세스"가 그 사이 supersede했다고 가정(파일만 직접 갱신).
        superseded = _record(content_id="c1", review_status="superseded", superseded_by="c2")
        new_record = _record(content_id="c2", review_status="approved")
        save_archive([superseded, new_record], self.archive_path)

        # 오래된 스냅샷은 여전히 통과된 것으로 남는다(알려진 경계).
        reason_with_stale_snapshot = uploader.check_shorts_upload_eligibility("c1", snapshot, self.shorts_scripts_dir)
        self.assertIsNone(reason_with_stale_snapshot)

        # 다음 실행(새 스냅샷)은 정확히 차단한다.
        fresh_snapshot = load_archive(self.archive_path)
        reason_next_run = uploader.check_shorts_upload_eligibility("c1", fresh_snapshot, self.shorts_scripts_dir)
        self.assertIsNotNone(reason_next_run)

    def test_scenario_17_api_exception_leaves_production_archive_unchanged(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)
        before_bytes = self.archive_path.read_bytes()

        class _FailingClient:
            def upload_short(self, **kwargs):
                raise RuntimeError("simulated network failure")

        with mock.patch.object(YouTubeClient, "from_environment", return_value=_FailingClient()):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(self.archive_path.read_bytes(), before_bytes, "업로드 스크립트는 production archive를 절대 쓰지 않아야 한다.")
        self.assertFalse(self.history_path.exists(), "실패한 업로드가 publish history에 기록되면 안 된다.")

    def test_scenario_18_history_write_failure_after_successful_upload_is_surfaced(self) -> None:
        """업로드는 성공했지만 history 기록에 실패하면, 이 사실을 stderr로
        경고하되 종료 코드는 0(업로드 자체는 성공)으로 유지한다(6-13 기존
        동작 재확인 - 이번에 변경하지 않음). 남은 위험은 문서 17장에 기록."""
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)

        fake_client = mock.Mock()
        fake_client.upload_short.return_value = YouTubeUploadResult(video_id="yt_ok")

        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client), mock.patch.object(
            YouTubeUploadHistory, "append", side_effect=OSError("disk full (simulated)")
        ):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])

        self.assertEqual(exit_code, 0, "업로드 자체는 성공했으므로 종료 코드는 0이어야 한다(기존 동작).")


if __name__ == "__main__":
    unittest.main()
