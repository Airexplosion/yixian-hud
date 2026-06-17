// ui.js — renders the view-model pushed from Python and wires the title-bar
// controls. State flows one way: Python → window.onState(vm). Controls call
// back into Python via window.pywebview.api.*.

'use strict';

const $ = (id) => document.getElementById(id);
const BOARD_SLOTS = 8;

let settings = { damageMode: 'matchup', rollMode: 'average', onTop: true,
                 recommend: true };
let lastVM = null;
let lastStateAt = 0;

// ── Rendering ──────────────────────────────────────────────────────────────
function lvTag(level) {
  return level && level > 1 ? ` <span class="lv">lv${level}</span>` : '';
}

function renderBoard(el, board, unlocked) {
  el.innerHTML = '';
  const slots = board || [];
  for (let i = 0; i < BOARD_SLOTS; i++) {
    const card = slots[i];
    const div = document.createElement('div');
    div.className = 'slot';
    if (typeof unlocked === 'number' && i >= unlocked) {
      div.className += ' locked';
      div.textContent = '🔒';
    } else if (!card) {
      div.className += ' empty';
      div.textContent = '·';
    } else {
      div.innerHTML = `${card.name}${lvTag(card.level)}`;
    }
    el.appendChild(div);
  }
}

// Highlight the slot that played the killing/final card in the most recent
// simulated battle. Green if YOU won, red if you lost, gray if undecided. If
// the battle took longer than 8 turns, write the end-turn number in the
// bottom-right of that slot.
function applyBoardHighlight(boardEl, d) {
  if (!boardEl) return;
  for (const slot of boardEl.querySelectorAll('.slot')) {
    slot.classList.remove('played-win', 'played-lose', 'played-draw');
    const tag = slot.querySelector('.end-turn');
    if (tag) tag.remove();
  }
  if (!d || d.lastSlotMe == null) return;
  const i = Number(d.lastSlotMe);
  const slots = boardEl.querySelectorAll('.slot');
  if (!(i >= 0 && i < slots.length)) return;
  const cls = d.outcome === 'win' ? 'played-win'
            : d.outcome === 'lose' ? 'played-lose'
            : d.outcome === 'draw' ? 'played-draw'
            : null;
  if (!cls) return;
  slots[i].classList.add(cls);
  if (d.endTurn && d.endTurn > 8) {
    const tag = document.createElement('span');
    tag.className = 'end-turn';
    tag.textContent = `T${d.endTurn}`;
    slots[i].appendChild(tag);
  }
}

function renderCounter(el, remaining) {
  el.innerHTML = '';
  const entries = Object.entries(remaining || {});
  if (!entries.length) {
    el.innerHTML = '<div class="empty-note">no data yet</div>';
    return;
  }
  entries.sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]));
  for (const [name, n] of entries) {
    const row = document.createElement('div');
    row.className = 'row' + (n <= 1 ? ' low' : '');
    row.innerHTML = `<span class="name">${name}</span><span class="n">${n}</span>`;
    el.appendChild(row);
  }
}

function renderFates(el, names, talents) {
  el.innerHTML = '';
  const list = names || [];
  if (!list.length) { el.style.display = 'none'; return; }
  el.style.display = 'flex';
  // Which fates the sim actually applies (others are display-only).
  const applied = new Set((talents || [])
    .filter((t) => t && t.simulationKind && t.simulationKind !== 'non-combat-or-unsupported')
    .map((t) => t.name));
  // Map English sim-name back to its display index isn't 1:1; just badge each
  // Chinese name and mark the ones that feed the sim.
  let appliedCount = applied.size;
  list.forEach((cn, i) => {
    const chip = document.createElement('span');
    const isApplied = i < (talents || []).length &&
      talents[i] && talents[i].simulationKind &&
      talents[i].simulationKind !== 'non-combat-or-unsupported';
    chip.className = 'fate' + (isApplied ? ' applied' : '');
    chip.textContent = cn;
    chip.title = isApplied ? 'affects damage sim' : 'display only (not simulated)';
    el.appendChild(chip);
  });
}

