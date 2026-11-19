#!/usr/bin/env python3
"""Local web MVP: discover current trends with Perplexity and preview traffic content."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
from http.cookies import SimpleCookie
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse, unquote
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from content_engine.generator import generate_content_bundle
from content_engine.media_assets import MediaAssetError, MediaAssetStore
from content_engine.publishing_connections import (
    VERIFY_PLATFORMS, connection_dashboard, publishing_connection_statuses,
    verify_publishing_connection,
)
from content_engine.publishing_queue import PublishingQueue, queue_dashboard
from content_engine.performance_insight import load_insights, STATUS_ACCEPTED
from content_engine.social_oauth import (
    FLOW_TTL_SECONDS, OAuthFlowRegistry, OAuthTokenVault, PROVIDERS, SocialOAuthClient,
    SocialOAuthError, build_callback_error_page, callback_uri, facebook_page_selection_page, setup_status,
)
from scripts.run_publishing_queue import start_scheduler
from tak_brain.models import KnowledgeRecord
from tak_scout.perplexity_research import PerplexityResearchProvider
from tak_scout.trend_discovery import TrendDiscovery, TrendItem, discover_trends

KST = ZoneInfo("Asia/Seoul")
STATE_MUTATION_LOCK = threading.RLock()
_JSON_REPLACE_LOCK = threading.Lock()
def _has_persistent_mount(path: Path) -> bool:
    """Check the configured data directory itself, which matches Render mountPath."""
    return os.path.ismount(path.expanduser().absolute())

def _resolve_writable_data_dir(configured: Path) -> tuple[Path, bool]:
    """Use the configured data directory when writable; otherwise use ephemeral /tmp."""
    fallback = Path(tempfile.gettempdir()) / "tak-auto-data"
    is_render = bool(os.getenv("RENDER_SERVICE_ID") or os.getenv("RENDER_GIT_COMMIT"))
    # On Render, a writable directory is not proof that the Persistent Disk mounted.
    candidates = [(configured, False)] if not is_render or _has_persistent_mount(configured) else []
    if fallback != configured or not candidates:
        candidates.append((fallback, True))
    for candidate, is_fallback in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".tak-auto-write-test-", dir=candidate, delete=True):
                pass
            return candidate, is_fallback
        except OSError:
            continue
    # Preserve the original configured path so the first write returns a clear error.
    return configured, False


CONFIGURED_DATA_DIR = Path(os.getenv("TAK_AUTO_DATA_DIR", str(ROOT / "data"))).expanduser()
DATA_DIR, USING_EPHEMERAL_STORAGE = _resolve_writable_data_dir(CONFIGURED_DATA_DIR)
TREND_PATH = DATA_DIR / "tak_auto_live_trends.json"
PREVIEW_PATH = DATA_DIR / "tak_auto_content_previews.json"
INSIGHTS_PATH = DATA_DIR / "tak_performance_insights.json"
QUEUE_PATH = DATA_DIR / "tak_auto_publishing_queue.json"
CONNECTION_CHECKS_PATH = DATA_DIR / "publishing_connection_checks.json"
OAUTH_TOKENS_PATH = DATA_DIR / "social_oauth_tokens.enc"
MEDIA_ASSETS_DIR = DATA_DIR / "media_assets"
MEDIA_ASSETS_PATH = DATA_DIR / "tak_auto_media_assets.json"
OAUTH_FLOW_REGISTRY = OAuthFlowRegistry()
_PENDING_FACEBOOK_CHOICES: dict[str, dict[str, object]] = {}


def _basic_auth_valid(header: str, username: str, password: str) -> bool:
    """Constant-time Basic Auth check; never logs credentials."""
    if not username or not password or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    supplied_user, separator, supplied_password = decoded.partition(":")
    return bool(separator) and hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_password, password)


def _origin_key(value: str, *, allow_root_path: bool = False) -> tuple[str, str, int] | None:
    """Normalize an HTTP origin, including default ports, without accepting URL paths."""
    try:
        parsed = urlparse(value)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return None
    if parsed.path not in ({"", "/"} if allow_root_path else {""}) or parsed.params or parsed.query or parsed.fragment:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname, port


def _same_origin(
    origin: str,
    host: str,
    forwarded_proto: str,
    trusted_public_url: str = "",
) -> bool:
    """Reject cross-origin form submissions, including behind HTTPS proxies."""
    if not origin or not host:
        return False
    supplied_origin = _origin_key(origin)
    if supplied_origin is None:
        return False

    # The configured public URL is authoritative behind a reverse proxy: the
    # proxy may rewrite Host or append a default port before this handler sees it.
    configured_origin = _origin_key(trusted_public_url, allow_root_path=True) if trusted_public_url.strip() else None
    if configured_origin is not None:
        return supplied_origin == configured_origin

    request_host = urlparse(f"//{host}")
    request_hostname = (request_host.hostname or "").lower().rstrip(".")
    is_loopback = request_hostname == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(request_hostname).is_loopback
        except ValueError:
            pass
    # Local preview is served over plain HTTP; some browser bridges still attach
    # an HTTPS forwarded-proto header. Restrict this exception to loopback hosts.
    expected_scheme = "http" if is_loopback else (forwarded_proto or "https").split(",")[0].strip().lower()
    expected_origin = _origin_key(f"{expected_scheme}://{host}")
    return expected_origin is not None and supplied_origin == expected_origin


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> None:
    """Durably replace a JSON file using a unique same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.name}.",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            pass
        # Windows can transiently reject overlapping replacements of the same
        # destination. Serialize the commit step while still allowing callers
        # to prepare unique temporary files concurrently.
        with _JSON_REPLACE_LOCK:
            for attempt in range(6):
                try:
                    os.replace(temporary_name, path)
                    break
                except PermissionError:
                    if os.name != "nt" or attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        temporary_name = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _read_connection_checks() -> dict:
    try:
        checks = _read_json(CONNECTION_CHECKS_PATH, {})
    except (OSError, json.JSONDecodeError):
        return {}
    return checks if isinstance(checks, dict) else {}


def _oauth_vault() -> OAuthTokenVault:
    return OAuthTokenVault(OAUTH_TOKENS_PATH, os.getenv("TAK_AUTO_OAUTH_ENCRYPTION_KEY", ""))


def _media_asset_store() -> MediaAssetStore:
    return MediaAssetStore(
        DATA_DIR,
        os.getenv("TAK_AUTO_MEDIA_SIGNING_KEY", ""),
        os.getenv("TAK_AUTO_PUBLIC_URL", ""),
    )


def _list_media_assets() -> list:
    try:
        return _media_asset_store().list_assets()
    except MediaAssetError:
        return []


def _read_oauth_connections(environ=None) -> tuple[dict[str, dict[str, str]], str]:
    values = os.environ if environ is None else environ
    encryption_key = str(values.get("TAK_AUTO_OAUTH_ENCRYPTION_KEY", "")).strip()
    if not encryption_key:
        return {}, ""
    try:
        if environ is None:
            vault = _oauth_vault()
        else:
            data_dir = Path(values.get("TAK_AUTO_DATA_DIR", str(DATA_DIR)))
            vault = OAuthTokenVault(data_dir / "social_oauth_tokens.enc", encryption_key)
        return vault.public_connections(), ""
    except SocialOAuthError as error:
        return {}, str(error)


def _oauth_setup_statuses(storage_error: str = "") -> dict[str, dict[str, object]]:
    statuses = {platform: setup_status(platform) for platform in PROVIDERS}
    if storage_error:
        for status in statuses.values():
            status["ready"] = False
            status["missing"] = [*status.get("missing", []), "SNS 암호화 저장소 확인"]
    return statuses


def _cookie_value(header: str, name: str) -> str:
    parsed = SimpleCookie()
    try:
        parsed.load(header)
        morsel = parsed.get(name)
        return morsel.value if morsel else ""
    except Exception:
        return ""


def _oauth_cookie(name: str, value: str, *, secure: bool, clear: bool = False) -> str:
    age = 0 if clear else FLOW_TTL_SECONDS
    return f"{name}={value}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")


def _oauth_cookie_is_secure(platform: str) -> bool:
    """Derive Secure from the registered HTTPS callback, not a client header."""
    try:
        return urlparse(callback_uri(platform)).scheme == "https"
    except SocialOAuthError:
        return False


def _health_payload(environ=None) -> dict[str, object]:
    values = os.environ if environ is None else environ
    raw_revision = str(values.get("RENDER_GIT_COMMIT", "")).strip().lower()
    revision = raw_revision[:12] if len(raw_revision) == 40 and all(char in "0123456789abcdef" for char in raw_revision) else None
    perplexity_ready = bool(values.get("TAK_SCOUT_PERPLEXITY_API_KEY"))
    auth_ready = bool(values.get("TAK_WEB_USERNAME") and values.get("TAK_WEB_PASSWORD"))
    publishing_enabled = str(values.get("TAK_AUTO_PUBLISHING_ENABLED", "")).strip().lower() == "true"
    publisher_configured = bool(str(values.get("TAK_AUTO_PUBLISHER", "")).strip())
    return {
        "status": "ok", "perplexity_configured": perplexity_ready,
        "web_auth_configured": auth_ready, "publishing_enabled": publishing_enabled,
        "publisher_adapter_configured": publisher_configured,
        "storage_persistent": not USING_EPHEMERAL_STORAGE,
        "storage_mode": "persistent_disk" if not USING_EPHEMERAL_STORAGE else "ephemeral_fallback",
        "ready": perplexity_ready and auth_ready and not USING_EPHEMERAL_STORAGE and (not publishing_enabled or publisher_configured), "revision": revision,
    }


def _run_connection_verification(
    platform: str, checks: dict, *, environ=None, now=None,
    oauth_connections: dict[str, dict[str, str]] | None = None,
) -> tuple[dict, str]:
    """Check one supported account and return a safe status-cache update."""
    if platform not in VERIFY_PLATFORMS:
        raise ValueError("현재 API 계정 확인을 지원하지 않는 플랫폼입니다.")
    values = os.environ if environ is None else environ
    current = now or datetime.now(timezone.utc)
    if oauth_connections is None:
        oauth_connections, storage_error = _read_oauth_connections(values)
        if storage_error:
            raise ValueError("SNS 암호화 저장소를 확인할 수 없습니다. 연결 설정을 점검하세요.")
    rows = {
        row["key"]: row
        for row in publishing_connection_statuses(values, oauth_connections=oauth_connections)
    }
    status = rows[platform]
    if status["missing"]:
        raise ValueError("필요한 인증 환경변수를 먼저 설정하세요: " + ", ".join(status["missing"]))
    if status["state"] == "expired":
        raise ValueError("토큰이 만료되어 계정을 확인할 수 없습니다.")
    try:
        profile = verify_publishing_connection(platform, values)
        checks[platform] = {
            "status": "verified", "account_id": profile["account_id"],
            "account_name": profile["account_name"], "checked_at": current.isoformat(),
        }
        message = f"{status['name']} 계정 연결을 확인했습니다: {profile['account_name']}"
    except (ValueError, RuntimeError) as error:
        account_env = "THREADS_USERNAME" if platform == "threads" else "YOUTUBE_CHANNEL_NAME"
        checks[platform] = {
            "status": "failed", "account_name": values.get(account_env, ""),
            "message": str(error)[:240], "checked_at": current.isoformat(),
        }
        message = f"{status['name']} 계정 확인 실패: {error}"
    return checks, message


def _select_accepted_strategy_insights(
    insight_ids: list[str], *, path: Path | str = INSIGHTS_PATH, limit: int = 5,
) -> list[dict]:
    """Return only explicitly selected, human-accepted insight summaries.

    Candidate/rejected/unknown IDs are never passed to content generation. The
    caller must submit the IDs in the current /generate form; acceptance alone
    never triggers automatic generation or changes to strategy.
    """
    selected = list(dict.fromkeys(str(value).strip() for value in insight_ids if str(value).strip()))
    if len(selected) > limit:
        raise ValueError(f"성과 인사이트는 한 번에 최대 {limit}개까지 선택할 수 있습니다.")
    by_id = {row.insight_id: row for row in load_insights(path)}
    missing = [value for value in selected if value not in by_id]
    if missing:
        raise ValueError("선택한 성과 인사이트를 찾을 수 없습니다. 화면을 새로고침하세요.")
    unapproved = [value for value in selected if by_id[value].status != STATUS_ACCEPTED]
    if unapproved:
        raise ValueError("사람이 승인한 성과 인사이트만 콘텐츠 생성에 참고할 수 있습니다.")
    result = []
    for value in selected:
        row = by_id[value]
        if row.result == "INSUFFICIENT_SAMPLE":
            raise ValueError("표본 부족 인사이트는 콘텐츠 전략 참고자료로 사용할 수 없습니다.")
        result.append({
            "insight_id": row.insight_id,
            "platform": row.platform,
            "metric": row.metric,
            "insight_type": row.insight_type,
            "result": row.result,
            "observation": row.observation[:500],
            "sample_size": row.sample_size,
        })
    return result


