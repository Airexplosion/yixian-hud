# -*- coding: utf-8 -*-
"""Validate the client-side battle skip: invoke the live BattleReplayPanel's
private OnSkipAnimationButtonClick (cancels the animation → shows result → back
to placement) via bot_glue3.callPrivate.

Run this WHILE a battle animation is playing. If it skips to the result, the
mechanism is validated and we wire it to an HUD button.

Usage:  python native_hud/bridge/skip.py   (game must be running)
"""
import os
import time
from pathlib import Path

import frida

REPO = Path(__file__).resolve().parents[2]
GLUE = str(Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build")) / "bot_glue3.agent.js")
PROC = os.environ.get("YX_PROC", "YiXianPai.exe")
TYPE = os.environ.get("YX_SKIP_TYPE", "BattleReplayPanel")
METHOD = os.environ.get("YX_SKIP_METHOD", "OnSkipAnimationButtonClick")


def main():
    sess = frida.attach(PROC)
    sc = sess.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    sc.load()
    ex = sc.exports_sync
    r = ex.call_private(TYPE, METHOD)
    print("callPrivate %s.%s -> %s" % (TYPE, METHOD, r), flush=True)
    time.sleep(1)
    try:
        sc.unload()
        sess.detach()
    except Exception:
        pass


if __name__ == "__main__":
    main()
