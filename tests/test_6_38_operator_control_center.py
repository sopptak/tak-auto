"""TAK AUTO 6-38 Operator Control Center
(docs/6-38-operator-control-center.md).

10월 1일 실제 운영자가 한 화면에서 SCOUT→KNOWLEDGE→MEDIA→HUMAN REVIEW→
PROMOTION→PRODUCTION ARCHIVE→PUBLISH→PERFORMANCE→INSIGHT를 확인할 수 있는
통합 관제판(content_engine/operator_summary.py, 신규)을 검증한다. 이
모듈은 새 판정 로직을 만들지 않고 6-14/6-17/6-19/6-21/6-26/6-33/6-35/
6-36/6-37이 이미 계산한 상태를 재사용/집계만 한다 - 순수 함수라
approve/dismiss/promote/publish 중 어떤 것도 실행하지 않는다.

실제 외부 API는 호출하지 않는다. 실제 운영 데이터는 어디에서도
생성/수정하지 않는다 - 전부 tempfile이다.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from content_engine.data_state import CORRUPTED, NOT_PRESENT, VALID
from content_engine.media_archive import MediaArchiveRecord
from content_engine.performance.models import PerformanceRecord
from content_engine.performance_insight import InsightRecord
from content_engine.threads_review import ThreadsPendingDraft
from tak_brain.models import KnowledgeRecord

from content_engine.operator_summary import (
    SYSTEM_BLOCKED,
    SYSTEM_NEEDS_REVIEW,
    SYSTEM_READY,
    SYSTEM_READY_WITH_HUMAN_STEP,
    OperatorInputs,
    OperatorSummary,
    StatusWhyAction,
    build_blocked_items,
    build_human_actions,
    build_next_actions,
    build_operator_summary,
    build_pipeline,
    build_publish_status,
)
import scripts.operator_control_center as operator_cli
from scripts.run_scout_dashboard import render_operator_center_html


def _knowledge(**overrides) -> KnowledgeRecord:
    defaults = dict(
        id="knowledge-1", source_raw_id="r1", source_url="https://example.test/1", title="제목",
        article_type=None, domain="기술", category="기술", knowledge_type="의견",
        lesson="충분히 긴 설명 문장을 담습니다 - 최소 분량 요건을 만족시키기 위한 텍스트입니다.",
        reusable_principle="원칙 문장입니다.", evidence=("SOURCE FACT: x",),
        inference_method="rule_based_template", confidence=None, created_at="2026-01-01T00:00:00Z",
        knowledge_review_status="approved",
    )
    defaults.update(overrides)
    return KnowledgeRecord(**defaults)


def _media_record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="content-1", knowledge_id="knowledge-1", platform="threads", generation_status="valid",
        original_title="원본", original_body="원본 본문", rewritten_title="재작성", rewritten_body="재작성 본문",
        source_url="https://example.test/1", evidence=(), evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z", review_status="approved", generation_id="gen-A",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


def _base_inputs(**overrides) -> OperatorInputs:
    defaults = dict(
        generated_at="2026-10-01T08:00:00+00:00", git_head="abc123", git_origin_main="abc123",
        git_working_tree_clean=True, test_status="PASS",
    )
    defaults.update(overrides)
    return OperatorInputs(**defaults)


# --- 1. OperatorSummary schema -------------------------------------------------------


class OperatorSummarySchemaTests(unittest.TestCase):
    def test_build_returns_operator_summary_instance(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertIsInstance(summary, OperatorSummary)

    def test_to_dict_round_trip_json_serializable(self) -> None:
        summary = build_operator_summary(_base_inputs())
        payload = summary.to_dict()
        serialized = json.dumps(payload, ensure_ascii=False)
        reparsed = json.loads(serialized)
        self.assertEqual(reparsed["system_status"], summary.system_status)

    def test_status_why_action_to_dict(self) -> None:
        item = StatusWhyAction(label="X", status="READY", why="w", action="a", count=3, detail_route="/x")
        d = item.to_dict()
        self.assertEqual(d, {"label": "X", "status": "READY", "why": "w", "action": "a", "count": 3, "detail_route": "/x"})


# --- 2. pipeline aggregation ------------------------------------------------------------


class PipelineAggregationTests(unittest.TestCase):
    def test_nine_stages_present_in_order(self) -> None:
        pipeline = build_pipeline(_base_inputs(), {})
        labels = [item.label for item in pipeline]
        self.assertEqual(
            labels,
            ["SCOUT", "KNOWLEDGE", "MEDIA", "HUMAN REVIEW", "PROMOTION", "PRODUCTION ARCHIVE", "PUBLISH", "PERFORMANCE", "INSIGHT"],
        )

    def test_scout_not_present_when_no_daily_pack(self) -> None:
        pipeline = build_pipeline(_base_inputs(scout_candidate_count=None), {})
        scout = next(item for item in pipeline if item.label == "SCOUT")
        self.assertEqual(scout.status, NOT_PRESENT)

    def test_scout_ready_with_count(self) -> None:
        pipeline = build_pipeline(_base_inputs(scout_candidate_count=7), {})
        scout = next(item for item in pipeline if item.label == "SCOUT")
        self.assertEqual(scout.count, 7)

    def test_knowledge_pending_needs_human_review(self) -> None:
        k = _knowledge(knowledge_review_status="pending")
        pipeline = build_pipeline(_base_inputs(knowledge_status=VALID, knowledge_records=(k,)), {})
        knowledge_stage = next(item for item in pipeline if item.label == "KNOWLEDGE")
        self.assertEqual(knowledge_stage.status, "NEEDS_HUMAN_REVIEW")
        self.assertEqual(knowledge_stage.count, 1)

    def test_promotion_counts_approved_not_yet_in_archive(self) -> None:
        pool_record = _media_record(review_status="approved", generation_status="valid")
        inputs = _base_inputs(generation_pool_found=True, generation_pool_records=(pool_record,), production_records=())
        pipeline = build_pipeline(inputs, {})
        promotion = next(item for item in pipeline if item.label == "PROMOTION")
        self.assertEqual(promotion.count, 1)

    def test_promotion_zero_when_already_in_archive(self) -> None:
        pool_record = _media_record(review_status="approved", generation_status="valid")
        archive_record = _media_record(review_status="approved", generation_status="valid")
        inputs = _base_inputs(generation_pool_found=True, generation_pool_records=(pool_record,), production_records=(archive_record,))
        pipeline = build_pipeline(inputs, {})
        promotion = next(item for item in pipeline if item.label == "PROMOTION")
        self.assertEqual(promotion.count, 0)


# --- 3. human actions --------------------------------------------------------------------


class HumanActionsTests(unittest.TestCase):
    def test_pending_knowledge_triggers_action(self) -> None:
        k = _knowledge(knowledge_review_status="pending")
        actions = build_human_actions(_base_inputs(knowledge_records=(k,)))
        labels = [a.label for a in actions]
        self.assertIn("KNOWLEDGE REVIEW", labels)

    def test_unreviewed_media_triggers_action(self) -> None:
        pool_record = _media_record(review_status="unreviewed")
        actions = build_human_actions(_base_inputs(generation_pool_records=(pool_record,)))
        labels = [a.label for a in actions]
        self.assertIn("MEDIA REVIEW", labels)

    def test_pending_threads_triggers_action(self) -> None:
        draft = ThreadsPendingDraft(
            content_id="c1", knowledge_id="k1", source_url="https://example.test/1", evidence_unit_ids=(),
            article_type=None, knowledge_type="의견", original_title="원본", original_body="본문",
            ai_rewritten_title="재작성", ai_rewritten_body="본문", status="pending", created_at="2026-01-01T00:00:00Z",
        )
        actions = build_human_actions(_base_inputs(threads_pending=(draft,)))
        labels = [a.label for a in actions]
        self.assertIn("THREADS PUBLISH", labels)

    def test_youtube_oauth_always_flagged_when_renderer_missing(self) -> None:
        actions = build_human_actions(_base_inputs(youtube_renderer_available=False))
        labels = [a.label for a in actions]
        self.assertIn("YOUTUBE OAUTH", labels)

    def test_no_automatic_execution_buttons_in_action(self) -> None:
        """6장: 자동 실행 버튼은 없다 - action 필드는 CLI 안내 문자열일
        뿐이다(실행 가능한 콜백이 아님)."""
        k = _knowledge(knowledge_review_status="pending")
        actions = build_human_actions(_base_inputs(knowledge_records=(k,)))
        for item in actions:
            self.assertIsInstance(item.action, str)

    def test_no_action_when_everything_clean(self) -> None:
        actions = build_human_actions(_base_inputs(youtube_renderer_available=True, youtube_credentials_present=True))
        self.assertEqual(actions, ())


# --- 4. blocked / risk ------------------------------------------------------------------


class BlockedRiskTests(unittest.TestCase):
    def test_youtube_always_blocked_without_renderer(self) -> None:
        blocked = build_blocked_items(_base_inputs(youtube_renderer_available=False))
        labels = [b.label for b in blocked]
        self.assertIn("YouTube", labels)

    def test_youtube_not_blocked_when_renderer_available(self) -> None:
        blocked = build_blocked_items(_base_inputs(youtube_renderer_available=True))
        labels = [b.label for b in blocked]
        self.assertNotIn("YouTube", labels)

    def test_duplicate_risk_knowledge_is_flagged(self) -> None:
        k1 = _knowledge(id="k-a", source_url="https://example.test/dup", title="같은 뉴스")
        k2 = _knowledge(id="k-b", source_url="https://example.test/dup", title="같은  뉴스")
        blocked = build_blocked_items(_base_inputs(knowledge_records=(k1, k2), youtube_renderer_available=True))
        self.assertTrue(any("STRATEGY_DUPLICATE_RISK" == b.status for b in blocked))

    def test_not_excessive_warnings_only_actionable_items(self) -> None:
        """7장: 경고를 많이 만드는 것이 목적이 아니다 - safe한 KNOWLEDGE는
        blocked_items에 나타나지 않아야 한다."""
        safe = _knowledge(id="k-safe")
        blocked = build_blocked_items(_base_inputs(knowledge_records=(safe,), youtube_renderer_available=True))
        self.assertEqual(blocked, ())


# --- 5. publish status ---------------------------------------------------------------------


class PublishStatusTests(unittest.TestCase):
    def test_three_platforms_independent(self) -> None:
        status = build_publish_status(_base_inputs(), {})
        labels = {item.label for item in status}
        self.assertEqual(labels, {"Threads", "Blog", "YouTube Shorts"})

    def test_no_ranking_field(self) -> None:
        status = build_publish_status(_base_inputs(), {})
        for item in status:
            d = item.to_dict()
            self.assertNotIn("rank", d)
            self.assertNotIn("best", d)

    def test_youtube_shorts_always_blocked_without_renderer(self) -> None:
        status = build_publish_status(_base_inputs(youtube_renderer_available=False), {})
        youtube = next(item for item in status if item.label == "YouTube Shorts")
        self.assertEqual(youtube.status, "BLOCKED")

    def test_threads_ready_when_approved_record_present(self) -> None:
        k = _knowledge()
        record = _media_record(platform="threads", review_status="approved")
        status = build_publish_status(_base_inputs(production_records=(record,)), {k.id: k})
        threads = next(item for item in status if item.label == "Threads")
        self.assertIn(threads.status, ("READY", "NEEDS_HUMAN_REVIEW"))


# --- 6. data health ------------------------------------------------------------------------


class DataHealthTests(unittest.TestCase):
    def test_not_present_reported_as_is(self) -> None:
        from content_engine.operator_summary import build_data_health

        health = build_data_health(_base_inputs())
        archive = next(item for item in health if item.label == "Production Archive")
        self.assertEqual(archive.status, NOT_PRESENT)
        self.assertIn("만들지", archive.why)

    def test_corrupted_reported_as_is(self) -> None:
        from content_engine.operator_summary import build_data_health

        health = build_data_health(_base_inputs(production_archive_status=CORRUPTED))
        archive = next(item for item in health if item.label == "Production Archive")
        self.assertEqual(archive.status, CORRUPTED)

    def test_valid_reported_with_no_fabrication(self) -> None:
        from content_engine.operator_summary import build_data_health

        health = build_data_health(_base_inputs(production_archive_status=VALID))
        archive = next(item for item in health if item.label == "Production Archive")
        self.assertEqual(archive.status, VALID)

    def test_all_eight_data_categories_present(self) -> None:
        from content_engine.operator_summary import build_data_health

        health = build_data_health(_base_inputs())
        labels = {item.label for item in health}
        self.assertEqual(
            labels,
            {"Production Archive", "Generation Pool", "KNOWLEDGE", "Threads Pending", "Shorts Scripts", "Blog Drafts", "Performance", "Insight"},
        )


# --- 7. performance / 8. insight ------------------------------------------------------------


class PerformanceInsightSummaryTests(unittest.TestCase):
    def test_performance_not_present(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertEqual(summary.performance.status, NOT_PRESENT)

    def test_performance_valid_with_platforms(self) -> None:
        record = PerformanceRecord(
            content_id="c1", knowledge_id="k1", platform="threads", published_at="2026-01-01T00:00:00Z",
            metric_collected_at="2026-01-02T00:00:00Z", metrics={"views": 100}, source="manual",
        )
        summary = build_operator_summary(_base_inputs(performance_status=VALID, performance_records=(record,)))
        self.assertEqual(summary.performance.count, 1)
        self.assertIn("threads", summary.performance.why)

    def test_insight_not_present(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertEqual(summary.insights.status, NOT_PRESENT)

    def test_insight_review_required_counted(self) -> None:
        from content_engine.performance_insight import compute_insight_id

        insight = InsightRecord(
            insight_id=compute_insight_id(scope="content", scope_id="c1", platform="blog", metric="views", analysis_window="all", insight_type="trend", evidence=()),
            created_at="2026-01-01T00:00:00Z", analysis_window="all", scope="content", scope_id="c1",
            platform="blog", metric="views", insight_type="trend", result="INSUFFICIENT_SAMPLE", observation="",
        )
        summary = build_operator_summary(_base_inputs(insight_status=VALID, insight_records=(insight,)))
        self.assertIn("review_required=1", summary.insights.why)

    def test_no_fake_revenue_shown(self) -> None:
        """10장: 실제 revenue 데이터가 없으면 0원이라고 임의 표시하지 않는다 -
        performance summary의 why 필드에 통화/금액 표기가 없어야 한다."""
        summary = build_operator_summary(_base_inputs())
        self.assertNotIn("원", summary.performance.why)
        self.assertNotIn("$", summary.performance.why)


# --- 9. next actions -----------------------------------------------------------------------


class NextActionsTests(unittest.TestCase):
    def test_max_three_actions(self) -> None:
        k = _knowledge(knowledge_review_status="pending")
        pool_record = _media_record(review_status="unreviewed")
        summary = build_operator_summary(_base_inputs(knowledge_records=(k,), generation_pool_records=(pool_record,)))
        self.assertLessEqual(len(summary.next_actions), 3)

    def test_next_actions_derived_from_human_actions_order(self) -> None:
        human_actions = (
            StatusWhyAction(label="A", status="X"),
            StatusWhyAction(label="B", status="X"),
        )
        blocked = (StatusWhyAction(label="C", status="X"),)
        result = build_next_actions(human_actions, blocked)
        self.assertEqual(result, ("A", "B", "C"))

    def test_no_numeric_priority_score_field(self) -> None:
        """11장: 중요도를 임의의 숫자로 평가하지 않는다 - next_actions는
        문자열 튜플일 뿐 점수 필드가 없다."""
        summary = build_operator_summary(_base_inputs())
        for action in summary.next_actions:
            self.assertIsInstance(action, str)


# --- 10. status/why/action structure --------------------------------------------------------


class StatusWhyActionStructureTests(unittest.TestCase):
    def test_blocked_items_have_why_and_action(self) -> None:
        blocked = build_blocked_items(_base_inputs(youtube_renderer_available=False))
        youtube = next(item for item in blocked if item.label == "YouTube")
        self.assertTrue(youtube.why)
        self.assertTrue(youtube.action)

    def test_ready_items_may_have_empty_why(self) -> None:
        pipeline = build_pipeline(_base_inputs(), {})
        human_review = next(item for item in pipeline if item.label == "HUMAN REVIEW")
        self.assertEqual(human_review.why, "")


# --- 11. filters(CLI) -----------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def test_cli_json_output_valid_on_empty_data_dir(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = operator_cli.main(["--data-dir", str(self.tmp_path), "--json"])
        self.assertEqual(exit_code, 0)
        parsed = json.loads(buffer.getvalue())
        self.assertIn("system_status", parsed)

    def test_cli_text_output_contains_all_sections(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            operator_cli.main(["--data-dir", str(self.tmp_path)])
        text = buffer.getvalue()
        for section in ("TODAY STATUS", "PIPELINE STATUS", "HUMAN ACTION", "BLOCKED / RISK", "PUBLISH STATUS", "DATA HEALTH", "PERFORMANCE / INSIGHT", "NEXT ACTION"):
            self.assertIn(section, text)

    def test_cli_does_not_write_any_file(self) -> None:
        before = sorted(p.name for p in self.tmp_path.iterdir())
        operator_cli.main(["--data-dir", str(self.tmp_path)])
        after = sorted(p.name for p in self.tmp_path.iterdir())
        self.assertEqual(before, after)


# --- 12. read-only -------------------------------------------------------------------------


class ReadOnlyTests(unittest.TestCase):
    def test_no_form_tags_in_operator_html(self) -> None:
        summary = build_operator_summary(_base_inputs())
        html = render_operator_center_html(summary)
        self.assertNotIn("<form", html)

    def test_no_forbidden_action_words_in_html(self) -> None:
        summary = build_operator_summary(_base_inputs())
        html = render_operator_center_html(summary).lower()
        for forbidden in ("approve", "dismiss", "promote", "publish now", "delete", "restore", "repair", "regenerate"):
            self.assertNotIn(forbidden, html)

    def test_no_post_route_for_operator_path(self) -> None:
        import scripts.run_scout_dashboard as dashboard_module

        source = Path(dashboard_module.__file__).read_text(encoding="utf-8")
        do_post_start = source.index("def do_POST")
        do_post_end = source.index("return DashboardRequestHandler", do_post_start)
        self.assertNotIn("/operator", source[do_post_start:do_post_end])

    def test_operator_summary_module_has_no_write_functions(self) -> None:
        import content_engine.operator_summary as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("upsert_archive", "save_archive", "set_review_status", "upsert_pending", "append_snapshot", "record_decision"):
            self.assertNotIn(forbidden, source)


# --- 13. security ---------------------------------------------------------------------------


class SecurityTests(unittest.TestCase):
    def test_secret_marker_not_in_summary_output(self) -> None:
        secret = "API_KEY=sk-secret-marker-6-38-should-never-leak"
        k = _knowledge(evidence=(secret,))
        summary = build_operator_summary(_base_inputs(knowledge_records=(k,)))
        serialized = json.dumps(summary.to_dict(), ensure_ascii=False)
        self.assertNotIn(secret, serialized)

    def test_secret_marker_not_in_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secret = "REFRESH_TOKEN=leak-marker-6-38"
            knowledge_path = tmp_path / "tak_brain_knowledge.json"
            knowledge_path.write_text(json.dumps([_knowledge(evidence=(secret,)).to_dict()], ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                operator_cli.main(["--data-dir", str(tmp_path)])
            self.assertNotIn(secret, buffer.getvalue())

    def test_env_var_values_never_read_only_presence_checked(self) -> None:
        source = Path(operator_cli.__file__).read_text(encoding="utf-8")
        # os.environ.get(...) 호출은 있지만 그 값을 print/출력하는 코드가 없어야 한다.
        self.assertNotIn("print(os.environ", source)


# --- 14. multi-PC --------------------------------------------------------------------------


class MultiPcTests(unittest.TestCase):
    def test_git_synced_display(self) -> None:
        summary = build_operator_summary(_base_inputs(git_head="abc", git_origin_main="abc", git_working_tree_clean=True))
        self.assertEqual(summary.git_status.status, "SYNCED")

    def test_git_out_of_sync_display(self) -> None:
        summary = build_operator_summary(_base_inputs(git_head="abc", git_origin_main="def"))
        self.assertEqual(summary.git_status.status, "OUT_OF_SYNC")
        self.assertEqual(summary.system_status, SYSTEM_NEEDS_REVIEW)

    def test_does_not_auto_generate_missing_production_archive(self) -> None:
        """20장: 현재 PC에서 보이지 않는 운영 데이터를 자동으로 생성/복구
        하지 않는다 - production_archive_status가 NOT_PRESENT면 그대로
        NOT_PRESENT로 남아야 한다(레코드를 지어내지 않음)."""
        summary = build_operator_summary(_base_inputs())
        production_stage = next(item for item in summary.pipeline if item.label == "PRODUCTION ARCHIVE")
        self.assertEqual(production_stage.status, NOT_PRESENT)
        self.assertIsNone(production_stage.count)


# --- 15/16. missing / corrupted data -----------------------------------------------------


class MissingCorruptedDataTests(unittest.TestCase):
    def test_all_missing_data_summary_is_stable(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertIsInstance(summary, OperatorSummary)

    def test_corrupted_production_archive_does_not_crash(self) -> None:
        summary = build_operator_summary(_base_inputs(production_archive_status=CORRUPTED))
        health = next(item for item in summary.data_health if item.label == "Production Archive")
        self.assertEqual(health.status, CORRUPTED)


# --- 17. idempotency -------------------------------------------------------------------------


class IdempotencyTests(unittest.TestCase):
    def test_same_synthetic_data_read_ten_times_identical(self) -> None:
        inputs = _base_inputs(knowledge_records=(_knowledge(),), production_records=(_media_record(),))
        results = [build_operator_summary(inputs) for _ in range(10)]
        first = results[0]
        for other in results[1:]:
            self.assertEqual(first, other)


# --- 18. synthetic scenarios A~M ----------------------------------------------------------


class SyntheticScenariosTests(unittest.TestCase):
    def test_scenario_a_all_ready(self) -> None:
        summary = build_operator_summary(_base_inputs(youtube_renderer_available=True, youtube_credentials_present=True))
        self.assertIn(summary.system_status, (SYSTEM_READY, SYSTEM_READY_WITH_HUMAN_STEP))

    def test_scenario_b_human_action_exists(self) -> None:
        k = _knowledge(knowledge_review_status="pending")
        summary = build_operator_summary(_base_inputs(knowledge_records=(k,), youtube_renderer_available=True, youtube_credentials_present=True))
        self.assertTrue(summary.human_actions)
        self.assertEqual(summary.system_status, SYSTEM_READY_WITH_HUMAN_STEP)

    def test_scenario_c_blocked_exists(self) -> None:
        summary = build_operator_summary(_base_inputs(youtube_renderer_available=False))
        self.assertTrue(summary.blocked_items)
        self.assertEqual(summary.system_status, SYSTEM_BLOCKED)

    def test_scenario_d_external_dependency_exists(self) -> None:
        summary = build_operator_summary(_base_inputs(youtube_renderer_available=False))
        youtube_shorts = next(item for item in summary.publish_status if item.label == "YouTube Shorts")
        self.assertEqual(youtube_shorts.status, "BLOCKED")

    def test_scenario_f_production_archive_not_present(self) -> None:
        summary = build_operator_summary(_base_inputs())
        production_stage = next(item for item in summary.pipeline if item.label == "PRODUCTION ARCHIVE")
        self.assertEqual(production_stage.status, NOT_PRESENT)

    def test_scenario_g_production_archive_valid(self) -> None:
        summary = build_operator_summary(_base_inputs(production_archive_status=VALID, production_records=(_media_record(),)))
        production_stage = next(item for item in summary.pipeline if item.label == "PRODUCTION ARCHIVE")
        self.assertEqual(production_stage.status, VALID)
        self.assertEqual(production_stage.count, 1)

    def test_scenario_h_superseded_content_exists(self) -> None:
        superseded = _media_record(content_id="c-old", review_status="superseded", superseded_by="c-new")
        active = _media_record(content_id="c-new", review_status="approved")
        k = _knowledge()
        summary = build_operator_summary(_base_inputs(production_archive_status=VALID, production_records=(superseded, active), knowledge_records=(k,)))
        publish = next(item for item in summary.publish_status if item.label == "Threads")
        self.assertIn(publish.status, ("SUPERSEDED", "READY", "NEEDS_HUMAN_REVIEW"))

    def test_scenario_i_youtube_blocked(self) -> None:
        summary = build_operator_summary(_base_inputs(youtube_renderer_available=False))
        blocked_labels = [b.label for b in summary.blocked_items]
        self.assertIn("YouTube", blocked_labels)

    def test_scenario_j_naver_human_action(self) -> None:
        approved_blog = _media_record(content_id="c-blog", platform="blog", review_status="approved")
        summary = build_operator_summary(_base_inputs(production_records=(approved_blog,)))
        labels = [a.label for a in summary.human_actions]
        self.assertIn("NAVER MANUAL PUBLISH", labels)

    def test_scenario_k_threads_ready(self) -> None:
        k = _knowledge()
        record = _media_record(platform="threads", review_status="approved")
        summary = build_operator_summary(_base_inputs(production_records=(record,), knowledge_records=(k,)))
        threads = next(item for item in summary.publish_status if item.label == "Threads")
        self.assertIn(threads.status, ("READY", "NEEDS_HUMAN_REVIEW"))

    def test_scenario_l_performance_not_present(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertEqual(summary.performance.status, NOT_PRESENT)

    def test_scenario_m_insight_review_required(self) -> None:
        from content_engine.performance_insight import compute_insight_id

        insight = InsightRecord(
            insight_id=compute_insight_id(scope="content", scope_id="c1", platform="blog", metric="views", analysis_window="all", insight_type="trend", evidence=()),
            created_at="2026-01-01T00:00:00Z", analysis_window="all", scope="content", scope_id="c1",
            platform="blog", metric="views", insight_type="trend", result="INSUFFICIENT_SAMPLE", observation="",
        )
        summary = build_operator_summary(_base_inputs(insight_status=VALID, insight_records=(insight,)))
        self.assertEqual(summary.insights.status, "NEEDS_HUMAN_REVIEW")


# --- 19. E2E ---------------------------------------------------------------------------------


class FullEndToEndTest(unittest.TestCase):
    def test_full_pipeline_reflected_in_operator_summary(self) -> None:
        knowledge = _knowledge(id="knowledge-e2e")
        pool_record = _media_record(content_id="content-e2e", knowledge_id="knowledge-e2e", review_status="approved", generation_status="valid")
        production_record = _media_record(content_id="content-e2e", knowledge_id="knowledge-e2e", review_status="approved")
        performance_record = PerformanceRecord(
            content_id="content-e2e", knowledge_id="knowledge-e2e", platform="threads",
            published_at="2026-01-01T00:00:00Z", metric_collected_at="2026-01-02T00:00:00Z",
            metrics={"views": 100}, source="manual",
        )

        inputs = _base_inputs(
            scout_candidate_count=1,
            knowledge_status=VALID, knowledge_records=(knowledge,),
            generation_pool_found=True, generation_pool_records=(pool_record,),
            production_archive_status=VALID, production_records=(production_record,),
            performance_status=VALID, performance_records=(performance_record,),
            youtube_renderer_available=False,
        )
        summary = build_operator_summary(inputs)

        scout_stage = next(item for item in summary.pipeline if item.label == "SCOUT")
        self.assertEqual(scout_stage.count, 1)
        production_stage = next(item for item in summary.pipeline if item.label == "PRODUCTION ARCHIVE")
        self.assertEqual(production_stage.count, 1)
        self.assertEqual(summary.performance.count, 1)
        self.assertTrue(any(b.label == "YouTube" for b in summary.blocked_items))
        html = render_operator_center_html(summary)
        self.assertIn("knowledge-e2e".split("-")[0].upper(), html.upper())  # sanity: html이 실제로 렌더링됨


# --- 20. dashboard route / JSON output -----------------------------------------------------


class DashboardRouteJsonTests(unittest.TestCase):
    def test_render_operator_center_html_contains_all_eight_sections(self) -> None:
        summary = build_operator_summary(_base_inputs())
        html = render_operator_center_html(summary)
        for section in ("TODAY STATUS", "PIPELINE STATUS", "HUMAN ACTION", "BLOCKED / RISK", "PUBLISH STATUS", "DATA HEALTH", "PERFORMANCE / INSIGHT", "NEXT ACTION"):
            self.assertIn(section, html)

    def test_json_output_matches_to_dict(self) -> None:
        summary = build_operator_summary(_base_inputs())
        self.assertEqual(json.loads(json.dumps(summary.to_dict())), summary.to_dict())


if __name__ == "__main__":
    unittest.main()
