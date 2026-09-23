"""TAK AUTO 6-36 Performance Insight Operationalization
(docs/6-36-performance-insight-operations.md).

Insight(6-35) -> Report -> Human Review -> Operational Decision을 검증한다.
Report는 새 분석을 수행하지 않고 이미 계산된 Performance/Insight를
운영 관점에서 정리만 한다(content_engine/insight_report.py, 신규).

실제 외부 API는 호출하지 않는다. 실제 운영 데이터(data/tak_performance.json,
data/tak_performance_insights.json 포함)는 어디에서도 생성/수정하지
않는다 - 전부 tempfile이다.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord, load_archive, upsert_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot, append_snapshots, load_snapshots
from content_engine.performance_insight import (
    CONSISTENT,
    INCOMPARABLE,
    INCONSISTENT,
    INSUFFICIENT_SAMPLE,
    STATUS_ACCEPTED,
    STATUS_CANDIDATE,
    STATUS_REJECTED,
    TREND_INCREASING,
    analyze_trend,
    append_insight,
    append_insights,
    check_traceability,
    compare_to_baseline,
    detect_anomaly,
    load_insights,
)
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.threads_review import ThreadsPendingDraft, upsert_pending

from content_engine.insight_report import (
    DailyReportSummary,
    DecisionError,
    DecisionRecord,
    MONETIZATION_DIRECT,
    MONETIZATION_INDIRECT,
    MONETIZATION_NOT_APPLICABLE,
    PRIORITY_INCOMPARABLE,
    PRIORITY_INSUFFICIENT_DATA,
    PRIORITY_INVALID,
    PRIORITY_NEW,
    PRIORITY_REVIEWED,
    WeeklyReportSummary,
    build_daily_report,
    build_weekly_report,
    classify_monetization_attribution,
    decisions_for_insight,
    drill_down_evidence,
    load_decisions,
    record_decision,
    render_daily_report_text,
    render_weekly_report_text,
    review_priority,
)
import scripts.performance_insight_report as report_cli
import scripts.run_scout_dashboard as dashboard_module


def _perf(**overrides) -> PerformanceRecord:
    defaults = dict(
        content_id="content-1", knowledge_id="knowledge-1", platform="blog",
        published_at="2026-10-01T00:00:00+00:00", metric_collected_at="2026-10-02T00:00:00+00:00",
        metrics={"views": 100}, source="manual",
    )
    defaults.update(overrides)
    return PerformanceRecord(**defaults)


def _series(values, **overrides) -> list[PerformanceRecord]:
    return [
        _perf(metric_collected_at=f"2026-10-{i + 1:02d}T00:00:00+00:00", metrics={"views": v}, **overrides)
        for i, v in enumerate(values)
    ]


# --- 1. report schema ---------------------------------------------------------------


class ReportSchemaTests(unittest.TestCase):
    def test_daily_report_is_frozen_dataclass_with_expected_fields(self) -> None:
        report = build_daily_report([], [], window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00")
        self.assertIsInstance(report, DailyReportSummary)
        self.assertEqual(report.measured_content_count, 0)

    def test_weekly_report_is_frozen_dataclass_with_expected_fields(self) -> None:
        report = build_weekly_report([], window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00")
        self.assertIsInstance(report, WeeklyReportSummary)
        self.assertEqual(report.trend_by_platform, {})

    def test_decision_record_rejects_invalid_decision(self) -> None:
        with self.assertRaises(DecisionError):
            DecisionRecord(insight_id="i1", decision="maybe", reviewed_at="2026-10-01T00:00:00+00:00")

    def test_decision_record_requires_reviewed_at(self) -> None:
        with self.assertRaises(DecisionError):
            DecisionRecord(insight_id="i1", decision=STATUS_ACCEPTED, reviewed_at="")


# --- 2. daily report -------------------------------------------------------------------


class DailyReportTests(unittest.TestCase):
    def test_measured_content_and_metric_quality_counts(self) -> None:
        performance = _series([100, -5, 300])  # -5는 quality WARNING(음수)
        report = build_daily_report(
            performance, [], window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00"
        )
        self.assertEqual(report.measured_content_count, 1)
        self.assertEqual(report.valid_metric_count, 2)
        self.assertEqual(report.invalid_metric_count, 1)

    def test_insight_status_counts(self) -> None:
        insights = [
            analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views"),
            analyze_trend(_series([1, 2]), scope="content", scope_id="c2", platform="blog", metric="views"),  # INSUFFICIENT_SAMPLE
        ]
        window_start = insights[0].created_at[:10] + "T00:00:00+00:00"
        window_end = insights[0].created_at[:10] + "T23:59:59+00:00"
        report = build_daily_report([], insights, window_start=window_start, window_end=window_end)
        self.assertEqual(report.candidate_count, 2)
        self.assertEqual(report.insufficient_sample_count, 1)

    def test_render_daily_report_text_contains_all_sections(self) -> None:
        report = build_daily_report([], [], window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00")
        text = render_daily_report_text(report)
        for label in ("Window:", "Data:", "Insights:", "measured", "candidate", "accepted", "rejected"):
            self.assertIn(label, text)


# --- 3. weekly report --------------------------------------------------------------------


class WeeklyReportTests(unittest.TestCase):
    def test_platforms_are_never_merged(self) -> None:
        threads_insight = analyze_trend(_series([100, 200, 300], platform="threads"), scope="content", scope_id="c1", platform="threads", metric="views")
        blog_insight = analyze_trend(_series([1, 2, 3], platform="blog"), scope="content", scope_id="c2", platform="blog", metric="views")
        window_start = threads_insight.created_at[:10] + "T00:00:00+00:00"
        window_end = threads_insight.created_at[:10] + "T23:59:59+00:00"
        report = build_weekly_report([threads_insight, blog_insight], window_start=window_start, window_end=window_end)
        self.assertEqual(set(report.trend_by_platform.keys()), {"threads", "blog"})
        self.assertEqual(len(report.trend_by_platform["threads"]), 1)
        self.assertEqual(len(report.trend_by_platform["blog"]), 1)

    def test_knowledge_scope_grouped_separately_from_platform_scope(self) -> None:
        knowledge_insight = analyze_trend(_series([1, 2, 3]), scope="knowledge", scope_id="knowledge-1", platform="", metric="views")
        window_start = knowledge_insight.created_at[:10] + "T00:00:00+00:00"
        window_end = knowledge_insight.created_at[:10] + "T23:59:59+00:00"
        report = build_weekly_report([knowledge_insight], window_start=window_start, window_end=window_end)
        self.assertIn("knowledge-1", report.knowledge_insights)

    def test_no_ranking_words_in_rendered_output(self) -> None:
        insight = analyze_trend(_series([100, 200, 999999]), scope="content", scope_id="c1", platform="blog", metric="views")
        window_start = insight.created_at[:10] + "T00:00:00+00:00"
        window_end = insight.created_at[:10] + "T23:59:59+00:00"
        report = build_weekly_report([insight], window_start=window_start, window_end=window_end)
        text = render_weekly_report_text(report)
        for forbidden in ("최고", "최악", "1위", "BEST", "WORST", "WINNER"):
            self.assertNotIn(forbidden, text)


# --- 4. insight grouping / 5. status grouping ------------------------------------------


class GroupingTests(unittest.TestCase):
    def test_review_priority_new(self) -> None:
        insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(review_priority(insight), PRIORITY_NEW)

    def test_review_priority_insufficient_data(self) -> None:
        insight = analyze_trend(_series([100]), scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(review_priority(insight), PRIORITY_INSUFFICIENT_DATA)

    def test_review_priority_incomparable(self) -> None:
        insight = compare_to_baseline(
            100, _series([1, 2, 3]), scope="content", scope_id="c1", platform="blog", metric="views",
            analysis_window="24h", target_platform="youtube",
        )
        self.assertEqual(review_priority(insight), PRIORITY_INCOMPARABLE)

    def test_review_priority_invalid_for_inconsistent_traceability(self) -> None:
        insight = check_traceability(content_id="c1", knowledge_id="k1", generation_id="g1", performance_records=[])
        self.assertEqual(review_priority(insight), PRIORITY_INVALID)

    def test_review_priority_reviewed_after_status_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            insights_path = Path(tmp) / "insights.json"
            decisions_path = Path(tmp) / "decisions.json"
            insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(insights_path, insight)
            record_decision(insights_path=insights_path, decisions_path=decisions_path, insight_id=insight.insight_id, decision=STATUS_ACCEPTED)
            reloaded = load_insights(insights_path)[0]
            self.assertEqual(review_priority(reloaded), PRIORITY_REVIEWED)


# --- 6. evidence drilldown ---------------------------------------------------------------


class EvidenceDrilldownTests(unittest.TestCase):
    def test_drilldown_resolves_knowledge_id_and_platform(self) -> None:
        performance = _series([100, 120, 150], content_id="c1", knowledge_id="k1", platform="blog")
        insight = analyze_trend(performance, scope="content", scope_id="c1", platform="blog", metric="views")
        resolved = drill_down_evidence(insight, performance)
        self.assertEqual(len(resolved), 3)
        for item in resolved:
            self.assertEqual(item["knowledge_id"], "k1")
            self.assertEqual(item["platform"], "blog")

    def test_drilldown_resolves_generation_id_via_media_records_readonly(self) -> None:
        performance = _series([100, 120, 150], content_id="c1", knowledge_id="k1")
        insight = analyze_trend(performance, scope="content", scope_id="c1", platform="blog", metric="views")
        media_record = MediaArchiveRecord(
            content_id="c1", knowledge_id="k1", platform="blog", generation_status="valid",
            original_title="t", original_body="b", rewritten_title="t2", rewritten_body="b2",
            source_url="https://example.test/1", evidence=(), evidence_unit_ids=("lesson:1",),
            created_at="2026-10-01T00:00:00+00:00", review_status="approved", generation_id="gen-A",
        )
        resolved = drill_down_evidence(insight, performance, media_records=[media_record])
        self.assertTrue(all(item["generation_id"] == "gen-A" for item in resolved))

    def test_drilldown_does_not_fabricate_missing_generation_id(self) -> None:
        performance = _series([100, 120, 150])
        insight = analyze_trend(performance, scope="content", scope_id="content-1", platform="blog", metric="views")
        resolved = drill_down_evidence(insight, performance)  # media_records 생략
        self.assertTrue(all(item["generation_id"] is None for item in resolved))


# --- 7. superseded handling ---------------------------------------------------------------


class SupersededReportTests(unittest.TestCase):
    def test_old_and_new_are_reported_separately(self) -> None:
        old_perf = _series([1000, 1200, 1500], content_id="content-OLD", knowledge_id="knowledge-1")
        new_perf = _series([10, 20, 30], content_id="content-NEW", knowledge_id="knowledge-1")
        old_insight = analyze_trend(old_perf, scope="content", scope_id="content-OLD", platform="blog", metric="views")
        new_insight = analyze_trend(new_perf, scope="content", scope_id="content-NEW", platform="blog", metric="views")

        report = build_daily_report(
            old_perf + new_perf, [old_insight, new_insight],
            window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00",
        )
        self.assertEqual(report.measured_content_count, 2, "OLD/NEW가 서로 다른 content로 각각 집계되어야 한다.")


# --- 8. generation handling(6-36 재판단) -----------------------------------------------


class GenerationHandlingTests(unittest.TestCase):
    def test_generation_id_available_only_via_readonly_media_join_not_as_stored_field(self) -> None:
        """12장 재판단 결론: PerformanceRecord/InsightRecord 스키마 자체에
        generation_id를 추가하지 않았다(schema를 깨뜨리지 않는다는 조건을
        만족하려면 저장하지 않는 것이 맞다) - 대신 drill_down_evidence()가
        MediaArchiveRecord를 읽기 전용으로 조인해서 "표시"만 한다."""
        performance = _series([1, 2, 3])
        insight = analyze_trend(performance, scope="content", scope_id="content-1", platform="blog", metric="views")
        self.assertNotIn("generation_id", insight.to_dict(), "InsightRecord 스키마 자체에는 generation_id가 없어야 한다(6-35/6-36 결론).")

    def test_legacy_records_without_generation_id_concept_still_report_correctly(self) -> None:
        performance = _series([50, 60, 70])
        insight = analyze_trend(performance, scope="content", scope_id="content-1", platform="blog", metric="views")
        resolved = drill_down_evidence(insight, performance)  # media_records 없음 = legacy
        self.assertEqual(len(resolved), 3)


# --- 9. monetization handling --------------------------------------------------------------


class MonetizationHandlingTests(unittest.TestCase):
    def test_no_revenue_metric_is_not_applicable(self) -> None:
        record = _perf(metrics={"views": 100})
        self.assertEqual(classify_monetization_attribution(record), MONETIZATION_NOT_APPLICABLE)

    def test_direct_revenue_metric_is_direct(self) -> None:
        record = _perf(metrics={"views": 100, "revenue": 5000})
        self.assertEqual(classify_monetization_attribution(record), MONETIZATION_DIRECT)

    def test_indirect_estimate_metric_is_indirect_not_direct(self) -> None:
        record = _perf(metrics={"views": 100, "attributed_revenue_estimate": 500})
        self.assertEqual(classify_monetization_attribution(record), MONETIZATION_INDIRECT)
        self.assertNotEqual(classify_monetization_attribution(record), MONETIZATION_DIRECT, "추정값을 실제 revenue처럼 DIRECT로 분류하면 안 된다.")


# --- 10. human review / 11. decision record --------------------------------------------------


class HumanReviewDecisionTests(unittest.TestCase):
    def test_candidate_to_accepted_via_record_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            insights_path = Path(tmp) / "insights.json"
            decisions_path = Path(tmp) / "decisions.json"
            insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(insights_path, insight)
            self.assertEqual(insight.status, STATUS_CANDIDATE)

            decision = record_decision(
                insights_path=insights_path, decisions_path=decisions_path,
                insight_id=insight.insight_id, decision=STATUS_ACCEPTED, reviewer_note="사람이 직접 확인함",
            )
            self.assertEqual(decision.decision, STATUS_ACCEPTED)
            self.assertEqual(decision.reviewer_note, "사람이 직접 확인함")
            reloaded = load_insights(insights_path)[0]
            self.assertEqual(reloaded.status, STATUS_ACCEPTED)

    def test_reviewer_note_defaults_to_empty_never_fabricated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            insights_path = Path(tmp) / "insights.json"
            decisions_path = Path(tmp) / "decisions.json"
            insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(insights_path, insight)
            decision = record_decision(insights_path=insights_path, decisions_path=decisions_path, insight_id=insight.insight_id, decision=STATUS_REJECTED)
            self.assertEqual(decision.reviewer_note, "", "reviewer_note를 명시하지 않으면 AI가 대신 채우지 않고 빈 문자열이어야 한다.")

    def test_decisions_for_insight_returns_full_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            insights_path = Path(tmp) / "insights.json"
            decisions_path = Path(tmp) / "decisions.json"
            insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(insights_path, insight)
            record_decision(insights_path=insights_path, decisions_path=decisions_path, insight_id=insight.insight_id, decision=STATUS_ACCEPTED, reviewer_note="1차 검토")
            record_decision(insights_path=insights_path, decisions_path=decisions_path, insight_id=insight.insight_id, decision=STATUS_REJECTED, reviewer_note="재검토 후 철회")
            history = decisions_for_insight(decisions_path, insight.insight_id)
            self.assertEqual(len(history), 2, "결정 이력은 덮어쓰지 않고 계속 쌓여야 한다(감사 추적).")

    def test_accepted_insight_never_triggers_knowledge_or_media_write(self) -> None:
        import content_engine.insight_report as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("upsert_archive", source)
        self.assertNotIn("save_archive", source)
        self.assertNotIn("set_review_status", source)
        self.assertNotIn("import tak_brain", source)


# --- 12. idempotency ----------------------------------------------------------------------


class IdempotencyTests(unittest.TestCase):
    def test_same_dataset_analyzed_and_reported_twice_is_identical(self) -> None:
        performance = _series([100, 120, 150])
        insight_a = analyze_trend(performance, scope="content", scope_id="c1", platform="blog", metric="views")
        insight_b = analyze_trend(performance, scope="content", scope_id="c1", platform="blog", metric="views")
        self.assertEqual(insight_a.insight_id, insight_b.insight_id)
        self.assertEqual(insight_a.evidence, insight_b.evidence)
        self.assertEqual(insight_a.observation, insight_b.observation)

    def test_duplicate_insight_not_stored_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            added = append_insights(path, [insight, insight])
            self.assertEqual(added, 1)

    def test_report_generation_is_pure_no_side_effects(self) -> None:
        performance = _series([100, 120, 150])
        insight = analyze_trend(performance, scope="content", scope_id="c1", platform="blog", metric="views")
        window_start = insight.created_at[:10] + "T00:00:00+00:00"
        window_end = insight.created_at[:10] + "T23:59:59+00:00"
        report1 = build_daily_report(performance, [insight], window_start=window_start, window_end=window_end)
        report2 = build_daily_report(performance, [insight], window_start=window_start, window_end=window_end)
        self.assertEqual(report1, report2)


# --- 13. failure injection ------------------------------------------------------------------


class FailureInjectionTests(unittest.TestCase):
    def test_empty_performance_is_zero_not_crash(self) -> None:
        report = build_daily_report([], [], window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00")
        self.assertEqual(report.measured_content_count, 0)

    def test_mixed_platform_insights_are_separated_in_weekly_report(self) -> None:
        threads = analyze_trend(_series([1, 2, 3], platform="threads"), scope="content", scope_id="c1", platform="threads", metric="views")
        youtube = analyze_trend(_series([4, 5, 6], platform="youtube"), scope="content", scope_id="c2", platform="youtube", metric="views")
        window_start = threads.created_at[:10] + "T00:00:00+00:00"
        window_end = threads.created_at[:10] + "T23:59:59+00:00"
        report = build_weekly_report([threads, youtube], window_start=window_start, window_end=window_end)
        self.assertEqual(len(report.trend_by_platform), 2)

    def test_unknown_content_id_traceability_is_inconsistent(self) -> None:
        r = check_traceability(content_id="does-not-exist", knowledge_id="k1", generation_id="g1", performance_records=[])
        self.assertEqual(r.result, INCONSISTENT)

    def test_superseded_content_still_appears_in_daily_report(self) -> None:
        old_perf = _series([100], content_id="content-OLD")
        report = build_daily_report(old_perf, [], window_start="2026-10-01T00:00:00+00:00", window_end="2026-10-31T23:59:59+00:00")
        self.assertEqual(report.measured_content_count, 1)

    def test_insufficient_sample_is_counted_separately_from_incomparable(self) -> None:
        insufficient = analyze_trend(_series([1]), scope="content", scope_id="c1", platform="blog", metric="views")
        incomparable = compare_to_baseline(100, _series([1, 2, 3]), scope="content", scope_id="c2", platform="blog", metric="views", analysis_window="24h", target_platform="youtube")
        window_start = insufficient.created_at[:10] + "T00:00:00+00:00"
        window_end = insufficient.created_at[:10] + "T23:59:59+00:00"
        report = build_daily_report([], [insufficient, incomparable], window_start=window_start, window_end=window_end)
        self.assertEqual(report.insufficient_sample_count, 1)
        self.assertEqual(report.incomparable_count, 1)

    def test_malformed_insight_json_raises_loudly_not_silently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "insights.json"
            path.write_text("{not valid json", encoding="utf-8")
            from content_engine.performance_insight import InsightError

            with self.assertRaises(InsightError):
                load_insights(path)

    def test_invalid_decision_value_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            insights_path = Path(tmp) / "insights.json"
            decisions_path = Path(tmp) / "decisions.json"
            insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
            append_insight(insights_path, insight)
            with self.assertRaises(Exception):
                record_decision(insights_path=insights_path, decisions_path=decisions_path, insight_id=insight.insight_id, decision="not-a-decision")


# --- 14. security redaction ------------------------------------------------------------------


class SecurityRedactionTests(unittest.TestCase):
    def test_secret_marker_never_appears_in_rendered_reports(self) -> None:
        secret = "sk-secret-marker-should-never-leak-anywhere-6-36"
        performance = _series([100, 120, 150], title=secret)
        insight = analyze_trend(performance, scope="content", scope_id="content-1", platform="blog", metric="views")
        window_start = insight.created_at[:10] + "T00:00:00+00:00"
        window_end = insight.created_at[:10] + "T23:59:59+00:00"
        daily = build_daily_report(performance, [insight], window_start=window_start, window_end=window_end)
        weekly = build_weekly_report([insight], window_start=window_start, window_end=window_end)
        self.assertNotIn(secret, render_daily_report_text(daily))
        self.assertNotIn(secret, render_weekly_report_text(weekly))

    def test_secret_marker_never_appears_in_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secret = "REFRESH_TOKEN_LEAK_MARKER_6_36"
            perf_path = tmp_path / "perf.json"
            insights_path = tmp_path / "insights.json"
            append_snapshots(perf_path, _series([100, 120, 150], title=secret))
            insights_path.write_text("[]", encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                report_cli.main(
                    [
                        "--performance", str(perf_path), "--insights", str(insights_path), "--daily",
                        "--window-start", "2026-10-01T00:00:00+00:00", "--window-end", "2026-10-31T23:59:59+00:00",
                    ]
                )
            self.assertNotIn(secret, buffer.getvalue())

    def test_secret_marker_never_appears_in_dashboard_insight_view(self) -> None:
        from scripts.run_scout_dashboard import render_insight_list_html

        secret = "DASHBOARD_LEAK_MARKER_6_36"
        performance = _series([100, 120, 150], title=secret)
        insight = analyze_trend(performance, scope="content", scope_id="content-1", platform="blog", metric="views")
        html = render_insight_list_html([insight])
        self.assertNotIn(secret, html)


# --- 15. dashboard/read-only behavior ---------------------------------------------------------


class DashboardReadOnlyTests(unittest.TestCase):
    def test_insight_list_html_has_no_form_or_action_elements(self) -> None:
        """18장: Dashboard의 /performance/insights는 조회만 가능해야 한다 -
        KNOWLEDGE 수정/MEDIA 생성/Production Archive 수정/발행으로 이어지는
        어떤 form/버튼도 없어야 한다."""
        from scripts.run_scout_dashboard import render_insight_list_html

        insight = analyze_trend(_series([100, 120, 150]), scope="content", scope_id="c1", platform="blog", metric="views")
        html = render_insight_list_html([insight])
        self.assertNotIn("<form", html)
        self.assertNotIn("method=\"post\"", html.lower())

    def test_insight_list_html_filters_by_platform(self) -> None:
        from scripts.run_scout_dashboard import render_insight_list_html

        threads_insight = analyze_trend(_series([1, 2, 3], platform="threads"), scope="content", scope_id="c1", platform="threads", metric="views")
        blog_insight = analyze_trend(_series([1, 2, 3], platform="blog"), scope="content", scope_id="c2", platform="blog", metric="views")
        html = render_insight_list_html([threads_insight, blog_insight], platform="threads")
        self.assertIn("threads", html)
        # blog 전용 content_id가 결과에 없어야 한다(필터링 확인).
        self.assertNotIn("c2", html)

    def test_no_post_route_exists_for_insights_path(self) -> None:
        source = Path(dashboard_module.__file__).read_text(encoding="utf-8")
        do_post_start = source.index("def do_POST")
        do_post_end = source.index("return DashboardRequestHandler", do_post_start)
        do_post_body = source[do_post_start:do_post_end]
        self.assertNotIn("/performance/insights", do_post_body, "insights 경로에 POST(쓰기) 핸들러가 있으면 안 된다.")


# --- 16. E2E --------------------------------------------------------------------------------


class FullEndToEndTest(unittest.TestCase):
    def test_knowledge_through_report_to_decision_with_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / "tak_media_archive.json"
            performance_path = tmp_path / "tak_performance.json"
            insights_path = tmp_path / "tak_performance_insights.json"
            decisions_path = tmp_path / "tak_performance_insight_decisions.json"

            old = MediaArchiveRecord(
                content_id="content-OLD", knowledge_id="knowledge-e2e", platform="threads",
                generation_status="valid", original_title="원본", original_body="원본 본문",
                rewritten_title="재작성", rewritten_body="재작성 본문", source_url="https://example.test/e2e",
                evidence=(), evidence_unit_ids=("lesson:1",), created_at="2026-10-01T00:00:00+00:00",
                review_status="superseded", superseded_by="content-NEW", generation_id="gen-A",
            )
            new = MediaArchiveRecord(
                content_id="content-NEW", knowledge_id="knowledge-e2e", platform="threads",
                generation_status="valid", original_title="정정된 원본", original_body="정정된 본문",
                rewritten_title="재작성2", rewritten_body="재작성 본문2", source_url="https://example.test/e2e",
                evidence=(), evidence_unit_ids=("lesson:1",), created_at="2026-10-05T00:00:00+00:00",
                review_status="approved", generation_id="gen-B",
            )
            upsert_archive(archive_path, [old, new])
            before_archive_bytes = archive_path.read_bytes()

            append_snapshots(
                performance_path,
                _series([500, 700, 1000], content_id="content-OLD", knowledge_id="knowledge-e2e")
                + _series([50, 80, 120], content_id="content-NEW", knowledge_id="knowledge-e2e"),
            )

            performance_records = load_snapshots(performance_path)
            old_trend = analyze_trend([r for r in performance_records if r.content_id == "content-OLD"], scope="content", scope_id="content-OLD", platform="threads", metric="views")
            new_trend = analyze_trend([r for r in performance_records if r.content_id == "content-NEW"], scope="content", scope_id="content-NEW", platform="threads", metric="views")
            traceability = check_traceability(content_id="content-OLD", knowledge_id="knowledge-e2e", generation_id="gen-A", performance_records=performance_records)
            append_insights(insights_path, [old_trend, new_trend, traceability])

            decision = record_decision(
                insights_path=insights_path, decisions_path=decisions_path,
                insight_id=old_trend.insight_id, decision=STATUS_ACCEPTED, reviewer_note="추세 확인함",
            )

            window_start = old_trend.created_at[:10] + "T00:00:00+00:00"
            window_end = old_trend.created_at[:10] + "T23:59:59+00:00"
            daily = build_daily_report(performance_records, load_insights(insights_path), window_start=window_start, window_end=window_end)
            weekly = build_weekly_report(load_insights(insights_path), window_start=window_start, window_end=window_end)

            evidence = drill_down_evidence(old_trend, performance_records, media_records=[old, new])

            self.assertEqual(archive_path.read_bytes(), before_archive_bytes, "E2E 전체 과정이 Production Archive를 건드리면 안 된다.")
            self.assertEqual(old_trend.result, TREND_INCREASING)
            self.assertEqual(new_trend.result, TREND_INCREASING)
            self.assertNotEqual(old_trend.sample_size, new_trend.sample_size + 100, "OLD/NEW가 섞이지 않아야 한다(실제로는 각 3건).")
            self.assertEqual(old_trend.sample_size, 3)
            self.assertEqual(new_trend.sample_size, 3)
            self.assertEqual(traceability.result, CONSISTENT)
            self.assertEqual(decision.decision, STATUS_ACCEPTED)
            self.assertGreaterEqual(daily.candidate_count + daily.accepted_count, 1)
            self.assertIn("threads", weekly.trend_by_platform)
            self.assertTrue(all(item["generation_id"] == "gen-A" for item in evidence))


# --- 17. Production Archive isolation / 18. operating data isolation --------------------------


class IsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.pending_path = self.tmp_path / "tak_threads_pending.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.performance_path = self.tmp_path / "tak_performance.json"
        self.insights_path = self.tmp_path / "tak_performance_insights.json"
        self.decisions_path = self.tmp_path / "tak_performance_insight_decisions.json"

        upsert_archive(
            self.archive_path,
            [
                MediaArchiveRecord(
                    content_id="content-1", knowledge_id="knowledge-1", platform="threads",
                    generation_status="valid", original_title="원본", original_body="원본 본문",
                    rewritten_title="재작성", rewritten_body="재작성 본문", source_url="https://example.test/1",
                    evidence=(), evidence_unit_ids=("lesson:1",), created_at="2026-10-01T00:00:00+00:00",
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
                ai_rewritten_body="재작성 본문", status="pending", created_at="2026-10-01T00:00:00+00:00",
            ),
        )
        history = PublishHistory(self.history_path)
        history.append(PublishRecord(content_id="content-1", published_at="2026-10-01T01:00:00+00:00", threads_post_id="p1", knowledge_id="knowledge-1"))
        append_snapshot(self.performance_path, _perf(content_id="content-1", knowledge_id="knowledge-1"))

    def _snapshot(self) -> dict[str, bytes]:
        return {
            "archive": self.archive_path.read_bytes(),
            "pending": self.pending_path.read_bytes(),
            "history": self.history_path.read_bytes(),
            "performance": self.performance_path.read_bytes(),
        }

    def test_report_generation_and_decision_recording_leave_other_stores_untouched(self) -> None:
        before = self._snapshot()

        performance_records = load_snapshots(self.performance_path)
        insight = analyze_trend(performance_records, scope="content", scope_id="content-1", platform="threads", metric="views")
        append_insight(self.insights_path, insight)
        record_decision(insights_path=self.insights_path, decisions_path=self.decisions_path, insight_id=insight.insight_id, decision=STATUS_ACCEPTED)
        window_start = insight.created_at[:10] + "T00:00:00+00:00"
        window_end = insight.created_at[:10] + "T23:59:59+00:00"
        build_daily_report(performance_records, load_insights(self.insights_path), window_start=window_start, window_end=window_end)
        build_weekly_report(load_insights(self.insights_path), window_start=window_start, window_end=window_end)

        after = self._snapshot()
        self.assertEqual(before, after, "리포트 생성/결정 기록이 Production Archive/Threads pending/Publish History/Performance 원자료를 건드리면 안 된다.")

        archive_record = load_archive(self.archive_path)[0]
        self.assertEqual(archive_record.review_status, "approved")


if __name__ == "__main__":
    unittest.main()
