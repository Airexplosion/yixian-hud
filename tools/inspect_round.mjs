// inspect_round.mjs
// Run yisim's matchup simulation for ONE round with maxTurns = 1, 2, …, N
// and capture the final HP after each turn. Bypasses the clamping in
// `perTurnTaken` so we can see healing / +max_hp deltas (e.g. 醉拳架势).
//
// Usage: node tools/inspect_round.mjs <round.json> <result_out.json> [N]
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const [, , roundPath, outPath, nStr] = process.argv;
if (!roundPath || !outPath) {
  console.error('usage: node inspect_round.mjs <round.json> <result_out.json> [N]');
  process.exit(2);
}
const N_DEFAULT = 16;
const N = Math.max(1, Math.min(64, Number(nStr) || N_DEFAULT));

const bundle = readFileSync(path.join(ROOT, 'web', 'yisim.bundle.js'), 'utf8');
(0, eval)(bundle);
if (!globalThis.yisim) {
  console.error('yisim not attached to globalThis after eval');
  process.exit(1);
}
await globalThis.yisim.ready();

const r = JSON.parse(readFileSync(roundPath, 'utf8'));
const me = r.me;
const opp = r.opponent;
const deckSlots = me.deckSlots || 8;
const oppDeckSlots = opp.deckSlots || deckSlots;
const meCult = me.xiuwei || 0;
const oppCult = opp.xiuwei || 0;
let turnOrder;
if (meCult > oppCult) turnOrder = 'me-first';
else if (meCult < oppCult) turnOrder = 'opp-first';
else turnOrder = 'tied';

const baseOpts = {
  rollMode: 'average',
  deckSlots,
  mode: 'matchup',
  turnOrder,
  lastStandSecond: turnOrder === 'tied',
  playerState: {
    hp: me.hp, maxHp: me.hp,
    physique: me.tipo || 0, maxPhysique: me.max_tipo || me.tipo || 0,
    cultivation: meCult,
  },
  talents: me.fates || [],
  opponentSlots: (opp.slots || []).slice(0, oppDeckSlots),
  opponentState: {
    hp: opp.hp, maxHp: opp.hp,
    physique: opp.tipo || 0, maxPhysique: opp.max_tipo || opp.tipo || 0,
    cultivation: oppCult,
  },
  opponentTalents: opp.fates || [],
};

// First, run once at maxTurns=N to learn endTurn and final state.
const fullResult = await globalThis.yisim.simulate(me.slots, {...baseOpts, maxTurns: N});
const endTurn = fullResult.endTurn ?? N;
const limit = Math.min(N, endTurn);

const perTurn = [];
for (let t = 1; t <= limit; t += 1) {
  const res = await globalThis.yisim.simulate(me.slots, {...baseOpts, maxTurns: t});
  perTurn.push({
    turn: t,
    myHp: res.myHp,
    oppHp: res.oppHp,
    myMaxHp: res.myMaxHp,
    oppMaxHp: res.oppMaxHp,
    myDef: res.myDef,
    oppDef: res.oppDef,
    myPhysique: res.myPhysique,
    oppPhysique: res.oppPhysique,
    cumDealt: (res.cumulativeDamage || [])[Math.min(t-1, (res.cumulativeDamage||[]).length-1)] ?? 0,
    cumTaken: (res.cumulativeTaken || [])[Math.min(t-1, (res.cumulativeTaken||[]).length-1)] ?? 0,
    outcome: res.outcome,
    endTurn: res.endTurn,
  });
}

writeFileSync(outPath, JSON.stringify({
  turnOrder,
  endTurn,
  outcome: fullResult.outcome,
  finalMyHp: fullResult.myHp,
  finalOppHp: fullResult.oppHp,
  myStartHp: me.hp,
  oppStartHp: opp.hp,
  perTurn,
}, null, 2), 'utf8');
console.error(`Wrote ${perTurn.length} turn snapshots to ${outPath}`);
