"""
addon.py (trimmed)
──────────────────
mitmproxy addon for the card counter. Decodes darksungame.com WebSocket
frames, mutates the client-side shadow on each gameplay message, and pushes
parsed GameState objects onto state_queue for the UI consumer thread.

Stripped from the original AI-bot addon: no game_loop, action_executor,
LLM, or traffic-file logging. Just decode → shadow → state_queue.

Imported as a top-level module (proxy/ is on sys.path) so the internal
`import shadow_state` calls in the ported modules resolve to the same
singleton instances this file uses.
"""
import copy
import datetime
import json
import os
import sys
import threading
from pathlib import Path

try:
    from mitmproxy import ctx          # proxy mode only
except ImportError:
    ctx = None                          # same-domain injection reuses the
    # dispatcher below without mitmproxy; _log() falls back to print().

from decoder import decode_frame
from game_state import parse_game_state, CardState, card_name
from state_queue import state_queue, new_game_event, round_ended_event
import shadow_state

TARGET_HOST = "darksungame.com"
CONFIG_FILE = str(Path(__file__).resolve().parent / "config.json")

# ─── Action injection (auto-player) ───────────────────────────────────────────
# The auto-player encodes client→server frames (autoplay/protocol.py) and asks us
# to inject them onto the live game WebSocket. We hold the mitmproxy master, its
# asyncio loop, and the latest game flow; inject_frame schedules the send on the
# loop thread (the coordinator runs on a different thread).
import collections as _collections

_inject_lock = threading.Lock()
_master = None
_loop = None
_game_flow = None
_client_opcodes = _collections.Counter()   # tally first byte of C→S binary frames
_last_client_frame = None                   # (type, raw_hex) of latest C→S 'data' frame


def set_runtime(master, loop):
    """Called once from runtime.start_proxy so injection can reach the master."""
    global _master, _loop
    with _inject_lock:
        _master, _loop = master, loop


