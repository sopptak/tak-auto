"""성과(Performance) 데이터가 기존 저장소를 건드리지 않는지 검증(6-01).

J. performance 데이터가 기존 archive를 변경하지 않음
K. 기존 publish history 변경 없음
L. 기존 MEDIA 승인 상태 변경 없음

전부 같은 임시 디렉터리에 기존 저장소(archive/threads pending/publish history)를
먼저 만들어두고, 성과 저장소에 스냅샷을 추가/조회한 뒤 그 파일들이 바이트 단위로
그대로인지 비교하는 방식으로 확인한다 - "관련 코드가 없다"는 정적 근거뿐 아니라
실제로 파일이 안 바뀐다는 것을 직접 실행해서 증명한다.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot, latest_snapshot_per_content
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_review import ThreadsPendingDraft, upsert_pending


class PerformanceDoesNotTouchExistingStoresTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.directory = Path(self.tmp_dir.name)

        self.archive_path = self.directory / "tak_media_archive.json"
        self.publish_history_path = self.directory / "threads_publish_log.json"
        self.pending_path = self.directory / "tak_threads_pending.json"
        self.performance_path = self.directory / "tak_performance.json"

        upsert_archive(
            self.archive_path,
            [
                MediaArchiveRecord(
                    content_id="content-1",
                    knowledge_id="knowledge-1",
                    platform="threads",
                    generation_status="valid",
                    original_title="원본",
                    original_body="원본 본문",
                    rewritten_title="AI 제목",
                    rewritten_body="AI 본문",
                    source_url="https://example.test/a",
                    evidence=(),
                    evidence_unit_ids=("lesson:1",),
                    created_at="2026-09-14T00:00:00+00:00",
                    review_status="approved",
                )
            ],
        )
        history = PublishHistory(self.publish_history_path)
        history.append(
            PublishRecord(
                content_id="content-1",
                published_at="2026-09-14T01:00:00+00:00",
                threads_post_id="18114019807999154",
                knowledge_id="knowledge-1",
                platform="threads",
            )
        )
        upsert_pending(
            self.pending_path,
            ThreadsPendingDraft(
                content_id="content-1",
                knowledge_id="knowledge-1",
                source_url="https://example.test/a",
                evidence_unit_ids=("lesson:1",),
                article_type="experience",
                knowledge_type="경험",
                original_title="원본",
                original_body="원본 본문",
                ai_rewritten_title="AI 제목",
                ai_rewritten_body="AI 본문",
                status="pending",
                created_at="2026-09-14T00:00:00+00:00",
            ),
        )

    def _snapshot_all_files(self) -> dict[str, str]:
        return {
            "archive": self.archive_path.read_text(encoding="utf-8"),
            "publish_history": self.publish_history_path.read_text(encoding="utf-8"),
            "pending": self.pending_path.read_text(encoding="utf-8"),
        }

    def test_appending_performance_snapshot_leaves_other_stores_untouched(self):
        before = self._snapshot_all_files()

        record = PerformanceRecord(
            content_id="content-1",
            knowledge_id="knowledge-1",
            platform="threads",
            published_at="2026-09-14T01:00:00+00:00",
            metric_collected_at="2026-09-17T00:00:00+00:00",
            metrics={"views": 500, "likes": 30},
            source="threads_api",
        )
        added = append_snapshot(self.performance_path, record)
        self.assertTrue(added)

        after = self._snapshot_all_files()
        self.assertEqual(before, after)

        # archive의 review_status(승인 상태)도 여전히 approved 그대로여야 한다.
        archive_record = load_archive(self.archive_path)[0]
        self.assertEqual(archive_record.review_status, "approved")

    def test_reading_latest_snapshot_does_not_write_anything(self):
        append_snapshot(
            self.performance_path,
            PerformanceRecord(
                content_id="content-1",
                knowledge_id="knowledge-1",
                platform="threads",
                published_at="2026-09-14T01:00:00+00:00",
                metric_collected_at="2026-09-17T00:00:00+00:00",
                metrics={"views": 500},
                source="threads_api",
            ),
        )
        before = self._snapshot_all_files()

        latest_snapshot_per_content(self.performance_path)
        latest_snapshot_per_content(self.performance_path)

        after = self._snapshot_all_files()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
