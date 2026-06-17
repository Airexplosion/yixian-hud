"""
shadow_state.py
───────────────
Client-side shadow of the user's hand / board / bench.

During the prep phase the server is silent — no GameStatus arrives between
the user's MoveCardReq placements and round end. To give the AI mid-prep
visibility into what's happening, the addon intercepts every relevant
C→S and S→C frame and mutates this shadow accordingly.

On every authoritative GameStatus (or BattleResult / PlayerData) for the
user's game, the addon calls `reset_from_player(...)` which compares the
predicted shadow against the authoritative state, logs any divergence to
proxy_analysis/output/shadow_diff.log, then overwrites the shadow with
the authoritative state. The diff log is the ground-truth feedback for
verifying / debugging our mutation rules.

After every mutation we `shadow_dirty_event.set()`. The game_loop thread
checks this and re-fires the AI with the fresh shadow.

KNOWN BEHAVIOUR (verified 2026-05-14):
- HAND comes from `field 200.7` — that's the user's actual hand
  (the card row visible in the UI), an instance list that includes
  DUPLICATES. We previously called this "bench" — wrong. The cards
  there CAN be PLACEd onto the board.

- Field 103 is a unique-names SUMMARY: one entry per distinct card
  name, no duplicates. Use it only as a fallback when 200.7 is empty
  (true only at round 1 of a fresh game, before the server has
  materialized the instance list). At round 1 we may miss duplicates
  that the client UI shows — accepted limitation; corrected on the
  round 2 GameStatus.

- BOARD lives in `field 200.6` (8 slots, 0 = empty). Includes
  duplicates as separate instances.

- PLACE source resolution: pop from `shadow.hand` (which IS 200.7
  when populated). No separate "bench" zone.

- Level is encoded in the card_id, not in the raw[2] field. Same-name
  variants differ by +10000 per level. Decoded in
  game_state.level_from_card_id.
"""
import datetime
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

BOARD_SLOTS = 8

# Zone codes used by MoveCardReq / CardOperation fields [src_zone, src_slot,
# dst_zone, dst_slot]. Decoded from real captures (2026-05-22):
#   0 = hand, 1 = board, 9 = seasonal holding ("the other place" you can park a
#   card in and take back). Any other zone is treated as generic holding so
#   cards are never lost. Slots are 0-indexed; dst_slot == -1 → append to hand.
ZONE_HAND = 0
ZONE_BOARD = 1
ZONE_SEASONAL = 9


# Breakthrough 修为/体魄 thresholds per realm tier (1-indexed).
# Tier T can breakthrough when 修为 >= THRESHOLDS[T-1] OR 体魄 >= same.
# Tier 5 is the max — no further breakthrough.
THRESHOLDS = [9, 21, 36, 55]


def breakthrough_status(realm_tier: int, xiuwei: int, tipo: int):
    """Return (available, threshold, gate_met).
      available  — True if a breakthrough can be done now.
      threshold  — 修为/体魄 value needed for the current tier, or None at max tier.
      gate_met   — "修为" / "体魄" / "" describing which gate (if any) is satisfied.
    """
    if not (isinstance(realm_tier, int) and 1 <= realm_tier <= len(THRESHOLDS)):
        return (False, None, "")
    threshold = THRESHOLDS[realm_tier - 1]
    if xiuwei >= threshold:
        return (True, threshold, "修为")
    if tipo >= threshold:
        return (True, threshold, "体魄")
    return (False, threshold, "")


def unlocked_board_slots(round_num: int) -> int:
    """How many of the 8 board slots are unlocked in the given round.
    Per the user: round 1 = 3 slots, +1 each round, capped at 8.
    Round 6 and onward have the full board."""
    if not isinstance(round_num, int) or round_num <= 0:
        return BOARD_SLOTS  # unknown round → don't artificially restrict
    return max(1, min(round_num + 2, BOARD_SLOTS))

# Area-code hypotheses for MoveCardReq field 2. Confirmed/refined as
# shadow_diff.log surfaces mismatches.
AREA_BOARD = 3
AREA_HAND  = 2
AREA_BENCH = 4
AREA_SHOP  = 5
AREA_UNK_1 = 1   # appears only in {1,2,3,4} full-move shape; treat as board

# Career / school IDs sent in SelectCareerReq {1: <id>}. Mapping confirmed by
# the user on 2026-05-13.
CAREER_NAMES = {
    1: "炼丹师",
    2: "符咒师",
    3: "琴师",
    4: "画师",
    5: "阵法师",
    6: "灵植师",
    7: "命理师",
}


def career_name(career_id: int) -> str:
    """Return the human-readable school name for a career id (1-7), or a
    fallback like `career#9` for unknown ids."""
    return CAREER_NAMES.get(career_id, f"career#{career_id}")


def career_id_from_name(name: str) -> int:
    """Inverse lookup. Returns 0 if the name isn't recognised."""
    if not name:
        return 0
    n = name.strip()
    for cid, school in CAREER_NAMES.items():
        if school == n:
            return cid
    return 0

# Path for the shadow-diff log (created lazily).
_DIFF_LOG_PATH = Path(__file__).resolve().parent.parent / "proxy_analysis" / "output" / "shadow_diff.log"

# Fate / talent ("天命") name catalog — extracted from the game's
# TalentConfig asset by extract_fates.py. {fate_id: name}.
_FATE_MAP_FILE = Path(__file__).resolve().parent / "fate_id_map.json"
_fate_map_cache: dict | None = None


def _load_fate_map() -> dict:
    global _fate_map_cache
    if _fate_map_cache is None:
        try:
            with _FATE_MAP_FILE.open(encoding="utf-8") as f:
                _fate_map_cache = {int(k): v for k, v in json.load(f).items()}
        except Exception:
            _fate_map_cache = {}
    return _fate_map_cache


def fate_name(fate_id: int) -> str:
    """Return the fate/talent name for an id, or `#<id>` if unknown."""
    return _load_fate_map().get(fate_id, f"#{fate_id}")

# Path for the per-action shadow trace (created lazily). Each _log_state()
# call appends 4 lines: action description + hand + board + bench.
_TRACE_LOG_PATH = Path(__file__).resolve().parent / "output" / "shadow_log.txt"

# Optional second target — set by addon._open_battle_log_dir() in DEBUG mode
# so the trace is ALSO written into the per-game battle_log/<timestamp>/ folder.
# Default None = single-target (legacy behavior).
_DEBUG_TRACE_LOG_PATH: Path | None = None


