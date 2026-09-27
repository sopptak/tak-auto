"""6-64 CHOICE100 금융 G1 - 게임 데이터(파이썬으로 독립 검증) + JS 엔진 테스트(node --test) + 화면·가드레일 정적 점검.

게임은 game_lab/choice100/ 안에만 있다(production·MONEY와 분리). node가 없으면 JS 테스트만 건너뛴다."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "game_lab" / "choice100"
DATA = json.loads((GAME / "data" / "finance.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")


class DataTests(unittest.TestCase):
    def test_100_choice_architecture_and_30_scenarios(self) -> None:
        self.assertEqual(DATA["total_choices"], 100)
        self.assertEqual(DATA["session_size"], 10)
        ranges = [tuple(c["range"]) for c in DATA["chapters"]]
        self.assertEqual(ranges, [(i * 10 + 1, i * 10 + 10) for i in range(10)])  # 1~100을 빈틈없이
        self.assertEqual([c["title"] for c in DATA["chapters"]],
                         ["돈의 흐름", "부채와 신용", "저축과 투자", "주거와 부동산", "소비와 라이프스타일", "위기와 리스크",
                          "소득과 커리어", "투자와 기회", "가족과 인생", "은퇴와 최종 선택"])
        self.assertEqual(len(DATA["scenarios"]), 30)
        for n in (1, 2, 3):
            self.assertEqual(sum(s["chapter"] == n for s in DATA["scenarios"]), 10)
        self.assertEqual([c["status"] for c in DATA["chapters"]], ["playable"] * 3 + ["planned"] * 7)

    def test_schema_links_and_tradeoffs(self) -> None:
        stats = {s["key"] for s in DATA["stats"]}
        ids = [s["id"] for s in DATA["scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        for sc in DATA["scenarios"]:
            for key in ("id", "chapter", "title", "situation", "choices", "next", "difficulty", "tags"):
                self.assertIn(key, sc, sc["id"])
            self.assertTrue(2 <= len(sc["choices"]) <= 4)
            self.assertTrue(any("requires" not in c for c in sc["choices"]), sc["id"])
            for c in sc["choices"]:
                where = f"{sc['id']}.{c['id']}"
                for key in ("id", "text", "effects", "result_text", "tip"):
                    self.assertIn(key, c, where)
                self.assertIn(c.get("next") or sc["next"], set(ids) | {"END"}, where)
                self.assertLessEqual(set(c["effects"]), stats, where)
            # 선택지끼리 효과가 모두 같으면 고민할 이유가 없다
            self.assertEqual(len({json.dumps([c["effects"], c.get("moves"), c.get("add_per_turn")], sort_keys=True) for c in sc["choices"]}),
                             len(sc["choices"]), sc["id"])
        self.assertEqual(DATA["scenarios"][-1]["next"], "END")

    def test_endings_cover_required_types(self) -> None:
        titles = [e["title"] for e in DATA["endings"]]
        for t in ("재무 안정형", "공격적 성장형", "소비 행복형", "위험한 한방형", "균형 성장형"):
            self.assertIn(t, titles)
        self.assertEqual(DATA["endings"][-1]["when"], [])

    def test_financial_guardrails_in_content(self) -> None:
        self.assertIn("실제 금융상품·투자·대출에 대한 조언이 아닙니다", DATA["disclaimer"])
        text = json.dumps(DATA["scenarios"], ensure_ascii=False)
        # 실제 금리·수익률 수치 단정 금지: TIP·결과문에 'N%' 없음(게임 사건 문구 on_enter만 %를 씀)
        for sc in DATA["scenarios"]:
            for c in sc["choices"]:
                self.assertNotRegex(c["tip"], r"\d+(\.\d+)?\s*%", f"{sc['id']}.{c['id']}")
                self.assertLessEqual(len(c["tip"]), 90)
        for brand in ("삼성", "카카오", "토스", "국민은행", "신한", "비트코인", "테슬라", "KB", "NH", "수협"):
            self.assertNotIn(brand, text)


class EngineTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "node 없음")
    def test_js_engine_suite(self) -> None:
        done = subprocess.run([NODE, "--test", str(GAME / "test" / "engine.test.js")], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])
        self.assertIn("fail 0", done.stdout)

    @unittest.skipUnless(NODE, "node 없음")
    def test_simulation_prints_only(self) -> None:
        before = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*"))
        done = subprocess.run([NODE, str(GAME / "sim.js"), str(GAME / "data" / "finance.json"), "120"], capture_output=True, text=True,
                              encoding="utf-8", timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr)
        summary = json.loads(done.stdout)
        self.assertGreaterEqual(summary["runs"], 100)
        self.assertEqual(set(summary["endings"]), {e["id"] for e in DATA["endings"]})
        self.assertEqual(before, sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*")))  # 어디에도 저장 안 함


class UiAndIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (GAME / "index.html").read_text(encoding="utf-8")
        self.js = (GAME / "renderer.js").read_text(encoding="utf-8") + (GAME / "engine.js").read_text(encoding="utf-8")

    def test_mobile_first_markup(self) -> None:
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1', self.html)
        self.assertIn("overflow-wrap: anywhere", self.html)
        self.assertIn("prefers-reduced-motion", self.html)
        self.assertIn("prefers-reduced-motion", self.js)
        self.assertRegex(self.html, r"body \{[^}]*font-size: 16px")
        self.assertRegex(self.html, r"\.choice \{[^}]*min-height: 54px")
        self.assertIn("이것은 가상의 재무 시뮬레이션입니다.", self.js)

    def test_no_ads_payments_login_or_external_calls(self) -> None:
        both = self.html + self.js
        self.assertNotRegex(both, r"(src|href)=\"https?://")
        self.assertNotRegex(both, r"fetch\(\s*[\"']https?://")
        for word in ("adsbygoogle", "gtag(", "stripe", "payment", "checkout", "purchase(", "login", "analytics.js"):
            self.assertNotIn(word, both.lower())
        self.assertRegex(self.js, r"try \{\s*if \(op === \"get\"\) return window\.localStorage")  # 저장 실패해도 게임은 돈다

    def test_isolated_from_production(self) -> None:
        for py in list((ROOT / "content_engine").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")) + list((ROOT / "tak_brain").glob("*.py")):
            self.assertNotIn("game_lab", py.read_text(encoding="utf-8"), py.name)
        for f in GAME.rglob("*.js"):
            src = f.read_text(encoding="utf-8")
            self.assertNotRegex(src, r"money_(tasks|log|scout|checks|config)")
            self.assertNotRegex(src, r"\.\./\.\./data|writeFileSync")


if __name__ == "__main__":
    unittest.main()
