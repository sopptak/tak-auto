"""MONEY Browser Scout(6-60) - 브라우저 에이전트가 **읽은** 화면을 MONEY 기회로 바꾸는 파이프라인.

    Browser(읽기 전용: 목록 화면의 글자·링크) -> Raw Scout Result(JSON)
      -> validate_raw()      형식/크기/플랫폼 검사
      -> adapters            플랫폼별 해석(content_engine.money_scout_adapters)
      -> normalize_item()    개인정보 제거, 숫자화, 원 환산(확인된 경우만), 시급, confidence, fingerprint
      -> staging             data/money_scout_staging.json (실행 기록 + 검토 대기 항목, 화면 원문은 저장 안 함)
      -> promote()           confidence > 0.5 이고 보상이 있는 것만 money_tasks.json 기회(status=new)로 병합
      -> MONEY               기존 기회/작업/완료/분석 흐름 그대로

브라우저를 움직이는 쪽(에이전트)은 이 모듈에 raw 결과만 넘긴다 - production JSON에 직접 쓰지 않는다.
이 모듈은 네트워크를 쓰지 않고, 로그인·설문 응답·제출·포인트 교환·광고 클릭 기능이 없다.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from content_engine import money
from content_engine.money_scout_adapters import ADAPTERS

STAGING_SCHEMA = "money_scout_staging/1"
RUN_KEEP = 30
MAX_TEXT_CHARS = 200_000
MAX_LINKS = 500
REVIEW_CONFIDENCE = 0.5
OK_STATES = ("SUCCESS", "NO_OPPORTUNITY")
STATUS_TEXT = {
    "SUCCESS": "읽음", "NO_OPPORTUNITY": "읽음 · 지금 기회 없음", "LOGIN_REQUIRED": "로그인 필요(직접 로그인 후 다시 실행)",
    "CAPTCHA_REQUIRED": "사람 확인(CAPTCHA) 화면 - 우회하지 않고 중단", "BLOCKED_TERMS": "이용약관상 자동 접근 금지 - 자동으로 읽지 않음",
    "APP_ONLY": "웹에 설문 목록 없음(앱 전용)", "BROWSER_RESTRICTED": "브라우저 도구가 이 사이트를 열 수 없음",
    "TIMEOUT": "시간 초과", "PAGE_CHANGED": "화면 구조가 바뀜 - 추측해서 저장하지 않음", "PARSE_FAILED": "해석 실패", "NOT_RUN": "이번에 확인 안 함",
    "AGENT_UNAVAILABLE": "브라우저 에이전트(claude 명령)를 찾을 수 없음", "AGENT_FAILED": "브라우저 에이전트 실행 실패(Chrome/확장 연결 확인)",
    "API_UNAVAILABLE": "공식 API 없음",
}
# 플랫폼별 스카우트 정책(2026-09-27 실제 Chrome으로 확인한 사실). point_krw: 1포인트 = 몇 원인지 **확인된 경우만**.
PLATFORMS = {
    "panelnow": {"name": "패널나우", "scout_url": "https://www.panelnow.co.kr/survey", "automation": "allowed",
                 "point_krw": 1, "point_evidence": "포인트 교환 화면: 네이버페이 포인트 3,000원 = 3,000P, 컬쳐랜드 상품권 2천원권 = 2,000P",
                 "terms_note": "이용약관에 자동 접근을 금지하는 조항 없음(불법프로그램 언급은 추천 부정 행위 항목뿐). 공개 설문 목록 화면만 읽는다."},
    "ovey": {"name": "오베이", "scout_url": "https://ovey.io/", "automation": "app_only", "point_krw": None,
             "terms_note": "웹사이트는 앱 소개 페이지뿐 - 설문 목록·웹 로그인 없음."},
    "heypoll": {"name": "헤이폴", "scout_url": "https://www.heypoll.co.kr/", "automation": "blocked_terms", "point_krw": None,
                "terms_note": "이용약관 금지행위: '자동 접속 프로그램 등을 사용하는 등 정상적인 용법과 다른 방법으로 서비스를 이용…', "
                              "'서비스 이용방법에 의하지 아니하고 비정상적인 방법으로 서비스를 이용하거나 … 접속하여 사용하는 행위'. "
                              "사람이 직접 연 화면을 붙여 넣는 수동 등록(mode=manual)만 처리한다."},
    "adpost": {"name": "네이버 애드포스트", "scout_url": "https://adpost.naver.com/", "automation": "browser_restricted", "point_krw": None,
               "kind": "asset", "terms_note": "Claude in Chrome이 이 사이트 열기를 거부함(safety restriction). 네이버 로그인 필요. "
                                             "수익 상태는 사람이 직접 연 화면을 붙여 넣을 때만 읽는다."},
}
# 6-61: 공식 API - 4곳 모두 공개된 기회 조회 API를 찾지 못했다(추측으로 만들지 않는다).
OFFICIAL_API = {"panelnow": None, "ovey": None, "heypoll": None, "adpost": None}
POLICY_STATUS = {"blocked_terms": "BLOCKED_TERMS", "app_only": "APP_ONLY", "browser_restricted": "BROWSER_RESTRICTED"}
_PII = [(re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "이메일"), (re.compile(r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b"), "전화번호"),
        (re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"), "주민번호"), (re.compile(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"), "카드번호")]
_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|ref|referrer|redirect-url|redirect_url)$", re.I)
ITEM_KEYS = ("external_id", "title", "category", "type", "reward_text", "time_text", "url", "first_come", "notes")


def plan() -> list[dict]:
    """에이전트에게 줄 순회 계획: 자동으로 열어도 되는 곳만 visit=True."""
    return [{"platform": k, "name": p["name"], "url": p["scout_url"], "visit": p["automation"] == "allowed",
             "skip_status": POLICY_STATUS.get(p["automation"]), "note": p["terms_note"], "official_api": OFFICIAL_API.get(k)}
            for k, p in PLATFORMS.items()]


# ---- 검사 / 개인정보 --------------------------------------------------------------------------

def validate_raw(raw) -> list[str]:
    """브라우저 결과 형식 검사. 문제 목록(비어 있으면 통과)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("platforms"), list):
        return ["최상위는 {'platforms': [...]} 객체여야 합니다."]
    errors = []
    if raw.get("mode", "agent") not in ("agent", "manual"):
        errors.append("mode는 agent 또는 manual")
    for i, p in enumerate(raw["platforms"]):
        if not isinstance(p, dict) or p.get("platform") not in PLATFORMS:
            errors.append(f"platforms[{i}]: 알 수 없는 플랫폼 {p.get('platform') if isinstance(p, dict) else p!r}")
            continue
        if p.get("status") is not None and p["status"] not in STATUS_TEXT:
            errors.append(f"{p['platform']}: 알 수 없는 status {p['status']!r}")
        if not isinstance(p.get("page_text", ""), str) or len(p.get("page_text", "")) > MAX_TEXT_CHARS:
            errors.append(f"{p['platform']}: page_text는 {MAX_TEXT_CHARS}자 이하 문자열")
        links = p.get("links", [])
        if not isinstance(links, list) or len(links) > MAX_LINKS or not all(isinstance(x, dict) for x in links):
            errors.append(f"{p['platform']}: links는 {MAX_LINKS}개 이하 {{text, href}} 목록")
    return errors


