// inspect_round_bun.mjs — run a single round through yisim's `just_run.js`
// logic directly (no bundle, no esbuild). Uses card_name_to_id_fuzzy to
// resolve Chinese names + level into card ids, then sim_n_turns(64) and
// dumps the full action log.
//
// Usage:
//   bun tools/inspect_round_bun.mjs <round.json>
import fs from 'fs';
import path from 'path';
import { GameState, ready as gamestate_ready } from '../vendor/yisim-master/gamestate_full.js';
import { format_card, ready as card_info_ready } from '../vendor/yisim-master/card_info.js';
await gamestate_ready;
await card_info_ready;

// Build a Chinese-name → base-id map directly from names.json (skip ufuzzy,
// which doesn't reliably hit CJK terms). names.json's `namecn` field is the
// proxy's wire format (after •→· normalization). When the same name maps to
// multiple ids (e.g. regular sect card AND character/event variant), prefer
// the id that actually exists in swogi.json — names.json has stub entries.
const yisimDir = path.join(import.meta.dir || path.dirname(new URL(import.meta.url).pathname),
                            '..', 'vendor', 'yisim-master');
const namesJson = JSON.parse(fs.readFileSync(path.join(yisimDir, 'names.json'), 'utf8'));
const swogiJson = JSON.parse(fs.readFileSync(path.join(yisimDir, 'swogi.json'), 'utf8'));
const cnToId = new Map();
for (const entry of namesJson) {
  if (!entry.namecn) continue;
  const id = String(entry.id);
  const prev = cnToId.get(entry.namecn);
  const idExists = swogiJson[id] !== undefined;
  const prevExists = prev !== undefined && swogiJson[prev] !== undefined;
  if (!prev || (idExists && !prevExists)) cnToId.set(entry.namecn, id);
}

const roundPath = process.argv[2];
if (!roundPath) {
  console.error('usage: bun inspect_round_bun.mjs <round.json>');
  process.exit(2);
}
const r = JSON.parse(fs.readFileSync(roundPath, 'utf8'));

// Proxy uses •(U+2022) bullet; yisim uses ·(U+00B7) middle dot. Normalize.
function normName(n) { return String(n || '').replace(/•/g, '·'); }

// Normal Attack ("普通攻击") auto-fills empty unlocked slots in-game. Locked
// slots (index >= deckSlots) are skipped entirely.
const NORMAL_ATTACK_BASE = '601011';
function slotsToIds(slots, deckSlots) {
  const out = [];
  const n = Math.min(Number(deckSlots) || 8, 8);
  for (let i = 0; i < n; i++) {
    const s = (slots || [])[i];
    if (!s || !s.name) { out.push(NORMAL_ATTACK_BASE); continue; }
    const base = cnToId.get(normName(s.name));
    if (!base) { console.error('unresolved card:', s.name); out.push(NORMAL_ATTACK_BASE); continue; }
    const lvl = Number(s.level) || 1;
    out.push(base.slice(0, -1) + String(lvl));
  }
  return out;
}

const meIds = slotsToIds(r.me?.slots, r.me?.deckSlots);
const oppIds = slotsToIds(r.opponent?.slots, r.opponent?.deckSlots);
// Turn order: higher (cultivation + speed) goes first. On exact tie the
// game is random — we run BOTH orderings and average the per-turn HP.
const speedMap = r.br_pre_battle_speed || {};
const meSpeed = Number(speedMap[r.me_uid] || 0);
const oppSpeed = Number(speedMap[r.opponent?.uid] || 0);
const meEffective = Number(r.me?.xiuwei || 0) + meSpeed;
const oppEffective = Number(r.opponent?.xiuwei || 0) + oppSpeed;
const tied = meEffective === oppEffective;
let meFirst;
if (meEffective > oppEffective) meFirst = true;
else if (meEffective < oppEffective) meFirst = false;
else meFirst = true;  // placeholder; we'll run both orderings when tied

