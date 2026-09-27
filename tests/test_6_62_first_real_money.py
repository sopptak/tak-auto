"""6-62 첫 실제 수익 실행 - 실제 PanelNow 회원 화면(2026-09-27, 로그인 상태에서 읽음)으로 만든 fixture.
panelnow_member_real.txt: 화면 글자(innerText). panelnow_member_tree_real.txt: 에이전트가 쓰는 read_page 트리(시간·포인트 칸이 빠짐).
두 fixture 모두 닉네임·포인트 잔액을 지웠다. 실제 claude/Chrome은 부르지 않는다. 데이터는 임시 폴더."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from content_engine import money, money_scout, money_scout_agent
from content_engine.money_scout_adapters import parse_panelnow, tree_lines
from tests.test_6_60_money_scout import PANELNOW_LOGGED_OUT
from tests.test_6_61_money_revenue_loop import NOW, LoopCase, fake_runner

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "money_scout"
MEMBER = (FIX / "panelnow_member_real.txt").read_text(encoding="utf-8")
TREE = (FIX / "panelnow_member_tree_real.txt").read_text(encoding="utf-8")


def agent_out(text: str) -> str:
    return json.dumps({"platforms": [{"platform": "panelnow", "page_url": "https://www.panelnow.co.kr/survey", "page_text": text,
                                      "note": "약관 동의 팝업 있음(누르지 않음)"}]}, ensure_ascii=False)


class MemberScreenTests(LoopCase):
    def test_1_3_4_5_6_real_member_text(self) -> None:
        r = parse_panelnow({"page_text": MEMBER})
        self.assertEqual(r["status"], "SUCCESS")
        self.assertEqual([(i["external_id"], i["title"], i["time_text"], i["reward_text"], i["category"]) for i in r["items"]],
                         [("c001", "Cint 설문조사 참여 수락", "1분", "3P", "제휴 조사"), ("d300170824", "랜덤참여조사", "25분", "700P", "제휴 조사")])

    def test_7_hourly_from_real_values(self) -> None:
        run = self.scout(MEMBER)
        by_id = {i["external_id"]: i for i in run["items"]}
        self.assertEqual((by_id["d300170824"]["reward_krw_estimate"], by_id["d300170824"]["estimated_minutes"], by_id["d300170824"]["hourly_rate"]),
                         (700, 25, 1680))
        self.assertEqual(by_id["c001"]["hourly_rate"], 180)

    def test_tree_reading_keeps_only_what_is_shown(self) -> None:
        self.assertIsNone(tree_lines(MEMBER))
        r = parse_panelnow({"page_text": TREE})
        self.assertEqual([(i["external_id"], i["time_text"], i["reward_text"]) for i in r["items"]],
                         [("c001", "", ""), ("d300170824", "", "700P")])  # 빠진 칸은 비움(추측 안 함)

    def test_2_logged_out_rejected_text_and_tree(self) -> None:
        self.assertEqual(parse_panelnow({"page_text": PANELNOW_LOGGED_OUT})["status"], "LOGIN_REQUIRED")
        self.assertEqual(parse_panelnow({"page_text": TREE.replace("로그아웃", "로그인")})["status"], "LOGIN_REQUIRED")

    def test_tree_after_full_read_does_not_erase_or_hide(self) -> None:
        self.scout(MEMBER)
        run = self.scout(TREE)  # 버튼 실행(트리) - c001은 보상이 안 읽혀 검토로 감
        self.assertEqual(run["promotion"]["disappeared"], 0)
        tasks = {t["external_id"]: t for t in self.store.tasks()}
        self.assertEqual((tasks["d300170824"]["reward"], tasks["d300170824"]["minutes"]), (700, 25))
        self.assertEqual((tasks["c001"]["reward"], tasks["c001"]["minutes"], tasks["c001"]["scout_state"]), (3, 1, "active"))

    def test_14_browser_failure_and_tools(self) -> None:
        self.assertIn("mcp__claude-in-chrome__read_page", money_scout_agent.AGENT_TOOLS)
        for bad in ("computer", "form_input", "javascript_tool", "find", "file_upload"):
            self.assertFalse(any(bad in t for t in money_scout_agent.AGENT_TOOLS), bad)
        prompt = money_scout_agent.build_prompt(money_scout.plan())
        self.assertIn("read_page", prompt)
        self.assertIn("약관 동의 같은 팝업이 떠 있어도 누르지 말고", prompt)
        empty = money_scout_agent.run_agent(claude="claude", runner=fake_runner(agent_out("")))
        self.assertEqual(next(p for p in empty["platforms"] if p["platform"] == "panelnow")["status"], "PARSE_FAILED")
        run = money_scout_agent.run_scout(tasks_path=self.dir / "money_tasks.json", staging_path=self.staging, now=NOW, claude="claude",
                                          runner=fake_runner(agent_out(TREE)))
        self.assertEqual((run["platforms"]["panelnow"]["status"], run["promotion"]["created"]), ("SUCCESS", 1))


class FirstMoneyTests(LoopCase):
    def test_8_top3_falls_back_to_hold_with_reason(self) -> None:
        self.scout(MEMBER)
        groups = money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW)
        self.assertEqual((len(groups["NOW"]), len(groups["LATER"]), len(groups["HOLD"])), (0, 0, 2))
        top = money_scout.top_picks(groups)
        self.assertEqual([t["external_id"] for t in top], ["d300170824", "c001"])
        self.assertTrue(all(t["bucket"] == "HOLD" and "내 기록 부족" in t["reason"] for t in top))
        gone = [{**t, "scout_state": "disappeared"} if t["external_id"] == "c001" else t for t in self.store.tasks()]
        self.assertEqual([t["external_id"] for t in money_scout.top_picks(money_scout.buckets(gone, [], self.config, NOW))],
                         ["d300170824"])  # 안 보이게 된 것은 TOP에 넣지 않는다

    def test_9_10_11_actual_revenue_pending_then_recorded(self) -> None:
        self.scout(MEMBER)
        tm = money_scout.today_money(self.store.tasks(), self.store.log(), self.config, NOW)
        self.assertEqual((tm["revenue_state"], tm["actual_today"], tm["goal"]["current"], tm["actual_hourly"]), ("REAL_REVENUE_PENDING", 0, 0, None))
        tid = next(t["id"] for t in self.store.tasks() if t["external_id"] == "d300170824")
        money_scout.record_choice(self.store, tid, "DO", now=NOW)
        e = self.store.complete(tid, actual_reward="500", actual_minutes="12", now=NOW + timedelta(minutes=30))
        self.assertEqual((e["actual_reward"], e["actual_minutes"], e["actual_hourly"], e["estimated_reward"]), (500, 12, 2500, 700))
        tm = money_scout.today_money(self.store.tasks(), self.store.log(), self.config, NOW + timedelta(minutes=31))
        self.assertEqual((tm["revenue_state"], tm["actual_today"], tm["goal"]["current"], tm["goal"]["first_progress"], tm["actual_hourly"]),
                         ("REAL_REVENUE_RECORDED", 500, 500, 5.0, 2500))
        self.assertEqual(tm["expected_krw"], 0)  # 남은 기회는 ⚪뿐 - 예상은 🔥·🟡만, 목표와 섞지 않음

    def test_12_one_record_does_not_retrain(self) -> None:
        self.scout(MEMBER)
        tid = next(t["id"] for t in self.store.tasks() if t["external_id"] == "d300170824")
        self.store.complete(tid, actual_reward=700, actual_minutes=10, now=NOW)
        c = next(t for t in money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW)["HOLD"] if t["external_id"] == "c001")
        self.assertIsNone(c.get("learned_hourly"))  # 표본 3건 미만 - 보정 안 함
        self.assertIn("내 기록 부족", c["reason"])
        self.assertLess(len(self.store.log()), self.config["learning"]["min_samples_for_hourly"])

    def test_15_duplicate_completion(self) -> None:
        self.scout(MEMBER)
        tid = self.store.tasks()[0]["id"]
        self.store.complete(tid, actual_reward=3, actual_minutes=1, now=NOW)
        with self.assertRaises(money.MoneyError):
            self.store.complete(tid, actual_reward=3, actual_minutes=1, now=NOW)
        self.assertEqual(len(self.store.log()), 1)

    def test_16_content_cluster_strategy_documented(self) -> None:
        doc = (ROOT / "docs" / "6-62-first-real-money-run.md").read_text(encoding="utf-8")
        for word in ("금융/대출", "부동산", "인간관계", "고전/전략", "AI", "직장생활", "소재군", "채널 분리", "실제 수익 0원 — 아직 발생하지 않음"):
            self.assertIn(word, doc)


class HomeHtmlTests(LoopCase):
    def test_13_production_money_untouched(self) -> None:
        import hashlib

        real = [ROOT / "data" / f"money_{n}.json" for n in ("tasks", "log", "checks", "config", "scout_staging")]
        before = [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in real]
        self.scout(MEMBER)
        self.scout(TREE)
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in real])

    def test_today_money_block_is_simple_and_honest(self) -> None:
        from scripts import money_web

        self.scout(MEMBER)
        html = money_web._today_money_html(self.store)
        for t in ("💰 TODAY MONEY", "오늘 발견 <b>2건", "🔥 지금 할 것 <b>0건", "오늘 실제 수익 <b>0원", "이번 달 실제 수익 <b>0원",
                  "🎯 첫 목표 <b>0 / 10,000원</b> (0%)", "실제 수익 0원 — 아직 발생하지 않음", "🔎 지금 수익기회 찾기"):
            self.assertIn(t, html)
        self.assertLess(html.index("🎯 첫 목표"), html.index("예상 수익"))
