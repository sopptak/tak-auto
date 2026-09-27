"""6-59 MONEY 성과 루프 - 확인 대비 성과, 표본 부족 처리, 개인화 순서, 보정, 최근 7일, 일일/주간 summary, 운영 로그, 빠른 수익 기록.
모든 데이터는 임시 폴더. 실제 data/money_*.json은 읽기만 해서 전후 비교한다."""

from __future__ import annotations

import hashlib
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from content_engine import money
from content_engine.money import MoneyError
from tests.test_6_57_money import KST, NOW, MoneyCase

ROOT = Path(__file__).resolve().parents[1]
EVENING = datetime(2026, 9, 27, 20, 0, tzinfo=KST)  # 일요일


class PerfCase(MoneyCase):
    def seed_panelnow(self, now=EVENING) -> None:
        """패널나우: 10일(9/18~9/27) 하루 1번 확인, 앞 6일(9/18~9/23) 발견·등록, 그중 9/20~9/23의 4건 완료(800원/20·20·20·22분)."""
        for i in range(10):
            day = now - timedelta(days=9 - i)
            found = i < 6
            self.store.record_check("패널나우", "found" if found else "none", now=day)
            if found:
                t = self.store.add_task(platform="패널나우", title=f"설문{i}", reward=850, minutes=20, status="new", now=day)
                if 2 <= i < 6:
                    self.store.complete(t["id"], actual_reward=800, actual_minutes=22 if i == 5 else 20, now=day + timedelta(minutes=30))

    def perf(self, **kw) -> dict:
        return {p["platform"]: p for p in money.performance(self.store.tasks(), self.store.log(), self.store.checks(), self.config, **kw)}