// Each fate has a `runtimeKey` like "p{n}_store_qi_stacks" where {n} is the
// phase position (1-5). Resolve and apply to the player object pre-sim.
// Also handle a few special-cased fates whose simulationKind isn't
// runtime-stack but which still need a stack seeded (matches the logic in
// yisim_entry.js prepareTalentIntegration).
const SPECIAL_FATE_KEYS = {
  // Two-part: transform 21501-cards + runtime effect on 62503-cards.
  'Solitary Void Golden Scroll': 'solitary_void_golden_scroll_fate_stacks',
};
// Some fates accumulate per round across the run instead of being a flat
// 1-stack seed. Each function returns the stack value to seed given the
// current round number (1-indexed).
const FATE_STACK_FROM_ROUND = {
  // Swordsmith: base 澄心剑胚 attack starts at 7 in R1 and +1 per round.
  // yisim's formula is `7 + min(swordsmith_stacks, 18)`, so seed stacks =
  // round - 1 (R1 → 0 stacks → base 7, R9 → 8 stacks → base 15).
  'Swordsmith': (rn) => Math.max(0, rn - 1),
};
function fateRuntimeWrites(fates, roundNumber) {
  const writes = [];
  const rn = Number(roundNumber || 1);
  for (const f of (fates || [])) {
    if (!f) continue;
    if (f.simulationKind === 'runtime-stack' && f.runtimeKey) {
      const phase = Number(f.phase || f.position || 0);
      const key = f.runtimeKey.replace('{n}', String(phase));
      const scaler = FATE_STACK_FROM_ROUND[f.name];
      const value = scaler ? scaler(rn) : 1;
      if (value > 0) writes.push({ key, value });
      continue;
    }
    const special = SPECIAL_FATE_KEYS[f.name];
    if (special) writes.push({ key: special, value: 1 });
  }
  return writes;
}
const meWrites = fateRuntimeWrites(r.me?.fates, r.round);
const oppWrites = fateRuntimeWrites(r.opponent?.fates, r.round);

// Pre-battle herb stacks from BR (10011 = 神力草, 10015 = 紫蕨).
// The stacks sit on the combatant WHO USED the herb; yisim's battle-start
// hooks (gamestate_full.js:1513+) apply the effect (+atk for divine_power,
// enemy +internal_injury for toxic_purple_fern). Apply directly to that
// player — no swap needed.
function herbWritesForUid(uid) {
  const herbs = (r.br_pre_battle_herbs || {})[uid] || {};
  return Object.entries(herbs)
    .filter(([_, v]) => Number(v) > 0)
    .map(([k, v]) => ({ key: k, value: Number(v) }));
}
meWrites.push(...herbWritesForUid(r.me_uid));
oppWrites.push(...herbWritesForUid(r.opponent?.uid));

const game = new GameState();
const a = {
  cultivation: Number(r.me?.xiuwei || 0),
  hp: Number(r.me?.hp || 0),
  physique: Number(r.me?.tipo || 0),
  max_physique: Number(r.me?.max_tipo || r.me?.tipo || 0),
  speed: meSpeed,
  cards: meIds,
};
const b = {
  cultivation: Number(r.opponent?.xiuwei || 0),
  hp: Number(r.opponent?.hp || 0),
  physique: Number(r.opponent?.tipo || 0),
  max_physique: Number(r.opponent?.max_tipo || r.opponent?.tipo || 0),
  speed: oppSpeed,
  cards: oppIds,
};

// yisim_entry.js convention: max_hp = base_hp + physique on battle start.
function attach(playerObj, src, writes, vaseCardIds, swordplayIds) {
  Object.assign(playerObj, src);
  playerObj.max_hp = (src.hp || 0) + (src.physique || 0);
  for (const w of (writes || [])) playerObj[w.key] = w.value;
  if (vaseCardIds && vaseCardIds.length > 0) {
    playerObj.five_elements_pure_vase_cards = vaseCardIds;
  }
  if (swordplayIds && swordplayIds.length > 0) {
    playerObj.swordplay_talent_cards = swordplayIds;
  }
}
const meVaseIds = slotsToIds(r.me?.vase_cards || [], (r.me?.vase_cards || []).length || 0);
const oppVaseIds = slotsToIds(r.opponent?.vase_cards || [], (r.opponent?.vase_cards || []).length || 0);

// 悟剑天赋 (Swordplay Talent) — the player's picked card list.
// Python verify_damage.py pre-resolves these to 5-char base IDs and stores
// them at `swordplay_talent_card_ids` for direct use by yisim's
// is_fake_unrestrained_sword / is_fake_cloud_sword checks.
const meSwordplayIds = r.me?.swordplay_talent_card_ids || [];
const oppSwordplayIds = r.opponent?.swordplay_talent_card_ids || [];

