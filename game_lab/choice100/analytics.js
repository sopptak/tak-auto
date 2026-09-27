/*
 * CHOICE100 로컬 플레이 기록(6-65) - "사람들이 실제로 게임을 하는가?"를 나중에 보기 위한 최소 기반.
 * 저장은 이 브라우저의 저장소에만(localStorage). 서버 전송·외부 API·개인정보 없음.
 * 이벤트: game_start, choice_made, game_completion, game_restart (+ play_time은 완료 시 계산)
 * 6-66: 다른 게임(보드)도 쓰도록 log(이름, 필드) 추가 - 필드는 숫자·짧은 글자만 저장. complete()의 metrics도 숫자만.
 * 플레이 시간 = 이벤트 사이 간격의 합(간격마다 최대 120초 - 창을 켜 둔 채 자리를 비운 시간은 빼려고).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Choice100Analytics = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const V = 1, MAX_EVENTS = 300, MAX_RUNS = 30, GAP_CAP_MS = 120000;

  function create(storage, gameId, version, clock = () => Date.now()) {
    const key = `choice100:analytics:${gameId}`;
    const empty = () => ({ v: V, game_id: gameId, restart_count: 0, plays: 0, completions: 0, events: [], runs: [], current: null });

    function load() {
      try {
        const o = JSON.parse(storage.get(key) || "null");
        if (o && o.v === V && o.game_id === gameId && Array.isArray(o.events) && Array.isArray(o.runs)) return o;
      } catch (e) { /* 손상된 기록은 새로 시작 */ }
      return empty();
    }
    function save(o) {
      o.events = o.events.slice(-MAX_EVENTS);
      o.runs = o.runs.slice(-MAX_RUNS);
      try { storage.set(key, JSON.stringify(o)); } catch (e) { /* 저장 불가 - 게임은 계속 */ }
    }
    function tick(o, t) {
      const c = o.current;
      if (!c) return;
      c.active_ms += Math.max(0, Math.min(GAP_CAP_MS, t - c.last_t));
      c.last_t = t;
    }

    return {
      key,
      start(isRestart = false) {
        const o = load(), t = clock();
        if (isRestart) { o.restart_count += 1; o.events.push({ e: "game_restart", t }); }
        o.plays += 1;
        o.current = { version, started_at: t, last_t: t, active_ms: 0, choice_count: 0 };
        o.events.push({ e: "game_start", t, version });
        save(o);
      },
      choice(n, scenarioId, choiceId) {
        const o = load(), t = clock();
        if (!o.current) o.current = { version, started_at: t, last_t: t, active_ms: 0, choice_count: 0 };
        tick(o, t);
        o.current.choice_count = n;
        o.events.push({ e: "choice_made", t, n, s: scenarioId, c: choiceId });
        save(o);
      },
      complete(summary) {
        const o = load(), t = clock();
        const c = o.current || { version, started_at: t, last_t: t, active_ms: 0, choice_count: summary.choice_count || 0 };
        o.current = c;
        tick(o, t);
        const run = { game_id: gameId, version: c.version, started_at: new Date(c.started_at).toISOString(), completed_at: new Date(t).toISOString(),
                      choice_count: summary.choice_count ?? c.choice_count, play_time_sec: Math.round(c.active_ms / 1000),
                      restart_count: o.restart_count, ending: summary.ending, style: summary.style,
                      net_worth: summary.net_worth, debt: summary.debt, happiness: summary.happiness };
        if (summary.metrics) run.metrics = cleanNumbers(summary.metrics);
        o.completions += 1;
        o.runs.push(run);
        o.events.push({ e: "game_completion", t, ending: summary.ending });
        o.current = null;
        save(o);
        return run;
      },
      log(e, fields = {}) {
        const o = load(), t = clock();
        if (o.current) tick(o, t);
        o.events.push({ e: String(e).slice(0, 40), t, ...cleanFields(fields) });
        save(o);
      },
      runs() { return load().runs.slice(); },
      previous() { const r = load().runs; return r.length >= 2 ? r[r.length - 2] : null; }, // complete() 직후 호출: 바로 전 판
      stats() {
        const o = load();
        const times = o.runs.map((r) => r.play_time_sec).filter((x) => Number.isFinite(x));
        return { plays: o.plays, completions: o.completions, restart_count: o.restart_count, events: o.events.length,
                 avg_play_time_sec: times.length ? Math.round(times.reduce((a, b) => a + b, 0) / times.length) : null };
      },
      clear() { try { storage.set(key, JSON.stringify(empty())); } catch (e) { /* 무시 */ } },
    };
  }

  // 저장할 필드는 숫자와 40자 이하 글자만(개인정보·긴 글이 섞여 들어오지 않게)
  function cleanFields(f) {
    const out = {};
    for (const [k, v] of Object.entries(f || {}).slice(0, 12)) {
      if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
      else if (typeof v === "boolean") out[k] = v;
      else if (typeof v === "string") out[k] = v.slice(0, 40);
    }
    return out;
  }
  function cleanNumbers(f) {
    return Object.fromEntries(Object.entries(f || {}).filter(([, v]) => typeof v === "number" && Number.isFinite(v)).slice(0, 12));
  }

  function memoryStorage() {
    const m = new Map();
    return { get: (k) => (m.has(k) ? m.get(k) : null), set: (k, v) => m.set(k, String(v)), dump: () => Object.fromEntries(m) };
  }

  return { create, memoryStorage, GAP_CAP_MS };
});
