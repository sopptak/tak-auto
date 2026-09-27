"""TAK AUTO MONEY(6-57) - 온라인 수익 노가다 관제판의 데이터/계산.

    DISCOVER(작업 등록) -> FILTER(예상 시급 등급) -> DO(사람이 공식 사이트에서 직접) -> RECORD(실제 보상/시간) -> LEARN(통계)

저장:
    data/money_tasks.json   작업 후보(예상 보상/시간 - 등록 후 바꾸지 않는다)
    data/money_log.json     완료/수익 기록(예상값 사본 + 실제값을 따로 보존, 추가만 한다)
    data/money_config.json  (선택) 목표 금액·등급 기준·플랫폼 목록 덮어쓰기. 없으면 DEFAULT_CONFIG.

이 모듈이 하지 않는 것: 외부 사이트 로그인/설문 응답/본인인증/CAPTCHA 우회/자동 제출, 비밀번호·토큰·쿠키·개인정보 저장,
네트워크 호출. 공식 링크를 보여주고 사람이 직접 한 결과를 기록·계산할 뿐이다.
모든 파일이 없어도(최초 실행) 빈 상태로 동작한다.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

TASKS_SCHEMA = "money_task/1"
LOG_SCHEMA = "money_log/1"
MAX_REWARD = 10_000_000
MAX_MINUTES = 24 * 60
MAX_TEXT = {"platform": 40, "title": 120, "memo": 500, "url": 500}

# 설정값(코드가 아니라 데이터) - data/money_config.json이 있으면 키 단위로 덮어쓴다.
DEFAULT_CONFIG = {
    "currency": "원",
    "utc_offset_hours": 9,  # KST(서머타임 없음). Windows에 tzdata가 없어 고정 오프셋을 쓴다.
    "goals": [10_000, 100_000, 1_000_000],  # 첫 목표 = goals[0]
    # 초기 실험용 기준(원/시간). 절대 평가가 아니다 - 실제 데이터를 보고 바꾼다.
    "thresholds": {"green": 3000, "yellow": 2000, "orange": 1000},
    "platforms": [
        # point_value: 보상 1(포인트) = 몇 원인지. 확인되지 않은 환산은 1로 두고 사람이 설정에서 바꾼다.
        {"name": "패널나우", "url": "https://www.panelnow.co.kr/", "aliases": ["panelnow", "패널"], "point_value": 1, "kind": "survey"},
        {"name": "오베이", "url": "https://ovey.io/", "aliases": ["ovey"], "point_value": 1, "kind": "survey"},
        {"name": "헤이폴", "url": "https://www.heypoll.co.kr/", "aliases": ["heypoll"], "point_value": 1, "kind": "survey"},
        {"name": "네이버 애드포스트", "url": "https://adpost.naver.com/", "aliases": ["애드포스트", "adpost"], "point_value": 1, "kind": "asset"},
        {"name": "기타", "url": "", "aliases": ["etc"], "point_value": 1, "kind": "other"},
    ],
}
GRADES = {  # 등급 -> (표시, 설명)
    "GREEN": ("🟢", "적극적으로 검토"), "YELLOW": ("🟡", "검토"), "ORANGE": ("🟠", "낮음"), "RED": ("🔴", "매우 낮음"),
}
ERROR_TEXT = {
    "PLATFORM_REQUIRED": "플랫폼을 고르거나 입력해 주세요.",
    "TITLE_REQUIRED": "작업명을 입력해 주세요.",
    "TEXT_TOO_LONG": "입력이 너무 깁니다.",
    "REWARD_INVALID": "보상은 0 이상의 숫자여야 합니다(예: 850, 850P, 1,200원).",
    "MINUTES_INVALID": "시간은 1분 이상 24시간 이하의 숫자여야 합니다.",
    "URL_INVALID": "링크는 http:// 또는 https:// 로 시작하는 주소여야 합니다.",
    "DEADLINE_INVALID": "마감시간 형식이 잘못됐습니다.",
    "TASK_NOT_FOUND": "작업을 찾을 수 없습니다.",
    "ALREADY_COMPLETED": "이미 완료 기록이 있는 작업입니다(중복 기록 방지).",
    "TASK_CLOSED": "이미 닫힌(건너뛴) 작업입니다.",
    "QUICK_PARSE_FAILED": "'플랫폼 시간 보상' 순서로 적어 주세요. 예: 패널나우 20분 850P",
    "GOALS_INVALID": "목표 금액은 1 이상의 숫자를 쉼표로 구분해 주세요(예: 10000, 100000).",
    "THRESHOLDS_INVALID": "등급 기준은 초록 ≥ 노랑 ≥ 주황 ≥ 0 이어야 합니다.",
    "DATA_UNREADABLE": "MONEY 데이터 파일을 읽을 수 없습니다(파일을 확인해 주세요 - 덮어쓰지 않았습니다).",
}
_LOCK = threading.Lock()  # 같은 PC의 Dashboard(ThreadingHTTPServer) 안에서 읽기-수정-쓰기를 한 번에


class MoneyError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail

    @property
    def text(self) -> str:
        return ERROR_TEXT.get(self.code, self.code) + (f" ({self.detail})" if self.detail else "")


# ---- 설정 ----------------------------------------------------------------------------------

def load_config(path: Path | str | None) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path and Path(path).exists():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise MoneyError("DATA_UNREADABLE", str(path)) from error
        for key in ("goals", "thresholds", "platforms", "utc_offset_hours", "currency"):
            if key in data:
                config[key] = {**config[key], **data[key]} if key == "thresholds" else data[key]
    validate_goals(config["goals"])
    validate_thresholds(config["thresholds"])
    return config


def validate_goals(goals) -> list[int]:
    try:
        values = [int(g) for g in goals]
    except (TypeError, ValueError) as error:
        raise MoneyError("GOALS_INVALID") from error
    if not values or any(v < 1 for v in values):
        raise MoneyError("GOALS_INVALID")
    return sorted(set(values))


def validate_thresholds(t: dict) -> dict:
    try:
        g, y, o = int(t["green"]), int(t["yellow"]), int(t["orange"])
    except (KeyError, TypeError, ValueError) as error:
        raise MoneyError("THRESHOLDS_INVALID") from error
    if not g >= y >= o >= 0:
        raise MoneyError("THRESHOLDS_INVALID")
    return {"green": g, "yellow": y, "orange": o}


def save_config(path: Path | str, goals, thresholds: dict) -> dict:
    """목표/등급 기준만 저장한다(플랫폼 목록 등 다른 키는 파일에 있던 값을 유지)."""
    path = Path(path)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing.update({"goals": validate_goals(goals), "thresholds": validate_thresholds(thresholds)})
    _write(path, existing)
    return load_config(path)


def platform_info(config: dict, name: str) -> dict | None:
    return next((p for p in config["platforms"] if p["name"] == name), None)


# ---- 계산 ----------------------------------------------------------------------------------

def hourly(reward: float, minutes: float) -> int | None:
    """시간당 수익 = reward × 60 ÷ minutes(원 단위 반올림). minutes가 0이면 None."""
    if not minutes or minutes <= 0:
        return None
    return int(round(reward * 60 / minutes))


def grade(rate: int | None, thresholds: dict) -> str:
    if rate is None:
        return "RED"
    if rate >= thresholds["green"]:
        return "GREEN"
    if rate >= thresholds["yellow"]:
        return "YELLOW"
    if rate >= thresholds["orange"]:
        return "ORANGE"
    return "RED"


def parse_reward(value) -> int:
    """'850', '850P', '1,200원', '850 포인트' -> 850. 음수/문자/너무 큼 -> REWARD_INVALID."""
    text = re.sub(r"(원|포인트|[Pp]|\s|,)", "", str(value if value is not None else ""))
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        raise MoneyError("REWARD_INVALID", str(value))
    reward = float(text)
    if reward > MAX_REWARD:
        raise MoneyError("REWARD_INVALID", str(value))
    return int(round(reward))


def parse_minutes(value) -> float:
    """'20', '20분', '1시간', '1시간 30분', '90min' -> 분."""
    text = str(value if value is not None else "").strip().lower()
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*(?:시간|h|hr|hours?))?\s*(?:(\d+(?:\.\d+)?)\s*(?:분|m|min|mins|minutes?)?)?", text)
    if not text or not m or not (m.group(1) or m.group(2)):
        raise MoneyError("MINUTES_INVALID", str(value))
    minutes = float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    if not 0 < minutes <= MAX_MINUTES:
        raise MoneyError("MINUTES_INVALID", str(value))
    return int(minutes) if minutes == int(minutes) else round(minutes, 1)


def _text(value, key: str, required_code: str | None = None) -> str:
    text = str(value or "").strip()
    if required_code and not text:
        raise MoneyError(required_code)
    if len(text) > MAX_TEXT[key]:
        raise MoneyError("TEXT_TOO_LONG", f"{key} {len(text)}자")
    return text


def _url(value, fallback: str = "") -> str:
    url = str(value or "").strip() or fallback
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or len(url) > MAX_TEXT["url"] or any(c in url for c in "<>\"' "):
        raise MoneyError("URL_INVALID", url[:80])  # javascript:, data: 등 차단
    return url


def local_tz(config: dict) -> timezone:
    return timezone(timedelta(hours=float(config.get("utc_offset_hours", 9))))


def _deadline(value, config: dict) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as error:
        raise MoneyError("DEADLINE_INVALID", text) from error
    if dt.tzinfo is None:  # 화면(datetime-local)은 이 PC 시간 기준
        dt = dt.replace(tzinfo=local_tz(config))
    return dt.isoformat(timespec="minutes")


def quick_parse(text: str, config: dict) -> dict:
    """캡처/메모 한 줄 -> 작업 입력값. 예: '패널나우 20분 850P 일반인 의견 조사'
    -> {platform, minutes, reward, title, estimated_hourly, grade}. 플랫폼 이름/별칭은 설정에서 찾는다."""
    raw = str(text or "").strip()
    rest = raw
    platform = None
    for p in config["platforms"]:
        for alias in [p["name"], *p.get("aliases", [])]:
            if alias and alias.lower() in rest.lower():
                platform = p["name"]
                rest = re.sub(re.escape(alias), " ", rest, count=1, flags=re.I)
                break
        if platform:
            break
    time_match = re.search(r"(\d+(?:\.\d+)?\s*(?:시간|hours?|hr|h)\s*)?(\d+(?:\.\d+)?\s*(?:분|minutes?|mins?|min))|\d+(?:\.\d+)?\s*(?:시간|hours?|hr)", rest, re.I)
    reward_match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(P|p|원|포인트)(?![A-Za-z])", rest)
    if not platform or not time_match or not reward_match:
        raise MoneyError("QUICK_PARSE_FAILED", raw[:60])
    minutes = parse_minutes(time_match.group(0))
    reward = parse_reward(reward_match.group(0))
    for m in sorted((time_match, reward_match), key=lambda m: m.start(), reverse=True):
        rest = rest[:m.start()] + " " + rest[m.end():]
    title = re.sub(r"\s+", " ", rest).strip(" -·/|,") or f"{platform} 작업"
    rate = hourly(reward * platform_info(config, platform).get("point_value", 1), minutes)
    return {"platform": platform, "minutes": minutes, "reward": reward, "title": title,
            "estimated_hourly": rate, "grade": grade(rate, config["thresholds"])}


# ---- 저장소 --------------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_list(path: Path) -> list[dict]:
    if not path.exists():
        return []  # 최초 실행
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError) as error:
        raise MoneyError("DATA_UNREADABLE", str(path)) from error
    if not isinstance(data, list):
        raise MoneyError("DATA_UNREADABLE", str(path))
    return data


@dataclass
class MoneyStore:
    tasks_path: Path
    log_path: Path
    config: dict

    def tasks(self) -> list[dict]:
        return _read_list(Path(self.tasks_path))

    def log(self) -> list[dict]:
        return _read_list(Path(self.log_path))

    def task(self, task_id: str) -> dict:
        found = next((t for t in self.tasks() if t.get("id") == task_id), None)
        if found is None:
            raise MoneyError("TASK_NOT_FOUND", str(task_id)[:40])
        return found

    def add_task(self, *, platform, title, reward, minutes, url="", memo="", deadline=None, source="manual",
                 now: datetime | None = None) -> dict:
        platform = _text(platform, "platform", "PLATFORM_REQUIRED")
        info = platform_info(self.config, platform) or {}
        task = {
            "schema": TASKS_SCHEMA, "id": f"task-{uuid.uuid4().hex[:12]}", "platform": platform,
            "title": _text(title, "title", "TITLE_REQUIRED"), "reward": parse_reward(reward), "minutes": parse_minutes(minutes),
            "point_value": info.get("point_value", 1), "url": _url(url, info.get("url", "")), "memo": _text(memo, "memo"),
            "deadline": _deadline(deadline, self.config), "status": "open", "source": source,
            "created_at": (now or _now()).isoformat(timespec="seconds"), "closed_at": None,
        }
        with _LOCK:
            tasks = self.tasks()
            tasks.append(task)
            _write(Path(self.tasks_path), tasks)
        return task

    def complete(self, task_id: str, *, actual_reward, actual_minutes, memo="", now: datetime | None = None) -> dict:
        """완료 기록: 작업의 예상값은 그대로 두고, 로그에 예상 사본 + 실제값을 따로 남긴다. 같은 작업은 한 번만."""
        actual_reward, actual_minutes = parse_reward(actual_reward), parse_minutes(actual_minutes)
        memo = _text(memo, "memo")
        with _LOCK:
            tasks, log = self.tasks(), self.log()
            task = next((t for t in tasks if t.get("id") == task_id), None)
            if task is None:
                raise MoneyError("TASK_NOT_FOUND", str(task_id)[:40])
            if task["status"] == "done" or any(e.get("task_id") == task_id for e in log):
                raise MoneyError("ALREADY_COMPLETED", task["title"][:40])
            if task["status"] != "open":
                raise MoneyError("TASK_CLOSED", task["title"][:40])
            at = (now or _now()).isoformat(timespec="seconds")
            pv = task.get("point_value", 1)
            entry = {
                "schema": LOG_SCHEMA, "id": f"log-{uuid.uuid4().hex[:12]}", "kind": "task", "task_id": task_id,
                "platform": task["platform"], "title": task["title"],
                "estimated_reward": task["reward"], "estimated_minutes": task["minutes"],
                "estimated_hourly": hourly(task["reward"] * pv, task["minutes"]),
                "actual_reward": actual_reward, "actual_minutes": actual_minutes,
                "actual_hourly": hourly(actual_reward * pv, actual_minutes),
                "point_value": pv, "memo": memo, "completed_at": at,
            }
            log.append(entry)
            task.update(status="done", closed_at=at)
            _write(Path(self.log_path), log)  # 로그를 먼저 - 중간에 끊겨도 로그 기준으로 중복이 막힌다
            _write(Path(self.tasks_path), tasks)
        return entry

    def skip(self, task_id: str, *, now: datetime | None = None) -> dict:
        """할 가치가 없거나 사라진 작업을 목록에서 내린다(삭제하지 않음 - 분석에 남는다)."""
        with _LOCK:
            tasks = self.tasks()
            task = next((t for t in tasks if t.get("id") == task_id), None)
            if task is None:
                raise MoneyError("TASK_NOT_FOUND", str(task_id)[:40])
            if task["status"] != "open":
                raise MoneyError("ALREADY_COMPLETED" if task["status"] == "done" else "TASK_CLOSED", task["title"][:40])
            task.update(status="skipped", closed_at=(now or _now()).isoformat(timespec="seconds"))
            _write(Path(self.tasks_path), tasks)
        return task

    def record_income(self, *, platform, amount, minutes=0, title="", memo="", now: datetime | None = None) -> dict:
        """작업 카드 없이 들어온 수익(예: 애드포스트 월 정산, 장기 수익자산). 시간은 선택(0 = 시급 계산에서 제외)."""
        platform = _text(platform, "platform", "PLATFORM_REQUIRED")
        minutes = parse_minutes(minutes) if str(minutes or "").strip() not in ("", "0") else 0
        amount = parse_reward(amount)
        pv = (platform_info(self.config, platform) or {}).get("point_value", 1)
        entry = {"schema": LOG_SCHEMA, "id": f"log-{uuid.uuid4().hex[:12]}", "kind": "income", "task_id": None,
                 "platform": platform, "title": _text(title, "title") or f"{platform} 수익",
                 "estimated_reward": None, "estimated_minutes": None, "estimated_hourly": None,
                 "actual_reward": amount, "actual_minutes": minutes, "actual_hourly": hourly(amount * pv, minutes),
                 "point_value": pv, "memo": _text(memo, "memo"), "completed_at": (now or _now()).isoformat(timespec="seconds")}
        with _LOCK:
            log = self.log()
            log.append(entry)
            _write(Path(self.log_path), log)
        return entry


# ---- 통계 ----------------------------------------------------------------------------------

def won(entry: dict) -> int:
    """기록 한 건의 원화 금액(포인트 환산)."""
    return int(round(entry["actual_reward"] * entry.get("point_value", 1)))


def _period_start(now_local: datetime, period: str) -> datetime | None:
    day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"today": day, "week": day - timedelta(days=day.weekday()), "month": day.replace(day=1), "total": None}[period]


def period_stats(log: list[dict], config: dict, now: datetime | None = None) -> dict:
    """오늘/이번 주(월요일 시작)/이번 달/누적: 수익(원), 투자시간(분), 실제 시급.
    시급은 시간을 들인 기록(kind=task 또는 minutes>0)만으로 계산한다 - 시간 없이 들어온 정산 수익이 시급을 부풀리지 않게."""
    tz = local_tz(config)
    now_local = (now or _now()).astimezone(tz)
    out = {}
    for period in ("today", "week", "month", "total"):
        start = _period_start(now_local, period)
        rows = [e for e in log if start is None or datetime.fromisoformat(e["completed_at"]).astimezone(tz) >= start]
        timed = [e for e in rows if e.get("actual_minutes")]
        minutes = sum(e["actual_minutes"] for e in rows)
        out[period] = {"earned": sum(won(e) for e in rows), "minutes": minutes, "count": len(rows),
                       "hourly": hourly(sum(won(e) for e in timed), sum(e["actual_minutes"] for e in timed))}
    return out


def goal_status(total: int, config: dict) -> dict:
    goals = validate_goals(config["goals"])
    first = goals[0]
    current = next((g for g in goals if total < g), None)  # 아직 못 이룬 가장 작은 목표
    target = current or goals[-1]
    return {"first_goal": first, "first_achieved": total >= first, "goals": goals,
            "achieved": [g for g in goals if total >= g], "target": target, "current": total,
            "remaining": max(0, target - total), "progress": min(100.0, round(total * 100 / target, 1)),
            "first_progress": min(100.0, round(total * 100 / first, 1)), "all_achieved": current is None}


def platform_stats(log: list[dict], config: dict) -> list[dict]:
    """플랫폼별 누적 수익/투자시간/실제 시급/예상 시급 대비 차이. 기록 없는 설정 플랫폼도 0으로 보여준다."""
    names = [p["name"] for p in config["platforms"]] + sorted({e["platform"] for e in log} - {p["name"] for p in config["platforms"]})
    out = []
    for name in names:
        rows = [e for e in log if e["platform"] == name]
        tasks = [e for e in rows if e.get("kind") == "task"]
        timed = [e for e in rows if e.get("actual_minutes")]
        est_won = sum(e["estimated_reward"] * e.get("point_value", 1) for e in tasks)
        est_min = sum(e["estimated_minutes"] for e in tasks)
        act_hourly = hourly(sum(won(e) for e in timed), sum(e["actual_minutes"] for e in timed))
        est_hourly = hourly(est_won, est_min)
        out.append({"platform": name, "count": len(rows), "earned": sum(won(e) for e in rows),
                    "minutes": sum(e["actual_minutes"] for e in rows), "actual_hourly": act_hourly,
                    "estimated_hourly": est_hourly,
                    "hourly_gap_pct": round((act_hourly - est_hourly) * 100 / est_hourly, 1) if act_hourly is not None and est_hourly else None,
                    "grade": grade(act_hourly, config["thresholds"]) if act_hourly is not None else None})
    return out


def open_tasks(tasks: list[dict], config: dict, now: datetime | None = None, *, sort: str = "hourly") -> list[dict]:
    """열린 작업 + 계산값(예상 시급, 등급, 마감 지남/남은 시간). 저장값은 바꾸지 않는다."""
    now = now or _now()
    rows = []
    for t in tasks:
        if t.get("status") != "open":
            continue
        rate = hourly(t["reward"] * t.get("point_value", 1), t["minutes"])
        deadline = datetime.fromisoformat(t["deadline"]) if t.get("deadline") else None
        rows.append({**t, "estimated_hourly": rate, "grade": grade(rate, config["thresholds"]),
                     "expired": bool(deadline and deadline <= now),
                     "minutes_left": int((deadline - now).total_seconds() // 60) if deadline and deadline > now else None})
    if sort == "new":
        rows.sort(key=lambda r: r["created_at"], reverse=True)
    elif sort == "deadline":
        rows.sort(key=lambda r: r["deadline"] or "9999")
    else:  # 예상 시급 높은 순
        rows.sort(key=lambda r: -(r["estimated_hourly"] or 0))
    return sorted(rows, key=lambda r: r["expired"])  # 마감 지난 작업은 항상 뒤로(안정 정렬)


def operator_status(tasks: list[dict], log: list[dict], config: dict, now: datetime | None = None) -> dict:
    """Operator Control Center용 요약(읽기 전용 값만)."""
    stats = period_stats(log, config, now)
    goal = goal_status(stats["total"]["earned"], config)
    return {"today": stats["today"]["earned"], "month": stats["month"]["earned"], "total": stats["total"]["earned"],
            "open_tasks": sum(1 for t in open_tasks(tasks, config, now) if not t["expired"]),
            "first_goal": goal["first_goal"], "first_goal_progress": goal["first_progress"], "first_achieved": goal["first_achieved"]}
