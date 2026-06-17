"""
game_state.py
─────────────
Parses the decoded GameStatus protobuf dict into clean Python dataclasses,
and formats the state as a text prompt for the AI agent.

Known protobuf field mappings (from proxy traffic analysis):
  Top-level:
    field "5"   → list of PlayerState objects
    field "10"  → round number (or "26" as fallback)
  Per player:
    field "1"   → player ID string
    field "100" → Destiny (HP) — starts at 100
    field "103" → list of cards: each {1: card_id, 2: card_level}
"""
import json
import os
import datetime
from dataclasses import dataclass, field
from pathlib import Path


# Resolve the card-id map relative to this package, not the process CWD.
CARD_MAP_FILE = str(Path(__file__).resolve().parent / "card_id_map.json")


def _load_card_map() -> dict:
    if os.path.exists(CARD_MAP_FILE):
        try:
            with open(CARD_MAP_FILE, encoding="utf-8") as f:
                return {int(k): v for k, v in json.load(f).items()}
        except Exception:
            pass
    return {}


def card_name(card_id: int) -> str:
    return _load_card_map().get(card_id, f"#{card_id}")


def _to_str(v) -> str:
    """Decode bytes to str; passthrough str; otherwise stringify."""
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    if v is None:
        return ""
    return str(v)


@dataclass
class CardState:
    id: int
    name: str
    level: int
    slot: int = 0  # 1-indexed position in the player's card list

    def __str__(self):
        lvl = f" lv{self.level}" if self.level > 1 else ""
        return f"[{self.slot}] {self.name}{lvl}"


@dataclass
class PlayerState:
    player_id: str
    destiny: int          # top-level field 3 — 100→…→0, 0 = eliminated
    cards: list = field(default_factory=list)   # list[CardState]
    raw: dict = field(default_factory=dict)     # original protobuf dict for this player struct
    display_name: str = ""  # top-level field 2 — Chinese display name (utf-8).
                            # Used to match local BattleLog.json entries (R28).
    xiuwei: int = 0       # 修为 (cultivation) — field 200.3
    tipo: int = 0         # 体魄 (physique)    — field 200.8.2 (R24-Phase-B)
    realm_tier: int = 1   # 境界 (realm tier)  — field 200.4 (1..5)
    hp: int = 40          # max HP — 40 + field 200.3 (xiuwei) (R24-Phase-B)
    hp_field: int = 0     # R27 HP candidate: top-level field 5. Monotonic up,
                          # breakthrough jumps, per-player varying. May be the
                          # real source for displayed HP (diagnostic only —
                          # not consumed by `hp` until user-verified).
    max_tipo: int = 0     # max 体魄 — from BattleLog.json (R28 fallback).
                          # 0 if log unavailable.
    max_hp: int = 0       # max battle HP — from BattleLog.json (R28 fallback).
                          # 0 if log unavailable.
    rerolls: int = 0      # reroll count — team container field 4 (only me's is reliable)
    board: list = field(default_factory=list)   # list[CardState|None] — field 200.6
    fates: list = field(default_factory=list)   # list[int] fate ids (R24-Phase-B; from p[17])
    # Matchup pairing UIDs (Round 13 finding): every player struct carries
    #   field 9  = the player you're about to fight THIS round (next),
    #   field 10 = the player you just fought (previous; absent on R1).
    # Both are UID strings that also appear as their own entry in players[].
    next_opponent_id: str = ""   # player struct field 9
    prev_opponent_id: str = ""   # player struct field 10


@dataclass
class GameState:
    ts: str
    round_num: int
    phase: str          # "prep" | "battle" | "result"
    players: list = field(default_factory=list)  # list[PlayerState]
    me_index: int = -1  # index into players[] that is the user; -1 = not present (spectator)
    raw: dict = field(default_factory=dict)
    # User's authoritative hand+board container (top-level pb["6"]).
    # .1 = hand bytes (with duplicates), .2 = board bytes, .200 = uid.
    # Verified against me_uid before being attached; None if missing.
    team_container: dict = field(default_factory=dict)


