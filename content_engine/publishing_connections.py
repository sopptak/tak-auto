"""Safe, read-only publishing-account configuration status for the dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import os
from typing import Mapping


PLATFORMS = (
    {
        "key": "youtube_shorts", "name": "YouTube Shorts", "icon": "▶",
        "required": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"),
        "account_env": "YOUTUBE_CHANNEL_NAME", "expiry_env": "",
        "renewal": "OAuth refresh token 설정 시 액세스 토큰을 자동 갱신합니다.",
        "publish_note": "게시하려면 승인된 MP4 영상 파일도 필요합니다.",
    },
    {
        "key": "tiktok", "name": "TikTok", "icon": "♪",
        "required": ("TIKTOK_ACCESS_TOKEN", "TIKTOK_OPEN_ID"),
        "account_env": "TIKTOK_USERNAME", "expiry_env": "TIKTOK_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰 만료일은 설정된 경우에 표시됩니다.",
        "publish_note": "게시하려면 TikTok 개발자 앱 승인과 MP4 파일이 필요합니다.",
    },
    {
        "key": "instagram_reels", "name": "Instagram Reels", "icon": "◎",
        "required": ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"),
        "account_env": "INSTAGRAM_USERNAME", "expiry_env": "INSTAGRAM_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰 만료일은 설정된 경우에 표시됩니다.",
        "publish_note": "프로페셔널 계정, 게시 권한, MP4 미디어가 필요합니다.",
    },
    {
        "key": "facebook", "name": "Facebook 페이지", "icon": "f",
        "required": ("FACEBOOK_ACCESS_TOKEN", "FACEBOOK_PAGE_ID"),
        "account_env": "FACEBOOK_PAGE_NAME", "expiry_env": "FACEBOOK_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰 만료일은 설정된 경우에 표시됩니다.",
        "publish_note": "페이지 권한을 확인하고 게시 어댑터를 연결해야 합니다.",
    },
    {
        "key": "threads", "name": "Threads", "icon": "@",
        "required": ("THREADS_ACCESS_TOKEN",),
        "account_env": "THREADS_USERNAME", "expiry_env": "THREADS_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰 만료일은 설정된 경우에 표시됩니다.",
        "publish_note": "Threads 텍스트 게시 API가 지원됩니다.",
    },
    {
        "key": "blog", "name": "네이버 블로그", "icon": "N",
        "required": (), "account_env": "NAVER_BLOG_NAME", "expiry_env": "",
        "renewal": "자동 계정 토큰 없음 · 게시 후 사람이 완료 처리해야 합니다.",
        "publish_note": "네이버 블로그 글쓰기 API가 종료되어 자동 게시를 지원하지 않습니다.",
        "manual": True,
    },
)


def _expiry_label(value: str, now: datetime) -> tuple[str, str]:
    if not value:
        return "만료일 미등록", "unknown"
    try:
        normalized = value.strip().replace("Z", "+00:00")
        expires_at = datetime.fromisoformat(normalized)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        seconds = (expires_at.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return "만료일 형식 오류", "invalid"
    if seconds <= 0:
        return "토큰 만료됨", "expired"
    days = int(seconds // 86400)
    if days:
        return f"{days}일 후 만료", "valid"
    hours = max(1, int(seconds // 3600))
    return f"{hours}시간 후 만료", "valid"


def publishing_connection_statuses(
    environ: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    values = os.environ if environ is None else environ
    current = now or datetime.now(timezone.utc)
    statuses = []
    for platform in PLATFORMS:
        required = platform["required"]
        missing = [name for name in required if not values.get(name, "").strip()]
        manual = bool(platform.get("manual"))
        account_name = values.get(platform["account_env"], "").strip()
        expires_in = ""
        expiry_state = "not_applicable"
        if platform["expiry_env"]:
            expires_in, expiry_state = _expiry_label(values.get(platform["expiry_env"], ""), current)
        if manual:
            state, label = "manual", "수동 게시"
        elif missing:
            state, label = "missing", "미연결"
        elif expiry_state == "expired":
            state, label = "expired", "토큰 만료"
        elif expiry_state == "invalid":
            state, label = "attention", "만료일 확인 필요"
        else:
            state, label = "configured", "인증 정보 설정됨 · 계정 확인 전"
        statuses.append({
            "key": platform["key"], "name": platform["name"], "icon": platform["icon"],
            "state": state, "label": label, "account_name": account_name or "계정명 확인 필요",
            "missing": missing, "expires_in": expires_in, "renewal": platform["renewal"],
            "publish_note": platform["publish_note"],
        })
    return statuses


def connection_dashboard(
    environ: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
) -> str:
    values = os.environ if environ is None else environ
    publishing_enabled = values.get("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true"
    adapter_configured = bool(values.get("TAK_AUTO_PUBLISHER", "").strip())
    statuses = publishing_connection_statuses(values, now=now)
    cards = []
    for row in statuses:
        state = str(row["state"])
        missing = ", ".join(str(name) for name in row["missing"])
        account = escape(str(row["account_name"]))
        expiry = f'<p class="connection-expiry">{escape(str(row["expires_in"]))}</p>' if row["expires_in"] else ""
        cards.append(f"""<article class="connection-card state-{escape(state)}">
<div class="connection-heading"><span class="connection-icon">{escape(str(row['icon']))}</span><b>{escape(str(row['name']))}</b><span class="connection-state">{escape(str(row['label']))}</span></div>
<p class="connection-account">{account}</p>{expiry}
<p class="meta">{escape(str(row['renewal']))}</p>
<p class="connection-note">{escape(str(row['publish_note']))}</p>
{f'<p class="connection-missing">필요 설정: {escape(missing)}</p>' if missing else ''}
</article>""")
    enabled_label = "활성화" if publishing_enabled else "비활성화 (기본값)"
    return f"""<section class="toolbar" id="account-connections">
<h2>게시 계정 연결 현황</h2>
<p>예약 게시 스위치: <b>{enabled_label}</b> · 게시 어댑터: <b>{'설정됨' if adapter_configured else '미설정'}</b> · 인증 토큰 원문은 이 화면에 표시하지 않습니다.</p>
<div class="connection-grid">{''.join(cards)}</div>
</section>"""
