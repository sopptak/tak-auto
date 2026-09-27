"""6-63 GAME FACTORY 후보 전략 문서 무결성 - 게임은 구현하지 않았으므로 문서가 가리키는 파일·심볼이 실제로 있는지만 본다."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "6-63-game-factory-candidate-strategy.md"


class GameFactoryDocTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")

    def test_twenty_required_sections(self) -> None:
        heads = re.findall(r"^## (\d+)\. (.+)$", self.text, re.M)
        self.assertEqual([int(n) for n, _ in heads], list(range(1, 21)))
        for title in ("Executive Summary", "User Game Director Expertise", "Learning Game", "Launch Criteria",
                      "Relationship to MONEY", "Explicitly NOT IMPLEMENTED"):
            self.assertTrue(any(title in h for _, h in heads), title)

    def test_referenced_paths_exist(self) -> None:
        paths = set(re.findall(r"`((?:docs|content_engine|tak_brain|tests|scripts)/[\w./-]+?)`", self.text))
        paths |= set(re.findall(r"`(docs/[\w.-]+\.md)`", self.text))
        self.assertGreater(len(paths), 8)
        for p in sorted(paths):
            if p.endswith("…"):
                continue
            with self.subTest(path=p):
                self.assertTrue((ROOT / p).exists(), p)

    def test_referenced_symbols_exist(self) -> None:
        code = {"tak_brain/models.py": ("CATEGORIES", "class KnowledgeRecord", "judgment_rule", "_INTERNAL_PATTERN"),
                "content_engine/media_strategy.py": ("HIGH_RISK_KEYWORDS", "def suggest_content_angles", "def build_generation_handoff",
                                                     'PLATFORMS = ("threads", "blog", "shorts")'),
                "content_engine/performance/models.py": ("metrics: dict[str, int]", 'PLATFORMS = ("threads", "youtube", "blog")'),
                "content_engine/performance/window.py": ("def classify_measurement_window",)}
        for path, symbols in code.items():
            src = (ROOT / path).read_text(encoding="utf-8")
            for s in symbols:
                with self.subTest(path=path, symbol=s):
                    self.assertIn(s, src)

    def test_category_mismatch_claim_is_true(self) -> None:
        from tak_brain.models import CATEGORIES

        for missing in ("AI", "직장생활", "고전/전략", "고전"):
            self.assertNotIn(missing, CATEGORIES)  # 9장: 소재군 일부는 category에 없다
        for present in ("금융", "대출", "부동산", "인간관계", "독서", "자기계발", "기타"):
            self.assertIn(present, CATEGORIES)

    def test_ten_candidates_and_not_implemented(self) -> None:
        self.assertEqual(len(re.findall(r"^\*\*(?:[1-9]|10)\. ", self.text, re.M)), 10)
        self.assertNotIn("game", __import__("content_engine.performance.models", fromlist=["PLATFORMS"]).PLATFORMS)
        self.assertFalse(list((ROOT / "content_engine").glob("*game*")))  # 게임 코드 없음


if __name__ == "__main__":
    unittest.main()
