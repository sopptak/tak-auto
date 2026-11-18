import io
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from content_engine.media_assets import MediaAssetStore
from content_engine.performance_insight import InsightRecord, STATUS_ACCEPTED, STATUS_CANDIDATE, append_insights
from scripts import run_trend_content_mvp


class TrendContentQueueRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name)
        self.preview = {
            "keyword": "테스트 키워드",
            "threads": [{"title": "제목", "body": "승인된 Threads 원고"}],
            "facebook": {"title": "Facebook 제목", "body": "Facebook 전용 게시문"},
            "blog": {"title": "블로그 제목", "body": "블로그 본문"},
            "shorts": [{
                "title": "쇼츠 제목", "body": "영상 대본",
                "youtube_description": "YouTube 설명",
                "instagram_caption": "Instagram 캡션",
                "tiktok_caption": "TikTok 캡션",
                "hashtags": ["탁자동", "#shorts"],
            }],
        }
        self.environment = patch.dict(os.environ, {
            "TAK_AUTO_MEDIA_SIGNING_KEY": "test-signing-key-that-is-at-least-32-chars",
            "TAK_AUTO_PUBLIC_URL": "https://tak-auto.example.test",
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.data_dir_patch = patch.object(run_trend_content_mvp, "DATA_DIR", self.data_dir)
        self.data_dir_patch.start()
        self.addCleanup(self.data_dir_patch.stop)
        payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
        self.asset = MediaAssetStore(
            self.data_dir, os.environ["TAK_AUTO_MEDIA_SIGNING_KEY"],
            os.environ["TAK_AUTO_PUBLIC_URL"],
        ).save_stream(io.BytesIO(payload), len(payload), "approved.mp4")

    def _valid_package(self):
        return {
            "blog": {
                "title": "블로그 제목", "meta_description": "검색 설명",
                "focus_keyword": "핵심 키워드", "body": "본문 " * 200,
            },
            "shorts": {
                "title": "쇼츠 제목", "hook": "첫 3초 후킹", "closing_cta": "댓글 남겨주세요",
                "duration_seconds": 60, "youtube_description": "설명",
                "instagram_caption": "릴스 문안", "tiktok_caption": "틱톡 문안",
                "hashtags": ["탁자동"],
                "scenes": [
                    {"time": f"00-0{i}초", "visual": "화면 구성", "caption": "자막", "narration": "내레이션"}
                    for i in range(5)
                ],
            },
            "threads": [
                {"title": "Threads 제목", "body": "Threads 본문"},
                {"title": "Threads 제목 2", "body": "Threads 본문 2"},
            ],
        }

    def test_render_storage_requires_an_actual_mount_not_just_a_writable_directory(self):
        configured = self.data_dir / "render-disk"
        fallback_root = self.data_dir / "tmp"
        with patch.dict(os.environ, {"RENDER_SERVICE_ID": "srv-test"}, clear=False):
            with patch.object(run_trend_content_mvp.tempfile, "gettempdir", return_value=str(fallback_root)):
                with patch("scripts.run_trend_content_mvp.os.path.ismount", return_value=False):
                    resolved, is_fallback = run_trend_content_mvp._resolve_writable_data_dir(configured)
        self.assertTrue(is_fallback)
        self.assertEqual(resolved, fallback_root / "tak-auto-data")
        same_as_fallback = fallback_root / "tak-auto-data"
        with patch.dict(os.environ, {"RENDER_SERVICE_ID": "srv-test"}, clear=False):
            with patch.object(run_trend_content_mvp.tempfile, "gettempdir", return_value=str(fallback_root)):
                with patch("scripts.run_trend_content_mvp.os.path.ismount", return_value=False):
                    resolved_same, same_is_fallback = run_trend_content_mvp._resolve_writable_data_dir(same_as_fallback)
        self.assertTrue(same_is_fallback)
        self.assertEqual(resolved_same, same_as_fallback)


        with patch.dict(os.environ, {"RENDER_SERVICE_ID": "srv-test"}, clear=False):
            with patch("scripts.run_trend_content_mvp.os.path.ismount", return_value=True):
                resolved, is_fallback = run_trend_content_mvp._resolve_writable_data_dir(configured)
        self.assertFalse(is_fallback)
        self.assertEqual(resolved, configured)

    def test_health_payload_reports_persistent_storage_mode(self):
        environment = {
            "TAK_SCOUT_PERPLEXITY_API_KEY": "configured",
            "TAK_WEB_USERNAME": "operator",
            "TAK_WEB_PASSWORD": "secret",
        }
        with patch.object(run_trend_content_mvp, "USING_EPHEMERAL_STORAGE", False):
            persistent = run_trend_content_mvp._health_payload(environment)
        self.assertTrue(persistent["storage_persistent"])
        self.assertEqual(persistent["storage_mode"], "persistent_disk")
        with patch.object(run_trend_content_mvp, "USING_EPHEMERAL_STORAGE", True):
            fallback = run_trend_content_mvp._health_payload(environment)
        self.assertFalse(fallback["storage_persistent"])
        self.assertEqual(fallback["storage_mode"], "ephemeral_fallback")

    def test_write_json_uses_atomic_replacement_and_leaves_no_temp_files(self):
        path = self.data_dir / "atomic-state.json"
        run_trend_content_mvp._write_json(path, {"version": 1, "value": "처음"})
        run_trend_content_mvp._write_json(path, {"version": 2, "value": "두 번째"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 2, "value": "두 번째"})
        self.assertEqual(list(self.data_dir.glob(".atomic-state.json.*.tmp")), [])

    def test_editorial_revision_target_maps_factual_claims_to_correct_platform_copy(self):
        self.assertEqual(
            run_trend_content_mvp._editorial_target({"area": "블로그"}),
            ("blog.body", "blog"),
        )
        self.assertEqual(
            run_trend_content_mvp._editorial_target({"area": "Threads 2"}),
            ("threads.1.body", "threads"),
        )
        self.assertEqual(
            run_trend_content_mvp._editorial_target({"area": "Facebook"}),
            ("facebook.body", "facebook"),
        )

    def test_concurrent_json_writes_never_leave_partial_json_or_shared_temp_conflicts(self):
        path = self.data_dir / "concurrent-state.json"
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(
                lambda index: run_trend_content_mvp._write_json(
                    path, {"writer": index, "payload": "한글 데이터 " * 100},
                ),
                range(24),
            ))
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(stored["writer"], range(24))
        self.assertEqual(list(self.data_dir.glob(".concurrent-state.json.*.tmp")), [])

    def test_generated_preview_carries_stable_knowledge_identity(self):
        package = self._valid_package()
        provider = Mock()
        provider.search.return_value = SimpleNamespace(
            answer=json.dumps(package, ensure_ascii=False),
            citations=["https://example.test/citation"],
            model="test-model",
        )
        item = {
            "keyword": "테스트 키워드",
            "category": "경제",
            "summary": "최근 주목할 만한 변화에 대한 요약입니다.",
            "why_now": "최근 발표된 제도 변화가 독자에게 영향을 주기 때문입니다.",
            "audience_question": "실제 생활에서 어떤 점을 확인해야 할까요?",
            "content_angle": "현장 적용 시 확인해야 할 핵심 사항을 정리합니다.",
            "key_points": [
                "첫 번째 독립 근거로 공식 발표 내용을 확인합니다.",
                "두 번째 독립 근거로 실제 적용 사례를 검토합니다.",
                "세 번째 독립 근거로 주의할 점을 비교합니다.",
            ],
            "source_urls": ["https://example.test/source"],
        }
        preview = run_trend_content_mvp._make_preview(
            item, {"citations": []}, provider=provider,
        )
        self.assertTrue(preview["knowledge_id"].startswith("trend-preview-"))
        self.assertEqual(preview["source_urls"][0], "https://example.test/source")
        identity_payload = json.dumps(
            {"keyword": "테스트 키워드", "source_urls": ["https://example.test/source"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        expected_id = "trend-preview-" + __import__("hashlib").sha256(
            identity_payload.encode("utf-8")
        ).hexdigest()[:16]
        self.assertEqual(preview["knowledge_id"], expected_id)

        # Same topic + same source set is stable; a different source event gets a new lineage.
        repeated = run_trend_content_mvp._make_preview(
            item, {"citations": []}, provider=provider,
        )
        self.assertEqual(repeated["knowledge_id"], preview["knowledge_id"])
        different_event = dict(item, source_urls=["https://example.test/another-event"])
        other_preview = run_trend_content_mvp._make_preview(
            different_event, {"citations": []}, provider=provider,
        )
        self.assertNotEqual(other_preview["knowledge_id"], preview["knowledge_id"])

    def _insight(self, insight_id, status=STATUS_ACCEPTED, result="INCREASING"):
        return InsightRecord(
            insight_id=insight_id, created_at="2026-11-18T00:00:00+00:00",
            analysis_window="all", scope="content", scope_id="content-1",
            platform="threads", metric="views", insight_type="trend",
            result=result, observation="첫 문장에 구체적 질문을 둔 게시물의 조회 추세가 증가했습니다.",
            evidence=({"content_id": "content-1", "metric_collected_at": "2026-11-17T00:00:00+00:00", "value": 100},),
            sample_size=3, status=status,
        )

    def test_only_explicitly_selected_accepted_insights_are_returned(self):
        path = self.data_dir / "insights.json"
        append_insights(path, [
            self._insight("accepted-1"),
            self._insight("candidate-1", STATUS_CANDIDATE),
            self._insight("insufficient-1", result="INSUFFICIENT_SAMPLE"),
        ])
        selected = run_trend_content_mvp._select_accepted_strategy_insights(
            ["accepted-1"], path=path,
        )
        self.assertEqual([row["insight_id"] for row in selected], ["accepted-1"])
        self.assertEqual(selected[0]["sample_size"], 3)

    def test_candidate_insights_cannot_be_used_as_generation_guidance(self):
        path = self.data_dir / "insights.json"
        append_insights(path, [self._insight("candidate-1", STATUS_CANDIDATE)])
        with self.assertRaisesRegex(ValueError, "사람이 승인한"):
            run_trend_content_mvp._select_accepted_strategy_insights(
                ["candidate-1"], path=path,
            )

    def test_insufficient_sample_insights_are_rejected_as_generation_guidance(self):
        path = self.data_dir / "insights.json"
        append_insights(path, [self._insight("low-sample", result="INSUFFICIENT_SAMPLE")])
        with self.assertRaisesRegex(ValueError, "표본 부족"):
            run_trend_content_mvp._select_accepted_strategy_insights(
                ["low-sample"], path=path,
            )

    def test_selected_insight_context_is_labeled_as_non_factual_guidance(self):
        context = [{
            "insight_id": "accepted-1", "platform": "threads", "metric": "views",
            "insight_type": "trend", "result": "INCREASING",
            "observation": "구체적 질문으로 시작한 게시물의 조회 추세 증가",
            "sample_size": 3,
        }]
        prompt = run_trend_content_mvp._build_content_prompt(
            {"keyword": "테스트", "source_urls": ["https://example.test/source"]},
            {"researched_at": "2026-11-18"},
            strategy_insights=context,
        )
        self.assertIn("human_accepted_performance_insights", prompt)
        self.assertIn("사실 근거가 아니라 형식·후킹·구성의 참고자료", prompt)
        self.assertIn("accepted-1", prompt)

    def test_source_integrity_accepts_valid_linked_source_and_generated_citation(self):
        report = run_trend_content_mvp._evaluate_source_integrity(
            {"source_urls": ["https://example.test/article"]},
            {}, ["https://example.test/article"],
        )
        self.assertEqual(report["status"], "URL 형식·연결 확인")
        self.assertEqual(report["source_count"], 1)
        self.assertEqual(report["warnings"], [])
        self.assertIn("원문 접속", report["scope_note"])

    def test_source_integrity_flags_missing_sources(self):
        report = run_trend_content_mvp._evaluate_source_integrity({}, {}, [])
        self.assertEqual(report["status"], "검토 필요")
        self.assertIn("연결된 유효 출처 URL이 없습니다.", report["warnings"])

    def test_source_integrity_flags_malformed_and_duplicate_source_urls(self):
        report = run_trend_content_mvp._evaluate_source_integrity(
            {"source_urls": ["ftp://example.test/file", "https://example.test/a#one", "https://example.test/a#two"]},
            {},
        )
        self.assertTrue(report["malformed_urls"])
        self.assertTrue(report["duplicate_urls"])
        self.assertEqual(report["status"], "검토 필요")

    def test_source_integrity_flags_generated_citation_not_in_research_sources(self):
        report = run_trend_content_mvp._evaluate_source_integrity(
            {"source_urls": ["https://example.test/research"]},
            {}, ["https://other.test/unlinked"],
        )
        self.assertEqual(report["unlinked_citations"], ["https://other.test/unlinked"])
        self.assertTrue(any("출처 목록에 없는" in warning for warning in report["warnings"]))

    def test_claim_citation_coverage_flags_numeric_claim_without_sentence_url(self):
        package = {"blog": {"body": "2026년 조사에서 응답자의 35%가 해당 서비스를 이용했다고 발표했습니다."}}
        report = run_trend_content_mvp._evaluate_claim_citation_coverage(package, ["https://example.test/report"])
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["unlinked_count"], 1)
        self.assertEqual(report["status"], "문장별 검토 필요")
        self.assertIn("의미적으로 검증", report["scope_note"])

    def test_claim_citation_coverage_recognizes_url_only_when_attached_to_same_sentence(self):
        url = "https://example.test/report"
        package = {"blog": {"body": f"2026년 조사에서 응답자의 35%가 해당 서비스를 이용했다고 발표했습니다. {url}"}}
        report = run_trend_content_mvp._evaluate_claim_citation_coverage(package, [url])
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["unlinked_count"], 0)
        self.assertEqual(report["claims"][0]["attached_sources"], [url])

    def test_claim_citation_coverage_does_not_treat_url_elsewhere_as_claim_support(self):
        url = "https://example.test/report"
        package = {"blog": {"body": f"2026년 조사에서 응답자의 35%가 해당 서비스를 이용했다고 발표했습니다.\n\n참고 출처: {url}"}}
        report = run_trend_content_mvp._evaluate_claim_citation_coverage(package, [url])
        self.assertEqual(report["unlinked_count"], 1)

    def test_editorial_recommendations_are_actionable_and_preserve_original_claim(self):
        quality = {
            "warnings": ["쇼츠 첫 3초 후킹 문장"],
            "search_intent": {
                "type": "절차형",
                "audience_question": "어떻게 신청하나요?",
                "answer_cue_present": False,
            },
        }
        claims = {
            "claims": [{
                "section": "블로그",
                "claim": "2026년 지원금은 300만원으로 확정됐습니다.",
                "citation_attached": False,
            }]
        }
        proposals = run_trend_content_mvp._build_editorial_recommendations(quality, claims)
        self.assertGreaterEqual(len(proposals), 3)
        claim_proposal = next(row for row in proposals if row["area"] == "블로그")
        self.assertEqual(claim_proposal["original"], "2026년 지원금은 300만원으로 확정됐습니다.")
        self.assertIn("원문을 열어", claim_proposal["proposal"])
        self.assertTrue(all("proposal" in row and "reason" in row for row in proposals))

    def test_editorial_recommendation_fingerprint_is_preview_scoped(self):
        recommendation = {"area": "블로그", "original": "주장", "proposal": "원문 확인"}
        first = run_trend_content_mvp._editorial_recommendation_key(recommendation, "knowledge-a")
        repeated = run_trend_content_mvp._editorial_recommendation_key(recommendation, "knowledge-a")
        other_preview = run_trend_content_mvp._editorial_recommendation_key(recommendation, "knowledge-b")
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other_preview)

    def test_editorial_target_mapping_is_explicit_and_rejects_unsupported_fields(self):
        self.assertEqual(
            run_trend_content_mvp._editorial_target({"area": "블로그 본문"}),
            ("blog.body", "blog"),
        )
        self.assertEqual(
            run_trend_content_mvp._editorial_target({"area": "Threads"}),
            ("threads.0.body", "threads"),
        )
        self.assertIsNone(
            run_trend_content_mvp._editorial_target({"area": "쇼츠 해시태그"}),
        )

    def test_editorial_revision_prompt_preserves_fact_checking_constraints_and_sources(self):
        prompt = run_trend_content_mvp._build_editorial_revision_prompt(
            {"source_urls": ["https://example.test/official"]},
            {
                "area": "블로그",
                "original": "2026년 지원금은 300만원으로 확정됐습니다.",
                "proposal": "원문을 확인하고 근거가 없으면 표현을 낮추세요.",
            },
            "blog.body",
            "기존 블로그 본문",
        )
        self.assertIn("통계·날짜·법률·정책·금액", prompt)
        self.assertIn("https://example.test/official", prompt)
        self.assertIn("기존 블로그 본문", prompt)
        self.assertIn("unresolved_claims", prompt)

    def test_editorial_revision_parser_rejects_oversized_output(self):
        with self.assertRaisesRegex(ValueError, "40,000자"):
            run_trend_content_mvp._parse_editorial_revision(
                '{"revised_text":"' + ("가" * 40001) + '"}'
            )

    def test_editorial_revision_parser_requires_nonempty_text_and_valid_metadata(self):
        parsed = run_trend_content_mvp._parse_editorial_revision(
            '{"revised_text":"수정된 문장","changes":["문장 간결화"],"unresolved_claims":["금액 원문 확인"]}'
        )
        self.assertEqual(parsed["revised_text"], "수정된 문장")
        self.assertEqual(parsed["unresolved_claims"], ["금액 원문 확인"])
        with self.assertRaisesRegex(ValueError, "비어"):
            run_trend_content_mvp._parse_editorial_revision('{"revised_text":" "}')
        with self.assertRaisesRegex(ValueError, "형식"):
            run_trend_content_mvp._parse_editorial_revision(
                '{"revised_text":"수정","changes":"문자열이어서는 안 됨"}'
            )

    def test_apply_editorial_revision_preserves_before_after_and_rechecks(self):
        preview = {
            "keyword": "테스트 키워드",
            "blog": {"title": "테스트 키워드 제목", "body": "기존 원문입니다. " * 30, "meta_description": "설명"},
            "shorts": [],
            "threads": [],
            "facebook": {},
            "source_urls": ["https://example.test/source"],
            "editorial_revisions": [{
                "revision_id": "revision-1",
                "target": "blog.body",
                "base_text": "기존 원문입니다. " * 30,
                "revised_text": "검토 후 수정한 원문입니다. " * 30,
                "status": "pending_review",
                "changes": ["표현을 명확하게 정리"],
                "unresolved_claims": [],
            }],
        }
        run_trend_content_mvp._apply_editorial_revision(preview, "revision-1", "reviewer")
        self.assertEqual(preview["blog"]["body"], ("검토 후 수정한 원문입니다. " * 30).strip())
        self.assertEqual(preview["editorial_history"][0]["before"], "기존 원문입니다. " * 30)
        self.assertEqual(preview["editorial_history"][0]["after"], preview["blog"]["body"])
        self.assertEqual(preview["editorial_history"][0]["applied_by"], "reviewer")
        self.assertEqual(preview["editorial_revisions"][0]["status"], "applied")
        self.assertIn("quality_report", preview)
        self.assertIn("claim_coverage", preview)

    def test_revert_editorial_revision_restores_original_and_marks_history(self):
        preview = {
            "keyword": "테스트",
            "blog": {"title": "테스트", "body": "수정 적용된 본문 " * 30},
            "shorts": [],
            "threads": [],
            "facebook": {},
            "source_urls": [],
            "editorial_revisions": [{
                "revision_id": "revision-revert",
                "target": "blog.body",
                "base_text": "원래 본문 " * 30,
                "revised_text": "수정 적용된 본문 " * 30,
                "status": "applied",
            }],
            "editorial_history": [{
                "revision_id": "revision-revert",
                "target": "blog.body",
                "before": "원래 본문 " * 30,
                "after": "수정 적용된 본문 " * 30,
            }],
        }
        run_trend_content_mvp._revert_editorial_revision(preview, "revision-revert")
        self.assertEqual(preview["blog"]["body"], "원래 본문 " * 30)
        self.assertTrue(preview["editorial_history"][0]["reverted_at"])
        self.assertEqual(preview["editorial_revisions"][0]["status"], "reverted")

    def test_revert_editorial_revision_rejects_newer_manual_changes(self):
        preview = {
            "blog": {"body": "사람이 다시 수정한 내용"},
            "editorial_history": [{
                "revision_id": "revision-stale-revert",
                "target": "blog.body",
                "before": "기존 내용",
                "after": "AI 수정본",
            }],
        }
        with self.assertRaisesRegex(ValueError, "원문이 다시 변경"):
            run_trend_content_mvp._revert_editorial_revision(preview, "revision-stale-revert")
        self.assertEqual(preview["blog"]["body"], "사람이 다시 수정한 내용")

    def test_apply_editorial_revision_rejects_stale_original_without_mutation(self):
        preview = {
            "blog": {"body": "이미 다른 사람이 변경한 원문"},
            "editorial_revisions": [{
                "revision_id": "revision-stale",
                "target": "blog.body",
                "base_text": "예전 원문",
                "revised_text": "오래된 수정안",
                "status": "pending_review",
            }],
        }
        with self.assertRaisesRegex(ValueError, "원문이 수정본 생성 이후 변경"):
            run_trend_content_mvp._apply_editorial_revision(preview, "revision-stale", "reviewer")
        self.assertEqual(preview["blog"]["body"], "이미 다른 사람이 변경한 원문")
        self.assertEqual(preview["editorial_revisions"][0]["status"], "pending_review")
        self.assertNotIn("editorial_history", preview)

    def test_editorial_recommendations_are_empty_when_all_checks_pass(self):
        proposals = run_trend_content_mvp._build_editorial_recommendations(
            {"warnings": [], "search_intent": {"answer_cue_present": True}},
            {"claims": [{"claim": "근거 URL이 연결된 문장", "citation_attached": True}]},
        )
        self.assertEqual(proposals, [])

    def test_search_intent_diagnostic_classifies_comparison_and_checks_answer_cues(self):
        package = self._valid_package()
        package["blog"]["title"] = "스마트안경 비교와 선택 기준"
        package["blog"]["body"] = (
            "스마트안경의 차이를 비교합니다. 장점과 단점을 확인하고 선택 기준을 정리합니다. "
            + ("제품별 장점과 단점을 비교해 선택 기준을 설명합니다. " * 40)
        )
        report = run_trend_content_mvp._evaluate_content_quality(
            package, "스마트안경 비교", {"audience_question": "스마트안경의 차이는 무엇인가요?"}
        )
        self.assertEqual(report["search_intent"]["type"], "비교형")
        self.assertTrue(report["search_intent"]["answer_cue_present"])
        self.assertIn("차이", report["search_intent"]["answer_cues"])

    def test_search_intent_diagnostic_flags_missing_procedural_answer_cues(self):
        package = self._valid_package()
        package["blog"]["body"] = "이 주제의 배경과 의미를 설명합니다. " * 60
        report = run_trend_content_mvp._evaluate_content_quality(
            package, "신청 방법", {"audience_question": "어떻게 신청하나요?"}
        )
        self.assertEqual(report["search_intent"]["type"], "절차형")
        self.assertFalse(report["search_intent"]["answer_cue_present"])
        self.assertEqual(report["search_intent"]["status"], "검색 의도 답변 보완 필요")

    def test_editorial_quality_check_scores_structure_without_claiming_fact_verification(self):
        package = self._valid_package()
        package["blog"]["title"] = "테스트 키워드 검색과 활용 방법"
        package["blog"]["meta_description"] = "테스트 키워드의 핵심 내용과 확인 방법을 정리한 실전 안내입니다. 지금 필요한 사항을 확인하고 구체적인 적용 순서와 주의사항까지 한 번에 살펴보세요."
        package["blog"]["body"] = (
            "# 테스트 키워드 안내\n\n" + ("테스트 키워드의 핵심 내용을 설명합니다. " * 50)
            + "\n## 첫 번째 확인사항\n\n" + ("구체적인 실행 방법을 설명합니다. " * 30)
            + "\n## 두 번째 확인사항\n\n" + ("주의사항과 적용 방법을 설명합니다. " * 30)
            + "\n## 정리\n\n" + ("마지막 확인 내용을 정리합니다. " * 20)
        )
        package["shorts"]["hook"] = "이 부분을 놓치면 중요한 차이가 생깁니다."
        package["shorts"]["closing_cta"] = "필요한 내용을 저장하고 다시 확인하세요."
        package["shorts"]["scenes"] = [
            {"time": f"00-{i:02d}초", "visual": "중앙 안전영역에 핵심 화면 배치", "caption": "짧은 핵심 자막", "narration": "장면별 설명 내레이션"}
            for i in range(6)
        ]
        package["shorts"]["hashtags"] = ["#테스트", "#정보", "#실전"]
        package["facebook"] = {"title": "Facebook 전용", "body": "Threads와 구분되는 Facebook 전용 문안입니다."}
        report = run_trend_content_mvp._evaluate_content_quality(package, "테스트 키워드")
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["grade"], "양호")
        self.assertIn("사실 정확성", report["scope_note"])
        self.assertEqual(report["warnings"], [])

    def test_editorial_quality_check_uses_audience_question_when_available(self):
        package = self._valid_package()
        package["blog"]["title"] = "초보자 대출 한도 확인 방법"
        package["blog"]["body"] = (
            "# 초보자 대출 한도 확인 방법\n"
            + ("대출 한도는 소득과 기존 부채, 담보가치 등을 확인해야 합니다. " * 35)
            + "\n## 확인 순서\n소득과 부채를 확인합니다.\n"
            + "## 준비 서류\n필요한 서류를 점검합니다.\n"
            + "## 주의사항\n조건별 차이를 확인합니다."
        )
        report = run_trend_content_mvp._evaluate_content_quality(
            package, "대출 한도",
            {"audience_question": "초보자는 대출 한도를 어떻게 확인하나요?"},
        )
        self.assertIn("독자 질문의 핵심어가 제목·본문에 반영", report["passed"])

    def test_editorial_quality_check_flags_weak_hook_pattern(self):
        package = self._valid_package()
        package["shorts"]["hook"] = "오늘은 관련 내용을 설명합니다."
        report = run_trend_content_mvp._evaluate_content_quality(package, "테스트 키워드")
        self.assertIn("질문·문제·대비 등 후킹 장치 포함", report["warnings"])

    def test_editorial_quality_check_flags_missing_structure(self):
        report = run_trend_content_mvp._evaluate_content_quality(
            {"blog": {"title": "짧은 글", "body": "본문"}, "shorts": {}, "threads": [], "facebook": {}},
            "검색 키워드",
        )
        self.assertLess(report["score"], 65)
        self.assertEqual(report["grade"], "수정 필요")
        self.assertTrue(report["warnings"])

    def test_content_package_preserves_facebook_specific_copy(self):
        package = self._valid_package()
        package["facebook"] = {"title": "Facebook 전용 제목", "body": "Facebook 전용 본문"}
        parsed = run_trend_content_mvp._parse_content_package(json.dumps(package, ensure_ascii=False))
        self.assertEqual(parsed["facebook"]["title"], "Facebook 전용 제목")
        self.assertEqual(parsed["facebook"]["body"], "Facebook 전용 본문")

    def test_content_package_falls_back_for_legacy_missing_facebook_copy(self):
        package = self._valid_package()
        parsed = run_trend_content_mvp._parse_content_package(json.dumps(package, ensure_ascii=False))
        self.assertEqual(parsed["facebook"]["title"], "Threads 제목")
        self.assertEqual(parsed["facebook"]["body"], "Threads 본문")

    def test_threads_is_ready_without_a_video_asset(self):
        self.assertEqual(
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "threads"),
            [{"title": "제목", "body": "승인된 Threads 원고"}],
        )

    def test_facebook_queue_uses_facebook_specific_copy(self):
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "facebook",
        )
        self.assertEqual(payload, [{
            "title": "Facebook 제목",
            "body": "Facebook 제목\n\nFacebook 전용 게시문",
        }])

    def test_facebook_queue_falls_back_to_threads_when_legacy_preview_has_no_facebook_copy(self):
        legacy_preview = dict(self.preview)
        legacy_preview.pop("facebook")
        payload = run_trend_content_mvp._queue_payload_for_platform(legacy_preview, "facebook")
        self.assertEqual(payload[0]["body"], "제목\n\n승인된 Threads 원고")

    def test_youtube_queue_uses_uploaded_mp4_path_and_metadata(self):
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "youtube_shorts", self.asset.asset_id,
        )
        self.assertEqual(payload[0]["video_path"], str(self.asset.path))
        self.assertEqual(payload[0]["title"], "쇼츠 제목")
        self.assertEqual(payload[0]["description"], "YouTube 설명")
        self.assertEqual(payload[0]["tags"], ["탁자동", "shorts"])

    def test_instagram_queue_stores_asset_reference_for_runtime_signed_url(self):
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "instagram_reels", self.asset.asset_id,
        )
        self.assertEqual(payload[0]["media_asset_id"], self.asset.asset_id)
        self.assertEqual(payload[0]["caption"], "Instagram 캡션\n\n#탁자동 #shorts")

    def test_video_platforms_require_an_uploaded_media_asset(self):
        for platform in ("youtube_shorts", "instagram_reels", "tiktok"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "미디어 자산"):
                run_trend_content_mvp._queue_payload_for_platform(self.preview, platform, "")

    def test_blog_remains_manual_until_a_blog_publisher_exists(self):
        with self.assertRaisesRegex(ValueError, "수동 게시"):
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "blog")

    def test_tiktok_queue_requires_explicit_privacy_and_uses_registered_video(self):
        with self.assertRaisesRegex(ValueError, "공개 범위"):
            run_trend_content_mvp._queue_payload_for_platform(
                self.preview, "tiktok", self.asset.asset_id,
            )
        payload = run_trend_content_mvp._queue_payload_for_platform(
            self.preview, "tiktok", self.asset.asset_id, "SELF_ONLY", True,
        )
        self.assertEqual(payload[0]["media_asset_id"], self.asset.asset_id)
        self.assertEqual(payload[0]["title"], "TikTok 캡션\n\n#탁자동 #shorts")
        self.assertEqual(payload[0]["privacy_level"], "SELF_ONLY")
        self.assertTrue(payload[0]["is_aigc"])

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            run_trend_content_mvp._queue_payload_for_platform(self.preview, "unknown")


if __name__ == "__main__":
    unittest.main()