def set_debug_trace_log_path(path: Path | None) -> None:
    """Toggle the per-game debug shadow_log destination. When set to a Path,
    every _log_state() write is mirrored there (in addition to the default
    path). Setting to None disables the mirror."""
    global _DEBUG_TRACE_LOG_PATH
    _DEBUG_TRACE_LOG_PATH = path


@dataclass
class ZoneCard:
    id: int
    name: str
    level: int = 1

    def __str__(self):
        lvl = f" lv{self.level}" if self.level > 1 else ""
        return f"{self.name}{lvl}"

    def signature(self) -> tuple:
        return (self.id, self.level)


@dataclass
class ShadowPlayerState:
    hand:  list = field(default_factory=list)   # list[ZoneCard], ordered, variable
    board: list = field(default_factory=lambda: [None] * BOARD_SLOTS)
    bench: list = field(default_factory=list)   # list[ZoneCard], ordered, variable
    # Cards parked in a non-hand/non-board zone (e.g. the seasonal "other place"),
    # keyed by (zone, slot). Still owned by the player; restored on move-back.
    seasonal: dict = field(default_factory=dict)
    xiuwei: int = 0       # 修为 (cultivation) — live: snapshot + 1 per absorb
    tipo: int = 0         # 体魄 (physique)    — snapshot from GameStatus
    realm_tier: int = 1   # 境界 (realm tier)  — 1..5
    rerolls: int = 0      # reroll-remaining — re-seeded each round from auth
    round_num: int = 0    # current round — sets the unlocked board-slot limit

    def empty_board_slots(self) -> list:
        return [i + 1 for i, c in enumerate(self.board) if c is None]

    def board_signature(self) -> tuple:
        return tuple((c.signature() if c else None) for c in self.board)

    def hand_signature(self) -> tuple:
        return tuple(c.signature() for c in self.hand if c is not None)

    def full_signature(self) -> tuple:
        return (self.hand_signature(), self.board_signature(),
                tuple(c.signature() for c in self.bench if c is not None),
                tuple(sorted((k, v.signature()) for k, v in self.seasonal.items())))


# ── Module-level shared state ────────────────────────────────────────────────
shadow: ShadowPlayerState | None = None
shadow_lock = threading.Lock()
shadow_dirty_event = threading.Event()


@dataclass
class PendingChoice:
    """Set when the game is waiting for the user to make a discrete pick.

    Three known triggers:
    - kind="class"  → round 2 (and possibly other rounds): pick a career id.
                      Options are implicit (1..N).
    - kind="daoyun" → PendingDaoYunResp from server lists 2-3 card options
                      the user must pick one of.
    - kind="fate"   → PendingTalentResp after a breakthrough lists 4 fate
                      (天命) options; the user picks one.
    """
    kind: str                       # "class" | "daoyun" | "fate"
    options: list                   # list of ZoneCard for "daoyun"; list[int] for "class"
    prompt_text: str = ""           # human-readable label for the AI


pending_choice: PendingChoice | None = None
pending_choice_lock = threading.Lock()


def set_pending_choice(choice: PendingChoice):
    """Record that the user needs to pick something. Cleared on PlayerData
    (which arrives after the choice is committed) or on a new GameStatus."""
    global pending_choice
    with pending_choice_lock:
        pending_choice = choice
    shadow_dirty_event.set()


def clear_pending_choice():
    global pending_choice
    with pending_choice_lock:
        if pending_choice is not None:
            pending_choice = None
            shadow_dirty_event.set()


def get_pending_choice() -> "PendingChoice | None":
    with pending_choice_lock:
        return pending_choice


# ── Career / sidejob pick confirmation ───────────────────────────────────────
# The addon records every C→S SelectCareerReq here so the executor can verify
# a class/sidejob click actually committed the intended career.
last_career_pick: int = 0
# Secondary careers chosen via the 副职兼修 fate. The fate can be picked at
# multiple breakthroughs (phase 2 / 3 / 4 / 5), each granting its own
# additional sidejob. Each entry is {"career_id": int, "phase": int} where
# `phase` is the breakthrough phase at which 副职兼修 was picked (2-5).
# Phase matters because 副职兼修 only adds cards of that phase and above —
# the realm-1 starter cards of the secondary career are NOT granted.
secondary_career_picks: list = []
# Phase of the most recently picked 副职兼修 fate, captured when the fate is
# confirmed via SimpleClientPact. Consumed by the next SelectCareerReq that
# has field 3=1 (the secondary career pick that immediately follows).
_pending_secondary_phase: int = 0
career_pick_event = threading.Event()


# Base fate id for 副职兼修 (the per-phase variants are at +10000 / +20000 /
# +30000 — fate_id 188 = phase 2, 10188 = phase 3, 20188 = phase 4, 30188 =
# phase 5). Used to detect the fate pick and derive the phase from id.
_FUZHIJIANXIU_BASE_ID = 188


