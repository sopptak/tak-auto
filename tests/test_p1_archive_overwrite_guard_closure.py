"""6-29 P1 Closure - docs/6-28-full-e2e-operating-readiness.md 21장 P1 #1
(archive_report() 조용한 재작성 문제)의 나머지 두 호출부
(scripts/generate_threads_draft.py, scripts/tak_auto.py)에 6-24 P0와 동일한
가드(content_engine.media_archive.find_protected_overwrite_targets())를
적용한 것을 검증한다.

기존 6-24(tests/test_production_readiness_audit_fixes.py)가 이미
find_protected_overwrite_targets() 자체의 판정 로직(approved/superseded
차단, unreviewed/dismissed 허용, 신규 content_id 허용)을 전담 검증하므로
여기서는 그 로직을 다시 테스트하지 않는다 - 이 파일은 "그 함수가 이
두 호출부에서 실제로, 쓰기 전에, 올바른 순서로 호출되는가"만 검증한다.

실제 LLM/RSS 네트워크는 호출하지 않는다(OpenAICompatibleRewriteProvider.from_environment,
tak_scout.collector.fetch_rss만 mock으로 대체). 실제 data/는 어디에서도
참조하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.media_archive import load_archive, save_archive
from content_engine.rewrite import MockRewriteProvider
from scripts.generate_threads_draft import main as generate_threads_draft_main


APPROVED_KNOWLEDGE = {
    "id": "knowledge-p1-closure-1",
    "source_raw_id": "https://blog.example.test/p1-closure",
    "source_url": "https://blog.example.test/p1-closure?trackingCode=rss",
    "title": "6-29 P1 closure 테스트용 KNOWLEDGE",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "article_type": "experience",
    "experience": "P1 closure 테스트를 위한 경험 서술입니다. 충분한 길이를 갖도록 작성합니다.",
    "problem": "P1 closure 테스트를 위한 문제 상황 서술입니다.",
    "action": "P1 closure 테스트를 위한 행동 서술입니다.",
    "decision": "P1 closure 테스트를 위한 판단 서술입니다.",
    "result": "P1 closure 테스트를 위한 결과 서술입니다.",
    "lesson": "P1 closure 테스트를 위한 교훈 서술입니다.",
    "reusable_principle": "P1 closure 테스트를 위한 재사용 가능한 원칙 서술입니다.",
    "evidence": ["P1 closure 테스트 근거 문장"],
    "derived_insight": "P1 closure 테스트를 위한 도출된 통찰입니다.",
    "inference_method": "rule_based_template",
    "confidence": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "knowledge_review_status": "approved",
    "category": "자기계발",
    "key_points": [],
    "case": "P1 closure 테스트 사례",
    "judgment_rule": "P1 closure 테스트 판단 규칙",
    "opinion": None,
    "factual_information": None,
    "current_validity": "확인 필요",
    "verification_required": True,
    "privacy_risk": False,
    "internal_information_risk": False,
    "reviewed_at": "2026-01-01T00:10:00+00:00",
    "review_note": "6-29 P1 closure 테스트 픽스처",
}


def _mock_llm():
    return mock.patch.object(
        OpenAICompatibleRewriteProvider, "from_environment", return_value=MockRewriteProvider()
    )


class GenerateThreadsDraftOverwriteGuardTests(unittest.TestCase):
    """CASE A/B/D/E(원본 지시 6장)를 scripts/generate_threads_draft.py의
    실제 CLI 진입점(main())을 통해 검증한다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(json.dumps([APPROVED_KNOWLEDGE], ensure_ascii=False), encoding="utf-8")
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"

    def _run(self, pending_path: Path) -> int:
        with _mock_llm():
            return generate_threads_draft_main(
                [
                    "--knowledge", str(self.knowledge_path),
                    "--history", str(self.history_path),
                    "--pending", str(pending_path),
                    "--archive", str(self.archive_path),
                ]
            )

    def test_case_a_approved_existing_content_blocks_rewrite(self) -> None:
        first_pending = self.tmp_path / "pending_1.json"
        exit_code = self._run(first_pending)
        self.assertEqual(exit_code, 0)
        records = load_archive(self.archive_path)
        self.assertTrue(records)

        approved_records = [replace(r, review_status="approved") for r in records]
        save_archive(approved_records, self.archive_path)
        before_bytes = self.archive_path.read_bytes()

        # has_unresolved_draft()가 1차 실행에서 만든 pending draft 때문에 조기
        # 종료되지 않도록, 2차 실행은 새 --pending 경로를 쓴다(archive 가드는
        # pending 상태와 무관하게 독립적으로 동작해야 한다).
        second_pending = self.tmp_path / "pending_2.json"
        exit_code_again = self._run(second_pending)

        self.assertEqual(exit_code_again, 1)
        self.assertEqual(self.archive_path.read_bytes(), before_bytes, "차단됐는데도 archive 파일이 바뀌었습니다.")
        self.assertFalse(second_pending.exists(), "차단된 실행이 pending draft를 만들면 안 됩니다.")

    def test_case_b_superseded_existing_content_blocks_rewrite(self) -> None:
        first_pending = self.tmp_path / "pending_1.json"
        self._run(first_pending)
        records = load_archive(self.archive_path)

        superseded_records = [
            replace(r, review_status="superseded", superseded_by="content-placeholder") for r in records
        ]
        save_archive(superseded_records, self.archive_path)
        before_bytes = self.archive_path.read_bytes()

        second_pending = self.tmp_path / "pending_2.json"
        exit_code_again = self._run(second_pending)

        self.assertEqual(exit_code_again, 1)
        self.assertEqual(self.archive_path.read_bytes(), before_bytes)

    def test_case_d_unreviewed_existing_content_is_not_blocked(self) -> None:
        """비교군: unreviewed/dismissed는 여전히 정상적으로 재작성 허용(기존 동작 보존)."""
        first_pending = self.tmp_path / "pending_1.json"
        exit_code = self._run(first_pending)
        self.assertEqual(exit_code, 0)
        records = load_archive(self.archive_path)
        self.assertTrue(all(r.review_status == "unreviewed" for r in records))

        second_pending = self.tmp_path / "pending_2.json"
        exit_code_again = self._run(second_pending)
        self.assertEqual(exit_code_again, 0)

    def test_dry_run_style_no_pending_created_on_block(self) -> None:
        """시나리오 9(원본 지시): write 전에 차단되므로 부수효과(pending 생성)도 없어야 한다."""
        first_pending = self.tmp_path / "pending_1.json"
        self._run(first_pending)
        records = load_archive(self.archive_path)
        save_archive([replace(r, review_status="approved") for r in records], self.archive_path)

        second_pending = self.tmp_path / "pending_2.json"
        self._run(second_pending)
        self.assertFalse(second_pending.exists())


