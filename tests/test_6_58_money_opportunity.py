"""6-58 MONEY 기회 운영 - 빠른 등록 파서, 기회 -> 작업 -> 완료, 오늘의 루틴/확인 기록, 추천 행동, 정렬/필터, 화면.
모든 데이터는 임시 폴더(실제 data/는 건드리지 않음)."""

from __future__ import annotations

import json
import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

from content_engine import money
from content_engine.money import MoneyError, parse_opportunity, quick_parse
from tests.test_6_57_money import KST, NOW, MoneyCase


class ParserTests(MoneyCase):
    def p(self, text: str) -> dict:
        return parse_opportunity(text, self.config)

    def test_1_2_3_spec_examples(self) -> None:
        for text, expected in (("패널나우 20분 850P 일반인 의견 조사", ("패널나우", "일반인 의견 조사", 850, 20, 2550, "YELLOW", "시간 여유 있을 때")),
                               ("오베이 15분 1200원 쇼핑 조사", ("오베이", "쇼핑 조사", 1200, 15, 4800, "GREEN", "지금 확인")),
                               ("헤이폴 10분 450P 설문", ("헤이폴", "설문", 450, 10, 2700, "YELLOW", "시간 여유 있을 때"))):
            with self.subTest(text):
                d = self.p(text)
                self.assertEqual((d["platform"], d["title"], d["reward"], d["minutes"], d["estimated_hourly"], d["grade"], d["recommended"]), expected)
                self.assertEqual(d["missing"], [])
                self.assertEqual(quick_parse(text, self.config)["estimated_hourly"], expected[4])

    def test_4_time_strings(self) -> None:
        for text, minutes in (("패널나우 20분 850P", 20), ("패널나우 약 20분 850P", 20), ("패널나우 20분 내외 850P", 20),
                              ("패널나우 15~20분 850P", 20), ("패널나우 15-20분 850P", 20), ("패널나우 1시간 850P", 60),
                              ("패널나우 1시간 30분 850P", 90), ("panelnow 25min 850P", 25), ("패널나우 소요시간: 12분 850P", 12)):
            with self.subTest(text):
                self.assertEqual(self.p(text)["minutes"], minutes)

    def test_5_6_point_and_won_strings(self) -> None:
        for text, reward in (("패널나우 20분 850P", 850), ("패널나우 20분 850 P", 850), ("패널나우 20분 850p", 850), ("패널나우 20분 850 포인트", 850),
                             ("패널나우 20분 1,200원", 1200), ("오베이 15분 1200원", 1200), ("오베이 15분 보상: 1,500", 1500),
                             ("오베이 15분 3000 points", 3000)):
            with self.subTest(text):
                self.assertEqual(self.p(text)["reward"], reward)

    def test_7_title_extraction(self) -> None:
        for text, title in (("패널나우 20분 850P 일반인 의견 조사", "일반인 의견 조사"), ("[오베이] 소비자 설문 · 소요시간 15~20분 · 보상 1,500원", "소비자 설문"),
                            ("패널나우\n일반인 의견 조사\n약 20분\n850P", "일반인 의견 조사"), ("헤이폴 10분 450P", "헤이폴 작업")):
            with self.subTest(text):
                self.assertEqual(self.p(text)["title"], title)

    def test_8_9_hourly_grade_and_recommendation_follow_settings(self) -> None:
        self.assertEqual({g: money.recommend(g) for g in money.GRADES},
                         {"GREEN": "지금 확인", "YELLOW": "시간 여유 있을 때", "ORANGE": "다른 작업 없을 때", "RED": "보류"})
        for text, g in (("오베이 10분 500원", "GREEN"), ("오베이 10분 400원", "YELLOW"), ("오베이 10분 250원", "ORANGE"), ("오베이 10분 100원", "RED")):
            with self.subTest(text):
                self.assertEqual(self.p(text)["grade"], g)
        path = self.dir / "money_config.json"
        money.save_config(path, [10000], {"green": 5000, "yellow": 4000, "orange": 1000})
        stricter = money.load_config(path)
        d = parse_opportunity("오베이 15분 1200원", stricter)  # 4,800원: 기준을 올리면 GREEN -> YELLOW
        self.assertEqual((d["grade"], d["recommended"]), ("YELLOW", "시간 여유 있을 때"))

    def test_17_bad_quick_input(self) -> None:
        for text, missing in (("패널나우 850P", ["minutes"]), ("모르는곳 10분 100P", ["platform"]), ("패널나우 20분", ["reward"]),
                              ("", ["platform", "minutes", "reward"]), ("패널나우 0분 850P", ["minutes"]), ("패널나우 20분 -850P", [])):
            with self.subTest(text):
                d = self.p(text)
                if text == "패널나우 20분 -850P":  # 음수 부호는 보상으로 읽지 않는다(850으로만 읽음)
                    self.assertEqual(d["reward"], 850)
                    continue
                self.assertEqual(d["missing"], missing)
                with self.assertRaises(MoneyError):
                    quick_parse(text, self.config)
        self.assertLessEqual(len(self.p("패널나우 20분 850P " + "가" * 5000)["title"]), money.MAX_TEXT["title"])


