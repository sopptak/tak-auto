"""content_engine.performance.store 검증(6-01).

C. snapshot 여러 개 저장(시계열), D. 동일 snapshot 중복 방지,
J/K/L(다른 저장소를 건드리지 않음)은 별도로 tests/test_performance_isolation.py에서 확인한다.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import (
    append_snapshot,
    append_snapshots,
    latest_snapshot_per_content,
    load_snapshots,
    snapshots_for_content,
)


def _record(content_id="content-1", collected_at="2026-09-15T00:00:00+00:00", views=100, **overrides):
    fields = {
        "content_id": content_id,
        "knowledge_id": "knowledge-1",
        "platform": "threads",
        "published_at": "2026-09-14T00:00:00+00:00",
        "metric_collected_at": collected_at,
        "metrics": {"views": views},
        "source": "threads_api",
    }
    fields.update(overrides)
    return PerformanceRecord(**fields)


class PerformanceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.path = Path(self.tmp_dir.name) / "tak_performance.json"

    def test_load_missing_file_returns_empty_list(self):
        self.assertEqual(load_snapshots(self.path), [])

    def test_append_snapshot_creates_file_and_directory(self):
        nested_path = Path(self.tmp_dir.name) / "nested" / "tak_performance.json"
        added = append_snapshot(nested_path, _record())
        self.assertTrue(added)
        self.assertTrue(nested_path.exists())
        self.assertEqual(len(load_snapshots(nested_path)), 1)

    # --- C. 여러 스냅샷(시계열) 저장 -------------------------------------------

    def test_multiple_snapshots_for_same_content_are_all_kept(self):
        append_snapshot(self.path, _record(collected_at="2026-09-15T00:00:00+00:00", views=100))
        append_snapshot(self.path, _record(collected_at="2026-09-17T00:00:00+00:00", views=850))
        append_snapshot(self.path, _record(collected_at="2026-09-21T00:00:00+00:00", views=2300))

        history = snapshots_for_content(self.path, "content-1")
        self.assertEqual(len(history), 3)
        self.assertEqual([r.metrics["views"] for r in history], [100, 850, 2300])
        # 오름차순(수집 시각 기준)으로 반환되어야 Day1->Day7 변화를 그대로 읽을 수 있다.
        self.assertEqual([r.metric_collected_at for r in history], sorted(r.metric_collected_at for r in history))

    def test_latest_snapshot_per_content_picks_most_recent(self):
        append_snapshot(self.path, _record(collected_at="2026-09-15T00:00:00+00:00", views=100))
        append_snapshot(self.path, _record(collected_at="2026-09-17T00:00:00+00:00", views=850))
        append_snapshot(self.path, _record(content_id="content-2", collected_at="2026-09-16T00:00:00+00:00", views=5))

        latest = latest_snapshot_per_content(self.path)
        self.assertEqual(set(latest.keys()), {"content-1", "content-2"})
        self.assertEqual(latest["content-1"].metrics["views"], 850)
        self.assertEqual(latest["content-2"].metrics["views"], 5)

    # --- D. 동일 snapshot 중복 방지 --------------------------------------------

    def test_duplicate_snapshot_is_not_added_twice(self):
        record = _record(collected_at="2026-09-15T00:00:00+00:00", views=100)
        first_added = append_snapshot(self.path, record)
        second_added = append_snapshot(self.path, record)

        self.assertTrue(first_added)
        self.assertFalse(second_added)
        self.assertEqual(len(load_snapshots(self.path)), 1)

    def test_same_content_different_collected_at_is_not_a_duplicate(self):
        append_snapshot(self.path, _record(collected_at="2026-09-15T00:00:00+00:00", views=100))
        added = append_snapshot(self.path, _record(collected_at="2026-09-16T00:00:00+00:00", views=200))
        self.assertTrue(added)
        self.assertEqual(len(load_snapshots(self.path)), 2)

    def test_append_snapshots_batches_writes_and_returns_added_count(self):
        records = [
            _record(collected_at="2026-09-15T00:00:00+00:00", views=100),
            _record(collected_at="2026-09-16T00:00:00+00:00", views=150),
        ]
        added = append_snapshots(self.path, records)
        self.assertEqual(added, 2)

        # 재실행(같은 레코드 2건 + 새 레코드 1건) - 새 1건만 추가되어야 한다.
        more_records = records + [_record(collected_at="2026-09-17T00:00:00+00:00", views=200)]
        added_again = append_snapshots(self.path, more_records)
        self.assertEqual(added_again, 1)
        self.assertEqual(len(load_snapshots(self.path)), 3)

    def test_load_rejects_non_list_json(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"not": "a list"}', encoding="utf-8")
        with self.assertRaises(Exception):
            load_snapshots(self.path)

    # --- 6-02: 중복 판정 키에 source를 포함하지 않는다는 설계 결정을 고정 -----------

    def test_same_content_and_time_different_source_is_still_a_duplicate(self):
        """의도된 동작이다(store.py의 _snapshot_key 문서 참고) - 버그가 아니다."""
        append_snapshot(
            self.path,
            _record(collected_at="2026-09-15T00:00:00+00:00", views=100, source="threads_api"),
        )
        added = append_snapshot(
            self.path,
            _record(collected_at="2026-09-15T00:00:00+00:00", views=999, source="manual"),
        )
        self.assertFalse(added)
        snapshots = load_snapshots(self.path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].metrics["views"], 100)  # 먼저 저장된 값이 유지된다.

    # --- 6-02: timezone-naive/aware가 섞여도 시간 순서가 안정적이어야 한다 ----------

    def test_naive_and_aware_timestamps_sort_by_actual_time_not_lexicographically(self):
        # tz-naive("2026-09-16T12:00:00")는 UTC로 간주된다. 문자열만 비교하면
        # "2026-09-16T12:00:00" < "2026-09-17T00:00:00+09:00"이지만, 후자는
        # UTC로 2026-09-16T15:00:00이라 실제로는 naive 값보다 더 나중 시각이다 -
        # 이 케이스는 문자열 비교와 실제 시간 비교가 같은 순서를 내므로, 아래
        # test_timezone_offset_changes_actual_chronological_order가 실제
        # 차이를 만드는 결정적 케이스다.
        append_snapshot(self.path, _record(collected_at="2026-09-16T12:00:00", views=100))
        append_snapshot(self.path, _record(collected_at="2026-09-17T00:00:00+09:00", views=200))

        history = snapshots_for_content(self.path, "content-1")
        self.assertEqual([r.metrics["views"] for r in history], [100, 200])

    def test_timezone_offset_changes_actual_chronological_order(self):
        # "2026-09-16T23:00:00+09:00"의 실제 UTC 시각은 2026-09-16T14:00:00 -
        # "2026-09-17T00:00:00+00:00"(UTC 그대로)보다 이르다. 문자열 사전식
        # 비교라면 "23:00:00+09:00" > "00:00:00+00:00"이라 거꾸로 정렬됐을 것이다.
        append_snapshot(self.path, _record(collected_at="2026-09-17T00:00:00+00:00", views=200))
        append_snapshot(self.path, _record(collected_at="2026-09-16T23:00:00+09:00", views=100))

        history = snapshots_for_content(self.path, "content-1")
        self.assertEqual([r.metrics["views"] for r in history], [100, 200])

    def test_latest_snapshot_per_content_respects_actual_timezone_order(self):
        append_snapshot(self.path, _record(collected_at="2026-09-17T00:00:00+00:00", views=200))
        append_snapshot(self.path, _record(collected_at="2026-09-16T23:00:00+09:00", views=100))

        latest = latest_snapshot_per_content(self.path)
        self.assertEqual(latest["content-1"].metrics["views"], 200)

    def test_unparseable_collected_at_does_not_crash_sorting(self):
        append_snapshot(self.path, _record(collected_at="not-a-valid-timestamp", views=1))
        append_snapshot(self.path, _record(collected_at="2026-09-17T00:00:00+00:00", views=2))

        history = snapshots_for_content(self.path, "content-1")
        self.assertEqual(len(history), 2)  # 예외 없이 둘 다 반환되면 충분하다.


if __name__ == "__main__":
    unittest.main()
