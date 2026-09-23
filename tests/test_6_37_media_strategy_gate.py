"""TAK AUTO 6-37 KNOWLEDGE -> MEDIA Content Strategy & Quality Gate
(docs/6-37-media-strategy-quality-gate.md).

KNOWLEDGE에서 MEDIA로 넘어가는 지점을 "콘텐츠 전략 및 품질 Gate"로
명확히 만든다 - AI는 근거와 후보(MediaStrategyCandidate)만 제공하고,
사람이 최종 판단한다. content_engine/media_strategy.py(신규)는 어떤
MEDIA도 생성하지 않고 KNOWLEDGE/Production Archive를 수정하지 않는다.

실제 외부 API는 호출하지 않는다. 실제 운영 데이터(data/tak_brain_knowledge.json,
data/tak_media_archive.json 포함)는 어디에서도 생성/수정하지 않는다 -
전부 tempfile이다.
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
from tak_brain.models import KnowledgeRecord

from content_engine.media_strategy import (
    ARTICLE_TYPE_UNKNOWN,
    CATEGORY_UNKNOWN,
    DOMAIN_UNKNOWN,
    EVIDENCE_INSUFFICIENT,
    EVIDENCE_INSUFFICIENT_CODE,
    EVIDENCE_MISSING,
    EVIDENCE_SUFFICIENT,
    HIGH_RISK_TOPIC,
    KNOWLEDGE_NOT_APPROVED,
    MISSING_KNOWLEDGE_ID,
    NOVELTY_HIGH_DUPLICATE_RISK,
    NOVELTY_NO_MATCH,
    NOVELTY_POSSIBLE_DUPLICATE,
    PLATFORMS,
    RECENTLY_COVERED,
    SOURCE_MISSING,
    SOURCE_WEAK,
    STRATEGY_BLOCKED,
    STRATEGY_DUPLICATE_RISK,
    STRATEGY_INSUFFICIENT_EVIDENCE,
    STRATEGY_INVALID,
    STRATEGY_READY,
    STRATEGY_REVIEW_REQUIRED,
    STRATEGY_SUPERSEDED,
    SUPERSEDED_SOURCE,
    MediaStrategyError,
    assess_novelty,
    build_generation_handoff,
    evaluate_media_strategy,
    suggest_content_angles,
)
import scripts.audit_media_strategy as strategy_cli
from scripts.run_scout_dashboard import render_media_strategy_list_html


def _knowledge(**overrides) -> KnowledgeRecord:
    defaults = dict(
        id="knowledge-1", source_raw_id="r1", source_url="https://example.test/1", title="테스트 제목",
        article_type=None, domain="기술", category="기술", knowledge_type="의견",
        lesson="이것은 충분히 긴 설명 문장입니다 - 검색 의도와 설명 가능성을 만족시키기 위한 최소 분량을 채웁니다.",
        reusable_principle="재사용 가능한 원칙 문장도 함께 채웁니다.",
        evidence=("SOURCE FACT: x", "SOURCE URL: https://example.test/1"),
        inference_method="rule_based_template", confidence=None, created_at="2026-01-01T00:00:00Z",
        knowledge_review_status="approved",
    )
    defaults.update(overrides)
    return KnowledgeRecord(**defaults)


def _production_record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="content-1", knowledge_id="knowledge-1", platform="blog", generation_status="valid",
        original_title="원본", original_body="원본 본문", rewritten_title="재작성", rewritten_body="재작성 본문",
        source_url="https://example.test/1", evidence=(), evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z", review_status="approved",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


# --- 1. strategy schema ------------------------------------------------------------


class StrategySchemaTests(unittest.TestCase):
    def test_candidate_round_trip_to_dict(self) -> None:
        candidate = evaluate_media_strategy(_knowledge())
        d = candidate.to_dict()
        self.assertEqual(d["knowledge_id"], "knowledge-1")
        self.assertIn("platform_eligibility", d)
        self.assertEqual(len(d["platform_eligibility"]), 3)

    def test_invalid_status_rejected(self) -> None:
        from content_engine.media_strategy import MediaStrategyCandidate

        with self.assertRaises(MediaStrategyError):
            MediaStrategyCandidate(
                knowledge_id="k1", source_url="", topic="", category="", domain="", article_type=None,
                platform_eligibility=(), risk_flags=(), evidence_quality=EVIDENCE_SUFFICIENT,
                novelty_signal=NOVELTY_NO_MATCH, human_review_required=False, reason_codes=(),
                status="NOT_A_STATUS",
            )

    def test_eligibility_for_lookup(self) -> None:
        candidate = evaluate_media_strategy(_knowledge())
        threads = candidate.eligibility_for("threads")
        self.assertIsNotNone(threads)
        self.assertEqual(threads.platform, "threads")
        self.assertIsNone(candidate.eligibility_for("tiktok"))


# --- 2. platform eligibility --------------------------------------------------------


class PlatformEligibilityTests(unittest.TestCase):
    def test_all_three_platforms_present_independently(self) -> None:
        candidate = evaluate_media_strategy(_knowledge())
        platforms = {item.platform for item in candidate.platform_eligibility}
        self.assertEqual(platforms, set(PLATFORMS))

    def test_high_risk_topic_blocks_all_platforms_uniformly(self) -> None:
        """KNOWLEDGE B 시나리오: 고위험 주제는 세 플랫폼 모두 동일하게
        REVIEW_REQUIRED여야 한다(랭킹이 아니라 콘텐츠 자체의 문제이므로
        플랫폼 무관하게 전파)."""
        candidate = evaluate_media_strategy(_knowledge(category="금융", domain="금융", title="대출 금리 인상"))
        self.assertEqual(candidate.status, STRATEGY_REVIEW_REQUIRED)
        for item in candidate.platform_eligibility:
            self.assertEqual(item.status, STRATEGY_REVIEW_REQUIRED)

    def test_short_content_gets_platform_specific_review_not_overall_block(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(lesson="짧음", reusable_principle=None))
        blog = candidate.eligibility_for("blog")
        threads = candidate.eligibility_for("threads")
        self.assertEqual(blog.status, STRATEGY_REVIEW_REQUIRED, "Blog는 분량 부족 시 개별적으로 REVIEW_REQUIRED여야 한다.")
        self.assertEqual(threads.status, STRATEGY_READY, "Threads는 짧은 내용도 evidence만 있으면 READY여야 한다(플랫폼 독립성).")

    def test_no_overall_ranking_field_exists(self) -> None:
        """5/16장: 플랫폼 간 점수를 합산한 "최고 플랫폼" 필드가 없어야 한다."""
        candidate = evaluate_media_strategy(_knowledge())
        d = candidate.to_dict()
        for forbidden_key in ("best_platform", "ranking", "overall_score", "top_platform"):
            self.assertNotIn(forbidden_key, d)


# --- 3. reason codes -----------------------------------------------------------------


class ReasonCodeTests(unittest.TestCase):
    def test_knowledge_not_approved(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(knowledge_review_status="pending"))
        self.assertEqual(candidate.status, STRATEGY_BLOCKED)
        self.assertIn(KNOWLEDGE_NOT_APPROVED, candidate.reason_codes)

    def test_article_type_category_domain_unknown_codes(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(article_type=None, category="기타", domain="기타"))
        self.assertIn(ARTICLE_TYPE_UNKNOWN, candidate.reason_codes)
        self.assertIn(CATEGORY_UNKNOWN, candidate.reason_codes)
        self.assertIn(DOMAIN_UNKNOWN, candidate.reason_codes)

    def test_reason_codes_are_facts_not_forced_to_block(self) -> None:
        """ARTICLE_TYPE_UNKNOWN 등은 정보성 코드일 뿐 - 그 자체로 상태를
        BLOCKED/REVIEW_REQUIRED로 끌어내리지 않아야 한다(6-04 원칙: SCOUT
        경로 KNOWLEDGE는 article_type=None이 정상이다)."""
        candidate = evaluate_media_strategy(_knowledge(article_type=None))
        self.assertEqual(candidate.status, STRATEGY_READY)


# --- 4. evidence / 5. source ----------------------------------------------------------


class EvidenceSourceTests(unittest.TestCase):
    def test_missing_source_url(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(source_url=""))
        self.assertIn(SOURCE_MISSING, candidate.reason_codes)
        self.assertEqual(candidate.status, STRATEGY_INSUFFICIENT_EVIDENCE)

    def test_weak_source_url_format(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(source_url="not-a-url"))
        self.assertIn(SOURCE_WEAK, candidate.reason_codes)

    def test_missing_evidence(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(evidence=()))
        self.assertIn(EVIDENCE_INSUFFICIENT_CODE, candidate.reason_codes)
        self.assertEqual(candidate.evidence_quality, EVIDENCE_INSUFFICIENT)

    def test_both_missing_is_evidence_missing_not_just_insufficient(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(source_url="", evidence=()))
        self.assertEqual(candidate.evidence_quality, EVIDENCE_MISSING)

    def test_ai_does_not_fabricate_source(self) -> None:
        """11장: 출처가 없으면 AI가 출처를 만들어내지 않는다 - candidate의
        source_url이 원본 KNOWLEDGE 값과 정확히 같아야 한다(변형 없음)."""
        knowledge = _knowledge(source_url="")
        candidate = evaluate_media_strategy(knowledge)
        self.assertEqual(candidate.source_url, "")


# --- 6. duplicate / 7. novelty ----------------------------------------------------------


class DuplicateNoveltyTests(unittest.TestCase):
    def test_no_match_for_unique_content(self) -> None:
        candidate = evaluate_media_strategy(_knowledge())
        self.assertEqual(candidate.novelty_signal, NOVELTY_NO_MATCH)

    def test_possible_duplicate_same_url_different_title(self) -> None:
        existing = _knowledge(id="k-existing", source_url="https://example.test/dup", title="원래 제목")
        candidate_knowledge = _knowledge(id="k-new", source_url="https://example.test/dup", title="다른 관점의 제목")
        candidate = evaluate_media_strategy(candidate_knowledge, other_knowledge=[existing])
        self.assertEqual(candidate.novelty_signal, NOVELTY_POSSIBLE_DUPLICATE)
        self.assertIn(RECENTLY_COVERED, candidate.reason_codes)

    def test_high_duplicate_risk_same_url_and_title(self) -> None:
        existing = _knowledge(id="k-existing", source_url="https://example.test/dup", title="같은 뉴스")
        candidate_knowledge = _knowledge(id="k-new", source_url="https://example.test/dup", title="같은  뉴스")
        candidate = evaluate_media_strategy(candidate_knowledge, other_knowledge=[existing])
        self.assertEqual(candidate.novelty_signal, NOVELTY_HIGH_DUPLICATE_RISK)
        self.assertEqual(candidate.status, STRATEGY_DUPLICATE_RISK)

    def test_same_source_new_angle_is_not_auto_blocked(self) -> None:
        """8장: 동일 source_url이라도 새로운 사실/관점(제목이 다름)이면
        자동 차단하지 않는다 - POSSIBLE_DUPLICATE(REVIEW 필요)로만 표시하고
        STRATEGY_BLOCKED는 아니다."""
        existing = _knowledge(id="k-existing", source_url="https://example.test/same", title="1차 보도")
        candidate_knowledge = _knowledge(id="k-new", source_url="https://example.test/same", title="후속 분석 기사")
        candidate = evaluate_media_strategy(candidate_knowledge, other_knowledge=[existing])
        self.assertNotEqual(candidate.status, STRATEGY_BLOCKED)
        self.assertNotEqual(candidate.status, STRATEGY_DUPLICATE_RISK)

    def test_assess_novelty_pure_function_directly(self) -> None:
        signal, reasons = assess_novelty(_knowledge())
        self.assertEqual(signal, NOVELTY_NO_MATCH)
        self.assertEqual(reasons, ())


# --- 8. superseded ---------------------------------------------------------------------


class SupersededTests(unittest.TestCase):
    def test_old_knowledge_fully_superseded_is_not_ready(self) -> None:
        knowledge = _knowledge(id="knowledge-old")
        production = [_production_record(content_id="c-old", knowledge_id="knowledge-old", review_status="superseded", superseded_by="c-new")]
        candidate = evaluate_media_strategy(knowledge, production_records=production)
        self.assertEqual(candidate.status, STRATEGY_SUPERSEDED)
        self.assertIn(SUPERSEDED_SOURCE, candidate.reason_codes)

    def test_new_knowledge_is_evaluated_independently(self) -> None:
        old_knowledge = _knowledge(id="knowledge-old")
        new_knowledge = _knowledge(id="knowledge-new", source_url="https://example.test/corrected")
        production = [
            _production_record(content_id="c-old", knowledge_id="knowledge-old", review_status="superseded", superseded_by="c-new"),
            _production_record(content_id="c-new", knowledge_id="knowledge-new", review_status="approved"),
        ]
        new_candidate = evaluate_media_strategy(new_knowledge, production_records=production)
        self.assertEqual(new_candidate.status, STRATEGY_READY)

    def test_new_evidence_not_linked_to_old(self) -> None:
        old_knowledge = _knowledge(id="knowledge-old", evidence=("OLD EVIDENCE",))
        new_knowledge = _knowledge(id="knowledge-new", evidence=("NEW EVIDENCE",))
        production = [_production_record(content_id="c-old", knowledge_id="knowledge-old", review_status="superseded", superseded_by="c-new")]
        new_candidate = evaluate_media_strategy(new_knowledge, production_records=production)
        self.assertNotIn("OLD EVIDENCE", str(new_candidate.to_dict()))

    def test_knowledge_with_no_production_yet_is_not_superseded(self) -> None:
        """아직 한 번도 MEDIA로 만들어진 적 없는 신규 KNOWLEDGE는(정상적인
        신규 후보) superseded가 아니어야 한다."""
        candidate = evaluate_media_strategy(_knowledge(id="brand-new"), production_records=[])
        self.assertNotEqual(candidate.status, STRATEGY_SUPERSEDED)


# --- 9. high risk / 10. article_type separation -----------------------------------------


class HighRiskArticleTypeSeparationTests(unittest.TestCase):
    def test_finance_category_triggers_high_risk(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(category="금융"))
        self.assertIn(HIGH_RISK_TOPIC, candidate.risk_flags)
        self.assertTrue(candidate.human_review_required)

    def test_health_law_tax_investment_trigger_high_risk(self) -> None:
        for keyword in ("건강", "법률", "세금", "투자"):
            with self.subTest(keyword=keyword):
                candidate = evaluate_media_strategy(_knowledge(category=keyword, domain=keyword, id=f"k-{keyword}"))
                self.assertIn(HIGH_RISK_TOPIC, candidate.risk_flags)

    def test_category_alone_does_not_set_article_type(self) -> None:
        """6-04/6-32 원칙 재확인: category가 finance-like여도 article_type을
        임의로 "finance"로 바꾸지 않는다 - candidate.article_type은 원본
        KnowledgeRecord.article_type을 그대로 보존해야 한다."""
        knowledge = _knowledge(category="금융", article_type=None)
        candidate = evaluate_media_strategy(knowledge)
        self.assertIsNone(candidate.article_type)

    def test_ai_tech_category_tagged_as_finance_by_mistake_does_not_get_article_type_finance(self) -> None:
        """6-04의 구체적 재현 사례(BBC Business RSS의 AI 기사)와 동일한
        패턴을 6-37 경계에서도 재확인한다."""
        knowledge = _knowledge(category="금융", title="AI 안전성 속도 완화 촉구", article_type=None)
        candidate = evaluate_media_strategy(knowledge)
        self.assertIsNone(candidate.article_type)
        self.assertIn(HIGH_RISK_TOPIC, candidate.risk_flags, "category 자체의 안전장치(사람 확인)는 독립적으로 유지되어야 한다.")


# --- 11. human review ------------------------------------------------------------------


class HumanReviewTests(unittest.TestCase):
    def test_high_risk_requires_human_review(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(category="금융"))
        self.assertTrue(candidate.human_review_required)

    def test_possible_duplicate_requires_human_review(self) -> None:
        existing = _knowledge(id="k-existing", source_url="https://example.test/dup")
        candidate_knowledge = _knowledge(id="k-new", source_url="https://example.test/dup", title="다른 제목")
        candidate = evaluate_media_strategy(candidate_knowledge, other_knowledge=[existing])
        self.assertTrue(candidate.human_review_required)

    def test_safe_content_does_not_require_human_review(self) -> None:
        candidate = evaluate_media_strategy(_knowledge())
        self.assertFalse(candidate.human_review_required)

    def test_no_automatic_user_voice_rewriting(self) -> None:
        """13장: user voice rewriting을 이 모듈이 하지 않는다 - lesson/
        reusable_principle 등 원본 텍스트 필드를 candidate 어디에도 다시
        쓰지 않는다(topic만 title을 그대로 옮긴다)."""
        source = Path(__import__("content_engine.media_strategy", fromlist=["x"]).__file__).read_text(encoding="utf-8")
        for forbidden in ("rewrite", "Rewrite", "paraphrase"):
            self.assertNotIn(forbidden, source)


# --- 12. content angle -----------------------------------------------------------------


class ContentAngleTests(unittest.TestCase):
    def test_fact_angle_always_present(self) -> None:
        angles = suggest_content_angles(_knowledge())
        self.assertIn("FACT", angles)

    def test_practical_angle_when_action_or_result_present(self) -> None:
        angles = suggest_content_angles(_knowledge(action="이렇게 행동했다.", result=None))
        self.assertIn("PRACTICAL", angles)

    def test_angles_do_not_generate_actual_text(self) -> None:
        angles = suggest_content_angles(_knowledge())
        for angle in angles:
            self.assertIsInstance(angle, str)
            self.assertNotIn(" ", angle, "angle은 라벨이어야 한다 - 실제 문장이 아니다.")


# --- 13. generation handoff -----------------------------------------------------------


class GenerationHandoffTests(unittest.TestCase):
    def test_handoff_bundles_knowledge_and_candidate(self) -> None:
        knowledge = _knowledge()
        candidate = evaluate_media_strategy(knowledge)
        handoff = build_generation_handoff(candidate, knowledge)
        self.assertIs(handoff["knowledge"], knowledge)
        self.assertIs(handoff["strategy_candidate"], candidate)

    def test_ready_status_permits_generation_flag(self) -> None:
        knowledge = _knowledge()
        candidate = evaluate_media_strategy(knowledge)
        handoff = build_generation_handoff(candidate, knowledge)
        self.assertTrue(handoff["generation_permitted"])

    def test_blocked_status_does_not_permit_generation(self) -> None:
        knowledge = _knowledge(knowledge_review_status="pending")
        candidate = evaluate_media_strategy(knowledge)
        handoff = build_generation_handoff(candidate, knowledge)
        self.assertFalse(handoff["generation_permitted"])

    def test_mismatched_knowledge_id_raises(self) -> None:
        knowledge = _knowledge(id="k1")
        other_knowledge = _knowledge(id="k2")
        candidate = evaluate_media_strategy(knowledge)
        with self.assertRaises(MediaStrategyError):
            build_generation_handoff(candidate, other_knowledge)

    def test_handoff_knowledge_is_compatible_with_existing_generator_unchanged(self) -> None:
        """기존 content_engine.generator.generate_content_bundle()이 handoff의
        knowledge 필드를 아무 변형 없이 받을 수 있어야 한다(기존 generator를
        다시 작성하지 않는다는 지시 확인)."""
        from content_engine.generator import generate_content_bundle

        knowledge = _knowledge()
        candidate = evaluate_media_strategy(knowledge)
        handoff = build_generation_handoff(candidate, knowledge)
        bundle = generate_content_bundle(handoff["knowledge"])
        self.assertEqual(bundle.status, "complete")

    def test_strategy_ready_is_not_automatic_generation(self) -> None:
        """15장 핵심: strategy READY != 자동 generation. media_strategy 모듈이
        generator/pipeline을 실제로 import하지 않는다(모듈 속성으로 직접
        확인 - docstring 안의 설명 텍스트는 검사 대상이 아니다)."""
        import content_engine.media_strategy as module

        self.assertFalse(hasattr(module, "generate_content_bundle"))
        self.assertFalse(hasattr(module, "run_media_batch"))


# --- 14. idempotency ---------------------------------------------------------------------


class IdempotencyTests(unittest.TestCase):
    def test_same_knowledge_evaluated_ten_times_is_identical(self) -> None:
        knowledge = _knowledge()
        results = [evaluate_media_strategy(knowledge) for _ in range(10)]
        first = results[0]
        for other in results[1:]:
            self.assertEqual(first, other)


# --- 15. failure injection ---------------------------------------------------------------


class FailureInjectionTests(unittest.TestCase):
    def test_missing_knowledge_id_is_invalid(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(id=""))
        self.assertEqual(candidate.status, STRATEGY_INVALID)
        self.assertIn(MISSING_KNOWLEDGE_ID, candidate.reason_codes)

    def test_pending_knowledge_is_blocked(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(knowledge_review_status="pending"))
        self.assertEqual(candidate.status, STRATEGY_BLOCKED)

    def test_dismissed_knowledge_is_blocked(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(knowledge_review_status="dismissed"))
        self.assertEqual(candidate.status, STRATEGY_BLOCKED)

    def test_missing_source_is_insufficient_evidence(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(source_url=""))
        self.assertEqual(candidate.status, STRATEGY_INSUFFICIENT_EVIDENCE)

    def test_invalid_source_format_is_flagged(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(source_url="ftp://weird"))
        self.assertIn(SOURCE_WEAK, candidate.reason_codes)

    def test_missing_evidence_is_insufficient(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(evidence=()))
        self.assertEqual(candidate.status, STRATEGY_INSUFFICIENT_EVIDENCE)

    def test_malformed_evidence_does_not_crash_evaluation(self) -> None:
        """KnowledgeRecord 자체는 evidence 타입을 강제하지 않는다(기존
        스키마) - media_strategy는 그런 malformed 입력이 와도 크래시 없이
        평가를 완료해야 한다."""
        candidate = evaluate_media_strategy(_knowledge(evidence=("only-one-item",)))
        self.assertIsNotNone(candidate)

    def test_unknown_category_domain_article_type_are_recorded_not_blocking(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(category=None, domain=None, article_type=None))
        self.assertEqual(candidate.status, STRATEGY_READY)
        self.assertIn(CATEGORY_UNKNOWN, candidate.reason_codes)
        self.assertIn(DOMAIN_UNKNOWN, candidate.reason_codes)

    def test_duplicate_source_and_title(self) -> None:
        existing = _knowledge(id="k-a", source_url="https://example.test/x", title="제목")
        candidate = evaluate_media_strategy(_knowledge(id="k-b", source_url="https://example.test/x", title="제목"), other_knowledge=[existing])
        self.assertEqual(candidate.status, STRATEGY_DUPLICATE_RISK)

    def test_superseded_content_is_flagged(self) -> None:
        production = [_production_record(content_id="c1", knowledge_id="knowledge-1", review_status="superseded", superseded_by="c2")]
        candidate = evaluate_media_strategy(_knowledge(), production_records=production)
        self.assertEqual(candidate.status, STRATEGY_SUPERSEDED)

    def test_missing_content_id_is_prevented_upstream_by_media_archive_schema(self) -> None:
        """MediaArchiveRecord 자체가 content_id를 필수로 요구하므로(6-06
        기존 스키마), media_strategy에 malformed 레코드가 도달할 수 없다 -
        이 사실을 직접 확인한다(media_strategy가 별도로 방어할 필요가 없음)."""
        from content_engine.media_archive import MediaArchiveError

        with self.assertRaises(MediaArchiveError):
            replace(_production_record(), content_id="")

    def test_high_risk_topic_recorded(self) -> None:
        candidate = evaluate_media_strategy(_knowledge(category="부동산"))
        self.assertIn(HIGH_RISK_TOPIC, candidate.risk_flags)

    def test_secret_like_text_in_evidence_does_not_crash_or_leak_specially(self) -> None:
        secret_knowledge = _knowledge(evidence=("API_KEY=sk-secret-should-not-crash-anything",))
        candidate = evaluate_media_strategy(secret_knowledge)
        self.assertIsNotNone(candidate)

    def test_empty_input_list_via_cli_produces_no_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            knowledge_path = Path(tmp) / "knowledge.json"
            knowledge_path.write_text("[]", encoding="utf-8")
            exit_code = strategy_cli.main(["--knowledge", str(knowledge_path)])
            self.assertEqual(exit_code, 0)


# --- 16. security --------------------------------------------------------------------------


class SecurityTests(unittest.TestCase):
    def test_secret_marker_not_in_candidate_output(self) -> None:
        secret = "API_KEY=sk-secret-marker-6-37-should-never-leak"
        knowledge = _knowledge(evidence=(secret,))
        candidate = evaluate_media_strategy(knowledge)
        serialized = json.dumps(candidate.to_dict(), ensure_ascii=False)
        # evidence 원문은 candidate에 복사되지 않는다(reason code/status만 담는다) -
        # 시크릿이 evidence 필드에 있어도 candidate 출력에는 나타나지 않아야 한다.
        self.assertNotIn(secret, serialized)

    def test_secret_marker_not_in_cli_output(self) -> None:
        secret = "REFRESH_TOKEN=leak-marker-6-37"
        with tempfile.TemporaryDirectory() as tmp:
            knowledge_path = Path(tmp) / "knowledge.json"
            knowledge = _knowledge(evidence=(secret,))
            knowledge_path.write_text(json.dumps([knowledge.to_dict()], ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                strategy_cli.main(["--knowledge", str(knowledge_path)])
            self.assertNotIn(secret, buffer.getvalue())

    def test_secret_marker_not_in_dashboard_html(self) -> None:
        secret = "Authorization: Bearer leak-marker-6-37"
        knowledge = _knowledge(evidence=(secret,))
        candidate = evaluate_media_strategy(knowledge)
        html = render_media_strategy_list_html([candidate])
        self.assertNotIn(secret, html)


# --- 17. CLI ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([_knowledge().to_dict(), _knowledge(id="k2", category="금융").to_dict()], ensure_ascii=False),
            encoding="utf-8",
        )

    def test_json_output_is_valid_json(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = strategy_cli.main(["--knowledge", str(self.knowledge_path), "--json"])
        self.assertEqual(exit_code, 0)
        parsed = json.loads(buffer.getvalue())
        self.assertEqual(len(parsed), 2)

    def test_status_filter(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            strategy_cli.main(["--knowledge", str(self.knowledge_path), "--status", STRATEGY_REVIEW_REQUIRED, "--json"])
        parsed = json.loads(buffer.getvalue())
        self.assertTrue(all(item["status"] == STRATEGY_REVIEW_REQUIRED for item in parsed))

    def test_knowledge_id_filter(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            strategy_cli.main(["--knowledge", str(self.knowledge_path), "--knowledge-id", "k2", "--json"])
        parsed = json.loads(buffer.getvalue())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["knowledge_id"], "k2")

    def test_cli_does_not_write_any_file(self) -> None:
        before = sorted(p.name for p in self.tmp_path.iterdir())
        strategy_cli.main(["--knowledge", str(self.knowledge_path)])
        after = sorted(p.name for p in self.tmp_path.iterdir())
        self.assertEqual(before, after)


# --- 18. dashboard ---------------------------------------------------------------------


class DashboardTests(unittest.TestCase):
    def test_no_form_or_action_elements(self) -> None:
        candidate = evaluate_media_strategy(_knowledge())
        html = render_media_strategy_list_html([candidate])
        self.assertNotIn("<form", html)
        self.assertNotIn("generate", html.lower())
        self.assertNotIn("promote", html.lower())

    def test_status_filter_in_render(self) -> None:
        ready = evaluate_media_strategy(_knowledge(id="k-ready"))
        review = evaluate_media_strategy(_knowledge(id="k-review", category="금융"))
        html = render_media_strategy_list_html([ready, review], status=STRATEGY_REVIEW_REQUIRED)
        self.assertIn("k-review", html)
        self.assertNotIn("k-ready", html)

    def test_no_post_route_for_strategy_path(self) -> None:
        import scripts.run_scout_dashboard as dashboard_module

        source = Path(dashboard_module.__file__).read_text(encoding="utf-8")
        do_post_start = source.index("def do_POST")
        do_post_end = source.index("return DashboardRequestHandler", do_post_start)
        self.assertNotIn("/media/strategy", source[do_post_start:do_post_end])


# --- 19. E2E ---------------------------------------------------------------------------


class FullEndToEndTest(unittest.TestCase):
    def test_scout_to_generation_pool_via_strategy_gate_with_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / "tak_media_archive.json"

            old_knowledge = _knowledge(id="knowledge-old", source_url="https://example.test/old", title="OLD 정정 전 제목")
            new_knowledge = _knowledge(id="knowledge-new", source_url="https://example.test/new", title="NEW 정정 후 제목")

            old_production = _production_record(content_id="c-old", knowledge_id="knowledge-old", review_status="superseded", superseded_by="c-new")
            new_production = _production_record(content_id="c-new", knowledge_id="knowledge-new", review_status="approved")
            upsert_archive(archive_path, [old_production, new_production])
            before_bytes = archive_path.read_bytes()

            production_records = load_archive(archive_path)
            old_candidate = evaluate_media_strategy(old_knowledge, production_records=production_records, other_knowledge=[old_knowledge, new_knowledge])
            new_candidate = evaluate_media_strategy(new_knowledge, production_records=production_records, other_knowledge=[old_knowledge, new_knowledge])

            self.assertEqual(old_candidate.status, STRATEGY_SUPERSEDED)
            self.assertEqual(new_candidate.status, STRATEGY_READY)

            handoff = build_generation_handoff(new_candidate, new_knowledge)
            self.assertTrue(handoff["generation_permitted"])

            self.assertEqual(archive_path.read_bytes(), before_bytes, "전체 E2E 과정이 Production Archive를 건드리면 안 된다.")


# --- 20. production isolation ------------------------------------------------------------


class ProductionIsolationTests(unittest.TestCase):
    def test_evaluation_never_writes_to_knowledge_or_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            knowledge_path = tmp_path / "knowledge.json"
            archive_path = tmp_path / "archive.json"
            knowledge_path.write_text(json.dumps([_knowledge().to_dict()], ensure_ascii=False), encoding="utf-8")
            upsert_archive(archive_path, [_production_record()])

            before_knowledge = knowledge_path.read_bytes()
            before_archive = archive_path.read_bytes()

            from tak_brain import load_knowledge_records

            records = load_knowledge_records(knowledge_path)
            production_records = load_archive(archive_path)
            for record in records:
                evaluate_media_strategy(record, production_records=production_records, other_knowledge=records)

            self.assertEqual(knowledge_path.read_bytes(), before_knowledge)
            self.assertEqual(archive_path.read_bytes(), before_archive)


if __name__ == "__main__":
    unittest.main()
