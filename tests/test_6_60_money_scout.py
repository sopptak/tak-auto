"""6-60 MONEY Browser Scout - 어댑터(실제 화면 캡처 fixture), 정규화, 중복 병합, 사라짐, 실패 격리, 개인정보, staging, 승격, 우선순위, 화면.
fixture 출처: tests/fixtures/money_scout/ (2026-09-27 로그인하지 않은 공개 화면, 개인정보 없음). AdPost는 실제 화면을 읽지 못해 합성 글자로만 시험한다.
모든 데이터는 임시 폴더."""

from __future__ import annotations

import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from content_engine import money, money_scout
from content_engine.money_scout_adapters import parse_adpost, parse_heypoll, parse_ovey, parse_panelnow
from tests.test_6_57_money import KST, MoneyCase

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "money_scout"
NOW = datetime(2026, 9, 27, 14, 30, tzinfo=KST)
PANELNOW_LOGGED_OUT = (FIX / "panelnow_survey.txt").read_text(encoding="utf-8")
# 6-61: 위 실제 캡처는 로그아웃 화면이고 그 목록은 비회원용 예시(번역 문구 고정)였다 -> LOGIN_REQUIRED.
# 목록 구조 해석 시험에는 같은 목록에서 로그아웃 메뉴(로그인/회원가입)만 뺀 변형을 쓴다. 실제 로그인 화면 구조는 아직 미검증.
PANELNOW = PANELNOW_LOGGED_OUT.replace("로그인\n회원가입\n", "내 활동\n", 1)
HEYPOLL = json.loads((FIX / "heypoll_home_links.json").read_text(encoding="utf-8"))
OVEY = (FIX / "ovey_home.txt").read_text(encoding="utf-8")
ADPOST_SYNTHETIC = "애드포스트 수입 현황\n이번 달 수입\n1,234원\n누적 수입\n56,780원\n지급 예정 금액\n50,000원\n공지 10월 지급일 안내"


def raw(*platforms, mode="agent") -> dict:
    return {"mode": mode, "agent": "test", "platforms": list(platforms)}


def pn(text=PANELNOW) -> dict:
    return {"platform": "panelnow", "page_url": "https://www.panelnow.co.kr/survey", "page_text": text}