function renderHand(el, hand, seasonal) {
  el.innerHTML = '';
  const cards = (hand || []).filter(Boolean);
  const parked = (seasonal || []).filter(Boolean);
  if (!cards.length && !parked.length) {
    el.innerHTML = '<div class="empty-note">empty</div>';
    return;
  }
  for (const c of cards) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `${c.name}${lvTag(c.level)}`;
    el.appendChild(chip);
  }
  // 织梦 (dream-vase) sub-row: cards parked in the seasonal holding.
  if (parked.length) {
    const sub = document.createElement('div');
    sub.className = 'hand-sub';
    const label = document.createElement('small');
    label.className = 'sub-label';
    label.textContent = '织梦';
    sub.appendChild(label);
    for (const c of parked) {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.innerHTML = `${c.name}${lvTag(c.level)}`;
      sub.appendChild(chip);
    }
    el.appendChild(sub);
  }
}

function renderDamageResult(d) {
  $('damage-mode-note').textContent = `(${settings.damageMode})`;
  const pillEl = $('result-pill');
  if (!d || d.error || d.first8Turns == null) {
    // R23: damage-total element removed; only the per-turn list + pill render.
    $('damage-turns').innerHTML = d && d.error
      ? `<span class="empty-note">${d.error}</span>` : '';
    pillEl.style.display = 'none';
    applyBoardHighlight($('me-board'), null);
    return;
  }

  // Matchup: emit the WIN @Tn / LOSE @Tn / DRAW chip + highlight the slot.
  if (d.matchup && d.outcome && d.outcome !== 'undecided') {
    let label, cls;
    if (d.outcome === 'win') {
      // Certain win (no RNG) vs a win found by the search (needs the rolls).
      label = `${d.deterministic ? '必胜' : '可赢'} @T${d.endTurn ?? '?'}`;
      cls = 'win';
    } else if (d.outcome === 'lose') { label = `LOSE @T${d.endTurn ?? '?'}`; cls = 'lose'; }
    else { label = `DRAW`; cls = 'draw'; }
    pillEl.className = 'result-pill ' + cls;
    pillEl.textContent = label;
    pillEl.style.display = '';
  } else if (d.matchup) {
    pillEl.className = 'result-pill draw';
    pillEl.textContent = `UNRESOLVED`;
    pillEl.style.display = '';
  } else {
    pillEl.style.display = 'none';
  }

  // Per-turn list, capped at T8 even if the battle ran longer.
  const dealt = (d.cumulativeDamage || []).slice(0, 8);
  $('damage-turns').innerHTML = dealt.map(
    (v, i) => `<span class="turn">T${i + 1} <b>${Math.round(v)}</b></span>`
  ).join('');

  // Highlight the slot the player last played (green if won, red if lost).
  applyBoardHighlight($('me-board'), d.matchup ? d : null);
}

// Build the yisim slot/options payload from a view-model and simulate. Guarded
// by a token so only the latest request updates the panel.
let _simToken = 0;