def scrub(text) -> tuple[str, bool]:
    """이메일/전화/주민/카드 번호 모양을 지운다. (정리된 글, 지웠는지)."""
    out, hit = str(text or ""), False
    for pattern, label in _PII:
        out, n = pattern.subn(f"[{label} 제거]", out)
        hit = hit or n > 0
    return out, hit


def canonical_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, query, ""))


# ---- 정규화 ----------------------------------------------------------------------------------

def _reward(text: str) -> tuple[int | None, str | None, str | None]:
    """'850P' -> (850, 'P'), '1,200원' -> (1200, '원'). 범위·문항당·모호하면 (None, unit, 사유) - 추측하지 않는다."""
    t = str(text or "").strip()
    if not t:
        return None, None, "보상 표시 없음"
    if "문항당" in t or "~" in t:
        return None, "P" if "P" in t.upper() else None, f"보상이 고정값이 아님({t})"
    m = re.fullmatch(r"(\d[\d,]*)\s*(P|p|원|포인트)", t)
    if not m:
        return None, None, f"보상 형식을 읽지 못함({t[:20]})"
    return int(m.group(1).replace(",", "")), "원" if m.group(2) == "원" else "P", None


def _minutes(text: str) -> int | float | None:
    t = re.sub(r"(약|내외|정도|이내)", "", str(text or "")).strip()
    if not t:
        return None
    try:
        return money.parse_minutes(t)
    except money.MoneyError:
        return None