class OpportunityTests(MoneyCase):
    def opp(self, **kw) -> dict:
        base = {"platform": "패널나우", "title": "일반인 의견 조사", "reward": 850, "minutes": 20, "status": "new", "source": "quick"}
        return self.store.add_task(**{**base, **kw})

    def test_10_register_opportunity(self) -> None:
        o = self.opp(deadline="2026-09-28T18:00", now=NOW)
        self.assertEqual((o["status"], o["source"], o["accepted_at"], o["url"]), ("new", "quick", None, "https://www.panelnow.co.kr/"))
        rows = money.open_tasks(self.store.tasks(), self.config, NOW, statuses=("new",))
        self.assertEqual((rows[0]["estimated_hourly"], rows[0]["grade"], rows[0]["recommended"]), (2550, "YELLOW", "시간 여유 있을 때"))
        self.assertEqual(money.open_tasks(self.store.tasks(), self.config, NOW), [])  # 기회는 '할 작업' 목록에 섞이지 않는다

    def test_11_opportunity_to_task_to_log(self) -> None:
        o = self.opp()
        t = self.store.accept(o["id"], now=NOW)
        self.assertEqual((t["status"], t["accepted_at"] is not None), ("open", True))
        with self.assertRaises(MoneyError) as ctx:
            self.store.accept(o["id"])
        self.assertEqual(ctx.exception.code, "NOT_AN_OPPORTUNITY")
        e = self.store.complete(o["id"], actual_reward=800, actual_minutes=24, now=NOW)
        self.assertEqual((e["estimated_hourly"], e["actual_hourly"]), (2550, 2000))
        self.assertEqual(self.store.task(o["id"])["status"], "done")

    def test_complete_directly_from_opportunity(self) -> None:
        o = self.opp()
        self.store.complete(o["id"], actual_reward=850, actual_minutes=20, now=NOW)
        t = self.store.task(o["id"])
        self.assertEqual((t["status"], t["accepted_at"]), ("done", t["closed_at"]))

    def test_15_opportunity_expiry(self) -> None:
        self.opp(title="마감 지남", reward=5000, deadline="2026-09-27T11:00")
        self.opp(title="여유", reward=100, deadline="2026-09-30T11:00")
        rows = money.open_tasks(self.store.tasks(), self.config, NOW, statuses=("new",))
        self.assertEqual([(r["title"], r["expired"]) for r in rows], [("여유", False), ("마감 지남", True)])
        self.assertEqual(money.operator_status(self.store.tasks(), [], self.config, NOW)["opportunities"], 1)

    def test_16_duplicate_opportunity_blocked(self) -> None:
        self.opp()
        for kw in ({}, {"title": " 일반인  의견조사 "}, {"status": "open", "dedupe": True}):  # 화면 등록은 항상 dedupe
            with self.subTest(kw), self.assertRaises(MoneyError) as ctx:
                self.opp(**kw)
            self.assertEqual(ctx.exception.code, "DUPLICATE_OPPORTUNITY")
        self.opp(reward=900)  # 보상이 다르면 다른 기회
        o = self.store.tasks()[0]
        self.store.skip(o["id"])
        self.opp()  # 닫힌 뒤에는 같은 기회를 다시 등록할 수 있다
        self.assertEqual(len(self.store.tasks()), 3)

    def test_sort_and_filter_options(self) -> None:
        self.opp(platform="헤이폴", title="b", reward=100, now=NOW - timedelta(minutes=3))
        self.opp(platform="오베이", title="a", reward=2000, now=NOW - timedelta(minutes=2))
        self.opp(platform="패널나우", title="c", reward=700, now=NOW - timedelta(minutes=1), deadline="2026-09-27T13:00")
        ids = lambda sort: [r["title"] for r in money.open_tasks(self.store.tasks(), self.config, NOW, sort=sort, statuses=("new",))]  # noqa: E731
        self.assertEqual(ids("hourly"), ["a", "c", "b"])
        self.assertEqual(ids("deadline"), ["c", "b", "a"])
        self.assertEqual(ids("new"), ["c", "a", "b"])
        self.assertEqual(ids("platform"), ["a", "c", "b"])  # 오베이 < 패널나우 < 헤이폴
        self.assertEqual(ids("grade"), ["a", "c", "b"])

    def test_learned_hourly_uses_my_platform_history(self) -> None:
        # 6-59: 보정은 표본(learning.min_samples_for_hourly=3)이 모일 때만 - 1건일 때는 "데이터 부족"(learned_hourly None)
        for i in range(3):
            done = self.opp(title=f"지난 설문 {i}")
            self.store.complete(done["id"], actual_reward=850, actual_minutes=25, now=NOW)  # 예상 2550 -> 실제 2040(-20%)
            if i == 0:
                self.opp(title="새 설문", reward=1000, minutes=20)
                row = money.open_tasks(self.store.tasks(), self.config, NOW, statuses=("new",), log=self.store.log())[0]
                self.assertEqual((row["learned_hourly"], row["learned_basis"], row["learned_needed"]), (None, 1, 3))
        row = money.open_tasks(self.store.tasks(), self.config, NOW, statuses=("new",), log=self.store.log())[0]
        self.assertEqual((row["estimated_hourly"], row["platform_actual_hourly"], row["platform_gap_pct"], row["learned_hourly"]), (3000, 2040, -20.0, 2400))


