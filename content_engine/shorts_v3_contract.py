"""Shorts V3 편집 계약(6-54) - 향후 Dashboard Editor / DB가 렌더러에 넣을 수 있는 데이터의 모양.

    editable_fields(template)  -> 편집기가 보여줄 필드 목록(선택지 포함, 템플릿에서 계산)
    check_document(data, base_dir) -> 렌더 없이 바로 검사(오류 코드 + 장면 길이) - 편집 중 실시간 피드백용

편집기는 V3 문서 JSON만 만들고, 렌더는 scripts/render_shorts_v3.py(또는 shorts_v3_pipeline.render_batch)가 한다.
"""

from __future__ import annotations

from pathlib import Path

from content_engine.shorts_v3_document import IMAGE_FITS, TRANSITIONS, V3RenderDocument, _POSITIONS
from content_engine.shorts_v3_pipeline import quality_gate, structure_issues
from content_engine.shorts_v3_layout import LayoutEngine
from content_engine.shorts_v3_template import V3Error, load_template

READ_ONLY = ("schema", "id", "template", "lineage")  # 편집기가 보여주되 고치지 않는 값


def editable_fields(template: dict | str = "default") -> dict:
    tpl = load_template(template) if isinstance(template, str) else template
    return {
        "document": {"title": "text", "brand": "text", "cta": "text",
                     "progress": {"enabled": "bool", "position": ["footer", "top"], "mode": ["time", "scene"], "counter": "bool"},
                     "audio": {"enabled": "bool", "background": ["ai", "finance", "human"], "volume": "number 0~2",
                               "fade_in": "seconds", "fade_out": "seconds"}},
        "scene": {"layout": sorted(tpl["layouts"]), "headline": "text", "body": "text(빈 줄 = 문단)", "subtitle": "text",
                  "emphasis": "list[text]", "source": {"label": "text", "value": "text | URL"},
                  "image": {"path": "file", "alt": "text", "source": "text", "fit": list(IMAGE_FITS),
                            "position": list(_POSITIONS) + ["{x, y} 0~1"], "scale": "number 1~4"},
                  "duration": f"seconds {tpl['timing']['min_scene_seconds']}~{tpl['timing']['max_scene_seconds']} (비우면 자동)",
                  "transition": list(TRANSITIONS)},
        "read_only": list(READ_ONLY),
    }


def check_document(data: dict, base_dir: Path | str = ".") -> dict:
    """렌더 없이 검사: {"ok", "codes", "errors", "warnings", "scenes": [{index, start, duration, layout}], "total"}."""
    try:
        doc = V3RenderDocument.from_dict(data, base_dir=base_dir)
    except V3Error as error:
        return {"ok": False, "codes": [error.code], "errors": [error.message], "warnings": [], "scenes": [], "total": None}
    layout = LayoutEngine(doc).report()
    verdict = quality_gate(structure_issues(doc, layout))
    return {"ok": verdict["status"] == "PASS", "codes": verdict["codes"], "errors": [e["message"] for e in verdict["errors"]],
            "warnings": [w["code"] for w in verdict["warnings"]], "total": layout["total"],
            "scenes": [{k: s[k] for k in ("index", "start", "duration", "layout")} for s in layout["scenes"]]}