// Chengyun's Fusion Style is the paired fate that activates the swordplay
// check. fate_talent_map.json already marks it runtime-stack so it gets
// seeded via meWrites/oppWrites automatically when the player has that
// fate — no manual injection needed here.
// sim_n_turns(n) always calls start_of_game_setup, so re-running with growing
// n is the cleanest "per-turn" path. Step in PAIRS so each row = one full
// round (both players have played). When effective stats tie, the actual
// game randomly picks who goes first — we sim BOTH orderings and average
// the per-turn HP (matches the live game's expectation over many trials).
const FULL_TURNS = 32;
const N = FULL_TURNS * 2;

function runOrdering(meGoesFirst) {
  const out = [];
  for (let halfT = 2; halfT <= N; halfT += 2) {
    const g = new GameState();
    if (meGoesFirst) { attach(g.players[0], a, meWrites, meVaseIds, meSwordplayIds); attach(g.players[1], b, oppWrites, oppVaseIds, oppSwordplayIds); }
    else             { attach(g.players[0], b, oppWrites, oppVaseIds, oppSwordplayIds); attach(g.players[1], a, meWrites, meVaseIds, meSwordplayIds); }
    g.sim_n_turns(halfT);
    const meIdx = meGoesFirst ? 0 : 1;
    const oppIdx = 1 - meIdx;
    out.push({
      turn: halfT / 2, gameOver: g.game_over,
      meHp: g.players[meIdx].hp, meMax: g.players[meIdx].max_hp, mePhy: g.players[meIdx].physique,
      oppHp: g.players[oppIdx].hp, oppMax: g.players[oppIdx].max_hp, oppPhy: g.players[oppIdx].physique,
    });
    if (g.game_over) break;
  }
  return out;
}
function finalDiff(snaps) {
  const last = snaps[snaps.length - 1];
  return last ? (last.meHp - last.oppHp) : 0;
}

let snaps;
let pickedOrder;  // for display
if (tied) {
  // Game flips a coin — try both orderings, pick the one whose final ΔHP
  // is closer to BR's actual ΔHP. The pb1 sign-convention matches the
  // verify_damage.py comparison logic.
  const snapsMe = runOrdering(true);
  const snapsOpp = runOrdering(false);
  const pb1IsMe = !!r.br_pb1_is_me;
  const actualPb1 = Number(r.br_pb5_hp_diff || 0);
  const diffMePb1 = pb1IsMe ? finalDiff(snapsMe) : -finalDiff(snapsMe);
  const diffOppPb1 = pb1IsMe ? finalDiff(snapsOpp) : -finalDiff(snapsOpp);
  const meCloser = Math.abs(diffMePb1 - actualPb1) <= Math.abs(diffOppPb1 - actualPb1);
  snaps = meCloser ? snapsMe : snapsOpp;
  pickedOrder = meCloser ? 'tied → ME-first closer' : 'tied → OPP-first closer';
} else {
  snaps = runOrdering(meFirst);
  pickedOrder = meFirst ? 'ME first' : 'ME second';
}

// Final full run for the action log.
if (meFirst) { attach(game.players[0], a, meWrites, meVaseIds, meSwordplayIds); attach(game.players[1], b, oppWrites, oppVaseIds, oppSwordplayIds); }
else         { attach(game.players[0], b, oppWrites, oppVaseIds, oppSwordplayIds); attach(game.players[1], a, meWrites, meVaseIds, meSwordplayIds); }
game.sim_n_turns(64);

console.log(`=== R${r.round} · ${pickedOrder} ===`);
console.log(`ME  cult=${a.cultivation} hp=${a.hp} phy=${a.physique}/${a.max_physique}`);
console.log(`OPP cult=${b.cultivation} hp=${b.hp} phy=${b.physique}/${b.max_physique}`);
console.log(`\nME deck:`);
console.log(meIds.map((c) => `  ${format_card(c)}`).join('\n'));
console.log(`\nOPP deck:`);
console.log(oppIds.map((c) => `  ${format_card(c)}`).join('\n'));
console.log(`\n=== Per-turn ===`);
console.log(`  T  ME hp/max/phy   OPP hp/max/phy`);
for (const s of snaps) {
  const me = `${s.meHp}/${s.meMax}/${s.mePhy}`;
  const op = `${s.oppHp}/${s.oppMax}/${s.oppPhy}`;
  console.log(`  ${String(s.turn).padStart(2)}  ${me.padEnd(14)} ${op}`);
}
console.log(`\n=== Battle log ===`);
console.log(game.output.join('\n'));
