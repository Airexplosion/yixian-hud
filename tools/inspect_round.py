"""
inspect_round.py
────────────────
Look up ONE round of a captured game and dump yisim's turn-by-turn HP for
both ME and OPP. Useful for digging into where the simulator diverges from
the real game.

Reuses verify_damage.py's extraction + BL-fill, then calls verify_damage.mjs
(which knows how to invoke yisim with the right options) and pretty-prints
the per-turn output for the requested round only.

Usage:
  .venv/Scripts/python.exe tools/inspect_round.py battle_log/<game> <round_number>
  .venv/Scripts/python.exe tools/inspect_round.py battle_log/2026-06-01_081328 6 --username 传奇角色先天12修
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Reuse verify_damage's helpers
sys.path.insert(0, str(ROOT / "tools"))
import verify_damage as vd  # noqa: E402


_BT_BONUS = {2: 5, 3: 7, 4: 10, 5: 13}


def _hp_formula(realm_seq):
    n = len(realm_seq)
    hp = [40]
    for r in range(1, n):
        hp.append(hp[r-1] + 2)
    for r in range(1, n):
        if realm_seq[r] > realm_seq[r-1]:
            for nr in range(realm_seq[r-1] + 1, realm_seq[r] + 1):
                for k in range(r-1, n):
                    hp[k] += _BT_BONUS.get(nr, 0)
    return hp


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect one round's per-turn HP")
    ap.add_argument("folder", type=Path, help="battle_log/<timestamp>/ folder")
    ap.add_argument("round", type=int, help="round number to inspect")
    ap.add_argument("--username", default=None,
                    help="username of ME (auto-detect if omitted)")
    args = ap.parse_args()

    folder = args.folder if args.folder.is_absolute() else (ROOT / args.folder)
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 2

    msgdump = folder / "msgdump.jsonl"
    if not msgdump.exists():
        print(f"Missing msgdump.jsonl", file=sys.stderr)
        return 2
    rounds = vd.extract_rounds(msgdump)
    if not rounds:
        print("No rounds extracted", file=sys.stderr)
        return 1

    # Fill HP from BL with formula fallback (same as verify_damage main).
    bl = vd.read_battle_log(folder / "battle_log.json")
    me_username = args.username or vd.auto_detect_username(bl, "", rounds)
    me_realms = [int(r["me"]["realm"] or 1) for r in rounds]
    me_hp_formula = _hp_formula(me_realms) if me_realms else []
    for r in rounds:
        rn = r["round"]
        me_name = me_username or r["me"].get("displayName") or ""
        opp_name = r["opponent"].get("displayName") or ""
        me_rec = bl.get(rn, {}).get(me_name) if me_name else None
        opp_rec = bl.get(rn, {}).get(opp_name) if opp_name else None
        if me_rec:
            r["me"]["hp"] = int(me_rec.get("maxHp", 0) or 0)
            r["me"]["max_tipo"] = int(me_rec.get("maxTiPo", 0) or 0)
            r["me"]["tipo"] = int(me_rec.get("tiPo", r["me"].get("tipo", 0)) or 0)
        else:
            idx = rounds.index(r)
            if 0 <= idx < len(me_hp_formula):
                r["me"]["hp"] = me_hp_formula[idx]
        if opp_rec:
            r["opponent"]["hp"] = int(opp_rec.get("maxHp", 0) or 0)
            r["opponent"]["max_tipo"] = int(opp_rec.get("maxTiPo", 0) or 0)
            r["opponent"]["tipo"] = int(opp_rec.get("tiPo", r["opponent"].get("tipo", 0)) or 0)
        else:
            idx = rounds.index(r)
            if 0 <= idx < len(me_hp_formula):
                r["opponent"]["hp"] = me_hp_formula[idx]
        # BR pre-battle physique override.
        br_pre = (r.get("br_pre_battle_phys") or {})
        opp_uid_self = r["opponent"].get("uid")
        if opp_uid_self and opp_uid_self in br_pre:
            tipo_cur, tipo_max = br_pre[opp_uid_self]
            if tipo_max:
                r["opponent"]["tipo"] = tipo_cur
                r["opponent"]["max_tipo"] = tipo_max
        my_uid_self = next((u for u in br_pre if u == r.get("me_uid")), None)
        if my_uid_self and my_uid_self in br_pre:
            tipo_cur, tipo_max = br_pre[my_uid_self]
            if tipo_max:
                r["me"]["tipo"] = tipo_cur
                r["me"]["max_tipo"] = tipo_max

    target = [r for r in rounds if r["round"] == args.round]
    if not target:
        avail = sorted(set(r["round"] for r in rounds))
        print(f"Round {args.round} not in capture. Available: {avail}", file=sys.stderr)
        return 1
    r = target[0]
    me = r["me"]
    opp = r["opponent"]

    print(f"\n=== R{args.round}: {me_username or '(unknown)'} vs {opp.get('displayName','?')} ===")
    print(f"\nME ({me_username}): realm={me['realm']} xw={me['xiuwei']} "
          f"hp={me['hp']} tipo={me['tipo']}/{me['max_tipo']}")
    print(f"  board: {[s['name']+' lv'+str(s.get('level',1)) if s else '_' for s in me['slots']]}")
    print(f"  fates: {[f.get('name','?') for f in (me.get('fates') or [])]}")
    print(f"\nOPP ({opp.get('displayName','?')}): realm={opp['realm']} xw={opp['xiuwei']} "
          f"hp={opp['hp']} tipo={opp['tipo']}/{opp['max_tipo']}")
    print(f"  board: {[s['name']+' lv'+str(s.get('level',1)) if s else '_' for s in opp['slots']]}")
    print(f"  fates: {[f.get('name','?') for f in (opp.get('fates') or [])]}")

    # Run yisim via inspect_round.mjs — calls simulate(maxTurns=1..N) so we
    # capture raw myHp/oppHp after each turn (incl. healing / +max_hp deltas
    # that perTurnTaken/perTurnDamage clamp away).
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        round_in = td_path / "round.json"
        result_out = td_path / "result.json"
        round_in.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        cmd = ["node", str(ROOT / "tools" / "inspect_round.mjs"),
               str(round_in), str(result_out), "16"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=str(ROOT))
        if proc.returncode != 0:
            print(f"\nyisim failed:\n{proc.stderr}", file=sys.stderr)
            return 1
        sim = json.loads(result_out.read_text(encoding="utf-8"))

    print(f"\n=== yisim (turnOrder={sim.get('turnOrder')}) ===")
    print(f"  outcome: {sim.get('outcome')}  endTurn: {sim.get('endTurn')}")
    print(f"  yisim end-state: myHp={sim.get('finalMyHp')} oppHp={sim.get('finalOppHp')}")

    per_turn = sim.get("perTurn") or []
    me_hp0 = sim.get("myStartHp", me["hp"])
    opp_hp0 = sim.get("oppStartHp", opp["hp"])

    print(f"\nstart of turn 1:  ME HP={me_hp0}   OPP HP={opp_hp0}")
    print(f"{'T':>3} {'ME HP':>7} {'OPP HP':>7} {'meMax':>6} {'oppMax':>6} "
          f"{'mePhy':>6} {'oppPhy':>6} {'meDef':>6} {'oppDef':>6} "
          f"{'cumDlt':>7} {'cumTkn':>7}")
    print(f"{'─'*3} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*6} {'─'*6} "
          f"{'─'*6} {'─'*6} {'─'*7} {'─'*7}")
    prev_me = me_hp0
    prev_opp = opp_hp0
    for t in per_turn:
        my_hp = t.get("myHp", 0)
        opp_hp = t.get("oppHp", 0)
        d_me = my_hp - prev_me
        d_opp = opp_hp - prev_opp
        sign_me = f"({'+' if d_me >= 0 else ''}{d_me})"
        sign_opp = f"({'+' if d_opp >= 0 else ''}{d_opp})"
        print(f"{t['turn']:>3} "
              f"{my_hp:>3}{sign_me:>4} {opp_hp:>3}{sign_opp:>4} "
              f"{t.get('myMaxHp',0):>6} {t.get('oppMaxHp',0):>6} "
              f"{t.get('myPhysique',0):>6} {t.get('oppPhysique',0):>6} "
              f"{t.get('myDef',0):>6} {t.get('oppDef',0):>6} "
              f"{t.get('cumDealt',0):>7} {t.get('cumTaken',0):>7}")
        prev_me = my_hp
        prev_opp = opp_hp

    print(f"\n=== Comparison ===")
    pb5 = r.get("br_pb5_hp_diff")
    pb1_is_me = r.get("br_pb1_is_me")
    actual_signed = pb5 if pb1_is_me else (-pb5 if pb5 is not None else None)
    yisim_signed = (sim.get("finalMyHp") or 0) - (sim.get("finalOppHp") or 0)
    print(f"  actual ΔHP (BR.pb[5], me-relative): {actual_signed}")
    print(f"  yisim  ΔHP (me − opp):              {yisim_signed}")
    if actual_signed is not None:
        print(f"  diff: {yisim_signed - actual_signed:+d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
