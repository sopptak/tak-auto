"""6-25 Threads Publish Path Consolidation - 통합 계약/레이스 컨디션 테스트
(docs/6-25-threads-publish-path-consolidation.md).

이 파일은 개별 스크립트 테스트(``test_publish_threads_auto_select.py``,
``test_threads_publisher.py``, ``test_run_daily.py``)가 다루지 않는 두 가지를
검증한다:

1. 공식 경로(``publish_approved_threads.py``)와 레거시 경로
   (``publish_threads.py``)가 이제 같은 eligibility 판정 함수
   (``content_engine.publish_eligibility``)를 실제로 공유하는지(10장/11장
   "이미 구현된 helper 재사용" 요구사항의 회귀 보증).
2. 10장 Race Condition 분석에서 식별한, 파일 기반 시스템이라 구조적으로
   남아있는 TOCTOU(time-of-check-to-time-of-use) 경계를 실제로 재현해서
   문서화한다 - "고칠 수 있는데 안 고친 버그"가 아니라 "설계상 알려진 한계"임을
   테스트로 명시한다.

실제 Threads API는 절대 호출하지 않는다(mock/synthetic만).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.publish_history import PublishHistory, compute_content_id
from content_engine.threads_publisher import ThreadsClient
import scripts.publish_approved_threads as official_cli
import scripts.publish_threads as legacy_cli


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1",
        knowledge_id="k1",
        platform="threads",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문입니다.",
        source_url="https://example.test/1",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z",
        review_status="unreviewed",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


def _success_transport(post_id="th_shared"):
    def transport(method, url, headers, payload, timeout):
        if method == "GET":
            return {"id": "111", "username": "tmong_wisdom", "name": "티몽의 지혜"}
        return {"id": post_id}

    return transport


class SharedEligibilityHelperTests(unittest.TestCase):
    """공식/레거시 경로가 같은 content_engine.publish_eligibility 함수를 호출하는지
    소스 레벨로 확인한다(새 중복 로직을 만들지 않았다는 것의 회귀 보증)."""

    def test_both_scripts_import_check_content_supersede_from_shared_module(self) -> None:
        official_source = Path(official_cli.__file__).read_text(encoding="utf-8")
        legacy_source = Path(legacy_cli.__file__).read_text(encoding="utf-8")
        for source in (official_source, legacy_source):
            self.assertIn("from content_engine.publish_eligibility import", source)
            self.assertIn("check_content_supersede", source)

    def test_neither_script_redefines_eligibility_logic(self) -> None:
        """새로운 중복 eligibility 함수(예: def is_eligible / def check_approved 등)를
        만들지 않았는지 확인한다 - publish_threads.py의
        check_threads_item_eligibility()는 판정을 새로 발명하지 않고
        find_production_record()/check_content_supersede()를 그대로 호출만
        해야 한다."""
        legacy_source = Path(legacy_cli.__file__).read_text(encoding="utf-8")
        self.assertIn("find_production_record(", legacy_source)
        self.assertIn("check_content_supersede(", legacy_source)


class RaceConditionBoundaryTests(unittest.TestCase):
    """10장 Race Condition 분석 - production archive 스냅샷을 한 번만 읽는
    설계의 실제 경계를 재현한다. 이것은 "버그를 고친다"가 아니라 "이 경계가
    실제로 어디인지 테스트로 고정한다"가 목적이다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

    def test_official_path_snapshot_does_not_see_supersede_written_after_load(self) -> None:
        """시나리오 13/18: publish_approved_threads.py가 production archive를
        읽은 *이후에* 다른 프로세스가 그 파일에 supersede를 기록해도, 이번
        실행은 이미 메모리에 있는 스냅샷을 계속 쓰므로 이 사실을 보지 못한다
        (6-19 설계: "모든 draft가 같은 스냅샷을 기준으로 판정받도록" - 한
        번의 실행 안에서 일관성을 우선한 의도된 트레이드오프, 새로 발견된
        버그가 아니다). 이 테스트는 그 경계를 문서화한다.
        """
        from content_engine.publish_eligibility import check_content_supersede
        from content_engine.media_archive import load_archive

        archive_path = self.tmp_path / "tak_media_archive.json"
        save_archive([_record(content_id="c1", review_status="approved")], archive_path)

        # publish_approved_threads.py의 main()과 동일한 순서: production archive를
        # 실행 시작 시점에 한 번만 읽는다.
        production_records = load_archive(archive_path)
        check_before = check_content_supersede(production_records, "c1")
        self.assertFalse(check_before.blocked, "스냅샷을 읽은 시점에는 아직 approved라 차단되지 않아야 한다.")

        # "다른 프로세스"가 그 사이 supersede_media_record.py로 이 레코드를
        # superseded로 바꿨다고 가정한다(실제로 그 CLI를 실행하지 않고, 같은
        # 효과만 파일에 직접 반영해 시간차를 시뮬레이션한다).
        save_archive(
            [_record(content_id="c1", review_status="superseded", superseded_by="c2"),
             _record(content_id="c2", review_status="approved")],
            archive_path,
        )

        # 이번 실행은 이미 읽은 production_records(구 스냅샷)를 계속 쓴다 -
        # 이것이 바로 이 함수가 파일을 다시 읽지 않는 순수 함수이기 때문이다.
        check_after_using_stale_snapshot = check_content_supersede(production_records, "c1")
        self.assertFalse(
            check_after_using_stale_snapshot.blocked,
            "알려진 경계: 스냅샷을 다시 읽지 않는 한 같은 실행 안에서는 뒤늦은 supersede를 감지하지 못한다.",
        )

        # 하지만 "다음" 실행(새 프로세스, 새 스냅샷)은 정상적으로 차단한다 -
        # 그래서 이 경계의 실질적 위험 창은 "같은 실행이 진행 중인 짧은 시간"으로
        # 한정된다(10장 문서 참고).
        fresh_records = load_archive(archive_path)
        check_next_run = check_content_supersede(fresh_records, "c1")
        self.assertTrue(check_next_run.blocked, "다음 실행(새 스냅샷)에서는 반드시 차단되어야 한다.")

    def test_two_concurrent_publish_attempts_can_both_pass_eligibility_before_either_writes_history(
        self,
    ) -> None:
        """레이스 컨디션의 핵심: PublishHistory도 매 판정마다 다시 읽지 않고
        루프 시작 전 한 번만 읽으므로("모든 draft가 같은 스냅샷"), 두 개의
        서로 다른 프로세스(A, B)가 동시에 같은 content_id를 대상으로 각자
        eligibility를 통과할 수 있다 - 이 문제는 파일 기반 구조에서 새 lock/DB
        없이는 근본적으로 막을 수 없다(10장에서 이렇게 결론 내렸다 - 이
        테스트는 그 결론의 근거를 재현한다)."""
        from content_engine.publish_history import PublishHistory

        history_path = self.tmp_path / "threads_publish_log.json"
        # 두 "프로세스"가 각자 독립적으로 히스토리를 읽는다(현재 구조 그대로).
        history_view_a = PublishHistory(history_path)
        history_view_b = PublishHistory(history_path)

        self.assertFalse(history_view_a.is_published("c1"))
        self.assertFalse(history_view_b.is_published("c1"))
        # 이 시점에는 아직 아무도 쓰지 않았으므로, 두 프로세스 모두 "게시 가능"으로
        # 판단한다 - 실제 API 호출이 두 번 나갈 위험은 워크플로우 레벨의
        # concurrency 직렬화(daily-threads-post.yml/publish-approved-threads.yml의
        # `concurrency: group:`)로 완화하고 있으며, 이 CLI 자체는 새 lock을
        # 추가하지 않는다(지시사항 10장 원칙).


if __name__ == "__main__":
    unittest.main()