class AdapterTests(unittest.TestCase):
    def test_1_panelnow_real_capture(self) -> None:
        out = parse_panelnow({"page_text": PANELNOW_LOGGED_OUT, "page_url": "https://www.panelnow.co.kr/survey"})
        self.assertEqual((out["status"], out["items"]), ("LOGIN_REQUIRED", []))  # 비회원 예시 목록은 기회가 아니다
        self.assertIn("비회원용 예시", out["detail"])
        r = parse_panelnow({"page_text": PANELNOW, "page_url": "https://www.panelnow.co.kr/survey"})
        self.assertEqual(r["status"], "SUCCESS")
        got = {i["external_id"]: (i["title"], i["category"], i["time_text"], i["reward_text"]) for i in r["items"]}
        self.assertEqual(got["r23710"], ("쇼핑 관련 조사", "일반 조사", "15분", "670P"))
        self.assertEqual(got["r42345"], ("일반인 의견 조사", "일반 조사", "20분", "850P"))
        self.assertEqual(got["p022"][2:], ("약5분", "문항당 1P"))
        self.assertEqual(len(r["items"]), 6)
        self.assertTrue(next(i for i in r["items"] if i["external_id"] == "b33291")["first_come"])
        self.assertEqual(next(i for i in r["items"] if i["external_id"] == "a34038")["notes"], ["추후 적립"])

    def test_2_ovey_is_app_only(self) -> None:
        self.assertEqual(parse_ovey({"page_text": OVEY})["status"], "APP_ONLY")
        self.assertEqual(parse_ovey({"page_text": "완전히 다른 화면"})["status"], "PAGE_CHANGED")

    def test_3_heypoll_links(self) -> None:
        r = parse_heypoll(HEYPOLL)
        self.assertEqual(r["status"], "SUCCESS")
        by = {i["external_id"]: i for i in r["items"]}
        s = by["survey-715762"]
        self.assertEqual((s["title"], s["category"], s["reward_text"], s["time_text"], s["url"]),
                         ("주류 관련 소비자 의견 조사(KR-09-Oww)", "기타", "1,400P", "", "https://www.heypoll.co.kr/survey/surveys/715762"))
        q = by["quick_survey-716661"]
        self.assertEqual((q["type"], q["first_come"], q["reward_text"]), ("quick_survey", True, "50P"))
        self.assertEqual(by["poll-716551"]["type"], "poll")
        self.assertNotIn("shop", json.dumps(r["items"]))  # 포인트 상점 링크는 기회가 아니다

    def test_4_adpost_revenue_status(self) -> None:
        r = parse_adpost({"page_text": ADPOST_SYNTHETIC})
        self.assertEqual((r["status"], r["items"]), ("SUCCESS", []))
        self.assertEqual({k: r["asset_status"][k] for k in ("current_revenue", "total_revenue", "payable")},
                         {"current_revenue": 1234, "total_revenue": 56780, "payable": 50000})
        self.assertEqual(parse_adpost({"page_text": "네이버 로그인\n아이디\n비밀번호"})["status"], "LOGIN_REQUIRED")

    def test_12_13_login_and_captcha(self) -> None:
        self.assertEqual(parse_panelnow({"page_text": "설문조사\n로그인\n아이디\n비밀번호\n로그인 상태 유지"})["status"], "LOGIN_REQUIRED")
        self.assertEqual(parse_panelnow({"page_text": "잠시만요\n로봇이 아닙니다\n확인"})["status"], "CAPTCHA_REQUIRED")
        self.assertEqual(parse_panelnow({"page_text": PANELNOW})["status"], "SUCCESS")  # 푸터의 'reCAPTCHA 서비스' 안내는 CAPTCHA가 아니다
        self.assertEqual(parse_heypoll({"page_text": "자동입력 방지문자를 입력하세요", "links": HEYPOLL["links"]})["status"], "CAPTCHA_REQUIRED")

    def test_page_changed_is_not_guessed(self) -> None:
        changed = PANELNOW.replace("r42345", "설문-42345")
        self.assertEqual(parse_panelnow({"page_text": changed})["status"], "PAGE_CHANGED")
        self.assertEqual(parse_panelnow({"page_text": "새 디자인 화면"})["status"], "PAGE_CHANGED")


class NormalizeTests(unittest.TestCase):
    def n(self, **item) -> dict:
        base = {"external_id": "r1", "title": "쇼핑 관련 조사", "reward_text": "670P", "time_text": "15분", "url": "https://www.panelnow.co.kr/survey"}
        return money_scout.normalize_item(item.pop("platform", "panelnow"), {**base, **item}, run_id="run", collected_at="t")

    def test_5_6_7_reward_minutes_hourly(self) -> None:
        n = self.n()
        self.assertEqual((n["reward"], n["reward_unit"], n["reward_krw_estimate"], n["estimated_minutes"], n["hourly_rate"], n["confidence"], n["verdict"]),
                         (670, "P", 670, 15, 2680, 0.95, "promote"))
        self.assertEqual((self.n(reward_text="1,200원")["reward_unit"], self.n(reward_text="1,200원")["reward_krw_estimate"]), ("원", 1200))
        self.assertEqual(self.n(time_text="약5분")["estimated_minutes"], 5)
        no_time = self.n(time_text="")
        self.assertEqual((no_time["estimated_minutes"], no_time["hourly_rate"], no_time["confidence"]), (None, None, 0.8))  # 시간을 지어내지 않음
        per_q = self.n(reward_text="문항당 1P")
        self.assertEqual((per_q["reward"], per_q["verdict"]), (None, "review"))
        self.assertIsNone(self.n(reward_text="0~10,000P")["reward"])

    def test_unconfirmed_point_rate_gives_no_krw(self) -> None:
        h = self.n(platform="heypoll", reward_text="1,400P", time_text="")
        self.assertEqual((h["reward"], h["reward_krw_estimate"], h["hourly_rate"]), (1400, None, None))
        self.assertIn("포인트→원 환산이 확인되지 않아 원화·시급을 만들지 않음", h["issues"])

    def test_8_fingerprint(self) -> None:
        a = money_scout.fingerprint("panelnow", "r1", "x", 1, 1, "")
        self.assertEqual(a, money_scout.fingerprint("panelnow", "r1", "다른 제목", 999, 5, "https://x"))  # 번호가 있으면 번호가 기준
        self.assertNotEqual(a, money_scout.fingerprint("heypoll", "r1", "x", 1, 1, ""))
        u1 = money_scout.fingerprint("p", None, "설문 A!", 100, 5, "https://a.com/s?id=3&utm_source=x")
        self.assertEqual(u1, money_scout.fingerprint("p", None, "설문a", 100, 5, "https://A.com/s?id=3#top"))
        self.assertEqual(money_scout.canonical_url("https://h.co/login?redirect-url=/x&id=1&fbclid=z"), "https://h.co/login?id=1")

    def test_16_privacy_filter(self) -> None:
        n = money_scout.normalize_item("panelnow", {"external_id": "r9", "title": "홍길동님 010-1234-5678 hong@test.com 조사", "reward_text": "500P",
                                                    "time_text": "10분", "answers": ["남", "30대"], "profile": {"income": 1}}, run_id="r", collected_at="t")
        self.assertNotIn("010-1234-5678", json.dumps(n, ensure_ascii=False))
        self.assertNotIn("hong@test.com", n["title"])
        self.assertNotIn("answers", n)
        self.assertNotIn("profile", n)
        self.assertEqual(n["confidence"], 0.75)
        self.assertIn("개인정보 모양 글자를 지움", n["issues"])


