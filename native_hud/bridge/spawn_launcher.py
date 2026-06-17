# -*- coding: utf-8 -*-
"""Spawn-inject launcher.

Launches YiXianPai.exe THROUGH frida so the protocol hook is installed BEFORE
the game opens its WebSocket — capturing every frame from the opening deal,
exactly like the network proxy. This is what makes the counter correct from
round 1: no missing baseline → no "剩?" on cards dealt at the start.

Usage:
    python native_hud/bridge/spawn_launcher.py
Override the game path with env YX_GAME_EXE if your Steam install differs.
The game must NOT already be running (spawn launches a fresh instance).
"""
import os

# Default to the common Steam install location; override via env if different.
os.environ.setdefault(
    "YX_GAME_EXE",
    r"F:\SteamLibrary\steamapps\common\YiXianPai\YiXianPai.exe",
)
os.environ["YX_SPAWN"] = "1"

import feed_probe  # noqa: E402  reuses the capture hook + dispatcher + consumer

if __name__ == "__main__":
    feed_probe.main()
