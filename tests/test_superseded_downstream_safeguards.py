"""6-19 — SUPERSEDED downstream 재발행 차단 검증
(docs/6-19-superseded-downstream-safeguards.md).

전부 synthetic fixture와 tempfile만 사용한다. 실제 production archive/
threads pending/publish log/ShortsScript/Blog pack 운영 파일은 어떤 테스트도
경로조차 참조하지 않는다(tests/test_media_superseded_lifecycle.py와 동일한
관례). 실제 Threads/YouTube API는 절대 호출하지 않는다 - 기존
tests/test_publish_approved_threads.py, tests/test_upload_youtube_short_cli.py와
동일하게 클라이언트를 patch한 Fake로 대체한다.

이 파일이 고정하는 것:
    1. Blog(archive 기반 Pack 생성)와 Shorts(archive 기반 Script 생성)는 이미
       review_status=="approved" 필터만으로 superseded 레코드를 자동 배제한다는
       회귀 방지 테스트(6-19 조사 결과 - 새 코드 없이 이미 안전함을 고정).
    2. Threads 발행 CLI(scripts/publish_approved_threads.py)가 production archive
       기준으로 superseded면 실제 Threads API를 호출하지 않고 차단한다는 것.
    3. YouTube 업로드 CLI(scripts/upload_youtube_short.py)가 --content-id가 주어졌을
       때 production archive 기준으로 superseded면 실제 YouTube API를 호출하지
       않고 차단한다는 것.
    4. ALREADY_PUBLISHED가 SUPERSEDED보다 항상 우선한다는 기존 정책이 두 CLI 모두
       유지된다는 것.
    5. 핵심 통합 시나리오(6-19 지시 14장): OLD가 approved로 승인되어 Threads
       pending/ShortsScript/Blog 후보가 이미 만들어진 뒤 NEW로 superseded되면,
       OLD의 세 플랫폼 발행/후보 선정이 모두 차단되고 NEW는 정상적으로 후보가
       된다는 것.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.blog_publish_pack import (
    build_blog_publish_pack_from_archive,
    select_approved_blog_candidates_from_archive,
)
from content_engine.media_archive import MediaArchiveRecord, upsert_archive
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.shorts_adapter import save_approved_shorts_script, shorts_script_output_path
from content_engine.threads_publisher import ThreadsAPIError, ThreadsClient, ThreadsPublishResult
from content_engine.threads_review import ThreadsPendingDraft, load_pending, mark_approved, save_pending
from content_engine.youtube_publisher import YouTubeClient, YouTubeUploadResult
from content_engine.youtube_upload_history import YouTubeUploadHistory, YouTubeUploadRecord
from scripts.generate_approved_shorts_script import main as shorts_cli_main
from scripts.publish_approved_threads import main as threads_publish_main
from scripts.upload_youtube_short import main as youtube_upload_main
from tak_brain import KnowledgeRecord


def _knowledge(**overrides) -> KnowledgeRecord:
    fields = dict(
        id="knowledge-6-19-1",
        source_url="https://example.test/6-19-article",
        title="원문 제목",
        article_type="experience",
        domain="자기계발",
        category="자기계발",
        knowledge_type="경험",
    )
    fields.update(overrides)
    return KnowledgeRecord(**fields)


def _record(**overrides) -> MediaArchiveRecord:
    base = dict(
        content_id="content-6-19-old",
        knowledge_id="knowledge-6-19-1",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="AI 재작성 제목",
        rewritten_body="AI가 재작성한 본문입니다.",
        source_url="https://example.test/6-19-article",
        evidence=(),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-19T00:00:00+00:00",
        review_status="approved",
    )
    base.update(overrides)
    return MediaArchiveRecord(**base)


class FakeThreadsClient:
    def __init__(self, result=None, error=None):
        self.result = result or ThreadsPublishResult(id="th_6_19_fake")
        self.error = error
        self.publish_text_calls: list[str] = []

    def publish_text(self, text: str, reply_control=None, topic_tag=None):
        self.publish_text_calls.append(text)
        if self.error is not None:
            raise self.error
        return self.result


class FakeYouTubeClient:
    def __init__(self, result=None, error=None):
        self.result = result or YouTubeUploadResult(video_id="yt_6_19_fake")
        self.error = error
        self.upload_short_calls: list[dict] = []

    def upload_short(self, **kwargs):
        self.upload_short_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def _make_temp_mp4() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.write(b"fake-mp4-bytes")
    handle.close()
    return Path(handle.name)


class _TempDirMixin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)


# --- A. Blog: 이미 안전함을 고정하는 회귀 테스트 --------------------------------


class BlogSupersededRegressionTests(_TempDirMixin):
    def test_superseded_blog_record_excluded_from_candidates(self):
        old = _record(
            content_id="content-blog-old",
            platform="blog",
            review_status="superseded",
            superseded_by="content-blog-new",
        )
        new = _record(
            content_id="content-blog-new",
            platform="blog",
            review_status="approved",
            knowledge_id="knowledge-6-19-1",
        )
        history = PublishHistory(self.tmp_path / "blog_publish_log.json")

        candidates = select_approved_blog_candidates_from_archive([old, new], history)

        content_ids = {record.content_id for record in candidates}
        self.assertNotIn("content-blog-old", content_ids)
        self.assertIn("content-blog-new", content_ids)

    def test_superseded_blog_record_excluded_from_pack(self):
        old = _record(
            content_id="content-blog-old-2",
            platform="blog",
            review_status="superseded",
            superseded_by="content-blog-new-2",
        )
        new = _record(
            content_id="content-blog-new-2",
            platform="blog",
            review_status="approved",
            knowledge_id="knowledge-6-19-1",
        )
        history = PublishHistory(self.tmp_path / "blog_publish_log.json")

        items = build_blog_publish_pack_from_archive([old, new], [_knowledge()], history)

        content_ids = {item.content_id for item in items}
        self.assertNotIn("content-blog-old-2", content_ids)
        self.assertIn("content-blog-new-2", content_ids)


# --- B. Shorts: 이미 안전함을 고정하는 회귀 테스트 -------------------------------


class ShortsSupersededRegressionTests(_TempDirMixin):
    def test_generate_shorts_script_cli_refuses_superseded_content_id(self):
        archive_path = self.tmp_path / "tak_media_archive.json"
        upsert_archive(
            archive_path,
            [
                _record(
                    content_id="content-shorts-old",
                    platform="shorts",
                    review_status="superseded",
                    superseded_by="content-shorts-new",
                )
            ],
        )
        output_dir = self.tmp_path / "shorts_scripts"

        exit_code = shorts_cli_main(
            [
                "--archive", str(archive_path),
                "--output-dir", str(output_dir),
                "--content-id", "content-shorts-old",
            ]
        )

        self.assertEqual(exit_code, 1)
        self.assertFalse(shorts_script_output_path(output_dir, "content-shorts-old").exists())

    def test_generate_shorts_script_cli_batch_mode_skips_superseded(self):
        archive_path = self.tmp_path / "tak_media_archive.json"
        upsert_archive(
            archive_path,
            [
                _record(
                    content_id="content-shorts-old-2",
                    platform="shorts",
                    review_status="superseded",
                    superseded_by="content-shorts-new-2",
                ),
                _record(
                    content_id="content-shorts-new-2",
                    platform="shorts",
                    review_status="approved",
                    original_body="첫 문단입니다.\n\n마지막 문단입니다.",
                ),
            ],
        )
        output_dir = self.tmp_path / "shorts_scripts"

        exit_code = shorts_cli_main(["--archive", str(archive_path), "--output-dir", str(output_dir)])

        self.assertEqual(exit_code, 0)
        self.assertFalse(shorts_script_output_path(output_dir, "content-shorts-old-2").exists())
        self.assertTrue(shorts_script_output_path(output_dir, "content-shorts-new-2").exists())


# --- C. Threads: 신규 supersede 차단 -------------------------------------------


class ThreadsSupersedeBlockTests(_TempDirMixin):
    def setUp(self) -> None:
        super().setUp()
        self.pending_path = self.tmp_path / "tak_threads_pending.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"

    def _seed_pending(self, *drafts: ThreadsPendingDraft) -> None:
        save_pending(list(drafts), self.pending_path)

    def _approved_draft(self, content_id: str, **overrides) -> ThreadsPendingDraft:
        fields = dict(
            content_id=content_id,
            knowledge_id="knowledge-6-19-1",
            source_url="https://example.test/6-19-article",
            evidence_unit_ids=("lesson:1",),
            article_type=None,
            knowledge_type="경험",
            original_title="원본 제목",
            original_body="원본 본문",
            ai_rewritten_title="AI 재작성 제목",
            ai_rewritten_body="AI 재작성 본문",
            status="pending",
            created_at="2026-09-19T00:00:00+00:00",
        )
        fields.update({k: v for k, v in overrides.items() if k not in ("final_title", "final_body")})
        draft = ThreadsPendingDraft(**fields)
        final_title = overrides.get("final_title", draft.ai_rewritten_title)
        final_body = overrides.get("final_body", draft.ai_rewritten_body)
        return mark_approved(draft, final_title=final_title, final_body=final_body, approved_at="2026-09-19T00:30:00+00:00")

    def _run(self, extra_args: list[str]) -> int:
        args = [
            "--input", str(self.pending_path),
            "--history", str(self.history_path),
            "--production-archive", str(self.archive_path),
        ]
        args.extend(extra_args)
        return threads_publish_main(args)

    def test_superseded_record_blocks_execute_without_api_call(self):
        draft = self._approved_draft("content-threads-old")
        self._seed_pending(draft)
        upsert_archive(
            self.archive_path,
            [
                _record(
                    content_id="content-threads-old",
                    platform="threads",
                    review_status="superseded",
                    superseded_by="content-threads-new",
                )
            ],
        )

        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("Threads API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(["--execute"])

        mocked.assert_not_called()
        self.assertEqual(exit_code, 1)
        reloaded = load_pending(self.pending_path)[0]
        self.assertEqual(reloaded.status, "approved")  # pending 파일은 그대로(변경 없음)
        self.assertFalse(self.history_path.exists())

    def test_superseded_record_blocks_dry_run_too(self):
        draft = self._approved_draft("content-threads-old-dry")
        self._seed_pending(draft)
        upsert_archive(
            self.archive_path,
            [
                _record(
                    content_id="content-threads-old-dry",
                    platform="threads",
                    review_status="superseded",
                    superseded_by="content-threads-new-dry",
                )
            ],
        )

        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("Threads API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(["--dry-run"])

        mocked.assert_not_called()
        self.assertEqual(exit_code, 1)

    def test_missing_archive_record_is_not_blocked_orphan_policy_preserved(self):
        """production archive 자체가 없거나(orphan) 이 content_id 레코드가 없으면
        기존처럼 차단하지 않는다(6-19는 ORPHAN 정책을 바꾸지 않는다)."""
        draft = self._approved_draft("content-threads-orphan")
        self._seed_pending(draft)
        # archive_path를 아예 만들지 않는다 -> load_archive는 빈 목록을 반환.

        fake_client = FakeThreadsClient()
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake_client.publish_text_calls, ["AI 재작성 본문"])

    def test_approved_active_record_is_not_blocked(self):
        draft = self._approved_draft("content-threads-active")
        self._seed_pending(draft)
        upsert_archive(
            self.archive_path,
            [_record(content_id="content-threads-active", platform="threads", review_status="approved")],
        )

        fake_client = FakeThreadsClient(result=ThreadsPublishResult(id="th_active"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--execute"])

        self.assertEqual(exit_code, 0)
        updated = load_pending(self.pending_path)[0]
        self.assertEqual(updated.status, "published")

    def test_already_published_takes_priority_over_superseded(self):
        """ALREADY_PUBLISHED가 SUPERSEDED보다 우선한다는 기존 Publish Readiness
        정책(content_engine.publish_audit)이 이 CLI에서도 유지되어야 한다."""
        draft = self._approved_draft("content-threads-already-published")
        self._seed_pending(draft)
        upsert_archive(
            self.archive_path,
            [
                _record(
                    content_id="content-threads-already-published",
                    platform="threads",
                    review_status="superseded",
                    superseded_by="content-threads-newer",
                )
            ],
        )
        PublishHistory(self.history_path).append(
            PublishRecord(
                content_id="content-threads-already-published",
                published_at="2026-09-18T00:00:00+00:00",
                threads_post_id="th_preexisting",
                knowledge_id="knowledge-6-19-1",
                platform="threads",
                source_url="https://example.test/6-19-article",
            )
        )

        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("Threads API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(["--execute"])

        mocked.assert_not_called()
        self.assertEqual(exit_code, 0)
        updated = load_pending(self.pending_path)[0]
        self.assertEqual(updated.status, "published")  # 기존 이력과 동기화됨(차단이 아님)
        self.assertEqual(updated.threads_post_id, "th_preexisting")


# --- D. YouTube 업로드: 신규 supersede 차단 -------------------------------------


class YouTubeUploadSupersedeBlockTests(_TempDirMixin):
    def setUp(self) -> None:
        super().setUp()
        self.video_path = _make_temp_mp4()
        self.addCleanup(self.video_path.unlink, missing_ok=True)
        self.history_path = self.tmp_path / "youtube_publish_log.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"

    def _run(self, extra_args: list[str]) -> int:
        args = [
            "--video", str(self.video_path),
            "--title", "6-19 테스트 제목",
            "--history", str(self.history_path),
            "--production-archive", str(self.archive_path),
        ]
        args.extend(extra_args)
        return youtube_upload_main(args)

    def test_superseded_content_id_blocks_execute_without_api_call(self):
        upsert_archive(
            self.archive_path,
            [
                _record(
                    content_id="content-yt-old",
                    platform="shorts",
                    review_status="superseded",
                    superseded_by="content-yt-new",
                )
            ],
        )

        with mock.patch.object(
            YouTubeClient, "from_environment", side_effect=AssertionError("YouTube API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(
                ["--content-id", "content-yt-old", "--knowledge-id", "knowledge-6-19-1"]
            )

        mocked.assert_not_called()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.history_path.exists())

    def test_superseded_content_id_blocks_dry_run_too(self):
        upsert_archive(
            self.archive_path,
            [
                _record(
                    content_id="content-yt-old-dry",
                    platform="shorts",
                    review_status="superseded",
                    superseded_by="content-yt-new-dry",
                )
            ],
        )

        with mock.patch.object(
            YouTubeClient, "from_environment", side_effect=AssertionError("YouTube API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(
                ["--content-id", "content-yt-old-dry", "--knowledge-id", "knowledge-6-19-1", "--dry-run"]
            )

        mocked.assert_not_called()
        self.assertEqual(exit_code, 1)

    def test_missing_content_id_skips_archive_check_backward_compatible(self):
        """--content-id를 생략한 기존 호출은 archive 검사를 아예 하지 않는다
        (기존 동작 그대로 - 판단 근거가 없기 때문)."""
        fake_client = FakeYouTubeClient()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_client.upload_short_calls), 1)

    def test_missing_archive_record_is_not_blocked_orphan_policy_preserved(self):
        fake_client = FakeYouTubeClient()
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(
                ["--content-id", "content-yt-orphan", "--knowledge-id", "knowledge-6-19-1"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_client.upload_short_calls), 1)

    def test_approved_active_record_is_not_blocked(self):
        upsert_archive(
            self.archive_path,
            [_record(content_id="content-yt-active", platform="shorts", review_status="approved")],
        )
        fake_client = FakeYouTubeClient(result=YouTubeUploadResult(video_id="yt_active"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = self._run(
                ["--content-id", "content-yt-active", "--knowledge-id", "knowledge-6-19-1"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_client.upload_short_calls), 1)

    def test_already_published_takes_priority_over_superseded(self):
        upsert_archive(
            self.archive_path,
            [
                _record(
                    content_id="content-yt-already-published",
                    platform="shorts",
                    review_status="superseded",
                    superseded_by="content-yt-newer",
                )
            ],
        )
        YouTubeUploadHistory(self.history_path).append(
            YouTubeUploadRecord(
                video_id="yt_preexisting",
                uploaded_at="2026-09-18T00:00:00+00:00",
                title="이전 업로드",
                privacy_status="private",
                content_id="content-yt-already-published",
                knowledge_id="knowledge-6-19-1",
            )
        )

        with mock.patch.object(
            YouTubeClient, "from_environment", side_effect=AssertionError("YouTube API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = self._run(
                ["--content-id", "content-yt-already-published", "--knowledge-id", "knowledge-6-19-1"]
            )

        mocked.assert_not_called()
        self.assertEqual(exit_code, 0)  # 차단(1)이 아니라 정상적인 idempotent skip(0)


# --- E. 핵심 통합 시나리오(6-19 지시 14장) ---------------------------------------


class EndToEndSupersedeDownstreamScenarioTests(_TempDirMixin):
    """OLD가 승인되어 세 플랫폼 downstream artifact가 이미 만들어진 뒤 NEW로
    supersede되면, OLD의 발행/후보 선정은 전부 차단되고 NEW는 정상 동작해야 한다."""

    def setUp(self) -> None:
        super().setUp()
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.threads_pending_path = self.tmp_path / "tak_threads_pending.json"
        self.threads_history_path = self.tmp_path / "threads_publish_log.json"
        self.blog_history_path = self.tmp_path / "blog_publish_log.json"
        self.youtube_history_path = self.tmp_path / "youtube_publish_log.json"
        self.shorts_scripts_dir = self.tmp_path / "shorts_scripts"
        self.video_path = _make_temp_mp4()
        self.addCleanup(self.video_path.unlink, missing_ok=True)

        # 1단계: OLD가 approved로 production archive에 존재하고, 이미 세 플랫폼
        # downstream artifact가 만들어져 있다.
        old_threads = _record(
            content_id="content-e2e-old-threads",
            platform="threads",
            knowledge_id="knowledge-e2e",
            review_status="approved",
        )
        old_shorts = _record(
            content_id="content-e2e-old-shorts",
            platform="shorts",
            knowledge_id="knowledge-e2e",
            review_status="approved",
            original_body="첫 문단입니다.\n\n마지막 문단입니다.",
        )
        old_blog = _record(
            content_id="content-e2e-old-blog",
            platform="blog",
            knowledge_id="knowledge-e2e",
            review_status="approved",
        )
        upsert_archive(self.archive_path, [old_threads, old_shorts, old_blog])

        # Threads pending(approved) 생성.
        draft = ThreadsPendingDraft(
            content_id="content-e2e-old-threads",
            knowledge_id="knowledge-e2e",
            source_url="https://example.test/6-19-article",
            evidence_unit_ids=("lesson:1",),
            article_type=None,
            knowledge_type="경험",
            original_title="원본 제목",
            original_body="원본 본문",
            ai_rewritten_title="AI 재작성 제목",
            ai_rewritten_body="AI 재작성 본문",
            status="pending",
            created_at="2026-09-19T00:00:00+00:00",
        )
        approved_draft = mark_approved(
            draft, final_title=draft.ai_rewritten_title, final_body=draft.ai_rewritten_body, approved_at="2026-09-19T00:30:00+00:00"
        )
        save_pending([approved_draft], self.threads_pending_path)

        # ShortsScript 생성.
        save_approved_shorts_script(old_shorts, self.shorts_scripts_dir)
        self.assertTrue(shorts_script_output_path(self.shorts_scripts_dir, "content-e2e-old-shorts").exists())

        # 2단계: OLD가 NEW로 대체된다(supersede) - NEW는 이미 promote되어 approved.
        new_threads = _record(
            content_id="content-e2e-new-threads",
            platform="threads",
            knowledge_id="knowledge-e2e",
            review_status="approved",
        )
        new_shorts = _record(
            content_id="content-e2e-new-shorts",
            platform="shorts",
            knowledge_id="knowledge-e2e",
            review_status="approved",
            original_body="새 첫 문단입니다.\n\n새 마지막 문단입니다.",
        )
        new_blog = _record(
            content_id="content-e2e-new-blog",
            platform="blog",
            knowledge_id="knowledge-e2e",
            review_status="approved",
        )
        superseded_old_threads = old_threads.__class__(
            **{**old_threads.to_dict(), "review_status": "superseded", "superseded_by": "content-e2e-new-threads"}
        )
        superseded_old_shorts = old_shorts.__class__(
            **{**old_shorts.to_dict(), "review_status": "superseded", "superseded_by": "content-e2e-new-shorts"}
        )
        superseded_old_blog = old_blog.__class__(
            **{**old_blog.to_dict(), "review_status": "superseded", "superseded_by": "content-e2e-new-blog"}
        )
        upsert_archive(
            self.archive_path,
            [
                superseded_old_threads,
                superseded_old_shorts,
                superseded_old_blog,
                new_threads,
                new_shorts,
                new_blog,
            ],
        )

    def test_old_threads_publish_is_blocked(self):
        with mock.patch.object(
            ThreadsClient, "from_environment", side_effect=AssertionError("Threads API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = threads_publish_main(
                [
                    "--input", str(self.threads_pending_path),
                    "--history", str(self.threads_history_path),
                    "--production-archive", str(self.archive_path),
                    "--execute",
                ]
            )
        mocked.assert_not_called()
        self.assertEqual(exit_code, 1)
        self.assertEqual(load_pending(self.threads_pending_path)[0].status, "approved")

    def test_old_shorts_upload_is_blocked(self):
        with mock.patch.object(
            YouTubeClient, "from_environment", side_effect=AssertionError("YouTube API가 호출되면 안 됩니다")
        ) as mocked:
            exit_code = youtube_upload_main(
                [
                    "--video", str(self.video_path),
                    "--title", "OLD 업로드 시도",
                    "--content-id", "content-e2e-old-shorts",
                    "--knowledge-id", "knowledge-e2e",
                    "--history", str(self.youtube_history_path),
                    "--production-archive", str(self.archive_path),
                ]
            )
        mocked.assert_not_called()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.youtube_history_path.exists())

    def test_old_blog_is_excluded_from_publish_pack(self):
        from content_engine.media_archive import load_archive

        records = load_archive(self.archive_path)
        history = PublishHistory(self.blog_history_path)
        items = build_blog_publish_pack_from_archive(records, [_knowledge(id="knowledge-e2e")], history)
        content_ids = {item.content_id for item in items}
        self.assertNotIn("content-e2e-old-blog", content_ids)

    def test_new_threads_candidate_publishes_normally(self):
        new_draft = ThreadsPendingDraft(
            content_id="content-e2e-new-threads",
            knowledge_id="knowledge-e2e",
            source_url="https://example.test/6-19-article",
            evidence_unit_ids=("lesson:1",),
            article_type=None,
            knowledge_type="경험",
            original_title="새 원본 제목",
            original_body="새 원본 본문",
            ai_rewritten_title="새 AI 재작성 제목",
            ai_rewritten_body="새 AI 재작성 본문",
            status="pending",
            created_at="2026-09-20T00:00:00+00:00",
        )
        approved_new_draft = mark_approved(
            new_draft,
            final_title=new_draft.ai_rewritten_title,
            final_body=new_draft.ai_rewritten_body,
            approved_at="2026-09-20T00:30:00+00:00",
        )
        save_pending([approved_new_draft], self.threads_pending_path)

        fake_client = FakeThreadsClient(result=ThreadsPublishResult(id="th_new_success"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = threads_publish_main(
                [
                    "--input", str(self.threads_pending_path),
                    "--history", str(self.threads_history_path),
                    "--production-archive", str(self.archive_path),
                    "--execute",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake_client.publish_text_calls, ["새 AI 재작성 본문"])
        self.assertEqual(load_pending(self.threads_pending_path)[0].status, "published")

    def test_new_shorts_candidate_uploads_normally(self):
        from content_engine.media_archive import load_archive

        records = load_archive(self.archive_path)
        new_shorts_record = next(r for r in records if r.content_id == "content-e2e-new-shorts")
        save_approved_shorts_script(new_shorts_record, self.shorts_scripts_dir)

        fake_client = FakeYouTubeClient(result=YouTubeUploadResult(video_id="yt_new_success"))
        with mock.patch.object(YouTubeClient, "from_environment", return_value=fake_client):
            exit_code = youtube_upload_main(
                [
                    "--video", str(self.video_path),
                    "--title", "NEW 업로드",
                    "--content-id", "content-e2e-new-shorts",
                    "--knowledge-id", "knowledge-e2e",
                    "--history", str(self.youtube_history_path),
                    "--production-archive", str(self.archive_path),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake_client.upload_short_calls), 1)

    def test_new_blog_candidate_is_included_in_publish_pack(self):
        from content_engine.media_archive import load_archive

        records = load_archive(self.archive_path)
        history = PublishHistory(self.blog_history_path)
        items = build_blog_publish_pack_from_archive(records, [_knowledge(id="knowledge-e2e")], history)
        content_ids = {item.content_id for item in items}
        self.assertIn("content-e2e-new-blog", content_ids)


if __name__ == "__main__":
    unittest.main()
