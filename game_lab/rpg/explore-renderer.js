/*
 * 고조선 탐험·부족 통합 화면(6-68). 규칙은 explore.js(+ engine.js 성장, ../board/engine.js 사냥). 기록은 ../choice100/analytics.js(이 브라우저만).
 * 한 화면: 상단(성장·자원) → 지도(안개) → 결과 → 사건/미니게임 또는 [장소 행동 · 부족 · 길].
 */
(function () {
  "use strict";
  const { Explore } = window.Choice100Explore;
  const BoardGame = window.Choice100Board.Game;
  const FACES = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];
  let app, data, game, stats, saveKey, last = null, boardLog = [], tab = "play";

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const storage = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 저장 불가 */ } },
    del(k) { try { window.localStorage.removeItem(k); } catch (e) { /* 무시 */ } },
  };
  const save = () => storage.set(saveKey, game.serialize());
  const badge = (hs) => (hs ? `<span class="hs hs-${hs}">${esc(data.historical_status_labels[hs])}</span>` : "");
  const lab = (k) => data.stat_labels[k] || [k, ""];
  const byId = (arr, id) => data[arr].find((x) => x.id === id);
  const edgeName = (id) => { const e = data.explore.edges.find((x) => x.id === id); const a = game.L[e.from], b = game.L[e.to]; return `${a.icon} ${a.name} ↔ ${b.icon} ${b.name}`; };

  async function boot(root, url) {
    app = root;
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
    } catch (e) {
      app.innerHTML = `<div class="card">데이터를 불러오지 못했습니다. <code>py -m http.server 8790 --bind 127.0.0.1 -d game_lab</code> 후 http://127.0.0.1:8790/rpg/gojoseon/</div>`;
      return;
    }
    saveKey = `choice100explore:${data.id}`;
    stats = window.Choice100Analytics.create(storage, data.id, data.version);
    document.addEventListener("keydown", onKey);
    renderTitle();
  }

  // ---- 타이틀 ----
  function renderTitle() {
    const saved = storage.get(saveKey);
    const resumable = saved ? Explore.restore(data, saved, { BoardGame }) : null;
    app.innerHTML = `<section class="title-screen pop"><div class="flag" aria-hidden="true">🏞️</div>
      <h1 class="logo">${esc(data.title)}<small>${esc(data.subtitle)}</small></h1>
      <p class="hook">${esc(data.tagline)}</p>
      <div class="intro">강가에 자리 잡은 작은 무리. 당신은 그 우두머리다.<br>탐험하고, 부족을 만나고, 함께할 길을 찾아 <b>나라</b>를 세워라.</div>
      <button class="big main" id="start">탐험 시작</button>
      ${resumable && !resumable.s.ended ? `<button class="ghost" id="resume">이어하기 · ${resumable.s.day}일째 · 부족 ${resumable.integratedCount()}/4</button>` : ""}
      <p class="disclaimer">${esc(data.disclaimer)}</p></section>`;
    app.querySelector("#start").onclick = () => {
      storage.del(saveKey);
      game = new Explore(data, { BoardGame });
      stats.start(!!resumable);
      last = { title: "어디로 가 볼까?", text: "🔍 둘러보기로 주변을 살피거나, 아래 길을 골라 떠나라. 소리와 냄새가 무엇이 있는지 알려 준다." };
      save();
      render();
    };
    const r = app.querySelector("#resume");
    if (r) r.onclick = () => { game = resumable; last = null; render(); };
    app.querySelector("#start").focus({ preventScroll: true });
  }

  // ---- 공통 ----
  function hud() {
    const st = game.rpg.state, li = game.rpg.levelInfo();
    const party = st.companions.map((id) => `<span title="${esc(byId("heroes", id).name)}">${byId("heroes", id).icon}</span>`).join("");
    const res = ["food", "population", "reputation", "copper"].map((k) => `<div class="stat"><div class="k">${lab(k)[1]} ${lab(k)[0]}</div><div class="v">${st.stats[k]}</div></div>`).join("");
    return `<div class="sticky"><div class="top"><span><b>Lv ${li.level}</b> · ${game.s.day}일째 · 부족 ${game.integratedCount()}/4</span><span class="party">${party}</span></div>
      <div class="xp" role="progressbar" aria-label="경험치" aria-valuenow="${li.exp}"><i style="width:${Math.round(li.progress * 100)}%"></i><span>EXP ${li.exp}${li.next ? ` / ${li.next}` : ""}</span></div>
      <div class="hud" role="group" aria-label="자원">${res}</div>
      <div class="tabs"><button class="tab${tab === "play" ? " on" : ""}" id="t_play">🗺️ 탐험</button><button class="tab${tab === "book" ? " on" : ""}" id="t_book">📖 기록</button></div></div>`;
  }
  function mapHtml() {
    const cells = [];
    const view = Object.fromEntries(game.mapView().map((v) => [`${v.loc.x},${v.loc.y}`, v]));
    for (let y = 0; y < 4; y++) for (let x = 0; x < 5; x++) {
      const v = view[`${x},${y}`];
      if (!v) { cells.push(`<div class="mc fog" aria-hidden="true"></div>`); continue; }
      const tr = v.loc.tribe ? game.s.tribes[v.loc.tribe] : null;
      const mark = tr && tr.status === "integrated" ? `<i class="flagm">${tr.method === "union" ? "🤝" : "⚔️"}</i>` : "";
      cells.push(`<div class="mc${v.here ? " here" : ""}${v.visited ? "" : " unknown"}" title="${esc(v.visited ? v.loc.name : "가 보지 않은 곳")}" aria-label="${esc(v.visited ? v.loc.name : "가 보지 않은 곳")}${v.here ? " (현재 위치)" : ""}">
        <span>${v.here ? "🧍" : v.visited ? v.loc.icon : "❓"}</span><small>${v.visited ? esc(v.loc.name.split(" ").slice(-1)[0]) : ""}</small>${mark}</div>`);
    }
    return `<div class="map" role="img" aria-label="지도: 가 본 곳 ${game.s.visited.length}/12">${cells.join("")}</div>`;
  }
  function gainedHtml(r) {
    if (!r) return "";
    const g = r.gained || {};
    const chips = [];
    if (g.exp) chips.push(`<span class="chip good">✨ EXP +${g.exp}</span>`);
    for (const [k, v] of Object.entries(g.stats || {})) if (v) chips.push(`<span class="chip ${v > 0 ? "good" : "bad"}">${lab(k)[1]} ${lab(k)[0]} ${v > 0 ? "+" : ""}${v}</span>`);
    for (const i of g.items || []) chips.push(`<span class="chip item">${byId("items", i).icon} ${esc(byId("items", i).name)}</span>`);
    for (const s of g.skills || []) chips.push(`<span class="chip skill">${byId("skills", s).icon} 어빌리티: ${esc(byId("skills", s).name)}</span>`);
    for (const p of g.policies || []) chips.push(`<span class="chip policy">📜 ${esc(byId("policies", p).name)}</span>`);
    for (const [t, n] of Object.entries(r.trust || {})) if (n) chips.push(`<span class="chip ${n > 0 ? "good" : "bad"}">${game.T[t].icon} 신뢰 ${n > 0 ? "+" : ""}${n}</span>`);
    if (r.companion) chips.push(`<span class="chip skill">${byId("heroes", r.companion).icon} 동료: ${esc(byId("heroes", r.companion).name)}</span>`);
    const lv = (g.level_up || []).map((l) => `<div class="levelup pop">⬆️ 레벨 업! Lv ${l}</div>`).join("");
    const kn = (g.knowledge || []).map((k) => { const x = byId("knowledge", k); return `<div class="lesson">📚 ${esc(x.text)} ${badge(x.historical_status)}${x.historical_status === "game_setting" ? "" : `<span class="src">출처: ${esc(x.source)} (${esc(x.source_date)} 확인)</span>`}</div>`; }).join("");
    const rv = (r.revealed || []).map((id) => `<div class="newpath">🛤️ 새 길이 열렸다: ${esc(edgeName(id))}</div>`).join("");
    const hunger = r.hunger ? `<div class="warn">😣 식량 없이 걸었다. 인구가 줄었다.</div>` : "";
    return `${lv}${hunger}<div class="chips">${chips.join("")}</div>${rv}${kn}`;
  }
  function lastHtml() {
    if (!last) return "";
    return `<section class="card last pop">${last.title ? `<div class="chapter">${esc(last.title)}</div>` : ""}<div>${esc(last.text || "")} ${badge(last.hs)}</div>
      ${last.source ? `<span class="src">출처: ${esc(last.source)}</span>` : ""}${last.lesson ? `<div class="lesson">📜 ${esc(last.lesson)}</div>` : ""}${gainedHtml(last.r)}</section>`;
  }
  function screen(body) {
    app.innerHTML = `${hud()}${body}<div class="foot"><button id="about" aria-expanded="false">이 게임에 대해</button> · <button id="home">처음 화면</button><div id="aboutText" class="hidden">${esc(data.disclaimer)}</div></div>`;
    app.querySelector("#t_play").onclick = () => { tab = "play"; render(); };
    app.querySelector("#t_book").onclick = () => { tab = "book"; render(); };
    app.querySelector("#home").onclick = renderTitle;
    const a = app.querySelector("#about");
    a.onclick = () => { const t = app.querySelector("#aboutText"); t.classList.toggle("hidden"); a.setAttribute("aria-expanded", String(!t.classList.contains("hidden"))); };
    const f = app.querySelector("#main .opt:not([disabled]), #main .act:not([disabled])");
    if (f && !("ontouchstart" in window)) f.focus({ preventScroll: true });
  }
  function act(fn, logName, extra) {
    try {
      const r = fn();
      if (logName) stats.log(logName, extra || {});
      for (const l of (r && r.gained && r.gained.level_up) || []) stats.log("level_up", { level: l });
      save();
      return r;
    } catch (e) {
      last = { title: "잠깐", text: e.message };
      return null;
    } finally { render(); }
  }

  // ---- 본 화면 ----
  function render() {
    if (game.s.ended) return renderEnding();
    if (tab === "book") return renderBook();
    if (game.s.mini) return renderMini();
    if (game.event()) return renderEvent();
    const here = game.L[game.s.loc];
    const si = game.searchInfo(), gi = game.gatherInfo();
    const acts = [];
    acts.push(`<button class="act" id="a_search"${si.left && !si.locked ? "" : " disabled"}>🔍 둘러보기${si.left ? ` <small>${si.locked ? esc(si.locked) : `남은 발견 ${si.left}`}</small>` : " <small>더 찾을 것이 없다</small>"}</button>`);
    if (gi) acts.push(`<button class="act" id="a_gather"${gi.ok ? "" : " disabled"}>🧺 채집 · ${lab(gi.gather.stat)[1]} ${lab(gi.gather.stat)[0]}${gi.gather.bonus && game.meets(gi.gather.bonus.requires) ? " (어빌리티 보너스)" : ""} <small>${gi.ok ? (gi.left === Infinity ? "언제든" : `${gi.left}번 남음`) : esc(gi.why || "다 캤다")}</small></button>`);
    for (const m of game.minigames()) acts.push(`<button class="act mg" data-mg="${m.mg.id}"${m.ok ? "" : " disabled"}>${m.mg.icon} 미니게임: ${esc(m.mg.name)}${m.won ? " ✓" : ""} <small>${m.ok ? esc(m.mg.desc) : esc(m.why)}</small></button>`);
    const tribe = here.tribe ? tribeHtml(here.tribe) : "";
    const dir = (to) => { const dx = to.x - here.x, dy = to.y - here.y; return (dy < 0 ? "⬆ 북" : dy > 0 ? "⬇ 남" : "") + (dx < 0 ? (dy ? "서" : "⬅ 서") : dx > 0 ? (dy ? "동" : "➡ 동") : "") + "쪽"; };
    const exits = game.exits().map((e) => `<button class="opt ex" data-to="${e.to.id}"${e.ok ? "" : " disabled"}>${dir(e.to)} · ${e.visited ? `${e.to.icon} ${esc(e.to.name)}` : `❓ ${esc(e.to.teaser || "가 보지 않은 곳")}`}
        <small>${e.ok ? `식량 ${e.edge.food || 0}${e.hungry ? " — 😣 식량이 모자라 인구가 줄어든다" : ""}` : "🔒 " + esc(e.why)}</small></button>`).join("");
    screen(`${mapHtml()}<div id="main">${lastHtml()}
      <section class="card"><div class="chapter">${here.icon} ${esc(here.name)} ${badge(here.historical_status)}</div><div class="flow">${esc(here.desc)}</div><div class="acts">${acts.join("")}</div></section>
      ${tribe}<section class="card"><div class="chapter">🛤️ 길</div><div class="opts">${exits}</div></section></div>`);
    const s = app.querySelector("#a_search");
    if (s) s.onclick = () => { const r = act(() => game.search(), "search", { loc: here.id }); if (r) last = { title: `🔍 ${here.name}`, text: r.text, hs: r.historical_status, source: r.source, r }; render(); };
    const gth = app.querySelector("#a_gather");
    if (gth) gth.onclick = () => { const r = act(() => game.gather(), "gather", { loc: here.id }); if (r) last = { title: "🧺 채집", text: r.text + (r.bonus ? " (어빌리티 덕에 더 얻었다)" : ""), r }; render(); };
    app.querySelectorAll(".mg").forEach((b) => (b.onclick = () => { act(() => game.startMini(b.dataset.mg), "minigame_start", { id: b.dataset.mg }); boardLog = []; last = null; render(); }));
    app.querySelectorAll(".ex").forEach((b) => (b.onclick = () => {
      const r = act(() => game.travel(b.dataset.to), "travel", { to: b.dataset.to });
      if (r) {
        const l = game.L[b.dataset.to];
        if (r.first) stats.log("discover", { loc: l.id });
        last = { title: `${r.first ? "✨ 새 장소 발견! " : ""}${l.icon} ${l.name}`, text: l.desc, hs: l.historical_status, r: { ...(r.arrive || {}), gained: r.gained || (r.arrive || {}).gained, hunger: r.hunger } };
        if (game.event() && game.L[b.dataset.to].tribe && game.s.tribes[game.L[b.dataset.to].tribe].status === "met") stats.log("tribe_meet", { tribe: game.L[b.dataset.to].tribe });
      }
      render();
      window.scrollTo({ top: 0 });
    }));
    bindTribe();
  }

  function tribeHtml(id) {
    const v = game.tribeView(id);
    const t = v.tribe;
    if (v.state.status === "unknown") return "";
    if (v.state.status === "integrated") return `<section class="card tribe done"><b>${t.icon} ${esc(t.name)}</b> — ${v.state.method === "union" ? "🤝 연합으로 함께한다" : "⚔️ 복속되었다"}</section>`;
    const need = t.union.trust;
    const bar = `<div class="trust" aria-label="신뢰 ${v.state.trust}/${need}"><i style="width:${Math.max(0, Math.min(100, (v.state.trust / need) * 100))}%"></i><span>신뢰 ${v.state.trust} / ${need}</span></div>`;
    const reqs = v.requests.map((r) => `<div class="req${r.done ? " ok" : ""}">${r.done ? "✅" : "⬜"} ${esc(r.req.text)}
        ${r.done ? "" : r.ok ? `<button class="small do" data-req="${r.req.id}">하기</button>` : r.offer ? `<button class="small offer" data-req="${r.req.id}">다시 돕기</button>${r.req.how ? `<small>${esc(r.req.how)}</small>` : ""}` : `<small>${esc(r.req.how || r.why)}</small>`}</div>`).join("");
    const gi = game.giftInfo(id);
    return `<section class="card tribe"><div class="chapter">${t.icon} ${esc(t.name)} ${badge(t.historical_status)}</div><div class="flow">${esc(t.desc)} · ${esc(t.trait)}</div>${bar}
      <div class="reqs">${reqs}</div>
      <div class="acts"><button class="act" id="a_gift" data-t="${id}"${gi.ok ? "" : " disabled"}>🎁 선물 (${lab(gi.stat)[0]} ${gi.amount} → 신뢰 +${gi.trust})</button>
      <button class="act primary" id="a_union" data-t="${id}"${v.union.ok ? "" : " disabled"}>🤝 연합하기 <small>${v.union.ok ? "함께하자고 손을 내민다" : `신뢰 ${need}·요청 해결 필요`}</small></button>
      ${v.force ? `<button class="act danger" id="a_force" data-t="${id}"${v.force.ok ? "" : " disabled"}>⚔️ 복속시키기 <small>${v.force.ok ? "명성이 크게 떨어진다" : esc(v.force.why || "위협한 적이 있어야 한다")}</small></button>` : ""}</div></section>`;
  }
  function bindTribe() {
    app.querySelectorAll(".do").forEach((b) => (b.onclick = () => { const tid = game.L[game.s.loc].tribe; const r = act(() => game.fulfill(tid, b.dataset.req), "tribe_request", { tribe: tid }); if (r) last = { title: "✅ 요청 해결", text: r.text, r }; render(); }));
    app.querySelectorAll(".offer").forEach((b) => (b.onclick = () => { const tid = game.L[game.s.loc].tribe; act(() => game.offer(tid, b.dataset.req)); last = null; render(); }));
    const g = app.querySelector("#a_gift");
    if (g) g.onclick = () => { const r = act(() => game.gift(g.dataset.t), "tribe_gift", { tribe: g.dataset.t }); if (r) last = { title: "🎁 선물", text: r.text, r }; render(); };
    for (const [sel, method] of [["#a_union", "union"], ["#a_force", "force"]]) {
      const b = app.querySelector(sel);
      if (b) b.onclick = () => { const r = act(() => game.integrate(b.dataset.t, method), "tribe_integrate", { tribe: b.dataset.t, method }); if (r) last = { title: method === "union" ? "🤝 부족 연합!" : "⚔️ 부족 복속", text: r.text, r }; render(); };
    }
  }

  // ---- 사건 ----
  function renderEvent() {
    const v = game.event();
    const opts = game.eventOptions().map((o, i) => `<button class="opt ch" data-c="${o.choice.id}"${o.ok ? "" : " disabled"}><span class="no">${i + 1}</span>${esc(o.choice.text)}${o.ok ? "" : `<small>${esc(o.why)}</small>`}</button>`).join("");
    screen(`${mapHtml()}<div id="main">${lastHtml()}<section class="card event pop"><div class="chapter">❗ ${esc(v.title)} ${badge(v.historical_status)}</div><p class="line">${esc(v.text)}</p>
      <div class="opts" role="group" aria-label="선택 (키보드 1~4)">${opts}</div></section></div>`);
    app.querySelectorAll(".ch").forEach((b) => (b.onclick = () => {
      const r = act(() => game.choose(b.dataset.c), "event_choice", { event: v.id, choice: b.dataset.c });
      if (r) last = { title: `${v.title} → ${v.choices.find((c) => c.id === b.dataset.c).text}`, text: r.result, hs: r.historical_status, lesson: r.lesson, r };
      if (game.s.ended) stats.log("ending", { ending: game.s.ended.ending });
      render();
    }));
  }

  // ---- 미니게임 ----
  function renderMini() {
    const mi = game.s.mini;
    const m = game.M[mi.id];
    if (m.type === "board") return renderBoardMini(m);
    const st = game.miniStep();
    const opts = st.step.options.map((o, i) => `<button class="opt pk" data-i="${i}"><span class="no">${i + 1}</span>${esc(o.text)}</button>`).join("");
    screen(`<div id="main">${lastHtml()}<section class="card event pop"><div class="chapter">${m.icon} ${esc(m.name)} · ${st.index + 1}/${st.total} (${m.pass}개 이상 맞히면 성공)</div>
      <p class="line">${esc(st.step.prompt)}</p>${st.hint ? `<div class="hint">💡 ${esc(st.hint)}</div>` : `<div class="flow">알고 있는 것이 있다면 힌트가 보인다.</div>`}<div class="opts">${opts}</div></section></div>`);
    app.querySelectorAll(".pk").forEach((b) => (b.onclick = () => {
      const r = act(() => game.miniAnswer(+b.dataset.i));
      if (!r) return;
      last = { title: `${m.icon} ${m.name}`, text: `${r.correct ? "⭕" : "❌"} ${r.feedback}${r.done ? ` — ${r.result.text}` : ""}`, r: r.done ? r.result : null };
      if (r.done) stats.log("minigame", { id: m.id, win: r.result.win });
      render();
    }));
  }
  function renderBoardMini(m) {
    const b = game.boardGame();
    const st = b.state, v = st.vars;
    const tiles = b.data.board.map((c, i) => `<div class="tile${i === st.pos ? " here" : ""}${st.phase === "steer" && b.steerOptions().some((o) => (st.pos + o.steps) % b.data.board.length === i) ? " target" : ""}" title="${esc(c.name)}"><span>${i === st.pos ? "🧍" : c.icon}</span></div>`).join("");
    let stage = "";
    if (st.phase === "quiz") { const q = b.quiz(); stage = `<div class="chapter">❓ 퀴즈 — 맞히면 🎲 주사위 특권</div><p class="line">${esc(q.question)}</p><div class="opts">${q.choices.map((c, i) => `<button class="opt" data-ba="${i}"><span class="no">${i + 1}</span>${esc(c)}</button>`).join("")}</div>`; }
    else if (st.phase === "parity") stage = `<b>🎲 주사위 특권!</b><div class="flow">홀짝을 선언(적중 3/6) — 맞으면 도착 칸을 고른다.</div><div class="opts two"><button class="opt" data-bp="odd"><span class="no">1</span>홀수 1·3·5</button><button class="opt" data-bp="even"><span class="no">2</span>짝수 2·4·6</button></div>`;
    else if (st.phase === "roll") stage = `<button class="big main" id="broll">🎲 주사위 굴리기</button>`;
    else if (st.phase === "steer") stage = `<b>🧭 적중! 도착 칸 선택</b><div class="opts">${b.steerOptions().map((o, i) => `<button class="opt" data-bs="${o.steps}"><span class="no">${i + 1}</span>${o.cell.icon} ${esc(o.cell.name)} <small>${o.steps}칸</small></button>`).join("")}</div>`;
    else if (st.phase === "cell") {
      const c = b.cell();
      if (c.type === "QUIZ") { const q = b.cellQuiz(); stage = `<div class="chapter">${c.icon} ${esc(c.name)}</div><p class="line">${esc(q.question)}</p><div class="opts">${q.choices.map((x, i) => `<button class="opt" data-bq="${i}"><span class="no">${i + 1}</span>${esc(x)}</button>`).join("")}</div>`; }
      else stage = `<div class="chapter">${c.icon} ${esc(c.name)}</div><div class="opts">${b.cellOptions().map((o, i) => `<button class="opt" data-bc="${esc(o.choice.id)}"${o.enabled ? "" : " disabled"}><span class="no">${i + 1}</span>${esc(o.choice.text)}${o.enabled ? "" : `<small>${esc(o.reason)}</small>`}</button>`).join("")}</div>`;
    } else if (st.phase === "turn_end") stage = `<button class="big main" id="bdone">사냥 마치기 ▶</button>`;
    screen(`<div id="main"><section class="card event"><div class="chapter">${m.icon} ${esc(m.name)} — ${esc(m.desc)}</div>
      <div class="bhud">🍖 ${v.coin} · 📚 ${v.knowledge} · 🦌 ${v.exploration}</div><div class="bmap">${tiles}</div>${boardLog.map((x) => `<div class="blog">${x}</div>`).join("")}${stage}</section></div>`);
    const B = (sel, fn) => app.querySelectorAll(sel).forEach((el) => (el.onclick = () => { fn(el); render(); }));
    B("#main .opt[data-ba]", (el) => { const q = b.quiz(); const r = b.answer(+el.dataset.ba); boardLog.push(`${r.correct ? "⭕ 정답 → 🎲 특권" : `❌ 오답(정답: ${esc(q.choices[q.correct])})`} <span class="flow">${esc(r.explanation)} (출처: ${esc(q.source)})</span>`); });
    B("#main .opt[data-bp]", (el) => roll(el.dataset.bp));
    B("#main .opt[data-bs]", (el) => { b.steerTo(+el.dataset.bs); boardLog.push(`🧭 → ${b.cell().icon} ${esc(b.cell().name)}`); auto(); });
    B("#main .opt[data-bq]", (el) => { const q = b.cellQuiz(); const r = b.answerCellQuiz(+el.dataset.bq); boardLog.push(`${r.correct ? "⭕" : "❌"} ${esc(q.choices[q.correct])}`); });
    B("#main .opt[data-bc]:not([disabled])", (el) => { const r = b.act(el.dataset.bc); boardLog.push(esc(r.result_text || "")); });
    const br = app.querySelector("#broll");
    if (br) br.onclick = () => { roll(null); render(); };
    const bd = app.querySelector("#bdone");
    if (bd) bd.onclick = () => {
      b.nextTurn();
      const r = act(() => game.finishBoardMini());
      if (r) { stats.log("minigame", { id: m.id, win: r.win }); last = { title: `${m.icon} ${m.name}`, text: r.text, r: { ...r, gained: mergeGains(r.merged, r.gained) } }; }
      boardLog = [];
      render();
    };
    function roll(p) {
      const r = p ? b.declare(p) : b.roll();
      if (p) stats.log("dice_parity_selected", { parity: p });
      stats.log("dice_result", { roll: r.roll, hit: r.hit === null ? "none" : r.hit });
      boardLog.push(`🎲 ${FACES[r.roll - 1]} ${r.roll} · ${p ? (r.hit ? "적중!" : "빗나감") : "특권 없음"}${b.state.phase !== "steer" ? ` → ${b.cell().icon} ${esc(b.cell().name)}` : ""}`);
      if (b.state.phase !== "steer") auto();
    }
    function auto() { const r = b.state.cell_result; if (b.state.phase === "turn_end" && r && r.auto) boardLog.push(esc(b.cell().event_text || "")); }
  }
  function mergeGains(a, b) {
    const s = { ...(a.stats || {}) };
    for (const [k, v] of Object.entries((b && b.stats) || {})) s[k] = (s[k] || 0) + v;
    return { exp: (a.exp || 0) + ((b && b.exp) || 0), stats: s, level_up: [...(a.level_up || []), ...((b && b.level_up) || [])] };
  }

  // ---- 기록(도감) ----
  function renderBook() {
    const st = game.rpg.state;
    const kn = st.knowledge.map((k) => { const x = byId("knowledge", k); return `<div class="lesson">${esc(x.text)} ${badge(x.historical_status)}${x.historical_status === "game_setting" ? "" : `<span class="src">${esc(x.source)}</span>`}</div>`; }).join("") || `<p class="flow">아직 없다. 둘러보고 부족과 이야기하라.</p>`;
    const tr = data.explore.tribes.map((t) => { const s = game.s.tribes[t.id]; return `<div class="req">${t.icon} ${s.status === "unknown" ? "❓ 아직 모르는 부족" : esc(t.name)} — ${s.status === "integrated" ? (s.method === "union" ? "🤝 연합" : "⚔️ 복속") : s.status === "met" ? `신뢰 ${s.trust}/${t.union.trust}` : "만나지 않음"}</div>`; }).join("");
    const ab = st.skills.map((s) => `<div class="req">${byId("skills", s).icon} <b>${esc(byId("skills", s).name)}</b> — ${esc(byId("skills", s).desc)}</div>`).join("") || `<p class="flow">부족과 연합하면 새 어빌리티를 얻는다.</p>`;
    const it = st.items.map((i) => `<div class="req">${byId("items", i).icon} ${esc(byId("items", i).name)} <span class="flow">${esc(byId("items", i).note)}</span></div>`).join("") || `<p class="flow">없음</p>`;
    screen(`<div id="main"><section class="card"><div class="chapter">🧭 부족</div>${tr}</section>
      <section class="card"><div class="chapter">✨ 어빌리티</div>${ab}</section><section class="card"><div class="chapter">🎒 아이템</div>${it}</section>
      <section class="card"><div class="chapter">📚 알게 된 것 (${st.knowledge.length})</div>${kn}</section>
      <section class="card"><div class="chapter">🗺️ 발견한 장소 ${game.s.visited.length}/12</div><div class="flow">${game.s.visited.map((l) => game.L[l].icon + " " + esc(game.L[l].name)).join(" · ")}</div></section></div>`);
  }

  // ---- 엔딩 ----
  function renderEnding() {
    const e = game.s.ended;
    const st = game.rpg.state;
    const lawText = { death: "살인은 목숨으로 갚는다", exile: "살인자는 쫓아낸다", grain: "상해는 곡식으로 갚는다", labor: "상해는 일로 갚는다", slave: "도둑은 노비로, 값을 치르면 풀어 준다", multiple: "도둑은 몇 배로 갚는다", forgive: "도둑도 한 번은 용서한다" };
    const ideal = game.s.choices.find((c) => c.startsWith("ev_found."));
    const idealText = { hongik: "사람을 널리 이롭게 하는 나라", strong: "강한 나라", full: "아무도 굶지 않는 나라" }[(ideal || "").split(".")[1]] || "-";
    const nameChoice = game.s.choices.find((c) => c.startsWith("ev_council."));
    const ep = data.explore.ending.epilogue;
    screen(`<div id="main"><section class="card pop"><div class="big-icon center">${e.icon}</div><h2 class="q center">${esc(e.title)}</h2><p class="center">${esc(e.text)}</p>
      <h3 class="sub-h">🏛️ 내가 만든 나라</h3>
      <div class="rows"><div>나라 이름</div><div>${nameChoice && nameChoice.endsWith("joseon") ? "조선" : "우리가 지은 이름"}</div>
        <div>이념</div><div>${esc(idealText)}</div>
        <div>함께한 부족</div><div>${e.tribes.filter((t) => t.status === "integrated").map((t) => `${t.icon} ${esc(t.name)} ${t.method === "union" ? "🤝" : "⚔️"}`).join("<br>") || "-"}</div>
        <div>법</div><div>${e.laws.map((l) => esc(lawText[l] || l)).join("<br>")}</div>
        <div>발견한 땅</div><div>${e.vals.places}/12</div><div>알게 된 것</div><div>${e.vals.knowledge}</div>
        <div>인구 · 명성</div><div>${e.vals.population} · ${e.vals.reputation}</div><div>레벨</div><div>Lv ${e.level} · ${e.days}일</div>
        <div>동료</div><div>${st.companions.map((c) => byId("heroes", c).icon + " " + esc(byId("heroes", c).name)).join(", ") || "-"}</div></div>
      <div class="lesson">📜 ${esc(ep.text)} ${badge(ep.historical_status)}<span class="src">${ep.sources.map(esc).join(" · ")}</span></div>
      <button class="big main" id="again">다른 길로 다시 세우기 ↻</button></section></div>`);
    app.querySelector("#again").onclick = () => { storage.del(saveKey); game = new Explore(data, { BoardGame }); stats.start(true); last = null; save(); render(); };
    if (!game.s.recorded) {
      game.s.recorded = true;
      stats.complete({ choice_count: game.s.actions, ending: e.ending, style: null, metrics: { tribes: e.vals.tribes, union: e.vals.union, force: e.vals.force, places: e.vals.places, knowledge: e.vals.knowledge, days: e.days, level: e.level } });
      save();
    }
  }

  function onKey(ev) {
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const n = Number(ev.key);
    if (n >= 1 && n <= 4) {
      const b = app.querySelectorAll("#main .opt:not(.ex)")[n - 1];
      if (b && !b.disabled) { ev.preventDefault(); b.click(); }
      return;
    }
    const idle = !document.activeElement || document.activeElement === document.body;
    if (ev.key === "Enter" && idle) { const m = app.querySelector("#main .main, #start"); if (m) { ev.preventDefault(); m.click(); } }
  }

  // 플레이테스트 도구용(읽기 전용으로 쓴다): 현재 게임 상태를 돌려준다
  window.Choice100ExploreRenderer = { boot, debugGame: () => game };
})();