def _note_client_frame(raw: bytes, mp):
    """Record opcode tally + the latest client action's raw bytes, for
    byte-exactness verification during auto-player bring-up. Action frames are
    also appended to proxy/output/client_frames.jsonl so the encoder can be
    checked against REAL raw bytes (opcode included) from another process."""
    global _last_client_frame
    if raw:
        _client_opcodes[raw[0]] += 1
    inner = (mp[1] if isinstance(mp, list) and len(mp) > 1 and isinstance(mp[1], dict)
             else None)
    if not (inner and inner.get("type")):
        return
    _last_client_frame = (inner.get("type"), bytes(raw).hex())
    try:
        rec = {"opcode": raw[0], "type": inner.get("type"),
               "raw_hex": bytes(raw).hex(), "msgpack": mp}
        with (_CAPTURE_DIR / "client_frames.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def inject_frame(frame: bytes) -> bool:
    """Schedule a raw binary frame to be sent client→server on the live game
    flow. Thread-safe; returns False if the proxy/flow isn't ready yet."""
    with _inject_lock:
        master, loop, flow = _master, _loop, _game_flow
    if master is None or loop is None or flow is None:
        return False

    def _do():
        try:
            master.commands.call("inject.websocket", flow, False, frame, False)
        except Exception as e:
            _log(f"[inject] failed: {e}")

    try:
        loop.call_soon_threadsafe(_do)
        return True
    except Exception as e:
        _log(f"[inject] schedule failed: {e}")
        return False


def force_reconnect() -> bool:
    """Drop the live game WebSocket so the client reconnects + the server re-sends
    the full room state → the stale prep UI repaints (so the player can see the
    injected board). Scheduled on the proxy loop. Risky: may disrupt the match."""
    with _inject_lock:
        master, loop, flow = _master, _loop, _game_flow
    if not (master and loop and flow):
        return False

    def _do():
        try:
            if getattr(flow, "killable", False):
                flow.kill()
            else:
                master.commands.call("flow.kill", [flow])
            _log("[reconnect] 断开游戏连接 → 客户端应重连+刷新")
        except Exception as e:
            _log(f"[reconnect] failed: {e}")

    try:
        loop.call_soon_threadsafe(_do)
        return True
    except Exception:
        return False


# ─── User UID (detected from /auth/login or GameStatus pb["6"]) ───────────────
_me_uid_lock = threading.Lock()
_me_uid: str = ""

# Last resolved battle pairing (winner/loser UIDs) — used later for matchup.
last_battle: dict = {}
# UID of the opponent the user most recently fought (BattleResult involving me).
my_last_opponent: str = ""

# Reroll events for the deck counter, drained by proxy_view.Counter. Each entry
# is {"old": <discarded card name>, "new": <drawn card name>}.
reroll_events: list = []

# Fate ids the user has chosen this game (breakthrough rewards), in pick order.
chosen_fates: list = []

# Daoyun (道韵) free-grant events for the Counter. Each entry is a card NAME
# that the server granted (via daoyun pick / 自在随心 random draw). Drained
# by proxy_view.Counter._drain_daoyun_events so the granted card doesn't
# count as a deck draw when it next appears in the hand.
daoyun_grant_events: list = []

# Snapshot of team_container[1] ids (set of int). RESETS at every GameStatus;
# diffed at every PlayerData to find new entries. ONLY actual daoyun grants
# get emitted — see _emit_daoyun_grants_from_team1.
_team1_snapshot: set = set()

# Daoyun pick state — only set after SimpleClientPact(kind=9) fires:
#   _daoyun_random_pending = True when a 自在随心 (id=27) pick happens; the
#       NEXT new id appearing in team_container[1] is the random card.
#   _daoyun_pending_picks  = set of explicit picked ids waiting to land in
#       team_container[1] (may be immediate or deferred until the player
#       reaches that card's required phase).
_daoyun_random_pending: bool = False
_daoyun_pending_picks: set = set()


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_me_uid() -> str:
    with _me_uid_lock:
        return _me_uid


def _reset_team1_snapshot(b):
    """Replace the team_container[1] snapshot with the new round's value.
    Called at every GameStatus (round boundary). The bytes are decoded as a
    packed varint list of card ids."""
    global _team1_snapshot
    ids: set = set()
    if isinstance(b, (bytes, bytearray)) and b:
        try:
            ids = set(shadow_state.decode_varint_list(b))
        except Exception:
            ids = set()
    _team1_snapshot = ids


def _emit_daoyun_grants_from_team1(b):
    """Diff team_container[1] against the round-start snapshot to find any
    NEW ids. Emit grant events ONLY for ids that match an outstanding daoyun
    pick (explicit pick id) or — if a 自在随心 random pick is pending — the
    first new id encountered (the server's resolved random card).

    team_container[1] also changes for non-daoyun reasons (it carries broader
    deck/round state); the daoyun-pending gating filters those out."""
    global _team1_snapshot, _daoyun_random_pending, _daoyun_pending_picks
    if not isinstance(b, (bytes, bytearray)) or not b:
        return
    try:
        cur = set(shadow_state.decode_varint_list(b))
    except Exception:
        return
    new_ids = cur - _team1_snapshot
    _team1_snapshot |= cur
    if not new_ids:
        return
    # Match explicit-pick ids first (deferred or immediate grants both match
    # here — the pick stays in the pending set until its id appears).
    resolved_explicit = new_ids & _daoyun_pending_picks
    for cid in resolved_explicit:
        try:
            nm = card_name(int(cid))
        except Exception:
            continue
        daoyun_grant_events.append({"name": nm, "id": int(cid)})
    _daoyun_pending_picks -= resolved_explicit
    # 自在随心 random pick: USER RULE — count the granted card as a real deck
    # draw, not a free grant. We do nothing here so the new id sits in
    # team_container[1] and Counter.observe() picks it up via the standard
    # hand-grew path. (Was previously credited as a free grant.)
    if _daoyun_random_pending:
        _daoyun_random_pending = False
    # 剑池问心 fate (ids 119 / 10119 / 20119 / 30119): when active, the cards
    # it adds to the hand are NOT pulled from the deck pool. Credit any
    # remaining new id as a free grant so it doesn't decrement remaining().
    if _JIANCHI_FATE_IDS & set(chosen_fates):
        remaining = new_ids - resolved_explicit
        for cid in remaining:
            try:
                nm = card_name(int(cid))
                daoyun_grant_events.append({"name": nm, "id": int(cid)})
            except Exception:
                pass


def _note_daoyun_pick(chosen_id: int):
    """Called from _handle_simple_client_pact when a daoyun pact (kind=9)
    is observed. Tracks the picked card id so the next team_container[1]
    addition that matches it counts as a daoyun grant."""
    global _daoyun_pending_picks
    # 自在随心 (id=27) — USER RULE: the random card it grants should count as
    # a real deck draw, not a free grant. Skip the pending-pick tracking
    # entirely so Counter.observe() treats the incoming card as a normal draw.
    if chosen_id == 27:
        return
    if chosen_id > 0:
        _daoyun_pending_picks.add(int(chosen_id))


# 剑池问心 fate ids across realm tiers (lv1 / lv2 / lv3 / lv4). When any of
# these is in `chosen_fates`, mid-round cards added to the hand are credited
# as free grants instead of decrementing the deck pool.
_JIANCHI_FATE_IDS = frozenset({119, 10119, 20119, 30119})


def _set_me_uid(uid: str):
    global _me_uid
    with _me_uid_lock:
        if uid and uid != _me_uid:
            _me_uid = uid
            cfg = _load_config()
            cfg["user_uid"] = uid
            _save_config(cfg)
            _log(f"[uid] user UID detected: {uid}")


_me_uid = _load_config().get("user_uid", "")


def _log(msg: str):
    try:
        ctx.log.info(msg)
    except Exception:
        print(msg)


# ─── blackboxprotobuf typedefs (force packed-varint fields to bytes) ──────────
_GAMESTATUS_TYPEDEF = {
    "5": {"type": "message", "message_typedef": {
        "200": {"type": "message", "message_typedef": {
            "6": {"type": "bytes"},
            "7": {"type": "bytes"},
        }},
    }},
    "6": {"type": "message", "message_typedef": {
        "1": {"type": "bytes"},
        "2": {"type": "bytes"},
        "200": {"type": "bytes"},
    }},
}
_PLAYERDATA_TYPEDEF = {
    "1": {"type": "message", "message_typedef": {
        "200": {"type": "message", "message_typedef": {
            "6": {"type": "bytes"},
            "7": {"type": "bytes"},
        }},
    }},
    "2": {"type": "message", "message_typedef": {
        "1": {"type": "bytes"},
        "2": {"type": "bytes"},
        "200": {"type": "bytes"},
    }},
}
_PENDINGTALENT_TYPEDEF = {"1": {"type": "bytes"}}


def _decode_pb(b64, typedef=None) -> dict:
    import base64
    import blackboxprotobuf
    try:
        raw = base64.b64decode(b64)
        if typedef:
            return blackboxprotobuf.decode_message(raw, typedef)[0]
        return blackboxprotobuf.decode_message(raw)[0]
    except Exception:
        return {}


# ─── msgpack-type predicates ──────────────────────────────────────────────────
def _inner(mp):
    if not isinstance(mp, list) or len(mp) < 2:
        return None
    return mp[1] if isinstance(mp[1], dict) else None


def _is_start_game_resp(mp) -> bool:
    inner = _inner(mp)
    return bool(inner and inner.get("type") == "StartGameResp")


def _is_round_end(mp) -> bool:
    inner = _inner(mp)
    return bool(inner and inner.get("type") == "BattleResult")


# ─── Spectator-mode detection ─────────────────────────────────────────────────
# Only SpectateFriendReq is treated as the spectator-entry signal. We tried
# matching SpectateReq earlier but it also fires for ambiguous things in the
# lobby (player-info previews, ranking refreshes, etc.), wrongly flipping the
# flag and freezing the counter on the user's next real game. SpectateFriendReq
# is the explicit "Spectate a Friend" click and only fires when entering an
# actual spectate session.
# Cleared by StartGameResp OR any client→server game action (MoveCardReq /
# ReplaceCardReq / etc.) — see the safety net in process_msgpack.
_is_spectating: bool = False


def _set_spectating(value: bool):
    global _is_spectating
    if _is_spectating != value:
        _is_spectating = value
        _log(f"[spectator] {'ENTERING' if value else 'LEAVING'} spectator mode")


def _is_spectate_msg(mp) -> bool:
    inner = _inner(mp)
    if not inner:
        return False
    return inner.get("type", "") == "SpectateFriendReq"


# ─── Shadow / state-queue plumbing ────────────────────────────────────────────
_last_my_state_lock = threading.Lock()
_last_my_state = None


def _push_state(state) -> None:
    global _last_my_state
    if state_queue.full():
        try:
            state_queue.get_nowait()
        except Exception:
            pass
    try:
        state_queue.put_nowait(state)
    except Exception:
        pass
    with _last_my_state_lock:
        _last_my_state = state


def _wake():
    """Re-push the last cached GameState so the consumer re-renders after a
    shadow mutation that had no fresh GameStatus."""
    with _last_my_state_lock:
        s = _last_my_state
    if s is None:
        return
    _push_state(s)


def _mutate_my_hand(slot: int, new_card_id: int, new_level: int = 1):
    with _last_my_state_lock:
        base = _last_my_state
    if base is None:
        return None
    me_idx = base.me_index
    if me_idx < 0 or me_idx >= len(base.players):
        return None
    new_state = copy.deepcopy(base)
    me = new_state.players[me_idx]
    for c in me.cards:
        if c.slot == slot:
            c.id = new_card_id
            c.name = card_name(new_card_id)
            c.level = new_level
            return new_state
    me.cards.append(CardState(id=new_card_id, name=card_name(new_card_id),
                              level=new_level, slot=slot))
    return new_state


# ─── S→C handlers (mutate shadow) ─────────────────────────────────────────────
def _handle_replace_card_resp(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "ReplaceCardResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    new_info = pb.get("2") if isinstance(pb.get("2"), dict) else None
    if not isinstance(new_info, dict):
        return
    slot = int(new_info.get("2", 0) or 0)
    new_id = int(new_info.get("3", 0) or 0)
    if not new_id:
        return
    # NB: the server omits `slot` on most prep-phase rerolls (e.g. Painter
    # side-job rerolls), so we must NOT gate on `slot` — that previously
    # dropped half the ReplaceCardResps and corrupted the shadow board.
    # pb["3"] = {2: slot, 3: old_id} — the discarded card (rerolled away).
    old_info = pb.get("3") if isinstance(pb.get("3"), dict) else {}
    old_id = int(old_info.get("3", 0) or 0) if isinstance(old_info, dict) else 0
    # Normalize paired Diviner faces (天谕·攻 ↔ 天谕·守 etc.) to the canonical
    # face id BEFORE looking up the card name. Otherwise the reroll event's
    # `old` could read e.g. "天谕·攻" while the shadow stores 天谕·守 — the
    # Counter would canonical-tally fine, but card_name's value is also used
    # for display/log so consistency matters.
    new_id = shadow_state.canonical_card_id(new_id)
    old_id = shadow_state.canonical_card_id(old_id)
    reroll_events.append({
        "old": card_name(old_id) if old_id else None,
        "new": card_name(new_id),
    })
    shadow_state.apply_replace_resp(pb, name_fn=card_name)
    # R36: always re-render. Without this, slot==0 rerolls (common on prep-
    # phase / Painter side-job rerolls) mutated the shadow but never pushed
    # to the UI, so "cards left in deck" stayed stale until the next
    # MoveCardReq happened to wake the consumer.
    _wake()
    if slot:
        new_state = _mutate_my_hand(slot, new_id, new_level=1)
        if new_state is not None:
            _push_state(new_state)
    return f"ReplaceCardResp: slot {slot} → {card_name(new_id)}"


def _handle_refine_card_resp(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "RefineCardResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    payload = pb.get("3") if isinstance(pb.get("3"), dict) else None
    if not isinstance(payload, dict):
        return
    card_id = int(payload.get("3", 0) or 0)
    if not card_id:
        return
    shadow_state.apply_refine_resp(pb, name_fn=card_name)
    _wake()
    return f"RefineCardResp: ABSORB {card_name(card_id)}"


def _handle_card_operation_resp(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "CardOperationResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    shadow_state.apply_card_operation_resp(pb)
    _wake()
    return "CardOperationResp: card move applied"


def _handle_pending_daoyun(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "PendingDaoYunResp":
        return
    pb = _decode_pb(inner.get("data", ""))
    b = pb.get("3", b"") if isinstance(pb, dict) else b""
    if not isinstance(b, (bytes, bytearray)):
        return
    # 2026-05 patch: daoyun grew from 4 to 5 options. The new 5th option can
    # use a SHORT id (e.g. id=27 for 自在随心) while the existing 4 use full
    # 7-digit card ids. The old `v >= 1_000_000` filter silently dropped the
    # new short-id option; keep all positive ids.
    options = []
    for v in shadow_state.decode_varint_list(b):
        if v <= 0:
            continue
        options.append(shadow_state.ZoneCard(
            id=v, name=card_name(v), level=shadow_state._level_from_id(v)))
    if not options:
        return
    shadow_state.set_pending_choice(shadow_state.PendingChoice(
        kind="daoyun", options=options,
        prompt_text="Pick ONE (DaoYun): " + ", ".join(c.name for c in options)))
    _wake()
    return f"PendingDaoYunResp: {[c.name for c in options]}"


def _handle_pending_talent(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "PendingTalentResp":
        return
    pb = _decode_pb(inner.get("data", ""), typedef=_PENDINGTALENT_TYPEDEF)
    b = pb.get("1", b"") if isinstance(pb, dict) else b""
    if not isinstance(b, (bytes, bytearray)):
        return
    ids = shadow_state.decode_varint_list(b)
    if not ids:
        return
    options = [shadow_state.ZoneCard(id=fid, name=shadow_state.fate_name(fid), level=1)
               for fid in ids]
    shadow_state.set_pending_choice(shadow_state.PendingChoice(
        kind="fate", options=options,
        prompt_text="Pick ONE fate (天命): " + ", ".join(c.name for c in options)))
    _wake()
    return f"PendingTalentResp: fates {[c.name for c in options]}"


def _handle_battle_result(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "BattleResult":
        return
    pb = _decode_pb(inner.get("data", ""))
    if not isinstance(pb, dict):
        return

    def _uid(v):
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", "replace")
        return str(v) if v is not None else ""

    global last_battle, my_last_opponent
    last_battle = {"winner": _uid(pb.get("8")), "loser": _uid(pb.get("9"))}
    me = _get_me_uid()
    if me and me in (last_battle["winner"], last_battle["loser"]):
        other = last_battle["loser"] if me == last_battle["winner"] else last_battle["winner"]
        if other:
            my_last_opponent = other
        return f"BattleResult: you {'WON' if me == last_battle['winner'] else 'LOST'}"
    return None


def _handle_player_data(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "PlayerData":
        return
    pb = _decode_pb(inner.get("data", ""), typedef=_PLAYERDATA_TYPEDEF)
    if not isinstance(pb, dict):
        return
    pdict = pb.get("1") if isinstance(pb.get("1"), dict) else None
    if not isinstance(pdict, dict):
        return
    me_uid = _get_me_uid()
    if not me_uid:
        return
    uid_raw = pdict.get("1", b"")
    uid = (uid_raw.decode("utf-8", "replace")
           if isinstance(uid_raw, (bytes, bytearray)) else str(uid_raw))
    if uid != me_uid:
        return

    from game_state import PlayerState, _parse_cards, _to_str, parse_player_stats
    xiuwei, tipo, realm_tier = parse_player_stats(pdict.get("200", {}))
    next_opp = pdict.get("9")
    prev_opp = pdict.get("10")
    # R27: keep `hp_field` (top-level [5] HP candidate) in sync on the
    # PlayerData refresh too, otherwise it'd reset to 0 between GameStatus
    # frames and the diagnostic side-by-side would flicker.
    hp_field = int(pdict.get("5", 0) or 0)
    # R28: also keep display_name in sync so BattleLog.json lookups work
    # when PlayerData fires between GameStatus frames.
    display_name = _to_str(pdict.get("2", "")) if pdict.get("2") else ""
    player = PlayerState(
        player_id=_to_str(pdict.get("1", "?")),
        destiny=int(pdict.get("100", 0) or 0),
        cards=_parse_cards(pdict.get("103", [])),
        display_name=display_name,
        xiuwei=xiuwei, tipo=tipo, realm_tier=realm_tier,
        # HP is NOT on the wire — the legacy `40 + xiuwei` was wrong. Real
        # HP comes from battle_log.json via proxy_view._battle_log_stats.
        hp=0,
        hp_field=hp_field,
        next_opponent_id=_to_str(next_opp) if next_opp else "",
        prev_opponent_id=_to_str(prev_opp) if prev_opp else "",
    )
    player.raw = pdict

    team_container = None
    pb2 = pb.get("2")
    if isinstance(pb2, dict):
        uid_b = pb2.get("200", b"")
        uid_s = (uid_b.decode("utf-8", "replace")
                 if isinstance(uid_b, (bytes, bytearray)) else str(uid_b))
        if uid_s == me_uid:
            team_container = pb2

    # Reroll-remaining lives in team_container field 4.
    if team_container is not None:
        player.rerolls = int(team_container.get("4", 0) or 0)
        # team_container[1] is the "incoming cards this round" list — daoyun
        # grants (and other free grants like 自在随心's random draw) get
        # appended to it during the round. Diff against the snapshot taken at
        # round-start to find NEW additions and queue them as free grants for
        # the Counter (so they don't decrement the deck pool).
        _emit_daoyun_grants_from_team1(team_container.get("1", b""))

    shadow_state.reset_from_player(player, name_fn=card_name,
                                   source="PlayerData", team_container=team_container)
    shadow_state.clear_pending_choice()
    _wake()
    return f"PlayerData: shadow refreshed (uid={uid[:8]}…)"


# ─── C→S handlers (mutate shadow) ─────────────────────────────────────────────
def _handle_move_card_req(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "MoveCardReq":
        return
    pb = _decode_pb(inner.get("data", ""))
    if not (pb.get("2") is not None or pb.get("3") is not None or pb.get("4") is not None):
        return
    shadow_state.apply_move_card(pb)
    _wake()
    return None


def _handle_insert_card_req(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "InsertCardReq":
        return
    pb = _decode_pb(inner.get("data", ""))
    shadow_state.apply_insert_card(pb)
    _wake()
    return "InsertCardReq: shadow board updated"


def _handle_simple_client_pact(mp):
    """SimpleClientPact (C→S): the client confirms a discrete choice as
    {1: kind, 2: chosen_id}. Kinds we handle:
      kind=9 (daoyun pick) — record the picked id so the next team_container[1]
              addition that matches becomes a free-grant event.
      kind=anything-else (fate pick on a pending fate choice) — handled below."""
    inner = _inner(mp)
    if not inner or inner.get("type") != "SimpleClientPact":
        return
    pb = _decode_pb(inner.get("data", ""))
    if not isinstance(pb, dict):
        return
    chosen = int(pb.get("2", 0) or 0)
    if not chosen:
        return
    kind = int(pb.get("1", 0) or 0)
    if kind == 9:
        # Daoyun pact. Record the pick for later matching against
        # team_container[1] additions (see _emit_daoyun_grants_from_team1).
        _note_daoyun_pick(chosen)
        # Don't return here — the regular fate-pending path below would
        # never fire for kind=9 anyway (kind=9 is its own pact category).
    pc = shadow_state.get_pending_choice()
    if pc is not None and getattr(pc, "kind", "") == "fate":
        option_ids = {getattr(o, "id", None) for o in getattr(pc, "options", [])}
        if chosen in option_ids:
            chosen_fates.append(chosen)
            # If this fate is 副职兼修, capture the phase from the fate id so
            # the next SelectCareerReq (secondary slot) records it correctly.
            shadow_state.note_fate_pick(chosen)
            # PendingTalentResp + this pact = breakthrough fate pick. The
            # game updates the player's realm tier server-side but doesn't
            # send a fresh PlayerData / GameStatus until the next round, so
            # the sidejob counter would otherwise lag a full round. Bump
            # the shadow's realm_tier optimistically (capped at 5) so the
            # counter sees the new realm immediately.
            sh = shadow_state.shadow
            if sh is not None:
                cur = int(getattr(sh, "realm_tier", 1) or 1)
                if cur < 5:
                    sh.realm_tier = cur + 1
            shadow_state.clear_pending_choice()
            _wake()
            return f"Fate chosen: {shadow_state.fate_name(chosen)} ({chosen})"
    return None


def _handle_select_career_req(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "SelectCareerReq":
        return
    pb = _decode_pb(inner.get("data", ""))
    cid = int(pb.get("1", 0) or 0) if isinstance(pb, dict) else 0
    if not cid:
        return
    # Field 3 = 1 marks the 副职兼修 SECONDARY pick (the fate-granted second
    # sidejob). When set, route to the secondary slot so the counter credits
    # an additional deck — including the case where primary == secondary
    # (same career chosen twice → double copies of that career's cards).
    is_secondary = bool(int(pb.get("3", 0) or 0)) if isinstance(pb, dict) else False
    shadow_state.note_career_pick(cid, secondary=is_secondary)
    slot = "secondary (副职兼修)" if is_secondary else "primary"
    return f"SelectCareerReq → {slot} career {cid} ({shadow_state.career_name(cid)})"


# ─── GameStatus → GameState push ──────────────────────────────────────────────
def _try_push_game_state(mp):
    inner = _inner(mp)
    if not inner or inner.get("type") != "GameStatus":
        return None
    pb = _decode_pb(inner.get("data", ""), typedef=_GAMESTATUS_TYPEDEF)
    if not pb:
        return None

    # Auto-detect the user's UID from their own team container (pb["6"]).
    # SKIP THIS WHEN SPECTATING — the team container during spectating is the
    # SPECTATED player's, and persisting it as the user's UID would leak hand
    # info downstream (PlayerData/GameStatus handlers update the shadow when
    # the message UID matches _me_uid).
    if not _is_spectating:
        f6 = pb.get("6")
        if isinstance(f6, dict) and isinstance(f6.get("1"), (bytes, bytearray)) \
                and isinstance(f6.get("2"), (bytes, bytearray)):
            uid_b = f6.get("200", b"")
            uid_s = (uid_b.decode("utf-8", "replace")
                     if isinstance(uid_b, (bytes, bytearray)) else str(uid_b))
            if uid_s and len(uid_s) >= 16 and uid_s != _get_me_uid():
                _set_me_uid(uid_s)

    me_uid = _get_me_uid()
    state = parse_game_state(pb, phase="prep", me_uid=me_uid)
    # Skip shadow updates while spectating — even if me_index >= 0 (e.g. the
    # auto-detect above ran on a prior frame before SpectateReq fired), we
    # don't want to keep updating the shadow with the spectated player's data.
    is_my_game = (not _is_spectating
                  and bool(me_uid)
                  and state.me_index >= 0)

    if is_my_game:
        shadow_state.reset_from_player(
            state.players[state.me_index], name_fn=card_name,
            source="GameStatus", team_container=state.team_container or None)
        if shadow_state.shadow is not None:
            shadow_state.shadow.round_num = state.round_num
        # Snapshot team_container[1] (incoming-cards list) at round boundary
        # WITHOUT emitting daoyun grants — the entries here are round-start
        # refills, not free grants. Subsequent PlayerData additions to this
        # field DURING the round will be diffed against this snapshot.
        _reset_team1_snapshot((state.team_container or {}).get("1", b""))
        _push_state(state)
        return f"GameStatus pushed — round {state.round_num}, {len(state.players)} players"
    return None


def process_msgpack(mp, from_client: bool):
    """Dispatch one decoded Colyseus msgpack payload through the shadow +
    state-queue handlers. Shared by the live websocket_message hook and the
    offline replay harness so both exercise identical logic."""
    if mp is None:
        return
    if not from_client:
        if _is_start_game_resp(mp):
            new_game_event.set()
            reroll_events.clear()
            chosen_fates.clear()
            daoyun_grant_events.clear()
            _team1_snapshot.clear()
            _daoyun_pending_picks.clear()
            globals()["_daoyun_random_pending"] = False
            # Reset the stale sidejob career pick from the previous game so
            # the Counter doesn't auto-populate the wrong sidejob's pool at
            # R1 of the new game before the new SelectCareerReq arrives.
            shadow_state.last_career_pick = 0
            # The user is starting their own match — definitely not spectating
            # anymore. Clear the flag so GameStatus / PlayerData paths resume
            # updating the shadow from the user's own player struct.
            _set_spectating(False)
            # YX_DEBUG=1: open a fresh battle_log/<timestamp>/ folder for this
            # game (copies the previous game's BattleLog.json on the way out).
            _open_battle_log_dir()
            # Drop any seasonal-parked cards so they don't leak into the new game
            # (seasonal is otherwise preserved across round resets within a game).
            if shadow_state.shadow is not None:
                shadow_state.shadow.seasonal.clear()
            with _last_my_state_lock:
                globals()["_last_my_state"] = None
        if _is_round_end(mp):
            round_ended_event.set()
        note = (_handle_replace_card_resp(mp)
                or _handle_refine_card_resp(mp)
                or _handle_card_operation_resp(mp)
                or _handle_pending_daoyun(mp)
                or _handle_pending_talent(mp)
                or _handle_battle_result(mp)
                or _handle_player_data(mp))
        if note:
            _log(note)
    else:
        # Client→server: catch spectator requests BEFORE the regular handlers.
        # SpectateReq / SpectateFriendReq flip _is_spectating so subsequent
        # GameStatus / PlayerData don't reset the shadow with the spectated
        # player's data (which would leak their hand into the user's UI).
        if _is_spectate_msg(mp):
            _set_spectating(True)
        # Safety net: any in-game ACTION the client sends proves the user is
        # in their own game (spectators can't move/refine/reroll cards). Clear
        # the flag so a stale SpectateReq from earlier lobby browsing doesn't
        # keep the counter frozen after the user actually starts playing.
        # StartGameResp also clears, but it doesn't always fire (e.g. AI /
        # practice games, reconnecting to an in-progress match).
        elif _is_spectating:
            inner_c = _inner(mp)
            if inner_c and inner_c.get("type") in (
                    "MoveCardReq", "InsertCardReq", "ReplaceCardReq",
                    "RefineCardReq", "CardOperationReq", "SelectCareerReq"):
                _set_spectating(False)
        note = (_handle_move_card_req(mp)
                or _handle_insert_card_req(mp)
                or _handle_simple_client_pact(mp)
                or _handle_select_career_req(mp))
        if note:
            _log(note)

    status = _try_push_game_state(mp)
    if status:
        _log(status)


# ─── Diagnostic capture (opt-in via YX_CAPTURE=1) ─────────────────────────────
# Records every non-heartbeat WS frame to proxy/output/traffic.jsonl (same shape
# the offline replay/analysis tools expect) and writes a running message-type
# tally to proxy/output/unhandled_types.txt, flagging types no handler consumes.
# Additive logging only — does not alter decoding or tracking behavior.
# Default OFF (opt-in). Set YX_CAPTURE=1 to enable, or use run_live.ps1 -Capture.
# Was default-ON during the tracking-debug phase, but that caused replay runs
# (which import addon) to silently truncate prior captures. Now opt-in.
CAPTURE = os.environ.get("YX_CAPTURE", "0") != "0"
_CAPTURE_DIR = Path(__file__).resolve().parent / "output"
_TRAFFIC_PATH = _CAPTURE_DIR / "traffic.jsonl"
_UNHANDLED_PATH = _CAPTURE_DIR / "unhandled_types.txt"

# ─── Debug mode (YX_DEBUG=1) — per-game folders under battle_log/ ─────────────
# When enabled, each StartGameResp opens a fresh folder
#   battle_log/<YYYY-MM-DD_HHMMSS>/
# containing four files for that game:
#   msgdump.jsonl       — every WS frame (same shape as traffic.jsonl)
#   shadow_log.txt      — translated/interpreted shadow events
#   deck_tracker.jsonl  — view-model snapshots (what the UI sees) per push
#   battle_log.json     — copy of the game's local BattleLog.json
# Always-on in the published build so users can share logs for debugging
# and so the data exists for the planned "review past games" feature.
# Dev runs stay opt-in via YX_DEBUG=1 to keep `python app.py` quiet.
DEBUG = (
    os.environ.get("YX_DEBUG", "0") != "0"
    or getattr(sys, "frozen", False)
)
# Where the per-game folders are written. In a PyInstaller-frozen build,
# Path(__file__).parent.parent points into the _MEIPASS temp dir which is
# read-only and ephemeral — useless for log retention. Use the .exe's own
# folder so users can browse, zip, and send logs back without hunting for
# AppData paths. (Lite stores its logs the same way — see yxlite-log.txt.)
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BATTLE_LOG_ROOT = _PROJECT_ROOT / "battle_log"
_battle_log_dir: Path | None = None    # current game's folder (None if no game active)
_battle_log_lock = threading.Lock()


def _open_battle_log_dir() -> Path | None:
    """Create a fresh battle_log/<timestamp>/ folder for a new game and make
    it the current target for msgdump / shadow_log / deck_tracker writes.
    Also copies BattleLog.json into the PREVIOUS game's folder (if any)
    before rotating, so the just-finished game has its battle log captured."""
    global _battle_log_dir
    if not DEBUG:
        return None
    # Close out the previous game by copying its BattleLog.json.
    _copy_battle_log_into_dir()
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        new_dir = _BATTLE_LOG_ROOT / ts
        new_dir.mkdir(parents=True, exist_ok=True)
        with _battle_log_lock:
            _battle_log_dir = new_dir
        # Pre-create empty files so the folder is obviously per-game.
        (new_dir / "msgdump.jsonl").write_text("", encoding="utf-8")
        (new_dir / "deck_tracker.jsonl").write_text("", encoding="utf-8")
        # shadow_log.txt is created lazily by shadow_state on first write.
        # Tell shadow_state where the per-game shadow_log lives.
        try:
            import shadow_state
            shadow_state.set_debug_trace_log_path(new_dir / "shadow_log.txt")
        except Exception:
            pass
        print(f"[debug] new battle_log dir: {new_dir}", flush=True)
        return new_dir
    except Exception as e:
        print(f"[debug] failed to open battle_log dir: {e}", flush=True)
        return None


def _copy_battle_log_into_dir() -> None:
    """Copy the user's local BattleLog.json (game-managed) into the current
    debug battle_log dir as battle_log.json. Safe to call repeatedly — the
    latest copy wins. Also called on app exit via atexit."""
    if not DEBUG:
        return
    with _battle_log_lock:
        dest_dir = _battle_log_dir
    if dest_dir is None:
        return
    try:
        from battle_log import DEFAULT_PATH as _BLOG_SRC
        if not _BLOG_SRC.exists():
            return
        import shutil
        shutil.copy2(str(_BLOG_SRC), str(dest_dir / "battle_log.json"))
    except Exception:
        pass


def write_deck_tracker_snapshot(view_model: dict) -> None:
    """Append one view-model snapshot to deck_tracker.jsonl. Called from the
    consumer thread after every push() so we have a full record of what the
    UI showed across the game."""
    if not DEBUG:
        return
    with _battle_log_lock:
        dest_dir = _battle_log_dir
    if dest_dir is None:
        return
    try:
        entry = {
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "vm": view_model,
        }
        with (dest_dir / "deck_tracker.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# Refresh BattleLog.json copy at the end of every state push and on exit.
import atexit
atexit.register(_copy_battle_log_into_dir)

# Message types our handlers actually consume (for the unhandled tally).
_HANDLED_TYPES = {
    # S→C
    "GameStatus", "ReplaceCardResp", "RefineCardResp", "CardOperationResp",
    "PendingDaoYunResp", "PendingTalentResp", "BattleResult", "PlayerData",
    "StartGameResp",
    # C→S
    "MoveCardReq", "InsertCardReq", "SimpleClientPact", "SelectCareerReq",
}
# Pure transport/lobby heartbeats — never card-affecting; skipped to keep the
# capture small.
_CAPTURE_SKIP = {"Ping", "Pong"}

_capture_lock = threading.Lock()
_type_tally: dict = {}        # (direction, type) -> count
_capture_frames = 0

if CAPTURE:
    try:
        _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        _TRAFFIC_PATH.write_text("", encoding="utf-8")       # fresh per session
        _UNHANDLED_PATH.write_text("", encoding="utf-8")
        print(f"[capture] ON → writing frames to {_TRAFFIC_PATH}", flush=True)
    except Exception:
        pass
else:
    print("[capture] OFF (set YX_CAPTURE=1 / use run_live.ps1 -Capture to record)",
          flush=True)


def _flush_unhandled():
    try:
        lines = ["# message-type tally for this capture session",
                 "#   '*' = a handler consumes it; 'x' = received but ignored", ""]
        for (direction, mtype), count in sorted(_type_tally.items(), key=lambda kv: -kv[1]):
            mark = "* " if mtype in _HANDLED_TYPES else "x "
            lines.append(f"{mark}{count:6d}  {direction:14s} {mtype}")
        _UNHANDLED_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def _capture_frame(mp, from_client: bool, url: str = ""):
    """Append one decoded frame to traffic.jsonl and tally its type. Live-only
    (called from websocket_message), never during replay."""
    global _capture_frames
    inner = (mp[1] if isinstance(mp, list) and len(mp) > 1 and isinstance(mp[1], dict)
             else None)
    mtype = inner.get("type") if inner else None
    if mtype in _CAPTURE_SKIP:
        return
    direction = "client->server" if from_client else "server->client"
    event = {
        "type": "ws_frame",
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "url": url,
        "decoded": {"msgpack": mp},
    }
    # NOTE: raw bytes are intentionally not stored on ws_frame to keep the
    # msgdump small for typical game messages (msgpack is enough). If you
    # need to inspect the opcode byte for debugging schema-decoded frames,
    # use _capture_undecoded (opcode 0x0e/0x0f) which DOES store raw hex.
    with _capture_lock:
        try:
            with _TRAFFIC_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # Mirror into the per-game debug folder if DEBUG mode is active.
        if DEBUG and _battle_log_dir is not None:
            try:
                with (_battle_log_dir / "msgdump.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception:
                pass
        key = (direction, mtype or "?")
        _type_tally[key] = _type_tally.get(key, 0) + 1
        _capture_frames += 1
        do_flush = (_capture_frames % 20 == 0)
        count = _capture_frames
    if do_flush:
        _flush_unhandled()
        # Also refresh the BattleLog.json copy periodically.
        _copy_battle_log_into_dir()
        print(f"[capture] {count} frames recorded", flush=True)


def _capture_undecoded(raw, from_client: bool, url: str = ""):
    """Record a binary WS frame that produced no msgpack, so we can see whether
    missing actions are decode failures (these appear) vs dropped frames (gaps
    in timestamps with nothing here). Also records the WebSocket URL so we
    can tell if multiple rooms/connections are in play."""
    direction = "client->server" if from_client else "server->client"
    try:
        data = bytes(raw)
    except Exception:
        return
    event = {
        "type": "ws_undecoded",
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "direction": direction,
        "url": url,
        "len": len(data),
        "hex": data.hex(),
    }
    with _capture_lock:
        try:
            with _TRAFFIC_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if DEBUG and _battle_log_dir is not None:
            try:
                with (_battle_log_dir / "msgdump.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception:
                pass
        _type_tally[(direction, "<undecoded>")] = _type_tally.get((direction, "<undecoded>"), 0) + 1


# ─── The mitmproxy addon ──────────────────────────────────────────────────────
class YiXianInterceptor:
    def response(self, flow):
        if TARGET_HOST not in flow.request.pretty_host or flow.response is None:
            return
        if "application/json" not in flow.response.headers.get("content-type", ""):
            return
        if "/auth/login" not in flow.request.pretty_url:
            return
        try:
            body = json.loads(flow.response.text)
            uid = body.get("data", {}).get("userInfo", {}).get("uid", "")
            if uid:
                _set_me_uid(uid)
        except Exception:
            pass

    def websocket_message(self, flow):
        if TARGET_HOST not in flow.request.pretty_host:
            return
        msg = flow.websocket.messages[-1]
        is_binary = (isinstance(msg.content, (bytes, bytearray))
                     and getattr(msg.type, "value", msg.type) == 2)
        if not is_binary:
            return

        # Remember the live game flow so the auto-player can inject onto it.
        global _game_flow
        _game_flow = flow

        mp = decode_frame(msg.content).get("msgpack")
        if msg.from_client:
            _note_client_frame(bytes(msg.content), mp)
        if CAPTURE:
            ws_url = ""
            try:
                ws_url = flow.request.pretty_url
            except Exception:
                pass
            if mp is None:
                # A binary frame we couldn't turn into msgpack — record it so we
                # can tell whether missing actions are decode failures vs truly
                # absent (dropped) frames. Schema-encoded ROOM_STATE frames
                # (opcode 0x0e/0x0f) land here too, with full raw bytes so
                # we can later schema-decode them for HP / max_hp.
                _capture_undecoded(msg.content, msg.from_client, ws_url)
            else:
                _capture_frame(mp, msg.from_client, ws_url)
        process_msgpack(mp, msg.from_client)

    def done(self):
        if CAPTURE:
            _flush_unhandled()


addons = [YiXianInterceptor()]
