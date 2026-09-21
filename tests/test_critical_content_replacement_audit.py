"""6-16 회귀 테스트: 이미 승인된 Production Archive 레코드를 안전하게 정정하는
절차를 검증한다(docs/6-16_critical_content_replacement_audit.md).

배경: `content-5971ed5204437cdd`(blog, `knowledge-scout-b28b782b2a33`,
review_status="approved")는 6-04에서 지적된 finance 템플릿 오염을 담고 있고,
6-05가 article_type 정정 후 실제 LLM으로 재생성한 교정본
`content-afc6060bc1957867`(review_status="unreviewed", generation_id 없음)가
`data/tak_media_archive_6-05_b28b782b2a33_regeneration.json`에 존재한다. 이
파일이 다루는 범위는 "그 교정본을 production archive에 실제로 반영하기 전에,
기존 코드가 이 상황을 안전하게 처리하는지"이며, 전부 합성 fixture 또는
tmp_path에서만 검증한다 - 실제 production archive/knowledge/threads pending
파일은 어떤 테스트도 열어서 쓰지 않는다(읽기조차 하지 않는다 - 6-06/6-14
계열 테스트와 달리 이 파일은 실제 파일 경로를 아예 참조하지 않는다).

이미 tests/test_media_versioning_and_promotion.py(6-06)와
tests/test_media_dashboard.py가 다루는 내용(같은 content_id의 generation
이력 보존, dry-run이 파일을 안 바꾸는지, "approved 콘텐츠는 Dashboard
화면에서 edit/dismiss 버튼 자체가 없다")은 여기서 다시 만들지 않는다. 이
파일이 새로 다루는 것은 그 두 사실을 조합했을 때 드러나는, 지금까지 테스트로
고정된 적 없는 세 가지 구조적 사실이다:

    1. 정정본이 원본과 다른 content_id를 받으면(6-05/6-06에서 실제로 9건 중
       2건이 그랬다), promotion은 기존 승인 레코드를 "교체"하지 않고 그
       옆에 "추가"할 뿐이다 - 두 레코드가 production archive에 동시에
       존재하게 된다.
    2. 그렇게 남은 "옛 승인 레코드"는 review_status가 이미 "approved"이므로,
       Dashboard의 기존 안전장치(_can_review_media_record) 때문에 edit/
       dismiss 양쪽 다 코드 레벨에서 거부된다 - 즉 현재 코드에는 "이 레코드는
       새 버전으로 대체됐다"고 표시할 방법이 아예 없다.
    3. content_id가 같은 채로 다른 아카이브 파일에 upsert하면(6-05가 실제로
       우회했던 바로 그 위험) 이전 rewritten_title/body가 조용히 사라진다 -
       이 위험이 실제로 재현됨을 합성 데이터로 고정해, 향후 누군가 generation
       pool 없이 직접 upsert_archive()로 "교체"를 구현하지 못하게 막는다.
    4. promote_media_generation.py는 publish 이력을 전혀 참조하지 않는다 -
       "이미 게시된 content_id"의 승격을 막는 장치가 이 스크립트에는 없고,
       그 판단은 전적으로 그 다음 단계인 scripts/audit_publish_candidates.py
       (content_id 단위로만 게시 이력을 대조)에 맡겨져 있다. content_id가
       바뀌는 정정에서는 이 대조가 "새 content_id는 옛 content_id의 게시
       이력과 무관하다"는 사각지대를 만든다는 것을 합성 데이터로 보여준다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from content_engine.media_archive import (
    MediaArchiveRecord,
    load_archive,
    upsert_archive,
    upsert_generation_archive,
)
from content_engine.publish_audit import (
    ALREADY_PUBLISHED,
    READY,
    PublishAuditInputs,
    audit_archive,
)
from content_engine.publish_history import PublishHistory, PublishRecord, compute_content_id
from scripts.promote_media_generation import PromotionError, plan_promotion
from scripts.run_scout_dashboard import (
    handle_media_dismiss_submission,
    handle_media_edit_submission,
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


class ApprovedRecordReplacementIsAdditiveTests(_TempFileMixin):
    """1. content_id가 바뀌는 정정 promotion은 옛 승인 레코드를 지우지도,
    바꾸지도 않는다 - 둘 다 남는다."""

    def setUp(self) -> None:
        self.production_path = self._tmp_json_path()
        self.pool_path = self._tmp_json_path()

        self.old_approved = _record(content_id="content-old0000001", review_status="approved")
        upsert_archive(self.production_path, [self.old_approved])

        self.corrected_candidate = _record(
            content_id="content-new0000002",  # 정정 후 템플릿이 바뀌어 content_id도 바뀐 경우(6-05 9건 중 2건과 동일한 상황)
            generation_id="gen-6-16-test",
            review_status="approved",
            rewritten_title="새 재작성 제목(오염 제거됨)",
            rewritten_body="새 재작성 본문(오염 제거됨)",
        )
        upsert_generation_archive(self.pool_path, [self.corrected_candidate])

    def test_promotion_adds_new_record_without_touching_old_one(self):
        candidate, current_active = plan_promotion(
            self.pool_path, self.production_path, "content-new0000002", "gen-6-16-test"
        )
        self.assertIsNone(current_active)  # 새 content_id이므로 "기존 활성 레코드 없음"으로 보고된다

        upsert_archive(self.production_path, [candidate])

        records = {r.content_id: r for r in load_archive(self.production_path)}
        self.assertEqual(len(records), 2, "정정 promotion은 레코드를 교체가 아니라 추가한다.")
        self.assertIn("content-old0000001", records)
        self.assertIn("content-new0000002", records)

        old_after = records["content-old0000001"]
        self.assertEqual(old_after.review_status, "approved")
        self.assertEqual(old_after.rewritten_title, "옛 재작성 제목(오염됨)")
        self.assertEqual(old_after, self.old_approved, "옛 레코드는 promotion으로 단 한 글자도 바뀌면 안 된다.")

    def test_same_knowledge_id_now_has_two_approved_active_records(self):
        """정정 후 production archive에는 같은 knowledge_id로부터 나온 "approved"
        레코드가 2건(옛 오염본 + 새 교정본) 동시에 존재하게 된다 - 이 상태
        자체를 감지/정리하는 코드는 현재 없다(사람이 결정해야 함, report 17장)."""
        candidate, _ = plan_promotion(
            self.pool_path, self.production_path, "content-new0000002", "gen-6-16-test"
        )
        upsert_archive(self.production_path, [candidate])

        approved_for_knowledge = [
            r
            for r in load_archive(self.production_path)
            if r.knowledge_id == "knowledge-shared" and r.review_status == "approved"
        ]
        self.assertEqual(len(approved_for_knowledge), 2)


class ApprovedRecordCannotBeSupersededInPlaceTests(_TempFileMixin):
    """2. 옛 승인 레코드가 새 버전으로 대체됐다는 사실을 이 레코드 자체에 표시할
    방법이 없다 - edit/dismiss 둘 다 approved 레코드에는 거부된다(기존
    _can_review_media_record 안전장치, 5-29/5-30). 이 테스트는 그 안전장치가
    "정정 시나리오"에서도 그대로 적용됨을 고정한다."""

    def setUp(self) -> None:
        self.production_path = self._tmp_json_path()
        self.old_approved = _record(content_id="content-old0000001", review_status="approved")
        upsert_archive(self.production_path, [self.old_approved])

    def test_dismiss_is_rejected_for_approved_record(self):
        updated, error = handle_media_dismiss_submission(self.production_path, "content-old0000001")
        self.assertIsNone(updated)
        self.assertEqual(error, "이미 승인된 콘텐츠는 보류할 수 없습니다.")
        record = load_archive(self.production_path)[0]
        self.assertEqual(record.review_status, "approved")

    def test_edit_is_rejected_for_approved_record(self):
        updated, error = handle_media_edit_submission(
            self.production_path, "content-old0000001", "새 제목", "새 본문"
        )
        self.assertIsNone(updated)
        self.assertEqual(error, "이미 승인된 콘텐츠는 수정할 수 없습니다.")
        record = load_archive(self.production_path)[0]
        self.assertIsNone(record.edited_title)

    def test_no_supersede_or_unapprove_route_exists(self):
        """이 파일이 import하는 run_scout_dashboard 모듈에 approved 레코드를
        "superseded"/"unapproved"로 표시하는 핸들러가 없음을 코드로 고정한다 -
        이런 함수가 향후 추가되면 이 테스트가 실패해 report 갱신을 유도한다."""
        import scripts.run_scout_dashboard as dashboard

        handler_names = [name for name in dir(dashboard) if name.startswith("handle_media_")]
        self.assertEqual(
            sorted(handler_names),
            ["handle_media_approve_submission", "handle_media_dismiss_submission", "handle_media_edit_submission"],
            "handle_media_* 핸들러 목록이 바뀌었다 - superseded/unapprove 경로가 새로 생겼다면 "
            "report 6~9장(A/B/C 방법 비교)을 다시 검토해야 한다.",
        )


class ContentIdCollisionSilentOverwriteRiskTests(_TempFileMixin):
    """3. 같은 content_id를 production archive에 직접 upsert하면 이전
    rewritten_* 텍스트가 조용히 사라진다(6-05/6-06이 우회했던 바로 그 위험).
    generation pool(복합 키)을 쓰지 않고 실수로 production archive 파일에
    직접 재작성 결과를 upsert하면 무슨 일이 벌어지는지 합성 데이터로 고정한다."""

    def test_upserting_same_content_id_into_production_archive_loses_old_text(self):
        production_path = self._tmp_json_path()
        old = _record(
            content_id="content-collide0001",
            review_status="approved",
            rewritten_title="승인된 옛 텍스트",
        )
        upsert_archive(production_path, [old])

        # article_type 정정 후 재생성했지만 원본 템플릿 제목 슬롯이 바뀌지
        # 않아 content_id가 우연히 같아진 새 결과(6-05 9건 중 7건이 이 상황).
        regenerated_same_id = _record(
            content_id="content-collide0001",
            review_status="unreviewed",
            rewritten_title="정정 후 새 텍스트",
        )
        upsert_archive(production_path, [regenerated_same_id])

        records = load_archive(production_path)
        self.assertEqual(len(records), 1, "content_id가 같으므로 upsert_archive()는 한 건으로 합친다.")
        self.assertEqual(records[0].rewritten_title, "정정 후 새 텍스트")
        self.assertNotEqual(
            records[0].rewritten_title,
            "승인된 옛 텍스트",
            "옛 승인 텍스트가 review_status 갱신 없이 조용히 사라졌다 - "
            "이래서 6-05/6-06은 generation pool(복합 키 파일)을 별도로 도입했다.",
        )
        # review_status는 upsert_archive() 규칙상 보존되지 않는다(그 보존은
        # archive_report()/archive_generation_report()가 prior 조회로 직접 하는
        # 일이다 - upsert_archive() 자체는 review_status를 그대로 덮어쓴다).
        self.assertEqual(
            records[0].review_status,
            "unreviewed",
            "upsert_archive()를 직접 쓰면 review_status(사람의 승인 여부)까지 "
            "덮어써진다 - 반드시 archive_report()/archive_generation_report() "
            "경유해야 하는 이유.",
        )


class ContentIdIdentityGuaranteesTests(unittest.TestCase):
    """content_id는 knowledge_id/platform/source_url/evidence_unit_ids/
    original_title/original_body의 해시다 - 이 중 하나라도 다르면 다른
    content_id가 나와야 한다(그래야 "content_id가 같다"는 것이 곧 "knowledge_id/
    source가 같다"는 것을 보장한다 - promotion이 knowledge_id/source_url을
    별도로 검증하지 않아도 안전한 이유)."""

    def _item(self, **overrides) -> dict:
        base = dict(
            knowledge_id="knowledge-a",
            platform="blog",
            source_url="https://example.test/a",
            evidence_unit_ids=["lesson:1"],
            original_title="제목",
            original_body="본문",
        )
        base.update(overrides)
        return base

    def test_same_inputs_produce_same_content_id(self):
        self.assertEqual(compute_content_id(self._item()), compute_content_id(self._item()))

    def test_different_knowledge_id_produces_different_content_id(self):
        self.assertNotEqual(
            compute_content_id(self._item()),
            compute_content_id(self._item(knowledge_id="knowledge-b")),
        )

    def test_different_source_url_produces_different_content_id(self):
        self.assertNotEqual(
            compute_content_id(self._item()),
            compute_content_id(self._item(source_url="https://example.test/b")),
        )


class PromotionIgnoresPublishHistoryGapTests(_TempFileMixin):
    """4. promote_media_generation.py는 publish 이력을 import조차 하지 않는다.
    "이미 게시된 콘텐츠의 승격을 막는" 판단은 전적으로 그 다음 단계인
    scripts/audit_publish_candidates.py(content_engine.publish_audit)에
    맡겨져 있는데, 그 audit은 content_id 단위로만 게시 이력을 대조한다.
    즉 정정으로 content_id가 바뀌면(1번 테스트와 동일 상황), "이 knowledge의
    콘텐츠가 이미 다른 content_id로 게시됐다"는 사실을 아무도 자동으로
    잡아주지 않는다 - 이 사각지대를 합성 데이터로 고정해 문서화한다(고치지
    않는다 - report 12장·17장에서 사람의 정책 결정 사항으로 남긴다)."""

    def test_new_content_id_is_not_flagged_already_published_even_though_sibling_id_was(self):
        knowledge_id = "knowledge-shared"
        source_url = "https://example.test/shared-article"

        old_published = _record(
            content_id="content-old0000001",
            knowledge_id=knowledge_id,
            source_url=source_url,
            review_status="approved",
        )
        new_corrected = _record(
            content_id="content-new0000002",
            knowledge_id=knowledge_id,
            source_url=source_url,
            review_status="approved",
            rewritten_title="새 재작성 제목(오염 제거됨)",
        )

        blog_history_path = self._tmp_json_path()
        PublishHistory(blog_history_path).append(
            PublishRecord(
                content_id="content-old0000001",
                published_at="2026-09-20T00:00:00+00:00",
                threads_post_id="",
                knowledge_id=knowledge_id,
                platform="blog",
                source_url=source_url,
            )
        )

        knowledge = KnowledgeRecord(
            id=knowledge_id,
            source_raw_id="raw-1",
            source_url=source_url,
            title="공유 지식",
            category="기타",
            domain="기타",
            knowledge_type="의견",
        )

        inputs = PublishAuditInputs(
            knowledge_by_id={knowledge_id: knowledge},
            blog_history=PublishHistory(blog_history_path),
            threads_history=PublishHistory(self._tmp_json_path()),
            threads_pending=(),
            youtube_history=None,
            shorts_scripts_path=None,
            shorts_dir_path=None,
        )

        results = {r.content_id: r for r in audit_archive([old_published, new_corrected], inputs=inputs)}

        self.assertEqual(results["content-old0000001"].status, ALREADY_PUBLISHED)
        self.assertEqual(
            results["content-new0000002"].status,
            READY,
            "content_id가 바뀐 정정본은 옛 content_id의 게시 이력과 대조되지 않아 "
            "READY로 분류된다 - 실제로 게시하기 전에 '같은 knowledge_id/source_url이 "
            "이미 게시됐는지'를 사람이 별도로 확인해야 한다는 뜻이다(자동 감지 없음).",
        )


if __name__ == "__main__":
    unittest.main()