class TakAutoOverwriteGuardWiringTests(unittest.TestCase):
    """scripts/tak_auto.run_operator()가 실제 SCOUT->INTERVIEW->KNOWLEDGE->
    MEDIA 경로를 전부 거친 뒤 find_protected_overwrite_targets()를 호출해
    archive_report() 이전에 차단하는지 확인한다.

    run_operator()는 매 실행마다 새 interview 응답으로 새 KNOWLEDGE를
    만드는 구조라(재사용 방지를 위한 source_raw_id/scout_id dedup이 있음),
    "완전히 동일한 content_id 충돌"을 실제 4단계 CLI 흐름만으로 결정적으로
    재현하려면 timestamp 등 비결정적 요소까지 통제해야 한다 - 대신 이
    테스트는 (1) 실제 흐름이 만든 진짜 report를 (2) 이미 approved로 표시된
    진짜 archive와 대조했을 때 (3) find_protected_overwrite_targets()가
    실제로 호출되고 그 결과가 archive_report() 실행 여부를 실제로 좌우하는지
    스파이(spy)로 확인한다 - 이것도 존재 여부가 아니라 "실제 호출 경로"를
    검증하는 것이다(호출 순서/인자/반환값 사용 여부까지 실제 코드로 확인).
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def _run_full_operator_flow(self, media_archive_path: Path, spy_targets: list | None = None):
        from tak_scout.collector import build_daily_pack, save_daily_pack_json
        from scripts.tak_auto import run_operator

        feed_xml = """<rss version="2.0"><channel>
<item>
  <title>P1 closure 검증용 기사</title>
  <link>https://example.test/p1-closure-article</link>
  <description>이 기사는 6-29 P1 closure 가드 배선을 검증하기 위한 synthetic fixture입니다.</description>
  <pubDate>Thu, 10 Sep 2026 09:00:00 +0900</pubDate>