class PipelineTests(MoneyCase):
    def setUp(self) -> None:
        super().setUp()
        self.staging = self.dir / "money_scout_staging.json"

    def ingest(self, r, now=NOW, **kw) -> dict:
        return money_scout.ingest(r, tasks_path=self.dir / "money_tasks.json", staging_path=self.staging, now=now, **kw)

    def scout_tasks(self) -> list[dict]:
        return [t for t in self.store.tasks() if t.get("source") == "browser_scout"]

    def test_17_18_staging_and_promotion(self) -> None:
        run = self.ingest(raw(pn()))
        self.assertEqual((run["overall"], run["platforms"]["panelnow"]["status"], run["promotion"]["created"]), ("SUCCESS", "SUCCESS", 5))
        staging = json.loads(self.staging.read_text(encoding="utf-8"))
        self.assertEqual(len(staging["runs"]), 1)
        self.assertNotIn("page_text", json.dumps(staging, ensure_ascii=False))
        self.assertNotIn("기본조사에서는 회원님에 대해", json.dumps(staging, ensure_ascii=False))  # 화면 원문은 저장하지 않음
        self.assertEqual(staging["runs"][0]["platforms"]["panelnow"]["raw_text_sha256"], hashlib.sha256(PANELNOW.encode()).hexdigest())
        t = next(t for t in self.scout_tasks() if t["external_id"] == "r23710")
        self.assertEqual((t["status"], t["platform"], t["reward"], t["minutes"], t["point_value"], t["reward_unit"], t["scout_state"], t["confidence"]),
                         ("new", "패널나우", 670, 15, 1, "P", "active", 0.95))
        self.assertNotIn("p022", [t["external_id"] for t in self.scout_tasks()])  # 확인 필요(보상 모름)는 승격 안 함
        self.assertEqual(run["platforms"]["panelnow"]["review"], 1)

    def test_9_duplicate_run_updates_instead_of_adding(self) -> None:
        self.ingest(raw(pn()))
        run = self.ingest(raw(pn(PANELNOW.replace("670P", "700P"))), now=NOW + timedelta(hours=1))
        self.assertEqual(len(self.scout_tasks()), 5)
        self.assertEqual((run["promotion"]["created"], run["promotion"]["updated"], run["promotion"]["unchanged"]), (0, 1, 4))
        t = next(t for t in self.scout_tasks() if t["external_id"] == "r23710")
        self.assertEqual((t["reward"], t["last_seen_at"]), (700, (NOW + timedelta(hours=1)).isoformat(timespec="seconds")))

    def test_10_completed_record_is_never_overwritten(self) -> None:
        self.ingest(raw(pn()))
        t = next(t for t in self.scout_tasks() if t["external_id"] == "r23710")
        self.store.complete(t["id"], actual_reward=670, actual_minutes=18, now=NOW)
        before_log = self.store.log()
        self.ingest(raw(pn(PANELNOW.replace("670P", "999P"))), now=NOW + timedelta(hours=1))
        after = self.store.task(t["id"])
        self.assertEqual((after["status"], after["reward"], after["closed_at"]), ("done", 670, t["closed_at"] or after["closed_at"]))
        self.assertEqual(self.store.log(), before_log)
        self.assertEqual(before_log[0]["estimated_hourly"], 2680)

    def test_11_disappeared_is_not_completed(self) -> None:
        self.ingest(raw(pn()))
        fewer = PANELNOW.replace("일반 조사\n쇼핑 관련 조사", "일반 조사\n다른 조사").replace("r23710", "r99999")
        run = self.ingest(raw(pn(fewer)), now=NOW + timedelta(hours=2))
        gone = next(t for t in self.scout_tasks() if t["external_id"] == "r23710")
        self.assertEqual((gone["status"], gone["scout_state"], run["promotion"]["disappeared"]), ("new", "disappeared", 1))
        self.assertEqual(self.store.log(), [])
        # 로그인 실패한 실행은 '사라짐'을 만들지 않는다(못 본 것 ≠ 없는 것)
        self.ingest(raw({"platform": "panelnow", "status": "LOGIN_REQUIRED"}), now=NOW + timedelta(hours=3))
        self.assertEqual(sum(t["scout_state"] == "disappeared" for t in self.scout_tasks()), 1)

    def test_14_partial_failure_is_isolated(self) -> None:
        run = self.ingest(raw(pn(), {"platform": "ovey", "page_text": OVEY}, {"platform": "heypoll", "page_text": HEYPOLL["page_text"], "links": HEYPOLL["links"]},
                              {"platform": "adpost", "status": "BROWSER_RESTRICTED"}))
        self.assertEqual({k: v["status"] for k, v in run["platforms"].items()},
                         {"panelnow": "SUCCESS", "ovey": "APP_ONLY", "heypoll": "BLOCKED_TERMS", "adpost": "BROWSER_RESTRICTED"})
        self.assertEqual((run["overall"], run["promotion"]["created"]), ("PARTIAL_SUCCESS", 5))
        broken = self.ingest(raw({"platform": "panelnow", "page_text": 12345}))  # 잘못된 형식
        self.assertEqual((broken["overall"], len(self.scout_tasks())), ("INVALID", 5))

    def test_adapter_crash_only_fails_that_platform(self) -> None:
        from unittest import mock

        with mock.patch.dict(money_scout.ADAPTERS, {"adpost": lambda raw: 1 / 0}):
            run = self.ingest(raw(pn(), {"platform": "adpost", "page_text": ADPOST_SYNTHETIC}, mode="manual"))
        self.assertEqual((run["platforms"]["adpost"]["status"], run["platforms"]["panelnow"]["status"], run["overall"]),
                         ("PARSE_FAILED", "SUCCESS", "PARTIAL_SUCCESS"))

    def test_15_malformed_browser_data(self) -> None:
        for bad in (None, [], {"platforms": "x"}, {"platforms": [{"platform": "unknown"}]}, {"platforms": [{"platform": "panelnow", "links": "x"}]},
                    {"platforms": [{"platform": "panelnow", "status": "HACKED"}]}, {"mode": "robot", "platforms": []},
                    {"platforms": [{"platform": "panelnow", "page_text": "x" * (money_scout.MAX_TEXT_CHARS + 1)}]}):
            with self.subTest(bad=str(bad)[:40]):
                self.assertTrue(money_scout.validate_raw(bad))
        self.assertEqual(self.store.tasks(), [])

    def test_blocked_terms_only_processed_in_manual_mode(self) -> None:
        hp = {"platform": "heypoll", "page_text": HEYPOLL["page_text"], "links": HEYPOLL["links"]}
        self.assertEqual(self.ingest(raw(hp))["platforms"]["heypoll"]["found"], 0)
        manual = self.ingest(raw(hp, mode="manual"))
        self.assertEqual(manual["platforms"]["heypoll"]["status"], "SUCCESS")
        t = next(t for t in self.scout_tasks() if t["external_id"] == "survey-715762")
        self.assertEqual((t["reward"], t["minutes"], t["point_value"], t["reward_krw_estimate"]), (1400, None, None, None))

    def test_19_priority_buckets_and_fallback(self) -> None:
        self.ingest(raw(pn()))
        b = money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW)
        titles = {k: [t["external_id"] for t in v] for k, v in b.items()}
        self.assertEqual(titles["NOW"], ["b33291"])                     # 6,000원/시간(선착순)
        self.assertEqual(titles["LATER"], ["a34038", "r23710", "r42345"])  # 2,700 · 2,680 · 2,550
        self.assertEqual(titles["HOLD"], ["b36835"])                    # 1,000원/시간
        self.assertIn("예상 시급만(내 기록 부족)", b["LATER"][0]["reason"])
        self.ingest(raw({"platform": "heypoll", "links": HEYPOLL["links"], "page_text": ""}, mode="manual"))
        hold = money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW)["HOLD"]
        self.assertIn("소요시간 또는 원 환산 정보가 없어 시급을 모름", {t["reason"] for t in hold})

    def test_priority_uses_my_records_when_sufficient(self) -> None:
        self.ingest(raw(pn()))
        for i in range(3):  # 패널나우 실제가 예상보다 훨씬 좋음(예상 2,550 -> 실제 5,100)
            t = self.store.add_task(platform="패널나우", title=f"과거 {i}", reward=850, minutes=20, status="new", now=NOW - timedelta(days=i + 1))
            self.store.complete(t["id"], actual_reward=850, actual_minutes=10, now=NOW - timedelta(days=i + 1))
        b = money_scout.buckets(self.store.tasks(), self.store.log(), self.config, NOW)
        r = next(t for t in b["NOW"] if t["external_id"] == "r23710")
        self.assertIn("내 기록 보정", r["reason"])

    def test_choices_do_later_skip(self) -> None:
        self.ingest(raw(pn()))
        ids = {t["external_id"]: t["id"] for t in self.scout_tasks()}
        self.assertEqual(money_scout.record_choice(self.store, ids["r23710"], "DO", now=NOW)["status"], "open")
        later = money_scout.record_choice(self.store, ids["r42345"], "LATER", now=NOW)
        self.assertEqual((later["status"], later["user_choice"]), ("new", "LATER"))
        self.assertEqual(money_scout.record_choice(self.store, ids["b36835"], "SKIP", now=NOW)["status"], "skipped")
        with self.assertRaises(money.MoneyError):
            money_scout.record_choice(self.store, ids["a34038"], "SUBMIT")

    def test_20_existing_money_flow_still_works_with_scout_tasks(self) -> None:
        self.ingest(raw(pn()))
        self.ingest(raw({"platform": "heypoll", "links": HEYPOLL["links"], "page_text": ""}, mode="manual"))
        rows = money.open_tasks(self.store.tasks(), self.config, NOW, statuses=("new",), log=self.store.log())
        hp = next(r for r in rows if r.get("external_id") == "survey-715762")
        self.assertEqual((hp["estimated_hourly"], hp["grade"]), (None, "RED"))
        e = self.store.complete(hp["id"], actual_reward=1400, actual_minutes=15, now=NOW)  # 환산 미확인: 예상은 모름, 실제는 사람이 적은 원화
        self.assertEqual((e["estimated_reward"], e["estimated_hourly"], e["actual_hourly"]), (None, None, 5600))
        pn_task = next(t for t in self.scout_tasks() if t["external_id"] == "r23710")
        e2 = self.store.complete(pn_task["id"], actual_reward=670, actual_minutes=20, now=NOW)
        self.assertEqual((e2["estimated_hourly"], e2["actual_hourly"]), (2680, 2010))
        perf = {p["platform"]: p for p in money.performance(self.store.tasks(), self.store.log(), self.store.checks(), self.config)}
        self.assertEqual((perf["패널나우"]["registered"], perf["패널나우"]["completed"], perf["패널나우"]["hourly_samples"]), (5, 1, 1))
        self.assertEqual(money.goal_status(money.period_stats(self.store.log(), self.config, NOW)["total"]["earned"], self.config)["current"], 2070)
        money.timeline(self.store.tasks(), self.store.log(), self.store.checks(), self.config)  # 시간 없는 기회가 있어도 오류 없음

    def test_request_is_recorded_and_closed_by_ingest(self) -> None:
        req = money_scout.request_scout(self.staging, now=NOW)
        self.assertEqual(money_scout.request_scout(self.staging, now=NOW)["id"], req["id"])  # 대기 중 요청은 하나
        self.ingest(dict(raw(pn()), request_id=req["id"]))
        st = money_scout.load_staging(self.staging)
        self.assertEqual((st["requests"][0]["status"], st["requests"][0]["scout_run_id"]), ("done", st["runs"][0]["scout_run_id"]))


