"""TAK AUTO MONEY 화면(6-57, 6-58) - scripts/run_scout_dashboard.py가 /money 요청을 여기로 넘긴다.

첫 화면은 "통계판"보다 "오늘 무엇을 할까"가 먼저 보이게 한다:
    ① 오늘의 수익 ② 첫 10,000원 ③ 오늘의 MONEY ROUTINE(오늘 할 일) ④ 지금 확인할 플랫폼 ⑤ 수익 기회 ⑥ 할 작업 ⑦ 최근 수익 기록

화면은 계산·기록·공식 링크만 한다. 외부 사이트 로그인/응답/제출/스크래핑 기능이 없고, 비밀번호·토큰·개인정보 입력칸이 없다.
공식 링크는 설정의 주소만, 새 탭(rel="noopener noreferrer")으로 사람이 직접 연다.

    handle(config, method, path, query, body) -> ("html", status, bytes) | ("redirect", url)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from html import escape
import threading
from urllib.parse import parse_qs, quote, unquote

from content_engine import money
from content_engine import money_scout

STYLE = """<style>
  .money { max-width: 1100px; }
  .money .btn { min-height: 40px; }
  .kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 12px; }
  .kpi { background: #fff; border: 1px solid #e2e2e0; border-radius: 10px; padding: 10px 12px; }
  .kpi .k { font-size: 0.75rem; color: #6b6b6b; } .kpi .v { font-size: 1.15rem; font-weight: 800; }
  .kpi .s { font-size: 0.75rem; color: #6b6b6b; }
  @media (max-width: 700px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  .goal { background: #fff; border: 1px solid #e2e2e0; border-radius: 12px; padding: 14px 16px; margin-bottom: 12px; }
  .goal.done { background: #dff3e3; border-color: #b6e0c1; }
  .bar { height: 14px; background: #eee; border-radius: 999px; overflow: hidden; margin: 8px 0; }
  .bar > div { height: 100%; background: #1a5c3a; }
  .tasks { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
  .tasks > .card { grid-column: 1 / -1; max-width: none; }
  .task { background: #fff; border: 1px solid #e2e2e0; border-left: 6px solid #ccc; border-radius: 10px; padding: 12px 14px; }
  .task.GREEN { border-left-color: #2e9e4f; } .task.YELLOW { border-left-color: #e0b400; }
  .task.ORANGE { border-left-color: #e57a1f; } .task.RED { border-left-color: #cf3b3b; } .task.expired { opacity: 0.55; }
  .task .p { font-weight: 700; } .task .t { font-size: 1.02rem; margin: 2px 0 8px; }
  .task .n { font-size: 0.88rem; line-height: 1.7; } .task .rate { font-size: 1.2rem; font-weight: 800; }
  .rec { display: inline-block; font-size: 0.78rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: #eef0f7; color: #33415c; }
  .rec.GREEN { background: #dff3e3; color: #1a5c3a; } .rec.YELLOW { background: #fff4de; color: #6b4a00; }
  .rec.ORANGE { background: #fde8d7; color: #8a4a12; } .rec.RED { background: #f9e0e0; color: #7a2626; }
  .routine { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
  .plat { background: #fff; border: 1px solid #e2e2e0; border-radius: 10px; padding: 12px 14px; }
  .plat.checked { border-color: #b6e0c1; background: #f4fbf5; }
  .plat .name { font-weight: 800; font-size: 1.02rem; } .plat .state { margin: 4px 0 8px; font-size: 0.9rem; }
  .today { background: #fff; border: 1px solid #e2e2e0; border-radius: 12px; padding: 12px 16px; margin-bottom: 12px; }
  .today .nums { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 6px; } .today .nums b { font-size: 1.15rem; }
  .checklist span { display: inline-block; margin: 2px 12px 2px 0; }
  .money input[type=text], .money input[type=number], .money input[type=url], .money input[type=datetime-local], .money select, .money textarea {
    width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #ccc; font-size: 1rem; font-family: inherit; }
  .money label.f { display: block; font-size: 0.8rem; color: #555; margin: 8px 0 3px; font-weight: 600; }
  .money .missing { border-color: #cf3b3b !important; background: #fff6f6; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; } .row > div { flex: 1 1 150px; min-width: 0; }
  .tbl { border-collapse: collapse; width: 100%; background: #fff; font-size: 0.88rem; }
  .tbl th, .tbl td { border-bottom: 1px solid #eee; padding: 7px 8px; text-align: left; }
  .tbl td.num, .tbl th.num { text-align: right; white-space: nowrap; }
  .tbl th, .tbl td:first-child { white-space: nowrap; }
  .scroll { overflow-x: auto; }
  .hint { font-size: 0.78rem; color: #777; } .up { color: #1a5c3a; } .down { color: #b3261e; }
  .btn.big { padding: 10px 16px; font-size: 0.95rem; }
  .legend span { margin-right: 10px; font-size: 0.8rem; }
</style>"""
NAV = ('<div class="nav-links"><a href="/">← Dashboard</a><a href="/money">💰 MONEY</a><a href="/money/scout">🔎 SCOUT</a><a href="/money/platforms">🏪 수익 플랫폼</a>'
       '<a href="/money/log">📒 수익 기록·분석</a><a href="/money/settings">⚙️ 목표·기준</a><a href="/operator">🧭 Operator Center</a></div>')
HOW_TO = ["오늘 확인할 플랫폼을 본다.", "[확인하기 ↗]로 공식 사이트에 직접 들어가 본다(로그인·설문은 그 사이트에서).",
          "할 만한 작업이 있으면 ⚡ 빠른 등록에 적는다(예: 패널나우 20분 850P 일반인 의견 조사). 없으면 [작업 없었음].",
          "확인 화면에서 예상 시급·추천 행동을 보고 등록한다.", "직접 작업한다.", "끝나면 [완료 기록]에 실제 보상과 걸린 시간을 적는다.",
          "MONEY가 실제 시급과 누적 수익, 첫 10,000원까지 남은 금액을 계산한다."]


def _page(title: str, body: str) -> bytes:
    from scripts.run_scout_dashboard import _page as dashboard_page  # 기존 Dashboard 공통 틀/CSS

    return dashboard_page(title, STYLE + body)


def _won(value) -> str:
    return "-" if value is None else f"{int(value):,}원"


def _minutes(value) -> str:
    if not value:
        return "0분"
    value = float(value)
    h, m = divmod(int(round(value)), 60)
    return f"{h}시간 {m}분" if h else f"{value:g}분"


def _rate(value) -> str:
    return "-" if value is None else f"{value:,}원/시간"


def _local(ts: str | None, config: dict, fmt: str = "%Y-%m-%d %H:%M") -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(money.local_tz(config)).strftime(fmt)
    except (TypeError, ValueError):
        return "-"


def _store(config) -> money.MoneyStore:
    return money.MoneyStore(config.money_tasks_path, config.money_log_path, money.load_config(config.money_config_path),
                            getattr(config, "money_checks_path", None))


def _options(values, current) -> str:
    return "".join(f'<option value="{escape(str(v))}"{" selected" if str(v) == str(current or "") else ""}>{escape(str(label))}</option>'
                   for v, label in values)


def _banner(notice: str | None, error: str | None) -> str:
    return (f'<div class="banner">{escape(notice)}</div>' if notice else "") + (f'<div class="error">{escape(error)}</div>' if error else "")


def _ext_link(url: str, label: str, css: str = "btn") -> str:
    return f'<a class="{css}" href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>' if url else ""


# ---- 공통 조각 ------------------------------------------------------------------------------

def _kpis(stats: dict) -> str:
    names = (("today", "오늘"), ("week", "이번 주"), ("month", "이번 달"), ("total", "누적"))
    rows = []
    for key, label, fmt in (("earned", "수익", _won), ("minutes", "투자시간", _minutes), ("hourly", "실제 시간당 수익", _rate)):
        rows += [f'<div class="kpi"><div class="k">{name} {label}</div><div class="v">{escape(fmt(stats[p][key]))}</div>'
                 + (f'<div class="s">{stats[p]["count"]}건</div>' if key == "earned" else "") + "</div>" for p, name in names]
    return f'<div class="kpis">{"".join(rows)}</div>'


def _goal_html(goal: dict) -> str:
    first = goal["first_goal"]
    if not goal["first_achieved"]:
        return f"""<div class="goal"><b>🎯 첫 {first:,}원까지</b> <span class="hint">첫 온라인 수익 목표</span>
<div class="bar"><div style="width:{goal['first_progress']}%"></div></div>
<div class="row"><div>현재: <b>{goal['current']:,}원</b></div><div>남은 금액: <b>{first - goal['current']:,}원</b></div><div>진행률: <b>{goal['first_progress']:g}%</b></div></div></div>"""
    nxt = "" if goal["all_achieved"] else (
        f'<div style="margin-top:8px">다음 목표 <b>{goal["target"]:,}원</b> — 남은 금액 {goal["remaining"]:,}원 · 진행률 {goal["progress"]:g}%'
        f'<div class="bar"><div style="width:{goal["progress"]}%"></div></div></div>')
    return (f'<div class="goal done"><b>🎉 첫 {first:,}원 달성</b> — 누적 {goal["current"]:,}원'
            f'{" · 설정한 모든 목표 달성" if goal["all_achieved"] else ""}{nxt}</div>')


def _task_card(t: dict, config: dict) -> str:
    icon, desc = money.GRADES[t["grade"]]
    pv = t.get("point_value", 1)
    unit = t.get("reward_unit") or ("P" if pv != 1 else "원")
    reward = f"{t['reward']:,}{unit}" + (f" (≈{t['reward'] * pv:,}원)" if unit == "P" and pv else "")
    deadline = ""
    if t.get("deadline"):
        if t["expired"]:
            deadline = f'<div class="down">⏰ 마감 지남 ({escape(_local(t["deadline"], config))})</div>'
        else:
            left = t["minutes_left"]
            deadline = f'<div>⏰ 마감 {escape(_local(t["deadline"], config))} (남은 {_minutes(left) if left < 2880 else f"{left // 1440}일"})</div>'
    if t.get("learned_hourly") is not None:  # 예상 시급만 보지 않게: 이 플랫폼 내 실제 기록(표본 충분할 때만)
        learned = (f'<div class="hint">내 기록 기준 보정 약 <b>{t["learned_hourly"]:,}원/시간</b> '
                   f'({escape(t["platform"])} 실제 {_rate(t["platform_actual_hourly"])}, 예상 대비 {t["platform_gap_pct"]:+g}%, {t["learned_basis"]}건)</div>')
    else:
        learned = f'<div class="hint">내 기록 보정: 데이터 부족 ({t.get("learned_basis", 0)}/{t.get("learned_needed", 3)}건)</div>'
    memo = f'<div class="hint">📝 {escape(t["memo"])}</div>' if t.get("memo") else ""
    tid = quote(t["id"])
    accept = (f'<form method="post" action="/money/task/{tid}/accept"><button class="btn primary" type="submit">할래요</button></form>'
              if t["status"] == "new" else "")
    return f"""<div class="task {t['grade']}{' expired' if t['expired'] else ''}" id="{escape(t['id'])}">
<div class="p">{icon} {escape(t['platform'])} <span class="rec {t['grade']}">{escape(t['recommended'])}</span></div>
<div class="t">{escape(t['title'])}</div>
<div class="n">예상시간 {_minutes(t['minutes']) if t.get('minutes') else '표시 없음'}<br>예상보상 {escape(reward)}{'' if t.get('point_value') is not None else ' <span class="hint">(원 환산 미확인)</span>'}<br>예상 시급 {f'<span class="rate">{t["estimated_hourly"]:,}원</span> <span class="hint">{escape(desc)}</span>' if t.get('estimated_hourly') is not None else '<span class="hint">계산 안 함(시간 또는 원 환산 모름)</span>'}{deadline}</div>
{learned}{memo}
<div class="actions" style="margin-top:10px">{accept}{_ext_link(t.get('url', ''), '바로가기 ↗', 'btn' if accept else 'btn primary') or '<span class="hint">링크 없음</span>'}
<a class="btn" href="/money/task/{tid}/complete">완료 기록</a>
<form method="post" action="/money/task/{tid}/skip"><button class="btn ghost" type="submit">안 함</button></form></div></div>"""


def _platform_state(r: dict, config: dict) -> str:
    if not r.get("active"):
        return "— 오늘 루틴 제외"
    if not r["checked_today"]:
        return '○ 오늘 미확인'
    return f'● 오늘 확인함 · {"작업 있음" if r["today_outcome"] == "found" else "작업 없음"}'


def _pct(value) -> str:
    return "-" if value is None else f"{value:g}%"


def _gap_cell(p: dict) -> str:
    """예상 대비 실제 시급 차이. 표본이 모자라면 숫자 옆에 '데이터 부족'을 붙인다(결론으로 쓰지 말라는 표시)."""
    if p["gap_pct"] is None:
        return "-"
    text = f"{p['gap_pct']:+g}%"
    if not p["hourly_sufficient"]:
        text += f' <span class="hint">({p["hourly_samples"]}/{p["hourly_needed"]}건 · 데이터 부족)</span>'
    return text


def _perf_line(pf: dict | None) -> str:
    """루틴 카드 한 줄: 표본이 모자라면 비율 대신 '데이터 수집 중'."""
    if not pf or not pf["checks"]:
        return "확인 기록 없음 · 데이터 수집 중"
    base = f"확인 {pf['checks']}회 · 발견률 {_pct(pf['discovery_rate'])} · 실제 시급 {_rate(pf['actual_hourly'])}"
    return base if pf["priority_ready"] else base + f" · 데이터 수집 중({pf['checks']}/{pf['checks_needed']})"


def _routine_card(r: dict, config: dict, pf: dict | None = None, rank: int | None = None) -> str:
    name = escape(r["name"])
    buttons = f"""{_ext_link(r['url'], '다시 확인 ↗' if r['checked_today'] else '확인하기 ↗', 'btn' if r['checked_today'] else 'btn primary')}
<form method="post" action="/money/check"><input type="hidden" name="platform" value="{name}"><input type="hidden" name="outcome" value="none"><button class="btn" type="submit">작업 없었음</button></form>
<form method="post" action="/money/check"><input type="hidden" name="platform" value="{name}"><input type="hidden" name="outcome" value="found"><button class="btn" type="submit">작업 있음 → 등록</button></form>"""
    badge = f"{'①②③④⑤⑥⑦⑧⑨'[rank]} " if rank is not None and rank < 9 else ""
    return f"""<div class="plat{' checked' if r['checked_today'] else ''}"><div class="name">{badge}{name} <span class="hint">{escape(r['kind_label'])}</span></div>
<div class="state">{_platform_state(r, config)}</div>
<div class="actions">{buttons}</div>
<div class="hint" style="margin-top:6px">누적 {_won(r['earned'])} · 최근 확인 {escape(_local(r['last_checked_at'], config, '%m-%d %H:%M'))}<br>{escape(_perf_line(pf))}</div></div>"""


def _quick_done_form(platforms: list[str]) -> str:
    return f"""<form method="post" action="/money/quick-done" class="card" id="quick-done" style="display:block;max-width:none">
<div class="row"><div><label class="f">플랫폼</label><select name="platform">{_options([(p, p) for p in platforms], platforms[0])}</select></div>
<div><label class="f">받은 수익 (원 또는 P)</label><input type="text" name="actual_reward" inputmode="numeric" required placeholder="1200"></div>
<div><label class="f">걸린 시간 (분)</label><input type="text" name="actual_minutes" inputmode="numeric" required placeholder="20"></div>
<div style="flex:2 1 200px"><label class="f">작업명 (선택)</label><input type="text" name="title" maxlength="120" placeholder="쇼핑 조사"></div></div>
<div class="actions" style="margin-top:10px"><button class="btn primary big" type="submit">기록</button></div>
<div class="hint">등록 없이 이미 끝낸 작업을 바로 기록합니다. 예상값을 모르므로 '예상 대비' 분석에서는 빠지고, 수익·시간·완료 통계에는 들어갑니다.</div></form>"""


EVENT_TEXT = {"check_none": "확인 → 작업 없음", "check_found": "확인 → 작업 있음", "registered": "기회 등록", "accepted": "할래요",
              "completed": "완료", "income": "수익"}


def _event_html(ev: dict) -> str:
    detail = ""
    if ev["type"] == "registered":
        detail = f" · {escape(ev['title'])} ({ev['reward']:,} / {_minutes(ev['minutes']) if ev.get('minutes') else '시간 표시 없음'})"
    elif ev["type"] == "accepted":
        detail = f" · {escape(ev['title'])}"
    elif ev["type"] in ("completed", "income"):
        est = (f" <span class='hint'>(예상 {ev['estimated_reward']:,} / {_minutes(ev['estimated_minutes'])})</span>"
               if ev.get("estimated_reward") is not None else "")
        detail = (f" · {escape(ev['title'])} → 실제 <b>{ev['earned']:,}원</b> / {_minutes(ev['minutes'])}{est}"
                  f" · 누적 <b>{ev['cumulative']:,}원</b>")
    return f'<li><span class="hint">{ev["time"]}</span> {escape(ev["platform"])} {EVENT_TEXT[ev["type"]]}{detail}</li>'


def _timeline_html(days: list[dict]) -> str:
    if not days:
        return '<div class="card">아직 기록이 없습니다. 플랫폼 확인·등록·완료가 쌓이면 여기에 날짜별로 남습니다.</div>'
    return "".join(f'<div class="card" style="max-width:none"><b>{d["date"]}</b> <span class="hint">수익 {d["earned"]:,}원</span>'
                   f'<ul style="margin:6px 0 0;padding-left:18px">{"".join(_event_html(ev) for ev in d["events"])}</ul></div>' for d in days)


def _summary_html(summ: dict, title: str) -> str:
    plats = " · ".join(f"{escape(p['platform'])} {p['earned']:,}원" for p in summ["by_platform"]) or "-"
    return f"""<div class="today"><b>{title}</b>
<div class="nums"><div>확인 <b>{summ['checks']}회</b></div><div>발견 <b>{summ['found']}회</b></div><div>등록한 기회 <b>{summ['opportunities']}건</b></div><div>완료 <b>{summ['completed']}건</b></div>
<div>수익 <b>{summ['earned']:,}원</b></div><div>투자 <b>{escape(_minutes(summ['minutes']))}</b></div><div>실제 시급 <b>{escape(_rate(summ['hourly']))}</b></div></div>
<div class="hint" style="margin-top:4px">확인한 곳: {escape(', '.join(summ['checked_platforms']) or '-')} · 안 한 곳: {escape(', '.join(summ['unchecked_platforms']) or '-')}<br>플랫폼별 수익: {plats}</div></div>"""


def _recent_html(recent: dict, goal: dict) -> str:
    if not recent["sufficient"]:
        return (f'<div class="hint" style="margin-top:6px">최근 {recent["days"]}일 평균: 데이터 부족 '
                f'(기록 {recent["entries"]}/{recent["needed"]}건 — 쌓이면 일평균 수익·작업시간을 보여줍니다)</div>')
    eta = f" · 이 속도면 다음 목표까지 약 <b>{recent['eta_days']}일</b>" if recent["eta_days"] else ""
    return (f'<div style="margin-top:6px">최근 {recent["days"]}일: 일평균 수익 <b>{recent["avg_daily_earned"]:,}원</b> · '
            f'일평균 작업 <b>{recent["avg_daily_minutes"]:g}분</b> · 실제 시급 <b>{_rate(recent["hourly"])}</b>{eta}</div>')


def _quick_form(text: str = "", platform: str = "") -> str:
    value = text or (f"{platform} " if platform else "")
    return f"""<form method="post" action="/money/quick" class="card" id="quick" style="display:block;max-width:none">
<div class="row"><div style="flex:3 1 260px"><input type="text" name="text" value="{escape(value)}" placeholder="예: 패널나우 20분 850P 일반인 의견 조사" required{' autofocus' if platform else ''}></div>
<div style="flex:0 0 auto"><button class="btn primary big" type="submit">확인</button></div></div>
<div class="hint">플랫폼 · 시간 · 보상을 적으면 예상 시급을 계산해 <b>저장 전에 확인 화면</b>을 보여줍니다. 캡처에서 읽은 여러 줄 글은 <a href="/money/capture">📷 캡처 텍스트로 등록</a>.</div></form>"""


# ---- /money --------------------------------------------------------------------------------

def _priority_html(prio: dict) -> str:
    if prio["ready"]:
        order = " ".join(f"{'①②③④⑤⑥⑦⑧⑨'[i]} {escape(n)}" for i, n in enumerate(prio["order"]))
        basis = " · ".join(f"{escape(n)} {'-' if v is None else f'{v:,}원'}" for n, v in prio["basis"].items())
        return (f'<div class="today"><b>오늘 추천 확인 순서</b> <span class="hint">내 기록 기준(확인 1회당 작업 수익) — 플랫폼 평가가 아니라 지금까지 내 기록</span>'
                f'<div style="margin-top:4px">{order}</div><div class="hint">확인 1회당 수익: {basis}</div></div>')
    prog = " · ".join(f"{escape(n)} {c}/{need}" for n, (c, need) in prio["progress"].items())
    return (f'<div class="hint" style="margin-bottom:6px">추천 확인 순서: <b>데이터 수집 중</b> — 모든 플랫폼이 확인 {prio["needed"]}회 이상 쌓이면 '
            f'내 기록 기준 순서를 계산합니다(지금: {prog}). 그 전에는 기본 순서.</div>')


def render_home(store: money.MoneyStore, query: dict, notice=None, error=None, quick_text="") -> str:
    config = store.config
    tasks, log, checks = store.tasks(), store.log(), store.checks()
    stats = money.period_stats(log, config)
    goal = money.goal_status(stats["total"]["earned"], config)
    today = money.today_summary(tasks, log, checks, config)
    perf = {p["platform"]: p for p in money.performance(tasks, log, checks, config)}
    prio = money.learned_priority(list(perf.values()), config)
    by_name = {r["name"]: r for r in money.routine(tasks, log, checks, config) if r.get("active") and r.get("url")}
    routine = [by_name[n] for n in prio["order"] if n in by_name]  # 표본이 충분할 때만 내 기록 순서, 아니면 설정 순서
    recent = money.recent_stats(log, config)
    day = money.activity_summary(tasks, log, checks, config, "today")
    today_events = [d for d in money.timeline(tasks, log, checks, config, limit_days=1)
                    if d["date"] == datetime.now(money.local_tz(config)).strftime("%Y-%m-%d")]
    get = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    sort, grade_filter, platform_filter = get("sort") or "hourly", get("grade"), get("platform")

    def pick(statuses):
        rows = money.open_tasks(tasks, config, sort=sort, statuses=statuses, log=log)
        return rows, [t for t in rows if (not grade_filter or t["grade"] == grade_filter) and (not platform_filter or t["platform"] == platform_filter)]

    opp_all, opps = pick(("new",))
    task_all, open_rows = pick(("open",))
    opp_cards = "".join(_task_card(t, config) for t in opps) or (
        '<div class="card">아직 발견한 기회가 없습니다. 플랫폼을 확인하고 할 만한 작업이 있으면 위에 적어 보세요.</div>' if not opp_all
        else '<div class="card">조건에 맞는 기회가 없습니다.</div>')
    task_cards = "".join(_task_card(t, config) for t in open_rows) or (
        '<div class="card">하기로 한 작업이 없습니다. 기회 카드에서 [할래요]를 누르면 여기로 옵니다.</div>' if not task_all
        else '<div class="card">조건에 맞는 작업이 없습니다.</div>')
    th = config["thresholds"]
    legend = (f'<div class="legend hint"><span>🟢 {th["green"]:,}원/시간 이상 · 지금 확인</span><span>🟡 {th["yellow"]:,}~{th["green"] - 1:,} · 시간 여유 있을 때</span>'
              f'<span>🟠 {th["orange"]:,}~{th["yellow"] - 1:,} · 다른 작업 없을 때</span><span>🔴 {th["orange"]:,} 미만 · 보류</span>'
              '<span>(초기 실험용 기준 · <a href="/money/settings">바꾸기</a>)</span></div>')
    platforms = [p["name"] for p in config["platforms"]]
    filters = f"""<form method="get" action="/money" class="row" style="max-width:820px;margin:6px 0 10px">
<div><select name="sort">{_options([("hourly", "예상 시급 높은 순"), ("deadline", "마감 임박 순"), ("new", "최근 등록 순"), ("platform", "플랫폼 순"), ("grade", "등급 순")], sort)}</select></div>
<div><select name="grade">{_options([("", "전체 등급")] + [(g, f"{i} {g}") for g, (i, d) in money.GRADES.items()], grade_filter)}</select></div>
<div><select name="platform">{_options([("", "모든 플랫폼")] + [(p, p) for p in platforms], platform_filter)}</select></div>
<div style="flex:0 0 auto"><button class="btn" type="submit">보기</button></div></form>"""
    checklist = "".join(f'<span>{"■" if r["checked_today"] else "□"} {escape(r["name"])}</span>' for r in routine)
    recent_rows = "".join(
        f'<tr><td>{escape(_local(e["completed_at"], config, "%m-%d %H:%M"))}</td><td>{escape(e["platform"])}</td><td>{escape(e["title"])}</td>'
        f'<td class="num">{money.won(e):,}원</td><td class="num">{_rate(e["actual_hourly"])}</td></tr>'
        for e in sorted(log, key=lambda e: e["completed_at"], reverse=True)[:5]) or '<tr><td colspan="5">아직 수익 기록이 없습니다.</td></tr>'
    t = stats["today"]
    return f"""<div class="money">{NAV}
<h1>💰 TAK AUTO MONEY</h1><div class="sub">온라인 수익 노가다 관제판 — 기회(OPPORTUNITY) · 수익성 · 우선순위 · 직접 실행 · 기록 · 학습</div>
{_banner(notice, error)}
{_today_money_html(store)}
<div class="today"><b>① 오늘의 수익 · 📊 오늘의 MONEY 활동</b><div class="nums"><div>오늘 수익 <b>{t['earned']:,}원</b></div><div>투자 <b>{escape(_minutes(t['minutes']))}</b></div>
<div>시급 <b>{escape(_rate(t['hourly']))}</b></div><div>완료 <b>{today['completed_today']}건</b></div><div>발견 기회 <b>{day['opportunities']}건</b></div></div>
<div class="hint" style="margin-top:4px">확인한 곳: {escape(', '.join(today['checked_names']) or '-')} · 안 한 곳: {escape(', '.join(today['unchecked']) or '-')}</div>
{('<details><summary class="hint">오늘 한 일 ' + str(len(today_events[0]['events'])) + '개</summary><ul style="margin:4px 0 0;padding-left:18px">' + ''.join(_event_html(ev) for ev in today_events[0]['events']) + '</ul></details>') if today_events else ''}</div>
{_goal_html(goal).removesuffix('</div>')}{_recent_html(recent, goal)}</div>
<div class="today"><b>🔥 오늘의 MONEY ROUTINE</b> <span class="hint">오늘 할 일</span>
<div class="checklist" style="margin-top:6px">오늘 확인할 곳 ({today['checked']}/{today['platforms']}): {checklist}</div>
<div class="nums"><div>오늘 발견한 기회 <b>{today['found_today']}건</b></div><div>오늘 완료한 작업 <b>{today['completed_today']}건</b></div><div>오늘 수익 <b>{today['earned_today']:,}원</b></div></div>
<details style="margin-top:6px"><summary class="hint">하루 사용법</summary><ol class="hint">{"".join(f"<li>{escape(s)}</li>" for s in HOW_TO)}</ol></details></div>

{_scout_home_html(store)}
<h2 id="routine">④ 지금 확인할 플랫폼 <span class="hint"><a href="/money/platforms">💰 수익 플랫폼 전체 →</a></span></h2>
{_priority_html(prio)}
<div class="routine">{"".join(_routine_card(r, config, perf.get(r["name"]), i if prio["ready"] else None) for i, r in enumerate(routine))}</div>
<div class="hint" style="margin-top:6px">"확인함"은 내가 공식 사이트를 직접 봤다는 기록일 뿐, 작업이 있다는 뜻이 아닙니다. 확인했지만 작업이 없던 날도 기록됩니다.</div>

<h2>⚡ 빠른 등록</h2>
{_quick_form(quick_text, get('found'))}

<details class="card" style="max-width:none"{' open' if get('done') else ''}><summary><b>💵 빠른 수익 기록</b> (이미 끝낸 작업: 오베이 · 1200 · 20분)</summary>
{_quick_done_form(platforms)}</details>

<h2>💡 수익 기회 <span class="hint">({len(opp_all)}건 · 발견만 한 것, [할래요]로 작업이 됩니다)</span></h2>
{legend}{filters}
<div class="tasks">{opp_cards}</div>

<h2>🔥 지금 할 만한 온라인 작업 <span class="hint">({len(task_all)}건 · 하기로 한 작업)</span></h2>
<div class="tasks">{task_cards}</div>

<h2>📒 최근 수익 기록 <span class="hint"><a href="/money/log">전체·분석 →</a></span></h2>
<div class="scroll"><table class="tbl"><tr><th>완료</th><th>플랫폼</th><th>작업</th><th class="num">수익</th><th class="num">실제 시급</th></tr>{recent_rows}</table></div>

<details class="card" style="margin-top:12px;max-width:none"><summary><b>📈 기간별 통계</b> (오늘·이번 주·이번 달·누적)</summary>{_kpis(stats)}</details>

<details class="card" style="max-width:none"><summary><b>✍️ 자세히 등록</b> (링크·메모·마감시간)</summary>
{_detail_form(platforms)}</details>

<details class="card" style="max-width:none"><summary><b>💵 작업 없이 들어온 수익 기록</b> (애드포스트 정산 등)</summary>
<form method="post" action="/money/income" style="display:block">
<div class="row"><div><label class="f">플랫폼</label><select name="platform">{_options([(p, p) for p in platforms], "네이버 애드포스트")}</select></div>
<div><label class="f">금액 (원)</label><input type="text" name="amount" inputmode="numeric" required></div>
<div><label class="f">들인 시간 (분, 선택)</label><input type="text" name="minutes" inputmode="numeric" placeholder="0"></div></div>
<label class="f">내용 (선택)</label><input type="text" name="title" maxlength="120" placeholder="9월 정산">
<div style="margin-top:10px"><button class="btn big" type="submit">기록</button></div>
<div class="hint">시간을 비우면 수익에는 더하고 시간당 수익 계산에서는 뺍니다.</div></form></details>

<div class="sub" style="margin-top:14px">TAK AUTO는 계산·기록·공식 링크만 합니다. 로그인·설문 응답·본인인증은 각 사이트에서 직접 하세요. 비밀번호/인증번호/개인정보는 여기에 저장하지 않습니다.</div>
</div>"""


def _detail_form(platforms: list[str], draft: dict | None = None, *, confirm: bool = False) -> str:
    d = draft or {}
    miss = set(d.get("missing") or [])
    cls = lambda k: ' class="missing"' if k in miss else ""  # noqa: E731
    val = lambda k: escape("" if d.get(k) is None else f"{d[k]:g}" if isinstance(d.get(k), float) else str(d[k]))  # noqa: E731
    buttons = ('<button class="btn primary big" type="submit" name="status" value="new">💡 기회로 저장</button> '
               '<button class="btn big" type="submit" name="status" value="open">🔥 바로 할 작업으로 등록</button> '
               '<a class="btn" href="/money">취소</a>') if confirm else '<button class="btn primary big" type="submit" name="status" value="open">저장</button>'
    choices = ([("", "플랫폼 선택")] if "platform" in miss else []) + [(p, p) for p in platforms]
    platform_opts = _options(choices, d.get("platform") or ("" if "platform" in miss else platforms[0]))
    return f"""<form method="post" action="/money/tasks" style="display:block">
<input type="hidden" name="source" value="{escape(d.get('source', 'manual'))}">
<div class="row"><div><label class="f">플랫폼</label><select name="platform"{cls('platform')}>{platform_opts}</select></div>
<div style="flex:2 1 240px"><label class="f">작업명</label><input type="text" name="title" required maxlength="120" value="{val('title')}" placeholder="일반인 의견 조사"></div></div>
<div class="row"><div><label class="f">예상 보상 (원 또는 P)</label><input type="text" name="reward" inputmode="numeric" required value="{val('reward')}" placeholder="850"{cls('reward')}></div>
<div><label class="f">예상 소요시간 (분)</label><input type="text" name="minutes" inputmode="numeric" required value="{val('minutes')}" placeholder="20"{cls('minutes')}></div>
<div><label class="f">마감시간 (선택)</label><input type="datetime-local" name="deadline"></div></div>
<label class="f">공식 링크 (비우면 플랫폼 공식 주소)</label><input type="url" name="url" placeholder="https://">
<label class="f">메모 (선택 · 비밀번호/개인정보는 적지 마세요)</label><input type="text" name="memo" maxlength="500">
<div class="actions" style="margin-top:10px">{buttons}</div></form>"""


def render_confirm(store: money.MoneyStore, draft: dict, error=None) -> str:
    """빠른 등록/캡처 텍스트 -> 저장 전 확인 화면(고칠 수 있음)."""
    platforms = [p["name"] for p in store.config["platforms"]]
    if draft.get("estimated_hourly") is not None:
        icon, _ = money.GRADES[draft["grade"]]
        summary = (f'<div class="task {draft["grade"]}" style="max-width:520px"><div class="p">{icon} {escape(draft["platform"] or "-")} '
                   f'<span class="rec {draft["grade"]}">{escape(draft["recommended"])}</span></div><div class="t">{escape(draft["title"])}</div>'
                   f'<div class="n">시간 {_minutes(draft["minutes"])} · 보상 {draft["reward"]:,} → 예상 시급 <span class="rate">{draft["estimated_hourly"]:,}원</span></div></div>')
    else:
        summary = ""
    missing = ""
    if draft.get("missing"):
        names = {"platform": "플랫폼", "minutes": "시간", "reward": "보상"}
        missing = f'<div class="error">읽지 못한 값: {", ".join(names[k] for k in draft["missing"])} — 빨간 칸을 채워 주세요.</div>'
    source = f'<details class="hint"><summary>입력한 원문</summary><pre style="white-space:pre-wrap">{escape(draft.get("source_text", ""))}</pre></details>'
    return f"""<div class="money">{NAV}<h1>등록 전 확인</h1>{_banner(None, error)}{missing}
<div class="sub">읽은 값이 맞는지 확인하고 고친 뒤 등록하세요. 아직 저장되지 않았습니다.</div>
{summary}<div class="card" style="max-width:720px">{_detail_form(platforms, draft, confirm=True)}</div>{source}</div>"""


def render_capture() -> str:
    return f"""<div class="money">{NAV}<h1>📷 캡처 텍스트로 등록</h1>
<div class="sub">설문 알림/목록 화면을 캡처해 글자만 복사(휴대폰의 '텍스트 복사' 등)해서 붙여 넣으세요. TAK AUTO는 이미지를 읽거나 외부 OCR을 부르지 않습니다.</div>
<form method="post" action="/money/quick" class="card" style="display:block;max-width:720px">
<textarea name="text" rows="7" placeholder="패널나우&#10;일반인 의견 조사&#10;약 20분&#10;850P" required></textarea>
<div style="margin-top:10px"><button class="btn primary big" type="submit">읽기 → 확인 화면</button></div></form></div>"""


# ---- 완료 기록 ------------------------------------------------------------------------------

def render_complete(store: money.MoneyStore, task: dict, error=None, form=None) -> str:
    form = form or {}
    val = lambda k, d="": escape((form.get(k) or [d])[0])  # noqa: E731
    pv = task.get("point_value", 1)
    est = money.hourly(task["reward"] * pv, task["minutes"]) if pv is not None and task.get("minutes") else None
    done = task["status"] not in ("open", "new")
    body = (f'<div class="error">{escape(money.ERROR_TEXT["ALREADY_COMPLETED" if task["status"] == "done" else "TASK_CLOSED"])}</div>' if done else f"""
<form method="post" action="/money/task/{quote(task['id'])}/complete" class="card" style="display:block">
<div class="row"><div><label class="f">실제 받은 금액 (원)</label><input type="text" name="actual_reward" inputmode="numeric" required autofocus value="{val('actual_reward', str(task['reward']) if pv is not None else '')}"></div>
<div><label class="f">실제 소요시간 (분)</label><input type="text" name="actual_minutes" inputmode="numeric" required value="{val('actual_minutes')}" placeholder="{f"{task['minutes']:g}" if task.get('minutes') else '분'}"></div></div>
<div style="margin-top:10px"><button class="btn primary big" type="submit">저장</button></div>
<details style="margin-top:6px"><summary class="hint">메모 (선택)</summary><input type="text" name="memo" maxlength="500" value="{val('memo')}"></details>
<div class="hint">예상값은 그대로 남고, 실제값이 따로 기록됩니다. 같은 작업은 한 번만 기록됩니다.</div></form>""")
    return f"""<div class="money">{NAV}<h1>완료 기록</h1>{_banner(None, None if done else error)}
<div class="card"><b>{escape(task['platform'])}</b> · {escape(task['title'])}<br>
예상: {task['reward']:,}{'P' if pv != 1 else '원'} / {_minutes(task['minutes'])} → 예상 시급 <b>{_rate(est)}</b></div>{body}</div>"""


# ---- /money/log -----------------------------------------------------------------------------

def render_log(store: money.MoneyStore, notice=None) -> str:
    config = store.config
    log = store.log()
    stats = money.period_stats(log, config)
    plat = money.platform_stats(log, config)
    tasks, checks = store.tasks(), store.checks()
    week = money.activity_summary(tasks, log, checks, config, "week")
    perf = money.performance(tasks, log, checks, config)
    days = money.timeline(tasks, log, checks, config)
    perf_rows = "".join(
        f'<tr><td>{escape(p["platform"])}</td><td class="num">{p["checks"]}</td><td class="num">{p["found"]}</td><td class="num">{p["no_task"]}</td>'
        f'<td class="num">{p["registered"]}</td><td class="num">{p["accepted"]}</td><td class="num">{p["completed"]}</td>'
        f'<td class="num">{_won(p["earned"])}</td><td class="num">{_minutes(p["minutes"])}</td><td class="num">{_rate(p["actual_hourly"])}</td>'
        f'<td class="num">{_pct(p["discovery_rate"])}</td><td class="num">{_pct(p["completion_rate"])}</td><td class="num">{_pct(p["revenue_rate"])}</td>'
        f'<td class="num">{_won(p["earned_per_check"])}</td>'
        f'<td class="num">{_rate(p["avg_estimated_hourly"])}</td><td class="num">{_rate(p["avg_actual_hourly"])}</td>'
        f'<td class="num">{_gap_cell(p)}</td></tr>'
        for p in perf)
    prow = "".join(
        f'<tr><td>{escape(p["platform"])}</td><td class="num">{p["count"]}</td><td class="num">{_won(p["earned"])}</td><td class="num">{_minutes(p["minutes"])}</td>'
        f'<td class="num">{(money.GRADES[p["grade"]][0] + " ") if p["grade"] else ""}{_rate(p["actual_hourly"])}</td><td class="num">{_rate(p["estimated_hourly"])}</td>'
        f'<td class="num {("up" if (p["hourly_gap_pct"] or 0) >= 0 else "down")}">{"-" if p["hourly_gap_pct"] is None else f"{p["hourly_gap_pct"]:+g}%"}</td></tr>'
        for p in plat)
    entries = []
    for e in sorted(log, key=lambda e: e["completed_at"], reverse=True):
        if e.get("estimated_reward") is not None:
            est = f'{e["estimated_reward"]:,}원 / {_minutes(e["estimated_minutes"])} ({_rate(e["estimated_hourly"])})'
        else:  # 빠른 수익 기록(예상 모름) / 작업 없는 수익
            est = "예상 없이 바로 기록(빠른 수익 기록)" if e.get("kind") == "task" else "작업 없이 들어온 수익"
        gap = ""
        if e.get("kind") == "task" and e.get("estimated_hourly") and e.get("actual_hourly") is not None:
            pct = (e["actual_hourly"] - e["estimated_hourly"]) * 100 / e["estimated_hourly"]
            gap = f' <span class="{"up" if pct >= 0 else "down"}">(예상 대비 {pct:+.1f}%)</span>'
        entries.append(f"""<div class="card"><b>{escape(e['platform'])}</b> · {escape(e['title'])}
<div class="n">예상: {escape(est)}<br>실제: <b>{money.won(e):,}원 / {_minutes(e['actual_minutes'])}</b><br>
실제 시급: <b>{_rate(e['actual_hourly'])}</b>{gap}<br><span class="hint">완료: {escape(_local(e['completed_at'], config))}</span>
{f'<div class="hint">📝 {escape(e["memo"])}</div>' if e.get('memo') else ''}</div></div>""")
    return f"""<div class="money">{NAV}<h1>📒 수익 기록 · 분석</h1>{_banner(notice, None)}
{_summary_html(week, "📅 이번 주 MONEY summary <span class='hint'>(월요일 KST 시작)</span>")}
{_kpis(stats)}
<h2>📊 플랫폼별 — 확인 대비 성과</h2>
<div class="scroll"><table class="tbl"><tr><th>플랫폼</th><th class="num">확인</th><th class="num">발견</th><th class="num">작업 없음</th><th class="num">등록</th>
<th class="num">수락</th><th class="num">완료</th><th class="num">수익</th><th class="num">투자</th><th class="num">실제 시급</th><th class="num">발견률</th>
<th class="num">완료율</th><th class="num">수익 발생률</th><th class="num">확인 1회당</th><th class="num">평균 예상 시급</th><th class="num">평균 실제 시급</th><th class="num">예상 대비</th></tr>{perf_rows}</table></div>
<div class="hint">발견률 = 발견/확인 · 완료율 = 완료/등록 · 수익 발생률 = 보상 있는 완료/확인 · 확인 1회당 = 작업 수익/확인. 확인 기록 없이 기회를 등록한 날은 "확인·발견 1회"로 셉니다.
평균 예상/실제 시급은 예상값을 알던 완료 기록만의 시간 가중 평균(Σ보상×60/Σ분). 표본이 {config["learning"]["min_samples_for_hourly"]}건 미만이면 "데이터 부족".</div>
<h2>💴 수익 · 투자시간 (전체 기록)</h2>
<div class="scroll"><table class="tbl"><tr><th>플랫폼</th><th class="num">건수</th><th class="num">누적 수익</th><th class="num">투자</th><th class="num">실제 시급</th><th class="num">예상 시급</th><th class="num">예상 대비</th></tr>{prow}</table></div>
<div class="hint">예상 대비 = (실제 시급 − 예상 시급) ÷ 예상 시급. 기록이 쌓일수록 어느 플랫폼이 실제로 나은지 보입니다.</div>
<h2>🧭 첫 10,000원까지의 운영 로그</h2><div class="hint" style="margin-bottom:6px">확인 · 등록 · 할래요 · 완료를 날짜별로(최신 날짜 먼저). 누적은 그 시점까지의 총 수익.</div>
{_timeline_html(days)}
<h2>최근 완료</h2>{"".join(entries) or '<div class="card">아직 기록이 없습니다.</div>'}</div>"""


# ---- /money/platforms -----------------------------------------------------------------------

def render_platforms(store: money.MoneyStore, notice=None, error=None) -> str:
    config = store.config
    tasks, log, checks = store.tasks(), store.log(), store.checks()
    rows = money.routine(tasks, log, checks, config)
    perf = {p["platform"]: p for p in money.performance(tasks, log, checks, config)}
    cards = []
    for r in rows:
        pf = perf.get(r["name"], {})
        noti = {True: "알림 있음", False: "알림 없음", None: "알림 여부 미확인"}[r.get("notification_available")]
        cards.append(f"""<div class="plat{' checked' if r['checked_today'] else ''}"><div class="name">{escape(r['name'])} <span class="hint">{escape(r['kind_label'])}</span></div>
<div class="hint">{escape(r.get('description') or '')}{' · 오늘 루틴 제외' if not r.get('active') else ''} · {noti}</div>
<div class="state">{_platform_state(r, config)}</div>
<div class="actions">{_ext_link(r.get('url', ''), '공식 사이트 ↗') or '<span class="hint">공식 링크 없음</span>'}</div>
<table class="kv hint" style="margin-top:6px"><tr><td>누적 수익</td><td>{_won(r['earned'])}</td></tr><tr><td>실제 시급</td><td>{_rate(r['actual_hourly'])}</td></tr>
<tr><td>예상 대비</td><td>{_gap_cell(pf) if pf else '-'}</td></tr>
<tr><td>최근 확인</td><td>{escape(_local(r['last_checked_at'], config))}</td></tr>
<tr><td>확인 / 작업 없음</td><td>{r['check_count']}회 / {r['no_task_count']}회</td></tr>
<tr><td>발견 / 완료</td><td>{r['found_count']}건 / {r['completed_count']}건 (열린 것 {r['open_count']})</td></tr>
<tr><td>발견률 / 완료율</td><td>{_pct(pf.get('discovery_rate'))} / {_pct(pf.get('completion_rate'))}</td></tr>
<tr><td>수익 발생률</td><td>{_pct(pf.get('revenue_rate'))}</td></tr>
<tr><td>확인 1회당 수익</td><td>{_won(pf.get('earned_per_check'))}</td></tr>
<tr><td>평균 예상 → 실제</td><td>{_rate(pf.get('avg_estimated_hourly'))} → {_rate(pf.get('avg_actual_hourly'))}{'' if pf.get('hourly_sufficient') else f" (데이터 부족 {pf.get('hourly_samples', 0)}/{pf.get('hourly_needed', 3)}건)"}</td></tr>
<tr><td>순서 추천</td><td>{'사용 가능' if pf.get('priority_ready') else f"데이터 수집 중 ({pf.get('checks', 0)}/{pf.get('checks_needed', 5)})"}</td></tr></table>
<form method="post" action="/money/platforms/note" style="display:block;margin-top:6px"><input type="hidden" name="platform" value="{escape(r['name'])}">
<input type="text" name="note" maxlength="500" value="{escape(r['note'])}" placeholder="메모(예: 알림 오면 30분 안에 마감)"><button class="btn" type="submit" style="margin-top:6px">메모 저장</button></form></div>""")
    return f"""<div class="money">{NAV}<h1>💰 수익 플랫폼</h1>{_banner(notice, error)}
<div class="sub">공식 사이트 링크와 내 기록만 보여줍니다. 외부 사이트의 작업 목록을 가져오지 않습니다(로그인·약관·개인정보 문제). 플랫폼 추가는 money_config.json의 platforms 목록으로.</div>
<div class="routine">{"".join(cards)}</div></div>"""


# ---- /money/scout ---------------------------------------------------------------------------

MANUAL_PLATFORMS = ("panelnow", "heypoll", "adpost")
_RUN_LOCK = threading.Lock()


def _start_agent_run(config) -> str:
    """버튼: 요청을 남기고, 에이전트 실행이 켜져 있으면 뒤에서 실행한다(서버는 바로 응답 - 화면이 10초마다 상태를 본다)."""
    from content_engine import money_scout_agent

    staging = _staging_path(config)
    req = money_scout.request_scout(staging)
    if not getattr(config, "money_scout_agent_enabled", False):
        return "requested"
    if req.get("status") == "running" or not _RUN_LOCK.acquire(blocking=False):
        return "running"
    money_scout.set_request(staging, req["id"], "running")

    visited = {p["platform"] for p in money_scout.plan() if p["visit"]}  # 정책상 안 가는 곳(앱 전용·약관)은 실패 사유가 아님

    def work() -> None:
        try:
            run = money_scout_agent.run_scout(tasks_path=config.money_tasks_path, staging_path=staging, request_id=req["id"])
            if run["overall"] in ("FAILED", "INVALID"):
                money_scout.set_request(staging, req["id"], "failed",
                                        " / ".join(f"{k}: {v['status']} {v['detail']}" for k, v in run["platforms"].items()
                                                  if v["status"] not in money_scout.OK_STATES and k in visited))
        except Exception as error:  # noqa: BLE001 - 실행 실패는 화면에 사유로 남긴다
            money_scout.set_request(staging, req["id"], "failed", f"{type(error).__name__}: {error}")
        finally:
            _RUN_LOCK.release()

    threading.Thread(target=work, daemon=True).start()
    return "running"


def _staging_path(config):
    """staging은 항상 money_tasks.json 옆(data/money_scout_staging.json) - 테스트/샌드박스 경로가 실제 data/로 새지 않게."""
    return Path(config.money_tasks_path).with_name("money_scout_staging.json")


def _today_money_html(store: money.MoneyStore) -> str:
    """6-61 TODAY MONEY: 예상(아직 안 번 돈)과 실제(받은 돈)를 분리. 목표는 실제만.
    6-62: 처음 보는 사람이 바로 읽게 - 발견/지금 할 것, 실제 오늘/이번 달, 첫 목표, 버튼만 크게. 나머지는 작은 글씨."""
    tm = money_scout.today_money(store.tasks(), store.log(), store.config)
    g = tm["goal"]
    unknown = f' + 원 환산/시간 모름 {tm["expected_unknown"]}건' if tm["expected_unknown"] else ""
    pending = ('<div class="hint" style="margin-top:4px">실제 수익 0원 — 아직 발생하지 않음. 설문 하나를 직접 끝내고 받은 금액·걸린 시간만 적으면 여기부터 채워집니다.</div>'
               if tm["revenue_state"] == "REAL_REVENUE_PENDING" else
               f'<div class="hint" style="margin-top:4px">실제 기록 {tm["actual_count"]}건 · 실제 시급 {f"{tm['actual_hourly']:,}원" if tm["actual_hourly"] is not None else "-"}</div>')
    row = 'style="display:flex;gap:22px;flex-wrap:wrap;margin-top:6px;font-size:1.05rem"'
    return f"""<div class="goal"><b>💰 TODAY MONEY</b>
<div class="nums" {row}><div>오늘 발견 <b>{tm['found_today']}건</b></div><div>🔥 지금 할 것 <b>{tm['now']}건</b></div></div>
<div class="nums" {row}><div>오늘 실제 수익 <b>{tm['actual_today']:,}원</b></div><div>이번 달 실제 수익 <b>{tm['actual_month']:,}원</b></div></div>
<div style="margin-top:8px;font-size:1.05rem">🎯 첫 목표 <b>{g['current']:,} / {g['first_goal']:,}원</b> ({g['first_progress']:g}%)</div>{pending}
<div class="actions" style="margin-top:8px"><a class="btn primary big" href="/money/scout">🔎 지금 수익기회 찾기 · TOP 3</a></div>
<div class="hint" style="margin-top:6px">예상 수익 <b>{tm['expected_krw']:,}원</b>{unknown} (🔥·🟡 기준, 목표에 안 넣음) · 🟡 {tm['later']}건 · ⚪ {tm['hold']}건</div></div>"""


def _scout_home_html(store: money.MoneyStore) -> str:
    try:
        run = money_scout.latest_run(money_scout.load_staging(Path(store.tasks_path).with_name("money_scout_staging.json")))
        now_count = len(money_scout.buckets(store.tasks(), store.log(), store.config)["NOW"])
    except money.MoneyError:
        return ""
    last = f"마지막 확인 {escape(_local(run['collected_at'], store.config, '%m-%d %H:%M'))} · {escape(run['overall'])}" if run else "아직 스카우트 기록 없음"
    return f'<div class="today"><b>🔎 MONEY SCOUT</b> <span class="hint">{last}</span> · 🔥 지금 할 것 <b>{now_count}건</b> <a class="btn" href="/money/scout">열기</a></div>'


def _scout_card(t: dict, config: dict) -> str:
    unit = t.get("reward_unit") or "원"
    krw = f" (≈{t['reward_krw_estimate']:,}원)" if unit == "P" and t.get("reward_krw_estimate") is not None else (" (원 환산 미확인)" if unit == "P" else "")
    minutes = _minutes(t["minutes"]) if t.get("minutes") else "시간 표시 없음"
    rate = f'예상 시급 <span class="rate">{t["estimated_hourly"]:,}원</span>' if t.get("estimated_hourly") is not None else "예상 시급 -"
    learned = f' · 내 기록 보정 약 {t["learned_hourly"]:,}원' if t.get("learned_hourly") is not None else ""
    tid = escape(t["id"])
    flags = " · ".join(x for x in (t.get("category"), "선착순" if t.get("first_come") else "", *(t.get("scout_notes") or [])) if x)
    state = {"open": "할 작업", "new": "기회"}.get(t["status"], t["status"])
    choice = {"DO": "한다", "LATER": "나중에", "SKIP": "안 한다"}.get(t.get("user_choice"), "")
    buttons = "".join(f'<form method="post" action="/money/scout/choice"><input type="hidden" name="task_id" value="{tid}"><input type="hidden" name="choice" value="{c}">'
                      f'<button class="btn{" primary" if c == "DO" else " ghost" if c == "SKIP" else ""}" type="submit">{label}</button></form>'
                      for c, label in (("DO", "한다"), ("LATER", "나중에"), ("SKIP", "안 한다")) if not (c == "DO" and t["status"] == "open"))
    return f"""<div class="task {t['grade'] if t.get('estimated_hourly') is not None else ''}">
<div class="p">{escape(t['platform'])} <span class="hint">{escape(state)}{(' · 내 선택: ' + choice) if choice else ''}</span></div>
<div class="t">{escape(t['title'])}</div>
<div class="n">{escape(minutes)} / {t['reward']:,}{escape(unit)}{escape(krw)}<br>{rate}{escape(learned)}<br><span class="hint">{escape(t['reason'])}</span>
<br><span class="hint">{escape(flags)}{' · ' if flags else ''}신뢰도 {t.get('confidence', '-')} · 마지막 발견 {escape(_local(t.get('last_seen_at'), config, '%m-%d %H:%M'))}</span></div>
<div class="actions" style="margin-top:8px">{_ext_link(t.get('url', ''), '열기 ↗')}{buttons}
<a class="btn" href="/money/task/{quote(t['id'])}/complete">완료 기록</a></div></div>"""


def render_scout(store: money.MoneyStore, config_obj, notice=None, error=None) -> str:
    config = store.config
    staging = money_scout.load_staging(_staging_path(config_obj))
    run = money_scout.latest_run(staging)
    pending = next((r for r in staging["requests"] if r["status"] in ("pending", "running")), None)
    last_req = staging["requests"][-1] if staging["requests"] else None
    groups = money_scout.buckets(store.tasks(), store.log(), config)
    age = money_scout.scout_age_hours(run)
    last = (f'{escape(_local(run["collected_at"], config))} ({age:g}시간 전) · 결과 <b>{escape(run["overall"])}</b> · <span class="hint">{escape(run["scout_run_id"])}</span>'
            if run else "아직 없음")
    rows = []
    for key, pol in money_scout.PLATFORMS.items():
        r = (run or {}).get("platforms", {}).get(key)
        status = r["status"] if r else "NOT_RUN"
        counts = f'{r["found"]} / {r["promotable"]} / {r["review"]}' if r else "-"
        rows.append(f'<tr><td>{escape(pol["name"])}</td><td><b>{escape(status)}</b><div class="hint">{escape(money_scout.STATUS_TEXT[status])}</div></td>'
                    f'<td class="num">{counts}</td><td class="hint" style="white-space:normal;min-width:220px">{escape(pol["terms_note"])}</td></tr>')
    sections = []
    for key, label in money_scout.BUCKETS.items():
        cards = "".join(_scout_card(t, config) for t in groups[key]) or '<div class="card">없음</div>'
        sections.append(f'<h2>{label} <span class="hint">({len(groups[key])}건)</span></h2><div class="tasks">{cards}</div>')
    review = [i for i in (run or {}).get("items", []) if i["verdict"] == "review"]
    review_html = "".join(f'<li>{escape(i["platform_name"])} · {escape(i["title"] or "(제목 없음)")} — {escape(", ".join(i["issues"]) or "정보 부족")} '
                          f'<span class="hint">(신뢰도 {i["confidence"]})</span></li>' for i in review) or "<li>없음</li>"
    asset = ((run or {}).get("platforms", {}).get("adpost") or {}).get("asset_status")
    adpost = (" · ".join(f"{label} {_won(asset.get(k))}" for k, label in (("current_revenue", "이번 달"), ("total_revenue", "누적"), ("payable", "지급 가능/예정")))
              if asset else f'읽은 적 없음 — {escape(money_scout.PLATFORMS["adpost"]["terms_note"])}')
    plan = "".join(f'<li>{escape(p["name"])}: {"<b>자동으로 읽음</b> " + escape(p["url"]) if p["visit"] else escape(money_scout.STATUS_TEXT[p["skip_status"]])}</li>'
                   for p in money_scout.plan())
    if pending and pending["status"] == "running":
        pending_html = (f'<meta http-equiv="refresh" content="10"><div class="banner">🔎 스카우트 실행 중({escape(_local(pending["requested_at"], config))} 시작) — '
                        '브라우저 에이전트가 PanelNow를 읽고 있습니다. 보통 1~2분, 이 화면은 10초마다 새로고침됩니다.</div>')
    elif pending:
        pending_html = (f'<div class="banner">요청 대기 중({escape(_local(pending["requested_at"], config))}) — 이 서버는 에이전트 실행이 꺼져 있어 요청만 남겼습니다. '
                        'Claude Code에서 <code>py scripts/money_scout.py run</code>을 실행하면 읽어 옵니다.</div>')
    elif last_req and last_req["status"] == "failed" and last_req.get("scout_run_id") in (None, (run or {}).get("scout_run_id")):  # 뒤에 새 결과가 있으면 숨김
        pending_html = f'<div class="error">지난 실행 실패: {escape(last_req.get("message") or "")}</div>'
    else:
        pending_html = ""
    top = money_scout.top_picks(groups)
    top_html = "".join(f'<div style="display:flex;gap:8px;align-items:flex-start"><div style="font-size:1.3rem;font-weight:800;min-width:34px">[{i}]</div>'
                       f'<div style="flex:1"><div class="hint">{money_scout.BUCKETS[t["bucket"]]}</div>{_scout_card(t, config)}</div></div>' for i, t in enumerate(top, 1)) or (
        '<div class="card">지금 할 만한 기회가 없습니다. 🔎 찾기를 눌러 보거나, 로그인이 필요한 곳은 직접 로그인 후 다시 찾기.</div>')
    total = sum(len(v) for v in groups.values())
    return f"""<div class="money">{NAV}<h1>🔎 MONEY SCOUT</h1>
<div class="sub">브라우저가 공개 설문 목록 화면을 <b>읽기만</b> 해서 기회를 모읍니다. 설문 응답·제출·로그인·CAPTCHA·포인트 교환·광고 클릭은 하지 않습니다. 실제 참여는 [열기 ↗]로 직접.</div>
{_banner(notice, error)}{pending_html}
<div class="today"><b>마지막 확인</b>: {last}
<form method="post" action="/money/scout/run" style="display:block;margin-top:8px"><button class="btn primary big" type="submit"{" disabled" if pending and pending["status"] == "running" else ""}>🔎 지금 수익기회 찾기</button></form>
<div class="hint">누르면 이 PC의 Claude Code가 Chrome(Claude in Chrome)으로 허용된 곳(PanelNow)의 목록 화면을 <b>읽기만</b> 합니다 — 클릭·입력 도구 없이 실행. Chrome이 켜져 있고 PanelNow에 직접 로그인돼 있어야 실제 설문이 보입니다.</div></div>
<h2>💰 오늘의 수익기회 <span class="hint">TOP {len(top)}</span></h2>
{top_html}
<details class="card" style="max-width:none;margin-top:12px"><summary><b>더 보기</b> — 전체 {total}건(🔥 {len(groups["NOW"])} · 🟡 {len(groups["LATER"])} · ⚪ {len(groups["HOLD"])})</summary>
{"".join(sections)}</details>
<h2>🧐 확인 필요 <span class="hint">(신뢰도 0.5 이하 또는 보상 모름 — 자동 등록 안 함)</span></h2><ul class="hint">{review_html}</ul>
<h2>📈 네이버 애드포스트 수익 상태</h2><div class="card" style="max-width:none">{adpost}</div>
<h2>플랫폼별 이번 결과</h2>
<div class="scroll"><table class="tbl"><tr><th>플랫폼</th><th>상태</th><th class="num">발견 / 등록 / 검토</th><th>자동 접근 정책(2026-09-27 확인)</th></tr>{"".join(rows)}</table></div>
<details class="card" style="max-width:none;margin-top:12px"><summary><b>직접 연 화면 붙여넣기</b> (수동 · 로그인 후 내가 연 목록/수익 화면)</summary>
<form method="post" action="/money/scout/manual" style="display:block">
<div class="row"><div><label class="f">플랫폼</label><select name="platform">{_options([(k, p["name"]) for k, p in money_scout.PLATFORMS.items() if k in MANUAL_PLATFORMS], "panelnow")}</select></div></div>
<label class="f">화면 글자 (전체 선택 → 복사 → 붙여넣기)</label><textarea name="page_text" rows="6" required></textarea>
<div style="margin-top:8px"><button class="btn big" type="submit">읽기</button></div>
<div class="hint">화면 원문은 저장하지 않고(해시만) 기회 정보만 뽑습니다. 이름·전화·이메일 모양 글자는 지웁니다. 헤이폴은 서베이·퀵서베이 목록 글자를 그대로 붙여 넣으면 됩니다(자동 접근은 약관상 하지 않음).</div></form></details>
<details class="card" style="max-width:none"><summary><b>에이전트 실행 순서</b></summary><ol class="hint">{plan}</ol>
<div class="hint">결과 형식: {{"mode":"agent","platforms":[{{"platform":"panelnow","page_url":…,"page_text":…,"links":[{{"text","href"}}]}}]}} → <code>py scripts/money_scout.py ingest 결과.json</code></div></details></div>"""


# ---- 설정 ----------------------------------------------------------------------------------

def render_settings(store: money.MoneyStore, notice=None, error=None) -> str:
    c = store.config
    return f"""<div class="money">{NAV}<h1>⚙️ 목표 · 수익성 기준</h1>{_banner(notice, error)}
<form method="post" action="/money/settings" class="card" style="display:block">
<label class="f">목표 금액 (원, 쉼표로 여러 개 — 가장 작은 값이 첫 목표)</label>
<input type="text" name="goals" value="{escape(', '.join(str(g) for g in c['goals']))}">
<div class="row"><div><label class="f">🟢 지금 확인 (원/시간 이상)</label><input type="text" name="green" inputmode="numeric" value="{c['thresholds']['green']}"></div>
<div><label class="f">🟡 시간 여유 있을 때 (이상)</label><input type="text" name="yellow" inputmode="numeric" value="{c['thresholds']['yellow']}"></div>
<div><label class="f">🟠 다른 작업 없을 때 (이상, 그 아래는 🔴 보류)</label><input type="text" name="orange" inputmode="numeric" value="{c['thresholds']['orange']}"></div></div>
<div style="margin-top:10px"><button class="btn primary big" type="submit">저장</button></div>
<div class="hint">초기 실험용 기준입니다. 기준을 바꾸면 모든 카드의 등급과 추천 행동이 바로 다시 계산됩니다. 저장 위치: money_config.json</div></form></div>"""


# ---- 요청 처리 ------------------------------------------------------------------------------

NOTICES = {"added": "작업을 등록했습니다.", "opportunity": "기회를 저장했습니다. 할 거면 [할래요]를 누르세요.",
           "accepted": "할 작업으로 옮겼습니다.", "done": "완료 기록을 저장했습니다(예상값과 실제값을 따로 보관).",
           "skipped": "목록에서 내렸습니다(기록은 남습니다).", "income": "수익을 기록했습니다.", "saved": "저장했습니다.",
           "checked": "오늘 확인함으로 기록했습니다(작업 없음).", "requested": "스카우트 요청을 남겼습니다.",
           "running": "스카우트를 시작했습니다(1~2분).",
           "choice_do": "'한다'로 기록 — 할 작업으로 옮겼습니다. [열기 ↗]로 직접 참여하세요.", "choice_later": "'나중에'로 기록했습니다.",
           "choice_skip": "'안 한다'로 기록했습니다.", "scouted": "붙여 넣은 화면을 읽었습니다.", "found": "오늘 확인함(작업 있음) — 아래 빠른 등록에 적어 주세요."}


def handle(config, method: str, path: str, query: dict, body: bytes = b""):
    form = parse_qs(body.decode("utf-8"), keep_blank_values=True) if method == "POST" else {}
    get = lambda k: (form.get(k) or [""])[0]  # noqa: E731
    notice = NOTICES.get((query.get("notice") or [""])[0])
    try:
        store = _store(config)
        home_error = lambda e, text="": ("html", 400, _page("TAK AUTO MONEY", render_home(store, {}, error=e.text, quick_text=text)))  # noqa: E731
        if method == "GET" and path == "/money":
            return "html", 200, _page("TAK AUTO MONEY", render_home(store, query, notice))
        if method == "GET" and path == "/money/log":
            return "html", 200, _page("MONEY 기록", render_log(store, notice))
        if method == "GET" and path == "/money/capture":
            return "html", 200, _page("캡처 텍스트로 등록", render_capture())
        if method == "GET" and path == "/money/platforms":
            return "html", 200, _page("수익 플랫폼", render_platforms(store, notice))
        if method == "POST" and path == "/money/platforms/note":
            try:
                money.save_platform_note(config.money_config_path, get("platform"), get("note"))
            except money.MoneyError as error:
                return "html", 400, _page("수익 플랫폼", render_platforms(store, error=error.text))
            return "redirect", "/money/platforms?notice=saved"
        if path == "/money/settings":
            if method == "POST":
                try:
                    money.save_config(config.money_config_path, [g for g in get("goals").replace(" ", "").split(",") if g],
                                      {"green": get("green"), "yellow": get("yellow"), "orange": get("orange")})
                except money.MoneyError as error:
                    return "html", 400, _page("MONEY 설정", render_settings(store, error=error.text))
                return "redirect", "/money/settings?notice=saved"
            return "html", 200, _page("MONEY 설정", render_settings(store, notice))
        if method == "POST" and path == "/money/check":
            try:
                store.record_check(get("platform"), get("outcome"))
            except money.MoneyError as error:
                return home_error(error)
            if get("outcome") == "found":
                return "redirect", f"/money?notice=found&found={quote(get('platform'))}#quick"
            return "redirect", "/money?notice=checked#routine"
        if method == "POST" and path == "/money/quick":
            text = get("text")
            if not text.strip():
                return home_error(money.MoneyError("QUICK_PARSE_FAILED"), text)
            draft = money.parse_opportunity(text, store.config)
            draft["source"] = "ocr" if "\n" in text.strip() else "quick"
            return "html", 200, _page("등록 전 확인", render_confirm(store, draft))  # 저장하지 않는다 - 확인 화면만
        if method == "POST" and path == "/money/tasks":
            status = get("status") or "open"
            try:
                store.add_task(platform=get("platform"), title=get("title"), reward=get("reward"), minutes=get("minutes"),
                               url=get("url"), memo=get("memo"), deadline=get("deadline"), status=status,
                               source=get("source") if get("source") in ("manual", "quick", "ocr") else "manual", dedupe=True)
            except money.MoneyError as error:
                draft = {k: get(k) for k in ("platform", "title", "reward", "minutes", "source")}
                if get("source") in ("quick", "ocr"):  # 확인 화면에서 온 입력은 확인 화면으로 되돌려 값을 잃지 않게
                    return "html", 400, _page("등록 전 확인", render_confirm(store, {**draft, "missing": []}, error=error.text))
                return home_error(error)
            return "redirect", f"/money?notice={'opportunity' if status == 'new' else 'added'}"
        if method == "GET" and path == "/money/scout":
            return "html", 200, _page("MONEY SCOUT", render_scout(store, config, notice))
        if method == "POST" and path in ("/money/scout/request", "/money/scout/run"):
            return "redirect", f"/money/scout?notice={_start_agent_run(config)}"
        if method == "POST" and path == "/money/scout/choice":
            try:
                money_scout.record_choice(store, get("task_id"), get("choice"))
            except money.MoneyError as error:
                return "html", 400, _page("MONEY SCOUT", render_scout(store, config, error=error.text))
            return "redirect", f"/money/scout?notice=choice_{get('choice').lower()}"
        if method == "POST" and path == "/money/scout/manual":
            platform = get("platform")
            if platform not in MANUAL_PLATFORMS or not get("page_text").strip():
                return "html", 400, _page("MONEY SCOUT", render_scout(store, config, error="플랫폼을 고르고 화면 글자를 붙여 넣어 주세요."))
            run = money_scout.ingest({"mode": "manual", "platforms": [{"platform": platform, "page_text": get("page_text"),
                                                                       "page_url": money_scout.PLATFORMS[platform]["scout_url"]}]},
                                     tasks_path=config.money_tasks_path, staging_path=_staging_path(config))
            return "redirect", f"/money/scout?notice=scouted&status={run['platforms'][platform]['status']}"
        if method == "POST" and path == "/money/quick-done":
            try:
                store.quick_complete(platform=get("platform"), actual_reward=get("actual_reward"), actual_minutes=get("actual_minutes"),
                                     title=get("title"))
            except money.MoneyError as error:
                return "html", 400, _page("TAK AUTO MONEY", render_home(store, {"done": ["1"]}, error=error.text))
            return "redirect", "/money/log?notice=done"
        if method == "POST" and path == "/money/income":
            try:
                store.record_income(platform=get("platform"), amount=get("amount"), minutes=get("minutes"), title=get("title"))
            except money.MoneyError as error:
                return home_error(error)
            return "redirect", "/money/log?notice=income"
        parts = path.split("/")  # ["", "money", "task", id, action]
        if len(parts) == 5 and parts[2] == "task":
            task_id, action = unquote(parts[3]), parts[4]
            try:
                task = store.task(task_id)
            except money.MoneyError as error:
                return "html", 404, _page("작업 없음", f'<div class="money">{NAV}<div class="error">{escape(error.text)}</div></div>')
            if action == "complete" and method == "GET":
                return "html", 200, _page("완료 기록", render_complete(store, task))
            if action == "complete" and method == "POST":
                try:
                    store.complete(task_id, actual_reward=get("actual_reward"), actual_minutes=get("actual_minutes"), memo=get("memo"))
                except money.MoneyError as error:
                    status = 409 if error.code in ("ALREADY_COMPLETED", "TASK_CLOSED") else 400
                    return "html", status, _page("완료 기록", render_complete(store, store.task(task_id), error=error.text, form=form))
                return "redirect", "/money/log?notice=done"
            if action in ("skip", "accept") and method == "POST":
                try:
                    store.skip(task_id) if action == "skip" else store.accept(task_id)
                except money.MoneyError as error:
                    return "html", 409, _page("TAK AUTO MONEY", render_home(store, {}, error=error.text))
                return "redirect", f"/money?notice={'skipped' if action == 'skip' else 'accepted'}"
    except money.MoneyError as error:  # 데이터 파일을 읽을 수 없음 - 덮어쓰지 않고 알린다
        return "html", 500, _page("MONEY 오류", f'<div class="money">{NAV}<div class="error">{escape(error.text)}</div></div>')
    return "html", 404, _page("페이지 없음", "<p>페이지를 찾을 수 없습니다.</p>")