def fingerprint(platform: str, external_id: str | None, title: str, reward, minutes, url: str) -> str:
    key = (f"{platform}|id|{external_id}" if external_id
           else f"{platform}|{re.sub(r'[^0-9a-z가-힣]', '', str(title).lower())}|{reward}|{minutes}|{canonical_url(url)}")
    return "fp-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_item(platform: str, item: dict, *, run_id: str, collected_at: str) -> dict:
    """어댑터 결과 한 건 -> 기회 후보. 없는 값은 None으로 두고 confidence를 낮춘다(만들어 넣지 않는다)."""
    cfg = PLATFORMS[platform]
    item = {k: item.get(k) for k in ITEM_KEYS}  # 허용 필드만(프로필·답변 등이 딸려 와도 버린다)
    title, pii_title = scrub(str(item.get("title") or "").strip()[:120])
    external_id, pii_id = scrub(str(item.get("external_id") or "").strip()[:40])
    reward, unit, reward_issue = _reward(item.get("reward_text"))
    minutes = _minutes(item.get("time_text"))
    krw = reward if unit == "원" else (reward * cfg["point_krw"] if reward is not None and unit == "P" and cfg.get("point_krw") else None)
    url = canonical_url(item.get("url") or cfg["scout_url"])
    issues = [x for x in (reward_issue,) if x]
    confidence = 0.95
    if minutes is None:
        confidence -= 0.15
        issues.append("소요시간 표시 없음 - 시급 계산 안 함")
    if reward is None:
        confidence -= 0.45
    if len(title) < 2:
        confidence -= 0.3
        issues.append("제목 없음")
    if not external_id:
        confidence -= 0.05
    if pii_title or pii_id:
        confidence -= 0.2
        issues.append("개인정보 모양 글자를 지움")
    if reward is not None and unit == "P" and krw is None:
        issues.append("포인트→원 환산이 확인되지 않아 원화·시급을 만들지 않음")
    confidence = round(max(0.0, confidence), 2)
    notes = [scrub(str(n))[0][:40] for n in (item.get("notes") or [])][:5]
    return {"platform": platform, "platform_name": cfg["name"], "external_id": external_id or None, "title": title,
            "category": scrub(str(item.get("category") or ""))[0][:30], "type": str(item.get("type") or "survey")[:20],
            "reward": reward, "reward_unit": unit, "reward_krw_estimate": krw, "estimated_minutes": minutes,
            "hourly_rate": money.hourly(krw, minutes) if krw is not None and minutes else None,
            "url": url, "first_come": bool(item.get("first_come")), "notes": notes, "source": "browser_scout",
            "scout_run_id": run_id, "collected_at": collected_at, "expires_at": None, "confidence": confidence, "issues": issues,
            "fingerprint": fingerprint(platform, external_id or None, title, reward, minutes, url),
            "verdict": "promote" if confidence > REVIEW_CONFIDENCE and reward is not None and len(title) >= 2 else "review"}


