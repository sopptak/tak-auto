"""6-17 SUPERSEDED 생명주기 테스트(docs/6-17_superseded_lifecycle_design.md).

전부 synthetic fixture 또는 tempfile만 사용한다 - 실제 production archive/
knowledge/threads pending 파일은 어떤 테스트도 경로조차 참조하지 않는다
(tests/test_critical_content_replacement_audit.py와 동일한 관례).

이 파일이 고정하는 것:
    1. review_status에 "superseded"가 추가되고, superseded_by/review_status가
       항상 함께 있어야 한다는 정합성 규칙(MediaArchiveRecord.__post_init__).
    2. 기존(6-16 이전) 레코드가 superseded_by 필드 없이도 KeyError 없이
       파싱된다는 backward compatibility.
    3. scripts/supersede_media_record.py의 plan_supersede()가 CASE 1~10
       (docs 9장)을 정확히 검증하고, 조건 미충족 시 옛 레코드를 절대
       건드리지 않는다는 것.
    4. supersede 후 audit_archive()가 옛 레코드를 SUPERSEDED로, 새 레코드를
       정상 후보(READY 또는 NEEDS_HUMAN_REVIEW)로 분류한다는 것.
    5. downstream artifact(예: publish history)가 supersede로 전혀 사라지지
       않는다는 것.
    6. 두 번 연속 supersede(체인)도 안전하게 동작한다는 것.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import (
    MediaArchiveRecord,
    MediaArchiveError,
    REVIEW_STATUS_TRANSITIONS,
    REVIEW_STATUSES,
    load_archive,
    upsert_archive,
)
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    READY,
    SUPERSEDED,
    PublishAuditInputs,
    audit_archive,
)
from content_engine.publish_history import PublishHistory, PublishRecord
from scripts.supersede_media_record import (
    SupersedeError,
    execute_supersede,
    plan_supersede,
)
from tak_brain import KnowledgeRecord


def _record(**overrides) -> MediaArchiveRecord:
    base = dict(
        content_id="content-old0000001",
        knowledge_id="knowledge-shared",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="옛 재작성 제목(오염됨)",
        rewritten_body="옛 재작성 본문(오염됨)",
        source_url="https://example.test/shared-article",
        evidence=("SOURCE FACT: 예시",),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-20T00:00:00+00:00",
    )
    base.update(overrides)
    return MediaArchiveRecord(**base)


class _TempFileMixin(unittest.TestCase):
    def _tmp_json_path(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        path = Path(tmp.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path


# --- 1. 데이터 모델 정합성 ----------------------------------------------------


class SupersededStatusRecognizedTests(unittest.TestCase):
    def test_superseded_is_a_valid_review_status(self):
        self.assertIn("superseded", REVIEW_STATUSES)

    def test_superseded_only_reachable_from_approved(self):
        for status, allowed in REVIEW_STATUS_TRANSITIONS.items():
            if status != "approved":
                self.assertNotIn(
                    "superseded",
                    allowed,
                    f"{status} -> superseded는 허용되지 않아야 한다(approved에서만 가능).",
                )
        self.assertIn("superseded", REVIEW_STATUS_TRANSITIONS["approved"])

    def test_superseded_is_terminal_no_outgoing_transitions(self):
        self.assertEqual(REVIEW_STATUS_TRANSITIONS["superseded"], frozenset())

    def test_superseded_without_superseded_by_is_rejected(self):
        with self.assertRaises(MediaArchiveError):
            _record(review_status="superseded", superseded_by=None)

    def test_superseded_by_without_superseded_status_is_rejected(self):
        with self.assertRaises(MediaArchiveError):
            _record(review_status="approved", superseded_by="content-new0000002")

    def test_superseded_by_cannot_point_to_self(self):
        with self.assertRaises(MediaArchiveError):
            _record(
                content_id="content-x",
                review_status="superseded",
                superseded_by="content-x",
            )

    def test_valid_superseded_record_constructs(self):
        record = _record(review_status="superseded", superseded_by="content-new0000002")
        self.assertEqual(record.review_status, "superseded")
        self.assertEqual(record.superseded_by, "content-new0000002")


class LegacyRecordCompatibilityTests(unittest.TestCase):
    def test_record_without_superseded_by_key_parses_with_default_none(self):
        legacy_dict = {
            "content_id": "content-legacy0001",
            "knowledge_id": "knowledge-legacy",
            "platform": "blog",
            "generation_status": "valid",
            "original_title": "t",
            "original_body": "b",
            "rewritten_title": "r",
            "rewritten_body": "rb",
            "source_url": "https://example.test/legacy",
            "evidence": [],
            "evidence_unit_ids": [],
            "created_at": "2026-01-01T00:00:00",
            "review_status": "approved",
            # superseded_by 키 자체가 없음 - 6-16 이전 레코드/6-06 이전
            # generation_id 부재 레코드와 동일한 상황.
        }
        record = MediaArchiveRecord.from_dict(legacy_dict)
        self.assertIsNone(record.superseded_by)
        self.assertEqual(record.review_status, "approved")

    def test_roundtrip_preserves_superseded_fields(self):
        record = _record(review_status="superseded", superseded_by="content-new0000002")
        restored = MediaArchiveRecord.from_dict(record.to_dict())
        self.assertEqual(restored, record)


# --- 2. plan_supersede() CASE 1~10 검증 --------------------------------------


class PlanSupersedeHappyPathTests(_TempFileMixin):
    def setUp(self) -> None:
        self.path = self._tmp_json_path()
        self.old = _record(content_id="content-old0000001", review_status="approved")
        self.new = _record(
            content_id="content-new0000002",
            review_status="approved",
            rewritten_title="새 재작성 제목(오염 제거됨)",
            rewritten_body="새 재작성 본문(오염 제거됨)",
        )
        upsert_archive(self.path, [self.old, self.new])

    def test_case3_approved_new_candidate_supersedes_old(self):
        plan = plan_supersede(self.path, "content-old0000001", "content-new0000002")
        self.assertEqual(plan.updated_old_record.review_status, "superseded")
        self.assertEqual(plan.updated_old_record.superseded_by, "content-new0000002")
        # plan_supersede()는 파일을 쓰지 않는다.
        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(records["content-old0000001"].review_status, "approved")

    def test_execute_writes_only_the_old_record(self):
        plan = plan_supersede(self.path, "content-old0000001", "content-new0000002")
        execute_supersede(self.path, plan)

        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(len(records), 2, "레코드가 삭제되면 안 된다 - 이력 보존.")
        self.assertEqual(records["content-old0000001"].review_status, "superseded")
        self.assertEqual(records["content-old0000001"].superseded_by, "content-new0000002")
        self.assertEqual(records["content-new0000002"].review_status, "approved")
        # 옛 레코드의 다른 필드는 전혀 바뀌지 않는다.
        self.assertEqual(records["content-old0000001"].rewritten_title, "옛 재작성 제목(오염됨)")
        self.assertEqual(records["content-old0000001"].created_at, self.old.created_at)
        self.assertEqual(records["content-old0000001"].knowledge_id, self.old.knowledge_id)

    def test_chained_supersede_is_supported(self):
        """A가 B로, B가 다시 C로 대체되는 연쇄도 안전하게 동작해야 한다."""
        plan1 = plan_supersede(self.path, "content-old0000001", "content-new0000002")
        execute_supersede(self.path, plan1)

        second_new = _record(
            content_id="content-newer0003",
            review_status="approved",
            rewritten_title="세 번째 교정",
        )
        upsert_archive(self.path, [second_new])

        plan2 = plan_supersede(self.path, "content-new0000002", "content-newer0003")
        execute_supersede(self.path, plan2)

        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(records["content-old0000001"].review_status, "superseded")
        self.assertEqual(records["content-old0000001"].superseded_by, "content-new0000002")
        self.assertEqual(records["content-new0000002"].review_status, "superseded")
        self.assertEqual(records["content-new0000002"].superseded_by, "content-newer0003")
        self.assertEqual(records["content-newer0003"].review_status, "approved")


class PlanSupersedeRejectionTests(_TempFileMixin):
    """CASE 1, 2, 4, 5, 6 + platform/source_url 정책(CASE 7)."""

    def setUp(self) -> None:
        self.path = self._tmp_json_path()
        self.old = _record(content_id="content-old0000001", review_status="approved")
        upsert_archive(self.path, [self.old])

    def test_case5_missing_old_content_id_rejected(self):
        new = _record(content_id="content-new0000002", review_status="approved")
        upsert_archive(self.path, [new])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-does-not-exist", "content-new0000002")
        # old 레코드는 손대지 않았다(애초에 old_content_id가 잘못됐으므로 old
        # 자체가 존재하지 않는 시나리오지만, 기존 old0000001도 그대로 남아있다).
        self.assertEqual(load_archive(self.path)[0].review_status, "approved")

    def test_missing_new_content_id_rejected(self):
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-does-not-exist")
        self.assertEqual(load_archive(self.path)[0].review_status, "approved", "old는 변경되지 않아야 한다.")

    def test_case1_invalid_new_candidate_rejected_old_stays_approved(self):
        new = _record(content_id="content-new0000002", review_status="unreviewed", generation_status="rejected")
        upsert_archive(self.path, [new])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-new0000002")
        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(records["content-old0000001"].review_status, "approved")

    def test_case2_unreviewed_new_candidate_rejected_old_stays_approved(self):
        new = _record(content_id="content-new0000002", review_status="unreviewed", generation_status="valid")
        upsert_archive(self.path, [new])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-new0000002")
        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(records["content-old0000001"].review_status, "approved")

    def test_case4_new_content_id_same_as_old_rejected(self):
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-old0000001")

    def test_case6_knowledge_id_mismatch_rejected(self):
        new = _record(
            content_id="content-new0000002",
            knowledge_id="knowledge-DIFFERENT",
            review_status="approved",
        )
        upsert_archive(self.path, [new])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-new0000002")
        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(records["content-old0000001"].review_status, "approved")

    def test_platform_mismatch_rejected(self):
        new = _record(content_id="content-new0000002", platform="shorts", review_status="approved")
        upsert_archive(self.path, [new])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-new0000002")

    def test_case7_source_url_mismatch_rejected_by_policy(self):
        """정책: source_url이 다르면 '정정'이 아니라 별개 콘텐츠로 간주해 거부한다
        (docs/6-17_superseded_lifecycle_design.md 10장 CASE 7 정책 결정)."""
        new = _record(
            content_id="content-new0000002",
            source_url="https://example.test/a-completely-different-article",
            review_status="approved",
        )
        upsert_archive(self.path, [new])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-new0000002")
        records = {r.content_id: r for r in load_archive(self.path)}
        self.assertEqual(records["content-old0000001"].review_status, "approved")

    def test_old_not_approved_rejected(self):
        path = self._tmp_json_path()
        old_unreviewed = _record(content_id="content-old0000001", review_status="unreviewed")
        new = _record(content_id="content-new0000002", review_status="approved")
        upsert_archive(path, [old_unreviewed, new])
        with self.assertRaises(SupersedeError):
            plan_supersede(path, "content-old0000001", "content-new0000002")

    def test_already_superseded_old_cannot_be_superseded_again(self):
        new1 = _record(content_id="content-new0000002", review_status="approved")
        upsert_archive(self.path, [new1])
        plan1 = plan_supersede(self.path, "content-old0000001", "content-new0000002")
        execute_supersede(self.path, plan1)

        new2 = _record(content_id="content-newer0003", review_status="approved")
        upsert_archive(self.path, [new2])
        with self.assertRaises(SupersedeError):
            plan_supersede(self.path, "content-old0000001", "content-newer0003")


# --- 3. Publish Readiness 연동 -------------------------------------------------


class PublishReadinessExcludesSupersededTests(_TempFileMixin):
    def _inputs(self, knowledge_by_id=None) -> PublishAuditInputs:
        return PublishAuditInputs(
            knowledge_by_id=knowledge_by_id or {},
            blog_history=PublishHistory(self._tmp_json_path()),
            threads_history=PublishHistory(self._tmp_json_path()),
            threads_pending=(),
            youtube_history=None,
            shorts_scripts_path=None,
            shorts_dir_path=None,
        )

    def test_superseded_record_is_excluded_from_active_candidates(self):
        old = _record(
            content_id="content-old0000001",
            review_status="superseded",
            superseded_by="content-new0000002",
        )
        new = _record(content_id="content-new0000002", review_status="approved")
        knowledge = KnowledgeRecord(
            id="knowledge-shared",
            source_raw_id="raw-1",
            source_url=old.source_url,
            title="공유 지식",
            category="기타",
            domain="기타",
            knowledge_type="의견",
        )
        results = {
            r.content_id: r
            for r in audit_archive([old, new], inputs=self._inputs({"knowledge-shared": knowledge}))
        }
        self.assertEqual(results["content-old0000001"].status, SUPERSEDED)
        self.assertEqual(results["content-new0000002"].status, READY)

    def test_already_published_takes_precedence_over_superseded(self):
        """이미 게시된 적 있는 옛 레코드가 나중에 superseded되면, 여전히
        ALREADY_PUBLISHED로 분류돼야 한다 - 회수 필요 여부를 판단할 정보를
        SUPERSEDED 표시가 가려버리면 안 된다(docs/6-17 8장)."""
        old = _record(
            content_id="content-old0000001",
            platform="blog",
            review_status="superseded",
            superseded_by="content-new0000002",
        )
        blog_history_path = self._tmp_json_path()
        PublishHistory(blog_history_path).append(
            PublishRecord(
                content_id="content-old0000001",
                published_at="2026-09-20T00:00:00+00:00",
                threads_post_id="",
                knowledge_id=old.knowledge_id,
                platform="blog",
                source_url=old.source_url,
            )
        )
        inputs = PublishAuditInputs(
            knowledge_by_id={},
            blog_history=PublishHistory(blog_history_path),
            threads_history=PublishHistory(self._tmp_json_path()),
            threads_pending=(),
            youtube_history=None,
            shorts_scripts_path=None,
            shorts_dir_path=None,
        )
        result = audit_archive([old], inputs=inputs)[0]
        self.assertEqual(result.status, ALREADY_PUBLISHED)


# --- 4. Downstream artifact/이력 보존 -----------------------------------------


class DownstreamArtifactNotDeletedTests(_TempFileMixin):
    def test_supersede_does_not_touch_publish_history_file(self):
        """supersede는 production archive 파일 하나만 갱신한다 - publish
        history/threads pending 등 다른 저장소 파일은 열지도 않는다."""
        production_path = self._tmp_json_path()
        old = _record(content_id="content-old0000001", review_status="approved")
        new = _record(content_id="content-new0000002", review_status="approved")
        upsert_archive(production_path, [old, new])

        blog_history_path = self._tmp_json_path()
        PublishHistory(blog_history_path).append(
            PublishRecord(
                content_id="content-old0000001",
                published_at="2026-09-19T00:00:00+00:00",
                threads_post_id="",
                knowledge_id=old.knowledge_id,
                platform="blog",
                source_url=old.source_url,
            )
        )
        before_mtime = blog_history_path.stat().st_mtime_ns
        before_bytes = blog_history_path.read_bytes()

        plan = plan_supersede(production_path, "content-old0000001", "content-new0000002")
        execute_supersede(production_path, plan)

        self.assertEqual(blog_history_path.read_bytes(), before_bytes, "publish history 파일이 바뀌면 안 된다.")
        self.assertEqual(blog_history_path.stat().st_mtime_ns, before_mtime)
        # 그리고 supersede 이후에도 게시 이력 자체는 그대로 조회 가능해야 한다.
        self.assertTrue(PublishHistory(blog_history_path).is_published("content-old0000001"))


if __name__ == "__main__":
    unittest.main()
