"""
verify_damage.py
────────────────
Verify the yisim damage calculator against a captured game.

Input:  a battle_log/<timestamp>/ folder produced by capture_game.bat
        with YX_DEBUG=1. The folder must contain msgdump.jsonl (wire
        frames) and battle_log.json (the game's own battle log).

Process:
  1. Replay msgdump.jsonl to extract per-round (board + stats + fates) for
     both me and the opponent.
  2. Run yisim's matchup simulation for each round via Node subprocess
     (tools/verify_damage.mjs).
  3. Read battle_log.json — the game logs `tiPo` (current 体魄) and
     `maxTiPo` per round. The damage YOU took in round N's battle is
     `maxTiPo[N+1] - tiPo[N+1]`. (BattleLog stamps the post-battle stats
     into the NEXT round's record.)
  4. Compare yisim's predicted damage taken vs. the actual.

Output: stdout + a markdown report at
        tools/verify_<game_folder_name>.md

Usage:
  .venv/Scripts/python.exe tools/verify_damage.py battle_log/2026-05-29_183358
  .venv/Scripts/python.exe tools/verify_damage.py battle_log/2026-05-29_183358 --username 哈基哈基哈菜加盐
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _card_to_slot(c: dict | None) -> dict | None:
    if not c:
        return None
    name = c.get("name", "")
    level = c.get("level", 1)
    is_dream = isinstance(name, str) and name.startswith("梦")
    if is_dream:
        return {"name": name, "level": level, "phase": level, "isDream": True}
    return {"name": name, "level": level, "isDream": False}


def _board_from_pb(p: dict, name_fn) -> list[dict]:
    """Decode a player struct's board (f200.6) into [{name, level}, ...]."""
    import shadow_state as _ss
    f200 = p.get("200") or p.get("200-1") or {}
    if not isinstance(f200, dict):
        return []
    b = f200.get("6", b"")
    if not isinstance(b, (bytes, bytearray)):
        return []
    try:
        cards = _ss.parse_board_from_varints(b, name_fn=name_fn) or []
    except Exception:
        return []
    return [{"name": c.name, "level": c.level} if c else None for c in cards]


# Fate-specific extra-card containers. Several fates store their card-pick
# list at p[200][N] for varying N. Each container has shape
#   {1: <fate_id>, 2: {1: <varint card-list bytes>}}
# We identify by (sub_field, fate_base_id_mod_10000):
#   p[200][14] / 199 = 五行玉瓶 (Five Elements Pure Vase) — vase contents
#   p[200][12] / 189 = 悟剑天赋 (Swordplay Talent)        — picked cards
def _fate_cards_from_pb(p: dict, sub_field: str, expected_fate_mod: int,
                        name_fn) -> list[dict]:
    import shadow_state as _ss
    f200 = p.get("200") or p.get("200-1") or {}
    if not isinstance(f200, dict):
        return []
    container = f200.get(sub_field)
    if not isinstance(container, dict):
        return []
    fate_id = int(container.get("1", 0) or 0)
    if fate_id % 10000 != expected_fate_mod:
        return []
    inner = container.get("2")
    if not isinstance(inner, dict):
        return []
    b = inner.get("1", b"")
    if not isinstance(b, (bytes, bytearray)) or not b:
        return []
    try:
        cards = _ss.parse_board_from_varints(b, name_fn=name_fn, n_slots=8) or []
    except Exception:
        return []
    return [{"name": c.name, "level": c.level} if c else None for c in cards]


def _vase_cards_from_pb(p: dict, name_fn) -> list[dict]:
    """Decode 五行玉瓶 contents from p[200][14] if present."""
    return _fate_cards_from_pb(p, "14", 199, name_fn)


def _swordplay_talent_cards_from_pb(p: dict, name_fn) -> list[dict]:
    """Decode 悟剑天赋 picked cards from p[200][12] if present."""
    return _fate_cards_from_pb(p, "12", 189, name_fn)