class ScoutHttpTests(MoneyCase):
    def setUp(self) -> None:
        super().setUp()
        from scripts.run_scout_dashboard import DashboardConfig, make_handler_class

        self.real = {p: (p.exists(), hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
                     for p in (ROOT / "data" / f"money_{n}.json" for n in ("tasks", "log", "checks", "config", "scout_staging"))}
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
        self.assertEqual(self.real, {p: (p.exists(), hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) for p in self.real})

    def req(self, path: str, form: dict | None = None) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", data=data), timeout=30) as r:
                return r.status, r.geturl(), r.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, path, error.read().decode("utf-8")

    def test_scout_page_request_manual_and_choice(self) -> None:
        _, _, html = self.req("/money/scout")
        for t in ("🔎 MONEY SCOUT", "마지막 확인</b>: 아직 없음", "🔎 지금 수익기회 찾기", "🔥 지금 할 것", "🟡 시간 되면", "⚪ 보류", "헤이폴",
                  "자동 접속 프로그램", "읽은 적 없음"):
            self.assertIn(t, html)
        _, url, html = self.req("/money/scout/request", {})
        self.assertIn("notice=requested", url)
        self.assertIn("요청 대기 중", html)
        _, url, html = self.req("/money/scout/manual", {"platform": "panelnow", "page_text": PANELNOW})
        self.assertIn("status=SUCCESS", url)
        for t in ("쇼핑 관련 조사", "15분 / 670P (≈670원)", "2,680원", "열기 ↗", "한다", "나중에", "안 한다", "확인 필요", "문항당 1P"):
            self.assertIn(t, html)
        tid = next(t["id"] for t in self.store.tasks() if t.get("external_id") == "r23710")
        _, url, _ = self.req("/money/scout/choice", {"task_id": tid, "choice": "DO"})
        self.assertIn("notice=choice_do", url)
        self.assertEqual(self.store.task(tid)["status"], "open")
        self.assertEqual(self.req("/money/scout/choice", {"task_id": tid, "choice": "SUBMIT"})[0], 400)
        self.assertEqual(self.req("/money/scout/manual", {"platform": "ovey", "page_text": "x"})[0], 400)  # 6-61: 헤이폴 붙여넣기는 허용, 오베이(앱 전용)는 없음
        _, _, home = self.req("/money")
        self.assertIn("🔎 MONEY SCOUT", home)
        self.assertTrue((self.dir / "money_scout_staging.json").exists())

    def test_scout_page_has_no_automation_controls(self) -> None:
        import re

        _, _, html = self.req("/money/scout")
        names = " ".join(re.findall(r'(?:name|action)="([^"]*)"', html)).lower()
        for word in ("password", "token", "cookie", "otp", "captcha", "submit_survey", "answer", "withdraw", "exchange"):
            self.assertNotIn(word, names)


if __name__ == "__main__":
    unittest.main()
