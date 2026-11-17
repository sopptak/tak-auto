"""Safe, read-only publishing-account configuration status for the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import os
from typing import Mapping
from urllib.parse import urlsplit

from .threads_publisher import ThreadsClient
from .youtube_publisher import YouTubeClient


VERIFY_PLATFORMS = frozenset({"threads", "youtube_shorts"})


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


def verify_publishing_connection(platform: str, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Make an explicit read-only API check for platforms with a profile endpoint."""
    if platform == "threads":
        client = ThreadsClient.from_environment(environ)
        api_url = urlsplit(client.api_base)
        if api_url.scheme != "https" or api_url.hostname != "graph.threads.net":
            raise ValueError("Threads 계정 확인은 공식 HTTPS API 주소에서만 실행할 수 있습니다.")
        profile = client.get_profile()
        return {"account_id": profile.id, "account_name": profile.username}
    if platform == "youtube_shorts":
        profile = YouTubeClient.from_environment(environ).get_channel_profile()
        return {"account_id": profile.channel_id, "account_name": profile.title}
    raise ValueError("이 플랫폼의 API 계정 확인은 아직 지원하지 않습니다.")


def publishing_connection_statuses(
    environ: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    verification_cache: Mapping[str, Mapping[str, str]] | None = None,
    oauth_connections: Mapping[str, Mapping[str, str]] | None = None,
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
        verification = (verification_cache or {}).get(platform["key"], {})
        oauth_connection = (oauth_connections or {}).get(platform["key"], {})
        verification_message = ""
        checked_at_label = ""
        oauth_connected = isinstance(oauth_connection, Mapping) and bool(oauth_connection.get("account_id"))
        if oauth_connected:
            account_name = str(oauth_connection.get("account_name") or account_name)
            checked_at = str(oauth_connection.get("connected_at", ""))
            if checked_at:
                try:
                    connected_at = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
                    if connected_at.tzinfo is None:
                        connected_at = connected_at.replace(tzinfo=timezone.utc)
                    checked_at_label = "연결 시각: " + connected_at.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
                except (TypeError, ValueError):
                    checked_at_label = ""
            linked_expiry = str(oauth_connection.get("expires_at", ""))
            if linked_expiry:
                expires_in, expiry_state = _expiry_label(linked_expiry, current)
                if expiry_state == "expired":
                    state, label = "expired", "토큰 만료 · 다시 연결 필요"
                elif expiry_state == "invalid":
                    state, label = "attention", "만료일 확인 필요"
                else:
                    state, label = "verified", "계정 연결됨"
            else:
                state, label = "verified", "계정 연결됨"
            missing = []
        elif isinstance(verification, Mapping) and verification.get("checked_at"):
            try:
                checked_at = datetime.fromisoformat(str(verification["checked_at"]).replace("Z", "+00:00"))
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                age_seconds = (current.astimezone(timezone.utc) - checked_at.astimezone(timezone.utc)).total_seconds()
                checked_at_label = "마지막 확인: " + checked_at.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
                if state not in {"missing", "expired", "manual"} and expiry_state != "invalid":
                    if 0 <= age_seconds <= 86400 and verification.get("status") == "verified":
                        state, label = "verified", "연결 확인됨"
                        account_name = str(verification.get("account_name") or account_name)
                    elif 0 <= age_seconds <= 86400 and verification.get("status") == "failed":
                        state, label = "verification_failed", "연결 확인 실패"
                        verification_message = str(verification.get("message") or "플랫폼 계정을 확인할 수 없습니다.")
                        account_name = str(verification.get("account_name") or account_name)
                    elif age_seconds > 86400:
                        state, label = "attention", "재확인 필요"
            except (TypeError, ValueError):
                state, label = "attention", "확인 시각 오류"
        statuses.append({
            "key": platform["key"], "name": platform["name"], "icon": platform["icon"],
            "state": state, "label": label, "account_name": account_name or "계정명 확인 필요",
            "missing": missing, "expires_in": expires_in, "renewal": platform["renewal"],
            "publish_note": platform["publish_note"],
            "verification_supported": platform["key"] in VERIFY_PLATFORMS,
            "verification_message": verification_message, "checked_at_label": checked_at_label,
        })
    return statuses


def connection_dashboard(
    environ: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    verification_cache: Mapping[str, Mapping[str, str]] | None = None,
    oauth_connections: Mapping[str, Mapping[str, str]] | None = None,
    oauth_setup: Mapping[str, Mapping[str, object]] | None = None,
    oauth_storage_error: str = "",
) -> str:
    values = os.environ if environ is None else environ
    publishing_enabled = values.get("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true"
    adapter_configured = bool(values.get("TAK_AUTO_PUBLISHER", "").strip())
    statuses = publishing_connection_statuses(values, now=now, verification_cache=verification_cache,
                                               oauth_connections=oauth_connections)
    cards = []
    for row in statuses:
        state = str(row["state"])
        setup = (oauth_setup or {}).get(str(row["key"]), {})
        missing = ", ".join(str(name) for name in setup.get("missing", [])) if setup else ", ".join(str(name) for name in row["missing"])
        account = escape(str(row["account_name"]))
        expiry = f'<p class="connection-expiry">{escape(str(row["expires_in"]))}</p>' if row["expires_in"] else ""
        verification_message = f'<p class="connection-verification-error">{escape(str(row["verification_message"]))}</p>' if row["verification_message"] else ""
        checked_at = f'<p class="meta">{escape(str(row["checked_at_label"]))}</p>' if row["checked_at_label"] else ""
        connected = isinstance(oauth_connections, Mapping) and bool(oauth_connections.get(str(row["key"]), {}).get("account_id"))
        connect_controls = ""
        if connected:
            connect_controls = f'''<p><a class="button connection-button" href="/connections/oauth/{escape(str(row['key']))}">계정 다시 연결</a></p>
<form method="post" action="/connections/disconnect"><input type="hidden" name="platform" value="{escape(str(row['key']))}"><button class="secondary" type="submit">이 앱에서 연결 해제</button></form>'''
        elif setup.get("ready"):
            connect_controls = f'<p><a class="button connection-button" href="/connections/oauth/{escape(str(row["key"]))}">계정 연결</a></p>'
        elif setup:
            missing_setup = ", ".join(str(name) for name in setup.get("missing", []))
            redirect_uri = str(setup.get("redirect_uri", ""))
            connect_controls = f'''<p><button type="button" class="secondary" disabled>계정 연결 설정 필요</button></p>
<p class="meta">웹 연결 준비에 필요한 서비스 설정을 먼저 완료하세요.</p>
<details><summary>연결 설정 보기</summary><p class="connection-missing">필요 설정: {escape(missing_setup)}</p>
{f'<p class="meta">OAuth 콜백 주소: <code>{escape(redirect_uri)}</code></p>' if redirect_uri else ''}</details>'''
            if row["verification_supported"] and not row["missing"] and state != "expired":
                connect_controls += f'<form method="post" action="/connections/verify"><input type="hidden" name="platform" value="{escape(str(row["key"]))}"><button type="submit" class="secondary">기존 토큰 확인</button></form>'
        if connect_controls:
            verify_control = connect_controls
        elif row["verification_supported"] and not row["missing"] and state != "expired":
            verify_control = f'<form method="post" action="/connections/verify"><input type="hidden" name="platform" value="{escape(str(row["key"]))}"><button type="submit" class="secondary">계정 연결 확인</button></form>'
        elif row["verification_supported"] and row["missing"]:
            verify_control = '<p class="meta">필수 인증 정보를 설정하면 API 확인을 실행할 수 있습니다.</p>'
        elif not row["verification_supported"] and state != "manual":
            verify_control = '<p class="meta">API 계정 확인 기능 준비 중</p>'
        else:
            verify_control = ""
        cards.append(f"""<article class="connection-card state-{escape(state)}">
<div class="connection-heading"><span class="connection-icon">{escape(str(row['icon']))}</span><b>{escape(str(row['name']))}</b><span class="connection-state">{escape(str(row['label']))}</span></div>
<p class="connection-account">{account}</p>{expiry}{checked_at}{verification_message}{verify_control}
<p class="meta">{escape(str(row['renewal']))}</p>
<p class="connection-note">{escape(str(row['publish_note']))}</p>
{f'<p class="connection-missing">필요 설정: {escape(missing)}</p>' if missing else ''}
</article>""")
    enabled_label = "활성화" if publishing_enabled else "비활성화 (기본값)"
    return f"""<section class="toolbar" id="account-connections">
<h2>게시 계정 연결 현황</h2>
<p>예약 게시 스위치: <b>{enabled_label}</b> · 게시 어댑터: <b>{'설정됨' if adapter_configured else '미설정'}</b> · SNS 로그인은 계정만 연결하며 게시 기능을 켜지 않습니다. 인증 토큰 원문은 이 화면에 표시하지 않습니다.</p>
{f'<p class="connection-verification-error">{escape(oauth_storage_error)}</p>' if oauth_storage_error else ''}
<div class="connection-grid">{''.join(cards)}</div>
</section>"""