// Map a view-model card to the slot shape yisim expects.
// `level` is set for both regular and dream cards (regular cards use it);
// `phase` is set equal to level for dream cards (yisim's resolver looks at
// `phase` to pick the right D-variant — without it dream cards all collapse
// to phase 1 and damage looks wrong).
// `isDream` tells yisim's isDreamSlot check directly (the engine also detects
// dream cards by the 梦 name prefix as a fallback).
function slotFromCard(c) {
  const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
  return isDream
    ? { name: c.name, level: c.level, phase: c.level, isDream: true }
    : { name: c.name, level: c.level, isDream: false };
}
async function updateDamage(vm) {
  if (!window.yisim || !vm || !vm.me) return;
  const me = vm.me;
  // 灵羽 (Spirit Feather) on board with no eligible lv1 merge target → yisim
  // has no implementation for it, so the damage sim would silently treat it
  // as 普通攻击 (3 dmg/turn) and under-count damage. Surface this explicitly
  // instead of running the sim with bad data.
  if (Array.isArray(me.lingyuUnresolved) && me.lingyuUnresolved.length > 0) {
    renderDamageResult({ error: '未识别卡片 (灵羽) — 伤害计算不可用' });
    return;
  }

  // Deck size = unlocked board slots (locked slots are excluded by the slice).
  // Empty UNLOCKED slots stay as nulls so yisim plays them as 普通攻击
  // (Normal Attack, 3 dmg/turn) — that matches what the real game does for
  // unfilled-but-unlocked slots.
  const deckSlots = me.unlocked || 8;
  // Dream cards (梦•X) use `phase` (1..5) instead of `level` to pick the
  // right variant inside yisim. For regular cards `level` is what yisim wants.
  // Pass BOTH so the engine resolves correctly either way.
  const slots = (me.board || []).slice(0, deckSlots).map(
    (c) => (c ? slotFromCard(c) : null)
  );
  const opts = {
    rollMode: settings.rollMode || 'average',
    deckSlots,
    maxTurns: 64,
    playerState: {
      hp: me.hp, maxHp: me.hp,
      physique: me.tipo || 0, maxPhysique: me.tipo || 0,
      cultivation: me.xiuwei || 0,
    },
    talents: (me.fates || []),
    mode: settings.damageMode,
  };
  if (settings.damageMode === 'matchup' && vm.opponent && vm.opponent.board) {
    const opp = vm.opponent;
    const oppDeckSlots = opp.unlocked || deckSlots;
    opts.opponentSlots = (opp.board || []).slice(0, oppDeckSlots).map(
      (c) => (c ? slotFromCard(c) : null)
    );
    opts.opponentState = {
      hp: opp.hp, maxHp: opp.hp,
      physique: opp.tipo || 0, maxPhysique: opp.tipo || 0,
      cultivation: opp.xiuwei || 0,
    };
    // R26: opponent fates now flow through yisim too. proxy_view emits
    // `opp.fates` in the same talent-object shape as `me.fates`, so the
    // simulator's normalizeTalents accepts it directly.
    opts.opponentTalents = (opp.fates || []);
  }
  const token = ++_simToken;
  try {
    const result = await window.yisim.simulate(slots, opts);
    if (token === _simToken) renderDamageResult(result);
  } catch (e) {
    if (token === _simToken) renderDamageResult({ error: String(e) });
  }
}

function renderDamage(vm) {
  $('damage-mode-note').textContent = `(${settings.damageMode})`;
  updateDamage(vm);
}

// ── 推荐摆法 (recommend.js) ─────────────────────────────────────────────────
// Heavy (~2-3s) local search, so: debounce, dedupe by an input hash (recompute
// only when board/hand/opponent/stats actually change), and cancel stale runs.
let _recToken = 0;
let _recSignal = null;
let _recTimer = null;
let _recLastKey = '';

function recInputKey(vm) {
  const me = vm.me || {}, opp = vm.opponent || {};
  // Pool = board + hand as an ORDER-INDEPENDENT multiset. Moving a card between
  // hand and board (i.e. following the recommendation) leaves the set
  // unchanged, so the recommendation stays put. It only recomputes when the
  // actual set of available cards changes (draw / reroll / refine / new round).
  const poolKey = []
    .concat((me.board || []).filter(Boolean), (me.hand || []).filter(Boolean))
    .map((c) => `${c.name}@${c.level || 1}`).sort().join(',');
  const oppKey = (opp.board || []).map((c) => (c ? `${c.name}@${c.level || 1}` : '_')).join(',');
  return [
    me.unlocked, poolKey,
    me.hp, me.tipo, me.xiuwei, (me.fates || []).length,
    settings.damageMode === 'solo' ? 'solo' : 'mu',
    oppKey, opp.hp, opp.tipo, opp.xiuwei, opp.boardFromRound,
  ].join('|');
}

