"""6-66 CHOICE100 BOARD CORE - QUIZ → REWARD(DICE_PARITY) → DICE → BOARD. 세계사 G1 데이터 검증 + JS 엔진 테스트(node) + 화면·분리 점검.

게임은 game_lab/board/ 안에만 있다(production·MONEY·금융 게임과 분리). node가 없으면 JS 테스트만 건너뛴다."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "game_lab" / "board"
WORLD = json.loads((BOARD / "world" / "world.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")


class WorldDataTests(unittest.TestCase):
    def test_quizzes_have_verifiable_sources(self) -> None:
        self.assertGreaterEqual(len(WORLD["quizzes"]), 10)
        ids = [q["id"] for q in WORLD["quizzes"]]
        self.assertEqual(len(ids), len(set(ids)))
        for q in WORLD["quizzes"]:
            for k in ("id", "question", "choices", "correct", "explanation", "topic", "era", "region", "source", "source_date"):
                self.assertIn(k, q, q["id"])
            self.assertEqual(len(set(q["choices"])), 4, q["id"])
            self.assertIn(q["correct"], range(4))
            self.assertRegex(q["source"], r"https://en\.wikipedia\.org/wiki/\w+", q["id"])
            self.assertRegex(q["source_date"], r"^\d{4}-\d{2}-\d{2}$")
            # 해설에 정답 보기가 들어 있다(정답·해설 불일치 방지)
            answer = q["choices"][q["correct"]]
            self.assertTrue(answer.rstrip("년") in q["explanation"] or answer in q["explanation"], (q["id"], answer))

    def test_board_shape_and_cells(self) -> None:
        board = WORLD["board"]
        self.assertGreaterEqual(len(board), 20)
        self.assertEqual(board[0]["type"], "START")
        counts = {t: sum(c["type"] == t for c in board) for t in ("CITY", "TRADE", "EXPLORE", "EVENT", "QUIZ", "BONUS")}
        for t, n in {"CITY": 4, "TRADE": 4, "EXPLORE": 4, "EVENT": 3, "QUIZ": 3, "BONUS": 2}.items():
            self.assertGreaterEqual(counts[t], n, t)
        for c in board:
            for k in ("id", "type", "name", "region"):
                self.assertIn(k, c)
            if c["type"] in ("EVENT", "EXPLORE"):
                self.assertIn("wikipedia.org", c["lesson"]["source"], c["name"])
                self.assertLessEqual(len(re.findall(r"[.!?다]\s|[.!?다]$", c["lesson"]["text"])), 2)

    def test_rewards_dice_and_state(self) -> None:
        self.assertEqual(WORLD["dice"], {"sides": 6})
        dp = WORLD["rewards"]["DICE_PARITY"]
        self.assertIn("3/6", dp["desc"])
        self.assertEqual(dp["on_hit"], {"steer": 1})
        for planned in ("MOVE_BONUS", "TRADE_BONUS", "EXPLORE_TOKEN", "PROTECTION", "COIN"):
            self.assertEqual(WORLD["rewards"][planned], {"status": "planned"})
        self.assertEqual([s["key"] for s in WORLD["stats"]], ["coin", "knowledge", "exploration"])
        self.assertGreaterEqual(WORLD["turns"], 10)

    def test_history_vs_game_setting_is_explicit(self) -> None:
        self.assertIn("게임용 가상", WORLD["route_note"])
        self.assertIn("실제 역사와 다릅니다", WORLD["disclaimer"])


class EngineTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "node 없음")
    def test_js_board_suite(self) -> None:
        done = subprocess.run([NODE, "--test", str(BOARD / "test" / "board.test.js")], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])
        self.assertIn("fail 0", done.stdout)

    @unittest.skipUnless(NODE, "node 없음")
    def test_simulation_is_stdout_only(self) -> None:
        before = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*"))
        done = subprocess.run([NODE, str(BOARD / "sim.js"), str(BOARD / "world" / "world.json"), "30"], capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        s = json.loads(done.stdout)
        self.assertEqual(s["games"], 360)
        self.assertAlmostEqual(s["dice"]["hit_rate"], 0.5, delta=0.05)
        self.assertEqual(before, sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*")))


class UiAndIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (BOARD / "world" / "index.html").read_text(encoding="utf-8")
        self.js = (BOARD / "renderer.js").read_text(encoding="utf-8") + (BOARD / "engine.js").read_text(encoding="utf-8")

    def test_mobile_and_accessibility_markup(self) -> None:
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1', self.html)
        self.assertIn("overflow-wrap: anywhere", self.html)
        self.assertIn("prefers-reduced-motion", self.html)
        self.assertIn("prefers-reduced-motion", self.js)
        self.assertIn(":focus-visible", self.html)
        self.assertRegex(self.html, r"\.opt \{[^}]*min-height: 54px")
        self.assertRegex(self.html, r"repeat\(8, minmax\(0, 1fr\)\)")  # 24칸 지도가 390px에 들어가게
        self.assertIn('aria-label="항로 지도', self.js)
        self.assertRegex(self.html, r'<script src="\.\./engine\.js\?v=')

    def test_dice_is_not_rigged_in_code(self) -> None:
        engine = (BOARD / "engine.js").read_text(encoding="utf-8")
        self.assertIn("1 + Math.floor(this.rng() * this.data.dice.sides)", engine)
        self.assertIn("getRandomValues", engine)
        self.assertEqual(engine.count("this.rng()"), 2)  # 주사위 1곳 + 퀴즈 섞기 1곳

    def test_analytics_local_only_and_events(self) -> None:
        analytics = (ROOT / "game_lab" / "choice100" / "analytics.js").read_text(encoding="utf-8")
        for net in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "http://", "https://"):
            self.assertNotIn(net, analytics)
        for ev in ("quiz_answer", "reward_earned", "dice_parity_selected", "dice_result", "board_move", "trade", "explore"):
            self.assertIn(f'stats.log("{ev}"', self.js)
        self.assertIn("stats.complete(", self.js)
        both = (self.html + self.js).lower()
        for word in ("adsbygoogle", "gtag(", "stripe", "payment", "checkout", "login", "google-analytics"):
            self.assertNotIn(word, both)
        self.assertNotRegex(self.html + self.js, r"(src|href)=\"https?://")

    def test_isolated_from_production_and_finance_intact(self) -> None:
        for py in list((ROOT / "content_engine").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")) + list((ROOT / "tak_brain").glob("*.py")):
            self.assertNotIn("game_lab", py.read_text(encoding="utf-8"), py.name)
        for f in BOARD.rglob("*.js"):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"money_(tasks|log|scout)|writeFileSync")
        finance = json.loads((ROOT / "game_lab" / "choice100" / "data" / "finance.json").read_text(encoding="utf-8"))
        self.assertEqual((finance["id"], len(finance["scenarios"])), ("choice100-finance", 40))


if __name__ == "__main__":
    unittest.main()