class RoutineTests(MoneyCase):
    def test_12_13_14_check_status_per_platform(self) -> None:
        rows = {r["name"]: r for r in money.routine([], [], [], self.config, NOW)}
        self.assertEqual(set(rows), {"패널나우", "오베이", "헤이폴", "네이버 애드포스트", "기타"})
        self.assertFalse(any(r["checked_today"] for r in rows.values()))
        self.store.record_check("패널나우", "none", now=NOW - timedelta(hours=1))
        self.store.record_check("오베이", "found", now=NOW)
        self.store.record_check("헤이폴", "none", now=NOW - timedelta(days=1))  # 어제
        rows = {r["name"]: r for r in money.routine(self.store.tasks(), [], self.store.checks(), self.config, NOW)}
        self.assertEqual((rows["패널나우"]["checked_today"], rows["패널나우"]["today_outcome"], rows["패널나우"]["no_task_count"]), (True, "none", 1))
        self.assertEqual((rows["오베이"]["checked_today"], rows["오베이"]["today_outcome"]), (True, "found"))
        self.assertEqual((rows["헤이폴"]["checked_today"], rows["헤이폴"]["check_count"]), (False, 1))
        s = money.today_summary(self.store.tasks(), [], self.store.checks(), self.config, NOW)
        self.assertEqual((s["platforms"], s["checked"], s["unchecked"]), (4, 2, ["헤이폴", "네이버 애드포스트"]))
        self.assertEqual(json.loads((self.dir / "money_checks.json").read_text(encoding="utf-8"))[0]["outcome"], "none")
        self.assertEqual(self.store.log(), [])  # 확인 기록은 수익과 별개

    def test_registering_counts_as_checked_today(self) -> None:
        self.store.add_task(platform="헤이폴", title="x", reward=450, minutes=10, status="new", now=NOW)
        rows = {r["name"]: r for r in money.routine(self.store.tasks(), [], [], self.config, NOW)}
        self.assertEqual((rows["헤이폴"]["checked_today"], rows["헤이폴"]["today_outcome"], rows["헤이폴"]["found_count"]), (True, "found", 1))
        s = money.today_summary(self.store.tasks(), [], [], self.config, NOW)
        self.assertEqual(s["found_today"], 1)

    def test_invalid_check(self) -> None:
        for platform, outcome, code in (("없는곳", "none", "PLATFORM_UNKNOWN"), ("패널나우", "maybe", "STATUS_INVALID")):
            with self.subTest(platform), self.assertRaises(MoneyError) as ctx:
                self.store.record_check(platform, outcome)
            self.assertEqual(ctx.exception.code, code)

    def test_platform_metadata_and_notes(self) -> None:
        p = money.platform_info(self.config, "네이버 애드포스트")
        self.assertEqual((p["kind"], p["active"]), ("content", True))
        for key in ("name", "kind", "url", "description", "active", "notification_available"):
            self.assertIn(key, money.platform_info(self.config, "패널나우"))
        path = self.dir / "money_config.json"
        money.save_platform_note(path, "패널나우", "알림 오면 30분 안에")
        c = money.load_config(path)
        self.assertEqual(money.routine([], [], [], c, NOW)[0]["note"], "알림 오면 30분 안에")
        with self.assertRaises(MoneyError):
            money.save_platform_note(path, "없는곳", "x")

    def test_operator_status_counts_unchecked(self) -> None:
        self.store.record_check("패널나우", "none", now=NOW)
        s = money.operator_status([], [], self.config, NOW, checks=self.store.checks())
        self.assertEqual((s["unchecked_platforms"], s["routine_platforms"], s["opportunities"]), (3, 4, 0))
        from content_engine.operator_summary import OperatorInputs, build_operator_summary

        row = build_operator_summary(OperatorInputs(generated_at="t", money=s)).money
        self.assertIn("새 기회 0건 · 오늘 미확인 플랫폼 3/4곳", row.why)
        self.assertIn("확인하세요", row.action)


