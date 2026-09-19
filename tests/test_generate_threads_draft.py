"""scripts/generate_threads_draft.py 검증 (5-11 설계 문서 Phase 1).

실제 외부 API(LLM, Threads)는 절대 호출하지 않는다. 유일한 경계는
``OpenAICompatibleRewriteProvider.from_environment``뿐이다(``tests/test_run_daily.py``와
동일한 방법론). ``ThreadsClient``는 애초에 이 스크립트에서 import되지 않으므로
mock할 대상 자체가 없다는 것도 이 파일에서 직접 검증한다.
"""

from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.media_archive import load_archive
from content_engine.publish_history import PublishHistory, PublishRecord
from content_engine.rewrite import MockRewriteProvider
from content_engine.threads_review import load_pending, mark_approved, mark_published, save_pending
from scripts.generate_threads_draft import main


# tests/test_run_daily.py의 픽스처와 동일한 성격(실제 운영 KNOWLEDGE를 복제해 테스트를
# 독립시킴)이나, 이 파일 전용으로 별도 복제본을 둔다(다른 테스트 파일과 값을 공유하지
# 않아 서로 영향 없음).
APPROVED_EXPERIENCE_RECORD = {
    "id": "knowledge-draft-test-1",
    "source_raw_id": "https://blog.example.test/1",
    "source_url": "https://blog.example.test/1?trackingCode=rss",
    "title": "낯선 도구로 첫 결과물을 만든 경험",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "article_type": "experience",
    "experience": "도구를 몰랐던 작성자가 AI로 기획을 정리하고 결과물을 만든 경험이다.",
    "problem": "도구를 전혀 몰라서 처음에는 시작조차 못 할 것 같았다.",
    "action": "AI에게 질문을 반복하며 하나씩 만들어갔다.",
    "decision": "완벽히 배우고 시작하는 대신 만들면서 배우기로 했다.",
    "result": "첫 번째 결과물을 완성하고 비공개 테스트까지 진행했다.",
    "lesson": "완벽하게 알 때까지 기다리지 않고 만들면서 배울 수 있다는 교훈을 얻었다.",
    "reusable_principle": "AI 도구로 기획과 첫 결과물을 만들고 문제마다 질문·수정을 반복한다.",
    "evidence": ["'질문하고 수정하고 또 질문했다.'"],
    "derived_insight": "AI를 작업 파트너로 활용하면 초심자도 결과물을 만들 수 있다는 지식이다.",
    "inference_method": "rule_based_template",
    "confidence": None,
    "created_at": "2026-09-10T10:03:26.653539+00:00",
    "knowledge_review_status": "approved",
    "category": "자기계발",
    "key_points": [],
    "case": "초심자의 도구 활용 사례",
    "judgment_rule": "낯선 영역은 직접 시도하고 검증한다.",
    "opinion": None,
    "factual_information": None,
    "current_validity": "확인 필요",
    "verification_required": True,
    "privacy_risk": False,
    "internal_information_risk": False,
    "reviewed_at": "2026-09-10T10:13:58.556711+00:00",
    "review_note": "테스트 픽스처용 복제본",
}


class GenerateThreadsDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.pending_path = self.tmp_path / "tak_threads_pending.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"

    def _write_knowledge(self, records) -> None:
        self.knowledge_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def _run(self, extra_args=None):
        args = [
            "--knowledge", str(self.knowledge_path),
            "--history", str(self.history_path),
            "--pending", str(self.pending_path),
            "--archive", str(self.archive_path),
        ]
        if extra_args:
            args.extend(extra_args)
        return main(args)

    def _mock_llm(self):
        """run_daily.py 테스트와 동일한 방법: 실제 LLM 호출 없이 MockRewriteProvider(원본
        그대로 반환)로 대체한다."""
        return mock.patch.object(
            OpenAICompatibleRewriteProvider, "from_environment", return_value=MockRewriteProvider()
        )

    # --- 기본 생성: pending 파일에 정확히 저장되는지 -------------------------------

    def test_generates_pending_draft_with_expected_fields(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm():
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        drafts = load_pending(self.pending_path)
        self.assertEqual(len(drafts), 1)

        draft = drafts[0]
        self.assertEqual(draft.status, "pending")
        self.assertEqual(draft.knowledge_id, "knowledge-draft-test-1")
        self.assertEqual(draft.article_type, "experience")
        self.assertEqual(draft.knowledge_type, "경험")
        self.assertTrue(draft.source_url)
        self.assertTrue(draft.evidence_unit_ids)
        self.assertTrue(draft.original_title)
        self.assertTrue(draft.original_body)
        # MockRewriteProvider는 원본을 그대로 반환하므로 ai_rewritten_*는 original_*과 같다.
        self.assertEqual(draft.ai_rewritten_title, draft.original_title)
        self.assertEqual(draft.ai_rewritten_body, draft.original_body)
        self.assertTrue(draft.content_id.startswith("content-"))
        self.assertTrue(draft.created_at)

    def test_final_fields_are_empty_before_approval(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm():
            self._run()

        draft = load_pending(self.pending_path)[0]
        self.assertIsNone(draft.final_title)
        self.assertIsNone(draft.final_body)
        self.assertFalse(draft.edited_by_user)

    # --- PublishHistory/rotation 재사용 검증 ---------------------------------------

    def test_selection_matches_rotation_and_excludes_published_content_id(self):
        """이미 게시(published)된 content_id는 다음 생성에서 다시 선택되지 않고,
        같은 KNOWLEDGE의 다른 valid Threads 후보로 정상 폴백해야 한다(기존
        select_unpublished_threads_item()을 그대로 재사용한다는 증거)."""
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm():
            self.assertEqual(self._run(), 0)
        first_draft = load_pending(self.pending_path)[0]
        first_content_id = first_draft.content_id

        # 첫 draft가 실제로 승인->발행까지 끝난 상황을 시뮬레이션한다(Phase 2가 아직
        # 없으므로 threads_review 헬퍼로 직접 만든다 - Threads API는 호출하지 않는다).
        published_draft = mark_published(
            mark_approved_like(first_draft), threads_post_id="th_test_1", published_at="2026-09-16T01:00:00+00:00"
        )
        save_pending([published_draft], self.pending_path)
        PublishHistory(self.history_path).append(
            PublishRecord(
                content_id=first_content_id,
                published_at="2026-09-16T01:00:00+00:00",
                threads_post_id="th_test_1",
                knowledge_id=first_draft.knowledge_id,
                platform="threads",
                source_url=first_draft.source_url,
            )
        )

        # published만 있고 pending/approved는 없으므로 다시 생성 가능해야 한다.
        with self._mock_llm():
            self.assertEqual(self._run(), 0)

        drafts = load_pending(self.pending_path)
        pending_or_approved = [d for d in drafts if d.status == "pending"]
        self.assertEqual(len(pending_or_approved), 1)
        second_content_id = pending_or_approved[0].content_id

        self.assertNotEqual(second_content_id, first_content_id, "이미 published된 content_id가 재선정되면 안 됩니다.")

    # --- idempotency: 미해결 draft가 있으면 새로 생성하지 않음 ----------------------

    def test_does_not_generate_when_pending_draft_already_exists(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])
        with self._mock_llm():
            self._run()
        drafts_before = load_pending(self.pending_path)

        with self._mock_llm() as mocked_from_env:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_from_env.assert_not_called()  # 미해결 draft가 있으면 LLM조차 호출하지 않아야 함
        self.assertEqual(load_pending(self.pending_path), drafts_before)

    def test_does_not_generate_when_approved_draft_already_exists(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])
        with self._mock_llm():
            self._run()
        draft = load_pending(self.pending_path)[0]
        approved = mark_approved_like(draft)
        save_pending([approved], self.pending_path)

        with self._mock_llm() as mocked_from_env:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_from_env.assert_not_called()
        self.assertEqual(load_pending(self.pending_path), [approved])

    def test_generates_again_when_only_published_draft_exists(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])
        with self._mock_llm():
            self._run()
        draft = load_pending(self.pending_path)[0]
        published = mark_published(mark_approved_like(draft), threads_post_id="th_1", published_at="now")
        save_pending([published], self.pending_path)

        with self._mock_llm() as mocked_from_env:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_from_env.assert_called_once()  # published는 미해결이 아니므로 다시 생성 시도함

    # --- ThreadsClient를 전혀 참조하지 않는지 --------------------------------------

    def test_module_never_imports_or_calls_threads_client(self):
        """설명 docstring(주석)에서 "ThreadsClient를 import하지 않는다"고 언급하는 것과는
        별개로, 실제 import 구문/모듈 객체 수준에서 이 사실을 검증한다."""
        import scripts.generate_threads_draft as module

        self.assertFalse(hasattr(module, "ThreadsClient"))
        self.assertNotIn("content_engine.threads_publisher", getattr(module, "__dict__", {}))

        source = Path("scripts/generate_threads_draft.py").read_text(encoding="utf-8")
        import_lines = [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]
        self.assertFalse(
            any("ThreadsClient" in line or "threads_publisher" in line for line in import_lines),
            "import 구문에 ThreadsClient/threads_publisher가 있으면 안 됩니다.",
        )
        self.assertNotIn("publish_text(", source)

    # --- 그 외 기본 동작(run_daily.py와 동일한 안전장치) ----------------------------

    def test_no_approved_knowledge_exits_zero_without_writing_pending(self):
        self._write_knowledge([{**APPROVED_EXPERIENCE_RECORD, "knowledge_review_status": "pending"}])

        with self._mock_llm() as mocked_from_env:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_from_env.assert_not_called()
        self.assertEqual(load_pending(self.pending_path), [])

    def test_missing_knowledge_file_exits_one(self):
        self.assertEqual(self._run(), 1)

    # --- E. rotation에서 선택되지 않은 나머지 draft도 archive에는 남는지 (5-27) -----

    def test_archive_keeps_drafts_not_selected_by_rotation(self):
        """이 스크립트는 TAK MEDIA가 만든 9개 Draft 중 rotation으로 고른 1개만
        tak_threads_pending.json에 넘긴다(설계상 정상 동작). 나머지 8개(다른 Threads
        후보 4개, Blog 1개, Shorts 3개)가 통째로 사라지지 않고 아카이브에는 전부
        남아있어야 한다는 5-27 설계 문서의 요구사항을 검증한다."""
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm():
            exit_code = self._run()

        self.assertEqual(exit_code, 0)

        pending = load_pending(self.pending_path)
        self.assertEqual(len(pending), 1, "rotation은 여전히 1건만 pending으로 승격해야 합니다.")

        archived = load_archive(self.archive_path)
        self.assertEqual(len(archived), 9, "나머지 8건도 아카이브에는 전부 남아있어야 합니다.")

        platforms = [record.platform for record in archived]
        self.assertEqual(platforms.count("blog"), 1)
        self.assertEqual(platforms.count("shorts"), 3)
        self.assertEqual(platforms.count("threads"), 5)
        self.assertTrue(all(record.knowledge_id == APPROVED_EXPERIENCE_RECORD["id"] for record in archived))

        # rotation으로 선택되어 pending으로 승격된 항목도 당연히 아카이브 안에 포함되어야 한다.
        archived_content_ids = {record.content_id for record in archived}
        self.assertIn(pending[0].content_id, archived_content_ids)


def mark_approved_like(draft):
    """이 테스트 파일 전용 헬퍼: Phase 2(발행 스크립트)가 아직 없으므로, "승인됨"
    상태를 흉내내기 위해 threads_review.mark_approved를 그대로 사용한다."""
    return mark_approved(
        draft,
        final_title=draft.ai_rewritten_title,
        final_body=draft.ai_rewritten_body,
        approved_at="2026-09-16T00:30:00+00:00",
    )


if __name__ == "__main__":
    unittest.main()
