"""Daily keyword snapshots and transparent content-opportunity ranking.

All metrics describe the collected RSS feeds only. No search volume, social reach,
or keyword competition is inferred from feed recurrence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import tempfile
from typing import Iterable

from .models import ScoutCandidate
from .trends import TrendSignal, aggregate_trends


@dataclass(frozen=True)
class KeywordObservation:
    observed_on: str
    keyword: str
    candidate_count: int
    source_count: int
    candidate_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["candidate_ids"] = list(self.candidate_ids)
        row["measurement"] = "collected_feed_recurrence"
        return row


@dataclass(frozen=True)
class Opportunity:
    keyword: str
    score: int
    candidate_count: int
    source_count: int
    reasons: tuple[str, ...]
    limitations: tuple[str, ...] = (
        "검색량 미확인", "키워드 경쟁도 미확인", "SNS 반응 미확인",
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "keyword": self.keyword, "score": self.score,
            "candidate_count": self.candidate_count,
            "source_count": self.source_count,
            "reasons": list(self.reasons),
            "limitations": list(self.limitations),
            "measurement": "heuristic_feed_opportunity",
        }


def observations_for_day(candidates: Iterable[ScoutCandidate],
                         observed_on: str | None = None) -> list[KeywordObservation]:
    day = observed_on or date.today().isoformat()
    return [
        KeywordObservation(day, signal.keyword, signal.candidate_count,
                           signal.source_count, signal.candidate_ids)
        for signal in aggregate_trends(candidates)
    ]


def load_history(path: Path | str) -> list[KeywordObservation]:
    target = Path(path)
    if not target.exists():
        return []
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise ValueError("키워드 이력 JSON 구조가 올바르지 않습니다.")
    rows = []
    for item in payload["observations"]:
        if not isinstance(item, dict):
            continue
        rows.append(KeywordObservation(
            observed_on=str(item.get("observed_on") or ""),
            keyword=str(item.get("keyword") or ""),
            candidate_count=int(item.get("candidate_count") or 0),
            source_count=int(item.get("source_count") or 0),
            candidate_ids=tuple(str(x) for x in item.get("candidate_ids", [])),
        ))
    return rows


def save_history(observations: Iterable[KeywordObservation], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # One record per keyword per day. Re-running today's job replaces today's snapshot.
    keyed = {(row.observed_on, row.keyword): row for row in observations}
    ordered = sorted(keyed.values(), key=lambda row: (row.observed_on, row.keyword))
    payload = {
        "schema_version": 1,
        "measurement": "collected_feed_recurrence",
        "observations": [row.to_dict() for row in ordered],
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                     delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(target)


def rising_keywords(history: Iterable[KeywordObservation],
                    current_day: str) -> list[dict[str, object]]:
    rows = list(history)
    current = {r.keyword: r for r in rows if r.observed_on == current_day}
    prior_days = sorted({r.observed_on for r in rows if r.observed_on < current_day})
    if not prior_days:
        return []
    previous_day = prior_days[-1]
    previous = {r.keyword: r for r in rows if r.observed_on == previous_day}
    rising = []
    for keyword, now in current.items():
        before = previous.get(keyword)
        if before and now.candidate_count > before.candidate_count:
            rising.append({
                "keyword": keyword, "previous_day": previous_day,
                "current_day": current_day,
                "previous_count": before.candidate_count,
                "current_count": now.candidate_count,
                "change": now.candidate_count - before.candidate_count,
                "measurement": "collected_feed_recurrence_change",
            })
    return sorted(rising, key=lambda x: (int(x["change"]), str(x["keyword"])), reverse=True)


def score_opportunities(signals: Iterable[TrendSignal]) -> list[Opportunity]:
    """Heuristic editorial shortlist; never label as low competition or search demand."""
    results = []
    for signal in signals:
        score = min(40, signal.candidate_count * 10) + min(30, signal.source_count * 15)
        reasons = [
            f"수집 피드에서 {signal.candidate_count}건 언급",
            f"서로 다른 출처 {signal.source_count}곳에서 관측",
        ]
        if signal.source_count >= 2:
            reasons.append("복수 출처 교차 확인 가능")
        results.append(Opportunity(signal.keyword, score, signal.candidate_count,
                                   signal.source_count, tuple(reasons)))
    return sorted(results, key=lambda x: (x.score, x.candidate_count, x.keyword),
                  reverse=True)


def build_daily_report(candidates: list[ScoutCandidate], history: list[KeywordObservation],
                       observed_on: str) -> dict[str, object]:
    signals = aggregate_trends(candidates)
    today = observations_for_day(candidates, observed_on)
    merged = [row for row in history if row.observed_on != observed_on] + today
    return {
        "generated_on": observed_on,
        "measurement_scope": "등록된 공개 RSS 수집 피드 내부",
        "top_keywords": [s.to_dict() for s in signals[:20]],
        "rising_keywords": rising_keywords(merged, observed_on)[:10],
        "content_opportunities": [o.to_dict() for o in score_opportunities(signals)[:5]],
        "limitations": [
            "검색량 및 검색 추세를 측정하지 않았습니다.",
            "SNS 조회·좋아요·공유량을 측정하지 않았습니다.",
            "키워드 광고·검색 경쟁도를 측정하지 않았습니다.",
            "급상승은 직전 저장 관측일 대비 피드 내 언급 건수 증가만 의미합니다.",
        ],
    }


def render_daily_report(report: dict[str, object]) -> str:
    lines = [
        f"# TAK AUTO 트렌드 리포트 — {report['generated_on']}", "",
        f"측정 범위: {report['measurement_scope']}", "",
        "## 오늘의 반복 키워드 TOP 20", "",
    ]
    top = report["top_keywords"]
    lines.extend([f"- {x['keyword']}: {x['candidate_count']}건 / 출처 {x['source_count']}곳"
                  for x in top] or ["- 반복 키워드 없음"])
    lines.extend(["", "## 급상승 키워드 TOP 10", "",
                  "> 직전 저장 관측일과 비교한 피드 내 언급 건수 증가입니다. 검색량 급상승이 아닙니다.", ""])
    rising = report["rising_keywords"]
    lines.extend([f"- {x['keyword']}: {x['previous_count']}건 → {x['current_count']}건 (+{x['change']})"
                  for x in rising] or ["- 비교 가능한 과거 관측 데이터가 부족하거나 증가 키워드가 없습니다."])
    lines.extend(["", "## 콘텐츠 기회 후보 TOP 5", "",
                  "> 편집 우선순위 참고 점수이며 검색 경쟁도·수요 점수가 아닙니다.", ""])
    opportunities = report["content_opportunities"]
    lines.extend([f"- {x['keyword']} ({x['score']}점): " + ", ".join(x["reasons"])
                  for x in opportunities] or ["- 후보 없음"])
    lines.extend(["", "## 데이터 한계", ""])
    lines.extend([f"- {x}" for x in report["limitations"]])
    return "\n".join(lines) + "\n"
