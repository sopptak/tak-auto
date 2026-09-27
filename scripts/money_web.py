"""TAK AUTO MONEY 화면(6-57) - scripts/run_scout_dashboard.py가 /money 요청을 여기로 넘긴다.

화면은 계산·기록·공식 링크만 한다. 외부 사이트 로그인/응답/제출 기능이 없고, 비밀번호·토큰·개인정보 입력칸이 없다.
공식 링크는 새 탭(rel="noopener noreferrer")으로 사람이 직접 연다.

    handle(config, method, path, query, body) -> ("html", status, bytes) | ("redirect", url)
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from urllib.parse import parse_qs, quote, unquote

from content_engine import money

STYLE = """<style>
  .money { max-width: 1100px; }
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
  .task { background: #fff; border: 1px solid #e2e2e0; border-left: 6px solid #ccc; border-radius: 10px; padding: 12px 14px; }
  .task.GREEN { border-left-color: #2e9e4f; } .task.YELLOW { border-left-color: #e0b400; }
  .task.ORANGE { border-left-color: #e57a1f; } .task.RED { border-left-color: #cf3b3b; } .task.expired { opacity: 0.55; }
  .tasks > .card { grid-column: 1 / -1; max-width: none; }
  .task .p { font-weight: 700; } .task .t { font-size: 1.02rem; margin: 2px 0 8px; }
  .task .n { font-size: 0.88rem; line-height: 1.7; } .task .rate { font-size: 1.2rem; font-weight: 800; }
  .money input[type=text], .money input[type=number], .money input[type=url], .money input[type=datetime-local], .money select, .money textarea {
    width: 100%; padding: 9px 10px; border-radius: 8px; border: 1px solid #ccc; font-size: 1rem; font-family: inherit; }
  .money label.f { display: block; font-size: 0.8rem; color: #555; margin: 8px 0 3px; font-weight: 600; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; } .row > div { flex: 1 1 150px; min-width: 0; }
  .tbl { border-collapse: collapse; width: 100%; background: #fff; font-size: 0.88rem; }
  .tbl th, .tbl td { border-bottom: 1px solid #eee; padding: 7px 8px; text-align: left; }
  .tbl td.num, .tbl th.num { text-align: right; white-space: nowrap; }
  .hint { font-size: 0.78rem; color: #777; } .up { color: #1a5c3a; } .down { color: #b3261e; }
  .btn.big { padding: 10px 16px; font-size: 0.95rem; }
  .legend span { margin-right: 10px; font-size: 0.8rem; }
</style>"""
NAV = ('<div class="nav-links"><a href="/">← Dashboard</a><a href="/money">💰 MONEY</a><a href="/money/log">📒 수익 기록·분석</a>'
       '<a href="/money/settings">⚙️ 목표·기준</a><a href="/operator">🧭 Operator Center</a></div>')


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


def _local(ts: str | None, config: dict) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(money.local_tz(config)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "-"


def _store(config) -> money.MoneyStore:
    return money.MoneyStore(config.money_tasks_path, config.money_log_path, money.load_config(config.money_config_path))


def _options(values, current) -> str:
    return "".join(f'<option value="{escape(str(v))}"{" selected" if str(v) == str(current or "") else ""}>{escape(str(label))}</option>'
                   for v, label in values)


def _banner(notice: str | None, error: str | None) -> str:
    return (f'<div class="banner">{escape(notice)}</div>' if notice else "") + (f'<div class="error">{escape(error)}</div>' if error else "")


# ---- /money --------------------------------------------------------------------------------

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
        return f"""<div class="goal"><b>🎯 첫 온라인 수익 목표</b> <span style="font-size:1.3rem;font-weight:800">{first:,}원</span>
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
    reward = f"{t['reward']:,}P" if pv != 1 else f"{t['reward']:,}원"
    deadline = ""
    if t.get("deadline"):
        if t["expired"]:
            deadline = f'<div class="down">⏰ 마감 지남 ({escape(_local(t["deadline"], config))})</div>'
        else:
            left = t["minutes_left"]
            deadline = f'<div>⏰ 마감 {escape(_local(t["deadline"], config))} (남은 {_minutes(left) if left < 2880 else f"{left // 1440}일"})</div>'
    link = (f'<a class="btn primary" href="{escape(t["url"])}" target="_blank" rel="noopener noreferrer">바로가기 ↗</a>'
            if t.get("url") else '<span class="hint">링크 없음</span>')
    memo = f'<div class="hint">📝 {escape(t["memo"])}</div>' if t.get("memo") else ""
    return f"""<div class="task {t['grade']}{' expired' if t['expired'] else ''}" id="{escape(t['id'])}">
<div class="p">{icon} {escape(t['platform'])} <span class="hint">{escape(desc)}</span></div>
<div class="t">{escape(t['title'])}</div>
<div class="n">예상시간 {_minutes(t['minutes'])}<br>예상보상 {escape(reward)}<br>예상 시급 <span class="rate">{t['estimated_hourly'] or 0:,}원</span>{deadline}</div>
{memo}
<div class="actions" style="margin-top:10px">{link}
<a class="btn" href="/money/task/{quote(t['id'])}/complete">완료 기록</a>
<form method="post" action="/money/task/{quote(t['id'])}/skip"><button class="btn ghost" type="submit">안 함</button></form></div></div>"""


def render_home(store: money.MoneyStore, query: dict, notice=None, error=None, quick_text="") -> str:
    config = store.config
    tasks, log = store.tasks(), store.log()
    stats = money.period_stats(log, config)
    goal = money.goal_status(stats["total"]["earned"], config)
    get = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    sort, grade_filter, platform_filter = get("sort") or "hourly", get("grade"), get("platform")
    rows = money.open_tasks(tasks, config, sort=sort)
    shown = [t for t in rows if (not grade_filter or t["grade"] == grade_filter) and (not platform_filter or t["platform"] == platform_filter)]
    cards = "".join(_task_card(t, config) for t in shown) or (
        '<div class="card">아직 등록된 작업이 없습니다. 위 <b>빠른 등록</b>에 "패널나우 20분 850P"처럼 적어 보세요.</div>' if not rows
        else '<div class="card">조건에 맞는 작업이 없습니다.</div>')
    th = config["thresholds"]
    legend = (f'<div class="legend hint"><span>🟢 {th["green"]:,}원/시간 이상</span><span>🟡 {th["yellow"]:,}~{th["green"] - 1:,}</span>'
              f'<span>🟠 {th["orange"]:,}~{th["yellow"] - 1:,}</span><span>🔴 {th["orange"]:,} 미만</span>'
              '<span>(초기 실험용 기준 · <a href="/money/settings">바꾸기</a>)</span></div>')
    platforms = [p["name"] for p in config["platforms"]]
    filters = f"""<form method="get" action="/money" class="row" style="max-width:720px;margin:6px 0 10px">
<div><select name="sort">{_options([("hourly", "예상 시급 높은 순"), ("deadline", "마감 빠른 순"), ("new", "최근 등록 순")], sort)}</select></div>
<div><select name="grade">{_options([("", "모든 등급")] + [(g, f"{i} {d}") for g, (i, d) in money.GRADES.items()], grade_filter)}</select></div>
<div><select name="platform">{_options([("", "모든 플랫폼")] + [(p, p) for p in platforms], platform_filter)}</select></div>
<div style="flex:0 0 auto"><button class="btn" type="submit">보기</button></div></form>"""
    official = " · ".join(f'<a href="{escape(p["url"])}" target="_blank" rel="noopener noreferrer">{escape(p["name"])} ↗</a>'
                          for p in config["platforms"] if p.get("url"))
    return f"""<div class="money">{NAV}
<h1>💰 TAK AUTO MONEY</h1><div class="sub">온라인 수익 노가다 관제판 — 찾고(DISCOVER) · 거르고(FILTER) · 직접 하고(DO) · 기록하고(RECORD) · 배운다(LEARN)</div>
{_banner(notice, error)}
{_goal_html(goal)}
{_kpis(stats)}
<h2>⚡ 빠른 등록</h2>
<form method="post" action="/money/quick" class="card" style="display:block">
<div class="row"><div style="flex:3 1 260px"><input type="text" name="text" value="{escape(quick_text)}" placeholder="예: 패널나우 20분 850P 일반인 의견 조사" required></div>
<div style="flex:0 0 auto"><button class="btn primary big" type="submit">등록</button></div></div>
<div class="hint">플랫폼 · 시간 · 보상만 적으면 예상 시급을 계산해 등록합니다(링크는 플랫폼 공식 주소).</div></form>
<h2>🔥 지금 할 만한 온라인 작업 <span class="hint">({len(rows)}건)</span></h2>
{legend}{filters}
<div class="tasks">{cards}</div>

<details class="card"><summary><b>✍️ 자세히 등록</b> (링크·메모·마감시간)</summary>
<form method="post" action="/money/tasks" style="display:block">
<div class="row"><div><label class="f">플랫폼</label><select name="platform">{_options([(p, p) for p in platforms], platforms[0])}</select></div>
<div style="flex:2 1 240px"><label class="f">작업명</label><input type="text" name="title" required maxlength="120" placeholder="일반인 의견 조사"></div></div>
<div class="row"><div><label class="f">예상 보상 (원 또는 P)</label><input type="text" name="reward" inputmode="numeric" required placeholder="850"></div>
<div><label class="f">예상 소요시간 (분)</label><input type="text" name="minutes" inputmode="numeric" required placeholder="20"></div>
<div><label class="f">마감시간 (선택)</label><input type="datetime-local" name="deadline"></div></div>
<label class="f">공식 링크 (비우면 플랫폼 공식 주소)</label><input type="url" name="url" placeholder="https://">
<label class="f">메모 (선택 · 비밀번호/개인정보는 적지 마세요)</label><input type="text" name="memo" maxlength="500">
<div style="margin-top:10px"><button class="btn primary big" type="submit">저장</button></div></form></details>

<details class="card"><summary><b>💵 작업 없이 들어온 수익 기록</b> (애드포스트 정산 등)</summary>
<form method="post" action="/money/income" style="display:block">
<div class="row"><div><label class="f">플랫폼</label><select name="platform">{_options([(p, p) for p in platforms], "네이버 애드포스트")}</select></div>
<div><label class="f">금액 (원)</label><input type="text" name="amount" inputmode="numeric" required></div>
<div><label class="f">들인 시간 (분, 선택)</label><input type="text" name="minutes" inputmode="numeric" placeholder="0"></div></div>
<label class="f">내용 (선택)</label><input type="text" name="title" maxlength="120" placeholder="9월 정산">
<div style="margin-top:10px"><button class="btn big" type="submit">기록</button></div>
<div class="hint">시간을 비우면 수익에는 더하고 시간당 수익 계산에서는 뺍니다.</div></form></details>

<div class="sub" style="margin-top:14px">공식 사이트: {official}<br>
TAK AUTO는 계산·기록·공식 링크만 합니다. 로그인·설문 응답·본인인증은 각 사이트에서 직접 하세요. 비밀번호/인증번호/개인정보는 여기에 저장하지 않습니다.</div>
</div>"""


# ---- 완료 기록 ------------------------------------------------------------------------------

def render_complete(store: money.MoneyStore, task: dict, error=None, form=None) -> str:
    config = store.config
    form = form or {}
    val = lambda k, d="": escape((form.get(k) or [d])[0])  # noqa: E731
    pv = task.get("point_value", 1)
    est = money.hourly(task["reward"] * pv, task["minutes"])
    done = task["status"] != "open"
    body = (f'<div class="error">{escape(money.ERROR_TEXT["ALREADY_COMPLETED" if task["status"] == "done" else "TASK_CLOSED"])}</div>' if done else f"""
<form method="post" action="/money/task/{quote(task['id'])}/complete" class="card" style="display:block">
<div class="row"><div><label class="f">실제 받은 보상 (원 또는 P)</label><input type="text" name="actual_reward" inputmode="numeric" required value="{val('actual_reward', str(task['reward']))}"></div>
<div><label class="f">실제 소요시간 (분)</label><input type="text" name="actual_minutes" inputmode="numeric" required value="{val('actual_minutes')}" placeholder="{task['minutes']:g}"></div></div>
<label class="f">완료 메모 (선택)</label><input type="text" name="memo" maxlength="500" value="{val('memo')}">
<div style="margin-top:10px"><button class="btn primary big" type="submit">완료 기록 저장</button></div>
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
    prow = "".join(
        f'<tr><td>{escape(p["platform"])}</td><td class="num">{p["count"]}</td><td class="num">{_won(p["earned"])}</td><td class="num">{_minutes(p["minutes"])}</td>'
        f'<td class="num">{(money.GRADES[p["grade"]][0] + " ") if p["grade"] else ""}{_rate(p["actual_hourly"])}</td><td class="num">{_rate(p["estimated_hourly"])}</td>'
        f'<td class="num {("up" if (p["hourly_gap_pct"] or 0) >= 0 else "down")}">{"-" if p["hourly_gap_pct"] is None else f"{p["hourly_gap_pct"]:+g}%"}</td></tr>'
        for p in plat)
    entries = []
    for e in sorted(log, key=lambda e: e["completed_at"], reverse=True):
        est = (f'{e["estimated_reward"]:,}원 / {_minutes(e["estimated_minutes"])} ({_rate(e["estimated_hourly"])})'
               if e.get("kind") == "task" else "작업 없이 들어온 수익")
        entries.append(f"""<div class="card"><b>{escape(e['platform'])}</b> · {escape(e['title'])}
<div class="n">예상: {escape(est)}<br>실제: <b>{money.won(e):,}원 / {_minutes(e['actual_minutes'])}</b><br>
실제 시급: <b>{_rate(e['actual_hourly'])}</b><br><span class="hint">완료: {escape(_local(e['completed_at'], config))}</span>
{f'<div class="hint">📝 {escape(e["memo"])}</div>' if e.get('memo') else ''}</div></div>""")
    return f"""<div class="money">{NAV}<h1>📒 수익 기록 · 분석</h1>{_banner(notice, None)}
{_kpis(stats)}
<h2>📊 플랫폼별</h2>
<table class="tbl"><tr><th>플랫폼</th><th class="num">건수</th><th class="num">누적 수익</th><th class="num">투자</th><th class="num">실제 시급</th><th class="num">예상 시급</th><th class="num">예상 대비</th></tr>{prow}</table>
<div class="hint">예상 대비 = (실제 시급 − 예상 시급) ÷ 예상 시급. 기록이 쌓일수록 어느 플랫폼이 실제로 나은지 보입니다.</div>
<h2>최근 완료</h2>{"".join(entries) or '<div class="card">아직 기록이 없습니다.</div>'}</div>"""


# ---- 설정 ----------------------------------------------------------------------------------

def render_settings(store: money.MoneyStore, notice=None, error=None) -> str:
    c = store.config
    return f"""<div class="money">{NAV}<h1>⚙️ 목표 · 수익성 기준</h1>{_banner(notice, error)}
<form method="post" action="/money/settings" class="card" style="display:block">
<label class="f">목표 금액 (원, 쉼표로 여러 개 — 가장 작은 값이 첫 목표)</label>
<input type="text" name="goals" value="{escape(', '.join(str(g) for g in c['goals']))}">
<div class="row"><div><label class="f">🟢 적극 검토 (원/시간 이상)</label><input type="text" name="green" inputmode="numeric" value="{c['thresholds']['green']}"></div>
<div><label class="f">🟡 검토 (이상)</label><input type="text" name="yellow" inputmode="numeric" value="{c['thresholds']['yellow']}"></div>
<div><label class="f">🟠 낮음 (이상, 그 아래는 🔴)</label><input type="text" name="orange" inputmode="numeric" value="{c['thresholds']['orange']}"></div></div>
<div style="margin-top:10px"><button class="btn primary big" type="submit">저장</button></div>
<div class="hint">초기 실험용 기준입니다. 실제 기록을 보고 바꾸세요. 저장 위치: money_config.json</div></form></div>"""


# ---- 요청 처리 ------------------------------------------------------------------------------

NOTICES = {"added": "작업을 등록했습니다.", "done": "완료 기록을 저장했습니다(예상값과 실제값을 따로 보관).",
           "skipped": "작업을 목록에서 내렸습니다(기록은 남습니다).", "income": "수익을 기록했습니다.", "saved": "저장했습니다."}


def handle(config, method: str, path: str, query: dict, body: bytes = b""):
    form = parse_qs(body.decode("utf-8"), keep_blank_values=True) if method == "POST" else {}
    get = lambda k: (form.get(k) or [""])[0]  # noqa: E731
    notice = NOTICES.get((query.get("notice") or [""])[0])
    try:
        store = _store(config)
        if method == "GET" and path == "/money":
            return "html", 200, _page("TAK AUTO MONEY", render_home(store, query, notice))
        if method == "GET" and path == "/money/log":
            return "html", 200, _page("MONEY 기록", render_log(store, notice))
        if path == "/money/settings":
            if method == "POST":
                try:
                    money.save_config(config.money_config_path, [g for g in get("goals").replace(" ", "").split(",") if g],
                                      {"green": get("green"), "yellow": get("yellow"), "orange": get("orange")})
                except money.MoneyError as error:
                    return "html", 400, _page("MONEY 설정", render_settings(store, error=error.text))
                return "redirect", "/money/settings?notice=saved"
            return "html", 200, _page("MONEY 설정", render_settings(store, notice))
        if method == "POST" and path == "/money/quick":
            try:
                parsed = money.quick_parse(get("text"), store.config)
                store.add_task(platform=parsed["platform"], title=parsed["title"], reward=parsed["reward"],
                               minutes=parsed["minutes"], source="quick")
            except money.MoneyError as error:
                return "html", 400, _page("TAK AUTO MONEY", render_home(store, {}, error=error.text, quick_text=get("text")))
            return "redirect", "/money?notice=added"
        if method == "POST" and path == "/money/tasks":
            try:
                store.add_task(platform=get("platform"), title=get("title"), reward=get("reward"), minutes=get("minutes"),
                               url=get("url"), memo=get("memo"), deadline=get("deadline"))
            except money.MoneyError as error:
                return "html", 400, _page("TAK AUTO MONEY", render_home(store, {}, error=error.text))
            return "redirect", "/money?notice=added"
        if method == "POST" and path == "/money/income":
            try:
                store.record_income(platform=get("platform"), amount=get("amount"), minutes=get("minutes"), title=get("title"))
            except money.MoneyError as error:
                return "html", 400, _page("TAK AUTO MONEY", render_home(store, {}, error=error.text))
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
            if action == "skip" and method == "POST":
                try:
                    store.skip(task_id)
                except money.MoneyError as error:
                    return "html", 409, _page("TAK AUTO MONEY", render_home(store, {}, error=error.text))
                return "redirect", "/money?notice=skipped"
    except money.MoneyError as error:  # 데이터 파일을 읽을 수 없음 - 덮어쓰지 않고 알린다
        return "html", 500, _page("MONEY 오류", f'<div class="money">{NAV}<div class="error">{escape(error.text)}</div></div>')
    return "html", 404, _page("페이지 없음", "<p>페이지를 찾을 수 없습니다.</p>")
