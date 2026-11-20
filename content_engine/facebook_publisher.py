"""Facebook Page feed publishing through the Meta Graph API."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class FacebookConfigurationError(ValueError):
    """Missing or invalid Facebook Page publishing configuration."""


class FacebookAPIError(RuntimeError):
    """Facebook Graph API or transport failure."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward Page access tokens through unexpected redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class FacebookPublishResult:
    post_id: str


def _request_json(method: str, url: str, *, access_token: str,
                  fields: Mapping[str, object] | None = None,
                  timeout_seconds: float = 30.0) -> Mapping[str, object]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "graph.facebook.com":
        raise FacebookAPIError("허용되지 않은 Facebook API 주소입니다.")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "TAK-AUTO/1.0",
    }
    body = None
    if fields is not None:
        body = urlencode({key: str(value) for key, value in fields.items()}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=headers, method=method.upper())
    try:
        with build_opener(_NoRedirectHandler()).open(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except HTTPError as error:
        raise FacebookAPIError(f"Facebook API 요청 실패 (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise FacebookAPIError("Facebook API 통신 결과를 확인할 수 없습니다.") from None
    if len(raw) > 1_000_000:
        raise FacebookAPIError("Facebook API 응답이 너무 큽니다.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FacebookAPIError("Facebook API 응답을 해석하지 못했습니다.") from None
    if not isinstance(result, dict):
        raise FacebookAPIError("Facebook API 응답 형식이 올바르지 않습니다.")
    if result.get("error"):
        error = result["error"]
        code = error.get("code") if isinstance(error, dict) else ""
        # A provider rejection is a known failure; do not classify it as a successful post.
        raise FacebookAPIError(f"Facebook API가 요청을 거부했습니다. (오류 코드: {code or 'unknown'})")
    return result


FacebookTransport = Callable[..., Mapping[str, object]]


@dataclass(frozen=True)
class FacebookClient:
    access_token: str
    page_id: str
    api_version: str = "v27.0"
    timeout_seconds: float = 30.0
    transport: FacebookTransport = _request_json

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise FacebookConfigurationError("Facebook 페이지 액세스 토큰이 없습니다.")
        if not self.page_id.strip() or not self.page_id.isdigit():
            raise FacebookConfigurationError("Facebook 페이지 ID가 올바르지 않습니다.")
        if not self.api_version.startswith("v") or not self.api_version[1:].replace(".", "").isdigit():
            raise FacebookConfigurationError("META_GRAPH_API_VERSION 설정을 확인하세요.")

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    def publish_text(self, message: str) -> FacebookPublishResult:
        text = message.strip()
        if not text:
            raise ValueError("Facebook 페이지 게시 본문이 비어 있습니다.")
        if len(text) > 63_206:
            raise ValueError("Facebook 페이지 게시 본문이 허용 길이를 초과했습니다.")
        response = self.transport(
            "POST", f"{self._base}/{self.page_id}/feed",
            access_token=self.access_token,
            fields={"message": text},
            timeout_seconds=self.timeout_seconds,
        )
        if response.get("error"):
            error = response["error"]
            code = error.get("code") if isinstance(error, dict) else ""
            raise FacebookAPIError(
                f"Facebook이 게시 요청을 거부했습니다. (오류 코드: {code or 'unknown'})"
            )
        post_id = str(response.get("id") or "").strip()
        if not post_id:
            raise FacebookAPIError("Facebook 게시 응답에 게시물 ID가 없습니다.")
        return FacebookPublishResult(post_id=post_id)

    def get_post_insights(self, post_id: str) -> Mapping[str, object]:
        """Read the supported lifetime insights for one post on this Page."""
        normalized = post_id.strip()
        parts = normalized.split("_")
        if not normalized or len(parts) > 2 or not all(part.isdigit() for part in parts):
            raise ValueError("Facebook 게시물 ID 형식이 올바르지 않습니다.")
        if len(parts) == 2 and parts[0] != self.page_id:
            raise ValueError("Facebook 게시물이 연결된 페이지에 속하지 않습니다.")
        metrics = "post_media_view,post_reactions_by_type_total"
        url = f"{self._base}/{normalized}/insights?{urlencode({'metric': metrics})}"
        return self.transport(
            "GET", url, access_token=self.access_token, timeout_seconds=self.timeout_seconds,
        )
