// yisim marginal damage. stdin JSON:
//   { board:[{name,level}|null...], talents:[...],
//     playerState:{hp,maxHp,physique,maxPhysique,cultivation}, deckSlots }
// Feeds yisim the SAME complete opts the web tool does (web/ui.js updateDamage) —
// crucially playerState (修为/体魄) and deckSlots, which scale damage hard; without
// them the numbers come out far too low. marginal[i] = full - (full without card i).
const fs = require('fs');
const path = require('path');

// Repo-relative bundle (…/native_hud/bridge → repo root → web/yisim.bundle.js).
const BUNDLE = path.join(__dirname, '..', '..', 'web', 'yisim.bundle.js');
(0, eval)(fs.readFileSync(BUNDLE, 'utf8'));
const Y = globalThis.yisim;

function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
  return isDream ? { name: c.name, level: c.level, phase: c.level, isDream: true }
                 : { name: c.name, level: c.level, isDream: false };
}

function buildOpts(j, deckSlots) {
  // Mirror web/ui.js updateDamage opts. If an opponent board is supplied, run
  // MATCHUP (real combat vs that board) instead of solo output.
  const opts = {
    mode: 'solo',
    rollMode: j.rollMode || 'average',
    deckSlots,
    maxTurns: 64,
    talents: j.talents || [],
    playerState: j.playerState || null,
    // 灵植成长层数 {origin_herb_stacks:5,...} → 注入我方 sim player(归元草加血等)。
    plantStacks: j.plantStacks || null,
  };
  const o = j.opponent;
  if (o && Array.isArray(o.board) && o.board.some(x => x)) {
    const oDeck = o.deckSlots || o.board.length || deckSlots;
    opts.mode = 'matchup';
    opts.opponentSlots = o.board.slice(0, oDeck).map(toSlot);
    opts.opponentState = o.playerState || null;
    opts.opponentTalents = o.talents || [];
  }
  return opts;
}

async function total(slots, opts) {
  const r = await Promise.resolve(Y.simulate(slots, opts));
  if (r && r.first8Turns != null) return r.first8Turns;
  if (r && r.cumulativeDamage && r.cumulativeDamage.length)
    return r.cumulativeDamage[Math.min(7, r.cumulativeDamage.length - 1)];
  return 0;
}

(async () => {
  let input = '';
  process.stdin.on('data', d => input += d);
  await new Promise(r => process.stdin.on('end', r));
  let j;
  try { j = JSON.parse(input); }
  catch (e) { process.stdout.write('{"error":"bad json"}'); return; }
  const board = j.board || [];
  const deckSlots = j.deckSlots || board.length || 8;
  const slots = board.map(toSlot);
  const opts = buildOpts(j, deckSlots);
  if (Y.ready) { try { await Promise.resolve(Y.ready); } catch (e) {} }

  // totalOnly: just the whole-board number (1 sim) — what the HUD shows.
  if (j.totalOnly) {
    const r = await Promise.resolve(Y.simulate(slots, opts));
    const cum = (r && r.cumulativeDamage) ? r.cumulativeDamage.slice(0, 8).map(x => Math.round(x)) : [];
    // matchup 下 cumulativeTaken = 己方承受的累积伤害(即对手对我方造成的) → HUD 第二行。
    const taken = (r && r.cumulativeTaken) ? r.cumulativeTaken.slice(0, 8).map(x => Math.round(x)) : [];
    // 每回合实际剩余 HP(含金梭兰等战斗开始效果) → HUD 剩命显示(我方剩命/对手剩命)。
    const myHp = (r && r.myHpSeries) ? r.myHpSeries.slice(0, 8).map(x => Math.round(x)) : [];
    const oppHp = (r && r.oppHpSeries) ? r.oppHpSeries.slice(0, 8).map(x => Math.round(x)) : [];
    const full = (r && r.first8Turns != null) ? Math.round(r.first8Turns)
               : (cum.length ? cum[cum.length - 1] : 0);
    process.stdout.write(JSON.stringify({
      full, cumulative: cum, cumulativeTaken: taken,
      myHpSeries: myHp, oppHpSeries: oppHp, mode: opts.mode,
      outcome: r && r.outcome, endTurn: r && r.endTurn,
      deterministic: r && r.deterministic,
    }));
    return;
  }

  const full = await total(slots, opts);
  const marginal = {};
  for (let i = 0; i < board.length; i++) {
    if (!board[i] || !board[i].name) continue;
    const minus = slots.slice(); minus[i] = null;
    const t = await total(minus, opts);
    marginal[i] = Math.round(full - t);
  }
  process.stdout.write(JSON.stringify({ full: Math.round(full), marginal }));
})().catch(e => process.stdout.write(JSON.stringify({ error: String(e && e.message) })));