</item>
</channel></rss>"""
        sources = [{"name": "P1 closure 테스트 소스", "url": "https://example.test/rss.xml", "category": "self_growth"}]
        with mock.patch("tak_scout.collector.fetch_rss", return_value=feed_xml):
            candidates, _ = build_daily_pack(sources, max_count=10)
        daily_pack_path = self.tmp_path / "tak_scout_daily.json"
        save_daily_pack_json(candidates, daily_pack_path)

        answers_path = self.tmp_path / "answers.json"
        knowledge_path = self.tmp_path / "knowledge.json"
        media_output_path = self.tmp_path / "media_batch.json"

        answer_iter = iter(["1", "D", "P1 closure 검증을 위한 커스텀 의견입니다", "Y"])
        input_func = lambda _prompt: next(answer_iter)  # noqa: E731

        printed: list[str] = []
        with _mock_llm():
            exit_code = run_operator(
                daily_pack_path=daily_pack_path,
                answers_path=answers_path,
                knowledge_path=knowledge_path,
                media_output_path=media_output_path,
                media_archive_path=media_archive_path,
                execute=False,
                input_func=input_func,
                print_func=printed.append,
            )
        return exit_code, printed

    def test_normal_flow_reaches_archive_report_when_nothing_protected(self) -> None:
        """대조군: 아무것도 approved/superseded가 아니면(전부 신규) archive_report가
        실제로 호출되어 archive가 정상적으로 생성된다 - 가드가 정상 흐름을
        막지 않는지 확인한다."""
        media_archive_path = self.tmp_path / "tak_media_archive.json"
        exit_code, printed = self._run_full_operator_flow(media_archive_path)

        self.assertEqual(exit_code, 0)
        self.assertTrue(media_archive_path.exists())
        records = load_archive(media_archive_path)
        self.assertEqual(len(records), 9)  # Blog1 + Shorts3 + Threads5

    def test_protected_content_blocks_before_archive_report_is_called(self) -> None:
        """CASE A/B(원본 지시 6장)를 tak_auto.py의 실제 run_operator() 호출
        경로 안에서 확인한다: find_protected_overwrite_targets()가 True를
        반환하도록(이미 approved인 것과 겹친다고 가정) 강제했을 때,
        archive_report()가 호출되지 않고 exit code가 1이며 archive 파일이
        전혀 쓰여지지 않는지 확인한다 - 이 테스트는 "가드 함수가 코드에
        존재한다"가 아니라 "그 함수의 반환값이 실제로 쓰기 여부를
        좌우한다"를 검증한다."""
        media_archive_path = self.tmp_path / "tak_media_archive.json"

        with mock.patch(
            "scripts.tak_auto.find_protected_overwrite_targets", return_value=["content-forced-conflict"]
        ) as mocked_guard, mock.patch("scripts.tak_auto.archive_report") as mocked_archive_report:
            exit_code, printed = self._run_full_operator_flow(media_archive_path)

        mocked_guard.assert_called_once()
        mocked_archive_report.assert_not_called()
        self.assertEqual(exit_code, 1)
        self.assertFalse(media_archive_path.exists(), "차단됐는데도 archive 파일이 생성되면 안 됩니다.")
        self.assertIn("content-forced-conflict", "\n".join(printed))

    def test_guard_receives_the_same_report_that_would_have_been_archived(self) -> None:
        """find_protected_overwrite_targets()가 실제 report(방금 생성된 9개
        draft)와 실제 archive 상태(load_archive 결과)를 인자로 받는지 확인한다
        - 엉뚱한 인자로 호출되면 판정 자체가 무의미해지므로 인자 타입/구조를
        확인한다."""
        media_archive_path = self.tmp_path / "tak_media_archive.json"

        with mock.patch(
            "scripts.tak_auto.find_protected_overwrite_targets", return_value=[]
        ) as mocked_guard:
            exit_code, _printed = self._run_full_operator_flow(media_archive_path)

        self.assertEqual(exit_code, 0)
        mocked_guard.assert_called_once()
        (report_arg, existing_records_arg), _kwargs = mocked_guard.call_args
        self.assertEqual(len(report_arg.items), 9)
        self.assertEqual(existing_records_arg, [])  # 최초 실행이라 archive가 비어 있었음


if __name__ == "__main__":
    unittest.main()
