# -*- coding: utf-8 -*-
"""Headless same-domain FEED PROBE (no C# HUD / no DLLs needed).

Purpose: diagnose the "remaining 算错" bug by capturing the EXACT same-domain
feed and replaying it through the proven counter, so its output can be diffed
against the proxy ground-truth (battle_log/*/deck_tracker.jsonl).

Attaches the capture agent (inbound DecodeFromBase64 + outbound
EncodeToProtobufData). For every {dir, type, base64} event it:
  1) appends the RAW event to native_hud/_build/feed_<ts>.jsonl  (replayable)
  2) feeds it through addon.process_msgpack — the SAME dispatcher the proxy
     counter uses — so shadow_state + Counter advance identically.
A consumer thread logs Counter.remaining for the watched cards on every push.

RUN FROM THE GAME MAIN MENU so the counter sees the opening deal (baseline);
attaching mid-round loses the baseline and every count drifts. Ctrl-C to stop.
The feed_<ts>.jsonl is the artefact to replay offline."""
import sys
import os
import json
import time
import threading
from pathlib import Path

import frida

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "proxy", REPO / "autoplay" / "inject"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import addon                                          # noqa: E402  proxy dispatcher
import state_queue as _sq                             # noqa: E402
from proxy_view import Counter, OpponentTracker       # noqa: E402

BUILD = Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build"))
CAPTURE = os.environ.get("YX_AGENT_CAPTURE", str(BUILD / "capture.agent.js"))
PROCESS = os.environ.get("YX_PROC", "YiXianPai.exe")
WATCH = ("震雷", "护身灵气", "灵气灌注")

_ts = time.strftime("%Y%m%d_%H%M%S")
_RAW_PATH = BUILD / ("feed_%s.jsonl" % _ts)
_raw_f = open(_RAW_PATH, "w", encoding="utf-8")
_raw_lock = threading.Lock()
_counts = {"in": 0, "out": 0, "err": 0}
_seen_types = set()


def _dump(ev):
    with _raw_lock:
        _raw_f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def on_message(msg, _data):
    if msg.get("type") != "send":
        if msg.get("type") == "error":
            print("[agent error]", msg.get("description"), flush=True)
        return
    p = msg.get("payload") or {}
    t, b, d = p.get("t"), p.get("b"), p.get("dir", "in")
    if not t:
        return
    _counts["in" if d == "in" else "out"] += 1
    _dump({"dir": d, "t": t, "b": b})
    key = (d, t)
    if key not in _seen_types:
        _seen_types.add(key)
        print("[type] %-3s %s" % (d, t), flush=True)
    # statereader wraps as the Colyseus msgpack shape the dispatcher expects.
    mp = ["data", {"type": t, "data": b}]
    try:
        addon.process_msgpack(mp, from_client=(d == "out"))
    except Exception as e:
        _counts["err"] += 1
        if _counts["err"] <= 5:
            print("[dispatch err] %s: %s" % (t, e), flush=True)


def consumer():
    counter = Counter()
    opp = OpponentTracker()
    last_round = [0]
    while True:
        try:
            state = _sq.state_queue.get(timeout=0.5)
        except Exception:
            continue
        rn = int(getattr(state, "round_num", 0) or 0)
        if _sq.new_game_event.is_set() or (last_round[0] > 1 and rn <= 1):
            try:
                _sq.new_game_event.clear()
            except Exception:
                pass
            counter.reset()
            opp.reset()
            print("[reset] 新局 counter重置 (round %d->%d)" % (last_round[0], rn), flush=True)
        last_round[0] = rn
        try:
            counter.observe(state)
            opp.observe(state)
            rem = counter.remaining()
            watched = {k: v for k, v in rem.items() if any(x in k for x in WATCH)}
            print("[r%s] in=%d out=%d err=%d remaining=%d watched=%s"
                  % (rn, _counts["in"], _counts["out"], _counts["err"], len(rem), watched),
                  flush=True)
        except Exception as e:
            print("[consumer] %s" % e, flush=True)


def main():
    spawn = os.environ.get("YX_SPAWN", "0") != "0"
    pid = None
    if spawn:
        exe = os.environ.get("YX_GAME_EXE", "")
        if not exe or not os.path.exists(exe):
            print("[spawn] 需要 YX_GAME_EXE 指向 YiXianPai.exe;当前=%r" % exe, flush=True)
            return
        print("spawn %s … (raw feed -> %s)" % (exe, _RAW_PATH), flush=True)
        pid = frida.spawn([exe])                 # launch suspended → hook before any WS frame
        session = frida.attach(pid)
    else:
        print("attach %s … (raw feed -> %s)" % (PROCESS, _RAW_PATH), flush=True)
        session = frida.attach(PROCESS)
    script = session.create_script(open(CAPTURE, encoding="utf-8").read(), runtime="qjs")
    script.on("message", on_message)
    script.load()
    if spawn:
        frida.resume(pid)
        print(">>> spawned + capture 已挂(先于第1帧). 游戏自己起来, 从开局抓全. Ctrl-C 停 <<<", flush=True)
    else:
        print(">>> capture 已挂. 现在从主菜单开一局,我盯 watched 计数. Ctrl-C 停 <<<", flush=True)
    threading.Thread(target=consumer, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            script.unload()
            session.detach()
        except Exception:
            pass
        _raw_f.close()
        print("[done] raw feed saved: %s" % _RAW_PATH, flush=True)


if __name__ == "__main__":
    main()
