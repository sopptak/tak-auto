"""TAK AUTO 6-34 Performance Loop and Monetization Measurement
(docs/6-34-performance-loop-and-monetization-measurement.md).

6-01/6-02가 이미 content_engine/performance/(models.py/store.py/summary.py/
blog.py/threads.py/youtube.py/migration.py)와 91개 테스트를 구축해 두었다 -
PerformanceRecord schema, snapshot 저장/idempotency, content별 trend 요약,
Production Archive/Human Review 격리는 이미 VERIFIED다(기존
tests/test_performance_*.py, tests/test_collect_performance_*.py가 담당).
이 파일은 6-34에서 새로 채운 3개 모듈만 검증한다:

  1) content_engine/performance/window.py(신규) - 24h/72h/7d/30d 측정 구간 분류.
  2) content_engine/performance/quality.py(신규) - 음수/역전/감소 이상 감지(WARNING만, 저장은 막지 않음).
  3) content_engine/performance/store.py::snapshots_for_knowledge(신규) - KNOWLEDGE 단위 조회(합치지 않음).
  4) scripts/import_performance_snapshots.py(신규) - JSON 배열 일괄 import CLI.

그리고 이 세션이 새로 분석한 구조적 사실(content_id가 generation_id와
무관하게 안정적임, compute_content_id()가 original_*/evidence만 사용)을
회귀 테스트로 고정한다. 실제 외부 API는 호출하지 않는다. 실제 운영
data/tak_performance.json은 어디에서도 생성/수정하지 않는다 - 전부
tempfile이다.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.quality import check_metric_quality, quality_status, VALID, WARNING
from content_engine.performance.store import (
    append_snapshot,
    append_snapshots,
    load_snapshots,
    snapshots_for_knowledge,
)
from content_engine.performance.summary import summarize_content_history
from content_engine.performance.window import (
    WINDOW_24H,
    WINDOW_30D,
    WINDOW_72H,
    WINDOW_7D,
    WINDOW_BEYOND_30D,
    WINDOW_UNKNOWN,
    classify_measurement_window,
)
from content_engine.publish_history import compute_content_id

import scripts.import_performance_snapshots as import_cli


def _record(**overrides) -> PerformanceRecord:
    defaults = dict(
        content_id="content-1",
        knowledge_id="knowledge-1",
        platform="blog",
        published_at="2026-09-15T00:00:00+00:00",
        metric_collected_at="2026-09-16T00:00:00+00:00",
        metrics={"views": 100, "likes": 5},
        source="manual",
    )
    defaults.update(overrides)
    return PerformanceRecord(**defaults)


# --- Section 6/10: Measurement Window ---------------------------------------


class MeasurementWindowTests(unittest.TestCase):
    def test_24h_boundary(self) -> None:
        self.assertEqual(
            classify_measurement_window("2026-09-15T00:00:00+00:00", "2026-09-15T12:00:00+00:00"), WINDOW_24H
        )

    def test_72h_boundary(self) -> None:
        self.assertEqual(
            classify_measurement_window("2026-09-15T00:00:00+00:00", "2026-09-17T00:00:00+00:00"), WINDOW_72H
        )

    def test_7d_boundary(self) -> None:
        self.assertEqual(
            classify_measurement_window("2026-09-15T00:00:00+00:00", "2026-09-20T00:00:00+00:00"), WINDOW_7D
        )

    def test_30d_boundary(self) -> None:
        self.assertEqual(
            classify_measurement_window("2026-09-15T00:00:00+00:00", "2026-10-10T00:00:00+00:00"), WINDOW_30D
        )

    def test_beyond_30d(self) -> None:
        self.assertEqual(
            classify_measurement_window("2026-09-15T00:00:00+00:00", "2026-12-01T00:00:00+00:00"), WINDOW_BEYOND_30D
        )

    def test_unparseable_timestamp_is_unknown(self) -> None:
        self.assertEqual(classify_measurement_window("not-a-date", "2026-09-16T00:00:00+00:00"), WINDOW_UNKNOWN)

    def test_measured_before_published_is_unknown_not_negative(self) -> None:
        self.assertEqual(
            classify_measurement_window("2026-09-16T00:00:00+00:00", "2026-09-15T00:00:00+00:00"), WINDOW_UNKNOWN
        )


# --- Section 13: Data Quality (VALID/WARNING) --------------------------------


class MetricQualityTests(unittest.TestCase):
    def test_valid_metrics_have_no_issues(self) -> None:
        record = _record(metrics={"views": 100, "likes": 5})
        issues = check_metric_quality(record)
        self.assertEqual(issues, ())
        self.assertEqual(quality_status(issues), VALID)

    def test_negative_metric_is_warning(self) -> None:
        record = _record(metrics={"views": -1})
        issues = check_metric_quality(record)
        self.assertEqual(quality_status(issues), WARNING)
        self.assertTrue(any(i.code == "negative_metric" for i in issues))

    def test_likes_exceeding_views_is_warning(self) -> None:
        record = _record(metrics={"views": 5, "likes": 20})
        issues = check_metric_quality(record)
        self.assertTrue(any(i.code == "likes_exceed_views" for i in issues))

    def test_metric_decrease_vs_previous_is_warning(self) -> None:
        previous = _record(metric_collected_at="2026-09-16T00:00:00+00:00", metrics={"views": 500})
        current = _record(metric_collected_at="2026-09-17T00:00:00+00:00", metrics={"views": 100})
        issues = check_metric_quality(current, previous=previous)
        self.assertTrue(any(i.code == "metric_decreased" for i in issues))

    def test_quality_check_never_blocks_storage(self) -> None:
        """WARNING이 있어도 저장 자체는 막지 않는다(6-34 13장: BLOCKED는 구조적
        오류에만 쓴다) - append_snapshot이 정상적으로 성공함을 확인한다."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "perf.json"
            record = _record(metrics={"views": -5, "likes": 999})
            issues = check_metric_quality(record)
            self.assertEqual(quality_status(issues), WARNING)
            added = append_snapshot(path, record)
            self.assertTrue(added)
            self.assertEqual(len(load_snapshots(path)), 1)


