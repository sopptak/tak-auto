/*
 * CHOICE100 화면(6-64 G1) - 엔진(Choice100.Game) 상태를 그리기만 한다. 게임 규칙은 engine.js, 내용은 data/*.json.
 * 흐름: 타이틀 → 상황 → 선택 → 결과(숫자 변화 + 한 줄 TIP) → 다음 … 10개마다 중간 결과 → 마지막 엔딩.
 * 저장: localStorage(try/catch) - 새로고침해도 이어하기. 저장이 안 되는 환경에서도 게임은 그대로 돈다.
 */
(function () {
  "use strict";
  const { Game, formatValue } = window.Choice100;
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const DELTA_KEYS_EXTRA = ["income", "expense", "credit", "risk"];

  let app, data, game, saveKey, lastHud = null;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const def = (k) => data.stats.find((s) => s.key === k) || { key: k, ...(data.derived[k] || {}) };
  const fmt = (k, v) => formatValue(def(k).unit, v, data.money_unit);
  const pad = (n) => String(n).padStart(2, "0");

  function store(op, value) {
    try {
      if (op === "get") return window.localStorage.getItem(saveKey);
      if (op === "set") window.localStorage.setItem(saveKey, value);
      if (op === "del") window.localStorage.removeItem(saveKey);
    } catch (e) { /* 저장 불가 환경(시크릿 창 등) - 무시 */ }
    return null;
  }
  const save = () => store("set", game.serialize());

  async function boot(root, url) {
    app = root;
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
    } catch (e) {
      app.innerHTML = `<div class="card">게임 데이터를 불러오지 못했습니다.<br><span class="flow">로컬에서 여는 경우: <code>py -m http.server 8790 -d game_lab/choice100</code> 후 http://127.0.0.1:8790/</span></div>`;
      return;
    }
    saveKey = `choice100:${data.id}`;
    document.addEventListener("keydown", onKey);
    renderTitle();
  }

  // ---- 타이틀 ----
  function renderTitle() {
    const saved = store("get");
    const resumable = saved ? Game.restore(data, saved) : null;
    app.innerHTML = `<section class="title-screen pop">
      <h1 class="logo">${esc(data.title)}<small>${esc(data.subtitle)}</small></h1>
      <p class="hook">"${esc(data.hook)}"</p>
      <p class="intro">${esc(data.intro)}</p>
      <button class="big" id="start">START</button>
      ${resumable && resumable.state.phase !== "end" ? `<button class="ghost" id="resume">이어하기 · ${resumable.state.count}개 선택함</button>` : ""}
      <p class="disclaimer">이것은 가상의 재무 시뮬레이션입니다.<br>${esc(data.disclaimer)}</p>
    </section>`;
    app.querySelector("#start").onclick = () => { store("del"); game = new Game(data); lastHud = null; save(); renderPlay(); };
    const r = app.querySelector("#resume");
    if (r) r.onclick = () => { game = resumable; lastHud = null; resume(); };
  }

  function resume() {
    const ph = game.state.phase;
    if (ph === "result") { game.next(); save(); renderPlay(); }
    else if (ph === "session_end") renderSession();
    else if (ph === "end") renderEnding();
    else renderPlay();
  }

  // ---- 상단 ----
  function hudHtml(values) {
    const cells = data.hud.map((k) => {
      const d = def(k);
      if (k === "happiness") {
        return `<div class="stat" data-k="${k}"><div class="k">${d.icon} ${esc(d.label)}</div><div class="v">${values[k]}</div>
                <div class="happy-bar"><i style="width:${values[k]}%"></i></div></div>`;
      }
      return `<div class="stat${k === "net_worth" ? " wide" : ""}" data-k="${k}"><div class="k">${d.icon} ${esc(d.label)}</div><div class="v">${esc(fmt(k, values[k]))}</div></div>`;
    }).join("");
    return `<div class="hud">${cells}</div>`;
  }

  function topHtml(n = Math.min(game.state.count + 1, data.total_choices)) {
    const sc = game.scenario();
    const playable = data.scenarios.length;
    return `<div class="top"><span><b>선택 ${pad(n)}</b> / ${data.total_choices}</span><span>CH${sc.chapter} · ${esc(data.chapters[sc.chapter - 1].title)}</span></div>
      <div class="bar" title="G1 공개 ${playable}개"><i style="width:${(game.state.count / data.total_choices) * 100}%"></i></div>`;
  }

  function animateHud(from, to) {
    for (const k of data.hud) {
      const el = app.querySelector(`.stat[data-k="${k}"]`);
      if (!el) continue;
      const a = from ? from[k] : to[k], b = to[k];
      const v = el.querySelector(".v");
      if (a !== b) {
        const better = def(k).bad ? b < a : b > a;
        el.classList.remove("up", "down");
        void el.offsetWidth;
        el.classList.add(better ? "up" : "down");
        setTimeout(() => el.classList.remove("up", "down"), 900);
      }
      if (reduceMotion || a === b) { v.textContent = k === "happiness" ? b : fmt(k, b); continue; }
      const t0 = performance.now(), dur = 500;
      const step = (t) => {
        const p = Math.min(1, (t - t0) / dur);
        const cur = Math.round(a + (b - a) * (1 - Math.pow(1 - p, 3)));
        v.textContent = k === "happiness" ? cur : fmt(k, cur);
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
      const hb = el.querySelector(".happy-bar > i");
      if (hb) hb.style.width = `${b}%`;
    }
  }

  // ---- 선택 화면 ----
  function renderPlay() {
    const sc = game.scenario();
    const now = game.snapshot();
    const from = lastHud || (game.state.enter_deltas ? Object.fromEntries(Object.keys(now).map((k) => [k, now[k] - (game.state.enter_deltas[k] || 0)])) : now);
    const events = (game.state.enter_events || []).map((e) => `<div class="event">📰 ${esc(e)}</div>`).join("");
    const opts = game.choices().map((o, i) => `<button class="choice" data-id="${esc(o.choice.id)}"${o.enabled ? "" : " disabled"}>
        <span class="no">${i + 1}</span>${esc(o.choice.text)}${o.enabled ? "" : `<span class="why">${esc(o.reason)}</span>`}</button>`).join("");
    app.innerHTML = `${topHtml()}${hudHtml(from)}
      <section class="card pop"><div class="chapter">CHAPTER ${sc.chapter}</div><h2 class="scene-title">${esc(sc.title)}</h2>
        <p class="situation">${esc(sc.situation)}</p>${events}</section>
      <div class="choices">${opts}</div>${footHtml()}`;
    animateHud(from, now);
    lastHud = now;
    app.querySelectorAll(".choice:not([disabled])").forEach((b) => (b.onclick = () => pick(b.dataset.id)));
    bindFoot();
  }

  function pick(id) {
    const out = game.choose(id);
    save();
    renderResult(out);
  }

  // ---- 결과 ----
  function chip(k, delta) {
    const d = def(k);
    const good = d.bad ? delta < 0 : delta > 0;
    const sign = delta > 0 ? "+" : "";
    const val = d.unit === "money" ? (delta > 0 ? "+" : "") + fmt(k, delta) : `${sign}${delta}`;
    return `<span class="delta ${good ? "good" : "bad"}">${d.icon} ${esc(d.label)} ${esc(val)}</span>`;
  }

  function renderResult(out) {
    // 선택 효과만 칩으로(월급·이자 같은 매달 흐름은 아래 한 줄로 따로)
    const own = {};
    for (const [k, v] of Object.entries(out.deltas)) {
      const x = v - (out.flow[k] || 0);
      if (x) own[k] = x;
    }
    const keys = [...data.hud, ...DELTA_KEYS_EXTRA].filter((k) => own[k]);
    const chips = keys.map((k) => chip(k, own[k])).join("") || `<span class="delta">변화 없음</span>`;
    const flow = Object.entries(out.flow).filter(([k]) => k !== "net_worth" && data.stats.some((s) => s.key === k))
      .map(([k, v]) => `${def(k).label} ${v > 0 ? "+" : ""}${fmt(k, v)}`).join(" · ");
    const events = out.events.map((e) => `<div class="event">⚠️ ${esc(e)}</div>`).join("");
    const label = out.phase === "end" ? "최종 결과 보기 ▶" : out.phase === "session_end" ? "중간 결과 보기 ▶" : "다음 선택 ▶";
    const before = lastHud;
    app.innerHTML = `${topHtml(game.state.count)}${hudHtml(before)}
      <section class="card result pop"><div class="chapter">${esc(out.scenario.title)} → ${esc(out.choice.text)}</div>
        <h3>${esc(out.result_text)}</h3><div class="deltas">${chips}</div>
        ${flow ? `<div class="flow">이번 달 흐름: ${esc(flow)}</div>` : ""}${events}
        <div class="tip">💡 ${esc(out.tip)}</div>
        <button class="big next" id="next">${label}</button></section>${footHtml()}`;
    animateHud(before, out.after);
    lastHud = out.after;
    app.querySelector("#next").onclick = advance;
    app.querySelector("#next").focus({ preventScroll: true });
    bindFoot();
  }

  function advance() {
    const ph = game.state.phase;
    if (ph === "end") return renderEnding();
    if (ph === "session_end") return renderSession();
    game.next();
    save();
    renderPlay();
  }

  // ---- 중간 결과 ----
  function rowsHtml(pairs) {
    return `<div class="rows">${pairs.map(([a, b]) => `<div>${a}</div><div>${b}</div>`).join("")}</div>`;
  }

  function renderSession() {
    const s = game.sessionSummary();
    const ch = s.chapter;
    const change = (k) => { const v = s.change[k]; return `${esc(fmt(k, s.now[k]))} <span class="flow">(${v >= 0 ? "+" : ""}${esc(fmt(k, v))})</span>`; };
    app.innerHTML = `<section class="card pop"><div class="chapter">선택 ${pad(s.count)} / ${data.total_choices} 완료</div>
      <h2 class="scene-title">CHAPTER ${ch.n} · ${esc(ch.title)} 끝!</h2>
      <div class="ending-title">순자산 ${s.change.net_worth >= 0 ? "+" : ""}${esc(fmt("net_worth", s.change.net_worth))}</div>
      ${rowsHtml(data.hud.map((k) => [`${def(k).icon} ${esc(def(k).label)}`, k === "happiness" ? `${s.now[k]} <span class="flow">(${s.change[k] >= 0 ? "+" : ""}${s.change[k]})</span>` : change(k)]))}
      <p class="flow">다음 챕터: ${esc(data.chapters[ch.n] ? data.chapters[ch.n].title : "-")}</p>
      <button class="big" id="cont">계속하기 ▶</button></section>${footHtml()}`;
    app.querySelector("#cont").onclick = () => { game.next(); save(); renderPlay(); };
    bindFoot();
  }

  // ---- 엔딩 ----
  function renderEnding() {
    const e = game.ending();
    const v = e.values;
    const start = { ...data.start };
    for (const [k, d] of Object.entries(data.derived)) start[k] = d.plus.reduce((a, x) => a + start[x], 0) - d.minus.reduce((a, x) => a + start[x], 0);
    const nwd = v.net_worth - start.net_worth;
    const playable = data.scenarios.length;
    app.innerHTML = `<section class="card pop"><div class="chapter">선택 ${pad(game.state.count)} / ${data.total_choices} · G1 중간 엔딩</div>
      <div class="ending-icon">${e.icon || "🏁"}</div><div class="ending-title">게임 결과: ${esc(e.title)}</div>
      <p class="situation" style="text-align:center">${esc(e.text)}</p>
      ${rowsHtml([["🏦 순자산", `${esc(fmt("net_worth", v.net_worth))} <span class="flow">(${nwd >= 0 ? "+" : ""}${esc(fmt("net_worth", nwd))})</span>`],
                  ["💰 현금", esc(fmt("cash", v.cash))], ["💳 부채", esc(fmt("debt", v.debt))], ["📈 투자", esc(fmt("investment", v.investment))],
                  ["😊 행복도", v.happiness], ["⚠️ 위험도", v.risk], ["💼 월소득 / 🧾 월지출", `${esc(fmt("income", v.income))} / ${esc(fmt("expense", v.expense))}`]])}
      <p class="flow">지금 공개된 선택은 ${playable}개입니다. 나머지 ${data.total_choices - playable}개(주거·위기·커리어·가족·은퇴)는 준비 중.</p>
      <button class="big" id="again">다시 하기 ↻</button>
      <p class="disclaimer">게임 결과이며 실제 재무 평가나 조언이 아닙니다.</p></section>${footHtml()}`;
    app.querySelector("#again").onclick = () => { store("del"); game = new Game(data); lastHud = null; save(); renderPlay(); };
    bindFoot();
  }

  // ---- 공통 ----
  function footHtml() {
    return `<div class="foot"><button id="about">이 게임에 대해</button> · <button id="home">처음 화면</button>
      <div id="aboutText" class="hidden" style="margin-top:6px">${esc(data.disclaimer)}</div></div>`;
  }
  function bindFoot() {
    const a = app.querySelector("#about"), h = app.querySelector("#home");
    if (a) a.onclick = () => app.querySelector("#aboutText").classList.toggle("hidden");
    if (h) h.onclick = renderTitle;
  }

  function onKey(ev) {
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const n = Number(ev.key);
    if (n >= 1 && n <= 4) {
      const b = app.querySelectorAll(".choice")[n - 1];
      if (b && !b.disabled) b.click();
    }
  }

  window.Choice100Renderer = { boot };
})();
