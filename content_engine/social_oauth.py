"""Server-side OAuth connections for the social accounts shown in TAK AUTO.

OAuth client secrets stay in the service environment and user tokens are stored
only in an encrypted, persistent vault. No provider API is called by importing
this module or rendering the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import HTTPRedirectHandler, Request, build_opener


CALLBACK_PATH = "/connections/oauth/callback/"
TOKEN_FILE_NAME = "social_oauth_tokens.enc"
FLOW_TTL_SECONDS = 900
ALLOWED_HOSTS = frozenset({
    "accounts.google.com", "oauth2.googleapis.com", "youtube.googleapis.com",
    "www.tiktok.com", "open.tiktokapis.com",
    "www.instagram.com", "api.instagram.com", "graph.instagram.com",
    "www.facebook.com", "graph.facebook.com", "threads.net", "graph.threads.net",
    "nid.naver.com", "openapi.naver.com",
})


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    client_id_env: str
    client_secret_env: str
    client_id_param: str
    authorize_url: str
    scopes: tuple[str, ...]


PROVIDERS: dict[str, Provider] = {
    "youtube_shorts": Provider(
        "youtube_shorts", "YouTube Shorts", "YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET", "client_id",
        "https://accounts.google.com/o/oauth2/v2/auth",
        ("https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/youtube.upload"),
    ),
    "tiktok": Provider(
        "tiktok", "TikTok", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "client_key",
        "https://www.tiktok.com/v2/auth/authorize/", ("user.info.basic", "video.publish"),
    ),
    "instagram_reels": Provider(
        "instagram_reels", "Instagram Reels", "INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET", "client_id",
        "https://www.instagram.com/oauth/authorize",
        ("instagram_business_basic", "instagram_business_content_publishing"),
    ),
    "facebook": Provider(
        "facebook", "Facebook 페이지", "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET", "client_id",
        "https://www.facebook.com", ("public_profile", "pages_show_list", "pages_read_engagement", "pages_manage_posts"),
    ),
    "threads": Provider(
        "threads", "Threads", "THREADS_APP_ID", "THREADS_APP_SECRET", "client_id",
        "https://threads.net/oauth/authorize", ("threads_basic", "threads_content_publish"),
    ),
    "blog": Provider(
        "blog", "네이버 블로그", "NAVER_LOGIN_CLIENT_ID", "NAVER_LOGIN_CLIENT_SECRET", "client_id",
        "https://nid.naver.com/oauth2.0/authorize", (),
    ),
}


class SocialOAuthError(RuntimeError):
    """Safe OAuth failure message without provider response bodies or credentials."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """OAuth requests carry bearer material and must not forward it across redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api_version(environ: Mapping[str, str]) -> str:
    version = environ.get("META_GRAPH_API_VERSION", "v27.0").strip()
    if not version.startswith("v") or not version[1:].replace(".", "").isdigit():
        raise SocialOAuthError("META_GRAPH_API_VERSION 설정을 확인하세요.")
    return version


