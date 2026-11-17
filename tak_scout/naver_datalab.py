"""Official Naver DataLab Search Trend API adapter.

The API returns relative search-interest ratios for requested keyword groups and
periods, not absolute query volume. Credentials are supplied via environment.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_ENDPOINT = "https://openapi.naver.com/v1/datalab/search"


class NaverDataLabError(RuntimeError):
    """Safe, user-facing DataLab adapter error."""


@dataclass(frozen=True)
class DataLabSeries:
    title: str
    keywords: tuple[str, ...]
    data: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, object]:
        return {"title": self.title, "keywords": list(self.keywords),
                "data": list(self.data), "measurement": "naver_datalab_relative_ratio"}


@dataclass(frozen=True)
class DataLabResult:
    start_date: str
    end_date: str
    time_unit: str
    results: tuple[DataLabSeries, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "startDate": self.start_date, "endDate": self.end_date,
            "timeUnit": self.time_unit,
            "results": [item.to_dict() for item in self.results],
            "measurement": "naver_datalab_relative_ratio",
            "note": "검색어 그룹 간 상대적 검색 관심도 지표이며 절대 검색량이 아닙니다.",
        }


class NaverDataLabProvider:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 endpoint: str = DEFAULT_ENDPOINT, timeout: float = 15.0):
        self.client_id = client_id or os.getenv("NAVER_DATALAB_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("NAVER_DATALAB_CLIENT_SECRET", "")
        self.endpoint = endpoint
        self.timeout = timeout

    def search_trend(self, keyword_groups: list[dict[str, object]], *,
                     start_date: str, end_date: str, time_unit: str = "date",
                     device: str | None = None, gender: str | None = None,
                     ages: list[str] | None = None) -> DataLabResult:
        if not self.client_id or not self.client_secret:
            raise NaverDataLabError(
                "네이버 데이터랩 인증정보가 없습니다. NAVER_DATALAB_CLIENT_ID와 "
                "NAVER_DATALAB_CLIENT_SECRET 환경변수를 설정하세요."
            )
        if not keyword_groups:
            raise ValueError("keyword_groups는 1개 이상이어야 합니다.")
        if time_unit not in {"date", "week", "month"}:
            raise ValueError("time_unit은 date, week, month 중 하나여야 합니다.")
        payload: dict[str, object] = {
            "startDate": start_date, "endDate": end_date,
            "timeUnit": time_unit, "keywordGroups": keyword_groups,
        }
        if device:
            payload["device"] = device
        if gender:
            payload["gender"] = gender
        if ages:
            payload["ages"] = ages
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise NaverDataLabError(f"네이버 데이터랩 요청 실패: HTTP {exc.code}") from None
        except (URLError, TimeoutError):
            raise NaverDataLabError("네이버 데이터랩에 연결할 수 없습니다.") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NaverDataLabError("네이버 데이터랩 응답을 해석할 수 없습니다.") from None

        results = []
        for row in data.get("results", []):
            results.append(DataLabSeries(
                title=str(row.get("title") or ""),
                keywords=tuple(str(x) for x in row.get("keywords", [])),
                data=tuple(dict(point) for point in row.get("data", [])),
            ))
        return DataLabResult(
            start_date=str(data.get("startDate") or start_date),
            end_date=str(data.get("endDate") or end_date),
            time_unit=str(data.get("timeUnit") or time_unit),
            results=tuple(results),
        )
