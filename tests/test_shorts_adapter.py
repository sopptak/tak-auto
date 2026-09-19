"""content_engine.shorts_adapter.short_draft_to_shorts_script 검증(5-19).

ShortDraft(title + 단일 body 문자열) -> ShortsScript(title/subtitle/cards/
takeaway/brand) 구조 변환만 검증한다. 렌더러(ShortsScript/shorts_renderer)
로직 자체는 이미 tests/test_shorts_script.py, tests/test_shorts_renderer.py가
검증하므로 여기서는 다시 검증하지 않는다.
"""

from __future__ import annotations

import unittest

from content_engine.media_archive import MediaArchiveRecord
from content_engine.models import ShortDraft
from content_engine.shorts_adapter import (
    ShortsAdapterError,
    approved_media_archive_record_to_shorts_script,
    short_draft_to_shorts_script,
)
from content_engine.shorts_script import MAX_CARDS, DEFAULT_BRAND


def _draft(body: str, title: str = "좋은 사람이 만만한 사람이 되지 않으려면") -> ShortDraft:
    return ShortDraft(
        title=title,
        body=body,
        source_url="https://example.test/article",
        evidence=("SOURCE FACT: 예시",),
        evidence_unit_ids=("unit-1",),
    )


class SingleParagraphTests(unittest.TestCase):
    def test_single_paragraph_is_reused_as_card_and_takeaway(self):
        draft = _draft("무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다.")
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.cards, ("무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다.",))
        self.assertEqual(script.takeaway, "무조건 잘해주는 것과 좋은 사람이 되는 것은 다릅니다.")

    def test_single_paragraph_does_not_invent_new_text(self):
        """takeaway는 원문 문단 그대로여야 한다 - 새 문장을 만들지 않는다."""
        body = "이 문단 하나가 전부입니다."
        draft = _draft(body)
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.cards[0], body)
        self.assertEqual(script.takeaway, body)


class MultiParagraphTests(unittest.TestCase):
    def test_three_paragraphs_last_becomes_takeaway(self):
        draft = _draft("첫 문단입니다.\n\n둘째 문단입니다.\n\n마지막 문단입니다.")
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.cards, ("첫 문단입니다.", "둘째 문단입니다."))
        self.assertEqual(script.takeaway, "마지막 문단입니다.")

    def test_five_paragraphs(self):
        paragraphs = [f"문단 {i}입니다." for i in range(1, 6)]
        draft = _draft("\n\n".join(paragraphs))
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.cards, tuple(paragraphs[:-1]))
        self.assertEqual(script.takeaway, paragraphs[-1])

    def test_title_is_used_as_is(self):
        draft = _draft("첫 문단.\n\n둘째 문단.", title="원본 제목 그대로")
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.title, "원본 제목 그대로")

    def test_subtitle_defaults_to_empty_string(self):
        """ShortDraft에는 subtitle에 대응하는 필드가 없다 - 없는 내용을 지어내지 않는다."""
        draft = _draft("첫 문단.\n\n둘째 문단.")
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.subtitle, "")

    def test_default_brand_is_tmong_wisdom(self):
        draft = _draft("첫 문단.\n\n둘째 문단.")
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(script.brand, DEFAULT_BRAND)

    def test_custom_brand_is_respected(self):
        draft = _draft("첫 문단.\n\n둘째 문단.")
        script = short_draft_to_shorts_script(draft, brand="커스텀 브랜드")
        self.assertEqual(script.brand, "커스텀 브랜드")