class PerformanceTests(PerfCase):
    def test_1_to_6_check_found_complete_rates_and_hourly(self) -> None:
        self.seed_panelnow()
        p = self.perf()["패널나우"]
        self.assertEqual((p["checks"], p["found"], p["no_task"], p["registered"], p["accepted"], p["completed"]), (10, 6, 4, 6, 4, 4))
        self.assertEqual((p["earned"], p["minutes"], p["actual_hourly"]), (3200, 82, 2341))
        self.assertEqual((p["discovery_rate"], p["completion_rate"], p["revenue_rate"], p["earned_per_check"]), (60.0, 66.7, 40.0, 320))
        self.assertEqual((p["avg_estimated_hourly"], p["avg_actual_hourly"], p["gap_pct"], p["hourly_sufficient"]), (2550, 2341, -8.2, True))

    def test_7_8_insufficient_samples_show_nothing(self) -> None:
        empty = self.perf()["오베이"]
        self.assertEqual((empty["checks"], empty["discovery_rate"], empty["completion_rate"], empty["actual_hourly"],
                          empty["earned_per_check"], empty["priority_ready"], empty["hourly_sufficient"]), (0, None, None, None, None, False, False))
        t = self.store.add_task(platform="오베이", title="x", reward=1200, minutes=15, status="new", now=EVENING)
        self.store.complete(t["id"], actual_reward=1200, actual_minutes=20, now=EVENING)
        p = self.perf()["오베이"]
        self.assertEqual((p["checks"], p["priority_ready"], p["hourly_samples"], p["hourly_sufficient"], p["gap_pct"]), (1, False, 1, False, -25.0))
        cal = {c["platform"]: c for c in money.calibration(self.store.log(), self.config)}["오베이"]
        self.assertEqual((cal["sufficient"], cal["ratio"]), (False, None))

    def test_implicit_check_when_registering_without_check_button(self) -> None:
        self.store.add_task(platform="헤이폴", title="a", reward=450, minutes=10, status="new", now=EVENING)
        self.store.add_task(platform="헤이폴", title="b", reward=500, minutes=10, status="new", now=EVENING + timedelta(minutes=5))
        p = self.perf()["헤이폴"]
        self.assertEqual((p["checks"], p["found"], p["implicit_checks"], p["registered"]), (1, 1, 1, 2))  # 같은 날 = 확인 1회
        self.store.record_check("헤이폴", "found", now=EVENING)
        p = self.perf()["헤이폴"]
        self.assertEqual((p["checks"], p["implicit_checks"]), (1, 0))  # 명시적 확인이 있으면 중복으로 세지 않음

    def test_9_priority_when_every_routine_platform_has_enough_checks(self) -> None:
        for name, found_days, reward in (("패널나우", 1, 500), ("오베이", 3, 1200), ("헤이폴", 0, 0), ("네이버 애드포스트", 0, 0)):
            for i in range(5):
                day = EVENING - timedelta(days=i)
                if i < found_days:
                    t = self.store.add_task(platform=name, title=f"t{i}", reward=reward, minutes=20, status="new", now=day)
                    self.store.complete(t["id"], actual_reward=reward, actual_minutes=20, now=day)
                self.store.record_check(name, "found" if i < found_days else "none", now=day)
        prio = money.learned_priority(list(self.perf().values()), self.config)
        self.assertTrue(prio["ready"])
        self.assertEqual(prio["order"], ["오베이", "패널나우", "헤이폴", "네이버 애드포스트"])  # 동점(0원)은 기본 순서
        self.assertEqual(prio["basis"]["오베이"], 720)  # 3,600원 / 확인 5회

    def test_10_default_order_until_all_have_enough(self) -> None:
        self.seed_panelnow()  # 패널나우만 10회
        prio = money.learned_priority(list(self.perf().values()), self.config)
        self.assertFalse(prio["ready"])
        self.assertEqual(prio["order"], ["패널나우", "오베이", "헤이폴", "네이버 애드포스트"])
        self.assertEqual(prio["progress"]["오베이"], (0, money.MIN_CHECKS_FOR_LEARNED_PRIORITY))

    def test_min_checks_is_configurable(self) -> None:
        path = self.dir / "money_config.json"
        path.write_text('{"learning": {"min_checks_for_priority": 1, "min_samples_for_hourly": 1}}', encoding="utf-8")
        c = money.load_config(path)
        self.assertEqual((c["learning"]["min_checks_for_priority"], c["learning"]["recent_days"]), (1, 7))
        for name in ("패널나우", "오베이", "헤이폴", "네이버 애드포스트"):
            self.store.record_check(name, "none", now=EVENING)
        perf = money.performance(self.store.tasks(), [], self.store.checks(), c)
        self.assertTrue(money.learned_priority(perf, c)["ready"])

    def test_11_calibrated_hourly(self) -> None:
        self.seed_panelnow()  # 4건, 평균 예상 2550 -> 실제 2341
        self.store.add_task(platform="패널나우", title="새 설문", reward=1000, minutes=20, status="new", now=EVENING)
        row = [r for r in money.open_tasks(self.store.tasks(), self.config, EVENING, statuses=("new",), log=self.store.log()) if r["title"] == "새 설문"][0]
        self.assertEqual((row["estimated_hourly"], row["learned_hourly"], row["learned_basis"]), (3000, round(3000 * 2341 / 2550), 4))

    def test_quick_complete_is_counted_but_not_in_estimate_learning(self) -> None:
        e = self.store.quick_complete(platform="오베이", actual_reward="1,200원", actual_minutes="20분", now=EVENING)
        self.assertEqual((e["kind"], e["estimated_reward"], e["actual_hourly"]), ("task", None, 3600))
        t = self.store.task(e["task_id"])
        self.assertEqual((t["status"], t["source"], t["estimate_known"], t["title"]), ("done", "quick_done", False, "오베이 작업"))
        p = self.perf()["오베이"]
        self.assertEqual((p["registered"], p["completed"], p["earned"], p["hourly_samples"], p["avg_estimated_hourly"]), (1, 1, 1200, 0, None))
        self.assertEqual(money.goal_status(money.period_stats(self.store.log(), self.config, EVENING)["total"]["earned"], self.config)["current"], 1200)
        stats = {s["platform"]: s for s in money.platform_stats(self.store.log(), self.config)}["오베이"]
        self.assertEqual((stats["earned"], stats["estimated_hourly"], stats["hourly_gap_pct"]), (1200, None, None))

    def test_gap_is_like_for_like_even_with_quick_records(self) -> None:
        """빠른 수익 기록(예상 없음)이 섞여도 '예상 대비'는 예상을 알던 완료끼리만 비교한다(화면 두 곳의 숫자가 같아야 함)."""
        t = self.store.add_task(platform="오베이", title="a", reward=1200, minutes=15, status="new", now=EVENING)
        self.store.complete(t["id"], actual_reward=1200, actual_minutes=20, now=EVENING)  # 4800 -> 3600 (-25%)
        self.store.quick_complete(platform="오베이", actual_reward=3000, actual_minutes=10, now=EVENING)  # 18000원/시간, 예상 없음
        stats = {x["platform"]: x for x in money.platform_stats(self.store.log(), self.config)}["오베이"]
        cal = {c["platform"]: c for c in money.calibration(self.store.log(), self.config)}["오베이"]
        self.assertEqual((stats["hourly_gap_pct"], cal["gap_pct"]), (-25.0, -25.0))
        self.assertEqual(stats["actual_hourly"], 8400)  # 전체 실제 시급은 모든 기록(4,200원 / 30분)

    def test_19_invalid_quick_complete(self) -> None:
        for kw, code in (({"platform": "없는곳"}, "PLATFORM_UNKNOWN"), ({"platform": ""}, "PLATFORM_REQUIRED"), ({"actual_reward": "-1"}, "REWARD_INVALID"),
                         ({"actual_reward": "abc"}, "REWARD_INVALID"), ({"actual_minutes": "0"}, "MINUTES_INVALID"), ({"actual_minutes": ""}, "MINUTES_INVALID")):
            with self.subTest(kw), self.assertRaises(MoneyError) as ctx:
                self.store.quick_complete(**{"platform": "오베이", "actual_reward": "1200", "actual_minutes": "20", **kw})
            self.assertEqual(ctx.exception.code, code)
        self.assertEqual((self.store.tasks(), self.store.log()), ([], []))


