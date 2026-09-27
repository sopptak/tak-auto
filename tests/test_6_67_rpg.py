"""6-67 CHOICE100 OCTOPATH WORLD - 영웅별 이야기 + 메인 스토리 + 시간의 문 + 성장(주몽 Vertical Slice).

데이터(역사 상태·출처) 독립 검증 + JS 엔진 테스트(node) + 화면·분리 점검. 게임은 game_lab/rpg/ 안에만 있다."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RPG = ROOT / "game_lab" / "rpg"
DATA = json.loads((RPG / "korea" / "korea.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")
HS = {"historical_fact", "historical_record", "legend", "game_setting"}


class KoreaDataTests(unittest.TestCase):
    def test_every_entity_declares_historical_status(self) -> None:
        for group in ("heroes", "items", "skills", "regions", "time_gates", "knowledge", "policies", "quizzes", "main_story", "npcs"):
            for x in DATA[group]:
                self.assertIn(x.get("historical_status"), HS, f"{group}/{x['id']}")
        for step in DATA["stories"][0]["chapters"][0]["steps"]:
            if step["type"] == "narration":
                self.assertIn(step["historical_status"], HS)
            for o in step.get("options", []):
                self.assertIn(o["historical_status"], HS)

    def test_facts_have_checked_sources_and_legend_is_not_fact(self) -> None:
        for group in ("quizzes", "knowledge"):
            for x in DATA[group]:
                self.assertRegex(x["source"], r"https://encykorea\.aks\.ac\.kr/Article/E\d+", x["id"])
                self.assertRegex(x["source_date"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertNotEqual(x["historical_status"], "game_setting", x["id"])  # 퀴즈·지식은 기록/전승만
        egg = next(k for k in DATA["knowledge"] if k["id"] == "k_egg_legend")
        self.assertEqual(egg["historical_status"], "legend")
        for q in DATA["quizzes"]:
            self.assertEqual(len(set(q["choices"])), 4)
        # 게임 장치는 모두 게임 설정
        self.assertTrue(all(g["historical_status"] == "game_setting" for g in DATA["time_gates"]))
        bow = next(i for i in DATA["items"] if i["id"] == "jumong_bow")
        self.assertEqual(bow["historical_status"], "game_setting")
        self.assertIn("게임 설정", DATA["disclaimer"])

    def test_world_structure(self) -> None:
        self.assertEqual([s["id"] for s in DATA["stages"]], ["korea", "china_japan", "eurasia"])
        self.assertEqual(DATA["main_story"][-1]["id"], "m_genghis")
        self.assertEqual(DATA["main_story"][-1]["historical_status"], "game_setting")
        self.assertGreaterEqual(len(DATA["heroes"]), 4)
        self.assertEqual({h["id"] for h in DATA["heroes"]} >= {"jumong", "sejong", "yisunsin", "jangbogo"}, True)
        self.assertEqual([h["id"] for h in DATA["heroes"] if h["playable"]], ["jumong"])
        self.assertEqual(DATA["relation_types"], ["FRIEND", "COMPANION", "MENTOR", "RIVAL", "ALLY", "NEUTRAL"])
        self.assertEqual(DATA["item_types"], ["ARTIFACT", "KNOWLEDGE", "POLICY", "SKILL"])
        levels = DATA["levels"]
        self.assertEqual(levels[0], 0)
        self.assertEqual(levels, sorted(set(levels)))
        steps = [s["type"] for s in DATA["stories"][0]["chapters"][0]["steps"]]
        for t in ("narration", "quiz", "reward", "board", "relation", "choice", "companion", "region", "main", "end"):
            self.assertIn(t, steps)
        self.assertLess(steps.index("companion"), steps.index("region"))  # 요청 순서: 동료 → 지역 → 내정


class EngineTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "node 없음")
    def test_js_rpg_suite(self) -> None:
        done = subprocess.run([NODE, "--test", str(RPG / "test" / "rpg.test.js")], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])
        self.assertIn("fail 0", done.stdout)

    @unittest.skipUnless(NODE, "node 없음")
    def test_simulation_stdout_only(self) -> None:
        before = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*"))
        done = subprocess.run([NODE, str(RPG / "sim.js"), str(RPG / "korea" / "korea.json"), "40"], capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        s = json.loads(done.stdout)
        self.assertEqual(s["runs"], 120)
        self.assertEqual(before, sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*")))


class UiAndIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (RPG / "korea" / "index.html").read_text(encoding="utf-8")
        self.js = (RPG / "renderer.js").read_text(encoding="utf-8") + (RPG / "engine.js").read_text(encoding="utf-8")

    def test_mobile_accessibility_and_badges(self) -> None:
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1', self.html)
        self.assertIn("overflow-wrap: anywhere", self.html)
        self.assertIn("prefers-reduced-motion", self.html)
        self.assertIn(":focus-visible", self.html)
        self.assertRegex(self.html, r"\.opt \{[^}]*min-height: 54px")
        for hs in HS:
            self.assertIn(f".hs-{hs}", self.html)
        self.assertIn('../../board/engine.js?v=', self.html)  # 6-66 보드 엔진 재사용

    def test_no_ads_payments_login_network(self) -> None:
        both = (self.html + self.js).lower()
        for word in ("adsbygoogle", "gtag(", "stripe", "payment", "checkout", "login", "google-analytics", "xmlhttprequest", "sendbeacon", "websocket"):
            self.assertNotIn(word, both)
        self.assertNotRegex(self.html + self.js, r"(src|href)=\"https?://")

    def test_isolated_and_other_games_intact(self) -> None:
        for py in list((ROOT / "content_engine").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")) + list((ROOT / "tak_brain").glob("*.py")):
            self.assertNotIn("game_lab", py.read_text(encoding="utf-8"), py.name)
        for f in RPG.rglob("*.js"):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"money_(tasks|log|scout)|writeFileSync")
        self.assertTrue((ROOT / "game_lab" / "choice100" / "data" / "finance.json").exists())
        self.assertTrue((ROOT / "game_lab" / "board" / "world" / "world.json").exists())


if __name__ == "__main__":
    unittest.main()
