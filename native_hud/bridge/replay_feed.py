# -*- coding: utf-8 -*-
"""Offline replay of a captured same-domain feed (native_hud/_build/feed_*.jsonl).

Feeds the recorded {dir,type,base64} stream back through addon.process_msgpack —
the SAME dispatcher the live bridge uses — and prints the Counter.remaining()
timeline for the watched cards per round, plus the final full remaining. Lets us
verify (and diff vs proxy ground-truth) without the live game.

Usage:  python native_hud/bridge/replay_feed.py [path/to/feed.jsonl] [card...]
        (no path → newest feed_*.jsonl in native_hud/_build)
"""
import sys
import os
import json
import glob
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "proxy", REPO / "autoplay" / "inject"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import addon                                    # noqa: E402
import state_queue as _sq                       # noqa: E402
from proxy_view import Counter, OpponentTracker  # noqa: E402

BUILD = REPO / "native_hud" / "_build"


def _newest_feed():
    feeds = sorted(glob.glob(str(BUILD / "feed_*.jsonl")), key=os.path.getmtime)
    return feeds[-1] if feeds else None


def main():
    args = sys.argv[1:]
    path = None
    watch = []
    for a in args:
        if a.endswith(".jsonl"):
            path = a
        else:
            watch.append(a)
    if not watch:
        watch = ["护身灵气", "灵气灌注", "震雷"]
    path = path or _newest_feed()
    if not path or not os.path.exists(path):
        print("no feed file found in", BUILD)
        return
    print("replay:", path, "| watch:", watch)

    counter = Counter()
    opp = OpponentTracker()
    last_round = [0]
    n = 0
    last_watched = None
    final_rem = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            t, b, d = ev.get("t"), ev.get("b"), ev.get("dir", "in")
            if not t:
                continue
            n += 1
            mp = ["data", {"type": t, "data": b}]
            try:
                addon.process_msgpack(mp, from_client=(d == "out"))
            except Exception:
                pass
            # drain whatever states this message pushed
            while True:
                try:
                    state = _sq.state_queue.get_nowait()
                except Exception:
                    break
                rn = int(getattr(state, "round_num", 0) or 0)
                if _sq.new_game_event.is_set() or (last_round[0] > 1 and rn <= 1):
                    try:
                        _sq.new_game_event.clear()
                    except Exception:
                        pass
                    counter.reset()
                    opp.reset()
                    print("  [reset] 新局 (round %d->%d)" % (last_round[0], rn))
                last_round[0] = rn
                counter.observe(state)
                opp.observe(state)
                rem = counter.remaining()
                final_rem = rem
                watched = {k: v for k, v in rem.items()
                           if any(x in k for x in watch)}
                if watched != last_watched:
                    print("  [r%s] remaining=%d  watched=%s" % (rn, len(rem), watched))
                    last_watched = watched

    print("\n=== events replayed: %d ===" % n)
    print("=== final remaining (%d cards) ===" % len(final_rem))
    for k in sorted(final_rem):
        print("  %s : %s" % (k, final_rem[k]))


if __name__ == "__main__":
    main()
