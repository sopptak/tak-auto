/*
 * CHOICE100 화면 V2(6-65) - 엔진(Choice100.Game) 상태를 그리기만 한다. 규칙은 engine.js, 내용은 data/*.json, 기록은 analytics.js.
 * 빠른 루프(퀴즈식 템포): 상황 카드는 그대로 두고, 고른 버튼을 강조하고, 결과를 같은 화면 아래에 바로 붙인다 → [다음].
 * 저장: localStorage(try/catch). 저장이 안 되는 환경에서도 게임은 돈다.
 */
(function () {
  "use strict";
  const { Game, formatValue } = window.Choice100;
  const reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const DELTA_KEYS_EXTRA = ["income", "expense", "credit", "risk"];
  const COUNT_MS = 450;

  let app, data, game, saveKey, stats, lastHud = null;

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const def = (k) => data.stats.find((s) => s.key === k) || { key: k, ...(data.derived[k] || {}) };
  const fmt = (k, v) => formatValue(def(k).unit, v, data.money_unit);
  const signed = (k, v) => (v > 0 ? "+" : "") + (def(k).unit === "money" ? fmt(k, v) : String(v));
  const pad = (n) => String(n).padStart(2, "0");
  const storage = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 저장 불가 환경 - 무시 */ } },
    del(k) { try { window.localStorage.removeItem(k); } catch (e) { /* 무시 */ } },
  };
  const save = () => storage.set(saveKey, game.serialize());

  async function boot(root, url) {
    app = root;
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
    } catch (e) {
      app.innerHTML = `<div class="card">게임 데이터를 불러오지 못했습니다.<br><span class="flow">로컬에서 여는 경우: <code>py -m http.server 8790 --bind 127.0.0.1 -d game_lab/choice100</code> 후 http://127.0.0.1:8790/</span></div>`;
      return;
    }
    saveKey = `choice100:${data.id}`;
    stats = window.Choice100Analytics.create(storage, data.id, data.version);
    document.addEventListener("keydown", onKey);
    renderTitle();
  }

  function newGame(isRestart) {
    storage.del(saveKey);
    game = new Game(data);
    lastHud = null;
    stats.start(isRestart);
    save();
    renderPlay();
  }

  // ---- 타이틀 ----
  function renderTitle() {
    const saved = storage.get(saveKey);
    const resumable = saved ? Game.restore(data, saved) : null;
    const inProgress = resumable && resumable.state.phase !== "end";
    const st = stats.stats();
    app.innerHTML = `<section class="title-screen pop">
      <h1 class="logo">${esc(data.title)}<small>${esc(data.subtitle)}</small></h1>
      <p class="hook">"${esc(data.hook)}"</p>
      <p class="intro">${esc(data.intro)}</p>
      <button class="big" id="start">START</button>
      ${inProgress ? `<button class="ghost" id="resume">이어하기 · ${resumable.state.count}개 선택함</button>` : ""}
      ${st.completions ? `<button class="ghost" id="records">📊 내 플레이 기록 · ${st.completions}판</button>` : ""}
      <p class="disclaimer">이것은 가상의 재무 시뮬레이션입니다.<br>${esc(data.disclaimer)}</p>
    </section>`;
    app.querySelector("#start").onclick = () => newGame(!!inProgress);
    const r = app.querySelector("#resume");
    if (r) r.onclick = () => { game = resumable; lastHud = null; resume(); };
    const rec = app.querySelector("#records");
    if (rec) rec.onclick = renderRecords;
    app.querySelector("#start").focus({ preventScroll: true });
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
      const val = k === "happiness" ? values[k] : esc(fmt(k, values[k]));
      const bar = k === "happiness" ? `<div class="happy-bar"><i style="width:${values[k]}%"></i></div>` : "";
      return `<div class="stat${k === "net_worth" ? " wide" : ""}" data-k="${k}"><div class="k">${d.icon} ${esc(d.label)}</div><div class="v">${val}</div>${bar}</div>`;
    }).join("");
    return `<div class="hud" role="group" aria-label="재무 상태">${cells}</div>`;
  }

  function topHtml(n) {
    const sc = game.scenario();
    return `<div class="top"><span><b id="counter">선택 ${pad(n)}</b> / ${data.total_choices}</span><span>CH${sc.chapter} · ${esc(data.chapters[sc.chapter - 1].title)}</span></div>
      <div class="bar" role="progressbar" aria-label="진행" aria-valuemin="0" aria-valuemax="${data.total_choices}" aria-valuenow="${game.state.count}"><i id="progress" style="width:${(game.state.count / data.total_choices) * 100}%"></i></div>`;
  }

  function animateHud(from, to) {
    for (const k of data.hud) {
      const el = app.querySelector(`.stat[data-k="${k}"]`);
      if (!el) continue;
      const a = from ? from[k] : to[k], b = to[k];
      const v = el.querySelector(".v");
      const show = (x) => { v.textContent = k === "happiness" ? x : fmt(k, x); };
      const hb = el.querySelector(".happy-bar > i");
      if (hb) hb.style.width = `${b}%`;
      if (a === b) { show(b); continue; }
      const better = def(k).bad ? b < a : b > a;
      el.classList.remove("up", "down");
      void el.offsetWidth;
      el.classList.add(better ? "up" : "down");
      const f = document.createElement("span");
      f.className = `float ${better ? "good" : "bad"}`;
      f.textContent = signed(k, b - a);
      f.setAttribute("aria-hidden", "true");
      el.appendChild(f);
      setTimeout(() => { el.classList.remove("up", "down"); f.remove(); }, 1100);
      if (reduceMotion) { show(b); continue; }
      const t0 = performance.now();
      const step = (t) => {
        const p = Math.min(1, (t - t0) / COUNT_MS);
        show(Math.round(a + (b - a) * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }
  }

  // ---- 선택 화면 ----
  function echoHtml(e) {
    const o = e.origin;
    const from = o ? `<span class="origin">선택 ${pad(o.n)} 「${esc(o.choice)}」의 결과</span>` : "";
    return `<div class="event echo">🔁 ${from}${esc(e.text)}</div>`;
  }

  function renderPlay() {
    const sc = game.scenario();
    const now = game.snapshot();
    const from = lastHud || (game.state.enter_deltas ? Object.fromEntries(Object.keys(now).map((k) => [k, now[k] - (game.state.enter_deltas[k] || 0)])) : now);
    const echoTexts = new Set((game.state.enter_echoes || []).map((e) => e.text));
    const events = (game.state.enter_events || []).filter((e) => !echoTexts.has(e)).map((e) => `<div class="event">📰 ${esc(e)}</div>`).join("")
      + (game.state.enter_echoes || []).map(echoHtml).join("");
    const opts = game.choices().map((o, i) => `<button class="choice" data-id="${esc(o.choice.id)}"${o.enabled ? "" : " disabled"} aria-keyshortcuts="${i + 1}">
        <span class="no" aria-hidden="true">${i + 1}</span>${esc(o.choice.text)}${o.enabled ? "" : `<span class="why">${esc(o.reason)}</span>`}</button>`).join("");
    app.innerHTML = `<div class="sticky">${topHtml(Math.min(game.state.count + 1, data.total_choices))}${hudHtml(from)}</div>
      <section class="card pop" id="scene"><div class="chapter">CHAPTER ${sc.chapter}</div><h2 class="scene-title">${esc(sc.title)}</h2>
        <p class="situation">${esc(sc.situation)}</p>${events}</section>
      <div class="choices" role="group" aria-label="선택지 (키보드 1~4)">${opts}</div><div id="result"></div>${footHtml()}`;
    animateHud(from, now);
    lastHud = now;
    app.querySelectorAll(".choice:not([disabled])").forEach((b) => (b.onclick = () => pick(b.dataset.id)));
    const first = app.querySelector(".choice:not([disabled])");
    if (first && !("ontouchstart" in window)) first.focus({ preventScroll: true });
    bindFoot();
  }

  function pick(id) {
    if (game.state.phase !== "choose") return;
    const out = game.choose(id);
    stats.choice(out.n, out.scenario.id, out.choice.id);
    save();
    showResult(out);
  }

  // ---- 결과(같은 화면 아래에) ----
  function chip(k, delta) {
    const d = def(k);
    const good = d.bad ? delta < 0 : delta > 0;
    return `<span class="delta ${good ? "good" : "bad"}">${d.icon} ${esc(d.label)} ${esc(signed(k, delta))}</span>`;
  }

  function showResult(out) {
    // 칩은 선택 효과만(월급·이자 같은 매달 흐름은 아래 한 줄로 따로)
    const keys = [...data.hud, ...DELTA_KEYS_EXTRA].filter((k) => out.own[k]);
    const chips = keys.map((k) => chip(k, out.own[k])).join("") || `<span class="delta">숫자 변화 없음</span>`;
    const flow = Object.entries(out.flow).filter(([k]) => data.stats.some((s) => s.key === k && s.unit === "money"))
      .map(([k, v]) => `${def(k).label} ${signed(k, v)}`).join(" · ");
    const events = out.events.map((e) => `<div class="event warn">⚠️ ${esc(e)}</div>`).join("");
    const delayed = out.delayed ? `<div class="event later">⏳ 이 선택은 나중에 다시 돌아올 수 있습니다.</div>` : "";
    const label = out.phase === "end" ? "최종 결과 보기 ▶" : out.phase === "session_end" ? "중간 결과 보기 ▶" : "다음 선택 ▶";
    app.querySelectorAll(".choice").forEach((b) => {
      b.disabled = true;
      b.classList.add(b.dataset.id === out.choice.id ? "picked" : "faded");
      b.setAttribute("aria-pressed", b.dataset.id === out.choice.id ? "true" : "false");
    });
    const counter = app.querySelector("#counter");
    if (counter) counter.textContent = `선택 ${pad(out.n)}`;
    const prog = app.querySelector("#progress");
    if (prog) prog.style.width = `${(out.n / data.total_choices) * 100}%`;
    const box = app.querySelector("#result");
    box.innerHTML = `<section class="card result pop" role="status">
        <h3>${esc(out.result_text)}</h3><div class="deltas">${chips}</div>${delayed}${events}
        ${flow ? `<div class="flow">이번 달 흐름: ${esc(flow)}</div>` : ""}
        <div class="tip">💡 ${esc(out.tip)}</div>
        <button class="big next" id="next">${label}</button></section>`;
    animateHud(lastHud, out.after);
    const big = (out.own.net_worth || 0) <= -300 || out.events.length;
    if (big && !reduceMotion) { const s = app.querySelector("#scene"); s.classList.remove("shake"); void s.offsetWidth; s.classList.add("shake"); }
    lastHud = out.after;
    const nx = app.querySelector("#next");
    nx.onclick = advance;
    nx.focus({ preventScroll: true });
    nx.scrollIntoView({ block: "nearest" }); // 모바일: 결과와 [다음]이 한 화면에(HUD는 sticky)
  }

  function advance() {
    const ph = game.state.phase;
    if (ph === "end") return renderEnding();
    if (ph === "session_end") return renderSession();
    game.next();
    save();
    renderPlay();
    window.scrollTo({ top: 0 });
  }

  // ---- 중간 결과 ----
  function rowsHtml(pairs) {
    return `<div class="rows">${pairs.map(([a, b]) => `<div>${a}</div><div>${b}</div>`).join("")}</div>`;
  }

  function renderSession() {
    const s = game.sessionSummary();
    const ch = s.chapter;
    const change = (k) => `${esc(k === "happiness" ? s.now[k] : fmt(k, s.now[k]))} <span class="flow">(${esc(signed(k, s.change[k]))})</span>`;
    app.innerHTML = `<section class="card pop"><div class="chapter">선택 ${pad(s.count)} / ${data.total_choices} 완료</div>
      <h2 class="scene-title">CHAPTER ${ch.n} · ${esc(ch.title)} 끝!</h2>
      <div class="ending-title">순자산 ${esc(signed("net_worth", s.change.net_worth))}</div>
      ${rowsHtml(data.hud.map((k) => [`${def(k).icon} ${esc(def(k).label)}`, change(k)]))}
      <p class="flow">다음 챕터: ${esc(data.chapters[ch.n] ? data.chapters[ch.n].title : "-")}</p>
      <button class="big" id="cont">계속하기 ▶</button></section>${footHtml()}`;
    const c = app.querySelector("#cont");
    c.onclick = () => { game.next(); save(); renderPlay(); window.scrollTo({ top: 0 }); };
    c.focus({ preventScroll: true });
    bindFoot();
    window.scrollTo({ top: 0 });
  }

  // ---- 엔딩 ----
  function renderEnding() {
    const e = game.ending();
    const v = e.values;
    const style = game.styleResult();
    if (!game.state.recorded) {
      stats.complete({ choice_count: game.state.count, ending: e.id, style: style && style.key, net_worth: v.net_worth, debt: v.debt, happiness: v.happiness });
      game.state.recorded = true;
      save();
    }
    const prev = stats.previous();
    const start = { ...data.start };
    for (const [k, d] of Object.entries(data.derived)) start[k] = d.plus.reduce((a, x) => a + start[x], 0) - d.minus.reduce((a, x) => a + start[x], 0);
    const endTitle = (id) => (data.endings.find((x) => x.id === id) || { title: id }).title;
    const cmp = prev ? `<h3 class="sub-h">지난 판과 비교</h3><div class="rows cmp">
        <div></div><div>지난 판 → 이번</div>
        <div>🏦 순자산</div><div>${esc(fmt("net_worth", prev.net_worth))} → <b>${esc(fmt("net_worth", v.net_worth))}</b></div>
        <div>💳 부채</div><div>${esc(fmt("debt", prev.debt))} → <b>${esc(fmt("debt", v.debt))}</b></div>
        <div>😊 행복도</div><div>${prev.happiness} → <b>${v.happiness}</b></div>
        <div>🏁 결과</div><div>${esc(endTitle(prev.ending))} → <b>${esc(e.title)}</b></div></div>` : "";
    const playable = data.chapters.filter((c) => c.status === "playable").length * (data.session_size || 10);
    app.innerHTML = `<section class="card pop"><div class="chapter">선택 ${pad(game.state.count)} / ${data.total_choices} · 중간 엔딩</div>
      <div class="ending-icon" aria-hidden="true">${e.icon || "🏁"}</div><div class="ending-title">게임 결과: ${esc(e.title)}</div>
      <p class="situation center">${esc(e.text)}</p>
      ${rowsHtml([["🏦 순자산", `${esc(fmt("net_worth", v.net_worth))} <span class="flow">(${esc(signed("net_worth", v.net_worth - start.net_worth))})</span>`],
                  ["💰 현금", esc(fmt("cash", v.cash))], ["💳 부채", esc(fmt("debt", v.debt))], ["📈 투자", esc(fmt("investment", v.investment))],
                  ["😊 행복도", v.happiness], ["⚠️ 위험도", v.risk]])}
      ${style ? `<div class="style-box"><div class="k">나의 플레이 스타일</div><div class="style-title">${style.icon} ${esc(style.title)}</div>
        <div class="flow">${esc(style.text)} ${esc(data.style.note)}</div></div>` : ""}
      ${cmp}
      <p class="replay">다음에는 다른 선택을 해 보세요. 결과가 어떻게 달라질까요?</p>
      <button class="big" id="again">한 판 더 ↻</button>
      <button class="ghost" id="records">📊 내 플레이 기록</button>
      <p class="flow">지금 공개된 선택은 ${playable}개입니다. 나머지 ${data.total_choices - playable}개는 준비 중.</p>
      <p class="disclaimer">게임 결과이며 실제 재무 평가나 조언이 아닙니다.</p></section>${footHtml()}`;
    const again = app.querySelector("#again");
    again.onclick = () => newGame(true);
    again.focus({ preventScroll: true });
    app.querySelector("#records").onclick = renderRecords;
    bindFoot();
    window.scrollTo({ top: 0 });
  }

  // ---- 플레이 기록(이 브라우저에만 저장) ----
  function renderRecords() {
    const st = stats.stats();
    const runs = stats.runs().slice(-5).reverse();
    const endTitle = (id) => (data.endings.find((x) => x.id === id) || { title: id || "-" }).title;
    const time = (s) => (Number.isFinite(s) ? `${Math.floor(s / 60)}분 ${s % 60}초` : "-");
    const list = runs.map((r) => `<div class="run"><b>${esc(endTitle(r.ending))}</b> · ${esc(fmt("net_worth", r.net_worth))} · ${time(r.play_time_sec)}
        <div class="flow">${esc(r.completed_at.slice(0, 16).replace("T", " "))} · 선택 ${r.choice_count}개</div></div>`).join("") || `<p class="flow">아직 끝낸 판이 없습니다.</p>`;
    app.innerHTML = `<section class="card pop"><h2 class="scene-title">📊 내 플레이 기록</h2>
      ${rowsHtml([["시작한 판", st.plays], ["끝낸 판", st.completions], ["다시 하기", st.restart_count], ["평균 플레이 시간", time(st.avg_play_time_sec)]])}
      <h3 class="sub-h">최근 5판</h3>${list}
      <p class="flow">이 기록은 이 브라우저에만 저장됩니다. 서버로 보내지 않고 개인정보를 담지 않습니다.</p>
      <button class="big" id="back">처음 화면</button></section>`;
    const b = app.querySelector("#back");
    b.onclick = renderTitle;
    b.focus({ preventScroll: true });
  }

  // ---- 공통 ----
  function footHtml() {
    return `<div class="foot"><button id="about" aria-expanded="false" aria-controls="aboutText">이 게임에 대해</button> · <button id="home">처음 화면</button>
      <div id="aboutText" class="hidden" style="margin-top:6px">${esc(data.disclaimer)}</div></div>`;
  }
  function bindFoot() {
    const a = app.querySelector("#about"), h = app.querySelector("#home");
    if (a) a.onclick = () => { const t = app.querySelector("#aboutText"); t.classList.toggle("hidden"); a.setAttribute("aria-expanded", String(!t.classList.contains("hidden"))); };
    if (h) h.onclick = renderTitle;
  }

  function onKey(ev) {
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const n = Number(ev.key);
    if (n >= 1 && n <= 4) {
      const b = app.querySelectorAll(".choice")[n - 1];
      if (b && !b.disabled) { ev.preventDefault(); b.click(); }
      return;
    }
    // → 또는 (아무것도 포커스되지 않았을 때) Enter: 이 화면의 주 버튼
    const idle = !document.activeElement || document.activeElement === document.body;
    if (ev.key === "ArrowRight" || (ev.key === "Enter" && idle)) {
      const nx = app.querySelector("#next, #cont, #start, #again");
      if (nx) { ev.preventDefault(); nx.click(); }
    }
  }

  window.Choice100Renderer = { boot };
})();
