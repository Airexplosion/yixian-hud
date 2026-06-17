# -*- coding: utf-8 -*-
"""Generic hot-update static-method caller — the "invoke layer" for validating
and exercising exposed game APIs from outside.

Calls a global/static ILRuntime hot-update method via bot_glue3's callS RPC.
Retries until the ILRuntime AppDomain is ready (the target is NOT invoked until
then), then calls exactly once and prints {ok, result, err}.

Usage:
    python native_hud/bridge/apicall.py AccountUtil AutoSelectBestRouteAsync 3
    YX_ATTACH=1 python native_hud/bridge/apicall.py <Type> <Method> [int...]
"""
import sys
import os
import time
from pathlib import Path

import frida

REPO = Path(__file__).resolve().parents[2]
GLUE = str(Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build")) / "bot_glue3.agent.js")
GAME = os.environ.get("YX_GAME_EXE", r"F:\SteamLibrary\steamapps\common\YiXianPai\YiXianPai.exe")
PROC = os.environ.get("YX_PROC", "YiXianPai.exe")


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print("usage: apicall.py <Type> <Method> [int args...]  (YX_ATTACH=1 to attach)")
        return
    typ, method = a[0], a[1]
    ints = [int(x) for x in a[2:]]
    attach = os.environ.get("YX_ATTACH", "0") != "0"
    pid = None
    if attach:
        sess = frida.attach(PROC)
    else:
        if not os.path.exists(GAME):
            print("[err] game exe not found:", GAME)
            return
        pid = frida.spawn([GAME])
        sess = frida.attach(pid)
    sc = sess.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    sc.load()
    ex = sc.exports_sync
    if not attach:
        frida.resume(pid)
        print("spawned; 等游戏到登录/菜单(AppDomain 就绪)…", flush=True)

    res = None
    for _ in range(60):
        try:
            r = ex.call_s(typ, method, ints)
            # getAD() throws before invoking the target when the AppDomain isn't
            # ready yet — so a not-ready error means the target was NOT called.
            err = "" if not r else str(r.get("err", ""))
            if r and (r.get("ok") or ("not found" in err) or ("Invoke" in err)):
                res = r
                break
        except Exception as e:
            res = {"ok": False, "err": str(e)}
        time.sleep(2)
    print("CALL %s.%s(%s) -> %s" % (typ, method, ints, res), flush=True)
    time.sleep(3)   # let an async side-effect (e.g. route ping) run
    try:
        sc.unload()
        sess.detach()
    except Exception:
        pass
    if pid is not None:
        try:
            frida.kill(pid)
        except Exception:
            pass


if __name__ == "__main__":
    main()
