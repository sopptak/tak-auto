"""TAK AUTO 6-30(docs/6-30-shorts-renderer-and-youtube-readiness.md) 전용 검증.

이 파일이 확인하는 것:
  1) **6-40에서 갱신**: 6-30 당시 ``content_engine.shorts_renderer``/
     ``scripts.render_youtube_short``는 이 저장소 git 이력 전체에 존재한 적이
     없어(CASE C, EXTERNAL_MACHINE_REQUIRED) "존재하지 않는다"는 회귀 감지
     테스트였다. 6-40이 6-30 15/16장의 권고("Git history에서 복구 불가능하면
     사람이 확인 후 REBUILD_REQUIRED")에 따라 실제로 renderer를 새로
     구현했으므로, 이 클래스는 이제 반대로 "renderer가 정상 존재/동작하는지"를
     확인한다 - 기능 자체의 상세 테스트는 ``tests/test_shorts_renderer.py``/
     ``tests/test_render_youtube_short_cli.py``(6-40, 신규)가 담당한다.
  2) 6-30 Section 11: ShortsScript와 mp4 파일이 실제로 디스크에 존재해도,
     Production Archive가 superseded면 scripts/upload_youtube_short.py의
     main() 전체 CLI 경로가 재업로드를 차단한다(실제 렌더러는 없으므로 가짜
     mp4 bytes를 쓰는 mock renderer 개념으로 대체).
  3) 6-30 Section 9/10: CASE A~F를 main() 전체 CLI 경로로 재확인한다(6-26의
     check_shorts_upload_eligibility() 단위 테스트가 아니라 실제 진입점).

실제 YouTube API/OAuth는 전혀 호출하지 않는다(YouTubeClient.from_environment를
항상 mock으로 대체). 운영 데이터(data/tak_media_archive.json,
data/shorts_scripts/, data/youtube_publish_log.json)는 전혀 건드리지 않는다 -
전부 tempfile.TemporaryDirectory() 안에서만 동작한다.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.shorts_adapter import save_approved_shorts_script
from content_engine.youtube_publisher import YouTubeClient, YouTubeUploadResult
from content_engine.youtube_upload_history import YouTubeUploadHistory
import scripts.upload_youtube_short as uploader


class RendererNowExistsTests(unittest.TestCase):
    """6-30 Section 15/16 -> 6-40: renderer를 REBUILD_REQUIRED 판정에 따라
    새로 구현했다(``docs/6-40-shorts-quality-validation.md``). 이 클래스는
    더 이상 "존재하지 않음"을 확인하지 않는다 - 반대로 두 진입점이 정상
    import/실행 가능한지만 최소한으로 확인한다(상세 기능 테스트는
    ``test_shorts_renderer.py``/``test_render_youtube_short_cli.py``)."""

    def test_shorts_renderer_module_is_importable(self) -> None:
        module = __import__("content_engine.shorts_renderer", fromlist=["render_shorts_video"])
        self.assertTrue(hasattr(module, "render_shorts_video"))

    def test_render_youtube_short_script_exists(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.assertTrue((repo_root / "scripts" / "render_youtube_short.py").exists())


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


def _mock_render_mp4(path: Path) -> Path:
    """실제 renderer가 없으므로, "렌더러가 만들었다고 가정한 mp4"를 흉내만
    낸다(6-30 Section 11/16 - 진짜 렌더러를 만들지 않는다는 제약을 지키면서
    Section 11이 요구하는 mock renderer 검증을 만족시킨다)."""
    path.write_bytes(b"fake-mp4-bytes-from-mock-renderer")
    return path


class CliLevelSupersededMp4Tests(unittest.TestCase):
    """6-30 Section 11: ShortsScript가 존재하고 렌더러가 만든(것으로 가정한)
    mp4 파일이 실제로 디스크에 있어도, Production Archive가 superseded면
    업로드가 차단되어야 한다. 새 차단 코드가 필요한지 확인하는 것이 목적이다 -
    기존 6-26 로직(check_shorts_upload_eligibility)이 main() 전체 경로에서도
    똑같이 동작하는지 실제 CLI 진입점으로 확인한다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"
        self.history_path = self.tmp_path / "youtube_publish_log.json"
        self.video_path = _mock_render_mp4(self.tmp_path / "rendered_short.mp4")

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

    def test_superseded_record_with_existing_mp4_is_blocked_by_full_cli(self) -> None:
        # ShortsScript/mp4는 승인 당시(아직 superseded 되기 전) 이미 만들어져
        # 디스크에 남아 있다고 가정한다(실제 시간 순서) - "렌더러가 없다"는
        # 사실과 별개로, "이미 만들어진 산출물이 있어도 supersede 이후에는
        # 못 올린다"는 정책 자체를 검증하는 것이 이 테스트의 목적이다.
        save_approved_shorts_script(_record(content_id="c1", review_status="approved"), self.shorts_scripts_dir)
        old_record = _record(content_id="c1", review_status="superseded", superseded_by="c2")
        new_record = _record(content_id="c2", review_status="approved")
        save_archive([old_record, new_record], self.archive_path)

        fake_client = mock.Mock()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])

        self.assertEqual(exit_code, 1)
        fake_client.upload_short.assert_not_called()
        self.assertFalse(self.history_path.exists(), "차단된 업로드가 publish history에 기록되면 안 된다.")
        self.assertTrue(self.video_path.exists(), "mp4 파일 자체는 그대로 남아 있어야 한다(업로드 스크립트가 파일을 지우지 않는다).")

    def test_approved_record_with_mock_rendered_mp4_is_eligible(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)

        fake_client = mock.Mock()
        fake_client.upload_short.return_value = YouTubeUploadResult(video_id="yt_mock_1")
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])

        self.assertEqual(exit_code, 0)
        fake_client.upload_short.assert_called_once()
        history = YouTubeUploadHistory(self.history_path)
        self.assertTrue(history.is_published("c1"))


