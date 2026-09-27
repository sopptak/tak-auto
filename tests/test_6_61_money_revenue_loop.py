"""6-61 MONEY 실제 수익 루프 - TODAY MONEY, 첫 10,000원(실제만), 2칸 완료 기록, TOP 3, 에이전트 실행기(가짜 실행기로), 대체 경로, 예약 명령.
실제 claude/Chrome은 부르지 않는다(runner 주입). 모든 데이터는 임시 폴더."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from content_engine import money, money_scout, money_scout_agent
from content_engine.money_scout_adapters import parse_panelnow
from tests.test_6_57_money import KST, MoneyCase
from tests.test_6_60_money_scout import HEYPOLL, PANELNOW, PANELNOW_LOGGED_OUT

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 27, 15, 0, tzinfo=KST)


def fake_runner(stdout: str = "", returncode: int = 0, exc: Exception | None = None, seen: dict | None = None):
    def run(cmd, **kw):
        if seen is not None:
            seen.update(cmd=cmd, input=kw.get("input"))
        if exc:
            raise exc
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    return run


def agent_json(text: str) -> str:
    return "읽었습니다.\n" + json.dumps({"platforms": [{"platform": "panelnow", "page_url": "https://www.panelnow.co.kr/survey",
                                                        "observed_at": "2026-09-27T06:00:00Z", "page_text": text}]}, ensure_ascii=False)


class LoopCase(MoneyCase):
    def setUp(self) -> None:
        super().setUp()
        self.staging = self.dir / "money_scout_staging.json"

    def scout(self, text=PANELNOW, **kw) -> dict:
        return money_scout_agent.run_scout(tasks_path=self.dir / "money_tasks.json", staging_path=self.staging, now=NOW,
                                           claude="claude", runner=fake_runner(agent_json(text)), **kw)


class AgentRunnerTests(LoopCase):
    def test_11_agent_result_ingested(self) -> None:
        seen = {}
        run = money_scout_agent.run_scout(tasks_path=self.dir / "money_tasks.json", staging_path=self.staging, now=NOW, claude="claude",
                                          runner=fake_runner(agent_json(PANELNOW), seen=seen))
        self.assertEqual((run["platforms"]["panelnow"]["status"], run["promotion"]["created"], run["overall"]), ("SUCCESS", 5, "PARTIAL_SUCCESS"))
        self.assertEqual(run["platforms"]["panelnow"]["observed_at"], "2026-09-27T06:00:00Z")
        # 읽기 도구만 허용, 지시는 표준입력(Windows claude.CMD 인자 잘림 회피), 방문 목록은 plan()이 허용한 곳뿐
        allowed = seen["cmd"][seen["cmd"].index("--allowedTools") + 1].split(",")
        self.assertEqual(set(allowed), set(money_scout_agent.AGENT_TOOLS))
        for forbidden in ("computer", "form_input", "javascript", "find", "Bash", "Write", "upload"):
            self.assertFalse(any(forbidden in t for t in allowed), forbidden)
        self.assertIn("--chrome", seen["cmd"])
        self.assertNotIn(seen["input"], seen["cmd"])
        self.assertIn("https://www.panelnow.co.kr/survey", seen["input"])
        self.assertNotIn("heypoll.co.kr", seen["input"])
        self.assertIn("절대 금지: 클릭, 입력, 로그인", seen["input"])

    def test_logged_out_visitor_sample_is_not_promoted(self) -> None:
        run = self.scout(PANELNOW_LOGGED_OUT)
        self.assertEqual((run["platforms"]["panelnow"]["status"], run["overall"], self.store.tasks()), ("LOGIN_REQUIRED", "FAILED", []))
        self.assertTrue(parse_panelnow({"page_text": PANELNOW_LOGGED_OUT})["detail"].startswith("로그아웃 상태"))

    def test_12_agent_unavailable_timeout_failure(self) -> None:
        cases = [(dict(claude=None, runner=fake_runner()), "AGENT_UNAVAILABLE"),
                 (dict(claude="claude", runner=fake_runner(exc=FileNotFoundError())), "AGENT_UNAVAILABLE"),
                 (dict(claude="claude", runner=fake_runner(exc=subprocess.TimeoutExpired("claude", 1))), "TIMEOUT"),
                 (dict(claude="claude", runner=fake_runner(returncode=1)), "AGENT_FAILED"),
                 (dict(claude="claude", runner=fake_runner("주소를 알려 주세요")), "PARSE_FAILED"),
                 (dict(claude="claude", runner=fake_runner('{"platforms": [{"platform": "heypoll", "page_text": "x"}]}')), "PARSE_FAILED")]
        import shutil
        from unittest import mock

        for kw, status in cases:
            with self.subTest(status=status), mock.patch.object(shutil, "which", return_value=None):
                raw = money_scout_agent.run_agent(**kw)
                entry = next(p for p in raw["platforms"] if p["platform"] == "panelnow")
                self.assertEqual(entry["status"], status)
                self.assertEqual({p["platform"]: p["status"] for p in raw["platforms"] if p["platform"] != "panelnow"},
                                 {"ovey": "APP_ONLY", "heypoll": "BLOCKED_TERMS", "adpost": "BROWSER_RESTRICTED"})
        self.assertEqual(self.store.tasks(), [])

    def test_13_no_official_api_is_recorded_not_invented(self) -> None:
        self.assertEqual({p["platform"]: p["official_api"] for p in money_scout.plan()},
                         {"panelnow": None, "ovey": None, "heypoll": None, "adpost": None})
        self.assertEqual(money_scout.STATUS_TEXT["API_UNAVAILABLE"], "공식 API 없음")
        src = (ROOT / "content_engine" / "money_scout_agent.py").read_text(encoding="utf-8") + (ROOT / "content_engine" / "money_scout.py").read_text(encoding="utf-8")
        for mod in ("import requests", "urllib.request", "http.client", "import socket"):
            self.assertNotIn(mod, src)

    def test_14_manual_fallback_heypoll_text(self) -> None:
        run = money_scout.ingest({"mode": "manual", "platforms": [{"platform": "heypoll", "page_text": HEYPOLL["page_text"]}]},
                                 tasks_path=self.dir / "money_tasks.json", staging_path=self.staging, now=NOW)
        self.assertEqual(run["platforms"]["heypoll"]["status"], "SUCCESS")
        titles = sorted(t["title"] for t in self.store.tasks())
        self.assertEqual(titles, ["주류 관련 소비자 의견 조사(KR-09-Oww)", "치킨 브랜드 관련 인식 조사"])
        again = money_scout.ingest({"mode": "manual", "platforms": [{"platform": "heypoll", "page_text": HEYPOLL["page_text"]}]},
                                   tasks_path=self.dir / "money_tasks.json", staging_path=self.staging, now=NOW + timedelta(hours=1))
        self.assertEqual((again["promotion"]["created"], len(self.store.tasks())), (0, 2))  # 번호 없어도 제목+보상으로 중복 방지

    def test_15_schedule_command_is_printed_not_registered(self) -> None:
        cmd = money_scout_agent.schtasks_command("08:30")
        self.assertTrue(cmd.startswith('schtasks /Create /SC DAILY /ST 08:30 /TN "TAK AUTO MONEY Scout"'))
        self.assertIn("money_scout.py", cmd)
        self.assertTrue(cmd.rstrip().endswith('run"'))
        src = (ROOT / "content_engine" / "money_scout_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("schtasks /Create", src.split("def schtasks_command")[0])  # 등록 명령을 실행하는 코드 없음


class RevenueLoopTests(LoopCase):
    def test_1_2_today_money_separates_expected_and_actual(self) -> None:
        tm = money_scout.today_money([], [], self.config, NOW)
        self.assertEqual((tm["found_today"], tm["now"], tm["expected_krw"], tm["actual_today"], tm["goal"]["current"], tm["goal"]["first_progress"]),
                         (0, 0, 0, 0, 0, 0.0))
        self.scout()
        tm = money_scout.today_money(self.store.tasks(), self.store.log(), self.config, NOW)
        self.assertEqual((tm["found_today"], tm["now"], tm["later"], tm["hold"]), (5, 1, 3, 1))
        self.assertEqual(tm["expected_krw"], 100 + 450 + 670 + 850)  # 🔥+🟡만
        self.assertEqual((tm["actual_today"], tm["goal"]["current"]), (0, 0))  # 예상은 목표에 안 들어감

    def test_3_4_5_6_actual_reward_minutes_hourly_and_goal(self) -> None:
        self.scout()
        tid = next(t["id"] for t in self.store.tasks() if t["external_id"] == "r23710")
        money_scout.record_choice(self.store, tid, "DO", now=NOW)
        e = self.store.complete(tid, actual_reward="500", actual_minutes="10", now=NOW + timedelta(minutes=12))
        self.assertEqual((e["actual_reward"], e["actual_minutes"], e["actual_hourly"]), (500, 10, 3000))
        self.assertEqual((e["estimated_reward"], e["estimated_hourly"]), (670, 2680))  # 8: 예상/실제 분리
        tm = money_scout.today_money(self.store.tasks(), self.store.log(), self.config, NOW + timedelta(minutes=13))
        self.assertEqual((tm["actual_today"], tm["actual_month"], tm["goal"]["current"], tm["goal"]["first_progress"]), (500, 500, 500, 5.0))

    def test_7_duplicate_completion_protection(self) -> None:
        self.scout()
        tid = self.store.tasks()[0]["id"]
        self.store.complete(tid, actual_reward=100, actual_minutes=1, now=NOW)
        with self.assertRaises(money.MoneyError) as ctx:
            self.store.complete(tid, actual_reward=100, actual_minutes=1, now=NOW)
        self.assertEqual(ctx.exception.code, "ALREADY_COMPLETED")
        self.scout()  # 다시 스카우트해도 완료된 것은 새로 생기거나 바뀌지 않는다
        self.assertEqual(len(self.store.log()), 1)
        self.assertEqual(sum(t["status"] == "done" for t in self.store.tasks()), 1)

    def test_9_calibration_lowers_priority_after_enough_bad_samples(self) -> None:
        self.scout()
        for i in range(3):  # 예상 2,680원인데 실제 1,200원 수준이 반복 -> 보정 후 🟡에서 ⚪로
            t = self.store.add_task(platform="패널나우", title=f"지난 조사 {i}", reward=670, minutes=15, status="new", now=NOW - timedelta(days=i + 1))
            self.store.complete(t["id"], actual_reward=670, actual_minutes=34, now=NOW - timedelta(days=i + 1))
        groups = money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW)
        r = next(t for g in groups.values() for t in g if t.get("external_id") == "r23710")
        self.assertEqual(r["bucket"], "HOLD")
        self.assertIn("내 기록 보정", r["reason"])

    def test_10_top3_order(self) -> None:
        self.scout()
        self.store.add_task(platform="패널나우", title="직접 등록한 빠른 설문", reward=900, minutes=10, status="new", now=NOW)  # 5,400원
        top = money_scout.top_picks(money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW))
        self.assertEqual([t["title"][:12] for t in top], ["★ 수요 득템 퀴즈 1", "직접 등록한 빠른 설문", "글로벌 파트너사 조사"])
        self.assertEqual(len(money_scout.top_picks(money_scout.buckets([], [], self.config, NOW))), 0)

    def test_17_existing_flow_regression(self) -> None:
        self.scout()
        rows = money.open_tasks(self.store.tasks(), self.config, NOW, statuses=("new",), log=self.store.log())
        self.assertEqual(len(rows), 5)
        money.timeline(self.store.tasks(), self.store.log(), self.store.checks(), self.config)
        money.performance(self.store.tasks(), self.store.log(), self.store.checks(), self.config)
        money.activity_summary(self.store.tasks(), self.store.log(), self.store.checks(), self.config, "week", NOW)


class LoopHttpTests(LoopCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        self.real = {p: (p.exists(), hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
                     for p in (ROOT / "data" / f"money_{n}.json" for n in ("tasks", "log", "checks", "config", "scout_staging"))}
        self.cfg = DashboardConfig(daily_pack_path=self.dir / "d.json", answers_path=self.dir / "a.json", knowledge_path=self.dir / "k.json",
                                   skipped_path=self.dir / "s.json", sessions_path=self.dir / "ss.json", media_archive_path=self.dir / "archive.json",
                                   money_tasks_path=self.dir / "money_tasks.json", money_log_path=self.dir / "money_log.json",
                                   money_config_path=self.dir / "money_config.json")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(self.cfg))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda s=self.server: (s.shutdown(), s.server_close(), thread.join(5)))

    def tearDown(self) -> None:
        super().tearDown()
        self.assertEqual(self.real, {p: (p.exists(), hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) for p in self.real})  # 16

    def req(self, path: str, form: dict | None = None) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data), timeout=30) as r:
                return r.status, r.geturl(), r.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, path, error.read().decode("utf-8")

    def test_full_loop_over_http(self) -> None:
        _, _, home = self.req("/money")
        for t in ("💰 TODAY MONEY", "오늘 발견 <b>0건", "예상 수익 <b>0원", "오늘 실제 수익 <b>0원", "이번 달 실제 수익 <b>0원", "목표 <b>0 / 10,000원</b> (0%)",
                  "🔎 지금 수익기회 찾기"):
            self.assertIn(t, home)
        self.assertLess(home.index("💰 TODAY MONEY"), home.index("① 오늘의 수익"))
        _, url, _ = self.req("/money/scout/run", {})  # 에이전트 실행 꺼진 설정(기본) -> 요청만
        self.assertIn("notice=requested", url)
        self.req("/money/scout/manual", {"platform": "panelnow", "page_text": PANELNOW})
        _, _, scout = self.req("/money/scout")
        for t in ("💰 오늘의 수익기회", "[1]", "[2]", "[3]", "더 보기", "전체 5건"):
            self.assertIn(t, scout)
        self.assertNotIn("[4]", scout)
        tid = next(t["id"] for t in self.store.tasks() if t["external_id"] == "r23710")
        self.req("/money/scout/choice", {"task_id": tid, "choice": "DO"})
        _, _, form = self.req(f"/money/task/{tid}/complete")
        self.assertEqual(len(__import__("re").findall(r'<input type="text" name="actual_', form)), 2)  # 금액·시간 두 칸
        self.assertIn("실제 받은 금액 (원)", form)
        _, url, _ = self.req(f"/money/task/{tid}/complete", {"actual_reward": "500", "actual_minutes": "10"})
        self.assertIn("/money/log", url)
        _, _, home = self.req("/money")
        for t in ("오늘 실제 수익 <b>500원", "목표 <b>500 / 10,000원</b> (5%)"):
            self.assertIn(t, home)

    def test_run_button_starts_agent_in_background_when_enabled(self) -> None:
        from unittest import mock

        from scripts import money_web

        import dataclasses

        from scripts.run_scout_dashboard import make_handler_class

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(dataclasses.replace(self.cfg, money_scout_agent_enabled=True)))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda s=self.server: (s.shutdown(), s.server_close()))
        started = threading.Event()

        def fake_run_scout(**kw):
            started.set()
            return money_scout.ingest({"mode": "agent", "request_id": kw["request_id"],
                                       "platforms": [{"platform": "panelnow", "page_url": "https://www.panelnow.co.kr/survey", "page_text": PANELNOW}]},
                                      tasks_path=kw["tasks_path"], staging_path=kw["staging_path"])

        with mock.patch.object(money_scout_agent, "run_scout", fake_run_scout):
            _, url, html = self.req("/money/scout/run", {})
            self.assertIn("notice=running", url)
            self.assertTrue(started.wait(10))
            for _ in range(50):
                if money_scout.load_staging(self.staging)["requests"][-1]["status"] == "done":
                    break
                time.sleep(0.1)
        self.assertEqual(money_scout.load_staging(self.staging)["requests"][-1]["status"], "done")
        self.assertEqual(len(self.store.tasks()), 5)
        self.assertTrue(money_web._RUN_LOCK.acquire(blocking=False))
        money_web._RUN_LOCK.release()


if __name__ == "__main__":
    unittest.main()
