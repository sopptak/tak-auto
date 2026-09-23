"""TAK AUTO 6-32 Content Production Engine Hardening
(docs/6-32-content-production-engine-hardening.md).

SCOUT -> KNOWLEDGE -> MEDIA 생산 구간을 집중 점검한다. 실제 외부 API/RSS
네트워크/Naver/Threads/YouTube 호출은 전혀 하지 않는다. 실제 운영 데이터
(data/)는 어디에서도 생성/수정하지 않는다 - 전부 tempfile/synthetic
fixture로만 검증한다.

이 파일이 다루는 것:
  1) SCOUT category(=RSS source의 블랭킷 카테고리)와 KNOWLEDGE article_type이
     혼동되지 않는다는 6-04의 기존 수정을 CASE A~D로 재확인(회귀 감지).
  2) SCOUT 중복 방지(URL/제목 정규화, 번역과 dedup의 독립성, knowledge_id
     idempotency)를 synthetic fixture로 검증.
  3) KST 스케줄(cron 23:00 UTC == 08:00 KST 익일) 산술 검증.
  4) content_engine.rewrite.RewriteValidator의 "경험" false positive를
     이번 세션에서 실제로 재현하고 수정한 뒤 regression test로 고정.
  5) MEDIA generation 단계의 content_id/generation_id overwrite 보호를
     실제 CLI(scripts/run_media_batch.py main())로 재확인.
  6) SCOUT candidate -> KNOWLEDGE pending -> 승인 -> MEDIA generation ->
     Generation Pool -> Human Review -> Promotion -> Production Archive ->
     Publish Readiness까지 하나의 First Content Rehearsal.
  7) SCOUT/KNOWLEDGE 레벨 Failure Injection(source unavailable, malformed
     feed, duplicate, missing evidence, missing source, approval missing).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import (
    MediaArchiveRecord,
    load_archive,
    new_generation_id,
    save_archive,
    upsert_generation_archive,
)
from content_engine.models import BlogDraft
from content_engine.publish_audit import READY, PublishAuditInputs, audit_archive
from content_engine.rewrite import RewriteRequest, RewriteValidator
from scripts.promote_media_generation import PromotionError, plan_promotion
from tak_brain import load_knowledge_records, select_approved
from tak_brain.knowledge import validate_knowledge
from tak_brain.models import KnowledgeRecord
from tak_scout.answers import InterviewAnswer
from tak_scout.collector import ScoutRssError, collect_all, dedupe_candidates
from tak_scout.knowledge_bridge import build_knowledge_from_interview
from tak_scout.models import ScoutCandidate

from tests.test_full_e2e_operating_readiness import _write_temp_knowledge_file


# --- Section 4: SCOUT CATEGORY 문제(6-04 회귀 감지) ------------------------------


def _candidate(**overrides) -> ScoutCandidate:
    defaults = dict(
        scout_id="scout-001",
        title="Anthropic CEO가 AI 개발 속도 완화를 촉구했다",
        summary="AI 안전성에 대한 우려가 제기되었다.",
        source_url="https://example.test/bbc-business/ai-safety",
        published_at="2026-01-01T00:00:00Z",
        source_name="BBC Business",
        category="finance",
    )
    defaults.update(overrides)
    return ScoutCandidate(**defaults)


def _answer(scout_id: str = "scout-001", option: str = "A") -> InterviewAnswer:
    return InterviewAnswer(scout_id=scout_id, selected_option=option, custom_answer="", answered_at="2026-01-01T00:10:00Z")


class ScoutCategoryContaminationTests(unittest.TestCase):
    def test_case_a_ai_tech_source_tagged_finance_does_not_get_finance_article_type(self) -> None:
        """CASE A: AI/Tech 기사가 BBC Business RSS(category="finance")로
        들어와도, article_type은 None이어야 한다(6-04 수정, content-based
        분류기가 SCOUT 경로에 없으므로 신뢰할 수 없는 신호를 만들지 않는다)."""
        candidate = _candidate(category="finance", title="AI 안전 속도 완화 촉구")
        knowledge = build_knowledge_from_interview(candidate, _answer())
        self.assertIsNone(knowledge.article_type, "SCOUT 경로에서 만든 KNOWLEDGE는 article_type을 추론하지 않아야 한다.")
        self.assertEqual(knowledge.category, "금융", "category/domain 자체는 원본 source category를 그대로 보존해야 한다(안전장치 유지).")

    def test_case_b_finance_article_type_only_settable_via_content_based_classification(self) -> None:
        """CASE B: 실제 금융 콘텐츠는 article_type="finance"가 될 수 있다 -
        단 SCOUT 경로가 아니라 tak_brain.article_types.ArticleTypeClassifier
        (실제 본문 키워드 분석)를 통해서만 가능함을 확인한다."""
        from tak_brain.article_types import ArticleTypeClassifier
        from tak_brain.models import RawContent

        raw = RawContent(
            id="p1",
            title="대출 금리 변경 안내",
            published_at="2026-01-01T00:00:00Z",
            body="이번 대출 상품의 영업이익과 당기순이익 기준이 변경되었습니다.",
            tags=(),
            source_url="https://example.test/finance-1",
            source="test",
            collected_at="2026-01-01T00:00:00Z",
            content_hash="hash1",
            extraction_method="test",
            extraction_status="ok",
        )
        classification = ArticleTypeClassifier().classify(raw)
        self.assertEqual(classification.article_type, "finance")

    def test_case_c_real_estate_content_follows_finance_review_policy(self) -> None:
        """CASE C: 부동산 콘텐츠는 category/domain에 "부동산"이 포함되면
        is_review_required()가 True를 반환해야 한다(article_type과 무관하게
        독립적으로 안전장치가 작동, 6-04 설계)."""
        from content_engine.blog_publish_pack import is_review_required

        candidate = _candidate(category="부동산", title="전세가율 급등")
        knowledge = build_knowledge_from_interview(candidate, _answer())
        self.assertIsNone(knowledge.article_type)
        self.assertTrue(is_review_required(knowledge), "부동산 category는 article_type=None이어도 사람 확인이 필요해야 한다.")

    def test_case_d_missing_category_falls_back_safely(self) -> None:
        """CASE D: category가 CATEGORIES 목록에도 별칭 목록에도 없으면
        "기타"로 안전하게 fallback해야 한다(크래시 없음)."""
        candidate = _candidate(category="unknown-category-xyz")
        knowledge = build_knowledge_from_interview(candidate, _answer())
        self.assertEqual(knowledge.category, "기타")
        self.assertIsNone(knowledge.article_type)


# --- Section 5: SCOUT 중복 방지 --------------------------------------------------


class ScoutDuplicateDetectionTests(unittest.TestCase):
    def test_same_url_different_case_and_trailing_slash_is_deduped(self) -> None:
        c1 = _candidate(scout_id="a", source_url="https://example.test/story", title="제목 A")
        c2 = _candidate(scout_id="b", source_url="HTTPS://EXAMPLE.TEST/story/", title="제목 B(다른 제목)")
        result = dedupe_candidates([c1, c2])
        self.assertEqual(len(result), 1, "URL이 대소문자/trailing slash만 다르면 같은 소재로 처리해야 한다.")
        self.assertEqual(result[0].scout_id, "a", "먼저 나온 후보만 남아야 한다.")

    def test_same_title_different_whitespace_from_different_sources_is_deduped(self) -> None:
        c1 = _candidate(scout_id="a", source_url="https://example.test/source1/1", title="AI  안전  속도  완화")
        c2 = _candidate(scout_id="b", source_url="https://example.test/source2/1", title="ai 안전 속도 완화")
        result = dedupe_candidates([c1, c2])
        self.assertEqual(len(result), 1, "제목이 공백/대소문자만 다르면 다른 source/URL이어도 중복으로 처리해야 한다.")

    def test_genuinely_different_stories_are_not_deduped(self) -> None:
        c1 = _candidate(scout_id="a", source_url="https://example.test/story-a", title="AI 안전 속도 완화 촉구")
        c2 = _candidate(scout_id="b", source_url="https://example.test/story-b", title="부동산 전세가율 급등")
        result = dedupe_candidates([c1, c2])
        self.assertEqual(len(result), 2, "실제로 다른 이야기는 중복 제거되면 안 된다.")

    def test_translation_does_not_affect_dedup(self) -> None:
        """title_translation.py의 번역은 별도 파일(scout_id 키)에 저장되고
        interview 표시 단계에서만 쓰인다 - dedupe_candidates()는 원문 제목만
        비교하므로 번역 여부와 무관하게 동일한 결과를 내야 한다."""
        c1 = _candidate(scout_id="a", source_url="https://example.test/story-1", title="Original English Title")
        c2 = _candidate(scout_id="b", source_url="https://example.test/story-2", title="Original English Title")
        result_before = dedupe_candidates([c1, c2])
        # "번역"은 여기서 별도 파일에 저장될 뿐 candidate.title 자체를 바꾸지 않는다 -
        # 따라서 dedupe 결과는 번역 유무와 무관하게 동일해야 한다(구조적으로 항상 참).
        result_after = dedupe_candidates([c1, c2])
        self.assertEqual(len(result_before), len(result_after))
        self.assertEqual(len(result_before), 1, "제목이 완전히 같으면(번역 전 원문 기준) 중복 제거되어야 한다.")

    def test_same_scout_id_and_answer_produces_idempotent_knowledge_id(self) -> None:
        """같은 scout_id에 같은 답변을 두 번 적용해도(재실행 시나리오)
        knowledge_id는 결정적으로 동일해야 한다 - 중복 KNOWLEDGE가 생기지
        않는다(sha256(scout_id:option:custom) 기반, 6-32에서 정책 변경 없음)."""
        candidate = _candidate()
        answer = _answer()
        k1 = build_knowledge_from_interview(candidate, answer)
        k2 = build_knowledge_from_interview(candidate, answer)
        self.assertEqual(k1.id, k2.id)

    def test_source_collection_failure_does_not_stop_other_sources(self) -> None:
        """RSS source 1건이 실패해도(malformed feed/unavailable) 나머지
        source는 계속 수집되어야 한다(6-24에서 이미 확립, 6-32에서 재확인)."""
        sources = [
            {"name": "broken", "url": "https://example.test/broken.xml", "category": "기타"},
            {"name": "ok", "url": "https://example.test/ok.xml", "category": "기타"},
        ]

        def fake_collect_from_source(source, timeout=20.0):
            if source["name"] == "broken":
                raise ScoutRssError("malformed feed (simulated)")
            return [_candidate(scout_id="ok-1", source_url="https://example.test/ok-1")]

        with mock.patch("tak_scout.collector.collect_from_source", side_effect=fake_collect_from_source):
            candidates, results = collect_all(sources)

        self.assertEqual(len(candidates), 1)
        by_name = {r.name: r for r in results}
        self.assertIsNotNone(by_name["broken"].error)
        self.assertIsNone(by_name["ok"].error)


# --- Section 6: KST Schedule -----------------------------------------------------


class KstScheduleTests(unittest.TestCase):
    def test_workflow_cron_is_23_00_utc_which_is_08_00_kst_next_day(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-scout.yml"
        text = workflow_path.read_text(encoding="utf-8")
        self.assertIn("cron: '0 23 * * *'", text, "daily-scout.yml의 cron 표현식이 바뀌었으면 이 테스트도 갱신해야 한다.")
        # 23:00 UTC + 9시간(KST, DST 없음) = 다음날 08:00 KST.
        utc_hour = 23
        kst_offset_hours = 9
        kst_hour = (utc_hour + kst_offset_hours) % 24
        self.assertEqual(kst_hour, 8)


# --- Section 14: MEDIA 콘텐츠 안전성 - "경험" false positive -------------------


class ExperienceFalsePositiveRegressionTests(unittest.TestCase):
    """6-32에서 재현하고 수정한 버그: content_engine/rewrite.py의
    _FACT_RISK_TERMS에 "경험"이 있으면, source_text에 그 글자가 우연히 없는
    한(예: knowledge_type이 "의견"인 SCOUT 경로) 새로운 사실이 전혀 없는
    재작성도 "사실 범위를 넓히는 표현"으로 잘못 차단됐다. "경험"을 제거하는
    최소 수정을 적용했다 - 다른 위험 단어(성과/수익/매출/계약/투자 등)는
    그대로 유지되어 실제 새 사실은 여전히 차단된다."""

    def _knowledge(self) -> KnowledgeRecord:
        return KnowledgeRecord(
            id="k1", source_raw_id="r1", source_url="https://example.test/1",
            title="AI 도구 활용 후기", article_type=None, domain="기술", category="기술",
            knowledge_type="의견",
            lesson="이 도구를 써보니 업무 속도가 빨라졌다.",
            reusable_principle="새로운 도구는 일단 써보는 게 낫다.",
            evidence=("SOURCE FACT: AI 도구 출시", "SOURCE URL: https://example.test/1"),
            inference_method="rule_based_template", confidence=None, created_at="2026-01-01T00:00:00Z",
            knowledge_review_status="approved",
        )

    def test_using_the_word_experience_alone_is_not_flagged(self) -> None:
        knowledge = self._knowledge()
        draft = BlogDraft(
            title="AI 도구 활용 후기", body="이 도구를 써보니 업무 속도가 빨라졌다.",
            source_url="https://example.test/1", evidence=knowledge.evidence,
        )
        rewritten = BlogDraft(
            title="AI 도구를 쓴 경험",
            body="제가 이 도구를 써 본 경험을 나눕니다. 확실히 속도가 빨라졌어요.",
            source_url="https://example.test/1", evidence=knowledge.evidence,
        )
        req = RewriteRequest(
            knowledge=knowledge, draft=draft, source_url=draft.source_url, evidence=draft.evidence,
            article_type=knowledge.article_type, knowledge_type=knowledge.knowledge_type,
        )
        result = RewriteValidator().validate(req, rewritten)
        self.assertEqual(result.status, "valid", f"'경험'이라는 단어만으로 차단되면 안 된다: {result.errors}")

    def test_genuinely_new_facts_are_still_rejected(self) -> None:
        """회귀 방지 검증: validator를 느슨하게 만들지 않았다는 것을 함께
        확인한다 - "매출"/"계약" 같은 실제 새 사실 주장은 여전히 차단된다."""
        knowledge = self._knowledge()
        draft = BlogDraft(
            title="AI 도구 활용 후기", body="이 도구를 써보니 업무 속도가 빨라졌다.",
            source_url="https://example.test/1", evidence=knowledge.evidence,
        )
        rewritten = BlogDraft(
            title="AI 도구로 매출 상승",
            body="이 도구로 매출이 크게 늘었고 새로운 계약도 성사됐습니다.",
            source_url="https://example.test/1", evidence=knowledge.evidence,
        )
        req = RewriteRequest(
            knowledge=knowledge, draft=draft, source_url=draft.source_url, evidence=draft.evidence,
            article_type=knowledge.article_type, knowledge_type=knowledge.knowledge_type,
        )
        result = RewriteValidator().validate(req, rewritten)
        self.assertEqual(result.status, "invalid")
        self.assertTrue(any("매출" in e for e in result.errors))
        self.assertTrue(any("계약" in e for e in result.errors))


# --- Section 11: content_id / generation_id overwrite 보호(MEDIA CLI 레벨) -----


class MediaGenerationOverwriteProtectionTests(unittest.TestCase):
    """generation A -> content_id X(approved, production archive에 반영됨)
    이후 generation B -> 같은 content_id X를 --as-generation 없이 다시
    아카이브에 쓰려 하면 scripts/run_media_batch.py의 main()이 실제로
    차단하는지 CLI 레벨에서 재확인한다(6-24 가드, 이번에는 run_media_batch.py
    main() 전체 경로로 검증 - 기존 회귀는 find_protected_overwrite_targets()
    단위 테스트 수준이었다)."""

    def test_reexecuting_media_batch_on_approved_content_is_blocked_by_cli(self) -> None:
        import scripts.run_media_batch as run_media_batch_module

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            knowledge_path = _write_temp_knowledge_file()
            archive_path = tmp_path / "tak_media_archive.json"

            with mock.patch(
                "scripts.run_media_batch.OpenAICompatibleRewriteProvider.from_environment",
                return_value=mock.Mock(),
            ), mock.patch(
                "scripts.run_media_batch.run_media_batch_file"
            ) as fake_run:
                from content_engine.pipeline import run_media_batch as real_run_media_batch
                from content_engine.rewrite import MockRewriteProvider

                records = load_knowledge_records(knowledge_path)
                approved = list(select_approved(records))
                report = real_run_media_batch(approved, provider=MockRewriteProvider())
                fake_run.return_value = report

                approved_record = replace(
                    MediaArchiveRecord.from_item(
                        next(i for i in report.items if i.platform == "threads"), generation_id="gen-A"
                    ),
                    review_status="approved",
                )
                save_archive([approved_record], archive_path)

                exit_code = run_media_batch_module.main(
                    [
                        "--input", str(knowledge_path),
                        "--archive", str(archive_path),
                        "--execute",
                    ]
                )

        self.assertEqual(exit_code, 1, "이미 approved인 content_id를 --as-generation 없이 재실행하면 CLI가 exit 1로 차단해야 한다.")


# --- Section 20: 10월 1일 First Content Rehearsal --------------------------------


class FirstContentRehearsalTest(unittest.TestCase):
    def test_scout_candidate_reaches_publish_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # SCOUT candidate (synthetic, 실제 RSS 호출 없음)
            candidate = _candidate(
                scout_id="scout-rehearsal-1",
                title="비개발자가 AI로 사이드 프로젝트를 완성했다",
                category="기타",
            )
            answer = _answer(scout_id="scout-rehearsal-1", option="A")

            # KNOWLEDGE pending
            knowledge = build_knowledge_from_interview(candidate, answer)
            validate_knowledge(knowledge)
            self.assertEqual(knowledge.knowledge_review_status, "pending")

            # Human approval(사람이 승인 - AI가 직접 바꾸지 않음)
            approved_knowledge = replace(knowledge, knowledge_review_status="approved")
            knowledge_path = tmp_path / "knowledge.json"
            knowledge_path.write_text(json.dumps([approved_knowledge.to_dict()], ensure_ascii=False), encoding="utf-8")

            records = load_knowledge_records(knowledge_path)
            approved = list(select_approved(records))
            self.assertEqual(len(approved), 1)

            # MEDIA generation -> Generation Pool
            from content_engine.pipeline import run_media_batch
            from content_engine.rewrite import MockRewriteProvider

            report = run_media_batch(approved, provider=MockRewriteProvider())
            self.assertEqual(report.total_draft_count, 9)

            generation_pool_path = tmp_path / "generation_pool.json"
            generation_id = new_generation_id(knowledge.id)
            gen_records = [MediaArchiveRecord.from_item(i, generation_id=generation_id) for i in report.items]
            upsert_generation_archive(generation_pool_path, gen_records)

            # Human Review: 하나를 승인
            threads_item = next(i for i in report.items if i.platform == "threads" and i.status == "valid")
            from content_engine.publish_history import compute_content_id

            content_id = compute_content_id(threads_item.to_dict())
            pool_records = load_archive(generation_pool_path)
            updated = [replace(r, review_status="approved") if r.content_id == content_id else r for r in pool_records]
            save_archive(updated, generation_pool_path)

            # Promotion -> Production Archive
            production_archive_path = tmp_path / "tak_media_archive.json"
            candidate_record, current_active = plan_promotion(
                generation_pool_path, production_archive_path, content_id, generation_id
            )
            self.assertIsNone(current_active)
            from content_engine.media_archive import upsert_archive

            upsert_archive(production_archive_path, [candidate_record])

            # Publish Readiness
            production_records = load_archive(production_archive_path)
            knowledge_by_id = {approved_knowledge.id: approved_knowledge}
            results = audit_archive(production_records, inputs=PublishAuditInputs(knowledge_by_id=knowledge_by_id))
            self.assertEqual(results[0].status, READY)

        self.assertFalse(Path(tmp).exists())


# --- Section 21: SCOUT/KNOWLEDGE Failure Injection -------------------------------


class ScoutKnowledgeFailureInjectionTests(unittest.TestCase):
    def test_source_unavailable_is_isolated(self) -> None:
        sources = [{"name": "down", "url": "https://example.test/down.xml", "category": "기타"}]
        with mock.patch("tak_scout.collector.collect_from_source", side_effect=ScoutRssError("timeout (simulated)")):
            candidates, results = collect_all(sources)
        self.assertEqual(candidates, [])
        self.assertIsNotNone(results[0].error)

    def test_malformed_feed_raises_scout_rss_error_not_generic_crash(self) -> None:
        from tak_scout.rss import parse_rss_items

        with self.assertRaises(ScoutRssError):
            parse_rss_items("<not valid xml", source_name="broken", category="기타")

    def test_duplicate_within_same_run_is_removed(self) -> None:
        c1 = _candidate(scout_id="a", source_url="https://example.test/dup", title="같은 뉴스")
        c2 = _candidate(scout_id="b", source_url="https://example.test/dup", title="같은 뉴스")
        self.assertEqual(len(dedupe_candidates([c1, c2])), 1)

    def test_missing_source_url_is_rejected_by_validate_knowledge(self) -> None:
        knowledge = build_knowledge_from_interview(_candidate(), _answer())
        broken = replace(knowledge, source_url="")
        with self.assertRaises(ValueError):
            validate_knowledge(broken)

    def test_missing_evidence_does_not_crash_but_is_visible_to_reviewer(self) -> None:
        knowledge = build_knowledge_from_interview(_candidate(), _answer())
        broken = replace(knowledge, evidence=())
        # validate_knowledge()는 evidence 존재를 강제하지 않는다(현재 정책,
        # 6-32에서 바꾸지 않는다) - 사람이 review_knowledge.py에서 evidence가
        # 빈 것을 보고 판단하는 것이 현재 설계다. 크래시 없이 통과함을 확인.
        validate_knowledge(broken)
        self.assertEqual(broken.evidence, ())

    def test_approval_missing_means_media_batch_produces_nothing(self) -> None:
        knowledge = build_knowledge_from_interview(_candidate(), _answer())
        self.assertEqual(knowledge.knowledge_review_status, "pending")
        approved = list(select_approved([knowledge]))
        self.assertEqual(approved, [], "승인되지 않은 KNOWLEDGE는 MEDIA 대상에서 제외되어야 한다.")


if __name__ == "__main__":
    unittest.main()
