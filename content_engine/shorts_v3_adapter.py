"""기존 ShortsScript(6-40 title/cards/takeaway) -> Shorts V3 문서(dict) 변환(6-52).

    기존 ShortsScript JSON -> 이 adapter -> V3 문서 JSON(사람이 고칠 수 있음) -> V3 renderer -> MP4

- 카드 문장은 바꾸지 않는다. 카드 하나가 본문 프레임에 안 들어가면 문장 경계에서만 장면을 나눈다.
- takeaway의 "출처: URL"은 본문이 아니라 각 장면의 source(footer)로 옮긴다(도메인만 표시, 원문은 lineage).
- 원본 ShortsScript/Production Archive를 읽기만 한다 - 결과 문서는 호출자가 원하는 곳에 저장한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from content_engine.shorts_script import ShortsScript
from content_engine.shorts_v2_renderer import LOOKS
from content_engine.shorts_v3_document import SCHEMA
from content_engine.shorts_v3_layout import fit_paragraphs, sub_rect
from content_engine.shorts_v3_template import load_template


def source_label(takeaway: str) -> tuple[str, str]:
    """'출처: https://www.bbc.co.uk/...' -> ('bbc.co.uk', 원문 URL). 출처 형식이 아니면 ('', '')."""
    m = re.match(r"\s*출처\s*[:：]\s*(\S+)", takeaway or "")
    if not m:
        return "", ""
    url = m.group(1)
    host = urlsplit(url).netloc
    return (host.removeprefix("www.") if host else url), url


def _fits(text: str, template: dict) -> bool:
    rect = sub_rect(tuple(template["frames"]["content"]), template["layouts"]["text_focus"]["text"])
    return fit_paragraphs(text, LOOKS[template["look"]], rect, template["text"]["body"]) is not None


def split_to_fit(card: str, template: dict) -> list[str]:
    """본문 프레임에 들어가도록 문장 경계에서만 묶음을 나눈다(글자는 그대로)."""
    if _fits(card, template):
        return [card]
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.?!])\s+", card.strip()):
        if chunks and _fits(f"{chunks[-1]} {sentence}", template):
            chunks[-1] = f"{chunks[-1]} {sentence}"
        else:
            chunks.append(sentence)  # 문장 하나가 안 들어가면 렌더러가 overflow로 알린다(자르지 않음)
    return chunks


def document_from_shorts_script(data: Mapping, *, generation_id: str | None = None, source_script: str = "",
                                template: str = "default") -> dict:
    script = ShortsScript.from_dict(data)  # 기존 스키마 검증 재사용
    tpl = load_template(template)
    label, url = source_label(script.takeaway)
    scenes = []
    for card in script.cards:
        for chunk in split_to_fit(card, tpl):
            scene = {"layout": "text_focus", "body": chunk}
            if label:  # 6-54: 원문 URL을 그대로 두고 화면에는 템플릿 source_labels로 읽을 수 있는 이름(BBC)만 표시
                scene["source"] = url
            scenes.append(scene)
    raw = json.dumps(dict(data), ensure_ascii=False, sort_keys=True).encode("utf-8")
    doc = {
        "schema": SCHEMA,
        "id": str(data.get("content_id") or ""),
        "template": template,
        "title": script.title,
        "lineage": {
            "content_id": data.get("content_id"),
            "generation_id": generation_id,
            "knowledge_id": data.get("knowledge_id"),
            "source_script": source_script,
            "source_script_canonical_sha256": hashlib.sha256(raw).hexdigest(),
            "source_url": url or None,
            "adapter": "shorts_v3_adapter.document_from_shorts_script",
        },
        "scenes": scenes,
    }
    if script.brand != tpl["brand"]["text"]:
        doc["brand"] = script.brand
    if not label and script.takeaway:  # 출처 형식이 아닌 takeaway는 마지막 장면 본문으로 둔다
        doc["scenes"].append({"layout": "text_focus", "body": script.takeaway})
    return doc