function renderSlots(slots) {
  return (slots || []).map((c, i) => {
    const pos = `<span class="pos">${i + 1}</span>`;
    if (!c) return `<span class="rec-slot normal">${pos}普攻</span>`;
    const lv = c.level && c.level > 1 ? `<span class="lv">lv${c.level}</span>` : '';
    return `<span class="rec-slot">${pos}${c.name}${lv}</span>`;
  }).join('');
}

// Format the win/lose verdict of a matchup result into {html, cls}.
// The engine now win-SEEKS (runs up to 1000 sims, stops at the first win and
// reports that line; otherwise the closest run). So:
//   • deterministic deck → 必胜 / 必败 (the outcome is certain)
//   • RNG deck, a win was found → 可赢 (achievable with the right rolls)
//   • RNG deck, no win in 1000 → 难赢 (couldn't find one; shows closest gap)
function verdictTag(r) {
  if (!r) return { html: '—', cls: '' };
  const kt = r.killTurn ? `第${r.killTurn}轮杀` : '';
  const won = r.outcome === 'win';
  if (r.deterministic) {
    if (won) return { html: `必胜 ${kt}`, cls: '' };
    return { html: `必败 · 还差${r.damageGap}伤害`, cls: ' bad' };
  }
  if (won) return { html: `可赢 ${kt} <span class="rec-note">看运气</span>`, cls: ' low' };
  return { html: `难赢 · 最少还差${r.damageGap}伤害`, cls: ' bad' };
}

function recBlock(title, tagHtml, noteHtml, slots) {
  return `<div class="rec-block">
      <div class="rec-head"><span class="rec-title">${title}</span>
        ${tagHtml}${noteHtml ? `<span class="rec-note">${noteHtml}</span>` : ''}</div>
      <div class="rec-slots">${renderSlots(slots)}</div>
    </div>`;
}

function renderRecommend(rec) {
  const body = $('rec-body');
  if (!body) return;
  if (!rec) { body.innerHTML = '<div class="rec-empty">无手牌数据</div>'; return; }
  const blocks = [];

  // Turn-order banner (from cultivation).
  if (rec.turnOrder) {
    blocks.push(`<div class="rec-order">⚔ ${rec.turnOrder}</div>`);
  }

  if (rec.beatOpponent) {
    const v = verdictTag(rec.beatOpponent);
    const rtag = rec.oppRound ? `对方R${rec.oppRound}牌面` : '对方上轮牌面';
    blocks.push(recBlock('打赢上轮',
      `<span class="rec-win${v.cls}">${v.html}</span>`, rtag, rec.beatOpponent.slots));
  }

  // Same board under the opposite turn order (one short line, no board).
  if (rec.altOrder) {
    const v = verdictTag(rec.altOrder);
    blocks.push(
      `<div class="rec-alt"><span class="rec-title2">${rec.altOrder.label}</span>
        <span class="rec-win${v.cls}">${v.html}</span>
        <span class="rec-note">(同一套牌)</span></div>`);
  }

  if (rec.stableKill) {
    const v = verdictTag(rec.stableKill);
    blocks.push(recBlock('稳杀',
      `<span class="rec-win${v.cls}">${v.html}</span>`, '对手按下轮增强估算', rec.stableKill.slots));
  }

  if (rec.damageMax) {
    const d = rec.damageMax;
    blocks.push(recBlock('伤害最大',
      `<span class="rec-dmg">${d.damage ?? '—'}</span>`, '前8回合 · 当前手牌', d.slots));
  }

  if (!rec.beatOpponent && !rec.damageMax) {
    body.innerHTML = '<div class="rec-empty">无可摆放的牌</div>';
    return;
  }
  body.innerHTML = blocks.join('');
}

function applyRecommendVisibility() {
  const card = $('recommend-card');
  if (card) card.style.display = settings.recommend === false ? 'none' : '';
}