class CardLimitBoundaryTests(unittest.TestCase):
    def test_eight_paragraphs_succeeds(self):
        paragraphs = [f"문단 {i}." for i in range(1, 9)]  # 8개 -> cards 7개
        draft = _draft("\n\n".join(paragraphs))
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(len(script.cards), 7)
        self.assertEqual(script.takeaway, paragraphs[-1])

    def test_nine_paragraphs_hits_exact_card_limit_and_succeeds(self):
        paragraphs = [f"문단 {i}." for i in range(1, 10)]  # 9개 -> cards 8개 = MAX_CARDS
        draft = _draft("\n\n".join(paragraphs))
        script = short_draft_to_shorts_script(draft)
        self.assertEqual(len(script.cards), MAX_CARDS)
        self.assertEqual(script.takeaway, paragraphs[-1])

    def test_ten_paragraphs_exceeds_card_limit_and_raises(self):
        paragraphs = [f"문단 {i}." for i in range(1, 11)]  # 10개 -> cards 9개 > MAX_CARDS
        draft = _draft("\n\n".join(paragraphs))
        with self.assertRaises(ShortsAdapterError):
            short_draft_to_shorts_script(draft)

    def test_error_does_not_silently_drop_paragraphs(self):
        """카드 초과 시 일부를 임의로 잘라내지 않고 명시적으로 실패해야 한다."""
        paragraphs = [f"문단 {i}." for i in range(1, 11)]
        draft = _draft("\n\n".join(paragraphs))
        with self.assertRaises(ShortsAdapterError) as ctx:
            short_draft_to_shorts_script(draft)
        self.assertIn("최대", str(ctx.exception))


class EmptyBodyTests(unittest.TestCase):
    def test_empty_body_raises(self):
        draft = _draft("")
        with self.assertRaises(ShortsAdapterError):
            short_draft_to_shorts_script(draft)

    def test_whitespace_only_body_raises(self):
        draft = _draft("   \n\n   ")
        with self.assertRaises(ShortsAdapterError):
            short_draft_to_shorts_script(draft)


def _archive_record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-shorts-test-1",
        "knowledge_id": "knowledge-shorts-1",
        "platform": "shorts",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 문단 1\n\n원본 문단 2",
        "rewritten_title": "AI 생성 제목",
        "rewritten_body": "AI 생성 문단 1\n\nAI 생성 문단 2",
        "source_url": "https://example.test/article",
        "evidence": ("SOURCE FACT: 예시",),
        "evidence_unit_ids": ("unit-1",),
        "created_at": "2026-09-19T00:00:00+00:00",
        "validation_errors": (),
        "error_message": None,
        "review_status": "approved",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


class ApprovedMediaArchiveRecordConversionTests(unittest.TestCase):
    """content_engine.media_archive.MediaArchiveRecord -> ShortsScript 연결(5-29)."""

    def test_approved_record_converts_using_generated_content_when_not_edited(self):
        record = _archive_record()

        script = approved_media_archive_record_to_shorts_script(record)

        self.assertEqual(script.title, "AI 생성 제목")
        self.assertEqual(script.cards, ("AI 생성 문단 1",))
        self.assertEqual(script.takeaway, "AI 생성 문단 2")

    def test_approved_record_uses_edited_content_when_present(self):
        record = _archive_record(edited_title="사람이 고친 제목", edited_body="사람이 고친 문단")

        script = approved_media_archive_record_to_shorts_script(record)

        self.assertEqual(script.title, "사람이 고친 제목")
        self.assertEqual(script.cards, ("사람이 고친 문단",))
        self.assertEqual(script.takeaway, "사람이 고친 문단")

    def test_non_shorts_platform_raises(self):
        record = _archive_record(platform="blog")
        with self.assertRaises(ShortsAdapterError):
            approved_media_archive_record_to_shorts_script(record)

    def test_non_valid_generation_status_raises(self):
        record = _archive_record(generation_status="rejected", review_status="unreviewed")
        with self.assertRaises(ShortsAdapterError):
            approved_media_archive_record_to_shorts_script(record)

    def test_not_yet_approved_raises(self):
        record = _archive_record(review_status="unreviewed")
        with self.assertRaises(ShortsAdapterError):
            approved_media_archive_record_to_shorts_script(record)


if __name__ == "__main__":
    unittest.main()
