"""content_engine.performance.summary 검증(6-02).

Performance Dashboard 시계열 추이가 사용하는 순수 함수들. 파일 I/O가 없으므로
PerformanceRecord 목록을 직접 만들어 검증한다.
"""

from __future__ import annotations

import unittest

from content_engine.performance.models import PerformanceRecord
from content_engine.performance.summary import (
    pick_headline_metric,
    render_text_trend,
    summarize_content_history,
)


def _record(collected_at: str, metrics: dict[str, int], source: str = "threads_api", **overrides):
    fields = {
        "content_id": "content-1",
        "knowledge_id": "knowledge-1",
        "platform": "threads",
        "published_at": "2026-09-14T00:00:00+00:00",
        "metric_collected_at": collected_at,
        "metrics": metrics,
        "source": source,
    }
    fields.update(overrides)
    return PerformanceRecord(**fields)


class SummarizeContentHistoryTests(unittest.TestCase):
    def test_empty_list_returns_none(self):
        self.assertIsNone(summarize_content_history([]))

    def test_single_snapshot_has_no_previous_and_no_delta(self):
        record = _record("2026-09-15T00:00:00+00:00", {"views": 100})
        summary = summarize_content_history([record])

        self.assertEqual(summary.snapshot_count, 1)
        self.assertIsNone(summary.previous)
        self.assertEqual(summary.first, record)
        self.assertEqual(summary.latest, record)
        self.assertEqual(summary.metric_delta(), {})

    def test_multiple_snapshots_compute_delta_from_first_to_latest(self):
        records = [
            _record("2026-09-15T00:00:00+00:00", {"views": 100, "likes": 5}),
            _record("2026-09-17T00:00:00+00:00", {"views": 430, "likes": 20}),
            _record("2026-09-21T00:00:00+00:00", {"views": 2300, "likes": 80}),
        ]
        summary = summarize_content_history(records)

        self.assertEqual(summary.snapshot_count, 3)
        self.assertEqual(summary.first.metrics["views"], 100)
        self.assertEqual(summary.latest.metrics["views"], 2300)
        self.assertEqual(summary.previous.metrics["views"], 430)
        self.assertEqual(summary.metric_delta(), {"likes": 75, "views": 2200})
        self.assertEqual(summary.previous_metric_delta(), {"likes": 60, "views": 1870})

    def test_summarize_accepts_unordered_input(self):
        # 호출부가 정렬해서 넘기지 않아도 내부에서 시간순으로 재정렬해야 한다.
        records = [
            _record("2026-09-21T00:00:00+00:00", {"views": 2300}),
            _record("2026-09-15T00:00:00+00:00", {"views": 100}),
            _record("2026-09-17T00:00:00+00:00", {"views": 430}),
        ]
        summary = summarize_content_history(records)
        self.assertEqual(summary.first.metrics["views"], 100)
        self.assertEqual(summary.latest.metrics["views"], 2300)

    def test_metric_missing_in_first_snapshot_is_excluded_not_zero_filled(self):
        records = [
            _record("2026-09-15T00:00:00+00:00", {"views": 100}),  # likes 없음
            _record("2026-09-17T00:00:00+00:00", {"views": 430, "likes": 20}),
        ]
        summary = summarize_content_history(records)
        delta = summary.metric_delta()
        self.assertIn("views", delta)
        self.assertNotIn("likes", delta)  # 0으로 지어내지 않고 제외한다.

    def test_baseline_is_migration_flag(self):
        records = [
            _record("2026-09-14T00:00:00+00:00", {}, source="migration_baseline"),
            _record("2026-09-17T00:00:00+00:00", {"views": 430}),
        ]
        summary = summarize_content_history(records)
        self.assertTrue(summary.baseline_is_migration)

    def test_baseline_is_migration_false_for_real_first_snapshot(self):
        records = [_record("2026-09-15T00:00:00+00:00", {"views": 100}, source="threads_api")]
        summary = summarize_content_history(records)
        self.assertFalse(summary.baseline_is_migration)

    def test_history_holds_full_ordered_snapshots_not_just_first_previous_latest(self):
        # 스냅샷이 2개뿐이면 first == previous가 되므로, trend 렌더링이 history
        # 전체를 쓰지 않고 [first, previous, latest]를 조합하면 중복 값이 생긴다
        # (6-02에서 발견/수정된 버그) - history가 정확히 시간순 2건만 담아야 한다.
        records = [
            _record("2026-09-17T00:00:00+00:00", {"views": 850}),
            _record("2026-09-15T00:00:00+00:00", {"views": 100}),
        ]
        summary = summarize_content_history(records)
        self.assertEqual(summary.previous, summary.first)  # 2건일 때는 실제로 같은 레코드다.
        self.assertEqual([r.metrics["views"] for r in summary.history], [100, 850])


class PickHeadlineMetricTests(unittest.TestCase):
    def test_prefers_views_when_present(self):
        records = [_record("2026-09-15T00:00:00+00:00", {"likes": 5, "views": 100})]
        self.assertEqual(pick_headline_metric(records), "views")

    def test_falls_back_to_alphabetically_first_key_when_no_views(self):
        # Blog manual 입력처럼 "views"가 아예 없는 경우 - 임의로 지어내지 않고
        # 실제 존재하는 키 중에서만 고른다.
        records = [_record("2026-09-15T00:00:00+00:00", {"shares": 5, "comments": 2})]
        self.assertEqual(pick_headline_metric(records), "comments")

    def test_empty_records_returns_none(self):
        self.assertIsNone(pick_headline_metric([]))

    def test_records_with_no_metrics_returns_none(self):
        records = [_record("2026-09-15T00:00:00+00:00", {})]
        self.assertIsNone(pick_headline_metric(records))


class RenderTextTrendTests(unittest.TestCase):
    def test_renders_ordered_values_with_arrow_separator(self):
        records = [
            _record("2026-09-21T00:00:00+00:00", {"views": 2300}),
            _record("2026-09-15T00:00:00+00:00", {"views": 100}),
            _record("2026-09-17T00:00:00+00:00", {"views": 430}),
        ]
        self.assertEqual(render_text_trend(records, "views"), "100 → 430 → 2,300")

    def test_two_snapshots_do_not_duplicate_the_first_value(self):
        # summarize_content_history().history를 그대로 넘기는 Dashboard의 실제 사용
        # 패턴 - 스냅샷 2건이면 "100 → 850"이어야지 "100 → 100 → 850"이면 안 된다.
        records = [
            _record("2026-09-17T00:00:00+00:00", {"views": 850}),
            _record("2026-09-15T00:00:00+00:00", {"views": 100}),
        ]
        self.assertEqual(render_text_trend(records, "views"), "100 → 850")

    def test_skips_snapshots_missing_the_metric(self):
        records = [
            _record("2026-09-15T00:00:00+00:00", {"views": 100}),
            _record("2026-09-16T00:00:00+00:00", {"likes": 3}),  # views 없음 - 0으로 채우지 않음
            _record("2026-09-17T00:00:00+00:00", {"views": 430}),
        ]
        self.assertEqual(render_text_trend(records, "views"), "100 → 430")

    def test_no_matching_metric_returns_empty_string(self):
        records = [_record("2026-09-15T00:00:00+00:00", {"likes": 3})]
        self.assertEqual(render_text_trend(records, "views"), "")


if __name__ == "__main__":
    unittest.main()