function scheduleRecommend(vm) {
  if (settings.recommend === false) return; // feature toggled off
  if (!window.recommendBoard || !vm || !vm.me) return;
  const pool = [].concat((vm.me.board || []).filter(Boolean),
                         (vm.me.hand || []).filter(Boolean));
  if (!pool.length) { renderRecommend(null); _recLastKey = ''; return; }
  const key = recInputKey(vm);
  if (key === _recLastKey) return; // inputs unchanged → keep current panel
  _recLastKey = key;
  $('rec-status').textContent = '计算中…';
  clearTimeout(_recTimer);
  _recTimer = setTimeout(() => runRecommend(vm), 500);
}

async function runRecommend(vm) {
  if (_recSignal) _recSignal.cancelled = true; // cancel any in-flight run
  const signal = { cancelled: false };
  _recSignal = signal;
  const token = ++_recToken;
  try {
    // No fixed budget → recommend.js auto-scales it to the board size.
    const rec = await window.recommendBoard(vm, {
      settings, qualityMul: Number(settings.recommendQuality) || 1, signal });
    if (token !== _recToken || signal.cancelled) return;
    $('rec-status').textContent = rec && rec.meta
      ? `(${rec.meta.slotCount}格 · ${rec.meta.poolSize}张候选)` : '';
    renderRecommend(rec);
    // Hand the latest recommendation to the auto-play coordinator (Python).
    try {
      const a = window.pywebview && window.pywebview.api;
      if (a && a.report_recommendation) a.report_recommendation(rec);
    } catch (_) {}
  } catch (e) {
    if (token === _recToken) {
      $('rec-status').textContent = '';
      const body = $('rec-body');
      if (body) body.innerHTML = `<div class="rec-empty">推荐失败: ${String(e)}</div>`;
    }
  } finally {
    if (typeof fitWindowToContent === 'function') fitWindowToContent();
  }
}

function render(vm) {
  if (!vm) return;
  $('round-label').textContent = `Round ${vm.round ?? '—'}`;
  $('phase-label').textContent = vm.phase || '';

  // YOU / OPPONENT / HAND sections were removed from the main window — they
  // now live exclusively in the counter window. Each $() lookup is guarded
  // because the elements may not exist in this layout.
  const me = vm.me || {};
  const opp = vm.opponent || {};
  const meHpStr = me.hp == null ? '—' : (me.hpIsPredicted ? `~${me.hp}` : `${me.hp}`);
  const meStats = $('me-stats');
  if (meStats) meStats.textContent = me.destiny != null
    ? `命${me.destiny} · HP${meHpStr} · 修${me.xiuwei ?? 0} · 体${me.tipo ?? 0} · 境${me.realm_tier ?? 1} · 转${me.rerolls ?? '—'}`
    : '';
  const meFates = $('me-fates'); if (meFates) renderFates(meFates, me.fateNames, me.fates);
  const meBoard = $('me-board'); if (meBoard) renderBoard(meBoard, me.board, me.unlocked);
  const handList = $('hand-list'); if (handList) renderHand(handList, me.hand, me.seasonal);

  const boardSrc = opp.boardFromRound ? `current board R${opp.boardFromRound}` : 'no board yet';
  const oppHpStr = opp.hp == null ? '—' : (opp.hpIsPredicted ? `~${opp.hp}` : `${opp.hp}`);
  const oppStats = $('opp-stats');
  if (oppStats) oppStats.textContent = opp.destiny != null
    ? `命${opp.destiny} · HP${oppHpStr} · 修${opp.xiuwei ?? 0} · 体${opp.tipo ?? 0} · 境${opp.realm_tier ?? 1} · ${opp.phase || vm.phase || ''} · ${boardSrc}`
    : '';
  const oppFates = $('opp-fates'); if (oppFates) renderOppFates(oppFates, opp.fateNames, opp.fates);
  const oppBoard = $('opp-board'); if (oppBoard) renderBoard(oppBoard, opp.board, opp.unlocked);

  // Counter lives in a separate window (web/counter.html). Skip rendering it
  // here if the counter-list element is absent in this layout.
  const counterEl = $('counter-list');
  if (counterEl) renderCounter(counterEl, (vm.counter || {}).remaining);
  renderDamage(vm);
  scheduleRecommend(vm);
  fitWindowToContent();
}