def _build_content_prompt(
    item: dict, trend_report: dict, strategy_insights: list[dict] | None = None,
) -> str:
    sources = item.get("source_urls") or trend_report.get("citations") or []
    facts = {
        "keyword": item.get("keyword"),
        "category": item.get("category"),
        "summary": item.get("summary"),
        "why_now": item.get("why_now"),
        "audience_question": item.get("audience_question"),
        "content_angle": item.get("content_angle"),
        "key_points": item.get("key_points", []),
        "verified_source_urls": sources,
        "research_date": trend_report.get("researched_at"),
        "human_accepted_performance_insights": strategy_insights or [],
    }
    return f"""당신은 한국어 검색 유입과 영상 시청 지속시간을 설계하는 전문 콘텐츠 에디터입니다.
아래 Perplexity 트렌드 조사 자료만 사실의 출발점으로 삼아 게시 직전 검토가 가능한 콘텐츠 패키지를 작성하세요.

자료:
{json.dumps(facts, ensure_ascii=False, indent=2)}

작성 원칙:
- 독자의 검색 의도에 직접 답하고, 제목은 구체적이며 과장하지 마세요.
- 확인된 사실, 해석, 전망을 분리하고 불확실한 내용은 단정하지 마세요.
- 자료에 없는 숫자·통계·인용·사례·발언·URL을 만들지 마세요.
- 원문 출처 URL은 위 verified_source_urls만 사용하세요.
- 블로그는 검색 의도에 답하는 충분한 본문(한국어 1,200자 이상 목표), 소제목, 체크포인트, 요약, 자연스러운 다음 행동 CTA를 포함하세요.
- 쇼츠는 약 60초 분량으로 6~8개 장면을 구성하세요. 각 장면은 time, visual, caption, narration을 포함하고 첫 3초 후킹과 마지막 행동 유도를 포함하세요. 세로 9:16(1080x1920) 기준으로 화면 중앙 안전영역에 핵심 피사체와 자막을 배치하고, 자막은 한 화면 최대 2줄·짧은 문장으로 작성하며 화면 가장자리 잘림을 피하도록 visual에 구도를 구체적으로 지시하세요.
- Threads는 각각 독립적으로 읽혀도 되는 후킹 중심 글 2개를 만들고 각 본문은 500자 이내로 하세요.
- Facebook 페이지용 글은 Threads와 별도로 작성하세요. 2~4개 짧은 문단으로 맥락과 경험·실행 포인트를 설명하고, 마지막에 자연스러운 질문이나 댓글 유도 문장을 넣으세요. 확인되지 않은 개인 경험을 창작하지 마세요.
- 같은 내용을 세 번 반복하지 말고 플랫폼별 문법에 맞게 재구성하세요.
- human_accepted_performance_insights는 사람이 명시적으로 선택한 과거 성과 관찰입니다. 사실 근거가 아니라 형식·후킹·구성의 참고자료로만 활용하고, 이번 트렌드의 사실처럼 인용하거나 수치·성과를 보장하지 마세요.
- 참고자료와 현재 트렌드가 맞지 않으면 참고자료를 무시하세요. 선택된 관찰을 기계적으로 복제하지 말고 현재 독자 검색 의도에 맞게 변형하세요.
- 결과는 아래 JSON 객체 하나로만 출력하세요. 코드펜스나 설명은 붙이지 마세요.
{{
  "blog": {{"title":"검색형 제목","meta_description":"검색 결과 설명","focus_keyword":"핵심 키워드","body":"Markdown 본문"}},
  "shorts": {{"title":"쇼츠 제목","duration_seconds":60,"hook":"첫 3초 후킹","scenes":[{{"time":"00-05초","visual":"9:16 화면 구도와 안전영역을 포함한 화면 구성","caption":"짧은 자막","narration":"내레이션"}}],"closing_cta":"마지막 행동 유도","youtube_description":"유튜브 설명란 문안","instagram_caption":"인스타그램 릴스 설명문","tiktok_caption":"틱톡 설명문","hashtags":["해시태그1","해시태그2"]}},
  "threads": [{{"title":"후킹 제목","body":"Threads 본문"}},{{"title":"후킹 제목","body":"Threads 본문"}}],
  "facebook": {{"title":"Facebook 페이지 제목","body":"Facebook 페이지 전용 게시 본문"}}
}}"""


def _parse_content_package(answer: str) -> dict:
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("콘텐츠 응답에서 JSON 객체를 찾지 못했습니다.")
    try:
        package, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ValueError("콘텐츠 응답의 JSON 형식이 올바르지 않습니다.") from error
    if not isinstance(package, dict):
        raise ValueError("콘텐츠 패키지는 JSON 객체여야 합니다.")
    blog = package.get("blog")
    shorts = package.get("shorts")
    threads = package.get("threads")
    if not isinstance(blog, dict):
        raise ValueError("블로그 원고 구조가 올바르지 않습니다. 다시 생성하세요.")
    for field, label in (("title", "제목"), ("meta_description", "검색 설명"),
                         ("focus_keyword", "핵심 키워드"), ("body", "본문")):
        if not isinstance(blog.get(field), str) or not blog[field].strip():
            raise ValueError(f"블로그 {label}이 비어 있거나 문자열이 아닙니다. 다시 생성하세요.")
    if len(blog["body"].strip()) < 500:
        raise ValueError("블로그 본문이 없거나 500자 미만입니다. 다시 생성하세요.")
    if not isinstance(shorts, dict):
        raise ValueError("쇼츠 원고 구조가 올바르지 않습니다. 다시 생성하세요.")
    for field, label in (("title", "제목"), ("hook", "도입 문장"), ("closing_cta", "마무리 안내"),
                         ("youtube_description", "YouTube 설명란"),
                         ("instagram_caption", "Instagram 문안"),
                         ("tiktok_caption", "TikTok 문안")):
        if not isinstance(shorts.get(field), str) or not shorts[field].strip():
            raise ValueError(f"쇼츠 {label}이 비어 있거나 문자열이 아닙니다. 다시 생성하세요.")
    duration = shorts.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or not 30 <= duration <= 90:
        raise ValueError("쇼츠 길이는 30~90초 사이의 숫자여야 합니다. 다시 생성하세요.")
    scenes = shorts.get("scenes")
    if not isinstance(scenes, list) or not 5 <= len(scenes) <= 8:
        raise ValueError("쇼츠는 5~8개 장면이 필요합니다. 다시 생성하세요.")
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"쇼츠 {index}번째 장면 구조가 올바르지 않습니다. 다시 생성하세요.")
        for field, label in (("time", "시간"), ("visual", "화면 구성"),
                             ("caption", "자막"), ("narration", "내레이션")):
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise ValueError(f"쇼츠 {index}번째 장면의 {label}이 비어 있습니다. 다시 생성하세요.")
    hashtags = shorts.get("hashtags", [])
    if not isinstance(hashtags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in hashtags):
        raise ValueError("쇼츠 해시태그 형식이 올바르지 않습니다. 다시 생성하세요.")
    if not isinstance(threads, list) or len(threads) != 2:
        raise ValueError("Threads 초안은 정확히 2개가 필요합니다.")
    for index, post in enumerate(threads, 1):
        if not isinstance(post, dict):
            raise ValueError(f"Threads {index}번째 초안 구조가 올바르지 않습니다.")
        if not isinstance(post.get("title"), str) or not post["title"].strip():
            raise ValueError(f"Threads {index}번째 초안 제목이 비어 있습니다.")
        if not isinstance(post.get("body"), str) or not post["body"].strip() or len(post["body"]) > 500:
            raise ValueError("Threads 본문은 비어 있지 않고 500자 이하여야 합니다.")
    facebook = package.get("facebook")
    if not isinstance(facebook, dict):
        facebook = {"title": threads[0]["title"], "body": threads[0]["body"]}
    if not isinstance(facebook.get("title"), str) or not facebook["title"].strip():
        facebook["title"] = threads[0]["title"]
    if not isinstance(facebook.get("body"), str) or not facebook["body"].strip():
        facebook["body"] = threads[0]["body"]
    package["facebook"] = facebook
    return package


def _safe_http_url(value: object) -> str | None:
    """Return a URL safe for an HTML link, or None for an unsafe/malformed value."""
    candidate = str(value or "").strip()
    has_control = any(ord(char) <= 0x20 or ord(char) == 0x7f for char in candidate)
    if not candidate or "\\" in candidate or has_control:
        return None
    try:
        parsed = urlparse(candidate)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        _ = parsed.port
    except ValueError:
        return None
    return candidate


def _safe_http_urls(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [safe for value in values if (safe := _safe_http_url(value)) is not None]


def _evaluate_source_integrity(
    item: dict, trend_report: dict, generated_citations: list | None = None,
) -> dict:
    """Check source URL syntax, duplicates, and whether generated citations are linked.

    This verifies URL structure and list linkage only; it does not fetch pages or
    establish that a source supports a claim or is trustworthy.
    """
    raw_urls = item.get("source_urls") or trend_report.get("citations") or []
    if not isinstance(raw_urls, list):
        raw_urls = []
    generated = generated_citations if isinstance(generated_citations, list) else []
    entries = []
    malformed = []
    duplicates = []
    seen = set()
    for raw in raw_urls:
        value = str(raw or "").strip()
        if not value:
            continue
        if _safe_http_url(value) is None:
            malformed.append(value[:300])
            continue
        parsed = urlparse(value)
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            fragment="",
        ).geturl()
        if normalized in seen:
            duplicates.append(value[:300])
            continue
        seen.add(normalized)
        entries.append(value)
    for raw in generated:
        value = str(raw or "").strip()
        if _safe_http_url(value) is not None:
            parsed = urlparse(value)
            normalized = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), fragment="").geturl()
            if normalized not in seen:
                seen.add(normalized)
                entries.append(value)
        elif value:
            malformed.append(value[:300])
    base_urls = item.get("source_urls") or trend_report.get("citations") or []
    if not isinstance(base_urls, list):
        base_urls = []
    base_normalized = set()
    for raw in base_urls:
        value = str(raw or "").strip()
        if _safe_http_url(value) is None:
            continue
        parsed = urlparse(value)
        base_normalized.add(parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), fragment="").geturl())
    unlinked = []
    for raw in generated:
        value = str(raw or "").strip()
        try:
            parsed = urlparse(value)
            normalized = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), fragment="").geturl()
        except ValueError:
            normalized = value
        if value and normalized not in base_normalized:
            unlinked.append(value[:300])
    warnings = []
    if not entries:
        warnings.append("연결된 유효 출처 URL이 없습니다.")
    if malformed:
        warnings.append("HTTP/HTTPS URL 형식이 아닌 출처가 있습니다.")
    if duplicates:
        warnings.append("중복 출처 URL이 있습니다.")
    if unlinked:
        warnings.append("생성 응답의 인용 URL 중 조사 자료 출처 목록에 없는 항목이 있습니다.")
    return {
        "status": "검토 필요" if warnings else "URL 형식·연결 확인",
        "source_count": len(entries),
        "sources": entries,
        "malformed_urls": malformed,
        "duplicate_urls": duplicates,
        "unlinked_citations": unlinked,
        "warnings": warnings,
        "scope_note": "URL 형식과 조사 자료의 출처 목록 연결만 확인했습니다. 원문 접속, 사실 주장과 출처의 관련성, 출처 신뢰도, 최신성은 검증하지 않았습니다.",
    }


def _evaluate_claim_citation_coverage(package: dict, source_urls: list | None = None) -> dict:
    """Flag factual-risk sentences and check for an explicit URL in the same sentence."""
    urls = [str(url).strip() for url in (source_urls or []) if str(url).strip()]
    sections = []
    blog = package.get("blog") or {}
    if isinstance(blog, dict):
        sections.append(("블로그", str(blog.get("body") or "")))
    for index, post in enumerate(package.get("threads") or [], 1):
        if isinstance(post, dict):
            sections.append((f"Threads {index}", str(post.get("body") or "")))
    facebook = package.get("facebook") or {}
    if isinstance(facebook, dict) and facebook.get("body"):
        sections.append(("Facebook", str(facebook.get("body"))))
    pattern = re.compile(
        r"(?:\d|%|퍼센트|원\b|명\b|건\b|년\b|월\b|일\b|분기|통계|조사|발표|집계|기준|정책|법률|시행|증가|감소|최초|최대|최저)"
    )
    candidates = []
    for section, body in sections:
        sentences = re.split(r"(?<=[.!?。])\s+|\n+", body)
        for sentence_index, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if len(sentence) < 18 or not pattern.search(sentence):
                continue
            following = sentences[sentence_index + 1].strip() if sentence_index + 1 < len(sentences) else ""
            attached = [url for url in urls if url in sentence or following.startswith(url)]
            candidates.append({
                "section": section,
                "claim": sentence[:500],
                "citation_attached": bool(attached),
                "attached_sources": attached,
                "status": "문장 내 URL 연결" if attached else "문장별 출처 대조 필요",
            })
    unlinked = [row for row in candidates if not row["citation_attached"]]
    return {
        "status": "문장별 검토 필요" if unlinked else ("후보 문장 없음" if not candidates else "문장 내 URL 연결"),
        "candidate_count": len(candidates),
        "unlinked_count": len(unlinked),
        "claims": candidates[:30],
        "warnings": (["수치·날짜·정책 등 사실 확인이 필요한 문장에 개별 출처 URL이 직접 연결되지 않았습니다."] if unlinked else []),
        "scope_note": "규칙으로 사실 확인 후보 문장을 추출하고 같은 문장 안의 URL만 표시했습니다. URL이 문장에 있어도 출처가 주장을 뒷받침하는지 의미적으로 검증하지 않습니다. 나머지 문장에도 사실 오류가 없다는 뜻은 아닙니다.",
    }


