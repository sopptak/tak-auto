"""content_engine.publish_eligibility 검증(6-19,
docs/6-19-superseded-downstream-safeguards.md).

이 모듈은 순수 판정 로직만 테스트한다 - 파일 I/O는 이 테스트가 직접 만든
synthetic MediaArchiveRecord 목록으로만 수행하고, 실제 production archive
파일(data/tak_media_archive.json)은 어떤 테스트도 경로조차 참조하지 않는다.
"""

from __future__ import annotations

import unittest

from content_engine.media_archive import MediaArchiveRecord
from content_engine.publish_eligibility import (
    check_content_supersede,
    check_supersede_block,
    find_production_record,
    format_block_message,
)


def _record(**overrides) -> MediaArchiveRecord:
    base = dict(
        content_id="content-eligibility-1",
        knowledge_id="knowledge-eligibility-1",
        platform="threads",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문",
        source_url="https://example.test/article",
        evidence=("SOURCE FACT: 예시",),
        evidence_unit_ids=("lesson:1",),
        created_at="2026-09-19T00:00:00+00:00",
    )
    base.update(overrides)
    return MediaArchiveRecord(**base)


class FindProductionRecordTests(unittest.TestCase):
    def test_finds_matching_content_id(self):
        record = _record(content_id="content-a")
        other = _record(content_id="content-b")
        found = find_production_record([other, record], "content-a")
        self.assertIs(found, record)

    def test_returns_none_when_not_found(self):
        self.assertIsNone(find_production_record([_record(content_id="content-a")], "content-missing"))

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(find_production_record([], "content-a"))


class CheckSupersedeBlockTests(unittest.TestCase):
    def test_missing_record_is_not_blocked(self):
        """ORPHAN(Production Archive에 레코드 없음)은 이 모듈의 책임이 아니다 -
        차단하지 않고 호출부의 기존 ORPHAN 정책에 맡긴다."""
        check = check_supersede_block(None)
        self.assertFalse(check.blocked)
        self.assertIsNone(check.reason)
        self.assertIsNone(check.superseded_by)

    def test_approved_record_is_not_blocked(self):
        check = check_supersede_block(_record(review_status="approved"))
        self.assertFalse(check.blocked)

    def test_unreviewed_record_is_not_blocked(self):
        check = check_supersede_block(_record(review_status="unreviewed"))
        self.assertFalse(check.blocked)

    def test_dismissed_record_is_not_blocked(self):
        check = check_supersede_block(_record(review_status="dismissed"))
        self.assertFalse(check.blocked)

    def test_superseded_record_is_blocked(self):
        record = _record(review_status="superseded", superseded_by="content-new-1")
        check = check_supersede_block(record)
        self.assertTrue(check.blocked)
        self.assertEqual(check.superseded_by, "content-new-1")
        self.assertIn("content-new-1", check.reason)
        self.assertIn("superseded", check.reason)


class CheckContentSupersedeTests(unittest.TestCase):
    def test_looks_up_and_blocks_in_one_call(self):
        old = _record(content_id="content-old", review_status="superseded", superseded_by="content-new")
        new = _record(content_id="content-new", review_status="approved")
        records = [old, new]

        self.assertTrue(check_content_supersede(records, "content-old").blocked)
        self.assertFalse(check_content_supersede(records, "content-new").blocked)
        self.assertFalse(check_content_supersede(records, "content-does-not-exist").blocked)


class FormatBlockMessageTests(unittest.TestCase):
    def test_message_includes_key_fields_for_grep(self):
        record = _record(content_id="content-msg-1", review_status="superseded", superseded_by="content-msg-2")
        check = check_supersede_block(record)
        message = format_block_message("content-msg-1", check)
        self.assertIn("content_id=content-msg-1", message)
        self.assertIn("status=SUPERSEDED", message)
        self.assertIn("superseded_by=content-msg-2", message)
        self.assertIn("result=BLOCKED", message)
        self.assertIn("reason=", message)


if __name__ == "__main__":
    unittest.main()