# --- Section 9/10: KNOWLEDGE 단위 조회(합치지 않음, superseded 보존) ------------


class KnowledgeGroupedSnapshotsTests(unittest.TestCase):
    def test_multiple_content_ids_under_same_knowledge_are_grouped_not_merged(self) -> None:
        """같은 KNOWLEDGE에서 OLD(superseded)와 NEW(현재 활성) content_id가
        모두 성과를 갖고 있어도, snapshots_for_knowledge()는 절대 합치지
        않고 content_id별로 분리해서 반환해야 한다(6-34 10장 핵심)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "perf.json"
            append_snapshots(
                path,
                [
                    _record(content_id="content-OLD", knowledge_id="knowledge-1", metrics={"views": 1000}),
                    _record(content_id="content-NEW", knowledge_id="knowledge-1", metrics={"views": 50}),
                    _record(content_id="content-unrelated", knowledge_id="knowledge-2", metrics={"views": 9999}),
                ],
            )
            grouped = snapshots_for_knowledge(path, "knowledge-1")
            self.assertEqual(set(grouped.keys()), {"content-OLD", "content-NEW"})
            self.assertEqual(grouped["content-OLD"][0].metrics["views"], 1000)
            self.assertEqual(grouped["content-NEW"][0].metrics["views"], 50)
            self.assertNotIn("content-unrelated", grouped)

    def test_superseded_old_content_performance_is_never_deleted_or_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "perf.json"
            old_snapshot_1 = _record(content_id="content-OLD", metric_collected_at="2026-09-16T00:00:00+00:00", metrics={"views": 100})
            old_snapshot_2 = _record(content_id="content-OLD", metric_collected_at="2026-09-17T00:00:00+00:00", metrics={"views": 300})
            append_snapshots(path, [old_snapshot_1, old_snapshot_2])

            # OLD가 superseded된 이후에도(운영상 사실일 뿐, 이 저장소는 review_status를
            # 전혀 모른다) 기존 스냅샷은 그대로 남아 있어야 한다 - 삭제하지 않는다.
            summary = summarize_content_history(load_snapshots(path))
            self.assertEqual(summary.snapshot_count, 2)
            self.assertEqual(summary.latest.metrics["views"], 300)
            self.assertEqual(summary.first.metrics["views"], 100)


# --- Section 12: Content Fingerprint / generation_id 분석(회귀 고정) -----------


class ContentIdGenerationIndependenceTests(unittest.TestCase):
    """6-34에서 분석한 핵심 사실: compute_content_id()는 original_title/
    original_body/evidence_unit_ids/knowledge_id/platform/source_url만
    사용하고 rewritten_*(LLM 출력, generation마다 달라짐)는 쓰지 않는다 -
    따라서 같은 슬롯의 서로 다른 generation_id는 (원본이 같다면) 항상 같은
    content_id를 만든다. 이는 Performance가 generation_id를 필수 key로
    가질 필요가 없다는 6-34 11장 결론의 근거이므로 회귀 테스트로 고정한다."""

    def test_content_id_is_stable_across_different_generation_ids(self) -> None:
        item = {
            "knowledge_id": "knowledge-1",
            "platform": "blog",
            "source_url": "https://example.test/1",
            "evidence_unit_ids": ["lesson:1"],
            "original_title": "원본 제목",
            "original_body": "원본 본문",
        }
        item_generation_a = {**item, "rewritten_title": "재작성 A", "rewritten_body": "재작성 본문 A"}
        item_generation_b = {**item, "rewritten_title": "완전히 다른 재작성 B", "rewritten_body": "전혀 다른 본문 B"}

        self.assertEqual(compute_content_id(item_generation_a), compute_content_id(item_generation_b))

    def test_content_id_changes_when_original_content_changes(self) -> None:
        base = {
            "knowledge_id": "knowledge-1", "platform": "blog", "source_url": "https://example.test/1",
            "evidence_unit_ids": ["lesson:1"], "original_title": "원본 제목", "original_body": "원본 본문",
        }
        corrected = {**base, "original_body": "정정된 원본 본문"}
        self.assertNotEqual(compute_content_id(base), compute_content_id(corrected))


# --- Section 21/22: Manual Import CLI (bulk, idempotent) ----------------------


class ImportPerformanceSnapshotsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.input_path = self.tmp_path / "input.json"
        self.output_path = self.tmp_path / "perf.json"

    def _write_input(self, records: list[dict]) -> None:
        self.input_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def test_bulk_import_adds_all_records(self) -> None:
        self._write_input(
            [
                _record(content_id="c1").to_dict(),
                _record(content_id="c2").to_dict(),
            ]
        )
        exit_code = import_cli.main(["--input", str(self.input_path), "--output", str(self.output_path)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(load_snapshots(self.output_path)), 2)

    def test_reimporting_same_file_is_idempotent(self) -> None:
        self._write_input([_record(content_id="c1").to_dict()])
        import_cli.main(["--input", str(self.input_path), "--output", str(self.output_path)])
        import_cli.main(["--input", str(self.input_path), "--output", str(self.output_path)])
        self.assertEqual(len(load_snapshots(self.output_path)), 1, "같은 파일을 두 번 import해도 중복 저장되면 안 된다.")

    def test_malformed_json_is_rejected_without_writing(self) -> None:
        self.input_path.write_text("{not valid json", encoding="utf-8")
        exit_code = import_cli.main(["--input", str(self.input_path), "--output", str(self.output_path)])
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())

    def test_missing_content_id_is_rejected(self) -> None:
        self._write_input([{"knowledge_id": "k1", "platform": "blog", "published_at": "x", "metric_collected_at": "y", "metrics": {}}])
        exit_code = import_cli.main(["--input", str(self.input_path), "--output", str(self.output_path)])
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())

    def test_unknown_platform_is_rejected(self) -> None:
        self._write_input(
            [
                {
                    "content_id": "c1", "knowledge_id": "k1", "platform": "tiktok",
                    "published_at": "2026-01-01T00:00:00Z", "metric_collected_at": "2026-01-02T00:00:00Z",
                    "metrics": {},
                }
            ]
        )
        exit_code = import_cli.main(["--input", str(self.input_path), "--output", str(self.output_path)])
        self.assertEqual(exit_code, 1)

    def test_missing_input_file_is_rejected(self) -> None:
        exit_code = import_cli.main(
            ["--input", str(self.tmp_path / "does_not_exist.json"), "--output", str(self.output_path)]
        )
        self.assertEqual(exit_code, 1)


# --- Section 27: 17개 신규 테스트 카테고리 중 아직 신규 파일이 다루지 않은 것 ---


class TraceabilityAndE2ETests(unittest.TestCase):
    """content/generation/knowledge traceability + full performance E2E.
    content_id/knowledge_id 추적성 자체는 6-28/6-31/6-32/6-33에서 이미 여러
    번 검증했다(MediaArchiveRecord.from_item()) - 여기서는 Performance
    레이어까지 연결되는 마지막 구간만 새로 검증한다."""

    def test_full_publish_to_performance_chain(self) -> None:
        """PUBLISH READINESS까지 도달한 콘텐츠(6-33 First Content Rehearsal과
        동일한 패턴)의 content_id/knowledge_id가 Performance 스냅샷에도 그대로
        이어지는지 확인한다 - 새 ID를 만들지 않는다."""
        record = MediaArchiveRecord(
            content_id="content-e2e-1",
            knowledge_id="knowledge-e2e-1",
            platform="threads",
            generation_status="valid",
            original_title="원본",
            original_body="원본 본문",
            rewritten_title="재작성",
            rewritten_body="재작성 본문",
            source_url="https://example.test/e2e",
            evidence=(),
            evidence_unit_ids=("lesson:1",),
            created_at="2026-09-14T00:00:00+00:00",
            review_status="approved",
        )
        with tempfile.TemporaryDirectory() as tmp:
            performance_path = Path(tmp) / "perf.json"
            snapshot = PerformanceRecord(
                content_id=record.content_id,
                knowledge_id=record.knowledge_id,
                platform=record.platform,
                published_at="2026-09-14T01:00:00+00:00",
                metric_collected_at="2026-09-15T01:00:00+00:00",
                metrics={"views": 120, "likes": 8},
                source="threads_api",
            )
            append_snapshot(performance_path, snapshot)

            loaded = load_snapshots(performance_path)
            self.assertEqual(loaded[0].content_id, record.content_id)
            self.assertEqual(loaded[0].knowledge_id, record.knowledge_id)
            self.assertEqual(loaded[0].platform, record.platform)

    def test_attribution_direct_vs_indirect_is_distinguishable_by_source(self) -> None:
        """6-34 16장(Attribution): 직접 측정 가능한 것(API/manual)과 추정이
        필요한 것을 이 저장소는 ``source`` 필드로 이미 구분하고 있다 -
        "migration_baseline"은 실제 성과가 아니라 발행 사실만 옮긴
        placeholder임을 summary.py의 baseline_is_migration이 명시적으로
        표시한다(새 attribution 모델을 만들지 않고 기존 필드 재사용)."""
        baseline = _record(source="migration_baseline", metrics={})
        real = _record(source="threads_api", metric_collected_at="2026-09-17T00:00:00+00:00", metrics={"views": 50})
        summary = summarize_content_history([baseline, real])
        self.assertTrue(summary.baseline_is_migration)


if __name__ == "__main__":
    unittest.main()