// ── Window auto-resize ─────────────────────────────────────────────────────
// After each render we ask the OS window to match the content's natural
// height (titlebar + visible cards). Width stays fixed at FIXED_WIDTH; the
// user can drag the window around but not resize it (frameless = no edge
// handles). Mirrors the lite version and the companion counter window.
// Height now follows the natural content height (measured each render) so the
// window grows for the 推荐摆法 panel and shrinks when it's empty. Width is
// fixed, so there's no width→height reflow feedback loop.
const FIXED_WIDTH = 360;
let lastResizeH = -1;
let resizePending = false;
let currentUiScale = 1.0;

// Grow the OS window to fit the natural content height. Width is fixed, so
// there's no width→height reflow feedback loop (the reason an earlier version
// hard-coded the height). Measuring scrollHeight lets the window expand for the
// 推荐摆法 panel and shrink back when it's empty.
function fitWindowToContent() {
  if (resizePending) return;
  resizePending = true;
  requestAnimationFrame(async () => {
    resizePending = false;
    const w = Math.round(FIXED_WIDTH * currentUiScale);
    let natural;
    if (document.body.classList.contains('collapsed')) {
      const bar = document.getElementById('titlebar');
      natural = bar ? bar.offsetHeight : 40;
    } else {
      const bar = document.getElementById('titlebar');
      const content = document.getElementById('content');
      natural = (bar ? bar.offsetHeight : 0) + (content ? content.scrollHeight : 0) + 10;
    }
    const h = Math.max(40, Math.min(1400, Math.round(natural * currentUiScale)));
    if (h === lastResizeH) return;
    lastResizeH = h;
    const a = window.pywebview && window.pywebview.api;
    if (a) {
      try { await a.resize_main(w, h); } catch (_) {}
    }
  });
}

// Opponent fate row — same chips as renderFates, but if the list is empty
// show a single "fates: unknown" placeholder chip (the protobuf doesn't
// expose other players' fate picks).
function renderOppFates(el, names, talents) {
  el.innerHTML = '';
  el.style.display = 'flex';
  if (!names || !names.length) {
    const chip = document.createElement('span');
    chip.className = 'fate unknown';
    chip.textContent = 'fates: unknown';
    chip.title = "the protobuf doesn't expose other players' chosen fates";
    el.appendChild(chip);
    return;
  }
  renderFates(el, names, talents);
}

// ── State entry point (called from Python) ───────────────────────────────────
window.onState = function (vm) {
  lastVM = vm;
  lastStateAt = Date.now();
  $('status-dot').className = 'dot live';
  try { render(vm); } catch (e) { console.error('render failed', e); }
};

// Mark the proxy connection stale if no state arrives for a while.
setInterval(() => {
  if (!lastStateAt) return;
  const age = Date.now() - lastStateAt;
  const dot = $('status-dot');
  dot.className = 'dot ' + (age > 8000 ? 'stale' : 'live');
}, 2000);

// ── Controls ─────────────────────────────────────────────────────────────────
async function api() {
  // pywebview injects window.pywebview.api asynchronously.
  return (window.pywebview && window.pywebview.api) || null;
}

function applyModeButton() {
  $('btn-mode').textContent = settings.damageMode;
}

window.addEventListener('pywebviewready', async () => {
  const a = await api();
  if (a) {
    try { settings = await a.get_settings(); } catch (_) {}
  }
  applyModeButton();
  applyRecButton();
  applyRecommendVisibility();
  // After settings load, apply the persisted UI scale (set by the
  // bottom-right resize handle in a previous session).
  if (typeof window.applyUiScale === 'function') {
    window.applyUiScale(Number(settings.uiScale) || 1.0);
  }
});

