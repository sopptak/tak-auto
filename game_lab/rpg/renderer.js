/*
 * CHOICE100 RPG 화면(6-67 Vertical Slice) - 타이틀 → 메인 1 → 시간의 문 → 영웅 선택 → 주몽 이야기(퀴즈·보상·보드·동료·지역) → 장 완료 → 지역 지도.
 * 규칙은 engine.js(RPG) + ../board/engine.js(보드 한 턴). 기록은 ../choice100/analytics.js(이 브라우저만).
 */
(function () {
  "use strict";
  const { Game } = window.Choice100Rpg;
  const BoardGame = window.Choice100Board.Game;
  const reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const FACES = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];
  const REL_LABEL = { FRIEND: "친구", COMPANION: "동료", MENTOR: "스승", RIVAL: "라이벌", ALLY: "동맹", NEUTRAL: "중립" };
  const ROLE_LABEL = { warrior: "전사", founder: "건국자", ruler: "군주", scholar: "학자", admiral: "제독", strategist: "전략가", merchant: "상인" };
  const REL_ICON = { FRIEND: "🤝", COMPANION: "🏹", MENTOR: "🧑‍🏫", RIVAL: "⚔️", ALLY: "🤝", NEUTRAL: "·" };

  let app, data, game, stats, saveKey, pending = null, boardLog = [];

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const storage = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 저장 불가 */ } },
    del(k) { try { window.localStorage.removeItem(k); } catch (e) { /* 무시 */ } },
  };
  const save = () => storage.set(saveKey, game.serialize());
  const badge = (hs) => hs ? `<span class="hs hs-${hs}">${esc(data.historical_status_labels[hs])}</span>` : "";
  const statLabel = (k) => data.stat_labels[k] || [k, ""];
  const item = (id) => data.items.find((x) => x.id === id);
  const skill = (id) => data.skills.find((x) => x.id === id);
  const hero = (id) => data.heroes.find((x) => x.id === id) || (data.npcs || []).find((x) => x.id === id);
  const know = (id) => data.knowledge.find((x) => x.id === id);

  async function boot(root, url) {
    app = root;
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
    } catch (e) {
      app.innerHTML = `<div class="card">데이터를 불러오지 못했습니다. <code>py -m http.server 8790 --bind 127.0.0.1 -d game_lab</code> 후 http://127.0.0.1:8790/rpg/korea/</div>`;
      return;
    }
    saveKey = `choice100rpg:${data.id}`;
    stats = window.Choice100Analytics.create(storage, data.id, data.version);
    document.addEventListener("keydown", onKey);
    renderTitle();
  }

  // ---- 공통 조각 ----
  function hud() {
    const li = game.levelInfo();
    const s = game.state.stats;
    const party = game.state.companions.map((id) => `<span title="${esc(hero(id).name)}">${hero(id).icon || "🧑"}</span>`).join("") || `<span class="flow">동료 없음</span>`;
    const cells = ["military", "admin", "food", "lore"].map((k) => `<div class="stat" data-k="${k}"><div class="k">${statLabel(k)[1]} ${statLabel(k)[0]}</div><div class="v">${s[k]}</div></div>`).join("");
    return `<div class="sticky"><div class="top"><span><b>Lv ${li.level}</b> ${esc(data.player.name)}</span><span class="party">🧑 ${party}</span></div>
      <div class="xp" role="progressbar" aria-label="경험치" aria-valuenow="${li.exp}" aria-valuemin="${li.cur}" aria-valuemax="${li.next ?? li.exp}"><i style="width:${Math.round(li.progress * 100)}%"></i><span>EXP ${li.exp}${li.next ? ` / ${li.next}` : ""}</span></div>
      <div class="hud" role="group" aria-label="능력치">${cells}</div></div>`;
  }
  function gainedHtml(g) {
    if (!g) return "";
    const out = [];
    if (g.exp) out.push(`<span class="chip good">✨ EXP +${g.exp}</span>`);
    for (const [k, v] of Object.entries(g.stats || {})) if (v) out.push(`<span class="chip ${v > 0 ? "good" : "bad"}">${statLabel(k)[1]} ${statLabel(k)[0]} ${v > 0 ? "+" : ""}${v}</span>`);
    for (const it of g.items || []) out.push(`<span class="chip item">${item(it).icon} ${esc(item(it).name)}</span>`);
    for (const sk of g.skills || []) out.push(`<span class="chip skill">${skill(sk).icon} 스킬: ${esc(skill(sk).name)}</span>`);
    for (const k of g.knowledge || []) out.push(`<span class="chip know">📚 지식 획득</span>`);
    for (const p of g.policies || []) out.push(`<span class="chip policy">🌾 정책 해금: ${esc(data.policies.find((x) => x.id === p).name)}</span>`);
    const lv = (g.level_up || []).map((l) => `<div class="levelup pop">⬆️ 레벨 업! Lv ${l}</div>`).join("");
    const kn = (g.knowledge || []).map((k) => `<div class="lesson">📚 ${esc(know(k).text)} ${badge(know(k).historical_status)}<span class="src">출처: ${esc(know(k).source)} (${esc(know(k).source_date)} 확인)</span></div>`).join("");
    return `${lv}<div class="chips">${out.join("")}</div>${kn}`;
  }
  function screen(body, withHud = true) {
    app.innerHTML = `${withHud && game ? hud() : ""}<div id="main">${body}</div>${foot()}`;
    bindFoot();
    const f = app.querySelector("#main .opt:not([disabled]), #main .main");
    if (f && !("ontouchstart" in window)) f.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }
  function foot() {
    return `<div class="foot"><button id="about" aria-expanded="false">이 게임에 대해</button> · <button id="map">지역 지도</button> · <button id="home">처음 화면</button>
      <div id="aboutText" class="hidden">${esc(data.disclaimer)}</div></div>`;
  }
  function bindFoot() {
    const a = app.querySelector("#about"), h = app.querySelector("#home"), m = app.querySelector("#map");
    if (a) a.onclick = () => { const t = app.querySelector("#aboutText"); t.classList.toggle("hidden"); a.setAttribute("aria-expanded", String(!t.classList.contains("hidden"))); };
    if (h) h.onclick = renderTitle;
    if (m) m.onclick = () => (game ? renderMap() : null);
  }

  // ---- 타이틀·메인·시간의 문 ----
  function renderTitle() {
    const saved = storage.get(saveKey);
    const resumable = saved ? Game.restore(data, saved, { BoardGame }) : null;
    app.innerHTML = `<section class="title-screen pop"><div class="flag" aria-hidden="true">🗺️</div>
      <h1 class="logo">${esc(data.title)}<small>${esc(data.subtitle)}</small></h1>
      <p class="hook">${esc(data.tagline)}</p>
      <button class="big main" id="start">게임 시작</button>
      ${resumable ? `<button class="ghost" id="resume">이어하기 · Lv ${resumable.state.level}</button>` : ""}
      <p class="disclaimer">${esc(data.disclaimer)}</p></section>`;
    app.querySelector("#start").onclick = () => {
      storage.del(saveKey);
      game = new Game(data, { BoardGame });
      stats.start(!!resumable);
      save();
      renderMain1();
    };
    const r = app.querySelector("#resume");
    if (r) r.onclick = () => { game = resumable; game.state.current ? renderStory() : renderHeroSelect(); };
    app.querySelector("#start").focus({ preventScroll: true });
  }

  function renderMain1() {
    const m = data.main_story[0];
    screen(`<section class="card story pop"><div class="chapter">📖 MAIN 1 · ${esc(m.title)} ${badge(m.historical_status)}</div>
      <p class="line"><b>${esc(data.player.name)}</b>: 오래된 서고 깊은 곳, 먼지 쌓인 책 사이에서 빛이 새어 나온다. 문이다. 손을 대자 글자들이 과거의 이름을 속삭인다.</p>
      <p class="flow">당신은 탁멍. 시간의 흐름을 여행하며 영웅들을 만나고, 지식과 능력을 얻어 자신만의 나라를 키운다.</p>
      <button class="big main" id="go">시간의 문으로 ▶</button></section>`);
    app.querySelector("#go").onclick = () => { game.completeMain("m1"); save(); renderGate(); };
  }

  function renderGate() {
    const g = data.time_gates[0];
    const r = data.regions.find((x) => x.id === g.to_region);
    screen(`<section class="card gate pop"><div class="gate-ring" aria-hidden="true">🌀</div><h2 class="q">${esc(g.name)}</h2>
      <p>${esc(g.era)} · ${esc(r.name)} ${badge(g.historical_status)}</p><p class="flow">${esc(r.desc || "")}</p>
      <p class="flow">시간의 문은 게임 설정입니다. 역사 속 시대 순서와 상관없이 영웅의 이야기를 골라 들어갈 수 있습니다.</p>
      <button class="big main" id="enter">문을 지난다 ▶</button></section>`);
    app.querySelector("#enter").onclick = () => { game.passGate(g.id); save(); renderHeroSelect(); };
  }

  // ---- 영웅 선택 ----
  function renderHeroSelect(preview) {
    const cards = game.heroCards().map(({ hero: h, playable, reason, done, companion }) => `
      <button class="hero${playable ? "" : " locked"}${preview === h.id ? " open" : ""}" data-h="${h.id}" aria-label="${esc(h.name)} ${playable ? "플레이 가능" : "잠김: " + esc(reason)}">
        <span class="hi">${h.icon}</span><b>${playable ? "" : "🔒 "}${esc(h.name)}</b><small>${esc(h.era)}</small>
        <span class="tag">${esc(h.tagline)}</span><span class="style">${(h.style || []).map((s) => `<i>${esc(s)}</i>`).join("")}</span>
        ${done ? `<span class="done">✓ 1장 완료</span>` : playable ? `<span class="play">PLAY</span>` : `<span class="lock">${esc(reason)}</span>`}${companion ? `<span class="done">동료</span>` : ""}</button>`).join("");
    const p = preview && data.heroes.find((h) => h.id === preview);
    const pv = p ? `<div class="card preview pop"><b>${p.icon} ${esc(p.name)} · 미리보기</b><div class="flow">${esc(p.tagline)} · 역할 ${p.role.map((r) => esc(ROLE_LABEL[r] || r)).join(" / ")}</div>
        <div class="chips">${p.skills.map((s) => `<span class="chip skill">${skill(s).icon} ${esc(skill(s).name)}</span>`).join("")}${p.items.map((i) => `<span class="chip item">${item(i).icon} ${esc(item(i).name)}</span>`).join("")}
        ${p.relationships.map((r) => `<span class="chip">${REL_ICON[r.type]} 탁멍과 ${REL_LABEL[r.type]}</span>`).join("")}</div>
        <div class="flow">🔒 ${esc(p.locked_reason || "")} — 이야기 준비 중</div></div>` : "";
    screen(`<h2 class="sec">영웅을 선택하세요</h2><p class="flow">각 영웅에게는 자기만의 이야기가 있습니다. 어떤 순서로든 진행할 수 있습니다.</p>
      <div class="heroes">${cards}</div>${pv}`);
    app.querySelectorAll(".hero").forEach((b) => (b.onclick = () => {
      const id = b.dataset.h;
      stats.log("hero_select", { hero: id, locked: b.classList.contains("locked") });
      if (b.classList.contains("locked")) return renderHeroSelect(id);
      if (game.state.stories[data.heroes.find((h) => h.id === id).story]?.done) return renderMap();
      pending = { entered: game.startStory(id) };
      save();
      renderStory();
    }));
  }

  // ---- 이야기 ----
  function renderStory() {
    const s = game.step();
    if (!s) return renderMap();
    const story = data.stories.find((x) => x.id === game.state.current.story);
    const ch = story.chapters.find((c) => c.id === game.state.current.chapter);
    const head = `<div class="chapter">${hero(story.hero).icon} ${esc(story.title)} · ${esc(ch.title)} <span class="flow">(${game.state.current.step + 1}/${ch.steps.length})</span></div>`;
    const ent = game.state.entered || {};
    let body = "";
    if (s.type === "narration") {
      body = `<p class="line">${s.speaker ? `<b>${esc(s.speaker)}</b>: ` : ""}${esc(s.text)}</p>${badge(s.historical_status)}<button class="big main" id="next">다음 ▶</button>`;
    } else if (s.type === "quiz") {
      const q = game.quiz();
      body = `<div class="qhead">❓ 역사 퀴즈 ${badge(q.historical_status)}</div><h2 class="q">${esc(q.question)}</h2>
        <div class="opts" role="group" aria-label="보기 (키보드 1~4)">${q.choices.map((c, i) => `<button class="opt" data-a="${i}"><span class="no">${i + 1}</span>${esc(c)}</button>`).join("")}</div>`;
    } else if (s.type === "choice") {
      body = `<h2 class="q">${esc(s.text)}</h2><div class="opts">${s.options.map((o, i) => {
        const ok = game.optionEnabled(o);
        const why = o.requires_stat ? `${statLabel(o.requires_stat.stat)[0]} ${o.requires_stat.gte} 필요` : "";
        return `<button class="opt" data-c="${esc(o.id)}"${ok ? "" : " disabled"}><span class="no">${i + 1}</span>${esc(o.text)}${ok ? "" : `<small>${esc(why)}</small>`}</button>`;
      }).join("")}</div>`;
    } else if (s.type === "reward") {
      const it = (ent.gained.items || []).map((i) => item(i));
      body = `<div class="reward pop">${it.map((x) => `<div class="big-icon">${x.icon}</div><b>${esc(x.name)} 획득!</b> ${badge(x.historical_status)}<div class="flow">${esc(x.note || "")}</div>`).join("")}
        ${esc(s.text || "")}${gainedHtml(ent.gained)}</div><button class="big main" id="next">다음 ▶</button>`;
    } else if (s.type === "companion") {
      const h = hero(s.hero);
      body = `<div class="reward join pop"><div class="big-icon">${h.icon}</div><b>${esc(h.name)} 합류!</b><div class="flow">탁멍 ↔ ${esc(h.name)}: ${REL_ICON.COMPANION} 동료</div>
        ${(h.skills || []).map((sk) => `<div class="skillcard">${skill(sk).icon} <b>${esc(skill(sk).name)}</b> ${badge(skill(sk).historical_status)}<div class="flow">${esc(skill(sk).desc)}</div></div>`).join("")}
        ${gainedHtml(ent.gained)}</div><button class="big main" id="next">다음 ▶</button>`;
    } else if (s.type === "relation") {
      const h = hero(s.hero);
      body = `<div class="reward pop"><div class="big-icon">${REL_ICON[s.to]}</div><b>${esc(h.name)} — ${REL_LABEL[s.to]}</b> ${badge(h.historical_status)}<div class="flow">${esc(h.desc || "")}</div></div><button class="big main" id="next">다음 ▶</button>`;
    } else if (s.type === "region") {
      const r = data.regions.find((x) => x.id === s.region);
      const g = ent.gained;
      body = `<div class="reward pop"><div class="big-icon">🗺️</div><b>${esc(r.name)}</b> <span class="flow">(${esc(r.era)})</span>
        <div>${g.unlocked ? `<span class="chip good">✓ 지역 열림 · 권장 Lv ${g.recommended_level}</span>` : `<span class="chip bad">🔒 권장 Lv ${g.recommended_level} · 지금 Lv ${g.level}</span><div class="flow">퀴즈를 더 맞혀 레벨을 올리면 열립니다.</div>`}</div></div>
        <button class="big main" id="next">다음 ▶</button>`;
    } else if (s.type === "main") {
      const m = data.main_story.find((x) => x.id === s.main);
      body = `<div class="reward pop"><div class="big-icon">📖</div><b>MAIN · ${esc(m.title)} ✓</b><div class="flow">${esc(m.desc)}</div><div class="flow">영웅의 이야기를 끝낼수록 메인 스토리가 강해집니다.</div></div><button class="big main" id="next">다음 ▶</button>`;
    } else if (s.type === "board") {
      return renderBoard(head, s);
    } else if (s.type === "end") {
      body = `<div class="reward pop"><div class="big-icon">🏁</div><b>${esc(s.text)}</b></div><button class="big main" id="next">장 마치기 ▶</button>`;
    }
    const res = pending && pending.result ? resultHtml(pending.result) : "";
    screen(`${res}<section class="card story pop">${head}${body}</section>`);
    bindStory();
  }

  function resultHtml(r) {
    if (r.type === "quiz") {
      const q = data.quizzes.find((x) => x.explanation === r.explanation);
      return `<section class="card done"><div class="verdict ${r.correct ? "ok" : "no"}">${r.correct ? "⭕ 정답!" : `❌ 오답 — 정답: ${esc(q.choices[r.answer])}`}</div>
        <div class="lesson">📖 ${esc(r.explanation)}<span class="src">출처: ${esc(r.source)}</span></div>${gainedHtml(r.gained)}</section>`;
    }
    if (r.type === "choice") {
      return `<section class="card done"><div>${esc(r.result)} ${badge(r.historical_status)}</div>${r.lesson ? `<div class="lesson">📜 ${esc(r.lesson)}</div>` : ""}${gainedHtml(r.gained)}${r.gained.bonus ? gainedHtml(r.gained.bonus) : ""}</section>`;
    }
    if (r.type === "board") return `<section class="card done"><b>🎲 사냥 결과</b>${gainedHtml(r.merged)}${r.merged.skill_bonus ? `<div class="flow">🎯 궁술 보너스</div>` : ""}</section>`;
    return "";
  }

  function bindStory() {
    app.querySelectorAll("#main .opt[data-a]").forEach((b) => (b.onclick = () => {
      const q = game.quiz();
      const r = game.advance(+b.dataset.a);
      stats.log("quiz_answer", { quiz: q.id, correct: r.correct });
      logGains(r.gained);
      logGains(game.state.entered && game.state.entered.gained); // 다음 단계에 들어가며 받은 것(보상 단계 등)
      pending = { result: r };
      save();
      renderStory();
    }));
    app.querySelectorAll("#main .opt[data-c]:not([disabled])").forEach((b) => (b.onclick = () => {
      const r = game.advance(b.dataset.c);
      logGains(r.gained);
      logGains(game.state.entered && game.state.entered.gained); // 다음 단계에 들어가며 받은 것(보상 단계 등)
      pending = { result: r };
      save();
      renderStory();
    }));
    const n = app.querySelector("#next");
    if (n) n.onclick = () => {
      const s = game.step();
      const r = game.advance();
      if (s.type === "companion") stats.log("companion_join", { hero: s.hero });
      if (r.type === "end") return renderChapterEnd(r);
      pending = { result: null };
      logGains(game.state.entered && game.state.entered.gained);
      save();
      renderStory();
    };
  }
  function logGains(g) {
    if (!g) return;
    for (const it of g.items || []) stats.log("item", { item: it });
    for (const l of g.level_up || []) stats.log("level_up", { level: l });
  }

  // ---- 보드 한 턴(6-66 엔진) ----
  function renderBoard(head, s) {
    const b = game.boardGame();
    if (!b) { // 보드가 끝나 결과를 합친 상태
      screen(`${resultHtml({ type: "board", merged: game.state.board.merged })}<section class="card story">${head}<button class="big main" id="next">다음 ▶</button></section>`);
      return bindStory();
    }
    const st = b.state;
    const v = st.vars;
    const tiles = b.data.board.map((c, i) => `<div class="tile${i === st.pos ? " here" : ""}${st.phase === "steer" && b.steerOptions().some((o) => (st.pos + o.steps) % b.data.board.length === i) ? " target" : ""}" title="${esc(c.name)}"><span>${i === st.pos ? "🧑" : c.icon}</span></div>`).join("");
    let stage = "";
    if (st.phase === "quiz") {
      const q = b.quiz();
      stage = `<div class="qhead">❓ 사냥 퀴즈 — 맞히면 🎲 주사위 특권</div><h2 class="q">${esc(q.question)}</h2><div class="opts">${q.choices.map((c, i) => `<button class="opt" data-ba="${i}"><span class="no">${i + 1}</span>${esc(c)}</button>`).join("")}</div>`;
    } else if (st.phase === "parity") {
      stage = `<div class="reward"><b>🎲 주사위 특권!</b><div class="flow">홀짝을 선언하세요. 맞으면(확률 3/6) 도착 칸을 고릅니다.</div><div class="opts two"><button class="opt" data-bp="odd"><span class="no">1</span>홀수 1·3·5</button><button class="opt" data-bp="even"><span class="no">2</span>짝수 2·4·6</button></div></div>`;
    } else if (st.phase === "roll") {
      stage = `<div class="flow">주사위 특권 없음</div><button class="big main" id="broll">🎲 주사위 굴리기</button>`;
    } else if (st.phase === "steer") {
      stage = `<div class="reward"><b>🧭 적중! 도착 칸 선택</b><div class="opts">${b.steerOptions().map((o, i) => `<button class="opt" data-bs="${o.steps}"><span class="no">${i + 1}</span>${o.cell.icon} ${esc(o.cell.name)} <small>${o.steps}칸</small></button>`).join("")}</div></div>`;
    } else if (st.phase === "cell") {
      const c = b.cell();
      if (c.type === "QUIZ") {
        const q = b.cellQuiz();
        stage = `<div class="qhead">${c.icon} ${esc(c.name)}</div><h2 class="q">${esc(q.question)}</h2><div class="opts">${q.choices.map((x, i) => `<button class="opt" data-bq="${i}"><span class="no">${i + 1}</span>${esc(x)}</button>`).join("")}</div>`;
      } else {
        stage = `<div class="qhead">${c.icon} ${esc(c.name)}</div><div class="opts">${b.cellOptions().map((o, i) => `<button class="opt" data-bc="${esc(o.choice.id)}"${o.enabled ? "" : " disabled"}><span class="no">${i + 1}</span>${esc(o.choice.text)}${o.enabled ? "" : `<small>${esc(o.reason)}</small>`}</button>`).join("")}</div>`;
      }
    } else if (st.phase === "turn_end") {
      stage = `<button class="big main" id="bdone">사냥 마치기 ▶</button>`;
    }
    screen(`<section class="card story">${head}<div class="qhead">${esc(s.text)}</div>
      <div class="bhud">🌾 군량 ${v.coin} · 📚 ${v.knowledge} · 🧭 ${v.exploration}</div><div class="bmap" aria-label="졸본 들판 8칸">${tiles}</div>
      ${boardLog.map((x) => `<div class="blog">${x}</div>`).join("")}${stage}</section>`);
    const B = (sel, fn) => app.querySelectorAll(sel).forEach((el) => (el.onclick = () => fn(el)));
    B("#main .opt[data-ba]", (el) => { const q = b.quiz(); const r = b.answer(+el.dataset.ba); stats.log("quiz_answer", { quiz: q.id, correct: r.correct, board: true });
      boardLog.push(`${r.correct ? "⭕ 정답 → 🎲 특권" : `❌ 오답(정답: ${esc(q.choices[q.correct])})`} <span class="flow">${esc(r.explanation)}</span>`); renderStory(); });
    B("#main .opt[data-bp]", (el) => roll(el.dataset.bp));
    const br = app.querySelector("#broll");
    if (br) br.onclick = () => roll(null);
    B("#main .opt[data-bs]", (el) => { b.steerTo(+el.dataset.bs); boardLog.push(`🧭 → ${b.cell().icon} ${esc(b.cell().name)}`); cellAuto(); renderStory(); });
    B("#main .opt[data-bq]", (el) => { const q = b.cellQuiz(); const r = b.answerCellQuiz(+el.dataset.bq); boardLog.push(`${r.correct ? "⭕" : "❌"} ${esc(q.choices[q.correct])}`); renderStory(); });
    B("#main .opt[data-bc]:not([disabled])", (el) => { const r = b.act(el.dataset.bc); boardLog.push(`${esc(r.result_text || "")}${r.lesson ? ` <span class="flow">📜 ${esc(r.lesson.text)}</span>` : ""}`); renderStory(); });
    const bd = app.querySelector("#bdone");
    if (bd) bd.onclick = () => {
      b.nextTurn();
      const merged = game.finishBoard();
      stats.log("board_done", { exp: merged.exp });
      boardLog = [];
      save();
      renderStory();
    };
    function roll(p) {
      const r = p ? b.declare(p) : b.roll();
      if (p) stats.log("dice_parity_selected", { parity: p });
      stats.log("dice_result", { roll: r.roll, hit: r.hit === null ? "none" : r.hit });
      const face = `${FACES[r.roll - 1]} ${r.roll}`;
      boardLog.push(`🎲 ${face} · ${p ? (r.hit ? "적중!" : "빗나감") : "특권 없음"}${b.state.phase !== "steer" ? ` → ${b.cell().icon} ${esc(b.cell().name)}` : ""}`);
      if (b.state.phase !== "steer") cellAuto();
      renderStory();
    }
    function cellAuto() {
      const r = b.state.cell_result;
      if (b.state.phase === "turn_end" && r && r.auto) boardLog.push(`${esc(b.cell().event_text || "")}${r.lesson ? ` <span class="flow">📜 ${esc(r.lesson.text)}</span>` : ""}`);
    }
  }

  // ---- 장 완료·지도 ----
  function renderChapterEnd(r) {
    const st = game.state;
    stats.log("chapter_complete", { story: r.story, chapter: r.chapter });
    stats.complete({ choice_count: st.answers.correct + st.answers.wrong, ending: r.chapter, style: null,
                     metrics: { level: st.level, exp: st.stats.exp, correct: st.answers.correct, wrong: st.answers.wrong, companions: st.companions.length, items: st.items.length } });
    save();
    pending = null;
    const rel = Object.entries(st.relations).map(([id, t]) => `<span class="chip">${REL_ICON[t]} ${esc(hero(id).name)} · ${REL_LABEL[t]}</span>`).join("");
    screen(`<section class="card pop"><div class="big-icon center">🏁</div><h2 class="q center">주몽 이야기 1장 완료</h2>
      <div class="rows"><div>레벨</div><div>Lv ${st.level} (EXP ${st.stats.exp})</div><div>퀴즈</div><div>⭕ ${st.answers.correct} · ❌ ${st.answers.wrong}</div>
        <div>아이템</div><div>${st.items.map((i) => item(i).icon + " " + esc(item(i).name)).join(", ") || "-"}</div><div>스킬</div><div>${st.skills.map((i) => skill(i).icon + " " + esc(skill(i).name)).join(", ") || "-"}</div>
        <div>동료</div><div>${st.companions.map((i) => hero(i).icon + " " + esc(hero(i).name)).join(", ") || "-"}</div><div>지식</div><div>${st.knowledge.length}개</div>
        <div>정책</div><div>${st.policies.map((p) => esc(data.policies.find((x) => x.id === p).name)).join(", ") || "-"}</div></div>
      <div class="chips">${rel}</div>
      <button class="big main" id="tomap">🗺️ 지역 지도</button><button class="ghost" id="tohero">영웅 선택</button></section>`);
    app.querySelector("#tomap").onclick = renderMap;
    app.querySelector("#tohero").onclick = () => renderHeroSelect();
  }

  function renderMap() {
    const groups = {};
    for (const c of game.regionCards()) (groups[c.region.stage] = groups[c.region.stage] || []).push(c);
    const stageTitle = (id) => (data.stages.find((x) => x.id === id) || { title: "허브" }).title;
    const html = Object.entries(groups).map(([sid, cs]) => `<h3 class="sub-h">${esc(stageTitle(sid))}</h3><div class="regions">${cs.map((c) => `
      <div class="region${c.unlocked ? " open" : ""}"><b>${c.unlocked ? "🟢" : c.meets_level ? "⚪" : "🔒"} ${esc(c.region.name)}</b><small>${esc(c.region.era)}</small>
        <span class="flow">권장 Lv ${c.region.recommended_level} · 난이도 ${"★".repeat(c.region.difficulty) || "-"}</span>${c.region.status === "planned" ? `<span class="flow">준비 중</span>` : ""}</div>`).join("")}</div>`).join("");
    const mains = data.main_story.map((m) => `<li class="${game.state.main_done.includes(m.id) ? "ok" : ""}">${game.state.main_done.includes(m.id) ? "✓" : "·"} ${esc(m.title)} ${badge(m.historical_status)}</li>`).join("");
    screen(`<h2 class="sec">🗺️ 지역 지도</h2><p class="flow">지금 Lv ${game.state.level}. 권장 레벨이 높은 지역일수록 위험합니다.</p>${html}
      <h3 class="sub-h">📖 메인 스토리</h3><ol class="mains">${mains}</ol><button class="big main" id="tohero">영웅 선택</button>`);
    app.querySelector("#tohero").onclick = () => renderHeroSelect();
  }

  function onKey(ev) {
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const n = Number(ev.key);
    if (n >= 1 && n <= 4) {
      const b = app.querySelectorAll("#main .opt")[n - 1];
      if (b && !b.disabled) { ev.preventDefault(); b.click(); }
      return;
    }
    const idle = !document.activeElement || document.activeElement === document.body;
    if (ev.key === "ArrowRight" || (ev.key === "Enter" && idle)) {
      const m = app.querySelector("#main .main, #start");
      if (m) { ev.preventDefault(); m.click(); }
    }
  }

  window.Choice100RpgRenderer = { boot };
})();