def note_fate_pick(fate_id: int):
    """Called by addon._handle_simple_client_pact when a breakthrough fate is
    confirmed. If the fate is 副职兼修, captures the phase (derived from the
    fate id's per-phase offset) so the immediately-following SelectCareerReq
    with field 3=1 knows what phase to record on the secondary pick."""
    global _pending_secondary_phase
    if not isinstance(fate_id, int) or fate_id <= 0:
        return
    base = fate_id % 10000
    if base != _FUZHIJIANXIU_BASE_ID:
        return
    # phase 2 = base, phase 3 = +10000, phase 4 = +20000, phase 5 = +30000
    _pending_secondary_phase = (fate_id // 10000) + 2


def note_career_pick(career_id: int, secondary: bool = False):
    """Called by the addon when a SelectCareerReq is observed.
    `secondary=True` when the wire's field 3 is set (the 副职兼修 secondary
    pick). Each secondary pick records the phase from the preceding
    `note_fate_pick(副职兼修)` so the counter can phase-filter cards correctly.
    Primary pick resets the secondary list (new game / character reset)."""
    global last_career_pick, secondary_career_picks, _pending_secondary_phase
    cid = int(career_id or 0)
    if secondary:
        if cid:
            phase = _pending_secondary_phase or 2
            secondary_career_picks.append({"career_id": cid, "phase": phase})
        _pending_secondary_phase = 0  # consume regardless
    else:
        last_career_pick = cid
        # Starting a new game / new primary career: clear all secondary state.
        secondary_career_picks = []
        _pending_secondary_phase = 0
    career_pick_event.set()


def get_career_pick() -> int:
    """The career id of the most recently observed PRIMARY SelectCareerReq
    (0 = none). Use `get_secondary_career_picks()` for the 副职兼修 slots."""
    return last_career_pick


def get_secondary_career_picks() -> list:
    """List of secondary career picks via 副职兼修, each as
    {"career_id": int, "phase": int}. Empty if 副职兼修 not picked."""
    return list(secondary_career_picks)


def get_secondary_career_pick() -> int:
    """Backwards-compat: career id of the LAST secondary pick (or 0 if none).
    New code should use `get_secondary_career_picks()` to see all picks."""
    if secondary_career_picks:
        return secondary_career_picks[-1].get("career_id", 0)
    return 0


def _log_state(action_desc: str):
    """Print a one-action snapshot of the shadow to stdout (mitmdump terminal)
    AND append the same block to yixian-proxy/output/shadow_log.txt so the
    user can read the trace even if mitmdump terminal scrollback is gone."""
    if shadow is None:
        return
    try:
        hand  = [str(c) for c in shadow.hand]
        board = [str(c) if c else "_" for c in shadow.board]
        bench = [str(c) for c in shadow.bench]
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        lines = [
            f"[{ts}] [shadow] {action_desc}",
            f"                hand:  {hand}",
            f"                board: {board}",
            f"                bench: {bench}",
        ]
        # stdout for mitmdump terminal
        for ln in lines:
            print(ln)
        # also persist to file
        try:
            _TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _TRACE_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass
        # Mirror to per-game debug folder when DEBUG mode is active.
        if _DEBUG_TRACE_LOG_PATH is not None:
            try:
                _DEBUG_TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with _DEBUG_TRACE_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except Exception:
                pass
    except Exception:
        pass


def log_event(line: str):
    """Append a single standalone line to the shadow trace (and stdout).
    For events that aren't a board/hand mutation — e.g. BREAKTHROUGH."""
    try:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        out = f"[{ts}] [shadow] {line}"
        print(out)
        _TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(out + "\n")
        if _DEBUG_TRACE_LOG_PATH is not None:
            try:
                _DEBUG_TRACE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with _DEBUG_TRACE_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(out + "\n")
            except Exception:
                pass
    except Exception:
        pass


# ── Helpers: varint decoding for field 200.6 / 200.7 ─────────────────────────


def decode_varint_list(b) -> list:
    """Decode a packed sequence of protobuf varints into a list of ints.
    Handles None / non-bytes by returning []."""
    if not isinstance(b, (bytes, bytearray)) or not b:
        return []
    out = []
    cur = 0
    shift = 0
    for byte in b:
        cur |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
        else:
            out.append(cur)
            cur = 0
            shift = 0
    return out


def _name_lookup_default(card_id: int) -> str:
    return f"#{card_id}"


# ── Paired Diviner transform cards (天谕 / 天运 / 天命 / 天机 / 天星) ─────────
# Each pair is ONE card with two faces; the user toggles between them by
# placing the card on the board and removing it. The game's wire protocol
# refers to a paired card by whichever face is currently visible, but our
# Counter (and any other code that compares ids) treats the pair as one card
# in a shared deck slot. To make this transparent everywhere downstream, we
# NORMALIZE the id at every wire-entry point in the shadow: the "even" face
# id (天谕·攻 = 11000004 etc.) is rewritten to its "odd" partner (天谕·守 =
# 11000003 etc.) before being stored in any ZoneCard. After this, the shadow
# always reports the canonical face; reroll lookups, hand matching, and
# observation diffs all work uniformly regardless of which physical face
# the user happens to be holding in the game UI.
_DIVINER_EVEN_FACES: set = {
    # 天谕·攻 (paired with 天谕·守 = -1)
    11000004, 11010004, 11020004, 11030004, 11040004,
    # 天运·趋吉 (paired with 天运·避凶 = -1)
    11000008, 11010008, 11020008, 11030008, 11040008,
    # 天命·重现 (paired with 天命·飞逝 = -1)
    11000012, 11010012, 11020012, 11030012, 11040012,
    # 天机·逆施 (paired with 天机·顺应 = -1)
    11000020, 11010020, 11020020, 11030020, 11040020,
    # 天星·御心 (paired with 天星·牵引 = -1)
    11000026, 11010026, 11020026, 11030026, 11040026,
}


def canonical_card_id(card_id: int) -> int:
    """For paired Diviner transform cards, return the canonical (lower-id)
    face. Non-paired cards return unchanged. Applied at all wire→shadow id
    entry points so the shadow stores ONE face per pair regardless of which
    one the game UI is currently showing."""
    cid = int(card_id or 0)
    if cid in _DIVINER_EVEN_FACES:
        return cid - 1
    return cid


def _level_from_id(card_id: int) -> int:
    """Same formula as game_state.level_from_card_id — duplicated here to
    avoid an import cycle. Level = ((id // 10000) % 100) + 1."""
    if not isinstance(card_id, int) or card_id <= 0:
        return 1
    return ((card_id // 10000) % 100) + 1


def parse_board_from_varints(b, name_fn=_name_lookup_default, n_slots: int = BOARD_SLOTS) -> list:
    """Decode the board field into a list of length n_slots.

    Each varint is one board slot: 0 → None (empty), anything else → a
    card. Character-specific cards have small IDs (e.g. 冥心入玄=81,
    万玄破魔掌=82) — there is NO leading status byte. Verified across all
    observed boards: every board field is exactly 8 varints (one per
    slot)."""
    ids = decode_varint_list(b)
    slots: list = []
    for v in ids:
        if v == 0:
            slots.append(None)
        else:
            v = canonical_card_id(v)  # collapse paired Diviner faces to one id
            slots.append(ZoneCard(id=v, name=name_fn(v), level=_level_from_id(v)))
        if len(slots) >= n_slots:
            break
    while len(slots) < n_slots:
        slots.append(None)
    return slots


def parse_bench_from_varints(b, name_fn=_name_lookup_default) -> list:
    """Decode the hand field (200.7 / pb.6.1 / pb.2.1) into a list of
    ZoneCard. The hand is a dense instance list — skip only 0 (padding);
    keep every non-zero id, INCLUDING small-id character cards."""
    ids = decode_varint_list(b)
    out = []
    for v in ids:
        if v == 0:
            continue
        v = canonical_card_id(v)  # collapse paired Diviner faces to one id
        out.append(ZoneCard(id=v, name=name_fn(v), level=_level_from_id(v)))
    return out


# ── Validation / divergence logging ──────────────────────────────────────────


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _log(line: str):
    try:
        _DIFF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DIFF_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _diff_lists(predicted: list, actual: list, label: str) -> str:
    """Return a one-line diff string or '' if equal."""
    if predicted == actual:
        return ""
    p_str = ", ".join(str(c) if c else "_" for c in predicted)
    a_str = ", ".join(str(c) if c else "_" for c in actual)
    return f"[{_ts()}] {label}  predicted=[{p_str}]  actual=[{a_str}]"


def log_divergence(predicted: ShadowPlayerState, actual: ShadowPlayerState):
    """Compare predicted (current shadow) to authoritative (just-parsed) and
    append per-zone mismatches to the diff log."""
    if predicted is None or actual is None:
        return
    for diff in (
        _diff_lists(predicted.hand, actual.hand, "HAND "),
        _diff_lists(predicted.board, actual.board, "BOARD"),
        _diff_lists(predicted.bench, actual.bench, "BENCH"),
    ):
        if diff:
            _log(diff)


def _subtract_multiset(pool: list, *zones) -> list:
    """Return `pool` with one occurrence of each card name in each `zone`
    removed. Preserves the original order of `pool`. Used to compute the
    placement-pending hand: field 103 includes cards on board/bench, so
    the true hand = field 103 minus those zones."""
    counts: dict = {}
    for zone in zones:
        for c in zone:
            if c is None:
                continue
            counts[c.name] = counts.get(c.name, 0) + 1
    out = []
    for c in pool:
        if c is None:
            continue
        if counts.get(c.name, 0) > 0:
            counts[c.name] -= 1
        else:
            out.append(c)
    return out


def reset_from_player(player, name_fn=_name_lookup_default, source: str = "?",
                      team_container: dict | None = None):
    """Authoritative refresh from a parsed PlayerState (game_state.PlayerState).

    Hand+board sourcing priority:
      1. PRIMARY: top-level `pb["6"]` (team_container). `.6.1` is the
         user's hand WITH duplicates; `.6.2` is the board. This is the
         most accurate source — populated at every round including
         round 1 (where 200.7 is empty). Verified against me_uid before
         being passed in.
      2. FALLBACK: `field 200.7` — instance list (duplicates) when
         team_container is absent.
      3. FALLBACK 2: `field 103 - board` for round-1 fresh games where
         both 200.7 and team_container are empty. Loses duplicates.

    Board comes from .6.2 (preferred) or field 200.6.
    """
    global shadow
    raw = getattr(player, "raw", None)
    if raw is None:
        raw = {}
    f200 = raw.get("200", {}) if isinstance(raw, dict) else {}
    if not isinstance(f200, dict):
        f200 = {}

    new_hand = None
    new_board = None

    # PRIMARY: team_container from pb["6"]
    # Present-but-empty hand field ({} from blackboxprotobuf or b"") means
    # the hand is actually empty (e.g. right after a breakthrough cleared
    # it). Treat that as authoritative — don't fall through to the stale
    # f200.7 which lags by a frame.
    if isinstance(team_container, dict):
        b1 = team_container.get("1", b"")
        b2 = team_container.get("2", b"")
        if "1" in team_container:
            if isinstance(b1, (bytes, bytearray)):
                new_hand = parse_bench_from_varints(b1, name_fn=name_fn)
            else:
                new_hand = []
        if isinstance(b2, (bytes, bytearray)):
            new_board = parse_board_from_varints(b2, name_fn=name_fn)

    # FALLBACK: .200.6 / .200.7
    if new_board is None:
        new_board = parse_board_from_varints(f200.get("6", b""), name_fn=name_fn)
    if new_hand is None:
        hand_from_200_7 = parse_bench_from_varints(f200.get("7", b""), name_fn=name_fn)
        if hand_from_200_7:
            new_hand = hand_from_200_7
        else:
            # Fallback 2: round-1 fresh game with neither pb["6"] nor 200.7.
            # Derive from field 103 minus board. Loses duplicates.
            full_pool = [
                ZoneCard(id=canonical_card_id(c.id), name=c.name,
                         level=max(1, c.level))
                for c in (player.cards or [])
            ]
            new_hand = _subtract_multiset(full_pool, new_board)

    new_state = ShadowPlayerState(
        hand=new_hand, board=new_board, bench=[],
        xiuwei=int(getattr(player, "xiuwei", 0) or 0),
        tipo=int(getattr(player, "tipo", 0) or 0),
        realm_tier=int(getattr(player, "realm_tier", 1) or 1),
        rerolls=int(getattr(player, "rerolls", 0) or 0),
    )

    with shadow_lock:
        if shadow is not None:
            log_divergence(shadow, new_state)
            # Carry the seasonal holding across the round reset: cards parked in
            # the seasonal zone return on a later round, so they must survive the
            # authoritative refresh (which otherwise rebuilds an empty seasonal).
            new_state.seasonal = dict(shadow.seasonal)
            new_state.round_num = shadow.round_num   # carry; addon updates on GameStatus
        shadow = new_state
    shadow_dirty_event.set()
    _log_state(f"RESET from {source}")


# ── Mutation helpers — called by addon.py on each observed action ────────────


def _zone(area: int):
    """Return a tuple (kind, ref) where kind is 'hand'|'board'|'bench' and
    ref is the list inside the current shadow. Returns (None, None) if the
    area code is unknown or shadow not initialised.

    AREA_UNK_1 (area=1) is mapped to 'hand': user-confirmed that
    `{2:1, 3:S, 4:D}` is a hand→board PLACE, not a board rearrange.
    """
    if shadow is None:
        return None, None
    if area == AREA_BOARD:
        return "board", shadow.board
    if area in (AREA_HAND, AREA_UNK_1):
        return "hand", shadow.hand
    if area == AREA_BENCH:
        return "bench", shadow.bench
    if area == AREA_SHOP:
        return "hand", shadow.hand  # shop drags treated as hand for now
    return None, None


def _rearrange_shift(zone_list: list, src: int, dst: int):
    """Variant A — pop and re-insert (variable-length zones)."""
    if src < 1 or src > len(zone_list):
        return
    item = zone_list.pop(src - 1)
    insert_idx = max(0, min(dst - 1, len(zone_list)))
    zone_list.insert(insert_idx, item)


def _rearrange_swap(zone_list: list, src: int, dst: int):
    """Variant B — swap two positions (fixed-slot zone)."""
    if not (1 <= src <= len(zone_list) and 1 <= dst <= len(zone_list)):
        return
    zone_list[src - 1], zone_list[dst - 1] = zone_list[dst - 1], zone_list[src - 1]


def _place_hand_to_board(src: int, dst_1indexed):
    """Drop hand[src] onto the board.

    Collision rules (when `dst_1indexed` points at an occupied slot):
      - same name AND same level → MERGE (upgrade that board card, consume hand[src])
      - different card (or same name different level) → DISPLACE
        (existing board card → right end of hand, new card → board slot)
      - empty slot → simple PLACE

    When `dst_1indexed` is None (no explicit slot, user dropped on the
    bench area): look for a same-name+same-level card anywhere on the
    board to MERGE with; otherwise place into the first empty slot.

    Returns a short human-readable action description for logging.
    """
    if not (1 <= src <= len(shadow.hand)):
        return ""
    card = shadow.hand[src - 1]

    # Case A: explicit destination slot
    if isinstance(dst_1indexed, int) and 1 <= dst_1indexed <= len(shadow.board):
        target = shadow.board[dst_1indexed - 1]
        if target is None:
            # Empty → simple PLACE
            shadow.board[dst_1indexed - 1] = card
            shadow.hand.pop(src - 1)
            return f"PLACE → board[{dst_1indexed}]"
        if target.name == card.name and target.level == card.level:
            # Same name + same level → MERGE
            target.id += 10000
            target.level += 1
            shadow.hand.pop(src - 1)
            return f"MERGE into board[{dst_1indexed}] (now {target.name} lv{target.level})"
        # Different card (or different level) → DISPLACE
        shadow.board[dst_1indexed - 1] = card
        shadow.hand.pop(src - 1)
        shadow.hand.append(target)
        return (f"DISPLACE board[{dst_1indexed}]: {target.name}"
                f"{(' lv'+str(target.level)) if target.level>1 else ''} → hand-right, "
                f"{card.name} → board[{dst_1indexed}]")

    # Case B: no explicit destination — try MERGE first, then PLACE first-empty.
    for i, b in enumerate(shadow.board):
        if b is not None and b.name == card.name and b.level == card.level:
            b.id += 10000
            b.level += 1
            shadow.hand.pop(src - 1)
            return f"MERGE into board[{i + 1}] (now {b.name} lv{b.level})"
    for i, b in enumerate(shadow.board):
        if b is None:
            shadow.board[i] = card
            shadow.hand.pop(src - 1)
            return f"PLACE → board[{i + 1}]"
    return ""  # board full


def _apply_unplace(src_field):
    """Best-effort un-place / discard. The user has not given us a firm
    model for the `{1:1, 2:A, 4:-1}` family of shapes, so this is
    approximate — the next GameStatus will authoritatively correct any
    drift via reset_from_player.

    Heuristic: if `src_field` is an int, try to un-place board[src_field]
    (1-indexed). If that slot is empty (or src_field is missing), fall
    back to popping the last non-empty board card (LIFO un-place).
    Un-placed cards go to the right end of the hand (matches the
    DISPLACE convention).
    """
    target_idx = None
    if isinstance(src_field, int) and 1 <= src_field <= len(shadow.board):
        if shadow.board[src_field - 1] is not None:
            target_idx = src_field - 1
    if target_idx is None:
        # LIFO: last non-empty board slot
        for i in range(len(shadow.board) - 1, -1, -1):
            if shadow.board[i] is not None:
                target_idx = i
                break
    if target_idx is None:
        return "UN-PLACE (board empty, nothing to do)"
    card = shadow.board[target_idx]
    shadow.board[target_idx] = None
    shadow.hand.append(card)
    return f"UN-PLACE board[{target_idx + 1}]={card.name} → hand-right"


def _format_pb(pb: dict) -> str:
    """Render a MoveCardReq pb dict in the canonical short form for logging."""
    return "{" + ", ".join(f"{k}:{v}" for k, v in sorted(pb.items())) + "}"


def _hand_to_hand_merge(src_1indexed: int, dst_1indexed=None):
    """Merge hand[src] into another hand card. Wire shapes:
      `{2:A}`      — no explicit target; merge with the first OTHER
                     hand card of the same name + level.
      `{2:A, 4:D}` — explicit target hand[D].

      - target valid (same name + level) → upgrade target
        (id += 10000, level += 1), consume the source.
      - no/invalid target → no-op.
    """
    if not (isinstance(src_1indexed, int) and 1 <= src_1indexed <= len(shadow.hand)):
        return f"HAND→HAND no-op (invalid src hand[{src_1indexed}])"
    src_card = shadow.hand[src_1indexed - 1]
    if src_card is None:
        return f"HAND→HAND no-op (hand[{src_1indexed}] empty)"

    target_idx = None
    if isinstance(dst_1indexed, int) and 1 <= dst_1indexed <= len(shadow.hand):
        # Explicit target
        if dst_1indexed - 1 != src_1indexed - 1:
            t = shadow.hand[dst_1indexed - 1]
            if t is not None and t.name == src_card.name and t.level == src_card.level:
                target_idx = dst_1indexed - 1
    else:
        # Auto-target: first OTHER hand card with same name + level
        for i, c in enumerate(shadow.hand):
            if i == src_1indexed - 1:
                continue
            if c is not None and c.name == src_card.name and c.level == src_card.level:
                target_idx = i
                break

    if target_idx is None:
        return f"HAND→HAND no-op (no same-name+level merge target for hand[{src_1indexed}]={src_card.name})"
    target = shadow.hand[target_idx]
    target.id += 10000
    target.level += 1
    shadow.hand.pop(src_1indexed - 1)
    return (f"MERGE hand[{src_1indexed}]+hand[{target_idx + 1}] "
            f"→ hand[{target_idx + 1}] {target.name} lv{target.level}")


def _board_to_board(src_1indexed: int, dst_1indexed: int):
    """Move board[src] onto board[dst].

      - same name + same level → MERGE (upgrade dst, src becomes empty)
      - different card on dst → SWAP (exchange src ↔ dst)
      - dst empty → simple move (board[src] → board[dst], src empty)
      - src == dst, or invalid → no-op
    """
    if not (isinstance(src_1indexed, int) and 1 <= src_1indexed <= len(shadow.board)):
        return "BOARD→BOARD no-op (invalid src)"
    if not (isinstance(dst_1indexed, int) and 1 <= dst_1indexed <= len(shadow.board)):
        return "BOARD→BOARD no-op (invalid dst)"
    if src_1indexed == dst_1indexed:
        return f"BOARD→BOARD no-op (src=dst=board[{src_1indexed}])"
    src_card = shadow.board[src_1indexed - 1]
    dst_card = shadow.board[dst_1indexed - 1]
    if src_card is None:
        return f"BOARD→BOARD no-op (board[{src_1indexed}] empty)"
    if dst_card is None:
        shadow.board[dst_1indexed - 1] = src_card
        shadow.board[src_1indexed - 1] = None
        return f"MOVE board[{src_1indexed}]={src_card.name} → board[{dst_1indexed}]"
    if src_card.name == dst_card.name and src_card.level == dst_card.level:
        # MERGE — upgrade dst, src becomes empty
        dst_card.id += 10000
        dst_card.level += 1
        shadow.board[src_1indexed - 1] = None
        return f"MERGE board[{src_1indexed}]+board[{dst_1indexed}] → board[{dst_1indexed}] {dst_card.name} lv{dst_card.level}"
    # SWAP
    shadow.board[src_1indexed - 1] = dst_card
    shadow.board[dst_1indexed - 1] = src_card
    return f"SWAP board[{src_1indexed}]↔board[{dst_1indexed}]"


def _board_auto_merge(src_1indexed: int):
    """Board-to-board MERGE with no explicit target. Wire shape
    `{1:1, 2:A, 3:1}` (board source, no f4). board[src] merges with the
    first OTHER board card of the same name + level; the merged lv+1
    card stays at the lower-index slot."""
    if not (isinstance(src_1indexed, int) and 1 <= src_1indexed <= len(shadow.board)):
        return f"BOARD→BOARD no-op (invalid src board[{src_1indexed}])"
    src_card = shadow.board[src_1indexed - 1]
    if src_card is None:
        return f"BOARD→BOARD no-op (board[{src_1indexed}] empty)"
    target_idx = None
    for i, c in enumerate(shadow.board):
        if i == src_1indexed - 1:
            continue
        if c is not None and c.name == src_card.name and c.level == src_card.level:
            target_idx = i
            break
    if target_idx is None:
        return (f"BOARD→BOARD no-op (no same-name+level merge target "
                f"for board[{src_1indexed}]={src_card.name})")
    # Merge into the LOWER-index slot so the result stays put.
    lo, hi = sorted((src_1indexed - 1, target_idx))
    kept = shadow.board[lo]
    kept.id += 10000
    kept.level += 1
    shadow.board[hi] = None
    return (f"MERGE board[{src_1indexed}]+board[{target_idx + 1}] "
            f"→ board[{lo + 1}] {kept.name} lv{kept.level}")


def _zone_take(state, zone: int, slot: int):
    """Remove and return the card at (zone, slot), or None."""
    if zone == ZONE_HAND:
        if 0 <= slot < len(state.hand):
            return state.hand.pop(slot)
        return None
    if zone == ZONE_BOARD:
        if 0 <= slot < len(state.board) and state.board[slot] is not None:
            c = state.board[slot]
            state.board[slot] = None
            return c
        return None
    # seasonal / any other holding zone
    return state.seasonal.pop((zone, slot), None)


def _upgrade(card):
    """Merge result: same card id means same name+level → bump one level."""
    card.id += 10000
    card.level += 1


def _zone_put(state, zone: int, slot: int, card) -> str:
    """Place `card` into (zone, slot), applying MERGE / DISPLACE / PLACE.
    Returns a short description for logging."""
    if card is None:
        return "no-op (nothing to move)"
    if zone == ZONE_HAND:
        if slot == -1 or slot >= len(state.hand):
            state.hand.append(card)
            return f"→ hand[end] {card}"
        tgt = state.hand[slot]
        if tgt is not None and tgt.id == card.id:
            _upgrade(tgt)
            return f"→ MERGE hand[{slot}] = {tgt}"
        state.hand.insert(slot, card)
        return f"→ hand[{slot}] {card}"
    if zone == ZONE_BOARD:
        if not (0 <= slot < len(state.board)):
            state.hand.append(card)         # out-of-range → keep in hand
            return f"→ hand[end] {card} (board slot {slot} oob)"
        tgt = state.board[slot]
        if tgt is None:
            state.board[slot] = card
            return f"→ PLACE board[{slot}] {card}"
        if tgt.id == card.id:
            _upgrade(tgt)
            return f"→ MERGE board[{slot}] = {tgt}"
        # DISPLACE: existing board card returns to hand, new card takes the slot
        state.board[slot] = card
        state.hand.append(tgt)
        return f"→ DISPLACE board[{slot}]: {tgt} → hand, {card} → board"
    # seasonal / other holding zone
    existing = state.seasonal.get((zone, slot))
    if existing is not None:
        state.hand.append(existing)         # don't lose a displaced holding card
    state.seasonal[(zone, slot)] = card
    return f"→ zone{zone}[{slot}] holds {card}"


def apply_zone_move(src_zone: int, src_slot: int, dst_zone: int, dst_slot: int) -> str:
    """Unified card move: take from (src_zone, src_slot), put into
    (dst_zone, dst_slot). Single path for every MoveCardReq / CardOperation —
    hand, board, and seasonal holding — replacing the old per-shape branches.

    Indexing matches the wire: 0-indexed slots; dst_slot == -1 → hand end.

    NOTE: the board does NOT auto-merge identical cards. Merges happen only when
    a move's destination slot already holds the same card id (an explicit drag
    onto an identical card) — handled by `_zone_put`. (Verified via the 骤风剑
    capture: three placed 骤风剑 stay separate until an explicit board→board
    drag merges two of them.)
    """
    if shadow is None:
        return "no shadow"
    with shadow_lock:
        # Board → board: the occupant SWAPS into the vacated source slot (not
        # displaced to hand — that's only the hand→board / type-2 behavior).
        if (src_zone == ZONE_BOARD and dst_zone == ZONE_BOARD
                and src_slot != dst_slot
                and 0 <= src_slot < len(shadow.board)
                and 0 <= dst_slot < len(shadow.board)):
            sc = shadow.board[src_slot]
            dc = shadow.board[dst_slot]
            if sc is None:
                outcome = "no-op (empty source)"
            elif dc is None:
                shadow.board[dst_slot] = sc
                shadow.board[src_slot] = None
                outcome = f"MOVE board[{src_slot}]→board[{dst_slot}] {sc}"
            elif dc.id == sc.id:
                _upgrade(dc)
                shadow.board[src_slot] = None
                outcome = f"MERGE board[{dst_slot}] = {dc}"
            else:
                shadow.board[src_slot], shadow.board[dst_slot] = dc, sc
                outcome = f"SWAP board[{src_slot}]↔board[{dst_slot}]"
            shadow_dirty_event.set()
            return f"[{src_zone}:{src_slot}]→[{dst_zone}:{dst_slot}] {outcome}"

        # Same-zone forward move: popping the source shifts later indices down.
        adj_dst = dst_slot
        if src_zone == dst_zone == ZONE_HAND and 0 <= src_slot < dst_slot:
            adj_dst = dst_slot - 1
        elif dst_zone == ZONE_HAND and src_zone != ZONE_HAND:
            # A card entering the hand from elsewhere (board un-place, seasonal
            # return) always goes to the RIGHT end — the wire's dst_slot for
            # hand-entry is just a placeholder. (User-confirmed.)
            adj_dst = -1
        card = _zone_take(shadow, src_zone, src_slot)
        outcome = _zone_put(shadow, dst_zone, adj_dst, card)
    shadow_dirty_event.set()
    return f"[{src_zone}:{src_slot}]→[{dst_zone}:{dst_slot}] {outcome}"


def _wire_int(pb: dict, key: str, default: int = 0) -> int:
    v = pb.get(key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def apply_move_card(pb: dict):
    """Apply a MoveCardReq via the unified zone model.

    Wire fields (protobuf omits a field when its value is 0):
        1 = src_zone, 2 = src_slot, 3 = dst_zone, 4 = dst_slot
    Zones: 0=hand, 1=board, 9=seasonal. Slots 0-indexed; dst_slot -1 = hand end.
    The addon only forwards reqs carrying at least one of fields 2/3/4, so a
    bare drag-start never reaches here. Examples (all one code path now):
        {2:3,3:1}        → hand[3] → board[0]  (PLACE)
        {2:2,3:1,4:1}    → hand[2] → board[1]
        {1:1,2:3,3:1,4:1}→ board[3] → board[1] (move/swap)
        {1:1,4:-1}       → board[0] → hand end (un-place)
        {2:1}            → hand[1] → hand[0]    (merge if same card)
    """
    if shadow is None or not isinstance(pb, dict):
        return
    src_zone = _wire_int(pb, "1")
    src_slot = _wire_int(pb, "2")
    dst_zone = _wire_int(pb, "3")
    dst_slot = _wire_int(pb, "4")
    outcome = apply_zone_move(src_zone, src_slot, dst_zone, dst_slot)
    _log_state(f"MoveCardReq {_format_pb(pb)} {outcome}")


INSERT_DIR_LEFT = 1
INSERT_DIR_RIGHT = 2


def _board_insert_shift(state, card, i: int, direction: int) -> str:
    """Type-3 placement: insert `card` at board index `i`, rippling the existing
    cards toward the nearest gap in `direction` (RIGHT=2, LEFT=1).

    RIGHT: the card at `i` and everything to its right shift right by one until
    the first empty slot at index >= i (which fills); if none, the last board
    card overflows to the right of the hand. (LEFT is the mirror.) A gap on the
    opposite side of `i` is not used. An empty target slot degrades to a plain
    place. Returns a log description.
    """
    b = state.board
    # Effective board length = unlocked slots this round (locked slots are None
    # like empties, but a card can't ripple into them — it overflows to hand).
    n = unlocked_board_slots(state.round_num) if state.round_num else len(b)
    n = max(1, min(n, len(b)))
    if not (0 <= i < n):
        state.hand.append(card)            # out of range → keep in hand
        return f"INSERT oob → hand[end] {card}"

    if direction == INSERT_DIR_LEFT:
        g = next((j for j in range(i, -1, -1) if b[j] is None), None)
        if g is not None:                  # ripple [g+1..i] left into the gap
            for j in range(g, i):
                b[j] = b[j + 1]
            b[i] = card
            return f"INSERT board[{i}] {card} (shift left → gap {g})"
        overflow = b[0]                     # no gap left → index-0 card overflows
        for j in range(0, i):
            b[j] = b[j + 1]
        b[i] = card
        if overflow is not None:
            state.hand.append(overflow)
        return f"INSERT board[{i}] {card} (shift left, {overflow} → hand)"

    # RIGHT (default)
    g = next((j for j in range(i, n) if b[j] is None), None)
    if g is not None:                       # ripple [i..g-1] right into the gap
        for j in range(g, i, -1):
            b[j] = b[j - 1]
        b[i] = card
        return f"INSERT board[{i}] {card} (shift right → gap {g})"
    overflow = b[n - 1]                      # no gap right → last card overflows
    for j in range(n - 1, i, -1):
        b[j] = b[j - 1]
    b[i] = card
    if overflow is not None:
        state.hand.append(overflow)
    return f"INSERT board[{i}] {card} (shift right, {overflow} → hand)"


def apply_insert_card(pb: dict):
    """InsertCardReq — type-3 placement (insert-and-shift). Distinct field layout
    from MoveCardReq: [1=src_zone, 2=src_slot, 3=dst_index, 4=direction], with
    direction 2=right / 1=left (0-indexed slots). The source card (hand or board)
    is removed, then inserted at the board index, shifting existing cards toward
    the nearest gap (overflow returns to the right of the hand)."""
    if shadow is None or not isinstance(pb, dict):
        return
    src_zone = _wire_int(pb, "1")
    src_slot = _wire_int(pb, "2")
    dst_index = _wire_int(pb, "3")
    direction = _wire_int(pb, "4", INSERT_DIR_RIGHT) or INSERT_DIR_RIGHT
    with shadow_lock:
        card = _zone_take(shadow, src_zone, src_slot)
        if card is None:
            outcome = "no-op (nothing to move)"
        else:
            outcome = _board_insert_shift(shadow, card, dst_index, direction)
    shadow_dirty_event.set()
    _log_state(f"InsertCardReq {_format_pb(pb)} [{src_zone}:{src_slot}]→ {outcome}")


def apply_replace_resp(pb: dict, name_fn=_name_lookup_default):
    """ReplaceCardResp: {'1': status, '2': {'2': slot, '3': new_id}, '3': {'2': slot, '3': old_id}}.

    The `slot` field is a server-side UI index whose semantics we haven't fully
    pinned down (sometimes 0-indexed, sometimes 1-indexed, sometimes missing on
    Painter side-job rerolls — see Round 11). So we use VALUE-based matching on
    `old_id`:

    - Locate the old card in the HAND (preferred — a reroll replaces a hand/shop
      card) and remove it. **Round 15: scan the hand from RIGHT to LEFT** so when
      duplicate ids are present, we remove the most-recently-drawn copy (the one
      the reroll UI typically targets). First-match-left was wrong every time the
      user rerolled the rightmost of two identical cards, causing a cascading
      desync of every subsequent slot-indexed MoveCardReq.
    - Fall back to the board only if the card isn't in the hand. (Bug #1 from
      Round 11: searching board first deleted a same-id board duplicate instead
      of the rerolled hand card.)
    - Append the new card to the right end of the hand.
    """
    if shadow is None or not isinstance(pb, dict):
        return
    info_new = pb.get("2") if isinstance(pb.get("2"), dict) else None
    info_old = pb.get("3") if isinstance(pb.get("3"), dict) else None
    if not isinstance(info_new, dict):
        return
    # Normalize the wire ids first: paired Diviner faces (天谕·攻 ↔ 天谕·守
    # etc.) are stored under the canonical (odd) face id in the shadow, so
    # the search and the inserted card both use the canonical form.
    new_id = canonical_card_id(int(info_new.get("3", 0) or 0))
    old_id = canonical_card_id(int(info_old.get("3", 0) or 0)) if isinstance(info_old, dict) else 0
    if not new_id:
        return
    with shadow_lock:
        removed_from = ""
        if old_id:
            # Round 15: rightmost-match. Reverse-scan so duplicates resolve to
            # the right-end copy, matching where the reroll UI usually fires.
            for i in range(len(shadow.hand) - 1, -1, -1):
                c = shadow.hand[i]
                if c is not None and c.id == old_id:
                    shadow.hand.pop(i)
                    removed_from = f"hand[{i}]"   # 0-indexed actual position
                    break
            if not removed_from:
                for i, c in enumerate(shadow.board):
                    if c is not None and c.id == old_id:
                        shadow.board[i] = None
                        removed_from = f"board[{i}]"
                        break
        new_card = ZoneCard(id=new_id, name=name_fn(new_id), level=_level_from_id(new_id))
        shadow.hand.append(new_card)
    shadow_dirty_event.set()
    src = removed_from or "?"
    _log_state(
        f"ReplaceCardResp {name_fn(old_id)}@{src} → {name_fn(new_id)} (id={new_id}) → hand"
    )


def apply_refine_resp(pb: dict, name_fn=_name_lookup_default):
    """RefineCardResp — always an ABSORB: the user dissolved a hand card
    for +1 修为 (cultivation).

    `pb["3"] = {2: slot, 3: card_id}` — `slot` is the **0-indexed hand
    position** of the absorbed card; protobuf omits it when 0 (the
    leftmost card), so an absent field 2 means slot 0. Remove
    `shadow.hand[slot]` when it matches `card_id`, else fall back to the
    first hand card with that id.
    """
    if shadow is None or not isinstance(pb, dict):
        return
    info = pb.get("3") if isinstance(pb.get("3"), dict) else None
    if not isinstance(info, dict):
        return
    slot = int(info.get("2", 0) or 0)   # 0-indexed; absent → 0 (leftmost)
    card_id = int(info.get("3", 0) or 0)
    if not card_id:
        return

    with shadow_lock:
        removed = None
        removed_idx = None
        # Prefer the exact slot when it holds the named card.
        if 0 <= slot < len(shadow.hand):
            c = shadow.hand[slot]
            if c is not None and c.id == card_id:
                removed = shadow.hand.pop(slot)
                removed_idx = slot
        # Fall back: first hand card with the matching id.
        if removed is None:
            for i, c in enumerate(shadow.hand):
                if c is not None and c.id == card_id:
                    removed = shadow.hand.pop(i)
                    removed_idx = i
                    break
        shadow.xiuwei += 1

        # Special absorb effect (e.g. 猫薄荷): a plain absorb carries only fields
        # 1 & 3, but a special-effect absorb adds field 2 = {1: zone, 2: idx} —
        # the server's resolved (often random) result. `zone` follows the same
        # codes as apply_zone_move (0 = hand, 1 = board); `idx` is the target
        # slot in that zone. Example: 猫薄荷 with {1:1, 2:3} = level up board[3]
        # (灵猫乱剑 → 灵猫乱剑·2). Plain absorbs (no field 2) are unchanged.
        effect_note = ""
        effect = pb.get("2")
        if isinstance(effect, dict):
            ezone = int(effect.get("1", 0) or 0)
            eidx = int(effect.get("2", 0) or 0)
            target = shadow.board if ezone == ZONE_BOARD else shadow.hand
            if 0 <= eidx < len(target) and target[eidx] is not None:
                tgt = target[eidx]
                tgt.id += 10000
                tgt.level += 1
                zname = "board" if ezone == ZONE_BOARD else "hand"
                effect_note = (f" | EFFECT level-up {zname}[{eidx}] → "
                               f"{tgt.name} lv{tgt.level}")

    shadow_dirty_event.set()
    if removed is not None:
        _log_state(
            f"RefineCardResp ABSORB hand[{removed_idx}]={name_fn(card_id)} "
            f"(id={card_id}) → 修为+1 = {shadow.xiuwei}{effect_note}"
        )
    else:
        _log_state(
            f"RefineCardResp ABSORB (id={card_id}) — card not in shadow hand; "
            f"修为+1 = {shadow.xiuwei}{effect_note}"
        )


def apply_card_operation_resp(pb: dict):
    """CardOperationResp / CardOperationReq — a generic card MOVE, not just a
    merge. `pb['2']` packs the same fields as MoveCardReq, as raw bytes:
        [src_zone, src_slot, dst_zone, dst_slot]   (trailing zeros omitted)
    Decoded from real captures (2026-05-22): the seasonal mechanic uses zone 9
    (e.g. `00 00 09 00` = hand[0] → seasonal[0]; `09 00 00` = seasonal[0] →
    hand[0]). The old code assumed every CardOperationResp was a board merge
    and read bytes[1]/bytes[3] as board slots → it wrongly deleted board[0].
    Now routed through the same unified mover, so merges, moves, and the
    seasonal park/return all behave correctly.
    """
    if shadow is None or not isinstance(pb, dict):
        return
    payload = pb.get("2")
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < 1:
        return
    b = list(payload[:4]) + [0] * (4 - len(payload[:4]))   # right-pad to 4
    src_zone, src_slot, dst_zone, dst_slot = b[0], b[1], b[2], b[3]
    outcome = apply_zone_move(src_zone, src_slot, dst_zone, dst_slot)
    _log_state(f"CardOperationResp {payload.hex()} {outcome}")
