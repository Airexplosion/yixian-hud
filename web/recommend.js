// recommend.js — "推荐摆法" optimizer.
//
// Searches over board arrangements of the cards the player currently holds
// (board + hand) and returns TWO recommendations:
//   1. beatOpponent — highest win-rate vs the known opponent board (which is
//      the opponent's PREVIOUS round board; the protocol doesn't expose the
//      current-round board in time). Null when no opponent board is known.
//   2. damageMax    — highest first-8-turn damage from the current hand,
//      ignoring the opponent (always produced).
//
// Pure logic only: calls globalThis.yisim.simulate, exposes
// globalThis.recommendBoard(vm, opts). UI glue lives in ui.js. Runs unchanged
// in the browser (window===globalThis) and in Node (eval bundle + this file).
//
// Cost model: search uses a cheap single deterministic run (rollMode 'high');
// the few best arrangements are re-scored with the 100-run 'average' matchup
// to report a real winRate.
'use strict';

(function () {
  const Y = () => globalThis.yisim;

  // Mirror ui.js slotFromCard (dream cards need phase=level + isDream).
  function slotFromCard(c) {
    if (!c) return null;
    const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
    return isDream
      ? { name: c.name, level: c.level, phase: c.level, isDream: true }
      : { name: c.name, level: c.level, isDream: false };
  }
  const cardKey = (c) => (c ? `${c.name}@${c.level || 1}` : '_');
  const arrKey = (arr) => arr.map(cardKey).join('|');

  // Pad/truncate an arrangement to exactly slotCount, tail filled with nulls
  // (yisim plays nulls as 普通攻击).
  function padSlots(arr, n) {
    const out = arr.slice(0, n).map(slotFromCard);
    while (out.length < n) out.push(null);
    return out;
  }

  // Consumables / tools that are never battle-board cards (丹药/草药/道果/画师
  // 工具/灵植/灵宠玩具). Excluded from every recommendation so the optimizer
  // never wastes a slot on e.g. 以画入道. Curated (combat cards with null engine
  // actions like 灵羽/木灵斩 are deliberately NOT here — better to keep a real
  // card than risk dropping one).
  const NORM = (s) => String(s || '').replace(/[•·]/g, '·').trim();
  const EXCLUDE_ALWAYS = new Set([
    '锻体丹', '还魂丹', '洗髓丹', '锻体玄丹', '悟道丹', '灵草药浴',
    '归元草', '金梭兰', '神力草', '归岩草', '火梭兰', '失力草', '愈甘菊', '清甘菊',
    '飞枭灵芝', '穿肠紫蕨', '影枭灵芝', '玄韵道果', '魔韵道果',
    '练笔', '以画入道', '触类旁通', '妙笔生花',
    '灵植浇灌', '灵宠认主', '小鱼干', '猫薄荷', '逗猫棒', '走火入魔',
  ].map(NORM));

  // ── shared context: pool, slotCount, turn order, matchup-base factory ──────
  function buildContext(vm, settings) {
    const me = vm.me || {};
    const slotCount = Math.max(1, Math.min(8, me.unlocked || 8));
    const opp = vm.opponent || {};
    const oppBoard = (opp.board || []).map(slotFromCard);
    const oppHasCards = oppBoard.some((c) => c != null);

    const playerState = {
      hp: me.hp, maxHp: me.hp,
      physique: me.tipo || 0, maxPhysique: me.max_tipo || me.tipo || 0,
      cultivation: me.xiuwei || 0,
    };
    const soloBase = {
      deckSlots: slotCount, maxTurns: 32,
      playerState, talents: me.fates || [],
    };

    // Turn order is decided by cultivation (修为): higher acts first; equal is
    // a coin-flip (engine 'tied' mode averages both orderings).
    const a = me.xiuwei || 0, b = opp.xiuwei || 0;
    const order = a > b ? 'me-first' : a < b ? 'opp-first' : 'tied';
    const orderLabel = a > b ? '你先手' : a < b ? '你后手' : '先手不定(修为相等)';
    const oppDeck = Math.max(1, Math.min(8, opp.unlocked || slotCount));

    // Build a matchup base for a given turn order, optionally STRENGTHENING the
    // opponent to predict next round (more HP, +1 board slot filled with a copy
    // of their strongest card — capped at 8). Used for the 稳杀 recommendation.
    function makeMatchup(turnOrder, strengthen) {
      if (!oppHasCards) return null;
      let oBoard = oppBoard.slice(0, oppDeck);
      let oHp = opp.hp || 60;
      if (strengthen) {
        oHp = Math.round(oHp * 1.15) + 8;          // next-round HP bump
        const filled = oBoard.filter(Boolean);
        if (filled.length && oBoard.length < 8) {   // +1 slot (capped), strongest card duped
          oBoard = oBoard.concat([filled[0]]);
        }
      }
      return Object.assign({}, soloBase, {
        opponentSlots: oBoard,
        opponentState: {
          hp: oHp, maxHp: oHp,
          physique: opp.tipo || 0, maxPhysique: opp.max_tipo || opp.tipo || 0,
          cultivation: opp.xiuwei || 0,
        },
        opponentTalents: opp.fates || [],
        turnOrder, lastStandSecond: a === b,
      });
    }

    const pool = []
      .concat((me.board || []).filter(Boolean))
      .concat((me.hand || []).filter(Boolean))
      .filter((c) => c && !EXCLUDE_ALWAYS.has(NORM(c.name)))
      .map((c) => ({ name: c.name, level: c.level || 1 }));

    return {
      slotCount, pool, oppHasCards,
      oppRound: opp.boardFromRound || null,
      order, orderLabel,
      solo: { mode: 'solo', hasOpponent: false, base: soloBase },
      matchupMode: (turnOrder, strengthen) => {
        const base = makeMatchup(turnOrder, strengthen);
        return base ? { mode: 'matchup', hasOpponent: true, base } : null;
      },
    };
  }

  // ── scoring (per mode) ─────────────────────────────────────────────────────
  function objective(r, m) {
    if (!r || r.error) return -1e12;
    const dmg = r.first8Turns || 0;
    if (!m.hasOpponent) return dmg;
    const hpDiff = (r.myHp || 0) - (r.oppHp || 0);
    const endTurn = r.endTurn || 32;
    let s = hpDiff * 100 + dmg * 0.5;
    if (r.outcome === 'win') s += 1e6 - endTurn * 100;
    else if (r.outcome === 'lose') s += -1e6 + endTurn * 100;
    return s;
  }

  // Qi-economy awareness. A board that holds qi-COST cards (震雷剑…) but no qi
  // SOURCE is uncomfortable to play (you can't reliably power them) and the
  // engine is over-optimistic there. Penalise the qi DEFICIT (totalCost −
  // totalGen, incl. 剑气) so the optimizer prefers qi-feasible boards. The
  // penalty is FAR below the win bonus, so a winning board is never sacrificed
  // for a losing one — it only reorders within the same outcome tier
  // ("尽量少放…除非只有这一种解"). CARD_QI is loaded by web/card_qi.js.
  function qiDeficit(arr) {
    const Q = globalThis.CARD_QI;
    if (!Q) return 0;
    let cost = 0, gen = 0;
    for (const c of arr) {
      if (!c) continue;
      const nm = NORM(c.name);
      if (Q.cost[nm]) cost += Q.cost[nm];
      if (Q.gen[nm]) gen += Q.gen[nm];
    }
    return Math.max(0, cost - gen);
  }
  function qiPenalty(arr, m) {
    const d = qiDeficit(arr);
    return d ? d * (m.hasOpponent ? 4000 : 4) : 0;
  }

  // Strategy seeds: turn each reference comp (globalThis.STRATEGY, from the
  // 画炎雪 guide) into a pool-realised ordered arrangement — take the player's
  // actual cards in the reference order. Returns the seeds that cover ≥3 slots.
  function strategySeeds(pool, slotCount) {
    const S = globalThis.STRATEGY;
    if (!S || !Array.isArray(S.refComps)) return [];
    const seeds = [];
    for (const comp of S.refComps) {
      const avail = pool.slice();
      const seed = [];
      for (const refName of comp.cards || []) {
        if (seed.length >= slotCount) break;
        const rn = NORM(refName);
        const i = avail.findIndex((c) => {
          const cn = NORM(c.name);
          return cn === rn || cn.includes(rn) || rn.includes(cn);
        });
        if (i >= 0) { seed.push(avail[i]); avail.splice(i, 1); }
      }
      if (seed.length >= Math.min(slotCount, 3)) seeds.push(seed);
    }
    return seeds;
  }

  async function scoreFast(m, slotCount, arr) {
    const r = await Y().simulate(padSlots(arr, slotCount),
      Object.assign({}, m.base, { mode: m.mode, rollMode: 'high' }));
    return { obj: objective(r, m) - qiPenalty(arr, m), r };
  }
  async function scoreFull(m, slotCount, arr) {
    return Y().simulate(padSlots(arr, slotCount),
      Object.assign({}, m.base, { mode: m.mode, rollMode: 'average' }));
  }
  function finalRank(full, m) {
    if (!full) return -1e12;
    if (!m.hasOpponent) return full.first8Turns || 0;
    // Win-seeking: a board that found a winning line ranks above any that
    // didn't; among winners prefer the faster kill, among non-winners prefer
    // the one that came closest (lowest opponent HP still standing).
    if (full.outcome === 'win') {
      return 2e6 - (full.endTurn || 32) * 100 + (full.first8Turns || 0) * 0.1;
    }
    return 1e6 - Math.max(0, Math.round(full.oppHp || 0)) + (full.first8Turns || 0) * 0.01;
  }

  // ── one optimisation pass for a single mode ────────────────────────────────
  async function searchMode(m, slotCount, pool, opt) {
    const budget = opt.budget, finalists = opt.finalists, signal = opt.signal || {};
    const cancelled = () => signal.cancelled === true;
    let evals = 0;
    const memo = new Map();
    async function evalArr(arr) {
      const k = arrKey(padSlots(arr, slotCount));
      const hit = memo.get(k);
      if (hit) return hit;
      const res = await scoreFast(m, slotCount, arr);
      memo.set(k, res); evals++;
      if (evals % 40 === 0) await new Promise((r) => setTimeout(r, 0));
      return res;
    }

    // seed: rank single cards, take the slotCount best, strongest first
    const uniq = dedupe(pool);
    const single = new Map();
    for (const c of uniq) {
      if (cancelled()) return null;
      single.set(cardKey(c), (await evalArr([c])).obj);
    }
    const sorted = pool.slice().sort(
      (a, b) => (single.get(cardKey(b)) || 0) - (single.get(cardKey(a)) || 0));
    const k = Math.min(slotCount, sorted.length);
    let current = sorted.slice(0, k);
    let curScore = (await evalArr(current)).obj;

    const restarts = [
      () => shuffle(sorted.slice(0, k)),
      () => sorted.slice(0, k).reverse(),
    ];
    if (sorted.length > k) restarts.push(() => sorted.slice(1, k + 1));
    // Strategy seeds: realise each reference comp (画炎雪 guide) from the pool
    // and add it as a restart. yi-sim then evaluates/optimises it — proven
    // compositions guide the search without overriding the sim's verdict.
    for (const seed of strategySeeds(pool, k)) restarts.push(() => seed.slice(0, k));
    let ri = -1;
    while (evals < budget && !cancelled()) {
      const imp = await climbOnce(m, slotCount, current, sorted, evalArr,
        () => evals >= budget || cancelled());
      if (imp.obj > curScore + 1e-6) { current = imp.arr; curScore = imp.obj; continue; }
      ri++;
      if (ri >= restarts.length) break;
      current = restarts[ri]().slice(0, k);
      curScore = (await evalArr(current)).obj;
    }
    if (cancelled()) return null;

    // finals: distinct top arrangements re-scored with average
    const ranked = [...memo.entries()]
      .map(([key, v]) => ({ key, arr: keyToArr(key, pool), obj: v.obj }))
      .sort((a, b) => b.obj - a.obj);
    const seen = new Set(); const top = [];
    for (const e of ranked) {
      if (e.arr.length === 0 || seen.has(e.key)) continue;
      seen.add(e.key); top.push(e);
      if (top.length >= finalists) break;
    }
    const finals = [];
    for (const e of top) {
      if (cancelled()) return null;
      finals.push({ arr: e.arr, full: await scoreFull(m, slotCount, e.arr) });
    }
    // Final ranking also subtracts the qi-deficit penalty so the chosen board
    // is qi-feasible, not just highest raw score (penalty ≪ win/lose gap).
    const rankOf = (f) => finalRank(f.full, m) - qiPenalty(f.arr, m);
    finals.sort((a, b) => rankOf(b) - rankOf(a));
    return { finals, evals };
  }

  async function climbOnce(m, slotCount, arr, pool, evalArr, stop) {
    let best = { arr: arr.slice(), obj: (await evalArr(arr)).obj };
    const n = arr.length;
    // 1. pairwise swaps
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (stop()) return best;
        const cand = arr.slice(); const t = cand[i]; cand[i] = cand[j]; cand[j] = t;
        const s = (await evalArr(cand)).obj;
        if (s > best.obj + 1e-6) best = { arr: cand, obj: s };
      }
    }
    // 2. insertion moves — pull the card at i out and reinsert at j, shifting
    //    the rest. Captures ordering changes that swaps can't (cards play
    //    left-to-right, so a buff card's position relative to what it boosts
    //    matters more than which two cells trade places).
    for (let i = 0; i < n && !stop(); i++) {
      for (let j = 0; j < n; j++) {
        if (j === i) continue;
        if (stop()) return best;
        const cand = arr.slice();
        const [card] = cand.splice(i, 1);
        cand.splice(j, 0, card);
        const s = (await evalArr(cand)).obj;
        if (s > best.obj + 1e-6) best = { arr: cand, obj: s };
      }
    }
    // 3. replacements — swap a placed card for an unused pool card
    const avail = expand(subtract(countBy(pool), countBy(arr)), pool);
    for (let i = 0; i < n && !stop(); i++) {
      for (const rep of avail) {
        if (stop()) return best;
        if (cardKey(rep) === cardKey(arr[i])) continue;
        const cand = arr.slice(); cand[i] = rep;
        const s = (await evalArr(cand)).obj;
        if (s > best.obj + 1e-6) best = { arr: cand, obj: s };
      }
    }
    return best;
  }

  // ── orchestrator: produce both recommendations ─────────────────────────────
  async function recommendBoard(vm, opts) {
    opts = opts || {};
    const settings = opts.settings || {};
    const signal = opts.signal || {};
    if (!Y() || !vm || !vm.me) return null;
    const ctx = buildContext(vm, settings);
    if (!ctx.pool.length || !ctx.slotCount) return null;

    // Adaptive search budget: scale with the problem size so small early-game
    // boards finish fast and full 8-slot late-game boards search deeply.
    // qualityMul (from the UI quality setting) scales the whole budget.
    const qualityMul = opts.qualityMul || 1;
    const autoBudget = Math.min(1200, Math.max(250,
      Math.round(ctx.slotCount * ctx.pool.length * 8)));
    const budget = Math.round((opts.budget || autoBudget) * qualityMul);
    const pass = { budget, finalists: opts.finalists || 6, signal };

    const SC = ctx.slotCount;
    // toResult also reports 几轮杀 (killTurn) and 还差多少伤害 (damageGap = how
    // much opponent HP is still standing when you don't kill).
    const toResult = (f) => f && f.full ? {
      cards: f.arr.filter(Boolean).map((c) => ({ name: c.name, level: c.level })),
      slots: padSlots(f.arr, SC),
      winRate: f.full.verdict ? f.full.verdict.winRate : null,
      // Whether the matchup outcome is certain (no RNG) vs a win-seek result.
      deterministic: !!f.full.deterministic,
      outcome: f.full.outcome, endTurn: f.full.endTurn,
      killTurn: f.full.outcome === 'win' ? f.full.endTurn : null,
      damageGap: f.full.outcome !== 'win' ? Math.max(0, Math.round(f.full.oppHp || 0)) : 0,
      damage: f.full.first8Turns, myHp: f.full.myHp, oppHp: f.full.oppHp,
    } : null;

    // 1. damage-max (solo) — always
    const soloRes = await searchMode(ctx.solo, SC, ctx.pool, pass);
    if (signal.cancelled) return null;
    const damageMax = soloRes && soloRes.finals.length
      ? Object.assign(toResult(soloRes.finals[0]),
          { alternatives: soloRes.finals.slice(1, 3).map(toResult) })
      : null;

    let beatOpponent = null, altOrder = null, stableKill = null;
    if (ctx.oppHasCards) {
      // 2. beat-opponent under your ACTUAL turn order (ties → assume you go 2nd,
      //    the harder case, so a "win" here is robust).
      const realOrder = ctx.order === 'tied' ? 'opp-first' : ctx.order;
      const mMode = ctx.matchupMode(realOrder, false);
      const mRes = await searchMode(mMode, SC, ctx.pool, pass);
      if (signal.cancelled) return null;
      if (mRes && mRes.finals.length) {
        beatOpponent = Object.assign(toResult(mRes.finals[0]),
          { alternatives: mRes.finals.slice(1, 3).map(toResult) });

        // 3. same board, OPPOSITE turn order — answers "若先手/若后手会怎样"
        //    (cheap: re-evaluate, no extra search).
        const otherOrder = realOrder === 'me-first' ? 'opp-first' : 'me-first';
        const otherMode = ctx.matchupMode(otherOrder, false);
        const otherFull = await scoreFull(otherMode, SC, mRes.finals[0].arr);
        if (!signal.cancelled) {
          altOrder = Object.assign(
            toResult({ arr: mRes.finals[0].arr, full: otherFull }),
            { label: otherOrder === 'me-first' ? '你若先手' : '你若后手' });
        }
      }

      // 4. 稳杀 — search vs a STRENGTHENED opponent (next-round HP + extra slot),
      //    reduced budget. A board that still wins here is robust.
      const stableMode = ctx.matchupMode(realOrder, true);
      const stablePass = Object.assign({}, pass, { budget: Math.round(pass.budget * 0.7) });
      const sRes = await searchMode(stableMode, SC, ctx.pool, stablePass);
      if (signal.cancelled) return null;
      if (sRes && sRes.finals.length) {
        stableKill = Object.assign(toResult(sRes.finals[0]),
          { alternatives: sRes.finals.slice(1, 3).map(toResult) });
      }
    }

    return {
      damageMax, beatOpponent, altOrder, stableKill,
      oppRound: ctx.oppRound, turnOrder: ctx.orderLabel,
      meta: { poolSize: ctx.pool.length, slotCount: SC, hasOpponent: ctx.oppHasCards },
    };
  }

  // ── utilities ──────────────────────────────────────────────────────────────
  function dedupe(list) {
    const m = new Map();
    for (const c of list) if (!m.has(cardKey(c))) m.set(cardKey(c), c);
    return [...m.values()];
  }
  function countBy(list) {
    const m = new Map();
    for (const c of list) m.set(cardKey(c), (m.get(cardKey(c)) || 0) + 1);
    return m;
  }
  function subtract(a, b) {
    const m = new Map(a);
    for (const [k, v] of b) m.set(k, (m.get(k) || 0) - v);
    return m;
  }
  function expand(counts, pool) {
    const byKey = new Map();
    for (const c of pool) if (!byKey.has(cardKey(c))) byKey.set(cardKey(c), c);
    const out = [];
    for (const [k, v] of counts) for (let i = 0; i < v; i++) if (byKey.get(k)) out.push(byKey.get(k));
    return out;
  }
  function keyToArr(key, pool) {
    const byKey = new Map();
    for (const c of pool) if (!byKey.has(cardKey(c))) byKey.set(cardKey(c), c);
    return key.split('|').filter((s) => s !== '_').map((s) => byKey.get(s)).filter(Boolean);
  }
  function shuffle(a) {
    a = a.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = (i * 7 + 3) % (i + 1);
      const t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  globalThis.recommendBoard = recommendBoard;
})();
