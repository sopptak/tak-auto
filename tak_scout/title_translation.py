"""TAK SCOUT 후보 제목의 한국어 표시용 번역 캐시(Dashboard 사용성 개선).

이 모듈은 오직 캐시 데이터 구조와 저장/로드만 담당한다. 번역 자체(LLM 호출)는
tak_scout/interview_llm.py의 InterviewLLMProvider.translate_titles()가 한다 - 이
파일은 그 결과를 scout_id 기준으로 저장해 두어, 같은 후보를 다시 볼 때 LLM을
반복 호출하지 않게 하는 것이 유일한 목적이다.

scout_id는 title+source_url의 결정적 해시(compute_scout_id)이므로, 원문 제목이
바뀌면 scout_id 자체가 달라진다 - 그래서 이 캐시는 "오염된(stale) 번역"을 걱정할
필요가 없다. 같은 scout_id는 항상 같은 원문 제목을 의미한다.

원문 title(ScoutCandidate.title)은 이 모듈이 절대 수정하지 않는다 - 여기 저장하는
것은 화면 표시 전용 별도 필드(display_title)뿐이다. KNOWLEDGE 생성
(tak_scout/knowledge_bridge.py)은 이 파일을 전혀 참조하지 않으므로 SOURCE
FACT/title은 항상 원문 그대로 유지된다.

같은 패턴을 그대로 따른다(tak_scout/interview_session.py 참고):
    load_translations()   파일이 없거나 비어 있으면 빈 목록
    save_translations()   tempfile + os.replace로 원자적 저장
    upsert_translation()  scout_id 기준으로 덮어쓰기(중복 없음)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
from typing import Any


class TitleTranslationError(ValueError):
    """번역 캐시 구조가 올바르지 않을 때 발생한다."""


@dataclass(frozen=True)
class TitleTranslation:
    """소재 1건(scout_id)의 한국어 표시용 제목 캐시 1건."""

    scout_id: str
    source_title: str
    display_title: str
    translated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scout_id": self.scout_id,
            "source_title": self.source_title,
            "display_title": self.display_title,
            "translated_at": self.translated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TitleTranslation":
        if not isinstance(data, dict):
            raise TitleTranslationError("번역 캐시 항목은 객체여야 합니다.")
        scout_id = str(data.get("scout_id") or "")
        if not scout_id:
            raise TitleTranslationError("scout_id가 필요합니다.")
        display_title = str(data.get("display_title") or "")
        if not display_title:
            raise TitleTranslationError("display_title이 필요합니다.")
        return cls(
            scout_id=scout_id,
            source_title=str(data.get("source_title") or ""),
            display_title=display_title,
            translated_at=str(data.get("translated_at") or ""),
        )


def load_translations(path: Path | str) -> list[TitleTranslation]:
    """번역 캐시 파일을 읽는다. 파일이 없거나 비어 있으면 빈 목록을 반환한다."""
    target = Path(path)
    if not target.exists():
        return []
    raw_text = target.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    data = json.loads(raw_text)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise TitleTranslationError("tak_scout_title_translations.json은 객체 목록이어야 합니다.")
    return [TitleTranslation.from_dict(item) for item in data]


def save_translations(translations: list[TitleTranslation], path: Path | str) -> None:
    """번역 캐시를 원자적으로(tempfile + replace) 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [translation.to_dict() for translation in translations]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(target)


def upsert_translation(path: Path | str, translation: TitleTranslation) -> list[TitleTranslation]:
    """같은 scout_id의 기존 캐시는 덮어쓰고, 새 scout_id는 추가한다."""
    by_scout_id = {existing.scout_id: existing for existing in load_translations(path)}
    by_scout_id[translation.scout_id] = translation
    result = list(by_scout_id.values())
    save_translations(result, path)
    return result


def translations_by_scout_id(path: Path | str) -> dict[str, TitleTranslation]:
    """조회 편의용: scout_id -> TitleTranslation 매핑을 만든다."""
    return {translation.scout_id: translation for translation in load_translations(path)}
