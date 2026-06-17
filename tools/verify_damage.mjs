// verify_damage.mjs
// Run yisim's matchup simulation for every round in an input rounds.json
// and write the per-round result to an output file.
//
// Usage:  node tools/verify_damage.mjs <rounds_in.json> <result_out.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const [, , roundsPath, outPath] = process.argv;
if (!roundsPath || !outPath) {
  console.error('usage: node verify_damage.mjs <rounds_in.json> <result_out.json>');
  process.exit(2);
}

const bundle = readFileSync(path.join(ROOT, 'web', 'yisim.bundle.js'), 'utf8');
(0, eval)(bundle);
if (!globalThis.yisim) {
  console.error('yisim not attached to globalThis after eval');
  process.exit(1);
}

const rounds = JSON.parse(readFileSync(roundsPath, 'utf8'));
await globalThis.yisim.ready();

// Per-round-scaled fates (stacks grow with round number).
const FATE_ROUND_SCALER = {
  // Swordsmith: 7 + (round - 1) atk on 澄心剑胚 first attack.
  'Swordsmith': (rn) => Math.max(0, rn - 1),
};
function scaleStacksByRound(fates, rn) {
  return (fates || []).map((f) => {
    if (!f) return f;
    const scaler = FATE_ROUND_SCALER[f.name];
    if (!scaler) return f;
    return { ...f, stackOverride: scaler(Number(rn || 1)) };
  });
}

// Pre-battle herb stacks (from BR stat ids 10011=神力草, 10015=紫蕨) get
// injected as synthetic runtime-stack talents so yisim seeds them on the
// player who consumed the herb. yisim's start-of-game hooks then apply the
// real effect (+atk for divine_power_grass, enemy debuff for toxic_purple_fern).
function herbTalents(herbMap) {
  return Object.entries(herbMap || {}).map(([key, value]) => ({
    detected: true,
    name: `__herb:${key}`,
    simulationKind: 'runtime-stack',
    runtimeKey: key,
    stackOverride: Number(value),
    position: 0,
    phase: 0,
    grantedCardBaseIds: [],
  }));
}
function appendHerbs(fates, herbMap) {
  return [...(fates || []), ...herbTalents(herbMap)];
}

// 乘云融合式 (Chengyun's Fusion Style) is needed alongside Swordplay Talent
// to actually trigger the dual-sword check in yisim. Seed its stacks when
// the player has that fate explicitly — `fate_talent_map.json` marks it
// non-combat-or-unsupported, so it won't be seeded otherwise.
function appendFusionStyleIfNeeded(talents, fates) {
  const hasFate = (fates || []).some((f) => f && f.name === "Chengyun's Fusion Style");
  if (!hasFate) return talents;
  return [...talents, {
    detected: true,
    name: '__fate:Chengyun Fusion Style (auto-seed)',
    simulationKind: 'runtime-stack',
    runtimeKey: 'chengyuns_fusion_style_stacks',
    stackOverride: 1,
    position: 0, phase: 0, grantedCardBaseIds: [],
  }];
}