def callback_uri(platform: str, environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    if platform not in PROVIDERS:
        raise SocialOAuthError("지원하지 않는 SNS입니다.")
    base = values.get("TAK_AUTO_PUBLIC_URL", "").strip().rstrip("/")
    parsed = urlsplit(base)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.scheme != "https" and not local_http:
        raise SocialOAuthError("TAK_AUTO_PUBLIC_URL에 HTTPS 주소를 설정해야 합니다.")
    if not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SocialOAuthError("TAK_AUTO_PUBLIC_URL은 도메인 주소만 입력하세요.")
    return base + CALLBACK_PATH + platform


def setup_status(platform: str, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environ is None else environ
    provider = PROVIDERS.get(platform)
    if provider is None:
        return {"ready": False, "missing": ["지원하지 않는 SNS"]}
    missing = [name for name in (provider.client_id_env, provider.client_secret_env)
               if not values.get(name, "").strip()]
    try:
        redirect = callback_uri(platform, values)
    except SocialOAuthError:
        redirect = ""
        missing.append("TAK_AUTO_PUBLIC_URL (HTTPS 주소)")
    encryption_key = values.get("TAK_AUTO_OAUTH_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        missing.append("TAK_AUTO_OAUTH_ENCRYPTION_KEY")
    else:
        try:
            _fernet(encryption_key)
        except SocialOAuthError:
            missing.append("TAK_AUTO_OAUTH_ENCRYPTION_KEY (Fernet 형식 오류)")
    return {"ready": not missing, "missing": missing, "redirect_uri": redirect}


def _fernet(key: str):
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii"))
    except (ImportError, ValueError, UnicodeEncodeError):
        raise SocialOAuthError("암호화 저장 설정을 확인하세요. cryptography 패키지와 Fernet 키가 필요합니다.") from None


class OAuthFlowRegistry:
    """Short-lived, single-use OAuth state and PKCE data held in process memory."""

    def __init__(self, *, now: Callable[[], datetime] | None = None):
        self._flows: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def create(self, platform: str, redirect_uri: str, *, verifier: str = "") -> tuple[str, dict[str, object]]:
        if platform not in PROVIDERS:
            raise SocialOAuthError("지원하지 않는 SNS입니다.")
        state = secrets.token_urlsafe(32)
        entry = {
            "platform": platform, "redirect_uri": redirect_uri, "verifier": verifier,
            "created_at": self._now().astimezone(timezone.utc).isoformat(),
        }
        with self._lock:
            self._prune_locked()
            self._flows[state] = entry
        return state, entry

    def consume(self, platform: str, state: str, cookie_state: str) -> dict[str, object]:
        if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
            raise SocialOAuthError("로그인 요청을 확인할 수 없습니다. 다시 연결하세요.")
        with self._lock:
            self._prune_locked()
            entry = self._flows.pop(state, None)
        if not entry or entry.get("platform") != platform:
            raise SocialOAuthError("로그인 요청이 만료되었거나 이미 사용되었습니다. 다시 연결하세요.")
        return entry

    def _prune_locked(self) -> None:
        cutoff = self._now().astimezone(timezone.utc) - timedelta(seconds=FLOW_TTL_SECONDS)
        for state, entry in list(self._flows.items()):
            try:
                created = datetime.fromisoformat(str(entry["created_at"]))
            except (KeyError, TypeError, ValueError):
                self._flows.pop(state, None)
                continue
            if created < cutoff:
                self._flows.pop(state, None)


class OAuthTokenVault:
    """Encrypted token store on the persistent app disk; requires a private env key."""

    _shared_lock = threading.RLock()

    def __init__(self, path: Path, encryption_key: str):
        if not encryption_key:
            raise SocialOAuthError("TAK_AUTO_OAUTH_ENCRYPTION_KEY가 설정되지 않았습니다.")
        self.path = Path(path)
        self.fernet = _fernet(encryption_key)
        self._lock = self._shared_lock

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            cleartext = self.fernet.decrypt(self.path.read_bytes())
            value = json.loads(cleartext.decode("utf-8"))
        except Exception as error:
            # Do not expose encrypted contents or cryptographic exception details.
            raise SocialOAuthError("SNS 인증 저장소를 열 수 없습니다. 암호화 키와 저장 파일을 확인하세요.") from None
        if not isinstance(value, dict):
            raise SocialOAuthError("SNS 인증 저장소의 데이터 형식이 올바르지 않습니다.")
        return value

    def _save(self, rows: dict[str, dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.fernet.encrypt((json.dumps(rows, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(self.path)
        if os.name != "nt":
            self.path.chmod(0o600)

    def save(self, platform: str, tokens: Mapping[str, object], profile: Mapping[str, object], *, scopes: str = "") -> None:
        if platform not in PROVIDERS:
            raise SocialOAuthError("지원하지 않는 SNS입니다.")
        access_token = str(tokens.get("access_token", ""))
        if not access_token:
            raise SocialOAuthError("플랫폼에서 인증 토큰을 받지 못했습니다.")
        expires_in = _safe_int(tokens.get("expires_in"))
        now = datetime.now(timezone.utc)
        record: dict[str, object] = {
            "access_token": access_token,
            "refresh_token": str(tokens.get("refresh_token", "")),
            "token_type": str(tokens.get("token_type", "Bearer")),
            "expires_at": (now + timedelta(seconds=expires_in)).isoformat() if expires_in > 0 else "",
            "granted_scopes": scopes or str(tokens.get("scope", tokens.get("scopes", ""))),
            "account_id": str(profile.get("account_id", ""))[:200],
            "account_name": str(profile.get("account_name", ""))[:200],
            "connected_at": now.isoformat(),
        }
        with self._lock:
            rows = self._load()
            rows[platform] = record
            self._save(rows)

    def get(self, platform: str) -> dict[str, object] | None:
        if platform not in PROVIDERS:
            return None
        with self._lock:
            return self._load().get(platform)

    def public_connections(self) -> dict[str, dict[str, str]]:
        with self._lock:
            rows = self._load()
        public: dict[str, dict[str, str]] = {}
        for platform, row in rows.items():
            if platform in PROVIDERS and isinstance(row, dict):
                public[platform] = {name: str(row.get(name, "")) for name in (
                    "account_id", "account_name", "expires_at", "connected_at", "granted_scopes",
                )}
        return public

    def disconnect(self, platform: str) -> bool:
        if platform not in PROVIDERS:
            raise SocialOAuthError("지원하지 않는 SNS입니다.")
        with self._lock:
            rows = self._load()
            removed = rows.pop(platform, None) is not None
            if removed:
                self._save(rows)
        return removed


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _json_request(method: str, url: str, *, fields: Mapping[str, object] | None = None,
                  headers: Mapping[str, str] | None = None) -> dict[str, object]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise SocialOAuthError("허용되지 않은 인증 서버 주소입니다.")
    body = None
    request_headers = {"Accept": "application/json", "User-Agent": "TAK-AUTO/1.0"}
    if headers:
        request_headers.update(headers)
    if fields is not None:
        encoded = urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
        if method.upper() == "GET":
            query = list(parse_qsl(parsed.query, keep_blank_values=True))
            query.extend((key, str(value)) for key, value in fields.items())
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        else:
            body = encoded
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    request = Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with build_opener(_NoRedirectHandler()).open(request, timeout=25) as response:
            raw = response.read(1_000_001)
    except HTTPError as error:
        raise SocialOAuthError(f"플랫폼 인증 요청이 거부되었습니다 (HTTP {error.code}). 앱 권한과 콜백 주소를 확인하세요.") from None
    except (URLError, TimeoutError, OSError):
        raise SocialOAuthError("플랫폼 인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None
    if len(raw) > 1_000_000:
        raise SocialOAuthError("플랫폼 인증 응답이 너무 큽니다.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SocialOAuthError("플랫폼 인증 응답을 해석하지 못했습니다.") from None
    if not isinstance(result, dict):
        raise SocialOAuthError("플랫폼 인증 응답 형식이 올바르지 않습니다.")
    if result.get("error") or result.get("error_description"):
        raise SocialOAuthError("플랫폼에서 로그인을 거부했습니다. 앱 설정과 승인 권한을 확인하세요.")
    return result


def _add_query(url: str, values: Mapping[str, object]) -> str:
    parsed = urlsplit(url)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend((key, str(value)) for key, value in values.items())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


class SocialOAuthClient:
    """Provider-specific authorization-code exchange and read-only identity check."""

    def __init__(self, environ: Mapping[str, str] | None = None,
                 request_json: Callable[..., dict[str, object]] = _json_request):
        self.environ = os.environ if environ is None else environ
        self.request_json = request_json

    def authorization_url(self, platform: str, redirect_uri: str, state: str, verifier: str = "") -> str:
        provider = PROVIDERS.get(platform)
        if not provider:
            raise SocialOAuthError("지원하지 않는 SNS입니다.")
        status = setup_status(platform, self.environ)
        if not status["ready"]:
            raise SocialOAuthError("로그인 설정이 필요합니다: " + ", ".join(str(x) for x in status["missing"]))
        if redirect_uri != status["redirect_uri"]:
            raise SocialOAuthError("OAuth 콜백 주소가 설정값과 일치하지 않습니다.")
        client_id = self.environ[provider.client_id_env].strip()
        if platform == "facebook":
            url = f"{provider.authorize_url}/{_api_version(self.environ)}/dialog/oauth"
        else:
            url = provider.authorize_url
        params: dict[str, object] = {
            provider.client_id_param: client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if provider.scopes:
            delimiter = "," if platform in {"tiktok", "instagram_reels", "facebook", "threads"} else " "
            params["scope"] = delimiter.join(provider.scopes)
        if platform == "youtube_shorts":
            params.update({"access_type": "offline", "include_granted_scopes": "true", "prompt": "consent",
                           "code_challenge": _pkce_challenge(verifier), "code_challenge_method": "S256"})
        elif platform == "facebook":
            params["auth_type"] = "rerequest"
        elif platform == "instagram_reels":
            params.update({"enable_fb_login": "0", "force_authentication": "1"})
        return _add_query(url, params)

    def complete(self, platform: str, code: str, redirect_uri: str, verifier: str = "", state: str = "") -> dict[str, object]:
        provider = PROVIDERS.get(platform)
        if not provider:
            raise SocialOAuthError("지원하지 않는 SNS입니다.")
        if not code or len(code) > 4096 or "\n" in code or "\r" in code:
            raise SocialOAuthError("플랫폼 인증 코드가 올바르지 않습니다.")
        if callback_uri(platform, self.environ) != redirect_uri:
            raise SocialOAuthError("OAuth 콜백 주소가 설정값과 일치하지 않습니다.")
        client_id = self.environ[provider.client_id_env].strip()
        client_secret = self.environ[provider.client_secret_env].strip()
        version = _api_version(self.environ) if platform == "facebook" else ""
        token, profile = self._exchange_and_profile(platform, code, redirect_uri, verifier, state,
                                                    client_id, client_secret, version)
        if platform == "facebook":
            # The selected Page token is saved only after the user chooses a Page.
            return {"tokens": {}, "profile": {}, "scopes": str(token.get("scope", "")), "choices": profile}
        return {"tokens": token, "profile": profile, "scopes": str(token.get("scope", token.get("scopes", "")))}

    def _exchange_and_profile(self, platform: str, code: str, redirect: str, verifier: str, state: str,
                              client_id: str, secret: str, version: str) -> tuple[dict[str, object], dict[str, object] | list[dict[str, object]]]:
        if platform == "youtube_shorts":
            raw = self.request_json("POST", "https://oauth2.googleapis.com/token", fields={
                "code": code, "client_id": client_id, "client_secret": secret, "redirect_uri": redirect,
                "grant_type": "authorization_code", "code_verifier": verifier,
            })
            token = self._token_fields(raw)
            profile_data = self.request_json("GET", "https://youtube.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                                             headers={"Authorization": f"Bearer {token['access_token']}"})
            items = profile_data.get("items")
            channel = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
            if not channel:
                raise SocialOAuthError("로그인한 Google 계정에서 YouTube 채널을 찾지 못했습니다.")
            snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
            return token, {"account_id": channel.get("id", ""), "account_name": snippet.get("title", "YouTube 채널")}

        if platform == "tiktok":
            raw = self.request_json("POST", "https://open.tiktokapis.com/v2/oauth/token/", fields={
                "client_key": client_id, "client_secret": secret, "code": code,
                "grant_type": "authorization_code", "redirect_uri": redirect,
            })
            token = self._token_fields(raw.get("data") if isinstance(raw.get("data"), dict) else raw)
            info = self.request_json("GET", "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name",
                                     headers={"Authorization": f"Bearer {token['access_token']}"})
            user = info.get("data", {}).get("user", {}) if isinstance(info.get("data"), dict) else {}
            if not isinstance(user, dict) or not user.get("open_id"):
                raise SocialOAuthError("TikTok 프로필을 확인하지 못했습니다. user.info.basic 권한을 확인하세요.")
            return token, {"account_id": user.get("open_id", ""), "account_name": user.get("display_name") or "TikTok 계정"}

        if platform == "instagram_reels":
            raw = self.request_json("POST", "https://api.instagram.com/oauth/access_token", fields={
                "client_id": client_id, "client_secret": secret, "grant_type": "authorization_code",
                "redirect_uri": redirect, "code": code,
            })
            token = self._token_fields(raw)
            # Convert the short-lived token into the long-lived Instagram Login token.
            long = self.request_json("GET", "https://graph.instagram.com/access_token", fields={
                "grant_type": "ig_exchange_token", "client_secret": secret, "access_token": token["access_token"],
            })
            token = self._token_fields(long)
            info = self.request_json("GET", "https://graph.instagram.com/me?fields=user_id,username",
                                     headers={"Authorization": f"Bearer {token['access_token']}"})
            if not info.get("user_id") and not info.get("id"):
                raise SocialOAuthError("Instagram 프로필을 확인하지 못했습니다. 비즈니스 또는 크리에이터 계정과 권한을 확인하세요.")
            return token, {"account_id": info.get("user_id", info.get("id", "")), "account_name": info.get("username", "Instagram 계정")}

        if platform == "facebook":
            token_url = f"https://graph.facebook.com/{version}/oauth/access_token"
            raw = self.request_json("GET", token_url, fields={
                "client_id": client_id, "client_secret": secret, "redirect_uri": redirect,
                "code": code,
            })
            short = self._token_fields(raw)
            long = self.request_json("GET", token_url, fields={
                "grant_type": "fb_exchange_token", "client_id": client_id, "client_secret": secret,
                "fb_exchange_token": short["access_token"],
            })
            user_token = self._token_fields(long)
            pages = self.request_json("GET", f"https://graph.facebook.com/{version}/me/accounts?fields=id,name,access_token",
                                      headers={"Authorization": f"Bearer {user_token['access_token']}"})
            rows = pages.get("data")
            choices = []
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and row.get("id") and row.get("access_token"):
                        choices.append({"account_id": str(row["id"]), "account_name": str(row.get("name") or "Facebook 페이지"),
                                        "access_token": str(row["access_token"]),
                                        "expires_in": _safe_int(row.get("expires_in"))})
            if not choices:
                raise SocialOAuthError("이 Facebook 계정에서 관리 가능한 페이지를 찾지 못했습니다. 페이지 권한을 확인하세요.")
            return user_token, choices

        if platform == "threads":
            raw = self.request_json("POST", "https://graph.threads.net/oauth/access_token", fields={
                "client_id": client_id, "client_secret": secret, "grant_type": "authorization_code",
                "redirect_uri": redirect, "code": code,
            })
            token = self._token_fields(raw)
            # Exchange for the long-lived Threads token before storing it.
            long = self.request_json("GET", "https://graph.threads.net/access_token", fields={
                "grant_type": "th_exchange_token", "client_secret": secret, "access_token": token["access_token"],
            })
            token = self._token_fields(long)
            profile = self.request_json("GET", "https://graph.threads.net/v1.0/me?fields=id,username",
                                        headers={"Authorization": f"Bearer {token['access_token']}"})
            if not profile.get("id"):
                raise SocialOAuthError("Threads 프로필을 확인하지 못했습니다. threads_basic 권한을 확인하세요.")
            return token, {"account_id": profile.get("id", ""), "account_name": profile.get("username", "Threads 계정")}

        if platform == "blog":
            raw = self.request_json("GET", "https://nid.naver.com/oauth2.0/token", fields={
                "grant_type": "authorization_code", "client_id": client_id, "client_secret": secret,
                "code": code, "state": state,
            })
            token = self._token_fields(raw)
            profile_data = self.request_json("GET", "https://openapi.naver.com/v1/nid/me",
                                             headers={"Authorization": f"Bearer {token['access_token']}"})
            user = profile_data.get("response") if isinstance(profile_data.get("response"), dict) else {}
            if not user.get("id"):
                raise SocialOAuthError("네이버 프로필을 확인하지 못했습니다. 네이버 로그인 동의 설정을 확인하세요.")
            return token, {"account_id": user.get("id", ""), "account_name": user.get("nickname") or user.get("name") or "네이버 계정"}
        raise SocialOAuthError("지원하지 않는 SNS입니다.")

    @staticmethod
    def _token_fields(raw: object) -> dict[str, object]:
        if not isinstance(raw, dict) or not raw.get("access_token"):
            raise SocialOAuthError("플랫폼에서 인증 토큰을 받지 못했습니다.")
        return {
            "access_token": str(raw.get("access_token", "")),
            "refresh_token": str(raw.get("refresh_token", "")),
            "token_type": str(raw.get("token_type", "Bearer")),
            "expires_in": _safe_int(raw.get("expires_in")),
            "refresh_expires_in": _safe_int(raw.get("refresh_expires_in")),
            "scope": str(raw.get("scope", raw.get("scopes", ""))),
        }


def _pkce_challenge(verifier: str) -> str:
    import base64
    import hashlib
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_callback_error_page(platform: str, message: str) -> str:
    name = PROVIDERS.get(platform, Provider("", "SNS", "", "", "", "", ())).name
    return f"""<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>SNS 연결 오류</title><body style='font:16px system-ui;max-width:640px;margin:12vh auto;padding:24px;color:#182235'>
<h1>{escape(name)} 연결을 완료하지 못했습니다</h1><p>{escape(message)}</p><p><a href='/'>대시보드로 돌아가기</a></p></body></html>"""


def facebook_page_selection_page(selection_id: str, choices: list[Mapping[str, object]]) -> str:
    options = "".join(
        f'<label style="display:block;padding:10px"><input type="radio" name="page_index" value="{index}" {"checked" if index == 0 else ""} required> '
        f'{escape(str(choice.get("account_name", "Facebook 페이지")))} · {escape(str(choice.get("account_id", "")))}</label>'
        for index, choice in enumerate(choices)
    )
    return f"""<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Facebook 페이지 선택</title><body style='font:16px system-ui;max-width:640px;margin:8vh auto;padding:24px;color:#182235'>
<h1>연결할 Facebook 페이지 선택</h1><p>게시 기능은 별도로 꺼져 있습니다. 여기서는 연결할 계정만 선택합니다.</p>
<form method=post action='/connections/oauth/facebook/select'><input type=hidden name=selection_id value='{escape(selection_id, quote=True)}'>
{options}<button type=submit style='padding:12px 18px;margin-top:12px'>이 페이지 연결</button></form></body></html>"""