$('btn-mode').addEventListener('click', async () => {
  settings.damageMode = settings.damageMode === 'matchup' ? 'solo' : 'matchup';
  applyModeButton();
  const a = await api();
  if (a) a.set_setting('damageMode', settings.damageMode);
  if (lastVM) renderDamage(lastVM); // M5: re-simulate; for now just relabel
});

function applyRecButton() {
  const b = $('btn-rec');
  if (b) b.style.opacity = settings.recommend === false ? '0.4' : '1';
}

$('btn-rec').addEventListener('click', async () => {
  settings.recommend = settings.recommend === false ? true : false;
  applyRecButton();
  applyRecommendVisibility();
  const a = await api();
  if (a) a.set_setting('recommend', settings.recommend);
  if (settings.recommend) {
    _recLastKey = '';                    // force a fresh compute
    if (lastVM) scheduleRecommend(lastVM);
  } else {
    clearTimeout(_recTimer);
    if (_recSignal) _recSignal.cancelled = true; // stop any in-flight run
  }
  fitWindowToContent();
});

// ── 自动打牌 master switch (green = armed) ────────────────────────────────────
function applyAutoButton(on) {
  const b = $('btn-auto');
  if (!b) return;
  b.style.color = on ? '#4ade80' : '';
  b.style.opacity = on ? '1' : '0.5';
  b.style.fontWeight = on ? '700' : '';
  b.textContent = on ? '自●' : '自';
  b.title = on ? '自动打牌: 开 (点击关闭)' : '自动打牌: 关 (点击开启)';
}

$('btn-auto').addEventListener('click', async () => {
  const a = await api();
  if (!a || !a.toggle_autoplay) return;
  try { applyAutoButton(await a.toggle_autoplay()); } catch (e) {}
});

(async () => {
  const a = await api();
  let on = false;
  if (a && a.autoplay_enabled) { try { on = await a.autoplay_enabled(); } catch (e) {} }
  applyAutoButton(on);
})();

$('btn-pin').addEventListener('click', async () => {
  settings.onTop = !settings.onTop;
  $('btn-pin').style.opacity = settings.onTop ? '1' : '0.4';
  const a = await api();
  if (a) { a.set_setting('onTop', settings.onTop); a.set_on_top(settings.onTop); }
});

$('btn-quit').addEventListener('click', async () => {
  const a = await api();
  if (a) a.quit();
});

// ── Minimize: collapse the body to just the titlebar (Ctrl+H or − button) ───
let _collapsed = false;
async function toggleCollapse() {
  _collapsed = !_collapsed;
  document.body.classList.toggle('collapsed', _collapsed);
  const a = await api();
  if (a && a.set_collapsed) a.set_collapsed(_collapsed);
}
$('btn-min').addEventListener('click', toggleCollapse);
window.addEventListener('keydown', (e) => {
  // Ctrl+H toggles collapse. Avoid swallowing the keystroke when the user
  // intends an input combo (we have no inputs, but be polite).
  if (e.ctrlKey && !e.altKey && !e.metaKey && e.key && e.key.toLowerCase() === 'h') {
    e.preventDefault();
    toggleCollapse();
  }
});

// ── Window dragging via the title bar ────────────────────────────────────────
// WebView2 ignores -webkit-app-region, so we move the native window ourselves:
// on title-bar mousedown we record the grab offset within the window, then on
// each mousemove move the window so the cursor keeps that same offset. Moves
// are coalesced to one per animation frame to keep the JS↔Python bridge light.
(function setupDrag() {
  const bar = $('titlebar');
  let dragging = false;
  let grabX = 0, grabY = 0;
  let pending = null, rafId = 0;

  function flush() {
    rafId = 0;
    if (!pending) return;
    const { x, y } = pending;
    pending = null;
    const a = window.pywebview && window.pywebview.api;
    if (a) a.move(x, y);
  }

  bar.addEventListener('mousedown', (e) => {
    // Ignore clicks on the control buttons.
    if (e.target.closest('.tbtn')) return;
    if (e.button !== 0) return;
    dragging = true;
    grabX = e.clientX;
    grabY = e.clientY;
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    pending = { x: Math.round(e.screenX - grabX), y: Math.round(e.screenY - grabY) };
    if (!rafId) rafId = requestAnimationFrame(flush);
  });

  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('blur', () => { dragging = false; });
})();