class OpportunityHttpTests(MoneyCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        cfg = DashboardConfig(daily_pack_path=self.dir / "d.json", answers_path=self.dir / "a.json", knowledge_path=self.dir / "k.json",
                              skipped_path=self.dir / "s.json", sessions_path=self.dir / "ss.json", media_archive_path=self.dir / "archive.json",
                              money_tasks_path=self.dir / "money_tasks.json", money_log_path=self.dir / "money_log.json",
                              money_config_path=self.dir / "money_config.json")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(cfg))
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

    def test_home_order_and_routine(self) -> None:
        _, _, html = self.req("/money")
        order = ["① 오늘의 수익", "🎯 첫 10,000원까지", "🔥 오늘의 MONEY ROUTINE", "④ 지금 확인할 플랫폼 <span", "<h2>⚡ 빠른 등록", "<h2>💡 수익 기회",
                 "<h2>🔥 지금 할 만한 온라인 작업", "<h2>📒 최근 수익 기록"]
        positions = [html.index(t) for t in order]
        self.assertEqual(positions, sorted(positions))
        for t in ("오늘 확인할 곳 (0/4)", "□ 패널나우", "□ 네이버 애드포스트", "○ 오늘 미확인", "확인하기 ↗", "오늘 발견한 기회 <b>0건", "하루 사용법"):
            self.assertIn(t, html)
        links = re.findall(r'<a class="btn[^"]*" href="([^"]+)" target="_blank" rel="noopener noreferrer">확인하기', html)
        self.assertEqual(links, ["https://www.panelnow.co.kr/", "https://ovey.io/", "https://www.heypoll.co.kr/", "https://adpost.naver.com/"])
        _, url, html = self.req("/money/check", {"platform": "패널나우", "outcome": "none"})
        self.assertIn("notice=checked", url)
        self.assertIn("● 오늘 확인함 · 작업 없음", html)
        self.assertIn("오늘 확인할 곳 (1/4)", html)
        self.assertIn("다시 확인 ↗", html)
        _, url, html = self.req("/money/check", {"platform": "오베이", "outcome": "found"})
        self.assertIn('value="오베이 "', html)  # 빠른 등록 칸에 플랫폼 이름을 미리 채움
        self.assertEqual(self.req("/money/check", {"platform": "<script>", "outcome": "none"})[0], 400)

    def test_quick_confirm_then_opportunity_accept_complete(self) -> None:
        status, _, html = self.req("/money/quick", {"text": "오베이 15분 1200원 쇼핑 조사"})
        self.assertEqual((status, self.store.tasks()), (200, []))
        for t in ("등록 전 확인", "4,800원", "지금 확인", "💡 기회로 저장", "🔥 바로 할 작업으로 등록", 'value="쇼핑 조사"'):
            self.assertIn(t, html)
        form = {"platform": "오베이", "title": "쇼핑 조사", "reward": "1200", "minutes": "15", "source": "quick", "status": "new",
                "url": "", "memo": "", "deadline": ""}
        _, url, html = self.req("/money/tasks", form)
        self.assertIn("notice=opportunity", url)
        self.assertIn("할래요", html)
        status, _, html = self.req("/money/tasks", form)  # 같은 기회 다시
        self.assertEqual(status, 400)
        self.assertIn("이미 목록에 있습니다", html)
        self.assertIn('value="쇼핑 조사"', html)  # 확인 화면으로 돌아가 값 유지
        tid = self.store.tasks()[0]["id"]
        _, url, _ = self.req(f"/money/task/{tid}/accept", {})
        self.assertIn("notice=accepted", url)
        self.assertEqual(self.store.task(tid)["status"], "open")
        _, url, html = self.req(f"/money/task/{tid}/complete", {"actual_reward": "1200", "actual_minutes": "20", "memo": ""})
        self.assertIn("(예상 대비 -25.0%)", html)
        _, _, html = self.req("/money")
        self.assertIn("현재: <b>1,200원", html)
        self.assertIn("오늘 완료한 작업 <b>1건", html)

    def test_capture_text_flow(self) -> None:
        _, _, html = self.req("/money/capture")
        self.assertIn("외부 OCR을 부르지 않습니다", html)
        status, _, html = self.req("/money/quick", {"text": "패널나우\n일반인 의견 조사\n약 20분\n850P"})
        self.assertEqual(status, 200)
        self.assertIn('name="source" value="ocr"', html)
        self.assertIn("2,550원", html)

    def test_18_xss_and_bad_urls(self) -> None:
        status, _, html = self.req("/money/quick", {"text": "패널나우 20분 850P <script>alert(1)</script>"})
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.store.add_task(platform="패널나우", title='<img src=x onerror=alert(1)>', reward=850, minutes=20, status="new")
        _, _, html = self.req("/money")
        self.assertNotIn("<img src=x", html)
        for url in ("javascript:alert(1)", "data:text/html,<b>x</b>", "https://a.b/\"onmouseover=\"x", "//evil.example"):
            with self.subTest(url):
                status, _, _ = self.req("/money/tasks", {"platform": "패널나우", "title": "t", "reward": "1", "minutes": "1", "url": url, "status": "open"})
                self.assertEqual(status, 400)
        status, _, _ = self.req("/money/platforms/note", {"platform": "패널나우", "note": "<b>메모</b>"})
        _, _, html = self.req("/money/platforms")
        self.assertIn("&lt;b&gt;메모&lt;/b&gt;", html)
        self.assertEqual(self.req("/money/tasks", {"platform": "패널나우", "title": "t", "reward": "1", "minutes": "1", "status": "done"})[0], 400)

    def test_platform_directory_page(self) -> None:
        _, _, html = self.req("/money/platforms")
        for t in ("💰 수익 플랫폼", "패널나우", "설문", "네이버 애드포스트", "콘텐츠 수익", "공식 사이트 ↗", "누적 수익", "실제 시급", "최근 확인",
                  "확인 / 작업 없음", "알림 여부 미확인", "메모 저장"):
            self.assertIn(t, html)
        self.assertNotIn("<script", html.lower().replace("<script>", ""))

    def test_no_fake_data_on_empty_start(self) -> None:
        for path in ("/money", "/money/platforms", "/money/log"):
            self.req(path)
        self.assertEqual([p.name for p in self.dir.glob("money_*.json")], [])


if __name__ == "__main__":
    unittest.main()
