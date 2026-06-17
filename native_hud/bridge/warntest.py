# -*- coding: utf-8 -*-
"""Force the danger warning on for a few seconds so its position can be judged
(normally it only shows when the opponent actually has a danger card). Repeatedly
pushes SetWarning to outvote the live consumer's clears.

Usage:  python native_hud/bridge/warntest.py ["message"] [seconds]
"""
import sys
import os
import time
from pathlib import Path

import frida

REPO = Path(__file__).resolve().parents[2]
GLUE = str(Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build")) / "bot_glue3.agent.js")
HUD_T = os.environ.get("YX_HUD_T", "YiXianBot.Hud31")
PROCESS = os.environ.get("YX_PROC", "YiXianPai.exe")

MSG = sys.argv[1] if len(sys.argv) > 1 else "⚠ 对手危险牌: 天音困仙曲 噬仙古藤"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0


def main():
    sess = frida.attach(PROCESS)
    sc = sess.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    sc.load()
    ex = sc.exports_sync
    n = int(SECS / 0.4)
    for _ in range(n):
        try:
            ex.call_str(HUD_T, "SetWarning", MSG)
        except Exception:
            pass
        time.sleep(0.4)
    try:
        ex.call_str(HUD_T, "SetWarning", "")
    except Exception:
        pass
    sess.detach()
    print("done", flush=True)


if __name__ == "__main__":
    main()
