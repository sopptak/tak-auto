"""MONEY Scout 실행기(6-61) - 버튼/예약 작업이 **실제로** 브라우저 에이전트를 부른다.

    run_scout()
      -> run_agent(): `claude --chrome -p <지시>` (Claude Code + Claude in Chrome, 헤드리스)
           허용 도구는 탭 열기/이동/화면 글자 읽기/탭 닫기뿐 - 클릭·입력·폼 도구가 없어 로그인·응답·제출이 불가능하다.
           plan()이 자동 방문을 허용한 플랫폼(PanelNow)만 연다. 결과는 표준출력의 JSON 한 개.
      -> money_scout.ingest(): 검사·개인정보 제거·정규화·중복 병합·staging (6-60 파이프라인 그대로)

에이전트가 없거나(claude 명령 없음) Chrome/확장 연결이 안 되거나 시간이 넘으면 그 상태를 기록하고 끝낸다 -
가짜 결과를 만들지 않는다. 사용자의 Claude 사용량을 쓴다(1회 약 1분).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from content_engine import money, money_scout

AGENT_TOOLS = ("mcp__claude-in-chrome__tabs_context_mcp", "mcp__claude-in-chrome__tabs_create_mcp", "mcp__claude-in-chrome__navigate",
               "mcp__claude-in-chrome__get_page_text", "mcp__claude-in-chrome__tabs_close_mcp")
TIMEOUT_SECONDS = 300


def build_prompt(plan: list[dict]) -> str:
    targets = "\n".join(f"- platform={p['platform']} url={p['url']}" for p in plan if p["visit"])
    return (
        "너는 TAK AUTO MONEY의 읽기 전용 스카우트다. 아래 주소만 새 탭에서 열고 화면 글자를 읽기만 해라.\n"
        "절대 금지: 클릭, 입력, 로그인, 인증, 설문 참여/응답/제출, 포인트 교환, 광고 클릭, 목록에 없는 주소 방문.\n"
        "로그인 화면이나 사람 확인(CAPTCHA) 화면이 나오면 아무것도 하지 말고 그대로 보고해라.\n"
        f"{targets}\n"
        "각 주소마다 get_page_text로 읽은 글자를 그대로(요약·수정 없이) 담아, 마지막에 JSON 한 개만 출력해라(다른 글 없이):\n"
        '{"platforms": [{"platform": "<위 platform>", "page_url": "<연 주소>", "observed_at": "<ISO 시각>", '
        '"page_text": "<읽은 글자>", "note": "<로그인/CAPTCHA/오류가 있었다면 짧게>"}]}\n'
        "연 탭은 닫아라."
    )


def _extract_json(stdout: str) -> dict | None:
    start, end = stdout.find("{"), stdout.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(stdout[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("platforms"), list) else None


def run_agent(*, claude: str | None = None, timeout: int = TIMEOUT_SECONDS, runner=subprocess.run, plan: list[dict] | None = None) -> dict:
    """에이전트를 한 번 실행해 6-60 raw 형식을 돌려준다. 방문하지 않는 플랫폼은 정책 상태를 붙인다."""
    plan = plan or money_scout.plan()
    visit = [p for p in plan if p["visit"]]
    raw = {"mode": "agent", "agent": "claude-cli --chrome",
           "platforms": [{"platform": p["platform"], "status": p["skip_status"], "detail": "plan(): 자동 방문 안 함"} for p in plan if not p["visit"]]}

    def fail(status: str, detail: str) -> dict:
        raw["platforms"] += [{"platform": p["platform"], "status": status, "detail": detail[:200]} for p in visit]
        return raw

    exe = claude or shutil.which("claude")
    if not exe:
        return fail("AGENT_UNAVAILABLE", "claude 명령을 찾을 수 없음(Claude Code 설치 필요)")
    # 지시는 표준입력으로 - Windows의 claude.CMD 경유 인자는 첫 줄바꿈에서 잘린다(6-61 실제 실행에서 확인)
    cmd = [exe, "--chrome", "-p", "--allowedTools", ",".join(AGENT_TOOLS), "--permission-mode", "dontAsk", "--max-turns", "20"]
    try:
        done = runner(cmd, input=build_prompt(plan), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        return fail("AGENT_UNAVAILABLE", "claude 실행 파일 없음")
    except subprocess.TimeoutExpired:
        return fail("TIMEOUT", f"{timeout}초 안에 끝나지 않음")
    if done.returncode != 0:
        return fail("AGENT_FAILED", (done.stderr or done.stdout or "").strip()[-200:] or f"exit {done.returncode}")
    data = _extract_json(done.stdout or "")
    if data is None:
        return fail("PARSE_FAILED", "에이전트 출력에서 결과 JSON을 찾지 못함")
    allowed = {p["platform"] for p in visit}
    got = {e.get("platform"): e for e in data["platforms"] if isinstance(e, dict) and e.get("platform") in allowed}
    for p in visit:
        e = got.get(p["platform"])
        if e is None or not str(e.get("page_text") or "").strip():
            raw["platforms"].append({"platform": p["platform"], "status": "PARSE_FAILED", "detail": "에이전트가 이 플랫폼 화면을 돌려주지 않음"})
            continue
        raw["platforms"].append({"platform": p["platform"], "page_url": str(e.get("page_url") or p["url"])[:300],
                                 "observed_at": str(e.get("observed_at") or "")[:40], "page_text": str(e["page_text"])[:money_scout.MAX_TEXT_CHARS],
                                 "links": []})
    return raw


def run_scout(*, tasks_path: Path | str, staging_path: Path | str, now: datetime | None = None, request_id: str | None = None,
              **agent_kwargs) -> dict:
    """에이전트 실행 -> ingest. request_id의 실행 요청이 이 결과로 닫힌다."""
    raw = run_agent(**agent_kwargs)
    if request_id:
        raw["request_id"] = request_id
    return money_scout.ingest(raw, tasks_path=tasks_path, staging_path=staging_path, now=now or money._now())


def schtasks_command(time: str = "09:00", python: str = "py") -> str:
    """Windows 작업 스케줄러 등록 명령(자동 등록하지 않는다 - 사용자가 직접 실행). Chrome이 켜져 있고 확장이 연결돼 있어야 읽힌다."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "money_scout.py"
    return f'schtasks /Create /SC DAILY /ST {time} /TN "TAK AUTO MONEY Scout" /TR "{python} \\"{script}\\" run"'
