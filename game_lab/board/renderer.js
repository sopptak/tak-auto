/*
 * CHOICE100 BOARD 화면(6-66 G1) - 엔진(Choice100Board.Game) 상태를 그린다. 규칙 engine.js, 내용 world/*.json, 기록 ../choice100/analytics.js.
 * 한 턴은 한 화면에서 아래로 쌓인다: 퀴즈 → 정답/오답 → (특권) 홀짝 선언 또는 굴리기 → 주사위 → (적중) 항로 조정 → 칸 → 결과·교훈 → 다음 퀴즈.
 */
(function () {
  "use strict";
  const { Game } = window.Choice100Board;
  const reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const TYPE_LABEL = { START: "출발", CITY: "도시", TRADE: "교역", EXPLORE: "탐험", QUIZ: "퀴즈", EVENT: "사건", BONUS: "보너스", REST: "휴식" };
  const FACES = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];

  let app, data, game, stats, saveKey, parts = [], busy = false, view = 0; // view: 화면이 바뀔 때마다 +1(늦게 끝난 연출 무시용)

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const statDef = (k) => data.stats.find((s) => s.key === k);
  const goodDef = (k) => data.goods.find((g) => g.key === k);
  const storage = {
    get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 저장 불가 환경 */ } },
    del(k) { try { window.localStorage.removeItem(k); } catch (e) { /* 무시 */ } },
  };
  const save = () => storage.set(saveKey, game.serialize());
  const chips = (deltas) => Object.entries(deltas || {}).filter(([, v]) => v).map(([k, v]) => {
    const d = statDef(k);
    return `<span class="delta ${v > 0 ? "good" : "bad"}">${d.icon} ${esc(d.label)} ${v > 0 ? "+" : ""}${v}</span>`;
  }).join("");

  async function boot(root, url) {
    app = root;
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
      data = await res.json();
    } catch (e) {
      app.innerHTML = `<div class="card">게임 데이터를 불러오지 못했습니다. <code>py -m http.server 8790 --bind 127.0.0.1 -d game_lab</code> 후 http://127.0.0.1:8790/board/world/</div>`;
      return;
    }
    saveKey = `choice100board:${data.id}`;
    stats = window.Choice100Analytics.create(storage, data.id, data.version);
    document.addEventListener("keydown", onKey);
    renderTitle();
  }

  // ---- 타이틀 ----
  function renderTitle() {
    view += 1;
    busy = false;
    const saved = storage.get(saveKey);
    const resumable = saved ? Game.restore(data, saved) : null;
    const inProgress = resumable && resumable.state.phase !== "end";
    const pr = data.rewards.DICE_PARITY;
    app.innerHTML = `<section class="title-screen pop">
      <h1 class="logo">${esc(data.title)}<small>${esc(data.subtitle)}</small></h1>
      <p class="hook">${esc(data.hook)}</p>
      <p class="intro">${esc(data.intro)}</p>
      <div class="rule">🎲 <b>${esc(pr.label)}</b>: ${esc(pr.desc)}</div>
      <button class="big" id="start">출항 START</button>
      ${inProgress ? `<button class="ghost" id="resume">이어하기 · 항해 ${resumable.state.turn}/${data.turns}</button>` : ""}
      <p class="disclaimer">${esc(data.disclaimer)}</p></section>`;
    app.querySelector("#start").onclick = () => newGame(!!inProgress);
    const r = app.querySelector("#resume");
    if (r) r.onclick = () => { game = resumable; parts = []; renderTurn(); };
    app.querySelector("#start").focus({ preventScroll: true });
  }

  function newGame(isRestart) {
    storage.del(saveKey);
    game = new Game(data);
    view += 1;
    busy = false;
    stats.start(isRestart);
    save();
    parts = [];
    renderTurn();
  }

  // ---- 상단: 항해·자원·짐·지도 ----
  function headerHtml() {
    const v = game.state.vars;
    const cargo = data.goods.map((g) => `${g.icon}${game.state.cargo[g.key]}`).join(" ");
    const hud = data.stats.map((s) => `<div class="stat"><div class="k">${s.icon} ${esc(s.label)}</div><div class="v">${v[s.key]}</div></div>`).join("")
      + `<div class="stat"><div class="k">📦 짐 ${game.cargoCount()}/${data.cargo_cap}</div><div class="v small">${cargo}</div></div>`;
    const steer = new Set((game.state.phase === "steer" ? game.steerOptions() : []).map((o) => (game.state.pos + o.steps) % data.board.length));
    const tiles = data.board.map((c, i) => `<div class="tile t-${c.type}${i === game.state.pos ? " here" : ""}${steer.has(i) ? " target" : ""}" title="${i}. ${esc(c.name)} (${TYPE_LABEL[c.type]})" aria-label="${i}번 ${esc(c.name)} ${TYPE_LABEL[c.type]}${i === game.state.pos ? " 현재 위치" : ""}">
        <span class="ti">${i === game.state.pos ? "⛵" : c.icon || "·"}</span><span class="tn">${i}</span></div>`).join("");
    const here = game.cell();
    return `<div class="sticky"><div class="top"><span><b>항해 ${game.state.turn}</b> / ${data.turns}</span><span>📍 ${esc(here.name)} · ${esc(here.region)}</span></div>
      <div class="hud" role="group" aria-label="자원">${hud}</div></div>
      <div class="map" role="img" aria-label="항로 지도: 24칸, 현재 ${game.state.pos}번 ${esc(here.name)}">${tiles}</div>
      <div class="flow center">${esc(data.route_note)}</div>`;
  }

  function renderTurn() {
    const body = parts.join("") + stageHtml();
    app.innerHTML = `${headerHtml()}<div id="turn">${body}</div>${footHtml()}`;
    bindStage();
    bindFoot();
    const primary = app.querySelector("#turn .opt:not([disabled]), #turn .main");
    if (primary) {
      if (!("ontouchstart" in window)) primary.focus({ preventScroll: true });
      primary.scrollIntoView({ block: "nearest" });
    }
  }

  // 지금 단계의 입력 부분(끝난 단계는 parts[]에 글로 남는다)
  function stageHtml() {
    const s = game.state;
    if (s.phase === "quiz") {
      const q = game.quiz();
      return `<section class="card pop"><div class="chapter">🌍 세계사 퀴즈 · ${esc(q.era)} · ${esc(q.region)}</div><h2 class="q">${esc(q.question)}</h2>
        <div class="opts" role="group" aria-label="보기 (키보드 1~4)">${q.choices.map((c, i) => `<button class="opt" data-a="${i}"><span class="no">${i + 1}</span>${esc(c)}</button>`).join("")}</div></section>`;
    }
    if (s.phase === "parity") {
      return `<section class="card pop reward"><div class="big-icon">🎲</div><b>주사위 특권 획득!</b><div class="flow">어느 쪽을 선언할까요? 맞으면 도착 칸을 한 칸 앞·그대로·한 칸 뒤 중에서 고릅니다. (확률 3/6)</div>
        <div class="opts two"><button class="opt" data-p="odd"><span class="no">1</span>홀수 <small>1·3·5</small></button><button class="opt" data-p="even"><span class="no">2</span>짝수 <small>2·4·6</small></button></div></section>`;
    }
    if (s.phase === "roll") {
      return `<section class="card pop"><div class="flow">주사위 특권 없음 — 그냥 굴립니다.</div><button class="big main" id="roll">🎲 주사위 굴리기</button></section>`;
    }
    if (s.phase === "steer") {
      const opts = game.steerOptions();
      return `<section class="card pop reward"><b>🧭 항로 조정권</b><div class="flow">도착할 칸을 고르세요.</div>
        <div class="opts">${opts.map((o, i) => `<button class="opt" data-s="${o.steps}"><span class="no">${i + 1}</span>${o.cell.icon || ""} ${esc(o.cell.name)} <small>${TYPE_LABEL[o.cell.type]} · ${o.steps}칸</small></button>`).join("")}</div></section>`;
    }
    if (s.phase === "cell") {
      const c = game.cell();
      if (c.type === "QUIZ") {
        const q = game.cellQuiz();
        return `<section class="card pop"><div class="chapter">${c.icon} ${esc(c.name)} · 보너스 퀴즈 (맞히면 ${chips(c.quiz).replace(/<[^>]+>/g, " ").trim()})</div><h2 class="q">${esc(q.question)}</h2>
          <div class="opts">${q.choices.map((ch, i) => `<button class="opt" data-cq="${i}"><span class="no">${i + 1}</span>${esc(ch)}</button>`).join("")}</div></section>`;
      }
      const opts = game.cellOptions();
      return `<section class="card pop"><div class="chapter">${c.icon} ${TYPE_LABEL[c.type]} · ${esc(c.region)}</div><h2 class="q">${esc(c.name)}</h2>
        <div class="opts">${opts.map((o, i) => `<button class="opt" data-c="${esc(o.choice.id)}"${o.enabled ? "" : " disabled"}><span class="no">${i + 1}</span>${esc(o.choice.text)}${o.enabled ? "" : `<small class="why">${esc(o.reason)}</small>`}</button>`).join("")}</div></section>`;
    }
    if (s.phase === "turn_end") {
      const last = s.turn >= data.turns;
      return `<button class="big main next" id="next">${last ? "항해 결과 보기 ▶" : "다음 퀴즈 ▶"}</button>`;
    }
    return "";
  }

  function bindStage() {
    const s = game.state;
    app.querySelectorAll("#turn .opt[data-a]").forEach((b) => (b.onclick = () => onAnswer(+b.dataset.a)));
    app.querySelectorAll("#turn .opt[data-p]").forEach((b) => (b.onclick = () => onRoll(b.dataset.p)));
    const r = app.querySelector("#roll");
    if (r) r.onclick = () => onRoll(null);
    app.querySelectorAll("#turn .opt[data-s]").forEach((b) => (b.onclick = () => onSteer(+b.dataset.s)));
    app.querySelectorAll("#turn .opt[data-cq]").forEach((b) => (b.onclick = () => onCellQuiz(+b.dataset.cq)));
    app.querySelectorAll("#turn .opt[data-c]:not([disabled])").forEach((b) => (b.onclick = () => onAct(b.dataset.c)));
    const n = app.querySelector("#next");
    if (n && s.phase === "turn_end") n.onclick = onNext;
  }

  // ---- 동작 ----
  function onAnswer(i) {
    const q = game.quiz();
    const out = game.answer(i);
    stats.log("quiz_answer", { quiz: q.id, correct: out.correct });
    if (out.privilege) stats.log("reward_earned", { type: "DICE_PARITY" });
    save();
    parts = [`<section class="card done"><div class="chapter">🌍 ${esc(q.question)}</div>
      <div class="verdict ${out.correct ? "ok" : "no"}">${out.correct ? `⭕ 정답! ${chips(data.quiz_reward)}` : `❌ 오답 — 정답: ${esc(q.choices[q.correct])}`}</div>
      <div class="lesson">📖 ${esc(out.explanation)} <span class="src">출처: ${esc(q.source)} (${esc(q.source_date)} 확인)</span></div></section>`];
    renderTurn();
  }

  function onRoll(parity) {
    if (busy) return;
    busy = true;
    const out = parity ? game.declare(parity) : game.roll();
    if (parity) stats.log("dice_parity_selected", { parity });
    stats.log("dice_result", { roll: out.roll, hit: out.hit === null ? "none" : out.hit });
    save();
    const verdict = parity ? `${parity === "odd" ? "홀수" : "짝수"}를 선언했습니다 → ${out.hit ? "<b class=\"ok\">적중! 항로 조정권</b>" : "<b class=\"no\">빗나감</b> — 나온 만큼 이동"}` : "특권 없이 굴렸습니다.";
    const v0 = view;
    const finish = () => {
      if (view !== v0) return; // 굴리는 사이 새 게임/처음 화면으로 갔으면 옛 연출은 버린다(결과는 이미 저장됨)
      parts.push(`<section class="card done dice"><div class="die" aria-label="주사위 ${out.roll}">${FACES[out.roll - 1]} <b>${out.roll}</b></div><div>${verdict}</div>${game.state.phase !== "steer" ? moveLine() : ""}</section>`);
      afterMove();
      busy = false;
      renderTurn();
    };
    if (reduceMotion || document.hidden) return finish(); // 안 보이는 탭에서는 연출 생략
    // 굴리는 연출(0.4초): 결과는 이미 정해졌고 화면만 굴러간다
    app.querySelectorAll("#turn .opt, #roll").forEach((b) => (b.disabled = true));
    const box = document.createElement("div");
    box.className = "card die rolling";
    app.querySelector("#turn").appendChild(box);
    let k = 0;
    const timer = setInterval(() => { box.textContent = FACES[(k++ + out.roll) % 6]; }, 60);
    setTimeout(() => { clearInterval(timer); finish(); }, 400);
  }

  function moveLine() {
    const m = game.state.moved;
    if (!m) return "";
    const c = game.cell();
    return `<div class="move">⛵ ${m.steps}칸 이동 → <b>${c.icon || ""} ${esc(c.name)}</b> <small>${TYPE_LABEL[c.type]}</small>${m.passedStart ? ` <span class="delta good">⚓ 한 바퀴! ${chips(data.lap_bonus).replace(/<[^>]+>/g, " ").trim()}</span>` : ""}</div>`;
  }

  function afterMove() {
    const s = game.state;
    if (s.phase === "steer") return;
    const c = game.cell();
    stats.log("board_move", { steps: s.moved.steps, cell: c.type });
    if (s.phase === "turn_end" && s.cell_result && s.cell_result.auto) {
      parts.push(`<section class="card done cell-${c.type}"><div class="chapter">${c.icon} ${TYPE_LABEL[c.type]} · ${esc(c.name)}</div>
        <div>${esc(c.event_text || "")}</div><div class="deltas">${chips(s.cell_result.effects)}</div>${lessonHtml(s.cell_result.lesson)}</section>`);
    }
    save();
  }

  function onSteer(steps) {
    game.steerTo(steps);
    parts.push(`<section class="card done">🧭 항로 조정 → ${moveLine()}</section>`);
    afterMove();
    renderTurn();
  }

  function onCellQuiz(i) {
    const q = game.cellQuiz();
    const r = game.answerCellQuiz(i);
    stats.log("quiz_answer", { quiz: q.id, correct: r.correct, bonus: true });
    save();
    parts.push(`<section class="card done"><div class="chapter">❓ ${esc(q.question)}</div>
      <div class="verdict ${r.correct ? "ok" : "no"}">${r.correct ? `⭕ 정답! ${chips(r.deltas)}` : `❌ 오답 — 정답: ${esc(q.choices[q.correct])}`}</div>
      <div class="lesson">📖 ${esc(r.explanation)} <span class="src">출처: ${esc(q.source)}</span></div></section>`);
    renderTurn();
  }

  function onAct(id) {
    const c = game.cell();
    const r = game.act(id);
    const ch = c.choices.find((x) => x.id === id);
    if (ch.buy || ch.sell) stats.log("trade", { kind: ch.buy ? "buy" : "sell", good: (ch.buy || ch.sell).good });
    if (c.type === "EXPLORE" && id === "explore") stats.log("explore", { bonus: r.bonus });
    save();
    const sold = (r.extra || []).map((x) => `${goodDef(x.good).icon} ${x.sold}개 × ${x.price}`).join(" ");
    parts.push(`<section class="card done cell-${c.type}"><div class="chapter">${c.icon} ${esc(c.name)} → ${esc(ch.text)}</div>
      <div>${esc(r.result_text || "")} ${sold ? `<span class="flow">(${esc(sold)})</span>` : ""}</div><div class="deltas">${chips(r.deltas)}</div>${lessonHtml(r.lesson)}</section>`);
    renderTurn();
  }

  function lessonHtml(l) {
    return l ? `<div class="lesson">📜 ${esc(l.text)} <span class="src">출처: ${esc(l.source)}</span></div>` : "";
  }

  function onNext() {
    const ph = game.nextTurn();
    save();
    parts = [];
    if (ph === "end") return renderEnding();
    renderTurn();
    window.scrollTo({ top: 0 });
  }

  // ---- 결과 ----
  function renderEnding() {
    const e = game.ending();
    const v = e.values;
    const s = game.state;
    if (!s.recorded) {
      stats.complete({ choice_count: s.turn, ending: e.id, style: null, metrics: { coin: v.coin, knowledge: v.knowledge, exploration: v.exploration, score: v.score, correct: s.correct, hits: s.hits, declared: s.declared } });
      s.recorded = true;
      save();
    }
    const prev = stats.previous();
    const pm = prev && prev.metrics;
    const cmp = pm ? `<h3 class="sub-h">지난 항해와 비교</h3><div class="rows"><div>종합 점수</div><div>${pm.score} → <b>${v.score}</b></div>
        <div>💰 코인</div><div>${pm.coin} → <b>${v.coin}</b></div><div>📚 지식</div><div>${pm.knowledge} → <b>${v.knowledge}</b></div><div>🧭 탐험</div><div>${pm.exploration} → <b>${v.exploration}</b></div></div>` : "";
    const w = data.score_weights;
    app.innerHTML = `<section class="card pop"><div class="chapter">항해 ${data.turns}회 완료 · 당신의 여행 결과</div>
      <div class="ending-icon" aria-hidden="true">${e.icon}</div><div class="ending-title">게임 결과: ${esc(e.title)}</div>
      <p class="center">${esc(e.text)}</p>
      <div class="rows"><div>💰 교역·항해 코인</div><div>${v.coin}</div><div>📚 지식</div><div>${v.knowledge}</div><div>🧭 탐험</div><div>${v.exploration}</div>
        <div>⭕ 맞힌 퀴즈</div><div>${s.correct}</div><div>🎲 홀짝 적중</div><div>${s.hits} / ${s.declared}</div>
        <div>종합 점수 <small>(코인×${w.coin} + 지식×${w.knowledge} + 탐험×${w.exploration})</small></div><div><b>${v.score}</b></div></div>
      ${cmp}
      <p class="replay">퀴즈를 더 맞히면 주사위를 더 다스릴 수 있습니다. 한 번 더?</p>
      <button class="big main" id="again">한 번 더 출항 ↻</button>
      <p class="disclaimer">게임 결과이며 실제 역사 지식 평가가 아닙니다. ${esc(data.route_note)}</p></section>${footHtml()}`;
    const a = app.querySelector("#again");
    a.onclick = () => newGame(true);
    a.focus({ preventScroll: true });
    bindFoot();
    window.scrollTo({ top: 0 });
  }

  function footHtml() {
    return `<div class="foot"><button id="about" aria-expanded="false">이 게임에 대해</button> · <button id="home">처음 화면</button>
      <div id="aboutText" class="hidden">${esc(data.disclaimer)}</div></div>`;
  }
  function bindFoot() {
    const a = app.querySelector("#about"), h = app.querySelector("#home");
    if (a) a.onclick = () => { const t = app.querySelector("#aboutText"); t.classList.toggle("hidden"); a.setAttribute("aria-expanded", String(!t.classList.contains("hidden"))); };
    if (h) h.onclick = renderTitle;
  }

  function onKey(ev) {
    if (ev.altKey || ev.ctrlKey || ev.metaKey || busy) return;
    const n = Number(ev.key);
    if (n >= 1 && n <= 4) {
      const b = app.querySelectorAll("#turn .opt")[n - 1];
      if (b && !b.disabled) { ev.preventDefault(); b.click(); }
      return;
    }
    const idle = !document.activeElement || document.activeElement === document.body;
    if (ev.key === "ArrowRight" || (ev.key === "Enter" && idle)) {
      const m = app.querySelector("#turn .main, #start, #again");
      if (m) { ev.preventDefault(); m.click(); }
    }
  }

  window.Choice100BoardRenderer = { boot };
})();