class SummaryTests(PerfCase):
    def test_12_13_goal_and_recent_seven_days(self) -> None:
        r = money.recent_stats([], self.config, EVENING)
        self.assertEqual((r["sufficient"], r["avg_daily_earned"], r["eta_days"]), (False, None, None))
        self.seed_panelnow()  # 최근 7일(9/21~9/27) 안의 완료: 9/21~9/23 (3건, 2,400원, 62분)
        r = money.recent_stats(self.store.log(), self.config, EVENING)
        self.assertEqual((r["entries"], r["earned"], r["sufficient"], r["avg_daily_earned"], r["avg_daily_minutes"]), (3, 2400, True, 343, 8.9))
        self.assertEqual(r["eta_days"], -(-(10000 - 3200) // 343))
        g = money.goal_status(3200, self.config)
        self.assertEqual((g["current"], g["remaining"], g["first_progress"]), (3200, 6800, 32.0))

    def test_14_15_weekly_and_daily_summary(self) -> None:
        self.seed_panelnow()
        self.store.record_check("오베이", "none", now=EVENING)
        week = money.activity_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, "week", EVENING)
        self.assertEqual(week["start"], "2026-09-21T00:00:00+09:00")
        self.assertEqual((week["checks"], week["found"], week["opportunities"], week["completed"], week["earned"], week["minutes"]), (8, 3, 3, 3, 2400, 62))
        self.assertEqual(week["checked_platforms"], ["패널나우", "오베이"])
        self.assertEqual(week["by_platform"], [{"platform": "패널나우", "earned": 2400, "checks": 7, "completed": 3},
                                               {"platform": "오베이", "earned": 0, "checks": 1, "completed": 0}])
        day = money.activity_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, "today", EVENING)
        self.assertEqual((day["checks"], day["opportunities"], day["completed"], day["earned"], day["unchecked_platforms"]),
                         (2, 0, 0, 0, ["헤이폴", "네이버 애드포스트"]))

    def test_18_kst_date_boundary(self) -> None:
        late = datetime(2026, 9, 27, 23, 59, tzinfo=KST)
        self.store.record_check("패널나우", "none", now=late)
        e = self.store.quick_complete(platform="오베이", actual_reward=500, actual_minutes=10, now=late)
        self.assertEqual(e["completed_at"], "2026-09-27T23:59:00+09:00")
        today = money.activity_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, "today", late)
        tomorrow = money.activity_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, "today", late + timedelta(minutes=2))
        self.assertEqual((today["checks"], today["earned"]), (2, 500))
        self.assertEqual((tomorrow["checks"], tomorrow["earned"]), (0, 0))
        # 월요일 00:00 KST = 새 주
        monday = datetime(2026, 9, 28, 0, 1, tzinfo=KST)
        self.assertEqual(money.activity_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, "week", monday)["earned"], 0)
        self.assertEqual(money.today_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, monday)["checked"], 0)

    def test_17_empty_data(self) -> None:
        self.assertTrue(all(p["checks"] == 0 and p["discovery_rate"] is None for p in money.performance([], [], [], self.config)))
        self.assertEqual(money.timeline([], [], [], self.config), [])
        day = money.activity_summary([], [], [], self.config, "today", EVENING)
        self.assertEqual((day["checks"], day["earned"], day["hourly"], day["by_platform"]), (0, 0, None, []))
        self.assertFalse(money.learned_priority(money.performance([], [], [], self.config), self.config)["ready"])

    def test_operating_timeline(self) -> None:
        self.store.record_check("패널나우", "none", now=EVENING)
        self.store.record_check("오베이", "found", now=EVENING + timedelta(minutes=1))
        o = self.store.add_task(platform="오베이", title="쇼핑 조사", reward=1200, minutes=20, status="new", now=EVENING + timedelta(minutes=2))
        self.store.accept(o["id"], now=EVENING + timedelta(minutes=3))
        self.store.complete(o["id"], actual_reward=1200, actual_minutes=20, now=EVENING + timedelta(minutes=30))
        days = money.timeline(self.store.tasks(), self.store.log(), self.store.checks(), self.config)
        self.assertEqual(len(days), 1)
        self.assertEqual([(e["type"], e["platform"]) for e in days[0]["events"]],
                         [("check_none", "패널나우"), ("check_found", "오베이"), ("registered", "오베이"), ("accepted", "오베이"), ("completed", "오베이")])
        done = days[0]["events"][-1]
        self.assertEqual((done["earned"], done["minutes"], done["estimated_reward"], done["cumulative"], done["time"]), (1200, 20, 1200, 1200, "20:30"))

    def test_operator_row_shows_recent_hourly_only_when_sufficient(self) -> None:
        from content_engine.operator_summary import OperatorInputs, build_operator_summary

        s = money.operator_status([], [], self.config, EVENING, checks=[])
        self.assertIsNone(s["recent_hourly"])
        self.assertNotIn("최근", build_operator_summary(OperatorInputs(generated_at="t", money=s)).money.why)
        self.seed_panelnow()
        s = money.operator_status(self.store.tasks(), self.store.log(), self.config, EVENING, checks=self.store.checks())
        self.assertIn("최근 7일 실제 시급 2,323원", build_operator_summary(OperatorInputs(generated_at="t", money=s)).money.why)


