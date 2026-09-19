"""tak_scout.title_translation(5-20) 단위 테스트.

한국어 표시용 제목 번역 "캐시" 데이터 계층만 검증한다. LLM 호출은
tak_scout.interview_llm.InterviewLLMProvider.translate_titles()가 하며,
tests/test_interview_llm.py에서 별도로 검증한다(이 파일 범위 밖).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tak_scout.title_translation import (
    TitleTranslation,
    TitleTranslationError,
    load_translations,
    save_translations,
    translations_by_scout_id,
    upsert_translation,
)


def _translation(
    scout_id: str = "scout-abc123",
    source_title: str = "We simply don't know - JP Morgan struggling to forecast oil prices due to Trump's war with Iran",
    display_title: str = "정말 알 수 없다 — JP모건, 이란 전쟁으로 유가 전망에 어려움",
    translated_at: str = "2026-09-19T06:00:00+00:00",
) -> TitleTranslation:
    return TitleTranslation(
        scout_id=scout_id,
        source_title=source_title,
        display_title=display_title,
        translated_at=translated_at,
    )


class TitleTranslationModelTests(unittest.TestCase):
    def test_construction(self):
        translation = _translation()
        self.assertEqual(translation.scout_id, "scout-abc123")
        self.assertIn("JP모건", translation.display_title)

    def test_dict_round_trip(self):
        translation = _translation()
        restored = TitleTranslation.from_dict(translation.to_dict())
        self.assertEqual(translation, restored)

    def test_source_title_preserved_verbatim_in_round_trip(self):
        original = "We simply don't know - JP Morgan struggling to forecast oil prices due to Trump's war with Iran"
        translation = _translation(source_title=original)
        restored = TitleTranslation.from_dict(translation.to_dict())
        self.assertEqual(restored.source_title, original)

    def test_missing_scout_id_is_rejected(self):
        data = _translation().to_dict()
        data["scout_id"] = ""
        with self.assertRaises(TitleTranslationError):
            TitleTranslation.from_dict(data)

    def test_missing_display_title_is_rejected(self):
        data = _translation().to_dict()
        data["display_title"] = ""
        with self.assertRaises(TitleTranslationError):
            TitleTranslation.from_dict(data)


class TitleTranslationFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "tak_scout_title_translations.json"

    def test_load_missing_file_returns_empty_list(self):
        self.assertEqual(load_translations(self.path), [])

    def test_load_empty_file_returns_empty_list(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(load_translations(self.path), [])

    def test_load_rejects_non_list_structure(self):
        self.path.write_text('{"not": "a list"}', encoding="utf-8")
        with self.assertRaises(TitleTranslationError):
            load_translations(self.path)

    def test_save_then_load_round_trip(self):
        translation = _translation()
        save_translations([translation], self.path)
        loaded = load_translations(self.path)
        self.assertEqual(loaded, [translation])

    def test_upsert_adds_new_scout_id(self):
        upsert_translation(self.path, _translation(scout_id="scout-1"))
        upsert_translation(self.path, _translation(scout_id="scout-2", display_title="다른 제목"))
        loaded = {t.scout_id for t in load_translations(self.path)}
        self.assertEqual(loaded, {"scout-1", "scout-2"})

    def test_upsert_overwrites_existing_scout_id(self):
        upsert_translation(self.path, _translation(scout_id="scout-1", display_title="첫 번역"))
        upsert_translation(self.path, _translation(scout_id="scout-1", display_title="갱신된 번역"))
        loaded = load_translations(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].display_title, "갱신된 번역")

    def test_upsert_persists_across_process_boundary(self):
        upsert_translation(self.path, _translation(scout_id="scout-1"))
        # load_translations를 다시 호출하는 것은 "새 프로세스가 파일만 보고 읽는 것"과
        # 동일한 경로다(파일 기반 캐시이므로 메모리 상태에 의존하지 않는다).
        reloaded = load_translations(self.path)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].scout_id, "scout-1")

    def test_translations_by_scout_id_builds_lookup_map(self):
        upsert_translation(self.path, _translation(scout_id="scout-1", display_title="번역 1"))
        upsert_translation(self.path, _translation(scout_id="scout-2", display_title="번역 2"))
        mapping = translations_by_scout_id(self.path)
        self.assertEqual(mapping["scout-1"].display_title, "번역 1")
        self.assertEqual(mapping["scout-2"].display_title, "번역 2")


if __name__ == "__main__":
    unittest.main()
