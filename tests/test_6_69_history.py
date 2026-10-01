"""6-69 KOREA HISTORY MASTER CONTENT SYSTEM.

역사 데이터(시대·인물·엔티티·관계·어빌리티·영웅 풀·영입 퀘스트)를 JSON에서 독립 검증하고, JS 검증기(node)와 고조선 슬라이스 회귀를 돌린다.
노래 「한국을 빛낸 100명의 위인들」은 목차로만 쓴다: 수록 여부만 저장하고 가사는 싣지 않는다."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIS = ROOT / "game_lab" / "history"
DATA = HIS / "data"
NODE = shutil.which("node")
STATUSES = {"HISTORICAL_RECORD", "HISTORICAL_INTERPRETATION", "MYTHOLOGY", "LEGEND", "LITERARY_FICTION", "GAME_SETTING"}
TYPES = {"PERSON", "HERO", "EVENT", "LOCATION", "REGION", "TERRAIN", "ARTIFACT", "TECHNOLOGY", "INSTITUTION", "CULTURE",
         "SPECIALTY", "COUNTRY", "TRIBE", "BATTLE", "KNOWLEDGE", "MYTH", "LEGEND"}


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.persons = load("persons.json")
        cls.entities = load("entities.json")
        cls.abilities = {a["id"] for a in load("abilities.json")}
        cls.eras = [e["id"] for e in load("eras.json")["historical_timeline"]]

    def test_entity_schema_and_status(self) -> None:
        for e in self.entities:
            self.assertIn(e["type"], TYPES, e["id"])
            self.assertIn(e["historical_status"], STATUSES, e["id"])
            for f in ("id", "name", "era", "description", "source_refs", "related_entities", "game_effects", "abilities", "unlock_condition"):
                self.assertIn(f, e, f"{e['id']}.{f}")
        for p in self.persons:
            self.assertIn(p["historical_status"], STATUSES, p["id"])
            for f in ("era", "country", "roles", "historical_summary", "key_events", "related_locations", "related_artifacts", "knowledge", "base_stats", "abilities"):
                self.assertIn(f, p, f"{p['id']}.{f}")
            self.assertIn("GAME_SETTING", p["game_data_note"])
            self.assertTrue(set(p["abilities"]) <= self.abilities, p["id"])

    def test_eras_all_present(self) -> None:
        self.assertEqual(self.eras, ["BRONZE_AGE", "GOJOSEON", "THREE_KINGDOMS", "NORTH_SOUTH_STATES", "GORYEO", "JOSEON", "MODERN"])
        self.assertTrue(self.abilities >= {"AB_JINDAE", "AB_HUNMINJEONGEUM", "AB_NAVAL_COMMAND", "AB_BRONZE_CASTING"})

    def test_song_is_membership_only(self) -> None:
        song = load("song_catalog.json")
        self.assertEqual(sum(p["song_catalog"]["included"] for p in self.persons), 100)
        self.assertTrue(all(set(p["song_catalog"]) == {"included"} for p in self.persons))
        self.assertNotIn("lyrics", json.dumps(song).lower())
        self.assertIn("가사", song["policy"])
        self.assertGreater(len(self.persons), 100)

    def test_contested_figures_and_fiction(self) -> None:
        p = {x["id"]: x for x in self.persons}
        self.assertFalse(p["YI_WANYONG"]["hero_eligible"])
        self.assertFalse(p["JEONG_JUNGBU"]["hero_eligible"])
        self.assertFalse(p["KIM_DUHAN"]["hero_eligible"])
        for fic in ("HONG_GILDONG", "YI_SUIL", "SIM_SUNAE"):
            self.assertEqual(p[fic]["historical_status"], "LITERARY_FICTION")
        self.assertEqual(p["DAN_GUN"]["historical_status"], "MYTHOLOGY")
        self.assertIn("전설", p["MUN_IKJEOM"]["historical_summary"])
        self.assertNotIn("2333", (DATA / "persons.json").read_text(encoding="utf-8") + (DATA / "entities.json").read_text(encoding="utf-8"))

    def test_sources_are_https_with_date(self) -> None:
        for k, s in load("sources.json").items():
            self.assertRegex(s["url"], r"^https://(encykorea\.aks\.ac\.kr/Article/E\d+|ko\.wikipedia\.org/wiki/)", k)
            self.assertRegex(s["checked"], r"^\d{4}-\d{2}-\d{2}$")


class EngineTests(unittest.TestCase):
    def _node(self, rel: str) -> None:
        done = subprocess.run([NODE, "--test", str(ROOT / rel)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-2000:])
        self.assertIn("fail 0", done.stdout)

    @unittest.skipUnless(NODE, "node 없음")
    def test_history_suite(self) -> None:
        self._node("game_lab/history/test/history.test.js")

    @unittest.skipUnless(NODE, "node 없음")
    def test_gojoseon_jumong_board_regression(self) -> None:
        self._node("game_lab/rpg/test/explore.test.js")
        self._node("game_lab/rpg/test/rpg.test.js")
        self._node("game_lab/board/test/board.test.js")


class IsolationTests(unittest.TestCase):
    def test_no_network_or_writes(self) -> None:
        js = (HIS / "history.js").read_text(encoding="utf-8")
        for word in ("xmlhttprequest", "sendbeacon", "websocket", "writefilesync", "localstorage", "http://", "https://"):
            self.assertNotIn(word, js.lower())
        for py in list((ROOT / "content_engine").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
            self.assertNotIn("game_lab", py.read_text(encoding="utf-8"), py.name)


if __name__ == "__main__":
    unittest.main()