class FullCliCaseAToFTests(unittest.TestCase):
    """6-30 Section 9/10: CASE A~F를 실제 main() CLI 진입점으로 재확인한다
    (6-26 단위 테스트는 check_shorts_upload_eligibility() 헬퍼만 호출했다 -
    6-29에서 지적된 "실제 호출 경로를 추적하라"는 기준을 이 파일에서 main()
    수준으로 다시 만족시킨다)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"
        self.history_path = self.tmp_path / "youtube_publish_log.json"
        self.video_path = _mock_render_mp4(self.tmp_path / "rendered_short.mp4")

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

    def test_case_a_already_published_is_idempotent_noop(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)
        history = YouTubeUploadHistory(self.history_path)
        from content_engine.youtube_upload_history import YouTubeUploadRecord

        history.append(
            YouTubeUploadRecord(
                video_id="yt_already",
                uploaded_at="2026-01-01T00:00:00Z",
                title="이미 올라간 영상",
                privacy_status="private",
                video_path=str(self.video_path),
                tags=(),
                content_id="c1",
                knowledge_id="k1",
            )
        )

        fake_client = mock.Mock()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])

        self.assertEqual(exit_code, 0)
        fake_client.upload_short.assert_not_called()

    def test_case_b_approved_is_eligible(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)

        fake_client = mock.Mock()
        fake_client.upload_short.return_value = YouTubeUploadResult(video_id="yt_b")
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])
        self.assertEqual(exit_code, 0)
        fake_client.upload_short.assert_called_once()

    def test_case_c_superseded_is_blocked(self) -> None:
        save_approved_shorts_script(_record(content_id="c1", review_status="approved"), self.shorts_scripts_dir)
        old_record = _record(content_id="c1", review_status="superseded", superseded_by="c2")
        new_record = _record(content_id="c2", review_status="approved")
        save_archive([old_record, new_record], self.archive_path)

        fake_client = mock.Mock()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])
        self.assertEqual(exit_code, 1)
        fake_client.upload_short.assert_not_called()

    def test_case_d_unreviewed_needs_human_review_is_blocked(self) -> None:
        record = _record(content_id="c1", review_status="unreviewed")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(_record(content_id="c1", review_status="approved"), self.shorts_scripts_dir)

        fake_client = mock.Mock()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])
        self.assertEqual(exit_code, 1)
        fake_client.upload_short.assert_not_called()

    def test_case_e_missing_production_is_orphan_blocked(self) -> None:
        # production archive 자체가 비어 있다(record 없음) - YouTube는 Threads와
        # 달리 ORPHAN을 통과시키지 않는다(6-26에서 의도적으로 뒤집은 정책).
        save_archive([], self.archive_path)
        save_approved_shorts_script(_record(content_id="c1", review_status="approved"), self.shorts_scripts_dir)

        fake_client = mock.Mock()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])
        self.assertEqual(exit_code, 1)
        fake_client.upload_short.assert_not_called()

    def test_case_f_content_id_conflict_is_blocked(self) -> None:
        import json

        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        save_approved_shorts_script(record, self.shorts_scripts_dir)
        script_path = self.shorts_scripts_dir / "c1.json"
        payload = json.loads(script_path.read_text(encoding="utf-8"))
        payload["content_id"] = "c1-tampered"
        script_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        fake_client = mock.Mock()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--content-id", "c1", "--knowledge-id", "k1"])
        self.assertEqual(exit_code, 1)
        fake_client.upload_short.assert_not_called()


if __name__ == "__main__":
    unittest.main()