# Map CJK card name → yisim base id (5-char prefix without level digit).
# Loaded lazily from vendor/yisim-master/names.json.
_CN_TO_YISIM_BASE_ID: dict[str, str] | None = None
def _cn_to_yisim_base_id() -> dict[str, str]:
    global _CN_TO_YISIM_BASE_ID
    if _CN_TO_YISIM_BASE_ID is not None:
        return _CN_TO_YISIM_BASE_ID
    out: dict[str, str] = {}
    try:
        names = json.loads(Path("vendor/yisim-master/names.json").read_text(encoding="utf-8"))
    except Exception:
        _CN_TO_YISIM_BASE_ID = out
        return out
    swogi = {}
    try:
        swogi = json.loads(Path("vendor/yisim-master/swogi.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    for entry in names:
        cn = entry.get("namecn")
        if not cn:
            continue
        yid = str(entry.get("id", ""))
        # Prefer ids that exist in swogi (resolves stub-id collisions).
        prev = out.get(cn)
        if prev and prev in swogi:
            continue
        out[cn] = yid
    _CN_TO_YISIM_BASE_ID = out
    return out


def _cards_to_yisim_base_ids(cards: list[dict]) -> list[str]:
    """Convert [{name, level}, ...] to a list of yisim 'card_id_without_level'
    strings (the 5-char prefix). Skips unresolvable names."""
    out: list[str] = []
    cn_map = _cn_to_yisim_base_id()
    for c in cards or []:
        if not c or not c.get("name"):
            continue
        name = str(c["name"]).replace("•", "·")
        base = cn_map.get(name)
        if not base:
            continue
        # Strip trailing digit (level placeholder) to get 5-char prefix.
        out.append(base[:-1])
    return out


def _slot_from_card_dict(c: dict | None) -> dict | None:
    if not c:
        return None
    name = c.get("name", "")
    level = c.get("level", 1)
    is_dream = isinstance(name, str) and name.startswith("梦")
    if is_dream:
        return {"name": name, "level": level, "phase": level, "isDream": True}
    return {"name": name, "level": level, "isDream": False}


def extract_rounds(msgdump_path: Path) -> list[dict]:
    """Replay msgdump.jsonl and snapshot, per round:
      - ME stats (hp/tipo/xiuwei/realm/fates) from R(N) GameStatus (pre-battle).
      - ME board for the R(N) BATTLE: snapshot of my player struct in
        R(N+1) GameStatus (boards carry over between rounds, so R(N+1)'s
        start-of-round board = R(N)'s end-of-prep / battle board).
      - OPP stats and board: same idea — opp's pb[5] entry in R(N+1)
        GameStatus, looked up by the opponent's UID (recorded at R(N)).
    The last round has no R(N+1) → skipped because we can't see its
    post-prep board."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "proxy"))
    import addon  # noqa: E402
    import runtime  # noqa: E402
    from game_state import card_name  # noqa: E402
    import shadow_state as _ss  # noqa: E402
    # Fate → talent-object conversion (uses fate_talent_map.json). yisim
    # ignores raw fate ids; it needs {runtimeKey, simulationKind, ...} shapes.
    from proxy_view import _fates_to_talents  # noqa: E402

    # Phase 1: walk msgdump and collect raw per-round per-player state from
    # every GameStatus, plus the me_uid and the matchup UIDs.
    per_round: dict[int, dict] = {}   # round_num -> {"my_uid", "players": {uid: pb}}

    def _decode_gs(raw: bytes) -> dict:
        import blackboxprotobuf
        try:
            from addon import _GAMESTATUS_TYPEDEF as _TD
        except Exception:
            _TD = None
        try:
            pb, _ = blackboxprotobuf.decode_message(raw, _TD) if _TD else blackboxprotobuf.decode_message(raw)
        except Exception:
            return {}
        return pb if isinstance(pb, dict) else {}

    import json as _json, base64
    me_uid_from_gs: str | None = None
    with msgdump_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = _json.loads(line)
            except Exception:
                continue
            if e.get("type") != "ws_frame":
                continue
            mp = (e.get("decoded") or {}).get("msgpack")
            if not (isinstance(mp, list) and len(mp) >= 2 and isinstance(mp[1], dict)):
                continue
            if mp[1].get("type") != "GameStatus":
                continue
            data = mp[1].get("data") or ""
            try:
                pb = _decode_gs(base64.b64decode(data))
            except Exception:
                continue
            round_num = pb.get("1", 0)
            if not isinstance(round_num, int) or round_num <= 0:
                continue
            # Resolve me_uid from team_container pb[6].200.
            f6 = pb.get("6")
            if isinstance(f6, dict):
                ub = f6.get("200", b"")
                if isinstance(ub, (bytes, bytearray)):
                    cand = ub.decode("utf-8", "replace")
                    if cand and len(cand) >= 16:
                        me_uid_from_gs = cand
            # Gather all 5* (player) lists, handle blackboxprotobuf -1 split.
            players_raw: list[dict] = []
            for k, v in list(pb.items()):
                if not (k == "5" or (isinstance(k, str) and k.startswith("5-"))):
                    continue
                if isinstance(v, list):
                    players_raw.extend([x for x in v if isinstance(x, dict)])
                elif isinstance(v, dict):
                    players_raw.append(v)
            per_player: dict[str, dict] = {}
            for p in players_raw:
                pid_b = p.get("1", b"")
                pid = pid_b.decode("utf-8", "replace") if isinstance(pid_b, (bytes, bytearray)) else str(pid_b)
                if pid:
                    per_player[pid] = p
            if round_num not in per_round:
                # Use the FIRST GameStatus for each round (don't overwrite).
                # The first one fires right after the previous round's
                # BattleResult and captures the prior round's end-of-battle
                # state. Later GameStatus updates within the same round
                # reflect ongoing prep activity that pollutes the snapshot
                # — for example, R19 GS #1 (line 595, +2 after R18 BR)
                # shows R18's actual battle board, while R19 GS #2 (line 626)
                # shows the board after several R19 prep moves.
                per_round[round_num] = {"my_uid": me_uid_from_gs, "players": per_player}

    if not per_round:
        return []

    # Phase 1b: also walk BattleResult messages and pull the per-battle
    # cultivation. BR carries the "during-battle" cultivation at
    # pb[N][1][5] (and mirror at pb[N][1][200][3]) — this is different
    # from BL `exp` (post-battle, after xiuwei gain) and from the wire
    # GameStatus `f200[3]` (start-of-prep). For YiXianPai turn-order
    # resolution, the BR value is the authoritative one.
    #
    # We also pull the authoritative end-of-battle results:
    #   pb[4] = winner's remaining HP (the loser is at HP ≤ 0)
    #   pb[6] = loser's life delta (negative; matches BL lifeDelta)
    # These are used to verify yisim's myHp/oppHp predictions instead of
    # the unreliable BL life[N] - life[N+1] (which is biased by between-
    # round regen and other passive effects).
    br_cultivation: dict[int, dict[str, int]] = {}  # round → {uid: cultivation}
    br_battle: dict[int, dict] = {}                 # round → {winner_hp, life_delta, me_overshoot, ...}
    with msgdump_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = _json.loads(line)
            except Exception:
                continue
            if e.get("type") != "ws_frame":
                continue
            mp = (e.get("decoded") or {}).get("msgpack")
            if not (isinstance(mp, list) and len(mp) >= 2 and isinstance(mp[1], dict)):
                continue
            if mp[1].get("type") != "BattleResult":
                continue
            try:
                import blackboxprotobuf
                br_pb, _ = blackboxprotobuf.decode_message(base64.b64decode(mp[1].get("data") or ""))
            except Exception:
                continue
            if not isinstance(br_pb, dict):
                continue
            rn = br_pb.get("7")
            if not isinstance(rn, int) or rn <= 0:
                continue
            # Each combatant is pb[1] / pb[2]; their UID is in [1][1] and
            # cultivation in [1][5]. Match by UID to the GameStatus my_uid.
            for combatant_key in ("1", "2"):
                cmb = br_pb.get(combatant_key)
                if not isinstance(cmb, dict):
                    continue
                inner = cmb.get("1")
                if not isinstance(inner, dict):
                    continue
                uid_b = inner.get("1", b"")
                uid_s = (uid_b.decode("utf-8", "replace")
                         if isinstance(uid_b, (bytes, bytearray)) else str(uid_b))
                cult = int(inner.get("5", 0) or 0)
                if uid_s and cult > 0:
                    br_cultivation.setdefault(rn, {})[uid_s] = cult
            # End-of-battle results.
            # pb[5] = pb[1].hp_end − pb[2].hp_end (verified against R11).
            # pb[6] = pb[1].life_delta − pb[2].life_delta (verified across rounds).
            # pb[1] doesn't have a fixed role (sometimes ME, sometimes OPP) —
            # we need to record the pb[1] UID to interpret pb[5] later.
            pb1_uid_b = (br_pb.get("1") or {}).get("1", {}).get("1", b"") if isinstance(br_pb.get("1"), dict) else b""
            pb1_uid_s = (pb1_uid_b.decode("utf-8", "replace")
                         if isinstance(pb1_uid_b, (bytes, bytearray)) else str(pb1_uid_b))
            # Per-combatant PRE-BATTLE stat ledger lives at pb[N][1][200][9].
            # Stat ids we care about:
            #   369   = speed (modifies turn-order: cult+speed beats cult alone)
            #   10011 = divine_power_grass_stacks (神力草, +increase_atk at battle start)
            #   10015 = toxic_purple_fern_stacks (紫蕨, +internal_injury to enemy at start)
            #   10023 = current physique (tipo)
            #   10024 = max physique
            # The herb stats sit on the combatant WHO USED the herb; yisim's
            # battle-start hook applies the effect (e.g. enemy debuff for fern).
            pre_battle_phys: dict[str, tuple[int, int]] = {}  # uid → (tipo, max_tipo)
            pre_battle_herbs: dict[str, dict[str, int]] = {}  # uid → {herb_stack_key: count}
            pre_battle_speed: dict[str, int] = {}  # uid → speed
            for combatant_key in ("1", "2"):
                cmb = br_pb.get(combatant_key)
                if not isinstance(cmb, dict):
                    continue
                inner = cmb.get("1")
                if not isinstance(inner, dict):
                    continue
                uid_b = inner.get("1", b"")
                uid_s = (uid_b.decode("utf-8", "replace")
                         if isinstance(uid_b, (bytes, bytearray)) else str(uid_b))
                stat_list = (inner.get("200") or {}).get("9") or []
                tipo_cur = 0
                tipo_max = 0
                speed = 0
                herbs: dict[str, int] = {}
                if isinstance(stat_list, list):
                    for entry in stat_list:
                        if not isinstance(entry, dict):
                            continue
                        sid = int(entry.get("1", 0) or 0)
                        sval = int(entry.get("2", 0) or 0)
                        if sid == 10023:
                            tipo_cur = sval
                        elif sid == 10024:
                            tipo_max = sval
                        elif sid == 369 and sval > 0:
                            speed = sval
                        elif sid == 10011 and sval > 0:
                            herbs["divine_power_grass_stacks"] = sval
                        elif sid == 10015 and sval > 0:
                            herbs["toxic_purple_fern_stacks"] = sval
                if uid_s and (tipo_cur or tipo_max):
                    pre_battle_phys[uid_s] = (tipo_cur, tipo_max)
                if uid_s and herbs:
                    pre_battle_herbs[uid_s] = herbs
                if uid_s and speed:
                    pre_battle_speed[uid_s] = speed
            br_battle[rn] = {
                "pb4": int(br_pb.get("4", 0) or 0),
                "pb5_hp_diff": int(br_pb.get("5", 0) or 0),
                "pb6_life_diff": int(br_pb.get("6", 0) or 0),
                "pb1_uid": pb1_uid_s,
                "pre_battle_phys": pre_battle_phys,
                "pre_battle_herbs": pre_battle_herbs,
                "pre_battle_speed": pre_battle_speed,
            }

    # Phase 2: for each round N (except the last), pull stats from R(N)'s
    # player struct and the BATTLE boards from R(N+1)'s player structs.
    def _player_stats(p: dict) -> dict:
        from game_state import parse_player_stats, _to_str
        f200 = p.get("200") or p.get("200-1") or {}
        if not isinstance(f200, dict):
            f200 = {}
        xiuwei, tipo, realm = parse_player_stats(f200)
        display_name = _to_str(p.get("2", "")) if p.get("2") else ""
        fates: list[int] = []
        try:
            fates = list(_ss.decode_varint_list(f200.get("5") or p.get("13") or b""))
        except Exception:
            pass
        return {
            "displayName": display_name,
            # HP is filled in from battle_log.json after extraction — the wire
            # doesn't carry the displayed HP, and there is NO clean formula
            # (40+xiuwei was wrong; the user clarified the actual game uses
            # base + class + breakthrough bonuses that aren't on the wire).
            "hp": 0,
            "tipo": tipo or 0,
            "xiuwei": xiuwei or 0,
            "realm": realm or 1,
            "fates": fates,
        }

    rounds_sorted = sorted(per_round.keys())
    rounds: list[dict] = []
    for n in rounds_sorted:
        # Need R(N+1) for battle board.
        n_next = n + 1
        if n_next not in per_round:
            continue
        cur = per_round[n]
        nxt = per_round[n_next]
        my_uid = cur["my_uid"] or nxt["my_uid"]
        if not my_uid:
            continue
        # Stats from R(N)'s ME player struct.
        my_pb_cur = cur["players"].get(my_uid)
        if not my_pb_cur:
            continue
        my_stats = _player_stats(my_pb_cur)
        # Battle board from R(N+1)'s ME player struct.
        my_pb_next = nxt["players"].get(my_uid)
        if not my_pb_next:
            continue
        my_board = _board_from_pb(my_pb_next, name_fn=card_name)
        # Fates from R(N+1) too — if ME broke through during R(N) prep
        # the fate list at start-of-R(N) (e.g. 凡躯) differs from what
        # was live in the R(N) battle (e.g. 灵炁奔涌 + 得炁 after the
        # 得炁 phase-5 pick transforms 凡躯). R(N+1)'s GameStatus
        # reflects the post-prep / end-of-battle state, so its fate
        # list is what was actually applied during R(N)'s battle.
        my_stats_next = _player_stats(my_pb_next)
        my_stats["fates"] = my_stats_next["fates"] or my_stats["fates"]
        # Opp UID: next_opponent_id on ME at R(N).
        opp_uid_raw = my_pb_cur.get("9", b"")
        opp_uid = opp_uid_raw.decode("utf-8", "replace") if isinstance(opp_uid_raw, (bytes, bytearray)) else str(opp_uid_raw)
        if not opp_uid:
            continue
        opp_pb_cur = cur["players"].get(opp_uid)
        opp_pb_next = nxt["players"].get(opp_uid)
        if not opp_pb_cur or not opp_pb_next:
            continue
        opp_stats = _player_stats(opp_pb_cur)
        opp_board = _board_from_pb(opp_pb_next, name_fn=card_name)
        # Same fate-refresh logic for OPP: end-of-R(N) fates are at R(N+1).
        # The user's R11 example: OPP's phase-1 fate 凡躯 transforms into
        # 灵炁奔涌 during R11 prep (得炁 phase-5 pick triggers the swap),
        # but R(N) GameStatus still shows the pre-transform list.
        opp_stats_next = _player_stats(opp_pb_next)
        opp_stats["fates"] = opp_stats_next["fates"] or opp_stats["fates"]
        # Unlocked board slots scale with round number: R1=3, R2=4, ..., R6+=8.
        # Cards beyond `deck` are in LOCKED slots and don't play.
        deck = max(1, min(n + 2, 8))
        # Build full talent objects so yisim can apply runtime-stack fates
        # like 云海连绵 (id 14 → endurance_as_cloud_sea_stacks). Raw ids
        # don't satisfy yisim's normalizeTalents and silently no-op.
        my_talents, my_fate_names = _fates_to_talents(my_stats["fates"])
        opp_talents, opp_fate_names = _fates_to_talents(opp_stats["fates"])
        # Cultivation for turn-order: pull from BattleResult.pb[N][1][5],
        # which is what the game uses to decide who acts first. Fall back
        # to wire xiuwei if BR is missing (e.g. last round, no battle yet).
        br_round = br_cultivation.get(n, {})
        my_cult = br_round.get(my_uid, my_stats["xiuwei"])
        opp_cult = br_round.get(opp_uid, opp_stats["xiuwei"])
        br_b = br_battle.get(n, {})
        # Determine the sign of pb[5] relative to ME's perspective:
        # if pb[1] is ME, pb[5] = ME_end − OPP_end (ME perspective).
        # if pb[1] is OPP, pb[5] = OPP_end − ME_end (need to negate).
        br_pb1_is_me = br_b.get("pb1_uid") == my_uid
        rounds.append({
            "round": n,
            "me_uid": my_uid,
            # Authoritative end-of-battle results from BR (the wire — not BL).
            "br_pb4": br_b.get("pb4"),
            "br_pb5_hp_diff": br_b.get("pb5_hp_diff"),
            "br_pb6_life_diff": br_b.get("pb6_life_diff"),
            "br_pb1_is_me": br_pb1_is_me,
            "br_pre_battle_phys": br_b.get("pre_battle_phys") or {},
            "br_pre_battle_herbs": br_b.get("pre_battle_herbs") or {},
            "br_pre_battle_speed": br_b.get("pre_battle_speed") or {},
            "me": {
                "displayName": my_stats["displayName"],
                "deckSlots": deck,
                "hp": my_stats["hp"],
                "tipo": my_stats["tipo"],
                "max_tipo": my_stats["tipo"],  # filled in by BattleLog when present
                "xiuwei": my_cult,    # cultivation used for turn-order (from BR)
                "realm": my_stats["realm"],
                "fates": my_talents,
                "fateNames": my_fate_names,
                "slots": [_slot_from_card_dict(c) for c in (my_board or [None]*deck)[:deck]],
                # 五行玉瓶 vase contents (if fate active) — yisim's
                # do_five_elements_pure_vase reads this list at sim start.
                "vase_cards": [_slot_from_card_dict(c) for c in _vase_cards_from_pb(my_pb_next, name_fn=card_name) if c],
                "swordplay_talent_card_ids": _cards_to_yisim_base_ids(_swordplay_talent_cards_from_pb(my_pb_next, name_fn=card_name)),
            },
            "opponent": {
                "displayName": opp_stats["displayName"],
                "uid": opp_uid,
                "deckSlots": deck,
                "hp": opp_stats["hp"],
                "tipo": opp_stats["tipo"],
                "max_tipo": opp_stats["tipo"],
                "xiuwei": opp_cult,   # cultivation used for turn-order (from BR)
                "realm": opp_stats["realm"],
                "fates": opp_talents,
                "fateNames": opp_fate_names,
                "slots": [_slot_from_card_dict(c) for c in (opp_board or [None]*deck)[:deck]],
                "vase_cards": [_slot_from_card_dict(c) for c in _vase_cards_from_pb(opp_pb_next, name_fn=card_name) if c],
                "swordplay_talent_card_ids": _cards_to_yisim_base_ids(_swordplay_talent_cards_from_pb(opp_pb_next, name_fn=card_name)),
            },
        })
    return rounds


def run_yisim(rounds_data: list[dict], work_dir: Path) -> list[dict]:
    """Run yisim via the verify_damage.mjs Node script. Returns the array
    of per-round simulation results."""
    rounds_file = work_dir / "_rounds.json"
    out_file = work_dir / "_yisim_out.json"
    rounds_file.write_text(json.dumps(rounds_data, ensure_ascii=False), encoding="utf-8")
    runner = ROOT / "tools" / "verify_damage.mjs"
    if not runner.exists():
        raise FileNotFoundError(f"yisim runner not found: {runner}")
    proc = subprocess.run(
        ["node", str(runner), str(rounds_file), str(out_file)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(f"yisim runner failed (exit {proc.returncode})")
    return json.loads(out_file.read_text(encoding="utf-8"))


def read_battle_log(path: Path) -> dict[int, dict[str, dict]]:
    """Read battle_log.json into {round: {username: player_record}}.
    The file format: first line is a session id; every other line is a
    JSON object with `round` and `players`."""
    out: dict[int, dict[str, dict]] = {}
    if not path.exists() or path.stat().st_size == 0:
        return out
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        r = rec.get("round")
        if not isinstance(r, int):
            continue
        out[r] = {}
        for p in rec.get("players", []) or []:
            if not isinstance(p, dict):
                continue
            uname = p.get("username") or p.get("userxname")
            if uname:
                out[r][uname] = p
    return out


def auto_detect_username(bl: dict, me_uid: str,
                          rounds: list | None = None) -> str | None:
    """Pick the user's display_name. Source of truth: the wire's GameStatus
    extracts each player's display_name from the protobuf; rounds_data[0]
    ['me']['displayName'] is the user's own name, captured authoritatively
    from the connection's perspective (no heuristic needed).

    Falls back to legacy "longest non-bot name in BL" only if rounds aren't
    provided AND no me_uid is given — that path is wrong for multi-human
    games where another human has a longer ASCII name than the user's CJK
    name, since Python `len(str)` counts characters not bytes.
    """
    # Preferred: pull from msgdump-extracted rounds (the wire is authoritative).
    if rounds:
        for r in rounds:
            name = (r.get("me") or {}).get("displayName")
            if name:
                return name
    if not bl:
        return None
    first_round = next(iter(bl.values()), {})
    if not first_round:
        return None
    if me_uid and me_uid in first_round:
        return me_uid
    # Legacy fallback heuristic — kept for back-compat but wrong for
    # multi-human games (`cococococo` 10 chars > `传奇角色先天12修` 8 chars).
    import re
    bot_re = re.compile(r"^ai\d+-lv\d+$")
    candidates = [n for n in first_round if not bot_re.match(n)]
    if candidates:
        return max(candidates, key=len)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("game_folder", type=Path, help="battle_log/<timestamp>/ folder")
    ap.add_argument("--username", default=None,
                    help="user's in-game display name (auto-detected if absent)")
    args = ap.parse_args()

    folder = args.game_folder.resolve()
    if not folder.is_dir():
        sys.exit(f"not a directory: {folder}")
    msgdump = folder / "msgdump.jsonl"
    battle_log_path = folder / "battle_log.json"
    if not msgdump.exists() or msgdump.stat().st_size == 0:
        sys.exit(f"missing or empty msgdump.jsonl in {folder}")

    print(f"=== Verifying {folder.name} ===\n")
    print("[1/5] Replaying msgdump.jsonl ...")
    rounds_data = extract_rounds(msgdump)
    print(f"      Extracted {len(rounds_data)} rounds")

    print("\n[2/5] Reading battle_log.json ...")
    bl = read_battle_log(battle_log_path)
    print(f"      {len(bl)} battle-log rounds")
    if not bl:
        print(f"      WARN: battle_log.json is empty or missing — actual-damage column will be blank.")

    me_username = args.username or auto_detect_username(bl, "", rounds_data)
    if not me_username and bl:
        print(f"      WARN: couldn't auto-detect user — pass --username explicitly")
    else:
        print(f"      User: {me_username!r}")

    print("\n[3/5] Filling HP/max_tipo from BattleLog (with BR overrides) ...")
    # The wire does not carry HP. battle_log.json is the only authoritative
    # source for HP. For physique (tipo/max_tipo), BL records the POST-battle
    # + POST-breakthrough state, which is wrong for the battle simulation
    # (R8 OPP is a confirmed example: BL says 45/50 but BR's pre-battle stat
    # ledger says 40/45). When BR carries pre-battle physique, prefer it
    # over BL.
    #
    # FALLBACK: when BL is missing HP for a round (incomplete capture), use
    # the user's empirical formula based on realm-per-round:
    #   - base 40
    #   - +2 per round (round 2 onward)
    #   - breakthrough bonus applied at round R when realm[R+1] > realm[R]
    #     (breakthrough happens during round R; GS shows new realm at R+1)
    #   - bonuses: realm 1->2=+5, 2->3=+7, 3->4=+10, 4->5=+13
    # This formula was verified to match EXACTLY for one game (no HP-boosting
    # cards). For games with 大还丹 etc. it under-counts; treat as approximate.
    _bt_bonus = {2: 5, 3: 7, 4: 10, 5: 13}
    def _hp_formula(realm_seq):
        n = len(realm_seq)
        hp = [40]
        for r in range(1, n):
            hp.append(hp[r-1] + 2)
        for r in range(1, n):
            if realm_seq[r] > realm_seq[r-1]:
                for nr in range(realm_seq[r-1] + 1, realm_seq[r] + 1):
                    for k in range(r-1, n):
                        hp[k] += _bt_bonus.get(nr, 0)
        return hp

    # Build ME realm timeline (one entry per round, in order)
    me_realms = [int(r["me"]["realm"] or 1) for r in rounds_data]
    me_hp_formula = _hp_formula(me_realms) if me_realms else []
    # OPP realms differ per round (different opponent each round) — no single
    # per-opponent realm sequence. For OPP we fall back to round-aligned ME HP
    # only if BL is missing, since the OPP's realm at their last breakthrough
    # is what matters and we don't track that history. Better than 0.

    filled = 0
    formula_filled = 0
    br_overrides = 0
    for r in rounds_data:
        rn = r["round"]
        me_name = me_username or r["me"].get("displayName") or ""
        opp_name = r["opponent"].get("displayName") or ""
        me_rec = bl.get(rn, {}).get(me_name) if me_name else None
        opp_rec = bl.get(rn, {}).get(opp_name) if opp_name else None
        if me_rec:
            r["me"]["hp"] = int(me_rec.get("maxHp", 0) or 0)
            r["me"]["max_tipo"] = int(me_rec.get("maxTiPo", 0) or 0)
            r["me"]["tipo"] = int(me_rec.get("tiPo", r["me"].get("tipo", 0)) or 0)
            filled += 1
        else:
            # Formula fallback for ME when BL data is missing for this round.
            idx = rounds_data.index(r)
            if 0 <= idx < len(me_hp_formula):
                r["me"]["hp"] = me_hp_formula[idx]
                formula_filled += 1
        if opp_rec:
            r["opponent"]["hp"] = int(opp_rec.get("maxHp", 0) or 0)
            r["opponent"]["max_tipo"] = int(opp_rec.get("maxTiPo", 0) or 0)
            r["opponent"]["tipo"] = int(opp_rec.get("tiPo", r["opponent"].get("tipo", 0)) or 0)
        else:
            # OPP HP fallback: same realm history we have for ME doesn't apply,
            # but using ME's per-round HP as a proxy is much better than 0.
            # The damage simulation primarily compares ME's deal-damage curve
            # vs OPP's; absolute OPP HP only matters for executing kill checks.
            idx = rounds_data.index(r)
            if 0 <= idx < len(me_hp_formula):
                r["opponent"]["hp"] = me_hp_formula[idx]
        # BR override for pre-battle physique values.
        br_pre = (r.get("br_pre_battle_phys") or {})
        my_uid_self = next((u for u in br_pre if u == r.get("me_uid")), None) or me_name
        opp_uid_self = r["opponent"].get("uid")
        if opp_uid_self and opp_uid_self in br_pre:
            tipo_cur, tipo_max = br_pre[opp_uid_self]
            if tipo_max:
                r["opponent"]["tipo"] = tipo_cur
                r["opponent"]["max_tipo"] = tipo_max
                br_overrides += 1
        if my_uid_self and my_uid_self in br_pre:
            tipo_cur, tipo_max = br_pre[my_uid_self]
            if tipo_max:
                r["me"]["tipo"] = tipo_cur
                r["me"]["max_tipo"] = tipo_max
    print(f"      Filled HP for {filled}/{len(rounds_data)} rounds (me side, from BL)")
    if formula_filled:
        print(f"      Formula fallback applied to {formula_filled}/{len(rounds_data)} rounds (no BL)")
    print(f"      BR pre-battle physique overrides applied to OPP in {br_overrides} rounds")

    print("\n[4/5] Running yisim simulation ...")
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        yisim_results = run_yisim(rounds_data, work_dir)
    print(f"      Got {len(yisim_results)} round results")

    print("\n[5/5] Comparing ...")

    # Build per-round summary by joining yisim + battle-log.
    #
    # Two metrics, both with EXACT match required (no tolerance — the boards
    # and stats are fully known, so yisim should reproduce the game exactly).
    # Mismatches surface yisim calculator bugs or missing state extraction.
    lines = [
        f"# Damage Verification — `{folder.name}`",
        "",
        f"User: **{me_username or '(unknown)'}**",
        "",
        "Comparison metric is **`BR.pb[5]` = (pb[1].hp_end − pb[2].hp_end)**",
        "from the wire. yisim's equivalent is `myHp − oppHp` (re-signed",
        "based on whether BR.pb[1] is ME or OPP). Exact match means yisim's",
        "per-turn HP simulation reproduces the real game.",
        "🎲 flags battles with RNG cards (probe via high-vs-low rollMode).",
        "",
        "| R | Opp | yisim out | yisim ΔHP | actual ΔHP (pb5) | diff | match | 🎲 |",
        "|---:|---|---|---:|---:|---:|:---:|:---:|",
    ]

    rounds_by_num = {r["round"]: r for r in rounds_data}
    diff_match = 0
    diff_measurable = 0
    diff_total_err = 0

    for sim in yisim_results:
        r = sim["round"]
        rd = rounds_by_num.get(r, {})
        opp_name = rd.get("opponent", {}).get("displayName") or rd.get("opponent", {}).get("uid", "?")
        yisim_outcome = sim.get("outcome", "?")
        my_hp_end = sim.get("myHp")
        opp_hp_end = sim.get("oppHp")

        # Actual ΔHP from BR.pb[5] = pb[1].hp_end − pb[2].hp_end.
        actual_diff = rd.get("br_pb5_hp_diff")
        pb1_is_me = rd.get("br_pb1_is_me")

        # Yisim's equivalent: re-sign based on which combatant is pb[1].
        # If pb[1] is ME:  yisim_diff = myHp − oppHp
        # If pb[1] is OPP: yisim_diff = oppHp − myHp
        yisim_diff = None
        if my_hp_end is not None and opp_hp_end is not None:
            yisim_diff = (my_hp_end - opp_hp_end) if pb1_is_me else (opp_hp_end - my_hp_end)

        diff_str = "—"
        match_mark = ""
        if actual_diff is not None and yisim_diff is not None:
            diff_measurable += 1
            err = yisim_diff - actual_diff
            diff_str = f"{err:+d}"
            diff_total_err += abs(err)
            if err == 0:
                match_mark = "✓"
                diff_match += 1
            else:
                match_mark = "✗"

        rng_mark = "🎲" if sim.get("hasRng") else ""
        lines.append(
            f"| R{r} | {opp_name[:14]} | {yisim_outcome} | "
            f"{yisim_diff if yisim_diff is not None else '—'} | "
            f"{actual_diff if actual_diff is not None else '—'} | "
            f"{diff_str} | {match_mark} | {rng_mark} |"
        )

    if diff_measurable > 0:
        lines.append("")
        lines.append(f"**Exact ΔHP match: {diff_match}/{diff_measurable} "
                     f"({100 * diff_match / diff_measurable:.0f}%)**")
        lines.append(f"**Mean abs error: {diff_total_err / diff_measurable:.1f}**")

    report = "\n".join(lines) + "\n"
    report_path = ROOT / "tools" / f"verify_{folder.name}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {report_path}")
    print()
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
