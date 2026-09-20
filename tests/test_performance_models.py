"""content_engine.performance.models.PerformanceRecord 검증(6-01)."""

from __future__ import annotations

import unittest

from content_engine.performance.models import PerformanceRecord, PerformanceRecordError


def _record(**overrides) -> PerformanceRecord:
    fields = {
        "content_id": "content-perf-1",
        "knowledge_id": "knowledge-perf-1",
        "platform": "threads",
        "published_at": "2026-09-15T00:00:00+00:00",
        "metric_collected_at": "2026-09-16T00:00:00+00:00",
        "metrics": {"views": 100, "likes": 5},
        "source": "threads_api",
    }
    fields.update(overrides)
    return PerformanceRecord(**fields)


class PerformanceRecordCreationTests(unittest.TestCase):
    """A. PerformanceRecord 생성, B. content_id/knowledge_id 연결(필수 검증)."""

    def test_creates_with_all_fields(self):
        record = _record(title="테스트 제목", external_id="media-123")
        self.assertEqual(record.content_id, "content-perf-1")
        self.assertEqual(record.knowledge_id, "knowledge-perf-1")
        self.assertEqual(record.metrics["views"], 100)
        self.assertEqual(record.title, "테스트 제목")
        self.assertEqual(record.external_id, "media-123")

    def test_empty_content_id_rejected(self):
        with self.assertRaises(PerformanceRecordError):
            _record(content_id="")

    def test_empty_knowledge_id_rejected(self):
        with self.assertRaises(PerformanceRecordError):
            _record(knowledge_id="")

    def test_invalid_platform_rejected(self):
        with self.assertRaises(PerformanceRecordError):
            _record(platform="naver_cafe")

    def test_invalid_source_rejected(self):
        with self.assertRaises(PerformanceRecordError):
            _record(source="scraper")

    def test_missing_metric_collected_at_rejected(self):
        with self.assertRaises(PerformanceRecordError):
            _record(metric_collected_at="")

    def test_non_integer_metric_value_rejected(self):
        with self.assertRaises(PerformanceRecordError):
            _record(metrics={"views": "100"})

    def test_bool_metric_value_rejected(self):
        # bool은 int의 서브클래스라 isinstance(True, int)가 True다 - 의도적으로 막는다.
        with self.assertRaises(PerformanceRecordError):
            _record(metrics={"views": True})

    def test_empty_metrics_allowed(self):
        # migration_baseline처럼 "발행 사실만 있고 실제 지표는 아직 없음"을 표현해야 한다.
        record = _record(source="migration_baseline", metrics={})
        self.assertEqual(record.metrics, {})


class PerformanceRecordRoundTripTests(unittest.TestCase):
    def test_to_dict_and_from_dict_round_trip(self):
        record = _record(title="제목", external_id="media-1", raw={"data": [{"name": "views"}]})
        restored = PerformanceRecord.from_dict(record.to_dict())
        self.assertEqual(restored, record)

    def test_from_dict_defaults_missing_fields_safely(self):
        restored = PerformanceRecord.from_dict(
            {
                "content_id": "content-x",
                "knowledge_id": "knowledge-x",
                "platform": "blog",
                "metric_collected_at": "2026-09-16T00:00:00+00:00",
            }
        )
        self.assertEqual(restored.metrics, {})
        self.assertEqual(restored.source, "manual")
        self.assertEqual(restored.title, "")
        self.assertIsNone(restored.raw)

    def test_from_dict_converts_string_metric_values_to_int(self):
        # JSON에는 정수/문자열 구분이 있지만 사람이 실수로 문자열을 넣는 경우도 방어한다.
        restored = PerformanceRecord.from_dict(
            {
                "content_id": "content-x",
                "knowledge_id": "knowledge-x",
                "platform": "blog",
                "metric_collected_at": "2026-09-16T00:00:00+00:00",
                "metrics": {"views": "850"},
            }
        )
        self.assertEqual(restored.metrics["views"], 850)


if __name__ == "__main__":
    unittest.main()
