"""6-42 YouTube 업로드 파이프라인 검증(실제 API 호출 없음).

MP4 -> OAuth -> Upload -> Processing 확인 -> Publish History -> 중복/SUPERSEDED/PUBLIC 보호.
실제 YouTube 업로드는 테스트에 넣지 않는다 - urlopen을 막아 두고 transport/클라이언트를
가짜로 주입한다. ``data/`` 아래 어떤 파일도 만들지 않는다.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.shorts_adapter import save_approved_shorts_script
from content_engine.youtube_publisher import (
    WAITING_PROCESSING,
    YouTubeAPIError,
    YouTubeClient,
)
from content_engine.youtube_upload_history import YouTubeUploadHistory
import scripts.upload_youtube_short as uploader


def _status_response(processing: str, privacy: str = "private", title: str = "제목") -> dict:
    return {"items": [{
        "id": "vid1",
        "snippet": {"title": title, "description": "설명", "publishedAt": "2026-09-26T00:00:00Z"},
        "status": {"privacyStatus": privacy, "uploadStatus": "uploaded"},
        "processingDetails": {"processingStatus": processing},
    }]}


def _client(status_responses: list) -> YouTubeClient:
    responses = iter(status_responses)

    def status_transport(token, video_id, timeout):
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item

    return YouTubeClient(
        client_id="id", client_secret="secret", refresh_token="refresh",
        token_transport=lambda *a: {"access_token": "tok"},
        upload_transport=lambda token, metadata, path, timeout: {"id": "vid1"},
        status_transport=status_transport,
    )


class NoNetworkMixin:
    def setUp(self) -> None:  # 실수로 실제 네트워크를 타면 즉시 실패
        patcher = mock.patch("content_engine.youtube_publisher.urlopen", side_effect=AssertionError("network"))
        patcher.start()
        self.addCleanup(patcher.stop)


class VideoStatusTests(NoNetworkMixin, unittest.TestCase):
    def test_status_response_is_parsed(self) -> None:
        status = _client([_status_response("succeeded")]).get_video_status("vid1")
        self.assertEqual((status.found, status.privacy_status, status.processing_status, status.title),
                         (True, "private", "succeeded", "제목"))

    def test_missing_video_is_not_found(self) -> None:
        self.assertFalse(_client([{"items": []}]).get_video_status("vid1").found)

    def test_polling_stops_when_processing_finishes(self) -> None:
        sleeps: list[float] = []
        client = _client([_status_response("processing"), _status_response("processing"), _status_response("succeeded")])
        status = client.wait_for_processing("vid1", attempts=6, interval_seconds=10, sleep=sleeps.append)
        self.assertEqual(status.processing_status, "succeeded")
        self.assertEqual(sleeps, [10, 10])

    def test_polling_is_bounded_and_reports_waiting(self) -> None:
        sleeps: list[float] = []
        client = _client([_status_response("processing")] * 3)
        status = client.wait_for_processing("vid1", attempts=3, interval_seconds=5, sleep=sleeps.append)
        self.assertEqual(status.processing_status, WAITING_PROCESSING)
        self.assertEqual(len(sleeps), 2)


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1", knowledge_id="k1", platform="shorts", generation_status="valid",
        original_title="원본", original_body="본문", rewritten_title="제목", rewritten_body="본문입니다.",
        source_url="https://example.test/1", evidence=(), evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z", review_status="approved",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class UploadCliPipelineTests(NoNetworkMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.video = self.tmp / "short.mp4"
        self.video.write_bytes(b"fake-mp4")
        self.history = self.tmp / "youtube_publish_log.json"
        self.archive = self.tmp / "tak_media_archive.json"
        self.scripts_dir = self.tmp / "shorts_scripts"
        self.upload_calls = 0

    def _fake_client(self, status_responses: list) -> YouTubeClient:
        client = _client(status_responses)

        def counting_upload(token, metadata, path, timeout):
            self.upload_calls += 1
            self.last_metadata = metadata
            return {"id": "vid1"}

        return YouTubeClient(**{**client.__dict__, "upload_transport": counting_upload})

    def _run(self, *extra: str, client: YouTubeClient | None = None) -> tuple[int, str]:
        args = ["--video", str(self.video), "--title", "제목", "--history", str(self.history),
                "--production-archive", str(self.archive), "--shorts-scripts-dir", str(self.scripts_dir), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), \
                mock.patch.object(YouTubeClient, "from_environment", return_value=client or self._fake_client([_status_response("succeeded")])):
            code = uploader.main(args)
        return code, out.getvalue()

    def test_public_requires_explicit_confirmation(self) -> None:
        code, out = self._run("--privacy", "public")
        self.assertEqual(code, 1)
        self.assertIn("--confirm-public", out)
        self.assertEqual(self.upload_calls, 0)
        self.assertFalse(self.history.exists())

    def test_default_privacy_is_private(self) -> None:
        code, _ = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(self.last_metadata["status"]["privacyStatus"], "private")

    def test_history_records_processing_status(self) -> None:
        code, out = self._run()
        self.assertEqual(code, 0)
        record = YouTubeUploadHistory(self.history).load()[0]
        self.assertEqual((record["video_id"], record["privacy_status"], record["processing_status"]),
                         ("vid1", "private", "succeeded"))

    def test_status_failure_does_not_undo_successful_upload(self) -> None:
        client = self._fake_client([YouTubeAPIError("YouTube Video Status HTTP 403: reason=insufficientPermissions")])
        code, out = self._run(client=client)
        self.assertEqual(code, 0)
        self.assertEqual(YouTubeUploadHistory(self.history).load()[0]["processing_status"], "UNKNOWN")
        self.assertIn("처리 상태 조회에 실패", out)

    def test_same_content_id_is_already_published_after_upload(self) -> None:
        save_archive([_record()], self.archive)
        save_approved_shorts_script(_record(), self.scripts_dir)
        code, _ = self._run("--content-id", "c1", "--knowledge-id", "k1")
        self.assertEqual((code, self.upload_calls), (0, 1))
        code, out = self._run("--content-id", "c1", "--knowledge-id", "k1", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("이미 YouTube 업로드 이력에 있습니다", out)
        code, out = self._run("--content-id", "c1", "--knowledge-id", "k1")  # live 재시도도 막힌다
        self.assertEqual(self.upload_calls, 1)
        self.assertEqual(len(YouTubeUploadHistory(self.history).load()), 1)

    def test_superseded_content_is_blocked_before_any_api_call(self) -> None:
        save_approved_shorts_script(_record(), self.scripts_dir)
        save_archive([_record(review_status="superseded", superseded_by="c2"), _record(content_id="c2")], self.archive)
        code, out = self._run("--content-id", "c1", "--knowledge-id", "k1")
        self.assertEqual(code, 1)
        self.assertIn("superseded", out.lower())
        self.assertEqual(self.upload_calls, 0)
        self.assertFalse(self.history.exists())


if __name__ == "__main__":
    unittest.main()
