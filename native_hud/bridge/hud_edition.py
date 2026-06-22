# -*- coding: utf-8 -*-
"""版本变体标记(由 build_hud.py 按 --lite 写入)。

LITE=True 的精简版:只保留 记牌器 + 跳过战斗,完全不带 yisim/伤害(不起 total_loop、不打包
node、GUI 隐藏伤害项)。默认 False = 完整版。
(spawn/attach 已在运行时自动判定 —— 游戏在跑就 attach、没跑就 spawn,不再分变体。)
"""
LITE = False