def _evaluate_content_quality(
    package: dict, keyword: str, trend_context: dict | None = None,
) -> dict:
    """Deterministic editorial checklist; this is not factual verification."""
    trend_context = trend_context if isinstance(trend_context, dict) else {}
    blog = package.get("blog") if isinstance(package.get("blog"), dict) else {}
    shorts = package.get("shorts") if isinstance(package.get("shorts"), dict) else {}
    threads = package.get("threads") if isinstance(package.get("threads"), list) else []
    facebook = package.get("facebook") if isinstance(package.get("facebook"), dict) else {}
    body = str(blog.get("body") or "")
    blog_title = str(blog.get("title") or "")
    scenes = shorts.get("scenes") if isinstance(shorts.get("scenes"), list) else []
    headings = sum(1 for line in body.splitlines() if line.strip().startswith("#"))
    thread_bodies = [
        str(row.get("body") or "").strip() for row in threads if isinstance(row, dict)
    ]
    audience_question = str(trend_context.get("audience_question") or "").strip()
    intent_terms = []
    for raw_term in re.findall(r"[가-힣A-Za-z0-9]{2,}", audience_question):
        term = re.sub(
            r"(에서|으로|까지|부터|하나요|인가요|할까요|습니다|합니다|하세요|은|는|이|가|을|를|의|에|로|와|과|도|만)$",
            "", raw_term,
        )
        if len(term) >= 2 and term not in {"어떻게", "무엇을", "무엇이", "어떤", "있나요", "위해서"}:
            intent_terms.append(term)
    intent_hits = sum(
        1 for term in set(intent_terms)
        if term.casefold() in (blog_title + " " + body).casefold()
    )
    intent_is_measurable = len(set(intent_terms)) >= 2
    intent_text = (audience_question + " " + keyword).casefold()
    intent_rules = [
        ("절차형", ("방법", "절차", "준비", "서류", "하는 법", "어떻게", "순서", "단계")),
        ("비교형", ("비교", "차이", "장단점", "추천", "순위", "어느", "vs", "대비")),
        ("거래형", ("구매", "가격", "비용", "신청", "예약", "대출", "가입", "판매", "구입")),
    ]
    intent_type = next((name for name, terms in intent_rules if any(term in intent_text for term in terms)), "정보형")
    intent_answer_terms = {
        "거래형": ("가격", "비용", "신청", "예약", "구매", "조건", "문의", "대상", "자격"),
        "비교형": ("차이", "비교", "장점", "단점", "반면", "기준", "선택"),
        "절차형": ("방법", "절차", "순서", "단계", "준비", "서류", "신청", "먼저", "다음"),
        "정보형": ("이유", "원인", "의미", "개념", "특징", "영향", "배경", "정리"),
    }
    intent_answer_hits = [term for term in intent_answer_terms[intent_type] if term in body.casefold()]
    intent_answer_present = bool(intent_answer_hits)
    hook = str(shorts.get("hook") or "").strip()
    hook_patterns = ("?", "왜", "놓치", "모르", "차이", "실수", "바로", "단 ", "3가지", "5가지", "반전", "하지만", "그런데")
    hook_has_pattern = any(pattern in hook for pattern in hook_patterns)
    checks = [
        ("blog_length", "블로그 본문 1,200자 이상", len(body.strip()) >= 1200, 5),
        ("blog_headings", "블로그 소제목 3개 이상", headings >= 3, 10),
        ("keyword_title", "핵심 키워드가 제목에 포함", bool(keyword and keyword.casefold() in blog_title.casefold()), 5),
        ("keyword_body", "핵심 키워드가 본문에 포함", bool(keyword and keyword.casefold() in body.casefold()), 5),
        ("search_intent", "독자 질문의 핵심어가 제목·본문에 반영", not intent_is_measurable or intent_hits >= min(2, len(set(intent_terms))), 10),
        ("blog_meta", "검색 설명 60~160자", 60 <= len(str(blog.get("meta_description") or "").strip()) <= 160, 5),
        ("shorts_scene_count", "쇼츠 장면 6~8개", 6 <= len(scenes) <= 8, 10),
        ("shorts_hook", "쇼츠 첫 3초 후킹 문장", bool(hook) and len(hook) >= 8, 5),
        ("shorts_hook_pattern", "질문·문제·대비 등 후킹 장치 포함", hook_has_pattern, 5),
        ("shorts_cta", "쇼츠 마무리 행동 유도", bool(str(shorts.get("closing_cta") or "").strip()), 5),
        ("shorts_scene_detail", "각 장면에 화면·자막·내레이션 존재", bool(scenes) and all(isinstance(s, dict) and all(str(s.get(k) or "").strip() for k in ("visual", "caption", "narration")) for s in scenes), 10),
        ("threads_pair", "Threads 독립 초안 2개 및 500자 제한", len(thread_bodies) == 2 and all(0 < len(text) <= 500 for text in thread_bodies), 10),
        ("threads_distinct", "Threads 두 초안의 본문이 서로 다름", len(thread_bodies) == 2 and thread_bodies[0] != thread_bodies[1], 5),
        ("facebook_native", "Facebook 전용 문안이 Threads와 구분됨", bool(str(facebook.get("body") or "").strip()) and str(facebook.get("body") or "").strip() not in thread_bodies, 5),
        ("hashtags", "쇼츠 해시태그 3개 이상", isinstance(shorts.get("hashtags"), list) and len(shorts["hashtags"]) >= 3, 5),
    ]
    score = sum(weight for _, _, passed, weight in checks if passed)
    failed = [label for _, label, passed, _ in checks if not passed]
    return {
        "score": score,
        "grade": "양호" if score >= 85 else "보완 권장" if score >= 65 else "수정 필요",
        "checks_passed": sum(1 for _, _, passed, _ in checks if passed),
        "checks_total": len(checks),
        "passed": [label for _, label, passed, _ in checks if passed],
        "warnings": failed,
        "search_intent": {
            "type": intent_type,
            "audience_question": audience_question,
            "keyword_coverage_hits": sorted(set(intent_terms), key=str.casefold),
            "keyword_coverage_count": intent_hits,
            "answer_cues": intent_answer_hits,
            "answer_cue_present": intent_answer_present,
            "status": "답변 단서 발견" if intent_answer_present else "검색 의도 답변 보완 필요",
            "scope_note": "검색 의도 유형과 본문 표현을 규칙으로 추정한 편집 보조 정보입니다. 실제 검색자의 의도나 검색엔진 평가를 측정하지 않습니다.",
        },
        "scope_note": "구조·분량·플랫폼별 편집 체크리스트 점수입니다. 사실 정확성, 출처 신뢰도, 저작권, 실제 성과를 판정하지 않습니다.",
    }


def _build_editorial_recommendations(quality_report: dict, claim_coverage: dict) -> list[dict]:
    """Build non-destructive, actionable revision proposals from review findings."""
    proposals = []
    guidance = {
        "블로그 본문 1,200자 이상": ("블로그 본문", "핵심 설명 뒤에 실제 적용 사례, 예외 조건, 주의사항을 추가하세요."),
        "블로그 소제목 3개 이상": ("블로그 구조", "독자가 궁금해할 질문형 소제목을 3개 이상으로 나누세요."),
        "핵심 키워드가 제목에 포함": ("블로그 제목", "핵심 키워드를 제목 앞부분에 자연스럽게 넣으세요."),
        "핵심 키워드가 본문에 포함": ("블로그 본문", "핵심 키워드와 동의어를 본문 초반에 자연스럽게 반영하세요."),
        "독자 질문의 핵심어가 제목·본문에 반영": ("검색 의도", "독자 질문의 핵심어를 제목과 첫 단락에 반영하고 직접 답변하세요."),
        "검색 설명 60~160자": ("검색 설명", "대상·핵심 효익·본문에서 얻을 정보를 60~160자로 요약하세요."),
        "쇼츠 장면 6~8개": ("쇼츠 구성", "문제 제기부터 해결·행동 유도까지 6~8장면으로 재구성하세요."),
        "쇼츠 첫 3초 후킹 문장": ("쇼츠 후킹", "첫 3초에 독자의 손실·궁금증·문제를 직접 제시하세요."),
        "질문·문제·대비 등 후킹 장치 포함": ("쇼츠 후킹", "일반적인 소개 대신 질문·흔한 실수·예상 밖의 차이를 제시하세요."),
        "쇼츠 마무리 행동 유도": ("쇼츠 CTA", "저장·댓글·공유 중 하나의 행동만 구체적으로 요청하세요."),
        "각 장면에 화면·자막·내레이션 존재": ("쇼츠 장면", "각 장면에 화면 묘사·짧은 자막·말로 읽을 내레이션을 모두 채우세요."),
        "Threads 독립 초안 2개 및 500자 제한": ("Threads", "서로 다른 관점의 독립 게시물 2개를 각각 500자 이내로 작성하세요."),
        "Threads 두 초안의 본문이 서로 다름": ("Threads", "첫 게시물은 문제 제기, 두 번째는 해결·반론 등 역할을 분리하세요."),
        "Facebook 전용 문안이 Threads와 구분됨": ("Facebook", "Facebook용으로 배경 설명과 독자 맥락을 보강한 별도 문안을 작성하세요."),
        "쇼츠 해시태그 3개 이상": ("쇼츠 해시태그", "주제·대상·형식을 대표하는 관련 해시태그를 추가하세요."),
    }
    for warning in quality_report.get("warnings", []):
        area, instruction = guidance.get(warning, ("콘텐츠 편집", "해당 항목을 확인하고 내용을 보완하세요."))
        proposals.append({"area": area, "original": warning, "proposal": instruction, "reason": "편집 품질 점검에서 미통과"})
    intent = quality_report.get("search_intent") or {}
    if not intent.get("answer_cue_present", True):
        proposals.append({
            "area": "검색 의도 답변",
            "original": str(intent.get("audience_question") or "검색 의도에 맞는 직접 답변"),
            "proposal": "질문에 대한 한 문장 답변을 본문 첫 부분에 배치한 뒤, 근거와 세부 내용을 이어서 설명하세요.",
            "reason": "검색 의도 유형에 맞는 답변 단서를 찾지 못함",
        })
    for row in claim_coverage.get("claims", []):
        if not row.get("citation_attached"):
            proposals.append({
                "area": str(row.get("section") or "사실 확인"),
                "original": str(row.get("claim") or ""),
                "proposal": "원문을 열어 수치·날짜·정책 주장을 대조하세요. 근거가 확인되면 해당 문장 바로 뒤에 출처 URL을 붙이고, 확인되지 않으면 삭제하거나 범위를 좁혀 표현하세요.",
                "reason": "문장에 직접 연결된 출처 URL이 없음",
            })
    return proposals[:40]


