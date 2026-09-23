"""6-24 Production Readiness 감사에서 발견한 P0 문제의 회귀 테스트
(docs/6-24-production-readiness-audit.md 4장).

발견된 문제: ``scripts/run_media_batch.py --execute``(``--as-generation`` 없이,
문서화된 기본 동작)와 ``scripts/run_daily.py``는 둘 다
``content_engine.media_archive.archive_report()``를 호출하는데, 이 함수는
``review_status``는 보존하지만 ``rewritten_title``/``rewritten_body``는 항상
최신 LLM 출력으로 덮어쓴다. 그 결과 이미 ``approved``(또는 ``superseded``)인
content_id를 같은 KNOWLEDGE로 재실행하면, 승인 상태는 그대로 "approved"로
보이면서 실제 문구만 사람이 다시 보지 못한 채 바뀔 수 있었다.

수정: ``content_engine.media_archive.find_protected_overwrite_targets()``(신규
순수 함수)를 두 CLI가 쓰기 직전에 호출해, approved/superseded content_id가
하나라도 있으면 즉시 중단한다(``archive_report()`` 자체의 동작은 바꾸지 않음 -
KNOWLEDGE 정정 후 재생성처럼 content_id가 바뀌는 정당한 재실행은 계속 허용).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

from content_engine.media_archive import (
    MediaArchiveRecord,
    find_protected_overwrite_targets,
    load_archive,
    save_archive,
)
from content_engine.llm_provider import OpenAICompatibleRewriteProvider
from content_engine.pipeline import MediaBatchItem, MediaBatchReport
from content_engine.rewrite import MockRewriteProvider

import scripts.run_media_batch as run_media_batch_cli
import scripts.run_daily as run_daily_cli


# --- 순수 함수 단위 테스트 -----------------------------------------------------


def _item(content_id_seed: str, **overrides) -> MediaBatchItem:
    defaults = dict(
        knowledge_id="k1",
        platform="shorts",
        status="valid",
        original_title=f"제목-{content_id_seed}",
        original_body=f"본문-{content_id_seed}",
        rewritten_title=f"재작성 제목-{content_id_seed}",
        rewritten_body=f"재작성 본문-{content_id_seed}",
        source_url=f"https://example.test/{content_id_seed}",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z",
        rejection_reasons=(),
        error_message=None,
    )
    defaults.update(overrides)
    return MediaBatchItem(**defaults)


def _report(*items: MediaBatchItem) -> MediaBatchReport:
    return MediaBatchReport(
        total_knowledge_count=1,
        approved_knowledge_count=1,
        skipped_knowledge_count=0,
        total_draft_count=len(items),
        valid_count=len(items),
        rejected_count=0,
        error_count=0,
        items=tuple(items),
    )


def _record_from(item: MediaBatchItem, **overrides) -> MediaArchiveRecord:
    from content_engine.publish_history import compute_content_id

    defaults = dict(
        content_id=compute_content_id(item.to_dict()),
        knowledge_id=item.knowledge_id,
        platform=item.platform,
        generation_status=item.status,
        original_title=item.original_title,
        original_body=item.original_body,
        rewritten_title=item.rewritten_title,
        rewritten_body=item.rewritten_body,
        source_url=item.source_url,
        evidence=item.evidence,
        evidence_unit_ids=item.evidence_unit_ids,
        created_at=item.created_at,
        review_status="unreviewed",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class FindProtectedOverwriteTargetsTests(unittest.TestCase):
    def test_approved_prior_is_protected(self) -> None:
        item = _item("a")
        prior = _record_from(item, review_status="approved")
        report = _report(item)
        protected = find_protected_overwrite_targets(report, [prior])
        self.assertEqual(protected, [prior.content_id])

    def test_superseded_prior_is_protected(self) -> None:
        item = _item("b")
        other = _record_from(_item("other"), content_id="other-target", review_status="approved")
        prior = _record_from(item, review_status="superseded", superseded_by="other-target")
        report = _report(item)
        protected = find_protected_overwrite_targets(report, [prior, other])
        self.assertEqual(protected, [prior.content_id])

    def test_unreviewed_prior_is_not_protected(self) -> None:
        item = _item("c")
        prior = _record_from(item, review_status="unreviewed")
        report = _report(item)
        protected = find_protected_overwrite_targets(report, [prior])
        self.assertEqual(protected, [])

    def test_dismissed_prior_is_not_protected(self) -> None:
        item = _item("d")
        prior = _record_from(item, review_status="dismissed")
        report = _report(item)
        protected = find_protected_overwrite_targets(report, [prior])
        self.assertEqual(protected, [])

    def test_brand_new_content_id_is_not_protected(self) -> None:
        item = _item("e")
        report = _report(item)
        protected = find_protected_overwrite_targets(report, [])
        self.assertEqual(protected, [])

    def test_only_matching_content_ids_are_reported(self) -> None:
        approved_item = _item("f")
        untouched_item = _item("g")
        prior_approved = _record_from(approved_item, review_status="approved")
        prior_unrelated = _record_from(_item("h"), review_status="approved")
        report = _report(approved_item, untouched_item)
        protected = find_protected_overwrite_targets(report, [prior_approved, prior_unrelated])
        self.assertEqual(protected, [approved_item_content_id := prior_approved.content_id])
        self.assertNotIn(prior_unrelated.content_id, protected)


# --- CLI 통합 테스트 -----------------------------------------------------------

APPROVED_KNOWLEDGE = {
    "id": "knowledge-p0-test",
    "source_raw_id": "https://example.test/p0-source",
    "source_url": "https://example.test/p0-source",
    "title": "P0 회귀 테스트용 KNOWLEDGE",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "experience": "테스트 목적으로 작성된 경험 서술입니다. 충분한 길이를 갖도록 여러 문장을 포함합니다.",
    "problem": "테스트를 위한 문제 상황 서술입니다.",
    "action": "테스트를 위한 행동 서술입니다.",
    "decision": "테스트를 위한 판단 서술입니다.",
    "result": "테스트를 위한 결과 서술입니다.",
    "lesson": "테스트를 위한 교훈 서술입니다.",
    "reusable_principle": "테스트를 위한 재사용 가능한 원칙 서술입니다.",
    "evidence": ["테스트 근거 문장 1", "테스트 근거 문장 2"],
    "derived_insight": "테스트를 위한 도출된 통찰입니다.",
    "inference_method": "rule_based_template",
    "confidence": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "knowledge_review_status": "approved",
    "category": "자기계발",
    "key_points": [],
    "case": "테스트 사례",
    "judgment_rule": "테스트 판단 규칙",
    "opinion": None,
    "factual_information": None,
    "current_validity": "확인 필요",
    "verification_required": True,
    "privacy_risk": False,
    "internal_information_risk": False,
    "reviewed_at": "2026-01-01T00:10:00+00:00",
    "review_note": "P0 회귀 테스트 픽스처",
}


class RunMediaBatchCliGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.knowledge_path.write_text(json.dumps([APPROVED_KNOWLEDGE], ensure_ascii=False), encoding="utf-8")

    def _mock_llm(self):
        return mock.patch.object(
            OpenAICompatibleRewriteProvider, "from_environment", return_value=MockRewriteProvider()
        )

    def _run(self, extra_args=None):
        args = ["--input", str(self.knowledge_path), "--archive", str(self.archive_path), "--execute"]
        if extra_args:
            args.extend(extra_args)
        with self._mock_llm():
            return run_media_batch_cli.main(args)

    def test_first_run_succeeds_and_writes_unreviewed_records(self) -> None:
        exit_code = self._run()
        self.assertEqual(exit_code, 0)
        records = load_archive(self.archive_path)
        self.assertTrue(records)
        self.assertTrue(all(r.review_status == "unreviewed" for r in records))

    def test_rerun_after_approval_is_blocked_and_archive_untouched(self) -> None:
        self._run()
        records = load_archive(self.archive_path)
        approved_records = [replace(r, review_status="approved") for r in records]
        save_archive(approved_records, self.archive_path)
        before_bytes = self.archive_path.read_bytes()

        exit_code = self._run()

        self.assertEqual(exit_code, 1)
        self.assertEqual(self.archive_path.read_bytes(), before_bytes, "차단됐는데도 archive 파일이 바뀌었습니다.")

    def test_rerun_after_dismissal_is_not_blocked(self) -> None:
        self._run()
        records = load_archive(self.archive_path)
        dismissed_records = [replace(r, review_status="dismissed") for r in records]
        save_archive(dismissed_records, self.archive_path)

        exit_code = self._run()
        self.assertEqual(exit_code, 0)

    def test_as_generation_mode_is_unaffected_by_guard(self) -> None:
        """--as-generation 경로는 애초에 production archive를 건드리지 않으므로
        이 가드 대상이 아니다(항상 통과)."""
        gen_pool_path = self.tmp_path / "tak_media_generation_x.json"
        with self._mock_llm():
            exit_code = run_media_batch_cli.main(
                [
                    "--input", str(self.knowledge_path),
                    "--archive", str(gen_pool_path),
                    "--execute",
                    "--as-generation",
                ]
            )
        self.assertEqual(exit_code, 0)
        with self._mock_llm():
            exit_code_again = run_media_batch_cli.main(
                [
                    "--input", str(self.knowledge_path),
                    "--archive", str(gen_pool_path),
                    "--execute",
                    "--as-generation",
                ]
            )
        self.assertEqual(exit_code_again, 0)


class RunDailyCliGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.output_path = self.tmp_path / "batch.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.knowledge_path.write_text(json.dumps([APPROVED_KNOWLEDGE], ensure_ascii=False), encoding="utf-8")

    def _mock_llm(self):
        return mock.patch.object(
            OpenAICompatibleRewriteProvider, "from_environment", return_value=MockRewriteProvider()
        )

    def _run(self):
        args = [
            "--knowledge", str(self.knowledge_path),
            "--output", str(self.output_path),
            "--history", str(self.history_path),
            "--archive", str(self.archive_path),
            "--dry-run",  # Threads 게시 자체는 이 P0 테스트의 관심사가 아니다
        ]
        with self._mock_llm():
            return run_daily_cli.main(args)

    def test_rerun_after_approval_is_blocked_before_archiving(self) -> None:
        first_exit = self._run()
        self.assertEqual(first_exit, 0)
        records = load_archive(self.archive_path)
        self.assertTrue(records)
        approved_records = [replace(r, review_status="approved") for r in records]
        save_archive(approved_records, self.archive_path)
        before_bytes = self.archive_path.read_bytes()

        second_exit = self._run()

        self.assertEqual(second_exit, 1)
        self.assertEqual(self.archive_path.read_bytes(), before_bytes)


if __name__ == "__main__":
    unittest.main()
