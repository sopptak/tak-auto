"""TAK AUTO 6-35 Performance Feedback Loop
(docs/6-35-performance-feedback-loop.md).

PERFORMANCE(원자료) -> ANALYSIS -> INSIGHT CANDIDATE -> HUMAN REVIEW ->
CONTENT STRATEGY INPUT를 검증한다. Insight는 6-34의 Performance 원자료와
완전히 분리된 별도 모듈(``content_engine/performance_insight.py``)이다 -
이 파일은 Insight 분석/저장이 Performance 원자료를 절대 건드리지 않고,
KNOWLEDGE/MEDIA를 자동으로 수정하지 않으며, 사람이 검토하기 전까지는
"candidate" 상태로만 남는다는 것을 검증한다.

실제 외부 API는 호출하지 않는다. 실제 운영 데이터(data/tak_performance.json,
data/tak_performance_insights.json 포함)는 어디에서도 생성/수정하지 않는다 -
전부 tempfile이다.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot, append_snapshots, load_snapshots
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_review import ThreadsPendingDraft, upsert_pending
from content_engine.performance_insight import (
    ABOVE_BASELINE,
    BELOW_BASELINE,
    CONSISTENT,
    INCOMPARABLE,
    INCONSISTENT,
    INSUFFICIENT_SAMPLE,
    MEDIA_PLATFORM_TO_PERFORMANCE_PLATFORM,
    MIN_SAMPLE_SIZE,
    NEAR_BASELINE,
    NO_OUTLIER,
    OUTLIER_DETECTED,
    STATUS_ACCEPTED,
    STATUS_CANDIDATE,
    STATUS_REJECTED,
    TREND_DECREASING,
    TREND_INCREASING,
    TREND_STABLE,
    InsightError,
    InsightRecord,
    analyze_trend,
    append_insight,
    append_insights,
    check_comparable,
    check_traceability,
    compare_to_baseline,
    compute_insight_id,
    detect_anomaly,
    insights_for_scope,
    load_insights,
    set_insight_status,
)
import scripts.analyze_performance as analyze_cli


def _perf(**overrides) -> PerformanceRecord:
    defaults = dict(
        content_id="content-1",
        knowledge_id="knowledge-1",
        platform="blog",
        published_at="2026-09-01T00:00:00+00:00",
        metric_collected_at="2026-09-02T00:00:00+00:00",
        metrics={"views": 100},
        source="manual",
    )
    defaults.update(overrides)
    return PerformanceRecord(**defaults)


def _series(values: list[int], **overrides) -> list[PerformanceRecord]:
    return [
        _perf(metric_collected_at=f"2026-09-{i + 1:02d}T00:00:00+00:00", metrics={"views": v}, **overrides)
        for i, v in enumerate(values)
    ]


# --- 1. schema ------------------------------------------------------------------


class InsightRecordSchemaTests(unittest.TestCase):
    def test_round_trip_to_dict_from_dict(self) -> None:
        record = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
        restored = InsightRecord.from_dict(record.to_dict())
        self.assertEqual(record, restored)

    def test_invalid_scope_is_rejected(self) -> None:
        with self.assertRaises(InsightError):
            InsightRecord(
                insight_id="x", created_at="t", analysis_window="all", scope="not-a-scope",
                scope_id="c1", platform="blog", metric="views", insight_type="trend",
                result="X", observation="",
            )

    def test_invalid_status_is_rejected(self) -> None:
        with self.assertRaises(InsightError):
            InsightRecord(
                insight_id="x", created_at="t", analysis_window="all", scope="content",
                scope_id="c1", platform="blog", metric="views", insight_type="trend",
                result="X", observation="", status="not-a-status",
            )

    def test_no_confidence_field_exists(self) -> None:
        """5장 지시: 근거 없는 confidence 점수를 만들지 않는다 - 필드 자체가 없다."""
        record = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertNotIn("confidence", record.to_dict())


# --- 2. trend / 9. trend(A/B/C synthetic) ----------------------------------------


class TrendTests(unittest.TestCase):
    def test_series_a_increasing(self) -> None:
        r = analyze_trend(_series([100, 120, 150, 180]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, TREND_INCREASING)

    def test_series_b_decreasing(self) -> None:
        r = analyze_trend(_series([180, 150, 120, 100]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, TREND_DECREASING)

    def test_series_c_stable(self) -> None:
        r = analyze_trend(_series([100, 100, 100, 100]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, TREND_STABLE)

    def test_insufficient_data_is_unknown_not_forced(self) -> None:
        r = analyze_trend(_series([100]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, INSUFFICIENT_SAMPLE)

    def test_explainability_observation_shows_raw_series(self) -> None:
        r = analyze_trend(_series([100, 120, 150, 180]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertIn("100", r.observation)
        self.assertIn("180", r.observation)
        self.assertIn("INCREASING", r.observation)


# --- 4. minimum sample(1/2/3/5/10/20) --------------------------------------------


class MinimumSampleTests(unittest.TestCase):
    def test_sample_sizes_1_and_2_are_insufficient(self) -> None:
        for n in (1, 2):
            r = analyze_trend(_series([100] * n), scope="content", scope_id="c1", platform="blog", metric="views")
            self.assertEqual(r.result, INSUFFICIENT_SAMPLE, f"n={n}")

    def test_sample_sizes_3_5_10_20_proceed(self) -> None:
        for n in (3, 5, 10, 20):
            r = analyze_trend(_series([100] * n), scope="content", scope_id="c1", platform="blog", metric="views")
            self.assertNotEqual(r.result, INSUFFICIENT_SAMPLE, f"n={n}")
            self.assertEqual(r.sample_size, n)

    def test_min_sample_size_constant_is_3(self) -> None:
        self.assertEqual(MIN_SAMPLE_SIZE, 3)


# --- 5. outlier -------------------------------------------------------------------


class OutlierTests(unittest.TestCase):
    def test_extreme_last_value_is_outlier(self) -> None:
        r = detect_anomaly(_series([100, 110, 120, 115, 10000]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, OUTLIER_DETECTED)

    def test_normal_series_is_not_outlier(self) -> None:
        r = detect_anomaly(_series([100, 110, 120, 115, 118]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, NO_OUTLIER)

    def test_outlier_insufficient_sample(self) -> None:
        r = detect_anomaly(_series([100, 200]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(r.result, INSUFFICIENT_SAMPLE)


# --- 6/11. platform separation / comparison rules ---------------------------------


class ComparabilityTests(unittest.TestCase):
    def test_youtube_24h_vs_blog_30d_is_not_comparable(self) -> None:
        self.assertFalse(check_comparable(platform_a="youtube", window_a="24h", platform_b="blog", window_b="30d"))

    def test_same_platform_and_window_is_comparable(self) -> None:
        self.assertTrue(check_comparable(platform_a="threads", window_a="7d", platform_b="threads", window_b="7d"))

    def test_compare_to_baseline_returns_incomparable_on_platform_mismatch(self) -> None:
        baseline_records = _series([100, 110, 120], platform="blog")
        r = compare_to_baseline(
            500, baseline_records, scope="content", scope_id="c1", platform="blog", metric="views",
            analysis_window="30d", target_platform="youtube",
        )
        self.assertEqual(r.result, INCOMPARABLE)

    def test_compare_to_baseline_returns_incomparable_on_window_mismatch(self) -> None:
        baseline_records = _series([100, 110, 120], platform="blog")
        r = compare_to_baseline(
            500, baseline_records, scope="content", scope_id="c1", platform="blog", metric="views",
            analysis_window="30d", target_window="24h",
        )
        self.assertEqual(r.result, INCOMPARABLE)


# --- 7. baseline --------------------------------------------------------------------


class BaselineTests(unittest.TestCase):
    def test_above_near_below_baseline_classification(self) -> None:
        baseline_records = [
            _perf(content_id=f"c{i}", published_at="2026-09-01T00:00:00+00:00", metric_collected_at="2026-09-02T00:00:00+00:00", metrics={"views": v})
            for i, v in enumerate([100, 100, 100, 100])
        ]
        above = compare_to_baseline(200, baseline_records, scope="content", scope_id="target", platform="blog", metric="views", analysis_window="24h")
        near = compare_to_baseline(105, baseline_records, scope="content", scope_id="target", platform="blog", metric="views", analysis_window="24h")
        below = compare_to_baseline(10, baseline_records, scope="content", scope_id="target", platform="blog", metric="views", analysis_window="24h")
        self.assertEqual(above.result, ABOVE_BASELINE)
        self.assertEqual(near.result, NEAR_BASELINE)
        self.assertEqual(below.result, BELOW_BASELINE)

    def test_no_automatic_best_worst_winner_labels(self) -> None:
        """7장 지시: BEST/WORST/WINNER 같은 평가를 자동으로 만들지 않는다."""
        baseline_records = [_perf(content_id=f"c{i}", metrics={"views": 100}) for i in range(5)]
        r = compare_to_baseline(999, baseline_records, scope="content", scope_id="target", platform="blog", metric="views", analysis_window="all")
        forbidden = ("BEST", "WORST", "WINNER")
        for word in forbidden:
            self.assertNotIn(word, r.result)
            self.assertNotIn(word, r.observation)


# --- 6/12. Platform / Content separation -------------------------------------------


class PlatformContentSeparationTests(unittest.TestCase):
    def test_media_platform_shorts_maps_to_performance_platform_youtube(self) -> None:
        """6-35 신규 발견: MediaArchiveRecord.platform="shorts"로 만들어진
        콘텐츠는 PerformanceRecord.platform="youtube"로 기록된다(기존
        content_engine/performance/youtube.py가 이미 이렇게 하드코딩하고
        있음) - 이 둘을 문자열로 직접 비교하면 안 된다는 것을 회귀 테스트로
        고정한다(6-32의 finance contamination 같은 종류의 혼동을 막는다)."""
        self.assertEqual(MEDIA_PLATFORM_TO_PERFORMANCE_PLATFORM["shorts"], "youtube")
        self.assertEqual(MEDIA_PLATFORM_TO_PERFORMANCE_PLATFORM["blog"], "blog")
        self.assertEqual(MEDIA_PLATFORM_TO_PERFORMANCE_PLATFORM["threads"], "threads")

    def test_platforms_are_analyzed_separately_not_merged(self) -> None:
        threads_records = _series([100, 200, 300], platform="threads")
        blog_records = _series([1, 2, 3], platform="blog")
        threads_trend = analyze_trend(threads_records, scope="platform", scope_id="threads", platform="threads", metric="views")
        blog_trend = analyze_trend(blog_records, scope="platform", scope_id="blog", platform="blog", metric="views")
        self.assertNotEqual(threads_trend.insight_id, blog_trend.insight_id)
        self.assertEqual(threads_trend.result, TREND_INCREASING)
        self.assertEqual(blog_trend.result, TREND_INCREASING)


# --- 8/9. KNOWLEDGE aggregation / Generation separation ---------------------------


class KnowledgeGenerationScopeTests(unittest.TestCase):
    def test_knowledge_scope_groups_multiple_content_ids(self) -> None:
        records = _series([100, 110, 120], content_id="content-A", knowledge_id="knowledge-1") + \
            _series([10, 20, 30], content_id="content-B", knowledge_id="knowledge-1")
        r = analyze_trend(records, scope="knowledge", scope_id="knowledge-1", platform="", metric="views")
        self.assertEqual(r.sample_size, 6)

    def test_legacy_records_without_generation_concept_still_work(self) -> None:
        """generation_id가 없는 legacy PerformanceRecord도(6-34 11장 결론:
        애초에 이 스키마에 generation_id가 없다) 기존 구조를 깨뜨리지 않고
        분석 가능해야 한다."""
        legacy_records = _series([50, 60, 70])
        r = analyze_trend(legacy_records, scope="content", scope_id="content-1", platform="blog", metric="views")
        self.assertEqual(r.sample_size, 3)


# --- 10. Superseded 보존 -----------------------------------------------------------


class SupersededPreservationTests(unittest.TestCase):
    def test_old_and_new_performance_are_independent_after_supersede(self) -> None:
        old_records = _series([1000, 1200, 1500], content_id="content-OLD", knowledge_id="knowledge-1")
        new_records = _series([10, 20], content_id="content-NEW", knowledge_id="knowledge-1")

        old_trend = analyze_trend(old_records, scope="content", scope_id="content-OLD", platform="blog", metric="views")
        # NEW는 표본 2건 -> INSUFFICIENT_SAMPLE이어야 하고, OLD 값이 섞이면 안 된다.
        new_trend = analyze_trend(new_records, scope="content", scope_id="content-NEW", platform="blog", metric="views")

        self.assertEqual(old_trend.sample_size, 3)
        self.assertEqual(new_trend.sample_size, 2)
        self.assertEqual(new_trend.result, INSUFFICIENT_SAMPLE, "OLD의 표본이 NEW에 섞여 표본 수를 부풀리면 안 된다.")

        # KNOWLEDGE aggregation에서는 둘 다 knowledge-1로 연결되어야 한다.
        knowledge_level = analyze_trend(old_records + new_records, scope="knowledge", scope_id="knowledge-1", platform="", metric="views")
        self.assertEqual(knowledge_level.sample_size, 5)


# --- 11. Evidence / 12. Explainability ---------------------------------------------


class EvidenceExplainabilityTests(unittest.TestCase):
    def test_evidence_contains_content_id_and_raw_values(self) -> None:
        r = analyze_trend(_series([100, 200, 300]), scope="content", scope_id="content-1", platform="blog", metric="views")
        self.assertEqual(len(r.evidence), 3)
        for item in r.evidence:
            self.assertIn("content_id", item)
            self.assertIn("metric_collected_at", item)
            self.assertIn("value", item)

    def test_evidence_allows_human_to_trace_back(self) -> None:
        records = _series([5, 10, 15], content_id="content-traceable")
        r = analyze_trend(records, scope="content", scope_id="content-traceable", platform="blog", metric="views")
        traced_content_ids = {item["content_id"] for item in r.evidence}
        self.assertEqual(traced_content_ids, {"content-traceable"})


# --- 13. Human Review workflow -----------------------------------------------------


class HumanReviewWorkflowTests(unittest.TestCase):
    def test_candidate_to_accepted_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            r = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            self.assertEqual(r.status, STATUS_CANDIDATE)
            append_insight(path, r)
            updated = set_insight_status(path, r.insight_id, STATUS_ACCEPTED)
            self.assertEqual(updated.status, STATUS_ACCEPTED)

    def test_candidate_to_rejected_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            r = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(path, r)
            updated = set_insight_status(path, r.insight_id, STATUS_REJECTED)
            self.assertEqual(updated.status, STATUS_REJECTED)

    def test_reanalysis_does_not_revert_accepted_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            r = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(path, r)
            set_insight_status(path, r.insight_id, STATUS_ACCEPTED)

            r_again = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            self.assertEqual(r.insight_id, r_again.insight_id, "같은 입력이면 같은 insight_id여야 idempotent하다.")
            append_insight(path, r_again)

            reloaded = load_insights(path)[0]
            self.assertEqual(reloaded.status, STATUS_ACCEPTED, "재분석이 사람의 승인 결정을 조용히 되돌리면 안 된다.")

    def test_accepted_status_alone_does_not_trigger_any_automatic_action(self) -> None:
        """19장: accepted도 단지 사람이 검토한 분석 결과일 뿐, 자동 콘텐츠
        생성/자동 KNOWLEDGE 수정으로 이어지지 않는다 - 이는 코드 부재로
        증명한다(이 모듈에 media_archive/tak_brain 쓰기 함수 import가 없다)."""
        import content_engine.performance_insight as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("upsert_archive", source)
        self.assertNotIn("save_archive", source)
        self.assertNotIn("set_review_status", source)


# --- 14. Idempotency ----------------------------------------------------------------


class IdempotencyTests(unittest.TestCase):
    def test_analyze_a_twice_produces_no_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            records = _series([100, 120, 150])
            r1 = analyze_trend(records, scope="content", scope_id="c1", platform="blog", metric="views")
            r2 = analyze_trend(records, scope="content", scope_id="c1", platform="blog", metric="views")
            added = append_insights(path, [r1, r2])
            self.assertEqual(added, 1)
            self.assertEqual(len(load_insights(path)), 1)

    def test_analyze_a_then_b_only_new_result_added(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            a = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(path, a)
            b = analyze_trend(_series([100, 120, 150, 999]), scope="content", scope_id="c1", platform="blog", metric="views")
            added = append_insight(path, b)
            self.assertTrue(added)
            self.assertEqual(len(load_insights(path)), 2)


# --- 15. Failure Injection ----------------------------------------------------------


class FailureInjectionTests(unittest.TestCase):
    def test_missing_metric_yields_zero_sample(self) -> None:
        records = _series([100, 200, 300])
        r = analyze_trend(records, scope="content", scope_id="c1", platform="blog", metric="nonexistent_metric")
        self.assertEqual(r.sample_size, 0)
        self.assertEqual(r.result, INSUFFICIENT_SAMPLE)

    def test_mixed_windows_is_handled_by_explicit_window_param(self) -> None:
        """mixed platform/window 자체가 섞여 저장되어 있어도, 호출부가
        analysis_window를 명시하면 compare_to_baseline이 그 window에
        해당하는 스냅샷만 걸러서 쓴다(window.py의 classify_measurement_window
        재사용, 새 필터링 로직을 만들지 않음)."""
        mixed = [
            _perf(content_id="c1", published_at="2026-09-01T00:00:00+00:00", metric_collected_at="2026-09-01T12:00:00+00:00", metrics={"views": 100}),  # 24h
            _perf(content_id="c2", published_at="2026-09-01T00:00:00+00:00", metric_collected_at="2026-09-20T00:00:00+00:00", metrics={"views": 900}),  # 7d
            _perf(content_id="c3", published_at="2026-09-01T00:00:00+00:00", metric_collected_at="2026-09-01T10:00:00+00:00", metrics={"views": 105}),  # 24h
            _perf(content_id="c4", published_at="2026-09-01T00:00:00+00:00", metric_collected_at="2026-09-01T20:00:00+00:00", metrics={"views": 110}),  # 24h
        ]
        r = compare_to_baseline(107, mixed, scope="content", scope_id="target", platform="blog", metric="views", analysis_window="24h")
        self.assertEqual(r.sample_size, 3, "7d 구간의 c2는 제외되고 24h 구간 3건만 baseline에 포함되어야 한다.")

    def test_superseded_content_traceability_still_verifiable(self) -> None:
        r = check_traceability(content_id="content-OLD", knowledge_id="knowledge-1", generation_id="gen-A", performance_records=_series([100], content_id="content-OLD", knowledge_id="knowledge-1"))
        self.assertEqual(r.result, CONSISTENT)

    def test_insufficient_sample_for_comparison(self) -> None:
        r = compare_to_baseline(100, _series([50, 60]), scope="content", scope_id="c1", platform="blog", metric="views", analysis_window="all")
        from content_engine.performance_insight import COMPARISON_UNKNOWN

        self.assertEqual(r.result, COMPARISON_UNKNOWN)

    def test_malformed_insight_json_raises_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(InsightError):
                load_insights(path)

    def test_duplicate_insight_via_append_insights_is_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            r = analyze_trend(_series([100, 200, 300]), scope="content", scope_id="c1", platform="blog", metric="views")
            added = append_insights(path, [r, r, r])
            self.assertEqual(added, 1)


# --- 16. Traceability -----------------------------------------------------------------


class TraceabilityTests(unittest.TestCase):
    def test_consistent_identity_chain(self) -> None:
        r = check_traceability(
            content_id="c1", knowledge_id="k1", generation_id="gen-A",
            performance_records=_series([100, 200], content_id="c1", knowledge_id="k1"),
        )
        self.assertEqual(r.result, CONSISTENT)

    def test_mismatched_knowledge_id_is_inconsistent(self) -> None:
        bad_records = _series([100], content_id="c1", knowledge_id="wrong-knowledge")
        r = check_traceability(content_id="c1", knowledge_id="k1", generation_id="gen-A", performance_records=bad_records)
        self.assertEqual(r.result, INCONSISTENT)

    def test_no_performance_records_is_inconsistent(self) -> None:
        r = check_traceability(content_id="c-missing", knowledge_id="k1", generation_id="gen-A", performance_records=[])
        self.assertEqual(r.result, INCONSISTENT)


# --- 17. Monetization attribution(설계 검증만, 구현은 FUTURE) --------------------


class MonetizationAttributionTests(unittest.TestCase):
    def test_monetization_insight_type_is_reserved_but_not_implemented(self) -> None:
        from content_engine.performance_insight import INSIGHT_TYPES

        self.assertIn("monetization", INSIGHT_TYPES)
        import content_engine.performance_insight as module

        self.assertFalse(hasattr(module, "analyze_monetization"), "6-35에서는 monetization 분석 함수를 구현하지 않았다(FUTURE).")


# --- 18. E2E --------------------------------------------------------------------------


class FullEndToEndTest(unittest.TestCase):
    def test_knowledge_to_accepted_insight_with_superseded_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / "tak_media_archive.json"
            performance_path = tmp_path / "tak_performance.json"
            insight_path = tmp_path / "tak_performance_insights.json"

            # KNOWLEDGE -> Generation -> Blog/Shorts/Threads -> Publish(approved)
            old_record = MediaArchiveRecord(
                content_id="content-OLD", knowledge_id="knowledge-e2e", platform="threads",
                generation_status="valid", original_title="원본", original_body="원본 본문",
                rewritten_title="재작성", rewritten_body="재작성 본문", source_url="https://example.test/e2e",
                evidence=(), evidence_unit_ids=("lesson:1",), created_at="2026-09-01T00:00:00+00:00",
                review_status="approved",
            )
            new_record = MediaArchiveRecord(
                content_id="content-NEW", knowledge_id="knowledge-e2e", platform="threads",
                generation_status="valid", original_title="정정된 원본", original_body="정정된 원본 본문",
                rewritten_title="재작성2", rewritten_body="재작성 본문2", source_url="https://example.test/e2e",
                evidence=(), evidence_unit_ids=("lesson:1",), created_at="2026-09-05T00:00:00+00:00",
                review_status="approved",
            )
            old_superseded = MediaArchiveRecord(**{**old_record.to_dict(), "review_status": "superseded", "superseded_by": "content-NEW"})
            upsert_archive(archive_path, [old_superseded, new_record])

            # Performance snapshots(OLD, superseded 이후에도 보존)
            append_snapshots(
                performance_path,
                _series([500, 700, 1000], content_id="content-OLD", knowledge_id="knowledge-e2e")
                + _series([50, 80], content_id="content-NEW", knowledge_id="knowledge-e2e"),
            )

            # Production Archive isolation: 분석 전후 archive 바이트 동일
            before_archive_bytes = archive_path.read_bytes()

            # Analysis -> Insight Candidate
            performance_records = load_snapshots(performance_path)
            old_trend = analyze_trend(
                [r for r in performance_records if r.content_id == "content-OLD"],
                scope="content", scope_id="content-OLD", platform="threads", metric="views",
            )
            traceability = check_traceability(
                content_id="content-OLD", knowledge_id="knowledge-e2e", generation_id="gen-A",
                performance_records=performance_records,
            )
            append_insights(insight_path, [old_trend, traceability])

            # Human Review simulation -> Accepted
            set_insight_status(insight_path, old_trend.insight_id, STATUS_ACCEPTED)

            # 검증
            self.assertEqual(archive_path.read_bytes(), before_archive_bytes, "분석이 Production Archive를 건드리면 안 된다.")
            accepted = [i for i in load_insights(insight_path) if i.status == STATUS_ACCEPTED]
            self.assertEqual(len(accepted), 1)
            self.assertEqual(old_trend.result, TREND_INCREASING)
            self.assertEqual(traceability.result, CONSISTENT)

            # NEW의 성과가 OLD와 섞이지 않았는지(superseded preservation)
            new_only = [r for r in performance_records if r.content_id == "content-NEW"]
            self.assertEqual(len(new_only), 2)
            self.assertEqual(sum(r.metrics["views"] for r in new_only), 130)


# --- 19/20. Production Archive isolation / Human Review isolation -----------------


class IsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.pending_path = self.tmp_path / "tak_threads_pending.json"
        self.threads_history_path = self.tmp_path / "threads_publish_log.json"
        self.performance_path = self.tmp_path / "tak_performance.json"
        self.insight_path = self.tmp_path / "tak_performance_insights.json"

        upsert_archive(
            self.archive_path,
            [
                MediaArchiveRecord(
                    content_id="content-1", knowledge_id="knowledge-1", platform="threads",
                    generation_status="valid", original_title="원본", original_body="원본 본문",
                    rewritten_title="재작성", rewritten_body="재작성 본문", source_url="https://example.test/1",
                    evidence=(), evidence_unit_ids=("lesson:1",), created_at="2026-09-01T00:00:00+00:00",
                    review_status="approved",
                )
            ],
        )
        upsert_pending(
            self.pending_path,
            ThreadsPendingDraft(
                content_id="content-1", knowledge_id="knowledge-1", source_url="https://example.test/1",
                evidence_unit_ids=("lesson:1",), article_type=None, knowledge_type="의견",
                original_title="원본", original_body="원본 본문", ai_rewritten_title="재작성",
                ai_rewritten_body="재작성 본문", status="pending", created_at="2026-09-01T00:00:00+00:00",
            ),
        )
        history = PublishHistory(self.threads_history_path)
        history.append(PublishRecord(content_id="content-1", published_at="2026-09-01T01:00:00+00:00", threads_post_id="p1", knowledge_id="knowledge-1"))
        append_snapshot(self.performance_path, _perf(content_id="content-1", knowledge_id="knowledge-1"))

    def _snapshot(self) -> dict[str, bytes]:
        return {
            "archive": self.archive_path.read_bytes(),
            "pending": self.pending_path.read_bytes(),
            "history": self.threads_history_path.read_bytes(),
            "performance": self.performance_path.read_bytes(),
        }

    def test_analysis_and_insight_storage_leave_other_stores_untouched(self) -> None:
        before = self._snapshot()

        records = load_snapshots(self.performance_path)
        r = analyze_trend(records, scope="content", scope_id="content-1", platform="threads", metric="views")
        append_insight(self.insight_path, r)
        set_insight_status(self.insight_path, r.insight_id, STATUS_ACCEPTED)

        after = self._snapshot()
        self.assertEqual(before, after, "Insight 분석/저장이 Production Archive/Threads pending/Publish History/Performance 원자료를 건드리면 안 된다.")

        archive_record = load_archive(self.archive_path)[0]
        self.assertEqual(archive_record.review_status, "approved", "Insight가 review_status를 바꾸면 안 된다.")


# --- 21. Security redaction ---------------------------------------------------------


class SecurityRedactionTests(unittest.TestCase):
    def test_secret_like_values_never_appear_in_insight_output(self) -> None:
        secret_marker = "sk-super-secret-token-should-never-appear-ANYWHERE"
        records = [
            _perf(content_id="c1", metrics={"views": 100}, title=secret_marker),
            _perf(content_id="c1", metric_collected_at="2026-09-03T00:00:00+00:00", metrics={"views": 200}),
            _perf(content_id="c1", metric_collected_at="2026-09-04T00:00:00+00:00", metrics={"views": 300}),
        ]
        r = analyze_trend(records, scope="content", scope_id="c1", platform="blog", metric="views")
        serialized = json.dumps(r.to_dict(), ensure_ascii=False)
        self.assertNotIn(secret_marker, serialized, "PerformanceRecord.title 같은 임의 필드가 Insight 출력에 그대로 새어나가면 안 된다.")

    def test_analyze_cli_output_never_prints_raw_field_from_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            perf_path = tmp_path / "perf.json"
            secret_marker = "REFRESH_TOKEN_LEAK_CHECK_MARKER"
            append_snapshots(
                perf_path,
                [
                    _perf(content_id="c1", title=secret_marker, metrics={"views": 100}),
                    _perf(content_id="c1", metric_collected_at="2026-09-03T00:00:00+00:00", metrics={"views": 200}),
                    _perf(content_id="c1", metric_collected_at="2026-09-04T00:00:00+00:00", metrics={"views": 300}),
                ],
            )
            import io
            from contextlib import redirect_stdout

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                analyze_cli.main(
                    ["--performance", str(perf_path), "--scope", "content", "--scope-id", "c1", "--platform", "blog", "--metric", "views"]
                )
            self.assertNotIn(secret_marker, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