class PerformanceHttpTests(PerfCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        self.real = {p: (p.exists(), hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
                     for p in (ROOT / "data" / f"money_{n}.json" for n in ("tasks", "log", "checks", "config"))}
        cfg = DashboardConfig(daily_pack_path=self.dir / "d.json", answers_path=self.dir / "a.json", knowledge_path=self.dir / "k.json",
                              skipped_path=self.dir / "s.json", sessions_path=self.dir / "ss.json", media_archive_path=self.dir / "archive.json",
                              money_tasks_path=self.dir / "money_tasks.json", money_log_path=self.dir / "money_log.json",
                              money_config_path=self.dir / "money_config.json")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(cfg))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))

    def tearDown(self) -> None:
        super().tearDown()
        # 16: 테스트는 임시 폴더만 쓴다 - 실제 data/money_*.json(있다면)은 그대로
        self.assertEqual(self.real, {p: (p.exists(), hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) for p in self.real})

    def req(self, path: str, form: dict | None = None) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data), timeout=30) as r:
                return r.status, r.geturl(), r.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, path, error.read().decode("utf-8")

    def test_empty_state_says_data_is_insufficient(self) -> None:
        _, _, home = self.req("/money")
        for t in ("📊 오늘의 MONEY 활동", "최근 7일 평균: 데이터 부족", "추천 확인 순서: <b>데이터 수집 중</b>", "패널나우 0/5", "확인 기록 없음 · 데이터 수집 중",
                  "💵 빠른 수익 기록"):
            self.assertIn(t, home)
        self.assertNotIn("오늘 추천 확인 순서</b>", home)
        _, _, log = self.req("/money/log")
        for t in ("📅 이번 주 MONEY summary", "📊 플랫폼별 — 확인 대비 성과", "발견률", "완료율", "수익 발생률", "🧭 첫 10,000원까지의 운영 로그", "아직 기록이 없습니다"):
            self.assertIn(t, log)
        _, _, plats = self.req("/money/platforms")
        self.assertIn("데이터 수집 중 (0/5)", plats)
        self.assertIn("데이터 부족 0/3건", plats)

    def test_quick_done_flow_and_pages_with_data(self) -> None:
        _, url, html = self.req("/money/quick-done", {"platform": "오베이", "actual_reward": "1200", "actual_minutes": "20", "title": ""})
        self.assertIn("notice=done", url)
        for t in ("오베이 완료 · 오베이 작업 → 실제 <b>1,200원</b> / 20분 · 누적 <b>1,200원</b>", "3,600원/시간"):
            self.assertIn(t, html)
        _, _, home = self.req("/money")
        self.assertIn("현재: <b>1,200원", home)
        self.assertIn("오늘 한 일 1개", home)
        self.assertIn("확인 1회 · 발견률 100% · 실제 시급 3,600원/시간 · 데이터 수집 중(1/5)", home)
        status, _, html = self.req("/money/quick-done", {"platform": "오베이", "actual_reward": "abc", "actual_minutes": "20"})
        self.assertEqual(status, 400)
        self.assertIn("보상은 0 이상의 숫자", html)
        self.assertIn('<details class="card" style="max-width:none" open><summary><b>💵 빠른 수익 기록', html)


if __name__ == "__main__":
    unittest.main()
