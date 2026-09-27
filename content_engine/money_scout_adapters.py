"""MONEY Browser Scout 플랫폼 어댑터(6-60) - 브라우저가 읽은 **화면 글자와 링크**만으로 기회를 뽑는다.

입력(브라우저 에이전트가 만든 raw 한 플랫폼 분량):
    {"page_url": str, "page_text": str(화면에 보이는 글자), "links": [{"text", "href"}]}
출력:
    {"status": SUCCESS | NO_OPPORTUNITY | LOGIN_REQUIRED | CAPTCHA_REQUIRED | APP_ONLY | PAGE_CHANGED | PARSE_FAILED,
     "items": [{"external_id", "title", "category", "type", "reward_text", "time_text", "url", "first_come", "notes"}],
     "asset_status": {...} | None, "detail": str}

CSS selector를 쓰지 않는다: 화면에 보이는 문구의 순서(PanelNow), 링크 주소의 의미 있는 경로(Heypoll)를 쓴다.
패턴이 안 맞으면 추측하지 않고 PAGE_CHANGED. 사이트 구조가 바뀌면 이 파일의 해당 함수만 고친다.
여기서는 값을 해석(숫자 변환·시급)하지 않는다 - 그건 content_engine.money_scout.normalize가 한다.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

# 진짜 사람 확인 화면에만 나오는 말(푸터의 'reCAPTCHA 서비스로 보호되며' 같은 안내문은 제외)
CAPTCHA_MARKERS = ("로봇이 아닙니다", "I'm not a robot", "보안문자를 입력", "자동입력 방지문자", "자동입력방지 문자", "캡차를 완료")
LOGIN_FORM_MARKERS = ("비밀번호", "아이디", "로그인 상태 유지", "인증번호 로그인")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def has_captcha(text: str) -> bool:
    return any(m.lower() in str(text or "").lower() for m in CAPTCHA_MARKERS)


def _result(status: str, items=None, detail: str = "", asset_status=None) -> dict:
    return {"status": status, "items": items or [], "detail": detail, "asset_status": asset_status}


# ---- PanelNow: /survey 목록(로그인 없이도 공개 목록이 보인다) ---------------------------------------

def parse_panelnow(raw: dict) -> dict:
    """화면 순서: [종류 '… 조사'] [제목] No. 응답시간 적립일정 포인트 [번호] [시간] [적립] [포인트] '설문 참여하기'.
    설문별 링크가 없으므로(버튼) url은 목록 페이지."""
    text = raw.get("page_text", "")
    if has_captcha(text):
        return _result("CAPTCHA_REQUIRED")
    lines = _lines(text)
    items = []
    for i, line in enumerate(lines):
        if line != "No." or lines[i + 1:i + 4] != ["응답시간", "적립일정", "포인트"] or i + 7 >= len(lines):
            continue
        ext, time_text, schedule, reward_text = lines[i + 4:i + 8]
        if not re.fullmatch(r"[a-z]\d{2,}", ext):
            return _result("PAGE_CHANGED", detail=f"설문 번호 형식이 예상과 다름: {ext[:20]!r}")
        title = lines[i - 1] if i >= 1 else ""
        category = lines[i - 2] if i >= 2 and lines[i - 2].endswith("조사") else ""
        items.append({"external_id": ext, "title": title, "category": category, "type": "survey",
                      "reward_text": reward_text, "time_text": time_text, "url": raw.get("page_url") or "https://www.panelnow.co.kr/survey",
                      "first_come": "선착순" in title, "notes": [schedule] if schedule and schedule != "실시간 적립" else []})
    if items:
        return _result("SUCCESS", items)
    if "설문조사" in text and "No." not in lines and any(m in text for m in LOGIN_FORM_MARKERS):
        return _result("LOGIN_REQUIRED")
    if "내게 온 설문조사" in text:
        return _result("NO_OPPORTUNITY", detail="목록 화면은 열렸지만 표시된 설문이 없음")
    return _result("PAGE_CHANGED", detail="설문 목록 문구(내게 온 설문조사/No./응답시간)를 찾지 못함")


# ---- Heypoll: 링크 주소에 설문 종류와 번호가 들어 있다 ----------------------------------------------

_HEYPOLL_PATH = re.compile(r"/?survey/(surveys|quick-surveys|polls)/(\d+)")
_HEYPOLL_TYPES = {"surveys": "survey", "quick-surveys": "quick_survey", "polls": "poll"}
_POINTS = re.compile(r"(\d[\d,]*)\s*P\b")


def parse_heypoll(raw: dict) -> dict:
    """링크 글자 예: '1,400P 기타 주류 관련 소비자 의견 조사(KR-09-Oww)', '퀵서베이 17/60 선착순 2배 50P'.
    화면에 소요시간이 없으므로 time_text는 비운다(추정하지 않음)."""
    if has_captcha(raw.get("page_text", "")):
        return _result("CAPTCHA_REQUIRED")
    items, seen = [], set()
    for link in raw.get("links") or []:
        href = unquote(str(link.get("href") or ""))
        m = _HEYPOLL_PATH.search(href)
        if not m:
            continue
        kind, number = m.group(1), m.group(2)
        if number in seen:
            continue
        seen.add(number)
        text = re.sub(r"\s+", " ", str(link.get("text") or "")).strip()
        points = _POINTS.findall(text)
        reward_text = f"{points[-1]}P" if points else ""
        title = text
        for noise in (r"\d[\d,]*\s*P\s*적립", r"\d[\d,]*\s*P\b", r"PICK", r"\d[\d,]*명 참여", r"\d+/\d+", r"선착순 [\d.]+배"):
            title = re.sub(noise, " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        category = ""
        if kind == "surveys":  # 'N P [분류] 제목' - 분류는 제목 앞 한 단어
            parts = title.split(" ", 1)
            if len(parts) == 2 and len(parts[0]) <= 8:
                category, title = parts
        items.append({"external_id": f"{_HEYPOLL_TYPES[kind]}-{number}", "title": title or ("퀵서베이" if kind == "quick-surveys" else ""),
                      "category": category, "type": _HEYPOLL_TYPES[kind], "reward_text": reward_text, "time_text": "",
                      "url": f"https://www.heypoll.co.kr/survey/{kind}/{number}", "first_come": "선착순" in text,
                      "notes": [n for n in re.findall(r"선착순 [\d.]+배|\d+/\d+", text)]})
    if items:
        return _result("SUCCESS", items)
    return _result("PAGE_CHANGED", detail="survey/surveys·quick-surveys·polls 링크를 찾지 못함")


# ---- Ovey: 웹은 앱 소개 페이지뿐(설문 목록은 앱 안) ---------------------------------------------------

def parse_ovey(raw: dict) -> dict:
    text = raw.get("page_text", "")
    if has_captcha(text):
        return _result("CAPTCHA_REQUIRED")
    if "앱 다운로드" in text and "No." not in text:
        return _result("APP_ONLY", detail="오베이 웹사이트에는 설문 목록이 없고 앱에서만 보인다(2026-09-27 확인)")
    return _result("PAGE_CHANGED", detail="앱 소개 화면이 아님 - 새 웹 목록이 생겼는지 사람이 확인 필요")


# ---- Naver AdPost: 설문이 아니라 내 콘텐츠 광고 수익 상태(ASSET / REVENUE STATUS) ----------------------

_WON = r"([\d,]+)\s*원"


def parse_adpost(raw: dict) -> dict:
    """로그인 후 수익 화면 글자에서 금액만 읽는다(광고 클릭·노출 관련 행동 없음). 기회(items)는 만들지 않는다."""
    text = raw.get("page_text", "")
    if has_captcha(text):
        return _result("CAPTCHA_REQUIRED")
    lines = _lines(text)
    if any(m in text for m in LOGIN_FORM_MARKERS) and not re.search(_WON, text):
        return _result("LOGIN_REQUIRED")

    def amount_after(*labels: str) -> int | None:
        for i, line in enumerate(lines):
            if any(label in line for label in labels):
                for candidate in [line] + lines[i + 1:i + 3]:
                    m = re.search(_WON, candidate)
                    if m:
                        return int(m.group(1).replace(",", ""))
        return None

    status = {"current_revenue": amount_after("이번 달 수입", "당월 수입", "이번달 수익", "당월 수익"),
              "total_revenue": amount_after("누적 수입", "누적 수익"),
              "payable": amount_after("지급 가능", "지급 예정"),
              "notice": next((line[:80] for line in lines if "공지" in line), None)}
    if all(v is None for k, v in status.items() if k != "notice"):
        return _result("PAGE_CHANGED", detail="수입 금액 문구를 찾지 못함")
    return _result("SUCCESS", [], asset_status=status)


ADAPTERS = {"panelnow": parse_panelnow, "heypoll": parse_heypoll, "ovey": parse_ovey, "adpost": parse_adpost}