# ---- 저장 ------------------------------------------------------------------------------------

def load_staging(path: Path | str) -> dict:
    path = Path(path)
    if not path.exists():
        return {"schema": STAGING_SCHEMA, "runs": [], "requests": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise money.MoneyError("DATA_UNREADABLE", str(path)) from error
    if not isinstance(data, dict):
        raise money.MoneyError("DATA_UNREADABLE", str(path))
    return {"schema": STAGING_SCHEMA, "runs": data.get("runs") or [], "requests": data.get("requests") or []}


def request_scout(staging_path: Path | str, *, now: datetime | None = None) -> dict:
    """화면의 [🔎 지금 수익기회 찾기]: 실행 요청을 남긴다. 실제 읽기는 브라우저 에이전트가 plan()대로 하고 ingest()로 넘긴다."""
    now = now or money._now()
    with money._LOCK:
        staging = load_staging(staging_path)
        pending = next((r for r in staging["requests"] if r["status"] == "pending"), None)
        if pending:
            return pending
        req = {"id": f"req-{uuid.uuid4().hex[:10]}", "requested_at": now.isoformat(timespec="seconds"), "status": "pending"}
        staging["requests"] = [*staging["requests"][-(RUN_KEEP - 1):], req]
        money._write(Path(staging_path), staging)
    return req


def _task_from(n: dict, now_iso: str) -> dict:
    cfg = PLATFORMS[n["platform"]]
    point_value = 1 if n["reward_unit"] == "원" else cfg.get("point_krw")  # None = 환산 미확인
    return {"schema": money.TASKS_SCHEMA, "id": f"task-{uuid.uuid4().hex[:12]}", "platform": cfg["name"], "title": n["title"],
            "reward": n["reward"], "minutes": n["estimated_minutes"], "point_value": point_value, "url": n["url"], "memo": "",
            "deadline": None, "status": "new", "source": "browser_scout", "created_at": now_iso, "closed_at": None, "accepted_at": None,
            "external_id": n["external_id"], "fingerprint": n["fingerprint"], "scout_run_id": n["scout_run_id"],
            "confidence": n["confidence"], "reward_unit": n["reward_unit"], "reward_krw_estimate": n["reward_krw_estimate"],
            "category": n["category"], "type": n["type"], "first_come": n["first_come"], "scout_notes": n["notes"],
            "scout_state": "active", "first_seen_at": now_iso, "last_seen_at": now_iso}


def promote(items: list[dict], tasks_path: Path | str, *, run_id: str, ok_platforms: list[str], now: datetime) -> dict:
    """검토를 통과한 후보를 money_tasks에 병합한다.
    - 같은 fingerprint가 있으면 새로 만들지 않고 last_seen/active만 갱신, 아직 기회(new)면 보이는 값(제목·보상·시간)도 갱신.
      할 작업(open)·완료(done)·안 함(skipped)의 값과 완료 기록은 절대 바꾸지 않는다.
    - 이번에 정상적으로 읽은 플랫폼에서 안 보인 기존 스카우트 기회는 scout_state=disappeared(완료 처리 아님)."""
    now_iso = now.isoformat(timespec="seconds")
    counts = {"created": 0, "updated": 0, "unchanged": 0, "disappeared": 0}
    with money._LOCK:
        tasks = money._read_list(Path(tasks_path))
        by_fp = {t.get("fingerprint"): t for t in tasks if t.get("fingerprint")}
        seen = set()
        for n in items:
            seen.add(n["fingerprint"])  # 6-62: 값이 덜 읽혀 검토로 간 것도 '보였음'(사라짐 처리 안 함)
            old = by_fp.get(n["fingerprint"])
            if n["verdict"] != "promote":
                if old is not None:
                    old.update(last_seen_at=now_iso, scout_state="active", scout_run_id=run_id)
                continue
            if old is None:
                task = _task_from(n, now_iso)
                tasks.append(task)
                by_fp[task["fingerprint"]] = task
                counts["created"] += 1
                continue
            old.update(last_seen_at=now_iso, scout_state="active", scout_run_id=run_id, confidence=n["confidence"])
            if old.get("status") == "new":
                # 6-62: 이번 읽기에 빠진 값(트리 읽기의 시간 칸 등)은 전에 본 값을 지우지 않는다
                n = {**n, **{k: old.get(o) for k, o in (("reward", "reward"), ("estimated_minutes", "minutes"),
                                                         ("reward_krw_estimate", "reward_krw_estimate")) if n[k] is None}}
                changed = (old.get("title"), old.get("reward"), old.get("minutes")) != (n["title"], n["reward"], n["estimated_minutes"])
                old.update(title=n["title"], reward=n["reward"], minutes=n["estimated_minutes"], url=n["url"],
                           reward_krw_estimate=n["reward_krw_estimate"], first_come=n["first_come"], scout_notes=n["notes"])
                counts["updated" if changed else "unchanged"] += 1
            else:
                counts["unchanged"] += 1
        names = {PLATFORMS[k]["name"] for k in ok_platforms}
        for t in tasks:
            if (t.get("source") == "browser_scout" and t.get("platform") in names and t.get("status") in ("new", "open")
                    and t.get("fingerprint") not in seen and t.get("scout_state") != "disappeared"):
                t.update(scout_state="disappeared", disappeared_at=now_iso)
                counts["disappeared"] += 1
        money._write(Path(tasks_path), tasks)
    return counts


def ingest(raw: dict, *, tasks_path: Path | str, staging_path: Path | str, now: datetime | None = None, promote_items: bool = True) -> dict:
    """브라우저 결과 한 번 -> 실행 기록. 플랫폼 하나가 실패해도 나머지는 계속한다."""
    now = now or money._now()
    errors = validate_raw(raw)
    run_id = str(raw.get("scout_run_id") or f"scout-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}") if isinstance(raw, dict) else "invalid"
    collected_at = now.isoformat(timespec="seconds")
    run = {"scout_run_id": run_id, "mode": raw.get("mode", "agent") if isinstance(raw, dict) else None, "collected_at": collected_at,
           "agent": str(raw.get("agent") or "")[:40] if isinstance(raw, dict) else "", "platforms": {}, "items": [], "errors": errors}
    if errors:
        run["overall"] = "INVALID"
    else:
        entries = {p["platform"]: p for p in raw["platforms"]}
        for key, cfg in PLATFORMS.items():
            entry = entries.get(key)
            result = {"status": "NOT_RUN", "detail": "", "items": [], "asset_status": None}
            if entry is not None:
                policy = POLICY_STATUS.get(cfg["automation"])
                if policy and run["mode"] == "agent":
                    result = {"status": policy, "detail": cfg["terms_note"], "items": [], "asset_status": None}
                elif entry.get("status") and entry["status"] != "SUCCESS":
                    result = {"status": entry["status"], "detail": str(entry.get("detail") or "")[:200], "items": [], "asset_status": None}
                else:
                    try:
                        result = ADAPTERS[key](entry)
                    except Exception as error:  # noqa: BLE001 - 한 플랫폼 실패는 그 플랫폼만(실패 격리)
                        result = {"status": "PARSE_FAILED", "detail": type(error).__name__, "items": [], "asset_status": None}
            text = str((entry or {}).get("page_text") or "")
            normalized = [normalize_item(key, it, run_id=run_id, collected_at=collected_at) for it in result["items"]]
            run["items"] += normalized
            run["platforms"][key] = {"status": result["status"], "detail": result.get("detail", ""), "asset_status": result.get("asset_status"),
                                     "observed_at": str((entry or {}).get("observed_at") or "")[:40] or None,
                                     "found": len(normalized), "promotable": sum(n["verdict"] == "promote" for n in normalized),
                                     "review": sum(n["verdict"] == "review" for n in normalized),
                                     "raw_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None, "raw_text_len": len(text)}
        attempted = [k for k, p in run["platforms"].items() if p["status"] != "NOT_RUN"]
        ok = [k for k in attempted if run["platforms"][k]["status"] in OK_STATES]
        run["overall"] = "SUCCESS" if attempted and len(ok) == len(attempted) else "PARTIAL_SUCCESS" if ok else "FAILED"
        run["promotion"] = (promote(run["items"], tasks_path, run_id=run_id, ok_platforms=ok, now=now) if promote_items
                            else {"created": 0, "updated": 0, "unchanged": 0, "disappeared": 0})
    with money._LOCK:
        staging = load_staging(staging_path)
        for req in staging["requests"]:
            if req["status"] in ("pending", "running") and (raw.get("request_id") in (None, req["id"]) if isinstance(raw, dict) else False):
                req.update(status="done", scout_run_id=run_id, done_at=collected_at)
        staging["runs"] = [*staging["runs"], run][-RUN_KEEP:]
        money._write(Path(staging_path), staging)
    return run


# ---- 우선순위 / 사용자 선택 ----------------------------------------------------------------------

BUCKETS = {"NOW": "🔥 지금 할 것", "LATER": "🟡 시간 되면", "HOLD": "⚪ 보류"}


def buckets(tasks: list[dict], log: list[dict], config: dict, now: datetime | None = None) -> dict:
    """스카우트 기회를 3칸으로. 기존 6-58 등급(설정 기준) + 6-59 내 기록 보정(표본 충분할 때만)을 쓴다.
    내 기록이 모자라면 예상 시급만으로 판단(그 사실을 reason에 적는다). 플랫폼 우열을 임의로 정하지 않는다."""
    now = now or money._now()
    # 6-61: 스카우트가 찾은 것뿐 아니라 빠른 등록/붙여넣기로 들어온 열린 기회·작업 모두(오늘 할 것은 출처와 무관)
    rows = money.open_tasks(tasks, config, now, statuses=("new", "open"), log=log)
    out = {k: [] for k in BUCKETS}
    th = config["thresholds"]
    for t in rows:
        learned = t.get("learned_hourly")
        rate = learned if learned is not None else t.get("estimated_hourly")
        basis = "내 기록 보정" if learned is not None else "예상 시급만(내 기록 부족)"
        if t.get("scout_state") == "disappeared" or t.get("expired"):
            key, reason = "HOLD", "이번 확인에서 안 보임(마감됐을 수 있음)"
        elif t.get("user_choice") == "LATER":
            key, reason = "LATER", "내가 '나중에'로 둠"
        elif rate is None:
            key, reason = "HOLD", "소요시간 또는 원 환산 정보가 없어 시급을 모름"
        elif t.get("first_come") and rate >= th["yellow"]:
            key, reason = "NOW", f"선착순 · {basis} {rate:,}원/시간"
        elif rate >= th["green"]:
            key, reason = "NOW", f"{basis} {rate:,}원/시간"
        elif rate >= th["yellow"]:
            key, reason = "LATER", f"{basis} {rate:,}원/시간"
        else:
            key, reason = "HOLD", f"{basis} {rate:,}원/시간(기준 {th['yellow']:,}원 미만)"
        out[key].append({**t, "bucket": key, "reason": reason, "priority_score": rate})
    for key in out:  # 6-61: 시급(보정 우선) -> 선착순 -> 마감 임박 -> 짧은 시간 -> 신뢰도
        out[key].sort(key=lambda r: (-(r["priority_score"] or 0), not r.get("first_come"), r.get("deadline") or "9999",
                                     r.get("minutes") or 9999, -(r.get("confidence") or 0), r["title"]))
    return out


def top_picks(groups: dict, n: int = 3) -> list[dict]:
    """오늘 할 것 TOP n: 🔥 먼저, 모자라면 🟡, 그래도 모자라면 ⚪(보류 표시 그대로).
    6-62: 실제 회원 설문 2건이 모두 기준 시급 미만(⚪)이라 TOP이 비었다 - 첫 수익이 목표일 때 '할 것 없음'보다
    가장 나은 보류를 보여 주는 게 맞다. 안 보이게 된(마감 가능) 것은 넣지 않는다."""
    hold = [t for t in groups["HOLD"] if t.get("scout_state") != "disappeared" and not t.get("expired")]
    return (groups["NOW"] + groups["LATER"] + hold)[:n]


def today_money(tasks: list[dict], log: list[dict], config: dict, now: datetime | None = None) -> dict:
    """TODAY MONEY: 예상(아직 안 번 돈)과 실제(받은 돈)를 분리한다. 목표 진행률은 실제만."""
    now = now or money._now()
    groups = buckets(tasks, log, config, now)
    stats = money.period_stats(log, config, now)
    pending = groups["NOW"] + groups["LATER"]
    known = [t.get("reward_krw_estimate") if t.get("reward_krw_estimate") is not None else (t["reward"] * t["point_value"] if t.get("point_value") else None)
             for t in pending]
    return {"found_today": sum(1 for t in tasks if t.get("source") != "quick_done" and money._is_today(t.get("created_at"), config, now)),
            "now": len(groups["NOW"]), "later": len(groups["LATER"]), "hold": len(groups["HOLD"]),
            "expected_krw": sum(k for k in known if k is not None), "expected_unknown": sum(1 for k in known if k is None),
            "actual_today": stats["today"]["earned"], "actual_month": stats["month"]["earned"],
            "goal": money.goal_status(stats["total"]["earned"], config),
            # 6-62: 실제로 받은 돈이 한 번도 기록되지 않았으면 PENDING(가짜 수익으로 채우지 않는다)
            "revenue_state": "REAL_REVENUE_RECORDED" if stats["total"]["earned"] > 0 else "REAL_REVENUE_PENDING",
            "actual_hourly": stats["total"]["hourly"], "actual_count": stats["total"]["count"]}


def set_request(staging_path: Path | str, req_id: str, status: str, message: str = "", *, now: datetime | None = None) -> None:
    """버튼 실행 상태 기록(pending -> running -> done/failed)."""
    with money._LOCK:
        staging = load_staging(staging_path)
        for req in staging["requests"]:
            if req["id"] == req_id:
                req.update(status=status, message=message[:200], updated_at=(now or money._now()).isoformat(timespec="seconds"))
        money._write(Path(staging_path), staging)


def record_choice(store: money.MoneyStore, task_id: str, choice: str, *, now: datetime | None = None) -> dict:
    """DO(한다 -> 할 작업으로), LATER(나중에), SKIP(안 한다 -> skipped). 어떤 선택도 외부 사이트에서 아무것도 하지 않는다."""
    if choice not in ("DO", "LATER", "SKIP"):
        raise money.MoneyError("STATUS_INVALID", str(choice)[:10])
    now = now or money._now()
    task = store.task(task_id)
    if choice == "DO" and task["status"] == "new":
        store.accept(task_id, now=now)
    elif choice == "SKIP" and task["status"] in ("new", "open"):
        store.skip(task_id, now=now)
    with money._LOCK:
        tasks = store.tasks()
        t = next(t for t in tasks if t["id"] == task_id)
        t.update(user_choice=choice, user_choice_at=now.isoformat(timespec="seconds"))
        money._write(Path(store.tasks_path), tasks)
    return t


def latest_run(staging: dict) -> dict | None:
    return staging["runs"][-1] if staging["runs"] else None


def scout_age_hours(run: dict | None, now: datetime | None = None) -> float | None:
    if not run:
        return None
    return round(((now or money._now()) - datetime.fromisoformat(run["collected_at"])) / timedelta(hours=1), 1)
