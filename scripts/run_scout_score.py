#!/usr/bin/env python3
"""TAK SCOUT SCORE: 오늘 수집된 SCOUT 후보를 점수화해 "먼저 볼 만한 소재" 순으로
정렬해 보여주는 CLI.

이 스크립트는 새로 RSS를 수집하지 않는다. scripts/run_scout.py가 이미 만든
data/tak_scout_daily.json을 읽기 전용으로 읽어(tak_scout.load_daily_pack),
tak_scout.scoring으로 점수를 매기고 정렬한 결과만 보여주거나 별도 파일로
저장한다.

scripts/run_scout.py의 기존 출력(data/tak_scout_daily.json,
data/tak_scout_daily.md)은 이 스크립트가 전혀 건드리지 않는다 - 100% 하위
호환. 점수가 반영된 결과는 별도 파일(기본값: data/tak_scout_daily_scored.json,
data/tak_scout_daily_scored.md)에 저장한다. JSON의 각 후보 항목은 기존
ScoutCandidate 필드(scout_id/title/summary/source_url/published_at/
source_name/category)에 score/score_breakdown/recommendation_reason 필드만
"추가"한 형태라서, 기존 ScoutCandidate.from_dict()로도 그대로 읽을 수 있다
(모르는 필드는 무시된다).

LLM을 쓰지 않는다(tak_scout.scoring 참고: 완전히 rule-based/deterministic).
TAK INTERVIEW / TAK BRAIN / TAK MEDIA 코드는 호출하지 않는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.models import utc_now
from tak_scout.collector import load_daily_pack
from tak_scout.models import ScoutCandidate
from tak_scout.scoring import ScoutScore, rank_candidates

_BREAKDOWN_LABELS: tuple[tuple[str, str, int], ...] = (
    ("content_interest", "콘텐츠 관심도", 25),
    ("expertise_relevance", "티몽 전문성", 25),
    ("opinion_potential", "의견 가능성", 20),
    ("monetization_relevance", "수익화 관련성", 15),
    ("recency", "최신성", 15),
)


def _format_entry(rank: int, candidate: ScoutCandidate, score: ScoutScore) -> list[str]:
    lines = [f"[{rank}] {score.total}점 - {candidate.title}", ""]
    for key, label, max_value in _BREAKDOWN_LABELS:
        lines.append(f"  {label}: {score.breakdown[key]}/{max_value}")
    lines.append("")
    lines.append(f"  추천 이유: {score.recommendation_reason}")
    lines.append(f"  scout_id: {candidate.scout_id}")
    return lines


def render_scored_markdown(
    ranked: list[tuple[ScoutCandidate, ScoutScore]], top_n: int, generated_at: str | None = None
) -> str:
    generated_at = generated_at or utc_now()
    lines = [
        "# TAK SCOUT SCORE",
        "",
        f"생성 시각(UTC): {generated_at}",
        f"전체 후보: {len(ranked)}건 (표시: 상위 {min(top_n, len(ranked))}건)",
        "",
        "점수는 LLM 없이 제목/요약/category/발행시각만으로 계산한 규칙 기반",
        "점수다(총 100점: 콘텐츠 관심도 25 + 티몽 전문성 25 + 의견 가능성 20 +",
        "수익화 관련성 15 + 최신성 15). 최종 판단은 사람이 한다.",
        "",
    ]
    for index, (candidate, score) in enumerate(ranked[:top_n], start=1):
        lines.append(f"## [{index}] {score.total}점 - {candidate.title}")
        lines.append("")
        for key, label, max_value in _BREAKDOWN_LABELS:
            lines.append(f"- {label}: {score.breakdown[key]}/{max_value}")
        lines.append("")
        lines.append(f"추천 이유: {score.recommendation_reason}")
        lines.append("")
        lines.append(f"출처: {candidate.source_name} ({candidate.category})")
        lines.append(f"원문: {candidate.source_url}")
        lines.append(f"scout_id: {candidate.scout_id}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_scored_json(
    ranked: list[tuple[ScoutCandidate, ScoutScore]], path: Path, generated_at: str | None = None
) -> None:
    payload = {
        "generated_at": generated_at or utc_now(),
        "candidate_count": len(ranked),
        # 정렬 순서를 그대로 저장한다(점수 내림차순). 각 후보 dict는 기존
        # ScoutCandidate.to_dict()에 score 관련 필드만 얹은 것이라 기존
        # ScoutCandidate.from_dict()로도 읽을 수 있다(모르는 필드는 무시).
        "candidates": [
            {**candidate.to_dict(), **score.to_dict()} for candidate, score in ranked
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TAK SCOUT SCORE: 오늘 SCOUT 후보를 점수화해 상위 소재 순으로 보여준다"
    )
    parser.add_argument(
        "--daily-pack",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily.json",
        help="읽기 전용 TAK SCOUT 결과 경로 (기본값: data/tak_scout_daily.json)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily_scored.json",
        help="점수 포함 결과 저장 경로(JSON, 기본값: data/tak_scout_daily_scored.json)",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily_scored.md",
        help="점수 포함 결과 저장 경로(Markdown, 기본값: data/tak_scout_daily_scored.md)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="화면/MD에 보여줄 상위 개수 (기본값: 10)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="파일 저장 없이 터미널 출력만 한다",
    )
    args = parser.parse_args(argv)

    if not args.daily_pack.exists():
        print(
            f"오류: {args.daily_pack}가 없습니다. 먼저 python3 scripts/run_scout.py를 실행하세요.",
            file=sys.stderr,
        )
        return 1

    try:
        candidates = load_daily_pack(args.daily_pack)
    except (OSError, ValueError) as error:
        print(f"오류: TAK SCOUT 결과를 읽을 수 없습니다: {error}", file=sys.stderr)
        return 1

    if not candidates:
        print("오늘 점수화할 SCOUT 후보가 없습니다.")
        return 0

    ranked = rank_candidates(candidates)
    generated_at = utc_now()

    print(f"TAK SCOUT SCORE: 후보 {len(candidates)}건 점수화 완료 (상위 {min(args.top, len(ranked))}건 표시)")
    print()
    for index, (candidate, score) in enumerate(ranked[: args.top], start=1):
        for line in _format_entry(index, candidate, score):
            print(line)

    if not args.no_save:
        save_scored_json(ranked, args.output_json, generated_at=generated_at)
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(
            render_scored_markdown(ranked, args.top, generated_at=generated_at), encoding="utf-8"
        )
        print(f"JSON 저장: {args.output_json}")
        print(f"MD 저장: {args.output_md}")
        print(
            f"안내: {args.daily_pack.name}, {args.daily_pack.with_suffix('.md').name}은 "
            "전혀 건드리지 않았습니다(기존 run_scout.py 출력 그대로 유지)."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