// ── Bottom-right resize handle ─────────────────────────────────────────
// Apply CSS zoom to scale the entire UI proportionally, then resize the OS
// window to match. Aspect ratio is preserved automatically because zoom
// scales all dimensions uniformly. Scale is persisted via the settings API
// so it survives restarts. Clamped to [0.6, 2.5] — below 0.6 controls
// become unreadable, above 2.5 the window outgrows typical monitors.
(function setupResize() {
  const handle = $('resize-handle');
  if (!handle) return;
  const MIN_SCALE = 0.6, MAX_SCALE = 2.5;
  // Pixels-per-scale-unit: 250px of diagonal drag = +1.0 to scale.
  const SENSITIVITY = 250;

  let uiScale = 1.0;

  function applyScale(s) {
    s = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    uiScale = s;
    currentUiScale = s;  // module-level so fitWindowToContent picks it up
    // Use zoom on body — Chromium/WebView2 scales layout visually.
    document.body.style.zoom = String(s);
    lastResizeH = -1;
    fitWindowToContent();
    return s;
  }

  // Exposed so the pywebview-ready handler can apply the persisted scale
  // once settings load (which happens AFTER this IIFE runs).
  window.applyUiScale = applyScale;

  let dragging = false, startX = 0, startY = 0, startScale = 1;
  handle.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    startX = e.screenX;
    startY = e.screenY;
    startScale = uiScale;
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    // Use the diagonal — bottom-right drag in either axis grows the window.
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    const delta = (dx + dy) / 2 / SENSITIVITY;
    applyScale(startScale + delta);
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    // Persist the new scale so the next launch starts at the same size.
    const a = window.pywebview && window.pywebview.api;
    if (a && a.set_setting) {
      try { a.set_setting('uiScale', uiScale); } catch (_) {}
    }
  });
  window.addEventListener('blur', () => { dragging = false; });
})();

// ── Auto-update banner ───────────────────────────────────────────────────
// Python's updater.check_for_update_async fires window.onUpdateAvailable
// when Gitee returns a manifest newer than the bundled version. The banner
// stays hidden until then. User clicks "更新" → Python downloads the new
// exe, verifies SHA256, schedules a swap-and-relaunch, exits the process.
window.onUpdateAvailable = function (info) {
  const banner = document.getElementById('update-banner');
  const verEl = document.getElementById('update-version');
  if (!banner || !info) return;
  verEl.textContent = info.version ? `v${info.version}` : '';
  banner.style.display = 'flex';
  if (typeof fitWindowToContent === 'function') fitWindowToContent();
};

(function setupUpdate() {
  const btn = document.getElementById('update-btn');
  const dismiss = document.getElementById('update-dismiss');
  const banner = document.getElementById('update-banner');
  if (!btn || !dismiss || !banner) return;

  btn.addEventListener('click', async () => {
    const a = window.pywebview && window.pywebview.api;
    if (!a || !a.start_update) return;
    btn.disabled = true;
    btn.textContent = '下载中…';
    try {
      const res = await a.start_update();
      if (res && res.ok === false) {
        btn.disabled = false;
        btn.textContent = '重试';
        const verEl = document.getElementById('update-version');
        if (verEl) verEl.textContent = `失败: ${res.error || '未知错误'}`;
      }
      // On success the process exits — no follow-up needed.
    } catch (_) {
      btn.disabled = false;
      btn.textContent = '重试';
    }
  });

  dismiss.addEventListener('click', () => {
    banner.style.display = 'none';
    if (typeof fitWindowToContent === 'function') fitWindowToContent();
  });
})();