def _editorial_recommendation_key(recommendation: dict, knowledge_id: str = "") -> str:
    canonical = json.dumps({"knowledge_id": knowledge_id, "recommendation": recommendation}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
def _editorial_target(recommendation: dict) -> tuple[str, str] | None:
    """Map a revision proposal to one editable preview field; never guess a platform."""
    area = str(recommendation.get("area") or "")
    if area in {"블로그", "블로그 본문", "블로그 구조", "검색 의도", "검색 의도 답변"}:
        return "blog.body", "blog"
    if area == "블로그 제목":
        return "blog.title", "blog"
    if area == "검색 설명":
        return "blog.meta_description", "blog"
    if area == "쇼츠 후킹":
        return "shorts.0.hook", "shorts"
    if area == "Threads 1":
        return "threads.0.body", "threads"
    if area == "Threads 2":
        return "threads.1.body", "threads"
    if area == "Facebook":
        return "facebook.body", "facebook"
    return None

def _read_editorial_target(preview: dict, target: str) -> str:
    value = preview
    for part in target.split("."):
        if part.isdigit():
            if not isinstance(value, list) or int(part) >= len(value):
                return ""
            value = value[int(part)]
        else:
            if not isinstance(value, dict):
                return ""
            value = value.get(part)
    return value if isinstance(value, str) else ""

def _write_editorial_target(preview: dict, target: str, value: str) -> None:
    parts = target.split(".")
    current = preview
    for part in parts[:-1]:
        current = current[int(part)] if part.isdigit() else current[part]
    final = parts[-1]
    if final.isdigit():
        current[int(final)] = value
    else:
        current[final] = value

def _parse_editorial_revision(answer: str) -> dict:
    """Parse a constrained revision response without accepting empty or malformed copy."""
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("수정 응답에서 JSON 객체를 찾지 못했습니다.")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise ValueError("수정 응답의 JSON 형식이 올바르지 않습니다.") from error
    if not isinstance(payload, dict):
        raise ValueError("수정 응답은 JSON 객체여야 합니다.")
    revised = payload.get("revised_text")
    if not isinstance(revised, str) or not revised.strip():
        raise ValueError("수정 문구가 비어 있습니다.")
    if len(revised) > 40000:
        raise ValueError("수정 문구가 너무 깁니다. 40,000자 이내로 다시 생성하세요.")
    changes = payload.get("changes", [])
    unresolved = payload.get("unresolved_claims", [])
    if not isinstance(changes, list) or any(not isinstance(row, str) for row in changes):
        raise ValueError("수정 내역 형식이 올바르지 않습니다.")
    if not isinstance(unresolved, list) or any(not isinstance(row, str) for row in unresolved):
        raise ValueError("미확인 주장 목록 형식이 올바르지 않습니다.")
    return {"revised_text": revised.strip(), "changes": [row.strip()[:500] for row in changes if row.strip()][:12], "unresolved_claims": [row.strip()[:500] for row in unresolved if row.strip()][:20]}

def _build_editorial_revision_prompt(preview: dict, recommendation: dict, target: str, original_text: str) -> str:
    sources = [str(url) for url in (preview.get("source_urls") or []) if isinstance(url, str)][:20]
    return (
        "선택된 콘텐츠 한 부분만 편집하고 JSON 객체만 반환하세요. "
        '형식: {"revised_text":"수정된 전체 텍스트","changes":["수정한 점"],"unresolved_claims":["추가 확인이 필요한 주장"]}. '
        "원문에 없는 통계·날짜·법률·정책·금액·인용을 만들지 마세요. 출처 URL이 있어도 원문 확인 전 사실로 단정하지 마세요. "
        "불확실한 주장은 삭제하거나 조건부 표현으로 낮추고 unresolved_claims에 기록하세요. 핵심 의미와 고유명사는 보존하세요. "
        f"대상 필드: {target}\n편집 영역: {recommendation.get('area', '')}\n"
        f"문제: {recommendation.get('original', '')}\n수정 방향: {recommendation.get('proposal', '')}\n"
        f"기존 원문:\n{original_text}\n참고 출처 URL(근거 확인 보장 아님):\n" + "\n".join(sources)
    )

def _refresh_preview_editorial_checks(preview: dict) -> None:
    """Recompute deterministic checks after an explicit editorial change."""
    shorts = preview.get("shorts") or []
    package = {
        "blog": preview.get("blog") or {},
        "shorts": shorts[0] if shorts and isinstance(shorts[0], dict) else {},
        "threads": preview.get("threads") or [],
        "facebook": preview.get("facebook") or {},
    }
    quality = _evaluate_content_quality(package, str(preview.get("keyword") or ""))
    claims = _evaluate_claim_citation_coverage(package, preview.get("source_urls") or [])
    preview["quality_report"] = quality
    preview["claim_coverage"] = claims
    preview["editorial_recommendations"] = _build_editorial_recommendations(quality, claims)


def _apply_editorial_revision(
    preview: dict, revision_id: str, applied_by: str, *, confirm_unresolved: bool = False,
) -> None:
    revisions = preview.get("editorial_revisions") or []
    revision = next(
        (row for row in revisions if hmac.compare_digest(str(row.get("revision_id", "")), revision_id)),
        None,
    )
    if not revision or revision.get("status") != "pending_review":
        raise ValueError("수정본이 없거나 이미 처리되었습니다.")
    if revision.get("unresolved_claims") and not confirm_unresolved:
        raise ValueError("추가 확인이 필요한 주장이 있습니다. 원문 대조 후 확인란을 선택하세요.")
    target = str(revision.get("target") or "")
    current_text = _read_editorial_target(preview, target)
    if current_text != revision.get("base_text"):
        raise ValueError("원문이 수정본 생성 이후 변경되었습니다. 최신 원문으로 다시 수정 문구를 생성하세요.")
    revised_text = str(revision.get("revised_text") or "").strip()
    if not revised_text:
        raise ValueError("수정 문구가 비어 있어 적용할 수 없습니다.")
    history = preview.setdefault("editorial_history", [])
    history.insert(0, {
        "target": target,
        "before": current_text,
        "after": revised_text,
        "revision_id": revision_id,
        "applied_at": utc_now(),
        "applied_by": applied_by,
    })
    preview["editorial_history"] = history[:20]
    _write_editorial_target(preview, target, revised_text)
    revision["status"] = "applied"
    revision["applied_at"] = utc_now()
    _refresh_preview_editorial_checks(preview)


def _revert_editorial_revision(preview: dict, revision_id: str) -> None:
    history = preview.get("editorial_history") or []
    record = next(
        (row for row in history if hmac.compare_digest(str(row.get("revision_id", "")), revision_id)),
        None,
    )
    if not record or record.get("reverted_at"):
        raise ValueError("되돌릴 수정 이력을 찾을 수 없거나 이미 복구했습니다.")
    target = str(record.get("target") or "")
    current_text = _read_editorial_target(preview, target)
    if current_text != record.get("after"):
        raise ValueError("수정 적용 이후 원문이 다시 변경되었습니다. 최신 내용을 확인하고 수동 복구하세요.")
    _write_editorial_target(preview, target, str(record.get("before") or ""))
    record["reverted_at"] = utc_now()
    for revision in preview.get("editorial_revisions") or []:
        if hmac.compare_digest(str(revision.get("revision_id", "")), revision_id):
            revision["status"] = "reverted"
            revision["reverted_at"] = record["reverted_at"]
            break
    _refresh_preview_editorial_checks(preview)


def _make_preview(
    item: dict, trend_report: dict, provider=None,
    strategy_insights: list[dict] | None = None,
) -> dict:
    urls = item.get("source_urls") or trend_report.get("citations") or []
    if not urls:
        raise ValueError("이 트렌드는 연결된 출처 URL이 없어 콘텐츠 초안을 만들 수 없습니다.")
    keyword = str(item.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("키워드가 비어 있습니다.")
    points = [str(value).strip() for value in item.get("key_points", []) if str(value).strip()]
    points.extend([
        str(item.get("why_now") or ""),
        str(item.get("audience_question") or ""),
        str(item.get("content_angle") or ""),
    ])
    points = list(dict.fromkeys(value for value in points if len(value) >= 12))
    if len(points) < 3:
        raise ValueError("콘텐츠 생성에 필요한 독립 근거가 3개 미만입니다.")
    facts = "\n".join([
        f"트렌드 키워드: {keyword}",
        f"요약: {item.get('summary', '')}",
        f"지금 주목하는 이유: {item.get('why_now', '')}",
        f"독자 질문: {item.get('audience_question', '')}",
        f"콘텐츠 관점: {item.get('content_angle', '')}",
        *[f"확인할 핵심 사실: {point}" for point in points],
    ])
    # A topic keyword can recur across days with different source articles.
    # Fingerprint the source set as well, so separate news events never share one
    # KNOWLEDGE/performance lineage merely because their keywords match.
    identity_sources = sorted({str(url).strip() for url in urls if str(url).strip()})
    identity_payload = json.dumps(
        {"keyword": keyword, "source_urls": identity_sources},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    preview_identity = hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()[:16]
    knowledge = KnowledgeRecord(
        id="trend-preview-" + preview_identity,
        source_raw_id="trend-preview:" + preview_identity,
        source_url=urls[0],
        title=str(item.get("blog_title") or keyword),
        domain=str(item.get("category") or "기타"),
        knowledge_type="정보",
        lesson=facts,
        evidence=tuple(f"SOURCE: {url}" for url in urls),
        created_at=utc_now(),
        knowledge_review_status="approved",
        summary=str(item.get("summary") or facts)[:500],
        key_points=tuple(points),
        factual_information=facts,
        current_validity="Perplexity 조사 시점 기준. 발행 전 원문과 최신성 재검증 필요.",
        verification_required=True,
    )
    if provider is not None:
        result = provider.search(
            _build_content_prompt(item, trend_report, strategy_insights),
            search_recency_filter="week",
        )
        package = _parse_content_package(result.answer)
        quality_report = _evaluate_content_quality(package, keyword, item)
        source_integrity = _evaluate_source_integrity(item, trend_report, list(result.citations))
        claim_coverage = _evaluate_claim_citation_coverage(package, list(dict.fromkeys(urls + list(result.citations))))
        editorial_recommendations = _build_editorial_recommendations(quality_report, claim_coverage)
        return {
            "keyword": keyword,
            "quality_report": quality_report,
            "source_integrity": source_integrity,
            "claim_coverage": claim_coverage,
            "editorial_recommendations": editorial_recommendations,
            "knowledge_id": knowledge.id,
            "strategy_insights": strategy_insights or [],
            "created_at": utc_now(),
            "status": "preview_only_not_approved",
            "warning": "Perplexity가 작성한 검토용 초안입니다. 원문 사실 확인과 사람의 승인을 거쳐야 게시할 수 있습니다.",
            "blog": package["blog"],
            "shorts": [{
                "title": package["shorts"].get("title", ""),
                "body": "\\n".join(
                    f"{scene.get('time', '')} | 화면: {scene.get('visual', '')} | "
                    f"자막: {scene.get('caption', '')} | 내레이션: {scene.get('narration', '')}"
                    for scene in package["shorts"]["scenes"]
                ) + "\\n마무리 CTA: " + str(package["shorts"].get("closing_cta", "")),
                "duration_seconds": package["shorts"].get("duration_seconds", 60),
                "hook": package["shorts"].get("hook", ""),
                "scenes": package["shorts"]["scenes"],
                "youtube_description": package["shorts"].get("youtube_description", ""),
                "instagram_caption": package["shorts"].get("instagram_caption", ""),
                "tiktok_caption": package["shorts"].get("tiktok_caption", ""),
                "hashtags": package["shorts"].get("hashtags", []),
            }],
            "threads": package["threads"],
            "facebook": package["facebook"],
            "source_urls": list(dict.fromkeys(urls + list(result.citations))),
            "content_model": result.model,
        }

    # Offline fallback is retained for deterministic tests and local template preview only.
    bundle = generate_content_bundle(knowledge)
    offline_package = {
        "blog": asdict(bundle.blog) if bundle.blog else {},
        "shorts": ({"scenes": [asdict(row) for row in bundle.shorts], "hook": "", "closing_cta": "", "hashtags": []}),
        "threads": [asdict(row) for row in bundle.threads],
        "facebook": ({"body": bundle.threads[0].body} if bundle.threads else {}),
    }
    claim_coverage = _evaluate_claim_citation_coverage(offline_package, urls)
    quality_report = _evaluate_content_quality(offline_package, keyword, item)
    editorial_recommendations = _build_editorial_recommendations(quality_report, claim_coverage)
    return {
        "keyword": keyword,
        "quality_report": quality_report,
        "source_integrity": _evaluate_source_integrity(item, trend_report),
        "claim_coverage": claim_coverage,
        "editorial_recommendations": editorial_recommendations,
        "knowledge_id": knowledge.id,
        "strategy_insights": strategy_insights or [],
        "created_at": utc_now(),
        "status": "preview_only_not_approved",
        "warning": "검토용 미승인 미리보기입니다. 사실·인용 원문 확인과 사람의 승인을 거쳐야 게시할 수 있습니다.",
        "blog": asdict(bundle.blog) if bundle.blog else None,
        "shorts": [asdict(row) for row in bundle.shorts],
        "threads": [asdict(row) for row in bundle.threads],
        "facebook": ({"title": bundle.threads[0].title, "body": bundle.threads[0].body} if bundle.threads else {}),
        "source_urls": urls,
    }


def _publishing_platform_readiness(oauth_connections: dict, *, media_available: bool, public_media_ready: bool) -> dict[str, bool]:
    """Enable platform choices only when granted publish scopes and media prerequisites exist."""
    def scopes_for(platform: str) -> set[str]:
        raw = str(oauth_connections.get(platform, {}).get("granted_scopes", ""))
        return {scope for scope in re.split(r"[,\s]+", raw) if scope}

    def connected(platform: str) -> bool:
        connection = oauth_connections.get(platform, {})
        return bool(connection.get("account_id") and str(connection.get("access_token_configured", "")).lower() == "true")

    def token_active(platform: str) -> bool:
        raw_expiry = str(oauth_connections.get(platform, {}).get("expires_at", "")).strip()
        if not raw_expiry:
            return True
        try:
            expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry.astimezone(timezone.utc) > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return False

    youtube = oauth_connections.get("youtube_shorts", {})
    facebook = oauth_connections.get("facebook", {})
    raw_tasks = facebook.get("tasks", [])
    tasks = ({str(task) for task in raw_tasks} if isinstance(raw_tasks, (list, tuple, set))
             else {task for task in re.split(r"[,\s]+", str(raw_tasks)) if task})
    return {
        "threads": connected("threads") and token_active("threads") and "threads_content_publish" in scopes_for("threads"),
        "facebook": (connected("facebook") and token_active("facebook") and {"pages_show_list", "pages_read_engagement", "pages_manage_posts"}.issubset(scopes_for("facebook")) and bool({"CREATE_CONTENT", "MANAGE"}.intersection(tasks))),
        "youtube_shorts": (connected("youtube_shorts") and "https://www.googleapis.com/auth/youtube.upload" in scopes_for("youtube_shorts") and str(youtube.get("refresh_token_configured", "")).lower() == "true" and media_available),
        "instagram_reels": (connected("instagram_reels") and token_active("instagram_reels") and {"instagram_business_basic", "instagram_business_content_publish"}.issubset(scopes_for("instagram_reels")) and media_available and public_media_ready),
        "tiktok": (connected("tiktok") and token_active("tiktok") and "video.publish" in scopes_for("tiktok") and media_available),
    }

def _queue_payload_for_platform(
    preview: dict, platform: str, media_asset_id: str = "",
    privacy_level: str = "", is_aigc: bool = False,
) -> list[dict]:
    """Build platform payloads only when the required text or media asset exists."""
    if platform == "threads":
        payloads = preview.get("threads") or []
        if not payloads:
            raise ValueError("이 콘텐츠에는 Threads 초안이 없습니다.")
        return payloads
    if platform == "facebook":
        facebook = preview.get("facebook") or {}
        if not isinstance(facebook, dict) or not facebook.get("body"):
            posts = preview.get("threads") or []
            facebook = posts[0] if posts else {}
        title = str(facebook.get("title") or "").strip()
        body = str(facebook.get("body") or "").strip()
        message = "\n\n".join(part for part in (title, body) if part).strip()
        if not message:
            raise ValueError("이 콘텐츠에는 Facebook 페이지용 텍스트 초안이 없습니다.")
        return [{"title": title, "body": message}]
    if platform in {"youtube_shorts", "instagram_reels", "tiktok"}:
        asset = _media_asset_store().get_asset(media_asset_id)
        shorts = preview.get("shorts") or []
        if not shorts:
            raise ValueError("이 콘텐츠에는 쇼츠 대본이 없습니다.")
        script = shorts[0]
        title = str(script.get("title") or preview.get("keyword") or "").strip()
        hashtags = [
            str(tag).strip().lstrip("#")
            for tag in (script.get("hashtags") or [])
            if str(tag).strip().lstrip("#")
        ]
        if platform == "youtube_shorts":
            return [{
                "title": title,
                "description": str(script.get("youtube_description") or ""),
                "tags": hashtags,
                "video_path": str(asset.path),
                "media_asset_id": asset.asset_id,
            }]
        caption_field = "tiktok_caption" if platform == "tiktok" else "instagram_caption"
        caption = str(script.get(caption_field) or title).strip()
        missing_hashtags = [f"#{tag}" for tag in hashtags if f"#{tag}" not in caption]
        if missing_hashtags:
            caption = caption + "\n\n" + " ".join(missing_hashtags)
        if platform == "tiktok":
            allowed_privacy = {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
            if privacy_level not in allowed_privacy:
                raise ValueError("TikTok 공개 범위를 명시적으로 선택해야 합니다.")
            return [{
                "title": caption,
                "media_asset_id": asset.asset_id,
                "privacy_level": privacy_level,
                "is_aigc": bool(is_aigc),
            }]
        return [{
            "title": title,
            "caption": caption,
            "media_asset_id": asset.asset_id,
            "share_to_feed": True,
        }]
    if platform == "blog":
        raise ValueError("네이버 블로그는 현재 수동 게시 방식입니다. 원고를 복사해 직접 발행하세요.")
    raise ValueError("지원하지 않는 게시 플랫폼입니다.")


def _page(
    report: dict | None, previews: list[dict], error: str = "",
    queue_snapshot: dict | None = None, connection_checks: dict | None = None,
) -> str:
    if connection_checks is None:
        connection_checks = _read_connection_checks()
    oauth_connections, oauth_storage_error = _read_oauth_connections()
    oauth_setup = _oauth_setup_statuses(oauth_storage_error)
    media_assets = _list_media_assets()
    media_key_ready = len(os.getenv("TAK_AUTO_MEDIA_SIGNING_KEY", "").strip()) >= 32
    public_media_origin = urlparse(os.getenv("TAK_AUTO_PUBLIC_URL", "").strip())
    public_media_ready = (
        public_media_origin.scheme == "https" and bool(public_media_origin.hostname)
        and not public_media_origin.username and not public_media_origin.password
        and public_media_origin.path in {"", "/"}
        and not public_media_origin.query and not public_media_origin.fragment
    )
    asset_options = "".join(
        f'<option value="{escape(asset.asset_id, quote=True)}">{escape(asset.filename)} · {asset.size_bytes // (1024 * 1024)}MB</option>'
        for asset in media_assets
    )
    readiness = _publishing_platform_readiness(oauth_connections, media_available=bool(media_assets), public_media_ready=public_media_ready)
    platform_options = (
        ('<option value="threads">Threads · 게시 권한 확인됨</option>' if readiness["threads"] else '<option value="threads" disabled>Threads · 계정 및 threads_content_publish 권한 연결 필요</option>')
        + ('<option value="facebook">Facebook 페이지 · 게시 권한 확인됨</option>' if readiness["facebook"] else '<option value="facebook" disabled>Facebook 페이지 · 페이지 게시 권한 연결 필요</option>')
        + ('<option value="youtube_shorts">YouTube Shorts · 업로드 권한 및 MP4 준비됨</option>' if readiness["youtube_shorts"] else '<option value="youtube_shorts" disabled>YouTube Shorts · youtube.upload, refresh token 및 MP4 필요</option>')
        + ('<option value="instagram_reels">Instagram Reels · 게시 권한 및 MP4 준비됨</option>' if readiness["instagram_reels"] else '<option value="instagram_reels" disabled>Instagram Reels · 게시 권한, HTTPS 주소 및 MP4 필요</option>')
        + '<option value="blog" disabled>네이버 블로그 · 수동 게시</option>'
        + ('<option value="tiktok">TikTok Direct Post · 게시 권한 및 MP4 준비됨</option>' if readiness["tiktok"] else '<option value="tiktok" disabled>TikTok · video.publish 권한 및 MP4 필요</option>')
    )
    media_upload_html = (
        '<section class="toolbar"><h2>쇼츠 영상 파일 등록</h2>'
        '<p>완성된 MP4를 등록하면 YouTube Shorts, Instagram Reels, TikTok 예약에 연결할 수 있습니다. 최대 100MB.</p>'
        '<input id="media-file" type="file" accept="video/mp4">'
        '<button type="button" id="upload-media">MP4 등록</button>'
        '<p id="media-upload-result" class="meta"></p></section>'
        if media_key_ready else
        '<section class="toolbar"><h2>쇼츠 영상 파일 등록</h2><p class="warning">TAK_AUTO_MEDIA_SIGNING_KEY 설정 후 사용할 수 있습니다.</p></section>'
    )
    error_html = f'<div class="error">{escape(error)}</div>' if error else ""
    if not report:
        report = {}
    trends = report.get("trends", [])
    accepted_insights = [
        row for row in load_insights(INSIGHTS_PATH)
        if row.status == STATUS_ACCEPTED and row.result != "INSUFFICIENT_SAMPLE"
    ]
    accepted_insights = sorted(accepted_insights, key=lambda row: row.created_at, reverse=True)[:20]
    cards = []
    for index, item in enumerate(trends):
        sources = " ".join(
            f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">출처 {i}</a>'
            for i, url in enumerate(_safe_http_urls(item.get("source_urls", [])), 1)
        )
        cards.append(f"""
<article class="trend">
  <div class="meta">#{index + 1} · {escape(str(item.get('category', '기타')))}</div>
  <h3>{escape(str(item.get('keyword', '')))}</h3>
  <p>{escape(str(item.get('summary', '')))}</p>
  <p><b>왜 지금?</b> {escape(str(item.get('why_now', '')))}</p>
  <p><b>독자 질문</b> {escape(str(item.get('audience_question', '')))}</p>
  <p><b>콘텐츠 관점</b> {escape(str(item.get('content_angle', '')))}</p>
  <p class="hook">쇼츠 후킹: {escape(str(item.get('shorts_hook', '')))}</p>
  <p class="meta">{sources}</p>
  <form method="post" action="/generate"><input type="hidden" name="index" value="{index}">
    {''.join(f'<label class="meta"><input type="checkbox" name="insight_id" value="{escape(row.insight_id, quote=True)}"> 성과 참고: {escape(row.platform)} · {escape(row.metric)} · {escape(row.result)} · 표본 {row.sample_size}건</label>' for row in accepted_insights)}
    <p class="meta">사람이 승인한 과거 성과를 선택하면 후킹·구성 참고자료로만 반영합니다. 선택하지 않아도 생성할 수 있습니다. 최대 5개.</p>
    <button type="submit">선택한 참고자료로 콘텐츠 패키지 생성</button></form>
</article>""")
    preview_cards = []
    for preview_index, preview in enumerate(previews):
        blog = preview.get("blog") or {}
        shorts = preview.get("shorts") or []
        threads = preview.get("threads") or []
        facebook_post = preview.get("facebook") or (threads[0] if threads else {})
        facebook_message = "\n\n".join(
            part for part in (
                str(facebook_post.get("title") or "").strip(),
                str(facebook_post.get("body") or "").strip(),
            ) if part
        )
        strategy_insights = preview.get("strategy_insights") or []
        strategy_feedback_html = (
            '<div class="warning"><b>사람이 승인한 성과 참고자료 적용</b><ul>'
            + "".join(
                f'<li>{escape(str(row.get("platform", "")))} · {escape(str(row.get("metric", "")))} · '
                f'{escape(str(row.get("result", "")))} · 표본 {escape(str(row.get("sample_size", 0)))}건 '
                f'({escape(str(row.get("insight_id", "")))})</li>'
                for row in strategy_insights if isinstance(row, dict)
            )
            + '</ul><p class="meta">과거 성과 관찰을 형식 참고로만 사용했습니다. 이번 콘텐츠의 성과를 보장하지 않습니다.</p></div>'
            if strategy_insights else
            '<p class="meta">성과 인사이트를 생성 참고자료로 선택하지 않았습니다.</p>'
        )
        claim_coverage = preview.get("claim_coverage") or {}
        claim_feedback_html = (
            '<div class="toolbar"><b>문장별 사실 확인 후보: '
            + escape(str(claim_coverage.get("status", "미평가"))) + '</b><p class="meta">'
            + str(int(claim_coverage.get("candidate_count", 0))) + '개 후보 · 출처 직접 연결이 필요한 문장 '
            + str(int(claim_coverage.get("unlinked_count", 0))) + '개</p><ul>'
            + "".join('<li><b>' + escape(str(row.get("section", ""))) + ' · ' + escape(str(row.get("status", ""))) + '</b><br>' + escape(str(row.get("claim", ""))) + '</li>' for row in claim_coverage.get("claims", []))
            + "".join('<li>' + escape(str(value)) + '</li>' for value in claim_coverage.get("warnings", []))
            + '</ul><p class="meta">' + escape(str(claim_coverage.get("scope_note", ""))) + '</p></div>'
        )
        source_integrity = preview.get("source_integrity") or {}
        source_feedback_html = (
            '<div class="toolbar"><b>출처 URL 확인: '
            + escape(str(source_integrity.get("status", "미평가"))) + '</b><p class="meta">'
            + escape(str(source_integrity.get("source_count", 0))) + '개 URL 확인</p><ul>'
            + "".join("<li>" + escape(str(value)) + "</li>" for value in source_integrity.get("warnings", []))
            + "".join('<li><a href="' + escape(url, quote=True) + '" target="_blank" rel="noopener">' + escape(url) + '</a></li>' for url in _safe_http_urls(source_integrity.get("sources", [])))
            + '</ul><p class="meta">' + escape(str(source_integrity.get("scope_note", ""))) + '</p></div>'
        )
        editorial_recommendations = preview.get("editorial_recommendations") or []
        recommendation_rows = []
        for recommendation_index, row in enumerate(editorial_recommendations):
            target_info = _editorial_target(row)
            if target_info:
                action = (
                    f'<form method="post" action="/editorial/revise"><input type="hidden" name="preview_index" value="{preview_index}">'
                    f'<input type="hidden" name="recommendation_index" value="{recommendation_index}">'
                    f'<input type="hidden" name="recommendation_key" value="{_editorial_recommendation_key(row, str(preview.get("knowledge_id") or ""))}"><button type="submit" class="secondary">이 항목 수정 문구 만들기</button></form>'
                )
            else:
                action = '<p class="meta">이 항목은 현재 자동 수정 대상이 아닙니다. 안내에 따라 직접 점검하세요.</p>'
            recommendation_rows.append(
                '<li><b>' + escape(str(row.get("area", ""))) + '</b>'
                + '<p class="meta">점검 항목: ' + escape(str(row.get("original", ""))) + '</p>'
                + '<p>' + escape(str(row.get("proposal", ""))) + '</p>'
                + '<p class="meta">제안 이유: ' + escape(str(row.get("reason", ""))) + '</p>' + action + '</li>'
            )
        editorial_recommendations_html = (
            '<div class="toolbar"><b>원문 보존형 수정 제안 · ' + str(len(editorial_recommendations)) + '건</b><ol>'
            + "".join(recommendation_rows)
            + '</ol><p class="meta">수정 문구 생성은 별도 요청이며, 생성 후에도 운영자가 비교·검토하고 직접 적용해야 합니다.</p></div>'
        )
        editorial_revisions = preview.get("editorial_revisions") or []
        revision_cards = []
        for revision in editorial_revisions:
            pending = revision.get("status") == "pending_review"
            citation_text = " · ".join(str(url) for url in revision.get("citations", []))
            if pending:
                acknowledgement = (
                    '<label class="meta"><input type="checkbox" name="confirm_unresolved" value="1" required> 추가 확인이 필요한 주장을 원문과 대조했습니다.</label>'
                    if revision.get("unresolved_claims") else ""
                )
                apply_form = (
                    f'<form method="post" action="/editorial/apply"><input type="hidden" name="preview_index" value="{preview_index}">'
                    f'<input type="hidden" name="revision_id" value="{escape(str(revision.get("revision_id", "")), quote=True)}">'
                    + acknowledgement + '<button type="submit">이 수정본 적용</button></form>'
                )
            elif revision.get("status") == "applied":
                apply_form = '<p class="meta">적용 완료</p>'
            else:
                apply_form = '<p class="meta">처리 완료</p>'
            revision_cards.append(
                '<article class="draft"><b>' + escape(str(revision.get("area", "수정본"))) + ' · ' + escape(str(revision.get("status", ""))) + '</b>'
                + '<p class="meta">원문</p><pre>' + escape(str(revision.get("base_text", ""))) + '</pre>'
                + '<p class="meta">수정 제안</p><pre>' + escape(str(revision.get("revised_text", ""))) + '</pre>'
                + '<p class="meta">수정 내역: ' + escape(" · ".join(revision.get("changes", []))) + '</p>'
                + '<p class="meta">AI 추가 참고 URL(원문 확인 필요): ' + escape(citation_text) + '</p>'
                + ('<p class="warning">추가 확인 필요: ' + escape(" · ".join(revision.get("unresolved_claims", []))) + '</p>' if revision.get("unresolved_claims") else '')
                + apply_form + '</article>'
            )
        editorial_revisions_html = (
            '<div class="toolbar"><b>수정 전후 비교 · ' + str(len(editorial_revisions)) + '건</b>'
            + "".join(revision_cards) + '</div>'
        ) if editorial_revisions else ""
        editorial_history = preview.get("editorial_history") or []
        history_cards = []
        for history in editorial_history:
            if history.get("reverted_at"):
                history_action = '<p class="meta">원문 복구 완료</p>'
            else:
                history_action = (
                    f'<form method="post" action="/editorial/revert"><input type="hidden" name="preview_index" value="{preview_index}">'
                    f'<input type="hidden" name="revision_id" value="{escape(str(history.get("revision_id", "")), quote=True)}">'
                    '<button type="submit" class="secondary">이 수정 적용 되돌리기</button></form>'
                )
            history_cards.append(
                '<article class="draft"><b>' + escape(str(history.get("target", ""))) + '</b>'
                + '<p class="meta">적용 전</p><pre>' + escape(str(history.get("before", ""))) + '</pre>'
                + '<p class="meta">적용 후</p><pre>' + escape(str(history.get("after", ""))) + '</pre>'
                + history_action + '</article>'
            )
        editorial_history_html = (
            '<div class="toolbar"><b>수정 이력 및 복구 · ' + str(len(editorial_history)) + '건</b>'
            + "".join(history_cards) + '</div>'
        ) if editorial_history else ""
        quality_report = preview.get("quality_report") or {}
        search_intent = quality_report.get("search_intent") or {}
        search_intent_html = (
            '<div class="toolbar"><b>검색 의도 점검: '
            + escape(str(search_intent.get("type", "미분류"))) + ' · '
            + escape(str(search_intent.get("status", "미평가"))) + '</b><p class="meta">'
            + '독자 질문 핵심어 ' + escape(str(search_intent.get("keyword_coverage_count", 0)))
            + '개 반영 · 답변 단서: '
            + escape(", ".join(search_intent.get("answer_cues", [])) or "발견되지 않음")
            + '</p><p class="meta">' + escape(str(search_intent.get("scope_note", ""))) + '</p></div>'
        )
        quality_feedback_html = (
            '<div class="toolbar"><b>콘텐츠 구조 품질 체크: '
            + escape(str(quality_report.get("score", 0))) + '/100 · '
            + escape(str(quality_report.get("grade", "미평가"))) + '</b><p class="meta">'
            + escape(str(quality_report.get("checks_passed", 0))) + ' / '
            + escape(str(quality_report.get("checks_total", 0))) + '개 항목 통과</p><ul>'
            + "".join("<li>" + escape(str(value)) + "</li>" for value in quality_report.get("warnings", []))
            + '</ul><p class="meta">' + escape(str(quality_report.get("scope_note", ""))) + '</p></div>'
        )
        preview_cards.append(f"""
<section class="preview">
  <h2>{escape(str(preview.get('keyword', '')))} 콘텐츠 미리보기</h2>
  <p class="meta">KNOWLEDGE ID: {escape(str(preview.get('knowledge_id') or ''))} · <a href="/performance?knowledge_id={escape(str(preview.get('knowledge_id') or ''), quote=True)}">이 주제의 플랫폼별 성과 보기</a></p>
  <p class="warning">{escape(str(preview.get('warning', '')))}</p>
  {quality_feedback_html}
  {search_intent_html}
  {editorial_recommendations_html}
  {editorial_revisions_html}
  {editorial_history_html}
  {source_feedback_html}\n  {claim_feedback_html}
  {strategy_feedback_html}
  <h3>네이버 블로그 · {escape(str(blog.get('title', '')))}</h3>
  <button type="button" class="secondary copy" data-copy="blog-{len(preview_cards)}">블로그 원고 복사</button>
  <pre id="blog-{len(preview_cards)}">{escape(str(blog.get('body', '')))}</pre>
  <h3>유튜브 쇼츠 · {len(shorts)}편</h3>
  {"".join(f'<div class="draft"><b>{escape(str(row.get("title", "")))}</b><p><b>첫 3초 후킹</b>: {escape(str(row.get("hook", "")))}</p><button type="button" class="secondary copy" data-copy="short-{len(preview_cards)}-{i}">쇼츠 대본 복사</button><pre id="short-{len(preview_cards)}-{i}">{escape(str(row.get("body", "")))}</pre></div>' for i, row in enumerate(shorts))}
  {"".join(f'<div class="draft"><b>{label}</b><button type="button" class="secondary copy" data-copy="caption-{len(preview_cards)}-{i}">문안 복사</button><pre id="caption-{len(preview_cards)}-{i}">{escape(str(shorts[i].get(field, "")))}</pre></div>' for i in range(len(shorts)) for label, field in [("YouTube 설명란", "youtube_description"), ("Instagram 릴스 문안", "instagram_caption"), ("TikTok 설명문", "tiktok_caption")])}
  {"".join(f'<p class="meta">해시태그: {escape(" ".join("#" + str(tag).lstrip("#") for tag in shorts[i].get("hashtags", [])))}</p>' for i in range(len(shorts)))}
  <h3>Threads · {len(threads)}편</h3>
  {"".join(f'<div class="draft"><b>{escape(str(row.get("title", "")))}</b><button type="button" class="secondary copy" data-copy="thread-{len(preview_cards)}-{i}">Threads 글 복사</button><pre id="thread-{len(preview_cards)}-{i}">{escape(str(row.get("body", "")))}</pre></div>' for i, row in enumerate(threads))}
  <h3>Facebook 페이지 게시문 · {escape(str(facebook_post.get("title") or ""))}</h3>
  <button type="button" class="secondary copy" data-copy="facebook-{len(preview_cards)}">Facebook 글 복사</button>
  <pre id="facebook-{len(preview_cards)}">{escape(facebook_message)}</pre>
  <p class="meta">{" ".join(f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">원문 출처</a>' for url in _safe_http_urls(preview.get("source_urls", [])))}</p>
  <details><summary>플랫폼 게시 예약 및 승인</summary>
    <p class="warning">승인 후에도 실제 게시 기능은 기본 비활성 상태입니다.</p>
    <form method="post" action="/queue/approve" class="queue-form">
      <input type="hidden" name="preview_index" value="{preview_index}">
      <label>플랫폼 <select name="platform">{platform_options}</select></label>
      <label>영상 파일 <select name="media_asset_id"><option value="">영상 선택 (영상 플랫폼만)</option>{asset_options}</select></label>
      <label>TikTok 공개 범위 (TikTok 선택 시 필수) <select name="privacy_level"><option value="">공개 범위 선택</option><option value="SELF_ONLY">나만 보기</option><option value="MUTUAL_FOLLOW_FRIENDS">맞팔로워</option><option value="FOLLOWER_OF_CREATOR">팔로워</option><option value="PUBLIC_TO_EVERYONE">전체 공개</option></select></label>
      <label><input type="checkbox" name="is_aigc" value="1"> TikTok 영상이 AI 생성 콘텐츠임을 표시</label>
      <p class="meta">영상 플랫폼은 등록한 MP4를 사용합니다. Instagram은 공개 HTTPS 서명 URL로 Meta가 가져가며, TikTok은 MP4를 TikTok으로 직접 전송하며 Facebook은 선택한 페이지에 텍스트를 게시합니다. TikTok 공개 범위는 실제 계정에서 허용하는 옵션과 일치해야 합니다.</p>
      <label>예약 시각 (한국시간) <input type="datetime-local" name="scheduled_at" required></label>
      <button type="submit">승인하고 예약</button>
    </form>
  </details>
</section>""")
    generated = escape(str(report.get("researched_at", "아직 조사 전")))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TAK AUTO Trend Factory</title>
<style>
:root{{--bg:#f3f5f9;--ink:#182235;--muted:#65728a;--line:#dfe5ee;--accent:#3157c8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,"Malgun Gothic",sans-serif}}
main{{max-width:1100px;margin:auto;padding:24px 16px 60px}}header{{background:#182744;color:white;border-radius:18px;padding:26px}}
h1{{margin:0;font-size:28px}}header p{{color:#d4def0}}h2{{margin-top:30px}}
.toolbar,.trend,.preview{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px;margin:14px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}
.trend h3{{font-size:20px;margin:6px 0}}.meta{{color:var(--muted);font-size:13px}}.hook{{font-weight:700;color:#9a4b13}}
button{{border:0;border-radius:9px;padding:11px 15px;background:var(--accent);color:white;font-weight:700;cursor:pointer}}button:disabled{{opacity:.55;cursor:not-allowed}}
button.secondary{{background:#475569}}.error{{background:#fee;border:1px solid #d88;padding:12px;border-radius:10px}}
.warning{{background:#fff4d9;padding:12px;border-radius:9px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 inherit;background:#f7f8fb;padding:14px;border-radius:9px}}
a{{color:#3157c8}}.draft{{border-top:1px solid var(--line);padding:10px 0}}
.copy{{margin:6px 0}}.copy.done{{background:#16794b}}
table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;overflow-wrap:anywhere}}.queue-form{{display:flex;flex-wrap:wrap;gap:12px;align-items:end}}label{{display:grid;gap:4px}}
.connection-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:12px;margin-top:16px}}.connection-card{{border:1px solid var(--line);border-radius:12px;padding:14px;background:#fbfcfe}}.connection-heading{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}.connection-icon{{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:8px;background:#e7edf8;color:#3157c8;font-weight:800}}.connection-login-icon{{position:relative;text-decoration:none;transition:transform .15s,box-shadow .15s}}.connection-login-icon:hover,.connection-login-icon:focus-visible{{transform:translateY(-1px);box-shadow:0 0 0 3px #dbe7ff;outline:none}}.connection-external-mark{{position:absolute;right:-4px;bottom:-4px;display:grid;place-items:center;width:13px;height:13px;border:1px solid white;border-radius:50%;background:#3157c8;color:white;font:10px/1 system-ui}}.connection-login-note{{font-size:13px;color:var(--muted);margin:8px 0 0}}.connection-state{{margin-left:auto;font-size:12px;font-weight:700}}.connection-account{{font-size:18px;font-weight:700;margin:10px 0 2px}}.connection-expiry{{font-size:13px;font-weight:700;color:#956500;margin:2px 0}}.connection-note{{font-size:13px;margin:8px 0 0}}.connection-missing{{font-size:12px;color:#9c3d39;overflow-wrap:anywhere}}.connection-verification-error{{font-size:12px;color:#b42318}}.connection-card form{{margin:8px 0}}.connection-button{{display:inline-block;padding:9px 13px;background:#3157c8;color:white;text-decoration:none;border-radius:9px;font-weight:700}}.connection-card details{{font-size:12px;overflow-wrap:anywhere}}.connection-card code{{overflow-wrap:anywhere}}.state-configured .connection-state,.state-verified .connection-state{{color:#16794b}}.state-expired .connection-state,.state-missing .connection-state,.state-verification_failed .connection-state{{color:#b42318}}.state-manual .connection-state,.state-attention .connection-state{{color:#956500}}
@media(max-width:560px){{h1{{font-size:22px}}.grid{{display:block}}}}
</style></head><body><main>
<header><h1>TAK AUTO · TREND CONTENT FACTORY</h1>
<p>최신 트렌드 발견 → Perplexity 조사 → 블로그·쇼츠·Threads 제작 → 트래픽 유도</p>
<p><a href="/performance" style="color:#d4def0">📈 전체 콘텐츠 성과 대시보드</a> · <a href="/performance/insights" style="color:#d4def0">성과 인사이트</a></p>
<div>마지막 조사: {generated} · 모델: {escape(str(report.get('model', '미연결')))}</div>
{"<p>임시 저장소 사용 중: 영속 저장 경로를 사용할 수 없어 임시 저장소를 사용 중입니다. 재시작·재배포 시 데이터가 사라질 수 있습니다.</p>" if USING_EPHEMERAL_STORAGE else ""}</header>
{error_html}
{connection_dashboard(verification_cache=connection_checks, oauth_connections=oauth_connections, oauth_setup=oauth_setup, oauth_storage_error=oauth_storage_error)}
<section class="toolbar"><h2>최신 트렌드 조사</h2>
<p>Perplexity가 최근 7일 공개 웹 자료를 바탕으로 여러 분야의 키워드 최대 20개를 발굴합니다. 선택 키워드 콘텐츠 생성에도 Perplexity API를 한 번 더 사용합니다.</p>
<form method="post" action="/discover"><button type="submit">Perplexity 최신 트렌드 TOP 20 조사</button></form>
<p class="meta">검색량 순위가 아니라 최신 근거·한국 독자 관련성·콘텐츠 설명 가치에 따른 편집 후보입니다.</p></section>
<h2>발굴된 트렌드 {len(trends)}개</h2><div class="grid">{''.join(cards) or '<p>아직 조사 결과가 없습니다. 위 버튼으로 첫 조사를 실행하세요.</p>'}</div>
{media_upload_html}
<h2>생성한 콘텐츠 패키지 {len(previews)}개</h2>{''.join(preview_cards) or '<p>트렌드를 선택해 콘텐츠 패키지를 생성하세요.</p>'}
{queue_dashboard(queue_snapshot or {"items": [], "history": []}, publishing_enabled=os.getenv("TAK_AUTO_PUBLISHING_ENABLED", "").strip().lower() == "true", pending_approvals=len(previews))}
</main><script>
document.addEventListener("click", async (event) => {{
  const button = event.target.closest("button.copy");
  if (!button) return;
  const target = document.getElementById(button.dataset.copy);
  if (!target) return;
  const text = target.innerText;
  try {{
    await navigator.clipboard.writeText(text);
    button.textContent = "복사 완료";
    button.classList.add("done");
  }} catch (_) {{
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    button.textContent = copied ? "복사 완료" : "텍스트를 직접 선택하세요";
  }}
}});
const uploadButton = document.getElementById("upload-media");
if (uploadButton) uploadButton.addEventListener("click", async () => {{
  const fileInput = document.getElementById("media-file");
  const result = document.getElementById("media-upload-result");
  const file = fileInput && fileInput.files && fileInput.files[0];
  if (!file) {{ result.textContent = "먼저 MP4 파일을 선택하세요."; return; }}
  if (!file.name.toLowerCase().endsWith(".mp4") || file.size > 100 * 1024 * 1024) {{
    result.textContent = "MP4 파일만 등록할 수 있으며 최대 크기는 100MB입니다."; return;
  }}
  uploadButton.disabled = true;
  result.textContent = "영상 파일을 안전하게 등록하고 있습니다...";
  try {{
    const response = await fetch("/media/assets/upload", {{
      method: "POST", credentials: "same-origin",
      headers: {{ "Content-Type": "video/mp4", "X-Asset-Filename": encodeURIComponent(file.name) }},
      body: file
    }});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "영상 등록에 실패했습니다.");
    result.textContent = "등록 완료: " + payload.filename + " · " + Math.round(payload.size_bytes / 1048576) + "MB. 페이지를 새로고침해 예약 화면에서 선택하세요.";
    fileInput.value = "";
  }} catch (error) {{
    result.textContent = error.message || "영상 등록에 실패했습니다.";
  }} finally {{
    uploadButton.disabled = false;
  }}
}});
const publishForm = document.querySelector('form[action="/queue/approve"]');
if (publishForm) {{
  const platformField = publishForm.querySelector('select[name="platform"]');
  const privacyField = publishForm.querySelector('select[name="privacy_level"]');
  const syncPrivacyRequirement = () => {{
    if (privacyField && platformField) privacyField.required = platformField.value === "tiktok";
  }};
  if (platformField) platformField.addEventListener("change", syncPrivacyRequirement);
  syncPrivacyRequirement();
}}
</script></body></html>"""


def create_handler():
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8", *, cookie: str | list[str] = ""):
            security_policy = "default-src 'none'; frame-ancestors 'none'"
            if content_type.lower().startswith("text/html"):
                nonce = secrets.token_urlsafe(18)
                body = body.replace("<script>", f'<script nonce="{nonce}">')
                security_policy = (
                    "default-src 'none'; base-uri 'none'; connect-src 'self'; "
                    "form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; "
                    "object-src 'none'; script-src 'nonce-" + nonce + "'; style-src 'unsafe-inline'"
                )
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", security_policy)
            self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
            if isinstance(cookie, list):
                for value in cookie:
                    self.send_header("Set-Cookie", value)
            elif cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(encoded)

        def _require_auth(self):
            username = os.getenv("TAK_WEB_USERNAME", "").strip()
            password = os.getenv("TAK_WEB_PASSWORD", "")
            if not username and not password and self.server.server_address[0] in {"127.0.0.1", "localhost"}:
                return True
            if _basic_auth_valid(self.headers.get("Authorization", ""), username, password):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="TAK AUTO", charset="UTF-8"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def _redirect(self, location: str, *, cookie: str = ""):
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _serve_media_asset(self, asset_id: str):
            try:
                query = parse_qs(urlparse(self.path).query)
                asset = _media_asset_store().resolve_signed(
                    asset_id,
                    query.get("expires", [""])[0],
                    query.get("signature", [""])[0],
                )
            except MediaAssetError:
                self._respond("유효하지 않거나 만료된 미디어 URL입니다.", 403, "text/plain; charset=utf-8")
                return
            size = asset.path.stat().st_size
            start, end = 0, size - 1
            status = 200
            range_header = self.headers.get("Range", "").strip()
            if range_header:
                try:
                    unit, value = range_header.split("=", 1)
                    if unit != "bytes" or "," in value:
                        raise ValueError("unsupported range")
                    first, last = value.split("-", 1)
                    if first:
                        start = int(first)
                        end = int(last) if last else size - 1
                    else:
                        suffix = int(last)
                        start = max(0, size - suffix)
                        end = size - 1
                    if start < 0 or start >= size or end < start:
                        raise ValueError("invalid range")
                    end = min(end, size - 1)
                    status = 206
                except (ValueError, TypeError):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "public, max-age=300")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Disposition", "inline; filename=video.mp4")
            self.send_header("Referrer-Policy", "no-referrer")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with asset.path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _start_oauth(self, platform: str):
            if platform not in PROVIDERS:
                self._respond("지원하지 않는 SNS입니다.", 404, "text/plain; charset=utf-8")
                return
            try:
                _, storage_error = _read_oauth_connections()
                if storage_error:
                    raise SocialOAuthError(storage_error)
                setup = setup_status(platform)
                if not setup["ready"]:
                    raise SocialOAuthError("웹 연결 설정이 필요합니다: " + ", ".join(str(x) for x in setup["missing"]))
                redirect = callback_uri(platform)
                verifier = secrets.token_urlsafe(64)[:96] if platform == "youtube_shorts" else ""
                state, _ = OAUTH_FLOW_REGISTRY.create(platform, redirect, verifier=verifier)
                url = SocialOAuthClient().authorization_url(platform, redirect, state, verifier)
                secure = _oauth_cookie_is_secure(platform)
                self._redirect(url, cookie=_oauth_cookie(f"tak_oauth_{platform}", state, secure=secure))
            except SocialOAuthError as error:
                self._respond(_page(_read_json(TREND_PATH, {}), _read_json(PREVIEW_PATH, []), str(error)), 400)

        def _finish_oauth(self, platform: str):
            cookie_platform = platform if platform in PROVIDERS else "invalid"
            cookie_name = f"tak_oauth_{cookie_platform}"
            secure = _oauth_cookie_is_secure(platform)
            clear_cookie = _oauth_cookie(cookie_name, "", secure=secure, clear=True)
            try:
                if platform not in PROVIDERS:
                    raise SocialOAuthError("지원하지 않는 SNS입니다.")
                query = parse_qs(urlparse(self.path).query)
                state = query.get("state", [""])[0]
                cookie_state = _cookie_value(self.headers.get("Cookie", ""), cookie_name)
                flow = OAUTH_FLOW_REGISTRY.consume(platform, state, cookie_state)
                if query.get("error"):
                    raise SocialOAuthError("SNS 로그인이 취소되었거나 권한 승인이 거부되었습니다.")
                code = query.get("code", [""])[0]
                result = SocialOAuthClient().complete(
                    platform, code, str(flow["redirect_uri"]), str(flow.get("verifier", "")), state=state,
                )
                if platform == "facebook":
                    choices = result.get("choices", [])
                    if not isinstance(choices, list) or not choices:
                        raise SocialOAuthError("연결할 Facebook 페이지가 없습니다.")
                    now = datetime.now(timezone.utc)
                    for key, value in list(_PENDING_FACEBOOK_CHOICES.items()):
                        try:
                            created = datetime.fromisoformat(str(value.get("created_at", "")))
                            if now - created > timedelta(seconds=FLOW_TTL_SECONDS):
                                _PENDING_FACEBOOK_CHOICES.pop(key, None)
                        except (TypeError, ValueError):
                            _PENDING_FACEBOOK_CHOICES.pop(key, None)
                    if len(_PENDING_FACEBOOK_CHOICES) >= 100:
                        raise SocialOAuthError("페이지 선택이 너무 많이 대기 중입니다. 잠시 후 다시 시도하세요.")
                    selection_id = secrets.token_urlsafe(32)
                    _PENDING_FACEBOOK_CHOICES[selection_id] = {
                        "choices": choices, "scopes": str(result.get("scopes", "")),
                        "created_at": now.isoformat(),
                    }
                    select_cookie = _oauth_cookie("tak_facebook_selection", selection_id, secure=secure)
                    self._respond(facebook_page_selection_page(selection_id, choices), cookie=[clear_cookie, select_cookie])
                    return
                _oauth_vault().save(platform, result["tokens"], result["profile"], scopes=str(result.get("scopes", "")))
                self._redirect("/?connected=" + platform, cookie=clear_cookie)
            except (SocialOAuthError, KeyError, TypeError, ValueError) as error:
                safe_message = str(error) if isinstance(error, SocialOAuthError) else "SNS 연결 정보를 처리하지 못했습니다. 다시 연결하세요."
                self._respond(build_callback_error_page(platform, safe_message), 400, cookie=clear_cookie)

        def do_GET(self):
            if self.path == "/health":
                self._respond(json.dumps(_health_payload()), content_type="application/json; charset=utf-8")
                return
            request_path = urlparse(self.path).path
            media_prefix = "/media/assets/"
            if request_path.startswith(media_prefix):
                self._serve_media_asset(request_path[len(media_prefix):])
                return
            callback_prefix = "/connections/oauth/callback/"
            if request_path.startswith(callback_prefix):
                self._finish_oauth(request_path[len(callback_prefix):])
                return
            if not self._require_auth():
                return
            oauth_prefix = "/connections/oauth/"
            if request_path.startswith(oauth_prefix):
                self._start_oauth(request_path[len(oauth_prefix):])
                return
            report = _read_json(TREND_PATH, {})
            previews = _read_json(PREVIEW_PATH, [])
            queue_snapshot = PublishingQueue(QUEUE_PATH).snapshot()
            self._respond(_page(report, previews, queue_snapshot=queue_snapshot))

        def do_POST(self):
            # Serialize state-changing form requests so read-modify-write flows
            # cannot overwrite each other's JSON snapshots. Large media uploads
            # use their own asset-store path and do not hold this lock.
            if urlparse(self.path).path == "/media/assets/upload":
                self._do_post_impl()
                return
            with STATE_MUTATION_LOCK:
                self._do_post_impl()

        def _do_post_impl(self):
            if not self._require_auth():
                return
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            forwarded_proto = self.headers.get("X-Forwarded-Proto", "http")
            if not _same_origin(origin, host, forwarded_proto, os.getenv("TAK_AUTO_PUBLIC_URL", "")):
                self._respond(_page(_read_json(TREND_PATH, {}), [], "허용되지 않은 출처의 요청입니다."), 403)
                return
            if urlparse(self.path).path == "/media/assets/upload":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except (TypeError, ValueError):
                    self._respond(json.dumps({"error": "Content-Length가 올바르지 않습니다."}), 400, "application/json; charset=utf-8")
                    return
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "video/mp4":
                    self._respond(json.dumps({"error": "video/mp4 형식으로 전송해야 합니다."}), 415, "application/json; charset=utf-8")
                    return
                if length <= 0 or length > 100 * 1024 * 1024:
                    self._respond(json.dumps({"error": "MP4 파일은 1~100MB 범위여야 합니다."}), 413, "application/json; charset=utf-8")
                    return
                try:
                    asset = _media_asset_store().save_stream(
                        self.rfile, length,
                        unquote(self.headers.get("X-Asset-Filename", "video.mp4")),
                    )
                    self._respond(json.dumps(asset.to_public_dict(), ensure_ascii=False), content_type="application/json; charset=utf-8")
                except MediaAssetError as error:
                    self._respond(json.dumps({"error": str(error)}, ensure_ascii=False), 400, "application/json; charset=utf-8")
                except OSError:
                    self._respond(json.dumps({"error": "영상 파일을 저장하지 못했습니다. 저장 공간을 확인하세요."}, ensure_ascii=False), 507, "application/json; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16_384:
                self._respond(_page(_read_json(TREND_PATH, {}), [], "요청이 너무 큽니다."), 413)
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            if self.path == "/connections/oauth/facebook/select":
                selection_id = form.get("selection_id", [""])[0]
                cookie_id = _cookie_value(self.headers.get("Cookie", ""), "tak_facebook_selection")
                if not selection_id or not cookie_id or not hmac.compare_digest(selection_id, cookie_id):
                    self._respond(_page(_read_json(TREND_PATH, {}), [], "Facebook 페이지 선택 요청이 만료되었습니다. 다시 연결하세요."), 400)
                    return
                pending = _PENDING_FACEBOOK_CHOICES.pop(selection_id, None)
                if not pending:
                    self._respond(_page(_read_json(TREND_PATH, {}), [], "Facebook 페이지 선택 시간이 만료되었습니다. 다시 연결하세요."), 400)
                    return
                try:
                    created_at = datetime.fromisoformat(str(pending["created_at"]))
                    if datetime.now(timezone.utc) - created_at > timedelta(seconds=FLOW_TTL_SECONDS):
                        raise ValueError("expired")
                    choices = pending.get("choices", [])
                    index = int(form.get("page_index", ["-1"])[0])
                    if not isinstance(choices, list) or index < 0 or index >= len(choices):
                        raise ValueError("invalid page")
                    selected = choices[index]
                    tokens = {"access_token": selected["access_token"], "expires_in": selected.get("expires_in", 0)}
                    profile = {
                        "account_id": selected["account_id"],
                        "account_name": selected["account_name"],
                        "tasks": selected.get("tasks", []),
                    }
                    _oauth_vault().save("facebook", tokens, profile, scopes=str(pending.get("scopes", "")))
                    secure = _oauth_cookie_is_secure("facebook")
                    self._redirect("/?connected=facebook", cookie=_oauth_cookie("tak_facebook_selection", "", secure=secure, clear=True))
                except (KeyError, TypeError, ValueError, SocialOAuthError) as error:
                    safe_message = str(error) if isinstance(error, SocialOAuthError) else "Facebook 페이지 선택을 완료하지 못했습니다. 다시 연결하세요."
                    self._respond(_page(_read_json(TREND_PATH, {}), [], safe_message), 400)
                return
            report = _read_json(TREND_PATH, {})
            previews = _read_json(PREVIEW_PATH, [])
            queue = PublishingQueue(QUEUE_PATH)
            try:
                if self.path == "/connections/disconnect":
                    platform = form.get("platform", [""])[0]
                    _oauth_vault().disconnect(platform)
                    self._redirect("/?disconnected=" + platform)
                    return
                if self.path == "/discover":
                    provider = PerplexityResearchProvider.from_environment()
                    discovered = discover_trends(provider)
                    report = discovered.to_dict()
                    _write_json(TREND_PATH, report)
                    self._respond(_page(report, previews, queue_snapshot=queue.snapshot()))
                    return
                if self.path == "/generate":
                    if not report.get("trends"):
                        raise ValueError("먼저 최신 트렌드를 조사하세요.")
                    index = int(form.get("index", ["-1"])[0])
                    if index < 0 or index >= len(report["trends"]):
                        raise ValueError("선택한 트렌드가 없습니다.")
                    selected_insights = _select_accepted_strategy_insights(
                        form.get("insight_id", []),
                    )
                    provider = PerplexityResearchProvider.from_environment()
                    preview = _make_preview(
                        report["trends"][index], report, provider=provider,
                        strategy_insights=selected_insights,
                    )
                    previews = [row for row in previews if row.get("keyword") != preview["keyword"]]
                    previews.insert(0, preview)
                    _write_json(PREVIEW_PATH, previews[:10])
                    self._respond(_page(report, previews[:10], queue_snapshot=queue.snapshot()))
                    return
                if self.path == "/editorial/revise":
                    preview_index = int(form.get("preview_index", ["-1"])[0])
                    recommendation_index = int(form.get("recommendation_index", ["-1"])[0])
                    if preview_index < 0 or preview_index >= len(previews):
                        raise ValueError("수정할 콘텐츠 미리보기를 찾을 수 없습니다.")
                    preview = previews[preview_index]
                    recommendations = preview.get("editorial_recommendations") or []
                    if recommendation_index < 0 or recommendation_index >= len(recommendations):
                        raise ValueError("수정 제안을 찾을 수 없습니다.")
                    recommendation = recommendations[recommendation_index]
                    supplied_key = form.get("recommendation_key", [""])[0]
                    if not supplied_key or not hmac.compare_digest(
                        supplied_key, _editorial_recommendation_key(recommendation, str(preview.get("knowledge_id") or "")),
                    ):
                        raise ValueError("수정 제안 목록이 갱신되었습니다. 최신 화면에서 다시 선택하세요.")
                    target_info = _editorial_target(recommendation)
                    if target_info is None:
                        raise ValueError("이 항목은 자동 수정 문구 생성 대상이 아닙니다. 전용 편집기에서 직접 수정하세요.")
                    target, _section = target_info
                    original_text = _read_editorial_target(preview, target)
                    if not original_text:
                        raise ValueError("수정 대상 원문이 비어 있어 진행할 수 없습니다.")
                    provider = PerplexityResearchProvider.from_environment()
                    result = provider.search(
                        _build_editorial_revision_prompt(preview, recommendation, target, original_text),
                        system_prompt=(
                            "당신은 보수적인 편집자입니다. 제공된 원문과 참고 URL 범위 밖의 사실을 만들지 않습니다. "
                            "요청된 JSON 구조를 엄격히 지키며, 검증되지 않은 주장은 반드시 미확인 목록에 남깁니다."
                        ),
                    )
                    parsed_revision = _parse_editorial_revision(result.answer)
                    if parsed_revision["revised_text"] == original_text.strip():
                        raise ValueError("수정 결과가 원문과 같습니다. 다른 수정 방향으로 다시 요청하세요.")
                    revision = {
                        "revision_id": secrets.token_urlsafe(18),
                        "recommendation_index": recommendation_index,
                        "area": str(recommendation.get("area") or ""),
                        "target": target,
                        "base_text": original_text,
                        "revised_text": parsed_revision["revised_text"],
                        "changes": parsed_revision["changes"],
                        "unresolved_claims": parsed_revision["unresolved_claims"],
                        "created_at": utc_now(),
                        "status": "pending_review",
                        "model": result.model,
                        "citations": list(result.citations)[:20],
                    }
                    revisions = preview.setdefault("editorial_revisions", [])
                    revisions.insert(0, revision)
                    preview["editorial_revisions"] = revisions[:20]
                    _write_json(PREVIEW_PATH, previews)
                    self._respond(_page(report, previews, "수정 문구를 생성했습니다. 원문과 비교한 뒤 직접 적용 여부를 결정하세요.", queue.snapshot()))
                    return
                if self.path == "/editorial/apply":
                    preview_index = int(form.get("preview_index", ["-1"])[0])
                    revision_id = form.get("revision_id", [""])[0]
                    if preview_index < 0 or preview_index >= len(previews) or not revision_id:
                        raise ValueError("적용할 수정본을 찾을 수 없습니다.")
                    preview = previews[preview_index]
                    applied_by = os.getenv("TAK_WEB_USERNAME", "local-user").strip() or "local-user"
                    confirm_unresolved = form.get("confirm_unresolved", [""])[0] == "1"
                    _apply_editorial_revision(preview, revision_id, applied_by, confirm_unresolved=confirm_unresolved)
                    _write_json(PREVIEW_PATH, previews)
                    self._respond(_page(report, previews, "선택한 수정본을 적용했습니다. 원문은 수정 이력에 보존했습니다.", queue.snapshot()))
                    return
                if self.path == "/editorial/revert":
                    preview_index = int(form.get("preview_index", ["-1"])[0])
                    revision_id = form.get("revision_id", [""])[0]
                    if preview_index < 0 or preview_index >= len(previews) or not revision_id:
                        raise ValueError("복구할 수정 이력을 찾을 수 없습니다.")
                    preview = previews[preview_index]
                    _revert_editorial_revision(preview, revision_id)
                    _write_json(PREVIEW_PATH, previews)
                    self._respond(_page(report, previews, "선택한 수정 적용을 되돌렸습니다. 복구 이력은 보존했습니다.", queue.snapshot()))
                    return
                if self.path == "/queue/approve":
                    index = int(form.get("preview_index", ["-1"])[0])
                    if index < 0 or index >= len(previews):
                        raise ValueError("승인할 콘텐츠 초안을 찾을 수 없습니다.")
                    platform = form.get("platform", [""])[0]
                    local_time = datetime.strptime(form.get("scheduled_at", [""])[0], "%Y-%m-%dT%H:%M")
                    scheduled_at = local_time.replace(tzinfo=KST)
                    preview = previews[index]
                    preview_key = json.dumps(preview, ensure_ascii=False, sort_keys=True)
                    content_id = "trend-" + hashlib.sha256(preview_key.encode("utf-8")).hexdigest()[:20]
                    media_asset_id = form.get("media_asset_id", [""])[0]
                    privacy_level = form.get("privacy_level", [""])[0]
                    is_aigc = form.get("is_aigc", [""])[0] == "1"
                    payloads = _queue_payload_for_platform(
                        preview, platform, media_asset_id, privacy_level, is_aigc,
                    )
                    knowledge_id = str(preview.get("knowledge_id") or "")
                    source_url = str((preview.get("source_urls") or [""])[0] or "")
                    for payload in payloads:
                        payload["_knowledge_id"] = knowledge_id
                        payload["_source_url"] = source_url
                    approver = os.getenv("TAK_WEB_USERNAME", "local-user").strip() or "local-user"
                    enqueued = [queue.enqueue_approved(
                        content_id=f"{content_id}-{platform}-{payload_index + 1}",
                        platform=platform, payload=payload,
                        scheduled_at=scheduled_at, approved_by=approver,
                    ) for payload_index, payload in enumerate(payloads)]
                    self._respond(_page(report, previews, f"{len(enqueued)}개 작업을 승인하고 예약했습니다.", queue.snapshot()))
                    return
                if self.path == "/connections/verify":
                    platform = form.get("platform", [""])[0]
                    checks = _read_connection_checks()
                    checks, message = _run_connection_verification(platform, checks)
                    _write_json(CONNECTION_CHECKS_PATH, checks)
                    self._respond(_page(report, previews, message, queue.snapshot(), checks))
                    return
                if self.path == "/queue/confirm-published":
                    current = datetime.now(timezone.utc)
                    queue.confirm_published(
                        form.get("item_id", [""])[0],
                        remote_id=form.get("remote_id", [""])[0],
                        reviewed_by=os.getenv("TAK_WEB_USERNAME", "local-user").strip() or "local-user",
                        now=current,
                    )
                    self._respond(_page(report, previews, "플랫폼 게시 이력을 확인 완료로 기록했습니다.", queue.snapshot()))
                    return
                if self.path == "/queue/retry":
                    current = datetime.now(timezone.utc)
                    queue.retry_after_review(
                        form.get("item_id", [""])[0],
                        scheduled_at=current + timedelta(seconds=45),
                        reviewed_by=os.getenv("TAK_WEB_USERNAME", "local-user").strip() or "local-user",
                        now=current,
                    )
                    self._respond(_page(report, previews, "미게시 확인을 기록하고 제한된 재시도를 예약했습니다.", queue.snapshot()))
                    return
                self._respond(_page(report, previews, "지원하지 않는 요청입니다."), 404)
            except Exception as error:
                # Never print request credentials or full exception payloads into the page.
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
                self._respond(_page(report, previews, message, queue.snapshot()), 400)

        def log_message(self, _format, *_args):
            return

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("TAK_AUTO_HOST", "127.0.0.1"), help="바인딩 주소 (클라우드: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost"} and not (
        os.getenv("TAK_WEB_USERNAME", "").strip() and os.getenv("TAK_WEB_PASSWORD", "")
    ):
        parser.error("외부 공개 서버는 TAK_WEB_USERNAME과 TAK_WEB_PASSWORD 인증 설정이 필수입니다.")
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1~65535 범위여야 합니다.")
    print("TAK AUTO Trend Content Factory")
    print(f"바인딩: {args.host}:{args.port}")
    print(f"데이터 디렉터리: {DATA_DIR}")
    if USING_EPHEMERAL_STORAGE:
        print("주의: 설정된 저장 경로를 쓸 수 없어 임시 저장소(/tmp)를 사용합니다. 재시작·재배포 시 데이터가 사라질 수 있습니다.")
    print("웹 인증: 설정됨" if os.getenv("TAK_WEB_USERNAME") and os.getenv("TAK_WEB_PASSWORD") else "웹 인증: 로컬 개발 모드")
    print("Perplexity API 키: 설정됨" if os.getenv("TAK_SCOUT_PERPLEXITY_API_KEY") else "Perplexity API 키: 미설정")
    print("종료: Ctrl+C")
    server = ThreadingHTTPServer((args.host, args.port), create_handler())
    scheduler_thread, scheduler_stop = start_scheduler(QUEUE_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        scheduler_stop.set()
        scheduler_thread.join(timeout=2)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