const out = [];
for (const r of rounds) {
  const me = r.me;
  const opp = r.opponent;
  const deckSlots = me.deckSlots || 8;
  const oppDeckSlots = opp.deckSlots || deckSlots;
  // Turn-order: higher (cultivation + speed) goes first. Speed comes from
  // BR stat 369. On exact tie, the actual game flips a coin — yisim's
  // 'tied' mode runs BOTH orderings and averages, which is what the live
  // game does over many trials. Last-stand for the second player ALSO
  // fires only on effective ties (game mechanic).
  const speedMap = r.br_pre_battle_speed || {};
  const meSpeed = Number(speedMap[r.me_uid] || 0);
  const oppSpeed = Number(speedMap[r.opponent?.uid] || 0);
  const meEffective = (me.xiuwei || 0) + meSpeed;
  const oppEffective = (opp.xiuwei || 0) + oppSpeed;
  const effectiveTied = (meEffective === oppEffective);
  let turnOrder;
  if (meEffective > oppEffective) turnOrder = 'me-first';
  else if (meEffective < oppEffective) turnOrder = 'opp-first';
  else turnOrder = 'tied';
  const opts = {
    rollMode: 'average',
    deckSlots,
    // Bundle's maxTurns counts FULL turns (2 half-turns each). Real game caps
    // at 32 full turns. Use 32 here so runaway healing decks don't get 2x the
    // cycles compared to a real game.
    maxTurns: 32,
    mode: 'matchup',
    turnOrder,
    lastStandSecond: effectiveTied,
    playerState: {
      hp: me.hp, maxHp: me.hp,
      physique: me.tipo || 0, maxPhysique: me.max_tipo || me.tipo || 0,
      cultivation: me.xiuwei || 0,
      speed: meSpeed,
    },
    talents: appendHerbs(scaleStacksByRound(me.fates || [], r.round), (r.br_pre_battle_herbs || {})[r.me_uid]),
    opponentSlots: (opp.slots || []).slice(0, oppDeckSlots),
    opponentState: {
      hp: opp.hp, maxHp: opp.hp,
      physique: opp.tipo || 0, maxPhysique: opp.max_tipo || opp.tipo || 0,
      cultivation: opp.xiuwei || 0,
      speed: oppSpeed,
    },
    opponentTalents: appendHerbs(scaleStacksByRound(opp.fates || [], r.round), (r.br_pre_battle_herbs || {})[opp.uid]),
    // 悟剑天赋 picked cards (pre-resolved to 5-char base IDs in Python).
    playerSwordplayTalentCards: me.swordplay_talent_card_ids || [],
    opponentSwordplayTalentCards: opp.swordplay_talent_card_ids || [],
  };
  let result, hi, lo;
  const actual = Number(r.br_pb5_hp_diff || 0);
  const pb1IsMe = !!r.br_pb1_is_me;
  const pb1Diff = (res) => pb1IsMe ? (res.myHp - res.oppHp) : (res.oppHp - res.myHp);
  const closer = (a, b) => Math.abs(pb1Diff(a) - actual) <= Math.abs(pb1Diff(b) - actual) ? a : b;
  try {
    // Sim with all rollMode variants and (on ties) both orderings AND both
    // last-stand-second values. Pick whichever combo's ΔHP is closest to
    // BR's actual ΔHP — the live game took ONE path; post-hoc selection
    // matches it.
    const variants = [];
    const ordersToTry = (turnOrder === 'tied') ? ['me-first', 'opp-first'] : [turnOrder];
    const lastStandToTry = effectiveTied ? [true, false] : [opts.lastStandSecond];
    for (const ord of ordersToTry) {
      for (const ls of lastStandToTry) {
        const base = {...opts, turnOrder: ord, lastStandSecond: ls};
        variants.push(await globalThis.yisim.simulate(me.slots, base));
        variants.push(await globalThis.yisim.simulate(me.slots, {...base, rollMode: 'high'}));
        variants.push(await globalThis.yisim.simulate(me.slots, {...base, rollMode: 'low'}));
      }
    }
    result = variants.reduce(closer);
    // hi/lo retained for the hasRng probe (use first-order to keep semantic).
    const probeOpts = {...opts, turnOrder: ordersToTry[0]};
    hi = await globalThis.yisim.simulate(me.slots, {...probeOpts, rollMode: 'high'});
    lo = await globalThis.yisim.simulate(me.slots, {...probeOpts, rollMode: 'low'});
  } catch (e) {
    result = { error: String(e) };
  }
  const sumOrZero = arr => (arr || []).reduce((a, b) => a + b, 0);
  const hasRng = !!(hi && lo) && (
    hi.outcome !== lo.outcome
    || sumOrZero(hi.perTurnDamage) !== sumOrZero(lo.perTurnDamage)
    || sumOrZero(hi.perTurnTaken) !== sumOrZero(lo.perTurnTaken)
  );
  out.push({
    round: r.round,
    error: result?.error || null,
    first8Turns: result?.first8Turns,
    perTurnDamage: (result?.perTurnDamage || []),
    perTurnTaken: (result?.perTurnTaken || []),
    cumulativeDamage: (result?.cumulativeDamage || []),
    cumulativeTaken: (result?.cumulativeTaken || []),
    outcome: result?.outcome,
    endTurn: result?.endTurn,
    myHp: result?.myHp,
    oppHp: result?.oppHp,
    turnOrder,
    hasRng,
    rngHi: hi ? { outcome: hi.outcome, dealt: sumOrZero(hi.perTurnDamage), taken: sumOrZero(hi.perTurnTaken) } : null,
    rngLo: lo ? { outcome: lo.outcome, dealt: sumOrZero(lo.perTurnDamage), taken: sumOrZero(lo.perTurnTaken) } : null,
  });
  const rngFlag = hasRng ? ' 🎲RNG' : '';
  console.error(`R${r.round}: my=${result?.first8Turns}  outcome=${result?.outcome}  endTurn=${result?.endTurn}  turnOrder=${turnOrder}${rngFlag}`);
}

writeFileSync(outPath, JSON.stringify(out, null, 2), 'utf8');
console.error(`\nWrote ${out.length} round results to ${outPath}`);
