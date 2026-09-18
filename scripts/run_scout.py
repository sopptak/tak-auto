#!/usr/bin/env python3
"""등록된 RSS source에서 오늘의 TAK SCOUT 후보를 수집하는 CLI.

TAK SCOUT는 공개 RSS만 읽는다. 로그인, 브라우저 크롤링, 접근 제한 우회는 하지 않으며
원문 전체를 복사하지 않고 제목/짧은 요약/URL 중심으로만 후보를 저장한다.

    data/scout_sources.json        읽기 전용 RSS source 목록(사람이 직접 관리)
    data/tak_scout_daily.json      프로그램 처리용 결과(다음 단계: run_interview.py)
    data/tak_scout_daily.md        사람이 보기 위한 결과
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tak_scout.collector import (
    DEFAULT_MAX_CANDIDATES,
    collect_all,
    dedupe_candidates,
    load_sources,
    save_daily_pack_json,
    save_daily_pack_markdown,
)
from tak_scout.scoring import top_candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK SCOUT 오늘의 소재 후보 수집기")
    parser.add_argument(
        "--sources",
        type=Path,
        default=ROOT / "data" / "scout_sources.json",
        help="RSS source 목록 JSON 경로 (기본값: data/scout_sources.json)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily.json",
        help="프로그램 처리용 결과 저장 경로 (기본값: data/tak_scout_daily.json)",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "data" / "tak_scout_daily.md",
        help="사람이 보기 위한 결과 저장 경로 (기본값: data/tak_scout_daily.md)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help=f"오늘 선정할 후보의 최대 개수 (기본값: {DEFAULT_MAX_CANDIDATES})",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="RSS 요청 타임아웃(초)")
    args = parser.parse_args(argv)

    try:
        sources = load_sources(args.sources)
    except (OSError, ValueError) as err:
        print(f"오류: source 목록을 읽을 수 없습니다: {err}", file=sys.stderr)
        return 1

    if not sources:
        print("오류: 등록된 RSS source가 없습니다. data/scout_sources.json을 확인하세요.", file=sys.stderr)
        return 1

    print(f"TAK SCOUT: 등록된 source {len(sources)}개에서 수집 시작...")
    raw_candidates, results = collect_all(sources, timeout=args.timeout)

    for result in results:
        if result.error:
            print(f"  실패: {result.name} ({result.url}) - {result.error}")
        else:
            print(f"  성공: {result.name} - {result.candidate_count}건 수집")

    # 5-19: 수집 순서(도착 순)가 아니라 TAK SCOUT SCORE(tak_scout.scoring, LLM 없는
    # rule-based 점수) 기준 상위 --max건을 "오늘의 후보"로 선정한다. 점수 계산
    # 로직 자체(scoring.py)는 전혀 수정하지 않았고, 기존에도 Dashboard "/" 화면이
    # 같은 함수(rank_candidates)로 정렬해서 보여주던 것과 동일한 기준이다 - 여기서는
    # "보여주는 순서"가 아니라 "선정되는 후보 자체"에 그 기준을 연결했을 뿐이다.
    deduped = dedupe_candidates(raw_candidates)
    ranked = top_candidates(deduped, n=args.max)
    candidates = [candidate for candidate, _score in ranked]

    save_daily_pack_json(candidates, args.output_json)
    save_daily_pack_markdown(candidates, args.output_md)

    print(f"오늘의 후보 {len(candidates)}건 선정 완료 (최대 {args.max}건, 중복 제거 후 SCOUT SCORE 상위)")
    print(f"JSON 저장: {args.output_json}")
    print(f"MD 저장: {args.output_md}")
    print("다음 단계: python3 scripts/run_interview.py 로 티몽에게 질문을 만드세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