def level_from_card_id(card_id: int) -> int:
    """Decode the card's level from its ID.

    YiXianPai encodes level inside the card ID itself: same-name variants
    differ by +10000 per level. Example chains observed:
      劈山掌 lv1=10000005, lv2=10010005, lv3=10020005
      地灵丹 lv1=2000003,  lv2=2010003,  lv3=2020003
    Formula: level = ((id // 10000) % 100) + 1
    """
    if not isinstance(card_id, int) or card_id <= 0:
        return 1
    return ((card_id // 10000) % 100) + 1


def _parse_cards(raw) -> list:
    if not isinstance(raw, list):
        raw = [raw] if isinstance(raw, dict) else []
    result = []
    slot = 0
    for c in raw:
        if not isinstance(c, dict):
            continue
        slot += 1
        cid = int(c.get("1", 0))
        # Level lives in the card ID, NOT in field 2. Field 2 is some
        # other property (tier/rarity); see notes in shadow_state.py.
        lvl = level_from_card_id(cid)
        result.append(CardState(
            id=cid,
            name=card_name(cid) if cid else "?",
            level=lvl,
            slot=slot,
        ))
    return result


def parse_player_stats(f200) -> tuple:
    """Extract (xiuwei, tipo, realm_tier) from a player struct's field 200.

    Used by both parse_game_state (GameStatus) and addon._handle_player_data
    (PlayerData) so a PlayerData reset preserves these stats instead of
    defaulting them to 0/1.
      200.3   → 修为 (cultivation)
      200.4   → 境界 (realm tier, 1..5)
      200.8.2 → 体魄 (physique). R24-Phase-B: was scanning 200.9 for stat-id
                10023, but that id doesn't appear in current game versions.
                The wire actually parks tipo in 200.8.2 (with 200.8.1 as a
                player-specific stat tag).
    """
    if not isinstance(f200, dict):
        return 0, 0, 1
    xiuwei = int(f200.get("3", 0) or 0)
    realm_tier = int(f200.get("4", 1) or 1)
    tipo = 0
    f8 = f200.get("8")
    if isinstance(f8, dict):
        try:
            tipo = int(f8.get("2", 0) or 0)
        except (TypeError, ValueError):
            tipo = 0
    return xiuwei, tipo, realm_tier


# R24-Phase-A: one-shot first-frame GameStatus dump for field discovery.
# Gated by `YX_DUMP_GS=1`. The first GameStatus per process is rendered to
# `proxy/output/gs_field_dump.txt` with EVERY per-player field index/value
# enumerated (including nested sub-fields of `200`). We use this to find
# the protobuf field carrying opponent fates and the correct HP/max_hp.
_dumped_gs = False


def _format_value(v, indent: int = 4) -> str:
    """Render one protobuf value for the dump. Truncates long bytes."""
    if isinstance(v, (bytes, bytearray)):
        hexs = v.hex()
        if len(v) > 128:
            return f"bytes[{len(v)}] = {hexs[:256]}…"
        return f"bytes[{len(v)}] = {hexs}"
    if isinstance(v, list):
        return f"list[{len(v)}] = {v!r}"
    if isinstance(v, dict):
        keys = sorted(v.keys())
        return f"dict keys={keys}"
    return repr(v)


def _maybe_dump_gameStatus(pb: dict, phase: str, me_uid: str) -> None:
    global _dumped_gs
    if _dumped_gs or not os.environ.get("YX_DUMP_GS"):
        return
    _dumped_gs = True
    try:
        out_path = Path(__file__).resolve().parent.parent / "proxy" / "output" / "gs_field_dump.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(
                f"# GameStatus first-frame dump · "
                f"{datetime.datetime.now().isoformat(timespec='seconds')}\n"
                f"# phase={phase} · me_uid={me_uid}\n"
            )
            f.write(f"# Top-level keys: {sorted(pb.keys())}\n")
            for tk in sorted(pb.keys()):
                tv = pb[tk]
                if tk == "5":
                    f.write(f"\n# field '5' = players list (rendered below per-player)\n")
                    continue
                f.write(f"  {tk}: {_format_value(tv)}\n")
            players_raw = pb.get("5", [])
            if not isinstance(players_raw, list):
                players_raw = [players_raw] if players_raw else []
            for i, p in enumerate(players_raw):
                if not isinstance(p, dict):
                    f.write(f"\n## player[{i}] · NOT-A-DICT · {p!r}\n")
                    continue
                pid = _to_str(p.get("1", "?"))
                f.write(f"\n## player[{i}] · id={pid}\n")
                f.write(f"keys: {sorted(p.keys())}\n")
                for k in sorted(p.keys()):
                    v = p[k]
                    if isinstance(v, dict):
                        f.write(f"  {k}: dict keys={sorted(v.keys())}\n")
                        for sk in sorted(v.keys()):
                            sv = v[sk]
                            if isinstance(sv, dict):
                                f.write(f"    {sk}: dict keys={sorted(sv.keys())}\n")
                                for ssk in sorted(sv.keys()):
                                    f.write(f"      {ssk}: {_format_value(sv[ssk])}\n")
                            else:
                                f.write(f"    {sk}: {_format_value(sv)}\n")
                    else:
                        f.write(f"  {k}: {_format_value(v)}\n")
        print(f"[gs-dump] wrote {out_path}")
    except Exception as e:  # never block parsing
        print(f"[gs-dump] error: {e!r}")


def parse_game_state(pb: dict, phase: str = "prep", me_uid: str = "") -> GameState:
    """Build a GameState from a decoded GameStatus protobuf dict.

    If me_uid is provided, finds the matching player and sets me_index.
    If the user isn't in the player list (spectator/replay), me_index stays -1.
    """
    # R24-Phase-A: when YX_DUMP_GS=1, dump the first GameStatus per process
    # to `proxy/output/gs_field_dump.txt`. Lets us audit every per-player
    # field we don't currently read (in particular, candidate HP and fates
    # fields). One-shot — no perf impact after the first call.
    _maybe_dump_gameStatus(pb, phase, me_uid)

    # blackboxprotobuf sometimes splits the repeated `5` tag into `5` plus
    # `5-1` (and beyond) when player structs in the same message have
    # variant sub-field shapes. Observed at realm-3→4 breakthrough rounds in
    # the 2026-05 patch (R9-R12): one player struct ended up at pb["5"] as a
    # dict and the other 7 at pb["5-1"] as a list. Gather all `5*` keys.
    players_raw = []
    for k in list(pb.keys()):
        if not (k == "5" or (isinstance(k, str) and k.startswith("5-"))):
            continue
        v = pb[k]
        if isinstance(v, list):
            players_raw.extend(v)
        elif isinstance(v, dict):
            players_raw.append(v)

    players = []
    # Lazy-import the fate-name catalog once per call so we can filter
    # p["17"] stat-list entries down to real fates.
    try:
        import shadow_state as _ss
        _fate_map = _ss._load_fate_map()
    except Exception:
        _ss = None
        _fate_map = {}
    for p in players_raw:
        if not isinstance(p, dict):
            continue
        # blackboxprotobuf sometimes names the field `200-1` instead of `200`
        # when it sees the same wire-tag twice with different inferred types.
        # Try both — the contents are equivalent.
        f200 = p.get("200") or p.get("200-1") or {}
        if not isinstance(f200, dict):
            f200 = {}
        xiuwei, tipo, realm_tier = parse_player_stats(f200)
        # Destiny (命) is the top-level field 3 — decreases when battles are
        # lost. The legacy parser read it from f200.1, but f200.1 is a static
        # "max destiny" sentinel (always 100); only top-level p[3] tracks the
        # live value.
        destiny = int(p.get("3", 0) or 0)
        # HP is NOT on the wire. The legacy `40 + xiuwei` was a wrong
        # approximation (wrong shape AND wrong base). Real HP comes from
        # battle_log.json (read by proxy_view via _battle_log_stats). Leave
        # the parsed value at 0; proxy_view falls back to 0 if the log is
        # unavailable (UI then treats it as "unknown").
        hp = 0
        # Reroll-remaining lives in the team container (pb["6"] for me; not
        # exposed per-opponent). Default to 0 here; filled in below for
        # me_index once we resolve the team container.
        rerolls = 0
        # Board = field 200.6 (8 packed varints).
        board = []
        if _ss is not None:
            try:
                board = _ss.parse_board_from_varints(f200.get("6", b""), name_fn=card_name)
            except Exception:
                board = []
        # Fates: a PACKED VARINT LIST in f200["5"] (mirrored at top-level p[13]).
        # Each player has 1+ fate ids: position 0 is the phase-1 (class-tied)
        # signature, additional entries are picked up at breakthroughs.
        # Examples from the 2026-05-26 capture:
        #   ai6-lv4 at R4:  f200["5"] = bytes 7d 59 → [125, 89] = [猛虎之躯, 木灵炼体]
        #   ai3-lv3 at R5:  f200["5"] = bytes 7d 49 → [125, 73] = [猛虎之躯, 金灵传承]
        #   me      at R4:  f200["5"] = bytes 13 35 → [19, 53]  = [血脉潜能, 机缘造化]
        # Earlier addendums wrongly used p["17"] (which carries unrelated stat
        # counters like 10022 / 10024) and a fate_id_map filter that dropped
        # valid fate ids like 73.
        fates: list[int] = []
        fate_bytes = f200.get("5") or p.get("13") or b""
        if isinstance(fate_bytes, (bytes, bytearray)) and fate_bytes and _ss is not None:
            try:
                ids = _ss.decode_varint_list(bytes(fate_bytes))
            except Exception:
                ids = []
            for fid in ids:
                try:
                    fid_i = int(fid)
                except (TypeError, ValueError):
                    continue
                if fid_i and fid_i not in fates:
                    fates.append(fid_i)
        # Next/prev opponent UIDs (broadcast on each player's struct).
        next_opp = p.get("9")
        prev_opp = p.get("10")
        # R27 HP candidate. top-level [5] is a small-int field that varies by
        # player, increases monotonically per round, and jumps at breakthrough.
        # Whether it IS displayed HP (with a per-player base offset) or only a
        # near-proxy of it requires one user-verified data point — stored
        # verbatim so proxy_view can compare it to the BattleLog HP without
        # re-parsing the wire.
        hp_field = int(p.get("5", 0) or 0)
        # R28: display name from top-level [2] (utf-8 bytes). Used by
        # proxy_view to match the player against BattleLog.json entries for
        # authoritative HP / tipo / maxTipo values.
        display_name = _to_str(p.get("2", "")) if p.get("2") else ""
        players.append(PlayerState(
            player_id=_to_str(p.get("1", "?")),
            destiny=destiny,
            cards=_parse_cards(p.get("103", [])),
            raw=p,
            display_name=display_name,
            xiuwei=xiuwei,
            tipo=tipo,
            realm_tier=realm_tier,
            hp=hp,
            hp_field=hp_field,
            rerolls=rerolls,
            board=board,
            fates=fates,
            next_opponent_id=_to_str(next_opp) if next_opp else "",
            prev_opponent_id=_to_str(prev_opp) if prev_opp else "",
        ))

    me_index = -1
    if me_uid:
        for i, p in enumerate(players):
            if p.player_id == me_uid:
                me_index = i
                break

    # Round number is in pb["1"], not pb["10"]. Field 10 is empty on every
    # GameStatus we've observed; field 1 monotonically increases each round.
    round_num = int(pb.get("1", 0) or pb.get("10", 0) or pb.get("26", 0) or 0)

    # Top-level pb["6"] is the user's authoritative team container.
    # Only attach if the embedded uid (.6.200) matches me_uid.
    team_container: dict = {}
    f6 = pb.get("6")
    if isinstance(f6, dict) and me_uid:
        uid_bytes = f6.get("200", b"")
        if isinstance(uid_bytes, (bytes, bytearray)):
            uid_str = uid_bytes.decode("utf-8", errors="replace")
        else:
            uid_str = str(uid_bytes)
        if uid_str == me_uid:
            team_container = f6

    # Reroll-remaining: team_container field 4. Verified against the user's
    # report (trajectory 3,5,5,7,7,4,8,11,14,18 across rounds → 18 at round 10).
    if team_container and me_index >= 0:
        players[me_index].rerolls = int(team_container.get("4", 0) or 0)

    return GameState(
        ts=datetime.datetime.utcnow().isoformat() + "Z",
        round_num=round_num,
        phase=phase,
        players=players,
        me_index=me_index,
        raw=pb,
        team_container=team_container,
    )


def _card_summary(cards: list) -> tuple:
    """Group cards by name and return (display_str, mergeable_names).
    Used for the OPPONENT display only. `mergeable_names` lists names
    that have 2+ copies at the SAME level (merge needs same name+level).
    """
    if not cards:
        return "(no cards)", []
    order: list = []
    counts: dict = {}
    levels: dict = {}
    nl_counts: dict = {}   # (name, level) -> count
    for c in cards:
        if c.name not in counts:
            order.append(c.name)
            counts[c.name] = 0
            levels[c.name] = []
        counts[c.name] += 1
        levels[c.name].append(c.level)
        nl_counts[(c.name, c.level)] = nl_counts.get((c.name, c.level), 0) + 1
    parts = []
    mergeable = []
    for n in order:
        cnt = counts[n]
        lv_set = sorted(set(levels[n]))
        if len(lv_set) == 1 and lv_set[0] > 1:
            piece = f"{n} ×{cnt} (lv{lv_set[0]})"
        elif len(lv_set) > 1:
            piece = f"{n} ×{cnt} (lvs {','.join(map(str, lv_set))})"
        else:
            piece = f"{n} ×{cnt}"
        parts.append(piece)
        if any(nl_counts.get((n, lv), 0) >= 2 for lv in lv_set):
            mergeable.append(n)
    total = sum(counts.values())
    return ", ".join(parts) + f"  ({total} total)", mergeable


def _format_hand_indexed(hand: list) -> str:
    """Render the hand as a 0-indexed list: 'hand[0]=X, hand[1]=Y lv2, ...'.
    Cards that cannot be placed on the board (tokens / 传承 / consumables)
    are tagged '(cannot place)'."""
    try:
        from bot import knowledge
        _placeable = knowledge.is_placeable
    except Exception:
        def _placeable(_n):
            return True
    parts = []
    for i, c in enumerate(hand):
        if c is None:
            continue
        lvl = f" lv{c.level}" if c.level > 1 else ""
        tag = "" if _placeable(c.name) else " (cannot place)"
        parts.append(f"hand[{i}]={c.name}{lvl}{tag}")
    return ", ".join(parts) if parts else "(no cards)"


def _format_board_line(board_slots: list, unlocked: int = 8) -> str:
    """Render the 8-slot board, 0-indexed. `unlocked` is a 1-based count
    (e.g. 3 → slots 0-2 usable); slots at index >= unlocked are locked."""
    parts = []
    for i, c in enumerate(board_slots):
        if i >= unlocked:
            parts.append(f"board[{i}] locked")
        elif c is None:
            parts.append(f"board[{i}] empty")
        else:
            lvl = f" lv{c.level}" if c.level > 1 else ""
            parts.append(f"board[{i}]={c.name}{lvl}")
    return ", ".join(parts)


def _mergeable_groups(hand: list, board: list) -> list:
    """Return human-readable mergeable groups. A group is 2+ cards with
    the SAME name AND SAME level, anywhere in hand or board. Each entry
    lists the coordinates, e.g. '轻剑 lv1 — board[0], board[2]'.
    Token / non-playable cards (e.g. 练笔) are excluded — they cannot be
    upgraded by merging."""
    try:
        from bot import knowledge
        _mergeable = knowledge.is_mergeable
    except Exception:
        def _mergeable(_n):
            return True
    groups: dict = {}
    order: list = []
    for i, c in enumerate(hand):
        if c is None or not _mergeable(c.name):
            continue
        key = (c.name, c.level)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f"hand[{i}]")
    for j, c in enumerate(board):
        if c is None or not _mergeable(c.name):
            continue
        key = (c.name, c.level)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f"board[{j}]")
    out = []
    for (name, lvl) in order:
        coords = groups[(name, lvl)]
        if len(coords) >= 2:
            out.append(f"{name} lv{lvl} — {', '.join(coords)}")
    return out


