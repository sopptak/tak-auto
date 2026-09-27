"""6-57 TAK AUTO MONEY - 계산/저장/통계/목표/화면/Operator 연결. 모든 데이터는 임시 폴더(실제 data/는 건드리지 않음)."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from content_engine import money
from content_engine.money import MoneyError, MoneyStore, goal_status, grade, hourly, load_config, period_stats, platform_stats

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=KST)  # 일요일 - 이번 주 = 9/21(월)~


class MoneyCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.config = load_config(None)
        self.store = MoneyStore(self.dir / "money_tasks.json", self.dir / "money_log.json", self.config)

    def add(self, reward=850, minutes=20, platform="패널나우", **kw) -> dict:
        return self.store.add_task(platform=platform, title=kw.pop("title", "일반인 의견 조사"), reward=reward, minutes=minutes, **kw)

    def done(self, at: datetime, reward=800, minutes=24, platform="패널나우") -> dict:
        task = self.add(platform=platform)
        return self.store.complete(task["id"], actual_reward=reward, actual_minutes=minutes, now=at)


class CalculationTests(MoneyCase):
    def test_01_hourly_850_20(self) -> None:
        self.assertEqual(hourly(850, 20), 2550)
        self.assertIsNone(hourly(850, 0))

    def test_02_05_grades(self) -> None:
        t = self.config["thresholds"]
        self.assertEqual([grade(v, t) for v in (3000, 2999, 2500, 2000, 1999, 1500, 1000, 999, 500, None)],
                         ["GREEN", "YELLOW", "YELLOW", "YELLOW", "ORANGE", "ORANGE", "ORANGE", "RED", "RED", "RED"])

    def test_thresholds_and_goals_are_config_not_code(self) -> None:
        path = self.dir / "money_config.json"
        path.write_text(json.dumps({"goals": [50000, 10000], "thresholds": {"green": 5000}}), encoding="utf-8")
        c = load_config(path)
        self.assertEqual(grade(4000, c["thresholds"]), "YELLOW")
        self.assertEqual(goal_status(0, c)["first_goal"], 10000)
        money.save_config(path, [100000], {"green": 4000, "yellow": 3000, "orange": 500})
        self.assertEqual(load_config(path)["goals"], [100000])
        for goals, th in (([0], {"green": 1, "yellow": 1, "orange": 1}), ([10], {"green": 1, "yellow": 2, "orange": 0}), (["x"], None)):
            with self.subTest(goals=goals, th=th), self.assertRaises(MoneyError):
                money.save_config(path, goals, th or {"green": 3, "yellow": 2, "orange": 1})

    def test_quick_parse(self) -> None:
        r = money.quick_parse("패널나우 20분 850P", self.config)
        self.assertEqual((r["platform"], r["minutes"], r["reward"], r["estimated_hourly"], r["grade"]), ("패널나우", 20, 850, 2550, "YELLOW"))
        r = money.quick_parse("heypoll 1시간 30분 3,000P 긴 설문", self.config)
        self.assertEqual((r["platform"], r["minutes"], r["reward"], r["title"]), ("헤이폴", 90, 3000, "긴 설문"))
        r = money.quick_parse("오베이 일반 설문 15분 500원", self.config)
        self.assertEqual((r["platform"], r["title"], r["estimated_hourly"]), ("오베이", "일반 설문", 2000))
        for bad in ("패널나우 850P", "모르는곳 10분 100P", "패널나우 20분", ""):
            with self.subTest(bad), self.assertRaises(MoneyError) as ctx:
                money.quick_parse(bad, self.config)
            self.assertEqual(ctx.exception.code, "QUICK_PARSE_FAILED")


class StoreTests(MoneyCase):
    def test_17_18_first_run_without_files(self) -> None:
        self.assertEqual((self.store.tasks(), self.store.log()), ([], []))
        s = period_stats([], self.config, NOW)
        self.assertEqual((s["today"]["earned"], s["total"]["minutes"], s["total"]["hourly"]), (0, 0, None))
        self.assertEqual(money.open_tasks([], self.config), [])
        self.assertFalse((self.dir / "money_tasks.json").exists())  # 읽기만으로 파일을 만들지 않는다

    def test_06_register_task(self) -> None:
        t = self.add(url="", memo="메모", deadline="2026-09-28T18:00")
        self.assertEqual((t["platform"], t["reward"], t["minutes"], t["status"], t["url"]), ("패널나우", 850, 20, "open", "https://www.panelnow.co.kr/"))
        self.assertEqual(t["deadline"], "2026-09-28T18:00+09:00")
        for key in ("id", "title", "created_at", "point_value"):
            self.assertIn(key, t)
        row = money.open_tasks(self.store.tasks(), self.config, NOW)[0]
        self.assertEqual((row["estimated_hourly"], row["grade"], row["expired"]), (2550, "YELLOW", False))

    def test_07_08_09_15_complete_keeps_estimate_and_actual_separately(self) -> None:
        t = self.add()
        e = self.store.complete(t["id"], actual_reward="800", actual_minutes="24분", memo="생각보다 길었음", now=NOW)
        self.assertEqual((e["estimated_reward"], e["estimated_minutes"], e["estimated_hourly"]), (850, 20, 2550))
        self.assertEqual((e["actual_reward"], e["actual_minutes"], e["actual_hourly"]), (800, 24, 2000))
        stored = self.store.task(t["id"])
        self.assertEqual((stored["reward"], stored["minutes"], stored["status"]), (850, 20, "done"))  # 예상값은 덮어쓰지 않는다
        self.assertEqual(self.store.log()[0]["task_id"], t["id"])

    def test_19_complete_unknown_task(self) -> None:
        with self.assertRaises(MoneyError) as ctx:
            self.store.complete("task-nope", actual_reward=1, actual_minutes=1)
        self.assertEqual(ctx.exception.code, "TASK_NOT_FOUND")

    def test_20_duplicate_completion_blocked(self) -> None:
        t = self.add()
        self.store.complete(t["id"], actual_reward=800, actual_minutes=24)
        with self.assertRaises(MoneyError) as ctx:
            self.store.complete(t["id"], actual_reward=800, actual_minutes=24)
        self.assertEqual(ctx.exception.code, "ALREADY_COMPLETED")
        self.assertEqual(len(self.store.log()), 1)
        with self.assertRaises(MoneyError):
            self.store.skip(t["id"])

    def test_duplicate_blocked_even_if_task_file_was_not_updated(self) -> None:
        t = self.add()
        self.store.complete(t["id"], actual_reward=800, actual_minutes=24)
        tasks = self.store.tasks()
        tasks[0]["status"] = "open"  # 로그 기록 후 작업 파일 쓰기 전에 끊긴 상황
        (self.dir / "money_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        with self.assertRaises(MoneyError) as ctx:
            self.store.complete(t["id"], actual_reward=800, actual_minutes=24)
        self.assertEqual(ctx.exception.code, "ALREADY_COMPLETED")

    def test_16_invalid_input(self) -> None:
        cases = [({"reward": "-5"}, "REWARD_INVALID"), ({"reward": "abc"}, "REWARD_INVALID"), ({"reward": "99999999999"}, "REWARD_INVALID"),
                 ({"minutes": "0"}, "MINUTES_INVALID"), ({"minutes": "-3"}, "MINUTES_INVALID"), ({"minutes": "2000"}, "MINUTES_INVALID"),
                 ({"platform": ""}, "PLATFORM_REQUIRED"), ({"title": " "}, "TITLE_REQUIRED"), ({"title": "가" * 200}, "TEXT_TOO_LONG"),
                 ({"url": "javascript:alert(1)"}, "URL_INVALID"), ({"url": "ftp://x.y"}, "URL_INVALID"), ({"url": 'https://a.b/"><script>'}, "URL_INVALID"),
                 ({"deadline": "내일"}, "DEADLINE_INVALID")]
        for kw, code in cases:
            with self.subTest(kw), self.assertRaises(MoneyError) as ctx:
                self.add(**kw)
            self.assertEqual(ctx.exception.code, code)
        t = self.add()
        for kw, code in (({"actual_reward": "-1", "actual_minutes": "5"}, "REWARD_INVALID"), ({"actual_reward": "1", "actual_minutes": "0"}, "MINUTES_INVALID")):
            with self.subTest(kw), self.assertRaises(MoneyError) as ctx:
                self.store.complete(t["id"], **kw)
            self.assertEqual(ctx.exception.code, code)
        self.assertEqual(self.store.log(), [])
        self.assertEqual(self.store.task(t["id"])["status"], "open")

    def test_corrupted_file_is_reported_not_overwritten(self) -> None:
        (self.dir / "money_log.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(MoneyError) as ctx:
            self.store.log()
        self.assertEqual(ctx.exception.code, "DATA_UNREADABLE")
        with self.assertRaises(MoneyError):
            self.store.complete(self.add()["id"], actual_reward=1, actual_minutes=1)
        self.assertEqual((self.dir / "money_log.json").read_text(encoding="utf-8"), "{broken")

    def test_skip_and_deadline_expiry(self) -> None:
        a = self.add(title="마감 지난 작업", reward=5000, deadline="2026-09-27T11:00")
        b = self.add(title="느긋한 작업", reward=100, deadline="2026-09-30T11:00")
        rows = money.open_tasks(self.store.tasks(), self.config, NOW)
        self.assertEqual([r["title"] for r in rows], ["느긋한 작업", "마감 지난 작업"])  # 마감 지난 것은 시급이 높아도 뒤로
        self.assertTrue(rows[1]["expired"])
        self.store.skip(b["id"])
        self.assertEqual([r["id"] for r in money.open_tasks(self.store.tasks(), self.config, NOW)], [a["id"]])
        self.assertEqual(self.store.task(b["id"])["status"], "skipped")

    def test_sorting(self) -> None:
        self.add(title="낮음", reward=100, now=NOW - timedelta(minutes=5))
        self.add(title="높음", reward=2000, now=NOW)
        self.assertEqual([r["title"] for r in money.open_tasks(self.store.tasks(), self.config, NOW)], ["높음", "낮음"])
        self.assertEqual(money.open_tasks(self.store.tasks(), self.config, NOW, sort="new")[0]["title"], "높음")


class StatsTests(MoneyCase):
    def test_10_13_periods(self) -> None:
        self.done(NOW - timedelta(hours=1), 800, 24)            # 오늘
        self.done(datetime(2026, 9, 22, 9, tzinfo=KST), 1200, 30)  # 이번 주(월)
        self.done(datetime(2026, 9, 2, 9, tzinfo=KST), 600, 12)    # 이번 달
        self.done(datetime(2026, 8, 31, 23, tzinfo=KST), 400, 10)  # 지난 달
        self.done(datetime(2026, 9, 26, 15, 30, tzinfo=timezone.utc), 300, 6)  # UTC 9/26 15:30 = KST 9/27 00:30 -> 오늘
        s = period_stats(self.store.log(), self.config, NOW)
        self.assertEqual({k: s[k]["earned"] for k in s}, {"today": 1100, "week": 2300, "month": 2900, "total": 3300})
        self.assertEqual({k: s[k]["minutes"] for k in s}, {"today": 30, "week": 60, "month": 72, "total": 82})
        self.assertEqual(s["today"]["hourly"], hourly(1100, 30))
        self.assertEqual(s["total"]["hourly"], hourly(3300, 82))

    def test_14_first_goal(self) -> None:
        g = goal_status(0, self.config)
        self.assertEqual((g["first_goal"], g["current"], g["remaining"], g["first_progress"], g["first_achieved"]), (10000, 0, 10000, 0.0, False))
        g = goal_status(2550, self.config)
        self.assertEqual((g["remaining"], g["first_progress"]), (7450, 25.5))
        g = goal_status(10000, self.config)
        self.assertEqual((g["first_achieved"], g["target"], g["remaining"]), (True, 100000, 90000))
        self.assertEqual(goal_status(2_000_000, self.config)["all_achieved"], True)

    def test_income_without_task_counts_money_not_hourly(self) -> None:
        self.done(NOW, 800, 24)
        e = self.store.record_income(platform="네이버 애드포스트", amount="5,000원", minutes="", title="9월 정산", now=NOW)
        self.assertEqual((e["kind"], e["task_id"], e["actual_minutes"], e["actual_hourly"]), ("income", None, 0, None))
        s = period_stats(self.store.log(), self.config, NOW)
        self.assertEqual((s["today"]["earned"], s["today"]["hourly"]), (5800, 2000))  # 시간 없는 정산이 시급을 부풀리지 않음

    def test_platform_stats_and_estimate_gap(self) -> None:
        self.done(NOW, 800, 24)                       # 예상 2550, 실제 2000
        self.done(NOW, 900, 20, platform="오베이")     # 예상 2550, 실제 2700
        stats = {p["platform"]: p for p in platform_stats(self.store.log(), self.config)}
        self.assertEqual(set(stats), {"패널나우", "오베이", "헤이폴", "네이버 애드포스트", "기타"})
        p = stats["패널나우"]
        self.assertEqual((p["earned"], p["minutes"], p["actual_hourly"], p["estimated_hourly"], p["hourly_gap_pct"]), (800, 24, 2000, 2550, -21.6))
        self.assertEqual((stats["오베이"]["actual_hourly"], stats["헤이폴"]["earned"], stats["헤이폴"]["actual_hourly"]), (2700, 0, None))

    def test_operator_status(self) -> None:
        self.add()
        self.done(NOW, 800, 24)
        s = money.operator_status(self.store.tasks(), self.store.log(), self.config, NOW)
        self.assertEqual((s["today"], s["open_tasks"], s["first_goal"], s["first_goal_progress"]), (800, 1, 10000, 8.0))


class OperatorRowTests(unittest.TestCase):
    def test_money_row(self) -> None:
        from content_engine.operator_summary import OperatorInputs, build_operator_summary

        empty = build_operator_summary(OperatorInputs(generated_at="t"))
        self.assertEqual((empty.money.label, empty.money.status), ("MONEY", "NOT_PRESENT"))
        m = {"today": 800, "month": 800, "total": 800, "open_tasks": 2, "first_goal": 10000, "first_goal_progress": 8.0, "first_achieved": False}
        row = build_operator_summary(OperatorInputs(generated_at="t", money=m)).money
        self.assertEqual((row.status, row.count, row.detail_route), ("IN_PROGRESS", 2, "/money"))
        self.assertIn("오늘 800원 · 이번 달 800원 · 열린 작업 2건 · 첫 목표(10,000원) 8%", row.why)
        self.assertEqual(build_operator_summary(OperatorInputs(generated_at="t", money=m)).to_dict()["money"]["status"], "IN_PROGRESS")


class MoneyHttpTests(MoneyCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        self.cfg = DashboardConfig(
            daily_pack_path=self.dir / "d.json", answers_path=self.dir / "a.json", knowledge_path=self.dir / "k.json",
            skipped_path=self.dir / "s.json", sessions_path=self.dir / "ss.json", media_archive_path=self.dir / "archive.json",
            money_tasks_path=self.dir / "money_tasks.json", money_log_path=self.dir / "money_log.json",
            money_config_path=self.dir / "money_config.json")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(self.cfg))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))

    def req(self, path: str, form: dict | None = None) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data), timeout=30) as r:
                return r.status, r.geturl(), r.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, path, error.read().decode("utf-8")

    def test_empty_home_log_settings(self) -> None:
        for path, texts in (("/money", ("💰 TAK AUTO MONEY", "온라인 수익 노가다 관제판", "🎯 첫 10,000원까지", "첫 온라인 수익 목표", "10,000원", "남은 금액: <b>10,000원", "진행률: <b>0%",
                                         "오늘 수익", "누적 투자시간", "이번 달 실제 시간당 수익", "🔥 지금 할 만한 온라인 작업", "빠른 등록",
                                         "https://www.panelnow.co.kr/", "https://ovey.io/", "https://www.heypoll.co.kr/", "https://adpost.naver.com/")),
                            ("/money/log", ("📊 플랫폼별", "패널나우", "헤이폴", "아직 기록이 없습니다")),
                            ("/money/settings", ("목표 금액", "10000, 100000, 1000000"))):
            status, _, html = self.req(path)
            self.assertEqual(status, 200, path)
            for t in texts:
                with self.subTest(path=path, text=t):
                    self.assertIn(t, html)
        self.assertFalse((self.dir / "money_tasks.json").exists())

    def test_full_flow_over_http(self) -> None:
        status, _, html = self.req("/money/quick", {"text": "패널나우 20분 850P 일반인 의견 조사"})
        self.assertEqual((status, self.store.tasks()), (200, []))  # 6-58: 확인 화면만, 아직 저장 안 됨
        self.assertIn("등록 전 확인", html)
        _, url, html = self.req("/money/tasks", {"platform": "패널나우", "title": "일반인 의견 조사", "reward": "850", "minutes": "20",
                                                  "source": "quick", "status": "open", "url": "", "memo": "", "deadline": ""})
        self.assertIn("notice=added", url)
        for t in ("일반인 의견 조사", "예상시간 20분", "예상보상 850원", "2,550원", 'target="_blank" rel="noopener noreferrer"', "완료 기록"):
            self.assertIn(t, html)
        task = self.store.tasks()[0]
        status, _, html = self.req(f"/money/task/{task['id']}/complete")
        self.assertIn("예상: 850원 / 20분", html)
        _, url, html = self.req(f"/money/task/{task['id']}/complete", {"actual_reward": "800", "actual_minutes": "24", "memo": ""})
        self.assertIn("/money/log", url)
        for t in ("예상: 850원 / 20분 (2,550원/시간)", "실제: <b>800원 / 24분", "실제 시급: <b>2,000원/시간", "-21.6%"):
            self.assertIn(t, html)
        status, _, html = self.req(f"/money/task/{task['id']}/complete", {"actual_reward": "800", "actual_minutes": "24"})
        self.assertEqual(status, 409)
        self.assertIn("중복 기록 방지", html)
        _, _, html = self.req("/money")
        self.assertIn("현재: <b>800원", html)
        self.assertIn("남은 금액: <b>9,200원", html)
        self.assertEqual(len(self.store.log()), 1)

    def test_form_errors_keep_input_and_explain(self) -> None:
        status, _, html = self.req("/money/quick", {"text": "패널나우 850P"})
        self.assertEqual(status, 200)
        self.assertIn("패널나우 850P", html)  # 입력 원문 유지
        self.assertIn("읽지 못한 값: 시간", html)
        self.assertEqual(self.store.tasks(), [])
        status, _, html = self.req("/money/quick", {"text": "  "})
        self.assertEqual(status, 400)
        self.assertIn("예: 패널나우 20분 850P", html)
        status, _, html = self.req("/money/tasks", {"platform": "패널나우", "title": "x", "reward": "850", "minutes": "20", "url": "javascript:alert(1)"})
        self.assertEqual(status, 400)
        self.assertIn("http://", html)
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(self.req("/money/task/task-nope/complete")[0], 404)
        self.assertEqual(self.req("/money/task/..%2F..%2Fx/complete")[0], 404)

    def test_goal_reached_banner_and_settings(self) -> None:
        t = self.add()
        self.store.complete(t["id"], actual_reward=12000, actual_minutes=60)
        _, _, html = self.req("/money")
        self.assertIn("🎉 첫 10,000원 달성", html)
        self.assertIn("다음 목표 <b>100,000원", html)
        _, url, _ = self.req("/money/settings", {"goals": "20000, 100000", "green": "3500", "yellow": "2000", "orange": "1000"})
        self.assertIn("notice=saved", url)
        _, _, html = self.req("/money")
        self.assertIn("20,000원", html)
        status, _, _ = self.req("/money/settings", {"goals": "abc", "green": "1", "yellow": "2", "orange": "3"})
        self.assertEqual(status, 400)

    def test_no_credential_or_automation_inputs(self) -> None:
        import re

        _, _, html = self.req("/money")
        names = " ".join(re.findall(r'name="([^"]*)"', html)).lower()
        for word in ("password", "passwd", "token", "cookie", "otp", "인증", "phone", "email", "birth", "주민"):
            with self.subTest(word):
                self.assertNotIn(word, names)
        src = (Path(__file__).resolve().parents[1] / "content_engine" / "money.py").read_text(encoding="utf-8")
        for mod in ("import requests", "urllib.request", "http.client", "import socket", "selenium", "playwright"):
            self.assertNotIn(mod, src)

    def test_operator_center_shows_money(self) -> None:
        _, _, html = self.req("/operator")
        self.assertIn("<h2>MONEY</h2>", html)
        self.assertIn("첫 목표(10,000원) 0%", html)


if __name__ == "__main__":
    unittest.main()
