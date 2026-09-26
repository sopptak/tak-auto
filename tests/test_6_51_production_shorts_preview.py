"""6-51 운영 ShortsScript -> Shorts V2 장면 분할 검증(렌더링 없음, data/ 미사용).

- 카드 문장을 나눠도 글자는 그대로(공백/줄바꿈만 다름)
- 모든 조각이 6-41 렌더러의 3줄/안전영역 규칙 안에 들어감
- 글이 적은 대본도 새 문장 없이 25초 하한을 맞춤
- 안전영역보다 긴 어절은 공백을 끼우지 않고 줄바꿈만 넣음
"""

from __future__ import annotations

import unittest
from pathlib import Path

from content_engine.shorts_script import ShortsScript
from content_engine.shorts_v2_scene import MIN_TOTAL_SECONDS, total_seconds
from scripts.render_production_shorts_preview import build_spec, fits, same_chars, split_card

HAS_FONTS = Path("C:/Windows/Fonts/NotoSansKR-VF.ttf").exists()
LONG_CARD = ("나는 이런 논란을 투명한 연구와 감독 아래 제한적으로 허용하면서 사회적 논의를 이어가는 방식으로 "
             "다뤄야 한다고 생각합니다. 원문 표현은 \"may be conscious\"입니다.")


@unittest.skipUnless(HAS_FONTS, "Noto Sans KR 폰트가 없는 환경입니다.")
class ProductionPreviewSplitTest(unittest.TestCase):
    def test_split_keeps_characters_and_fits(self) -> None:
        chunks = split_card(LONG_CARD)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(same_chars("".join(chunks), LONG_CARD))
        self.assertTrue(all(fits(c) for c in chunks))
        self.assertIn('"may be conscious"\n입니다.', chunks[-1])  # 공백 없이 줄바꿈만

    def test_short_script_padded_to_minimum_without_new_text(self) -> None:
        script = ShortsScript(title="짧은 제목", subtitle="", cards=("한 문장.", "두 문장."), takeaway="출처: https://example.com/a?x=1")
        spec, split = build_spec(script, "content-test")
        self.assertGreaterEqual(total_seconds(spec), MIN_TOTAL_SECONDS)
        self.assertEqual([s.text for s in spec.scenes[1:-1]], ["한 문장.", "두 문장."])
        self.assertEqual(spec.scenes[-2].note, "출처: example.com/a")


if __name__ == "__main__":
    unittest.main()
