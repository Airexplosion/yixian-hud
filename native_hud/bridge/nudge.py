# -*- coding: utf-8 -*-
"""Live HUD position nudger.

Attaches a throwaway glue session to the running game and calls Hud20.SetPos to
move a label, WITHOUT restarting the game or the HUD launcher. Positions are
anchored offsets (x right+, y down−) in the same units the HUD uses.

Usage:  python native_hud/bridge/nudge.py opp 70 -196 [total 0 -132] [warn 0 -172]
        (triples of: which x y, where which ∈ total|warn|opp)
"""
import sys
import os
from pathlib import Path

import frida

REPO = Path(__file__).resolve().parents[2]
GLUE = str(Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build")) / "bot_glue3.agent.js")
HUD_T = os.environ.get("YX_HUD_T", "YiXianBot.Hud31")
PROCESS = os.environ.get("YX_PROC", "YiXianPai.exe")


def main():
    a = sys.argv[1:]
    if len(a) < 3 or len(a) % 3 != 0:
        print("usage: nudge.py which x y [which x y ...]   (which: total|warn|opp)")
        return
    sess = frida.attach(PROCESS)
    sc = sess.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    sc.load()
    ex = sc.exports_sync
    for i in range(0, len(a), 3):
        which, x, y = a[i], a[i + 1], a[i + 2]
        r = ex.call_str(HUD_T, "SetPos", "%s,%s,%s" % (which, x, y))
        print("%s %s,%s -> %s" % (which, x, y, r), flush=True)
    sess.detach()


if __name__ == "__main__":
    main()