def format_state(state: GameState) -> str:
    """Render GameState as plain text for the LLM prompt.

    For the user, includes hand / board / bench lines pulled from the
    client-side shadow (shadow_state.shadow). Falls back to just the
    card list if the shadow isn't initialised yet."""
    try:
        import shadow_state
    except Exception:
        shadow_state = None

    lines = [f"=== Game State  Round {state.round_num} ==="]
    my_mergeable: list = []

    for i, p in enumerate(state.players):
        if i == state.me_index:
            label = "You"
        elif state.me_index < 0:
            label = f"Player {i}"
        else:
            label = f"Opponent {i}"

        if i == state.me_index and shadow_state is not None and shadow_state.shadow is not None:
            sh = shadow_state.shadow
            unlocked = shadow_state.unlocked_board_slots(state.round_num)
            hand_str = _format_hand_indexed(sh.hand)
            board_str = _format_board_line(sh.board, unlocked=unlocked)
            # Mergeable groups: 2+ cards of the same name AND level,
            # listed by coordinate (hand[i] / board[j]).
            my_mergeable = _mergeable_groups(sh.hand, sh.board)
            lines.append(f"{label}  Destiny={p.destiny}  HP={p.hp}  Rerolls={p.rerolls}")
            lines.append(f"  Hand:  {hand_str}")
            lines.append(f"  Board: {board_str}")
            if unlocked < 8:
                lines.append(f"         (only board[0]-board[{unlocked-1}] unlocked this round; board[{unlocked}]-board[7] are LOCKED)")
            # Cultivation stats + breakthrough availability.
            xw, tp, tier = sh.xiuwei, sh.tipo, sh.realm_tier
            lines.append(f"  修为(cultivation): {xw}   体魄(physique): {tp}   境界(realm tier): {tier}")
            avail, thr, gate = shadow_state.breakthrough_status(tier, xw, tp)
            if avail:
                lines.append(f"  BREAKTHROUGH AVAILABLE — {gate} ≥ {thr}. Issue BREAKTHROUGH to advance realm + gain a fate.")
            elif thr is not None:
                lines.append(f"  Breakthrough locked — need 修为 or 体魄 ≥ {thr} (have {xw}/{tp}). Absorbing a card gives +1 修为.")
            else:
                lines.append(f"  Breakthrough — max realm reached.")
        else:
            cards_str, mergeable = _card_summary(p.cards)
            if i == state.me_index:
                my_mergeable = mergeable
            lines.append(
                f"{label}  Destiny={p.destiny}  HP={p.hp}  "
                f"修为={p.xiuwei}  境界(realm)={p.realm_tier}"
            )
            # Opponent board in slot order — what they cast in battle.
            board_cards = []
            for c in p.board:
                if c is None:
                    continue
                lvl = f" lv{c.level}" if getattr(c, "level", 1) > 1 else ""
                board_cards.append(f"{c.name}{lvl}")
            board_str = ", ".join(board_cards) if board_cards else "(empty)"
            lines.append(f"  Board: {board_str}")
            lines.append(f"  Owned cards: {cards_str}")

    lines.append("")
    if my_mergeable:
        lines.append("Mergeable now (same name + same level):")
        for grp in my_mergeable:
            lines.append(f"  {grp}")
    else:
        lines.append("Mergeable now: (none — no 2 cards share name AND level)")

    # Surface any pending discrete choice the user must make THIS turn.
    # Suppresses all other actions — the AI must recommend the choice first.
    pc = None
    if shadow_state is not None and getattr(shadow_state, "get_pending_choice", None):
        pc = shadow_state.get_pending_choice()
    if pc is not None:
        # The active system prompt (selected by AIAgent based on pc.kind)
        # already carries the rules and class table. Here we only need to
        # surface runtime data the system prompt can't bake in.
        lines.append("")
        if pc.kind == "daoyun":
            opt_names = [c.name for c in pc.options]
            lines.append(f"DaoYun options: {opt_names}")
        elif pc.kind == "fate":
            opt_names = [c.name for c in pc.options]
            lines.append(f"Fate (天命) options: {opt_names}")
        elif pc.kind == "class":
            lines.append("Class-selection round — pick one career_id.")
        else:
            lines.append(f"Pending choice: {pc.prompt_text}")

    lines.append("Refer to cards by their 0-indexed coordinate (hand[i] / board[j]). What is your next action?")
    return "\n".join(lines)
