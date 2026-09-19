"""TAK SCOUT Dashboard 전용 "관심 없음" 상태 저장.

기존 TAK INTERVIEW 답변(A/B/C/D)과는 다른 개념이다 - "이 소재에는 관심이 없어
답하지 않겠다"는 뜻이라 InterviewAnswer 스키마에 억지로 끼워 넣지 않는다. 그래서
완전히 별도 파일(data/tak_scout_dashboard_skipped.json)에 최소 구조로 저장한다.
이 파일은 tak_scout.answers / tak_scout.knowledge_bridge / apply_interview.py
어디에서도 읽지 않으며, 이 파일을 추가한다고 해서 기존 흐름이 전혀 바뀌지
않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from blog_importer.models import utc_now


@dataclass(frozen=True)
class SkippedCandidate:
    scout_id: str
    skipped_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"scout_id": self.scout_id, "skipped_at": self.skipped_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkippedCandidate":
        scout_id = str(data.get("scout_id") or "")
        if not scout_id:
            raise ValueError("scout_id가 필요합니다.")
        return cls(scout_id=scout_id, skipped_at=str(data.get("skipped_at") or ""))


def load_skipped(path: Path | str) -> list[SkippedCandidate]:
    """건너뛴(관심 없음) 소재 목록을 읽는다. 파일이 없거나 비어 있으면 빈 목록."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    data = json.loads(raw_text)
    if not isinstance(data, list):
        raise ValueError("tak_scout_dashboard_skipped.json은 목록 구조여야 합니다.")
    return [SkippedCandidate.from_dict(item) for item in data]


def save_skipped(records: list[SkippedCandidate], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.to_dict() for record in records]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_skipped(path: Path | str, scout_id: str) -> list[SkippedCandidate]:
    """scout_id를 "관심 없음"으로 표시한다(같은 scout_id면 시각만 갱신, 중복 저장 안 함)."""
    if not scout_id:
        raise ValueError("scout_id가 필요합니다.")
    by_scout_id = {record.scout_id: record for record in load_skipped(path)}
    by_scout_id[scout_id] = SkippedCandidate(scout_id=scout_id, skipped_at=utc_now())
    result = list(by_scout_id.values())
    save_skipped(result, path)
    return result


def skipped_scout_ids(path: Path | str) -> frozenset[str]:
    return frozenset(record.scout_id for record in load_skipped(path))
