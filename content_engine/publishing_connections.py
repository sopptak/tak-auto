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
        "login_url": "https://accounts.google.com/ServiceLogin?service=youtube",
        "required": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"),
        "account_env": "YOUTUBE_CHANNEL_NAME", "expiry_env": "",
        "renewal": "토큰이 만료되면 이 화면에서 계정을 다시 연결하세요.",
        "publish_note": "YouTube Shorts 게시 어댑터는 승인 대기열에서 비공개 업로드로 동작합니다. 웹 OAuth 연결과 MP4 등록이 필요합니다.",
    },
    {
        "key": "tiktok", "name": "TikTok", "icon": "♪",
        "login_url": "https://www.tiktok.com/login",
        "required": ("TIKTOK_ACCESS_TOKEN", "TIKTOK_OPEN_ID"),
        "account_env": "TIKTOK_USERNAME", "expiry_env": "TIKTOK_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰이 만료되면 이 화면에서 계정을 다시 연결하세요.",
        "publish_note": "TikTok Direct Post는 video.publish 권한, 앱 승인, 명시적 공개 범위 선택과 MP4 등록이 필요합니다.",
    },
    {
        "key": "instagram_reels", "name": "Instagram Reels", "icon": "◎",
        "login_url": "https://www.instagram.com/accounts/login/",
        "required": ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"),
        "account_env": "INSTAGRAM_USERNAME", "expiry_env": "INSTAGRAM_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰이 만료되면 이 화면에서 계정을 다시 연결하세요.",
        "publish_note": "Instagram Reels 게시 어댑터는 Instagram 프로페셔널 계정 권한과 공개 HTTPS 영상 URL이 필요합니다.",
    },
    {
        "key": "facebook", "name": "Facebook 페이지", "icon": "f",
        "login_url": "https://www.facebook.com/login/",
        "required": ("FACEBOOK_ACCESS_TOKEN", "FACEBOOK_PAGE_ID"),
        "account_env": "FACEBOOK_PAGE_NAME", "expiry_env": "FACEBOOK_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰이 만료되면 이 화면에서 계정을 다시 연결하세요.",
        "publish_note": "Facebook 페이지 게시에는 pages_manage_posts, pages_read_engagement 권한과 선택한 페이지의 CREATE_CONTENT 작업 권한이 필요합니다.",
    },
    {
        "key": "threads", "name": "Threads", "icon": "@",
        "login_url": "https://www.threads.net/login",
        "required": ("THREADS_ACCESS_TOKEN",),
        "account_env": "THREADS_USERNAME", "expiry_env": "THREADS_ACCESS_TOKEN_EXPIRES_AT",
        "renewal": "토큰이 만료되면 이 화면에서 계정을 다시 연결하세요.",
        "publish_note": "Threads 웹 연결 토큰은 게시 권한 동의 시 텍스트 게시 어댑터에서 사용합니다. 게시 스위치와 운영자 승인은 별도로 필요합니다.",
    },
    {
        "key": "blog", "name": "네이버 블로그", "icon": "N",
        "login_url": "https://nid.naver.com/nidlogin.login",
        "required": (), "account_env": "NAVER_BLOG_NAME", "expiry_env": "",
        "renewal": "자동 계정 토큰 없음 · 게시 후 사람이 완료 처리해야 합니다.",
        "publish_note": "네이버 블로그 글쓰기 API 종료로 자동 게시를 지원하지 않습니다.",
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
        publish_note = str(platform["publish_note"])
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
            if platform["key"] == "threads":
                granted_scopes = {
                    scope for scope in str(oauth_connection.get("granted_scopes", "")).replace(",", " ").split() if scope
                }
                if "threads_content_publish" in granted_scopes:
                    publish_note = "Threads 게시 권한이 연결되었습니다. 실제 게시에는 게시 스위치와 운영자 승인이 필요합니다."
                else:
                    publish_note = "계정은 연결됐지만 Threads 게시 권한이 없습니다. 다시 연결해 게시 권한에 동의해야 합니다."
            if platform["key"] == "facebook":
                granted_scopes = {
                    scope for scope in str(oauth_connection.get("granted_scopes", "")).replace(",", " ").split() if scope
                }
                required_scopes = {"pages_show_list", "pages_read_engagement", "pages_manage_posts"}
                raw_page_tasks = oauth_connection.get("tasks", [])
                page_tasks = (
                    {str(task) for task in raw_page_tasks}
                    if isinstance(raw_page_tasks, (list, tuple, set))
                    else {task for task in str(raw_page_tasks).replace(",", " ").split() if task}
                )
                if not required_scopes.issubset(granted_scopes):
                    publish_note = "페이지는 연결됐지만 게시 권한이 부족합니다. pages_manage_posts 및 pages_read_engagement 권한으로 다시 연결하세요."
                elif not {"CREATE_CONTENT", "MANAGE"}.intersection(page_tasks):
                    publish_note = "페이지는 연결됐지만 CREATE_CONTENT 또는 MANAGE 작업 권한이 없습니다. 게시 권한이 있는 페이지를 다시 선택하세요."
                else:
                    publish_note = "Facebook 페이지 게시 권한과 CREATE_CONTENT 또는 MANAGE 작업 권한이 확인되었습니다."
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
            "login_url": platform["login_url"],
            "state": state, "label": label, "account_name": account_name or "계정명 확인 필요",
            "missing": missing, "expires_in": expires_in, "renewal": platform["renewal"],
            "publish_note": publish_note,
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
<div class="connection-heading"><a class="connection-icon connection-login-icon" href="{escape(str(row['login_url']), quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="{escape(str(row['name']), quote=True)} 로그인 페이지를 새 탭으로 열기" title="{escape(str(row['name']), quote=True)} 로그인"><span aria-hidden="true">{escape(str(row['icon']))}</span><span class="connection-external-mark" aria-hidden="true">↗</span></a><b>{escape(str(row['name']))}</b><span class="connection-state">{escape(str(row['label']))}</span></div>
<p class="connection-account">{account}</p>{expiry}{checked_at}{verification_message}{verify_control}
<p class="meta">{escape(str(row['renewal']))}</p>
<p class="connection-note">{escape(str(row['publish_note']))}</p>
{f'<p class="connection-missing">필요 설정: {escape(missing)}</p>' if missing else ''}
</article>""")
    enabled_label = "활성화" if publishing_enabled else "비활성화 (기본값)"
    return f"""<section class="toolbar" id="account-connections">
<h2>게시 계정 연결 현황</h2>
<p>예약 게시 스위치: <b>{enabled_label}</b> · 게시 어댑터: <b>{'설정됨' if adapter_configured else '미설정'}</b> · Threads 게시 권한은 승인된 대기열에서만 사용합니다. 게시 기능은 기본 비활성화입니다. 인증 토큰 원문은 이 화면에 표시하지 않습니다.</p>
<p class="connection-login-note">서비스 아이콘을 누르면 해당 SNS 로그인 페이지가 새 탭으로 열립니다. 그곳에서 로그인하는 것만으로 TAK AUTO 연결 상태가 바뀌지는 않습니다.</p>
{f'<p class="connection-verification-error">{escape(oauth_storage_error)}</p>' if oauth_storage_error else ''}
<div class="connection-grid">{''.join(cards)}</div>
</section>"""
