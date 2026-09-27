"""6-68 고조선 — 첫 번째 땅: 탐험 + 부족 통합 Vertical Slice.

역사 경계(사실·기록·신화·전승·게임 설정)와 출처를 데이터에서 독립 검증하고, JS 엔진 테스트(node)와 화면·분리를 점검한다.
주몽(6-67)·보드(6-66)는 그대로 두고 재사용한다."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RPG = ROOT / "game_lab" / "rpg"
DATA = json.loads((RPG / "gojoseon" / "gojoseon.json").read_text(encoding="utf-8"))
X = DATA["explore"]
NODE = shutil.which("node")
TAGS = {"historical_fact", "historical_record", "mythology", "legend", "game_setting"}


class HistoryBoundaryTests(unittest.TestCase):
    def test_every_entity_is_tagged(self) -> None:
        for group in ("knowledge", "items", "skills", "heroes", "policies"):
            for x in DATA[group]:
                self.assertIn(x["historical_status"], TAGS, f"{group}/{x['id']}")
        for group in ("locations", "events", "tribes"):
            for x in X[group]:
                self.assertIn(x["historical_status"], TAGS, f"{group}/{x['id']}")
        for loc in X["locations"]:
            for s in loc.get("searches", []):
                self.assertIn(s["historical_status"], TAGS)
        for ev in X["events"]:
            for c in ev["choices"]:
                self.assertIn(c["historical_status"], TAGS)

    def test_myth_record_fact_are_separated_with_sources(self) -> None:
        k = {x["id"]: x for x in DATA["knowledge"]}
        self.assertEqual({k[i]["historical_status"] for i in ("k_myth", "k_dangun", "k_hongik")}, {"mythology"})
        self.assertEqual({k[i]["historical_status"] for i in ("k_dolmen", "k_bipa")}, {"historical_fact"})
        self.assertEqual(k["k_8laws"]["historical_status"], "historical_record")
        for x in DATA["knowledge"]:
            if x["historical_status"] != "game_setting":
                self.assertRegex(x["source"], r"https://(encykorea\.aks\.ac\.kr/Article/E\d+|ko\.wikipedia\.org/wiki/)", x["id"])
                self.assertRegex(x["source_date"], r"^\d{4}-\d{2}-\d{2}$")
        # 퀴즈(사냥 보드)도 출처가 있다
        for q in DATA["boards"]["forest_hunt"]["data"]["quizzes"]:
            self.assertIn("encykorea", q["source"])

    def test_no_uncertain_founding_year_and_tribes_are_fiction(self) -> None:
        text = json.dumps(DATA, ensure_ascii=False)
        self.assertNotIn("2333", text)
        self.assertIn("건국 연도를 사실로 쓰지 않습니다", DATA["disclaimer"])
        for t in X["tribes"]:
            self.assertEqual(t["historical_status"], "game_setting")
            self.assertIn("게임 설정", t["desc"])
        self.assertEqual(X["ending"]["epilogue"]["historical_status"], "game_setting")
        self.assertIn("신화", X["ending"]["epilogue"]["text"])

    def test_slice_shape(self) -> None:
        self.assertGreaterEqual(len(X["locations"]), 10)
        self.assertEqual(len(X["tribes"]), 4)
        self.assertEqual({t["trait"].split("·")[0] for t in X["tribes"]}, {"사냥", "농사", "청동", "교역"})
        self.assertEqual({m["type"] for m in X["minigames"]}, {"pick", "board"})
        for t in X["tribes"]:
            self.assertTrue(t["requests"])
            self.assertIn("rewards", t["union"])
            enc = next(e for e in X["events"] if e["id"] == t["encounter"])
            self.assertGreaterEqual(len(enc["choices"]), 4)  # 관찰·교역/선물·도움·위협


class EngineTests(unittest.TestCase):
    def _node(self, rel: str) -> None:
        done = subprocess.run([NODE, "--test", str(ROOT / rel)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])
        self.assertIn("fail 0", done.stdout)

    @unittest.skipUnless(NODE, "node 없음")
    def test_explore_suite(self) -> None:
        self._node("game_lab/rpg/test/explore.test.js")

    @unittest.skipUnless(NODE, "node 없음")
    def test_jumong_and_board_still_pass(self) -> None:
        self._node("game_lab/rpg/test/rpg.test.js")
        self._node("game_lab/board/test/board.test.js")

    @unittest.skipUnless(NODE, "node 없음")
    def test_simulation_stdout_only(self) -> None:
        before = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*"))
        done = subprocess.run([NODE, str(RPG / "explore-sim.js"), str(RPG / "gojoseon" / "gojoseon.json"), "10"], capture_output=True, text=True, encoding="utf-8", timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        s = json.loads(done.stdout)
        self.assertEqual(s["runs"], 40)
        self.assertTrue(all(b["ended"] == b["n"] for b in s["by"].values()))
        self.assertEqual(before, sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*")))


class UiAndIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (RPG / "gojoseon" / "index.html").read_text(encoding="utf-8")
        self.js = "".join((RPG / f).read_text(encoding="utf-8") for f in ("explore.js", "explore-renderer.js"))

    def test_mobile_and_accessibility(self) -> None:
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1', self.html)
        self.assertIn("overflow-wrap: anywhere", self.html)
        self.assertIn(":focus-visible", self.html)
        self.assertIn("prefers-reduced-motion", self.html)
        self.assertRegex(self.html, r"repeat\(5, minmax\(0, 1fr\)\)")  # 5×4 지도가 390px 안에
        self.assertIn(".hs-mythology", self.html)
        self.assertIn('aria-label="지도', self.js)
        for f in ("../../board/engine.js", "../../choice100/analytics.js", "../engine.js", "../explore.js"):
            self.assertIn(f, self.html)  # 기존 엔진 재사용

    def test_no_ads_payments_login_network(self) -> None:
        both = (self.html + self.js).lower()
        for word in ("adsbygoogle", "gtag(", "stripe", "payment", "checkout", "login", "google-analytics", "xmlhttprequest", "sendbeacon", "websocket"):
            self.assertNotIn(word, both)
        self.assertNotRegex(self.html + self.js, r"(src|href)=\"https?://")

    def test_isolated_and_previous_slices_intact(self) -> None:
        for py in list((ROOT / "content_engine").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")) + list((ROOT / "tak_brain").glob("*.py")):
            self.assertNotIn("game_lab", py.read_text(encoding="utf-8"), py.name)
        for rel in ("game_lab/rpg/korea/korea.json", "game_lab/rpg/korea/index.html", "game_lab/board/world/world.json", "game_lab/choice100/data/finance.json"):
            self.assertTrue((ROOT / rel).exists(), rel)
        for f in RPG.rglob("*.js"):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"money_(tasks|log|scout)|writeFileSync")


if __name__ == "__main__":
    unittest.main()
