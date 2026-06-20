# -*- coding: utf-8 -*-
"""Full native-HUD launcher (spawn-inject).

Launches YiXianPai THROUGH frida (hook before frame 1 → counts correct from
round 1), then on ONE process runs two scripts:
  · capture.agent.js   — inbound/outbound protobuf → addon.process_msgpack →
                         Counter  (the 记牌器, reused proxy logic)
  · bot_glue3.agent.js — loads YiXianHud19.dll into the game's ILRuntime
                         AppDomain and exposes Show / SetRemaining
A consumer thread pushes Counter.remaining() (name-expanded for exact in-game
CardConfig.name match) to Hud19.SetRemaining, which draws 剩X on every card.

Run from a CLOSED game (spawn launches a fresh instance). Ctrl-C to stop.
"""
import sys
import os
import json
import time
import threading
import subprocess
from pathlib import Path

# PyInstaller --windowed 打包后没有控制台窗口,sys.stdout/stderr 会是 None → 任何 print
# 都会崩(NoneType.write)。把它们重定向到 exe 旁的 YiXianHUD.log(无黑框 + 留日志便于排错);
# 开发态(非打包)保持原控制台不动。
if sys.stdout is None or sys.stderr is None:
    try:
        _logdir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        _logf = open(_logdir / "YiXianHUD.log", "a", encoding="utf-8", errors="replace")
        if sys.stdout is None:
            sys.stdout = _logf
        if sys.stderr is None:
            sys.stderr = _logf
    except Exception:
        class _NullIO:
            def write(self, *a):
                return 0
            def flush(self):
                pass
        if sys.stdout is None:
            sys.stdout = _NullIO()
        if sys.stderr is None:
            sys.stderr = _NullIO()

# Windows 控制台/后台重定向的 stdout 默认 GBK,卡名里的 •(•,如「崩拳•弹」)GBK
# 编码不了 → print 抛 UnicodeEncodeError。该异常在 consumer 线程打印 "[r..] keys=[...]"
# 时触发,位置在 SetRemaining 推送之前 → 整轮推送被打断,s_remaining 永远为空 → 所有卡
# 显示「剩?」(记牌器表面"坏掉")。强制 stdout/stderr 用 UTF-8 且对无法编码字符替换。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import frida

if getattr(sys, "frozen", False):
    REPO = Path(sys._MEIPASS)            # PyInstaller bundle root (data laid out to mirror repo)
else:
    REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "proxy", REPO / "autoplay" / "inject",
           REPO / "native_hud" / "bridge"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

def _load_name_to_id():
    try:
        # key 必须和 deck_pool 输出的 name 同口径:deck_pool 用 _canonical(_normalize_sep(name)),
        # 而 card_id_map 里分隔符是 •(bullet)。不归一化 → "云剑•崩雪" vs "云剑·崩雪" 对不上,
        # 云剑系列(及所有带分隔符的牌)全被 pool_payload 丢弃。优先复用记牌器的同一套归一函数。
        try:
            from proxy_view import _canonical, _normalize_sep
            def _norm(s):
                return _canonical(_normalize_sep(s))
        except Exception:
            _sep = str.maketrans({"•": "·"})
            def _norm(s):
                return s.translate(_sep)
        m = json.loads((REPO / "proxy" / "card_id_map.json").read_text(encoding="utf-8"))
        out = {}
        for k, v in m.items():
            cid = int(k)
            # 归一到一级牌 id(等价游戏 GetCardBaseId):同名牌有 1/2/3 级三个 id
            # (基础 + 等级*10000),卡池按一级卡面展示,故全部映射到一级 base。
            base = (cid % 10000) + (cid // 100000) * 100000
            out[_norm(v)] = base
        return out
    except Exception:
        return {}

NAME_TO_ID = _load_name_to_id()

import addon                                                  # noqa: E402
import state_queue as _sq                                     # noqa: E402
from proxy_view import (Counter, OpponentTracker,             # noqa: E402
                        remaining_with_aliases, build_view_model)

BUILD = Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build"))
CAPTURE = str(BUILD / "capture.agent.js")
GLUE = str(BUILD / "bot_glue3.agent.js")
HUD_DLL = str(BUILD / "YiXianHud32.dll")
NODE_MARGINAL = str(REPO / "native_hud" / "bridge" / "yisim_marginal.js")
GAME_NAME = "YiXianPai.exe"
HUD_T = "YiXianBot.Hud32"
# Earlier HUD iterations to hide on (re)load so only the current one draws.
OLD_HUDS = ["Hud31", "Hud30", "Hud29", "Hud28", "Hud27", "Hud26", "Hud25", "Hud24", "Hud23", "Hud22", "Hud21", "Hud20", "Hud19", "Hud18", "Hud17", "Hud16"]

# Live settings (toggled from the GUI). Loops read these each iteration.
SETTINGS = {
    "remaining": True,   # 记牌器 剩X
    "damage": True,      # T1..T8 造伤
    "opponent": True,    # 对手 命/修
    "warning": True,     # 危险牌警告
    "skip": True,        # 跳过战斗按钮
    "matchup": True,     # 伤害模式: True=matchup(vs对手), False=solo
}
WATCH = ("护身灵气", "灵气灌注", "震雷")
_SEP_NORM = str.maketrans({"•": "·"})           # runtime names mix • and ·
# Danger cards: if the opponent's board has any of these, flash a warning.
DANGER_CARDS = {
    "缚仙古藤", "噬仙古藤", "天音困仙曲", "幽绪乱心曲", "奇门锁妖塔",
    "猎枭古弓", "水灵·海龙啸", "影枭兔", "幽冥虚魂犬", "噬灵虚兽",
}


def _card_name(c):
    return (c.get("name") if isinstance(c, dict) else c) or ""


# ── Game-exe resolution (no hardcoded path) ───────────────────────────────────
def _exe_dir():
    """Folder the launcher/exe lives in (where the game and config sit)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _config_path():
    return _exe_dir() / "YiXianHUD_config.json"


def _load_cfg():
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cfg(cfg):
    try:
        _config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


DEFAULT_POS = {"total": (0, -182), "warn": (0, -222), "opp": (70, -240), "skip": (-80, -380)}


# ── 可配置热键 ────────────────────────────────────────────────────────────────
DEFAULT_HOTKEYS = {"swap": {"vk": 0x44, "ctrl": False},   # D 换牌
                   "pool": {"vk": 0x09, "ctrl": False}}   # Tab 卡池
_VK_NAMES = {0x01: "鼠标左键", 0x02: "鼠标右键", 0x04: "鼠标中键", 0x05: "鼠标侧键1", 0x06: "鼠标侧键2",
             0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Space",
             0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓",
             0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8",
             0xBC: ",", 0xBE: ".", 0xBF: "/", 0xBA: ";"}


def _load_hotkeys():
    hk = (_load_cfg().get("hotkeys") or {})
    out = {}
    for act in ("swap", "pool"):
        b = hk.get(act) or {}
        d = DEFAULT_HOTKEYS[act]
        out[act] = {"vk": int(b.get("vk", d["vk"])), "ctrl": bool(b.get("ctrl", d["ctrl"]))}
    return out


HOTKEYS = _load_hotkeys()


def _vk_name(b):
    vk = int(b.get("vk", 0))
    n = _VK_NAMES.get(vk)
    if not n:
        n = chr(vk) if 0x30 <= vk <= 0x5A else "VK%02X" % vk   # 0-9 / A-Z
    return ("Ctrl+" if b.get("ctrl") else "") + n


def _hotkey_label(act):
    return _vk_name(HOTKEYS.get(act) or DEFAULT_HOTKEYS[act])


def _set_hotkey(act, vk, ctrl):
    HOTKEYS[act] = {"vk": int(vk), "ctrl": bool(ctrl)}
    cfg = _load_cfg()
    cfg.setdefault("hotkeys", {})[act] = {"vk": int(vk), "ctrl": bool(ctrl)}
    _save_cfg(cfg)


def _capture_hotkey(act, on_done):
    """后台轮询:等点按钮的鼠标键释放后,捕获下一个按下的键/鼠标键(含侧键)+当时 Ctrl 状态,
    存为 act 的绑定;捕获到或 ~10s 超时后回调 on_done(让 GUI 刷新显示)。"""
    import ctypes
    user32 = ctypes.windll.user32
    skip = (0x10, 0x11, 0x12)   # shift/ctrl/alt 修饰键本身不作主键

    def run():
        time.sleep(0.35)
        for _ in range(500):
            ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
            for vk in range(0x01, 0xFF):
                if vk in skip:
                    continue
                if (user32.GetAsyncKeyState(vk) & 0x8000) != 0:
                    _set_hotkey(act, vk, ctrl)
                    try:
                        on_done()
                    except Exception:
                        pass
                    return
            time.sleep(0.02)
        try:
            on_done()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def _positions():
    cfg = _load_cfg()
    p = dict(DEFAULT_POS)
    for k, v in (cfg.get("positions") or {}).items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            p[k] = (int(v[0]), int(v[1]))
    return p


def _pos_get(key):
    return _positions().get(key, (0, 0))


def _make_on_pos():
    def on_pos(key, x, y):
        ex = _hud_ex.get("ex")
        if ex is not None:
            try:
                ex.call_str(HUD_T, "SetPos", "%s,%d,%d" % (key, x, y))
            except Exception:
                pass
        cfg = _load_cfg()
        cfg.setdefault("positions", {})[key] = [x, y]
        _save_cfg(cfg)
    return on_pos


def _ask_game_exe():
    """Pop a file picker so the user selects YiXianPai.exe."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        p = filedialog.askopenfilename(
            title="找不到游戏 — 请选择 YiXianPai.exe",
            filetypes=[("弈仙牌", "YiXianPai.exe"), ("可执行文件", "*.exe")])
        r.destroy()
        return p or None
    except Exception:
        return None


def resolve_game_exe():
    """Find the game exe: env override → same folder as us → remembered choice →
    ask the user (and remember it). Returns a path or None if the user cancels."""
    p = os.environ.get("YX_GAME_EXE")
    if p and os.path.exists(p):
        return p
    same = _exe_dir() / GAME_NAME
    if same.exists():
        return str(same)
    cfg = _load_cfg()
    saved = cfg.get("game_exe")
    if saved and os.path.exists(saved):
        return saved
    chosen = _ask_game_exe()
    if chosen and os.path.exists(chosen):
        cfg["game_exe"] = chosen
        _save_cfg(cfg)
        return chosen
    return None


_NODE = {"exe": None}


def node_exe():
    """node for the yisim sim: bundled node.exe (frozen) first so the published
    exe works WITHOUT node installed; else fall back to a system node."""
    if _NODE["exe"]:
        return _NODE["exe"]
    import shutil
    cand = None
    if getattr(sys, "frozen", False):
        b = Path(sys._MEIPASS) / "node.exe"
        if b.exists():
            cand = str(b)
    if not cand:
        cand = shutil.which("node")
    if not cand:
        for p in (r"C:\Program Files\nodejs\node.exe",
                  os.path.expandvars(r"%ProgramFiles%\nodejs\node.exe"),
                  os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe")):
            if p and os.path.exists(p):
                cand = p
                break
    _NODE["exe"] = cand or "node"
    return _NODE["exe"]


_counts = {"in": 0, "out": 0}
_hud_ex = {"ex": None}
_hud_ready = threading.Event()
_latest = {"vm": None}


def on_feed(msg, _data):
    if msg.get("type") != "send":
        return
    p = msg.get("payload") or {}
    t, b, d = p.get("t"), p.get("b"), p.get("dir", "in")
    if not t:
        return
    _counts["in" if d == "in" else "out"] += 1
    try:
        addon.process_msgpack(["data", {"type": t, "data": b}], from_client=(d == "out"))
    except Exception:
        pass


def hud_loader():
    """Load the HUD DLL once the ILRuntime AppDomain is ready, then Show.
    Load and Show are retried separately: LoadAssembly only once (re-loading the
    same assembly errors), but Show is retried until it actually subscribes
    (early invokes can hit a transient 'system error' before the scene is up)."""
    ex = _hud_ex["ex"]

    def hide_olds():
        for old in OLD_HUDS:
            try:
                ex.call_s("YiXianBot." + old, "Hide", [])
            except Exception:
                pass

    for _ in range(80):
        # 1) Already loaded (re-attach to a game we set up before)? Show works
        #    immediately — DON'T re-load the assembly: re-loading stacks a second
        #    tick → duplicate labels. Reuse it and we're done.
        try:
            s = ex.call_s(HUD_T, "Show", [])
            if s and s.get("ok") and str(s.get("result", "")).startswith("ok"):
                print("[hud] reuse (already loaded) ->", s, flush=True)
                hide_olds()
                _hud_ready.set()
                for _k, (_x, _y) in _positions().items():
                    try:
                        ex.call_str(HUD_T, "SetPos", "%s,%d,%d" % (_k, _x, _y))
                    except Exception:
                        pass
                return
        except Exception:
            pass
        # 2) Not loaded yet → load the assembly, hide older iterations, then Show.
        try:
            with open(HUD_DLL, "rb") as f:
                r = ex.load_bot(f.read())
            if r and r.get("ok"):
                print("[hud] assembly loaded", flush=True)
                hide_olds()
                try:
                    s = ex.call_s(HUD_T, "Show", [])
                    if s and s.get("ok") and str(s.get("result", "")).startswith("ok"):
                        print("[hud] Show ->", s, flush=True)
                        _hud_ready.set()
                        for _k, (_x, _y) in _positions().items():
                            try:
                                ex.call_str(HUD_T, "SetPos", "%s,%d,%d" % (_k, _x, _y))
                            except Exception:
                                pass
                        return
                except Exception:
                    pass
        except Exception as e:
            print("[hud] load err", e, flush=True)
        time.sleep(3)


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
            print("[reset] 新局 (round %d->%d)" % (last_round[0], rn), flush=True)
        last_round[0] = rn
        try:
            counter.observe(state)
            opp.observe(state)
            vm = build_view_model(state, counter=counter,
                                  last_battle=addon.last_battle, opp_tracker=opp)
            _latest["vm"] = vm
            rem = (vm.get("counter") or {}).get("remaining") or {}
            print("[r%s] in=%d out=%d remaining=%d keys=%s"
                  % (rn, _counts["in"], _counts["out"], len(rem),
                     list(rem.keys())[:10]), flush=True)
            ex = _hud_ex["ex"]
            if ex is not None and _hud_ready.is_set():
                ex.call_str(HUD_T, "SetShowLeft", "1" if SETTINGS["remaining"] else "0")
                ex.call_str(HUD_T, "SetShowSkip", "1" if SETTINGS["skip"] else "0")
                if rem:
                    payload = remaining_with_aliases(rem)
                    ex.call_str(HUD_T, "SetRemaining",
                                "|".join("%s:%s" % (k, v) for k, v in payload.items()))
                # #1 卡池补全:本宗门 + 当前阶段的全部常规牌(含没抽到的满数牌)。
                # 宗门 id 从 C# GetPlayerSect 取(记牌器没存主宗门),phase 用玩家境界。
                from pool_payload import pool_payload
                try:
                    _r = ex.call_str(HUD_T, "GetPlayerSect", "")
                    _si = (_r.get("result", "") if isinstance(_r, dict) else "") or ""
                    _ps = _si.split(",")
                    _psect, _pphase = int(_ps[0]), int(_ps[1])
                    _full = counter.deck_pool(_psect, _pphase)
                    print("[pool] sect=%d phase=%d 常规牌=%d" % (_psect, _pphase, len(_full)), flush=True)
                    ex.call_str(HUD_T, "SetPool", pool_payload(_full, NAME_TO_ID))
                except Exception as _pe:
                    print("[pool] %s -> 退回见过的牌" % _pe, flush=True)
                    ex.call_str(HUD_T, "SetPool", pool_payload(rem, NAME_TO_ID))
                # Opponent HP cap + 修为. The tracked values are LAST round's;
                # user's rule: this round ≈ last HP +2, last 修为 +5.
                # NB: keep `opp` = the OpponentTracker (do NOT rebind it here, or
                # next round's opp.observe() blows up — use a separate name).
                opp_vm = vm.get("opponent")
                if opp_vm and SETTINGS["opponent"]:
                    ohp = int(opp_vm.get("hp") or 0) + 2
                    oxw = int(opp_vm.get("xiuwei") or 0) + 5
                    ex.call_str(HUD_T, "SetOpponent", "敌 命%d 修%d (预估)" % (ohp, oxw))
                else:
                    ex.call_str(HUD_T, "SetOpponent", "")
                names = {_card_name(c).translate(_SEP_NORM)
                         for c in ((opp_vm or {}).get("board") or []) if c}
                danger = sorted(names & DANGER_CARDS)
                if danger and SETTINGS["warning"]:
                    ex.call_str(HUD_T, "SetWarning", "⚠ 对手危险牌: " + " ".join(danger))
                else:
                    ex.call_str(HUD_T, "SetWarning", "")
        except Exception as e:
            print("[consumer] %s" % e, flush=True)


def _fmt_damage_table(my_cum, opp_cum, tag):
    """造伤显示:去掉 T1..T8,做成表格。solo 一行(己方),matchup 两行(第一行己方造伤,
    第二行对手造伤),战斗结论 tag(必胜/可赢/会输 @Tn)单独一行。

    游戏字体是比例字体且数字非等宽,这套 TMP 又不认 <mspace>/<pos> 富文本布局标签,纯文本
    无法逐列对齐 → C# 侧(Hud32.DrawTotal)改用"每格独立定位的网格"渲染。这里只负责把数据
    排成 C# 约定的格式:行用 '\\n' 分隔,单元格用 '\\t' 分隔;每行首格是 我/敌 标签,后面每
    个回合一格,' | ' 作为列前缀(空缺格留空,不出多余竖线)。"""
    grid = [("我", my_cum)]
    if opp_cum:
        grid.append(("敌", opp_cum))
    if not any(c for _, c in grid):
        return ""
    ncol = max(len(c) for _, c in grid)
    lines = []
    for label, cum in grid:
        cells = [label]
        for i in range(ncol):
            v = str(cum[i]) if i < len(cum) else ""
            cells.append("" if v == "" else (v if i == 0 else "| " + v))
        lines.append("\t".join(cells))
    if tag:
        lines.append(tag.strip())   # 战斗结论单独一行(网格里是单格行)
    return "\n".join(lines)


def total_loop():
    """Whole-board yisim damage (the SAME number the web tool shows: 8-turn
    cumulative), fed the same inputs the web does (board levels + 仙命/天衍
    talents + deckSlots). Pushed to Hud19.SetTotal (screen-anchored)."""
    while True:
        try:
            vm = _latest["vm"]
            me = (vm or {}).get("me") or {}
            board = me.get("board") or []
            ex = _hud_ex["ex"]
            if ex is not None and _hud_ready.is_set() and not SETTINGS["damage"]:
                ex.call_str(HUD_T, "SetTotal", "")   # damage display off
                time.sleep(1.0)
                continue
            if ex is not None and _hud_ready.is_set() and any(c for c in board) \
                    and not (me.get("lingyuUnresolved")):
                obj = {
                    "totalOnly": True,
                    "board": board,
                    "talents": me.get("fates") or [],
                    "deckSlots": me.get("unlocked") or len(board) or 8,
                    # 灵植成长层数(归元草加血等)→ yisim player.*_stacks,solo/matchup 都带。
                    "plantStacks": me.get("plantStacks") or {},
                    # 我方真实状态(血量/体魄/修为)→ 剩命显示要准必须传(否则 yisim 用默认 110)。
                    "playerState": {
                        "hp": me.get("hp"), "maxHp": me.get("hp"),
                        "physique": me.get("tipo") or 0,
                        "maxPhysique": me.get("tipo") or 0,
                        "cultivation": me.get("xiuwei") or 0,
                    },
                }
                # MATCHUP: if enabled AND we know the opponent's (last-seen) board,
                # sim real combat against it so the damage reflects THIS opponent.
                opp_vm = (vm or {}).get("opponent")
                oboard = (opp_vm or {}).get("board") or []
                if SETTINGS["matchup"] and opp_vm and any(c for c in oboard):
                    obj["opponent"] = {
                        "board": oboard,
                        "deckSlots": opp_vm.get("unlocked") or len(oboard) or 8,
                        "talents": opp_vm.get("fates") or [],
                        "playerState": {
                            "hp": opp_vm.get("hp"), "maxHp": opp_vm.get("hp"),
                            "physique": opp_vm.get("tipo") or 0,
                            "maxPhysique": opp_vm.get("tipo") or 0,
                            "cultivation": opp_vm.get("xiuwei") or 0,
                        },
                    }
                payload = json.dumps(obj, ensure_ascii=False)
                # 入参快照(控制台):核对喂给 yisim 的 talents/board/playerState 是否传对。
                try:
                    _b = lambda bd: [("%s·%s" % (c["name"], c.get("level"))) if c else "_"
                                     for c in (bd or [])]
                    _t = lambda ts: [(t.get("name"), t.get("simulationKind"), t.get("runtimeKey"),
                                      ("x%s" % t["stackOverride"]) if t.get("stackOverride") is not None
                                      else "x?")
                                     for t in (ts or [])]
                    print("[total-in] myBoard=%s" % _b(board), flush=True)
                    print("[total-in] myFateNames=%s" % (me.get("fateNames") or []), flush=True)
                    print("[total-in] myTalents=%s" % _t(me.get("fates")), flush=True)
                    if obj.get("opponent"):
                        _o = obj["opponent"]
                        print("[total-in] oppBoard=%s" % _b(_o.get("board")), flush=True)
                        print("[total-in] oppTalents=%s" % _t(_o.get("talents")), flush=True)
                except Exception as _e:
                    print("[total-in] dump failed: %s" % _e, flush=True)
                p = subprocess.run([node_exe(), NODE_MARGINAL], input=payload.encode("utf-8"),
                                   capture_output=True, timeout=25,
                                   creationflags=(0x08000000 if sys.platform.startswith("win") else 0))
                res = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
                full = res.get("full")
                cum = res.get("cumulative") or []
                my_hp = res.get("myHpSeries") or []
                opp_hp = res.get("oppHpSeries") or []
                outcome = res.get("outcome")
                end_turn = res.get("endTurn")
                is_matchup = res.get("mode") == "matchup"
                print("[total] mode=%s full=%s outcome=%s@T%s myHp=%s oppHp=%s plant=%s"
                      % (res.get("mode"), full, outcome, end_turn, my_hp, opp_hp,
                         obj.get("plantStacks")), flush=True)
                # outcome tag (matchup only): 必胜/可赢/会输 @Tn
                tag = ""
                if outcome == "win":
                    tag = "  %s@T%s" % ("必胜" if res.get("deterministic") else "可赢", end_turn)
                elif outcome == "lose":
                    tag = "  会输@T%s" % end_turn
                # matchup → 两行剩余血量(我方剩命/对手剩命,含金梭兰等战斗开始效果);
                # solo(无对手)→ 一行造伤累计(无对手不谈剩命)。
                if is_matchup and (my_hp or opp_hp):
                    txt = _fmt_damage_table(my_hp, opp_hp or None, tag)
                    ex.call_str(HUD_T, "SetTotal", txt)
                elif cum:
                    txt = _fmt_damage_table(cum, None, tag)
                    ex.call_str(HUD_T, "SetTotal", txt)
                elif full is not None:
                    ex.call_str(HUD_T, "SetTotal", "造伤 %s%s" % (full, tag))
            time.sleep(1.5)
        except Exception as e:
            print("[total] %s" % e, flush=True)
            time.sleep(2)


PROCESS = os.environ.get("YX_PROC", "YiXianPai.exe")


def _hotkey_loop():
    import ctypes
    user32 = ctypes.windll.user32
    VK_CTRL = 0x11
    acts = (("pool", "TogglePool"), ("swap", "SwapHovered"))
    prev = {"pool": False, "swap": False}

    def _fg_is_game():
        try:
            hwnd = user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            return "YiXian" in buf.value or "弈仙" in buf.value
        except Exception:
            return False

    while True:
        try:
            ex = _hud_ex.get("ex")
            if ex is not None and _fg_is_game():
                ctrl = (user32.GetAsyncKeyState(VK_CTRL) & 0x8000) != 0
                for act, method in acts:
                    b = HOTKEYS.get(act) or DEFAULT_HOTKEYS[act]
                    vk = int(b.get("vk", 0)); need_ctrl = bool(b.get("ctrl", False))
                    # 需 Ctrl 的:vk 按下且 Ctrl 按下;不需 Ctrl 的:vk 按下且 Ctrl 没按(避免 Ctrl+vk 误触发)
                    raw = (user32.GetAsyncKeyState(vk) & 0x8000) != 0
                    down = raw and (ctrl if need_ctrl else not ctrl)
                    if down and not prev[act]:
                        try:
                            ex.call_str(HUD_T, method, "")
                        except Exception:
                            pass
                    prev[act] = down
        except Exception:
            pass
        time.sleep(0.01)   # 10ms 轮询,按键更跟手(原 30ms 偏迟钝)


EULA_TEXT = """YiXianHUD 最终用户许可协议(EULA)与使用须知

请在使用前仔细阅读。勾选并点击「同意并继续」即表示你已阅读、理解并接受以下全部条款;若不同意,请点「不同意,退出」。

一、性质说明
本程序是面向弈仙牌(YiXianPai)的第三方辅助工具,通过 frida 注入游戏进程,在游戏内叠加显示记牌/造伤等信息,并提供跳过战斗、换牌等操作。本程序与游戏官方(弈仙牌/DarkSun)无任何关联,未获其授权或认可。

二、注入与运行风险
1) 本程序会注入并修改游戏运行行为,可能导致游戏崩溃、卡死、对局/存档数据异常。
2) 因使用本程序造成的任何游戏内损失、数据丢失、账号异常,均由你自行承担。
3) 本程序按「现状」提供,作者不对其稳定性、正确性、适用性作任何担保。

三、封禁风险(重要)
1) 游戏官方几乎肯定不支持、不认可此类第三方程序,并保留包括封禁账号在内的一切处置权利。
2) 使用本程序可能导致你的游戏账号被警告、限制、封禁或永久封停。
3) 你理解并接受上述风险,自愿使用,后果自负。

四、保密与传播限制(重要)
1) 不得在任何游戏官方运营环境(官方群、论坛、客服、活动等)讨论、发布、截图、传播本程序的任何部分。
2) 不得在任何公开平台(直播、短视频、社交媒体等)直播或展示本程序的任何内容。
3) 本程序仅供个人学习研究与私下使用,请勿公开炫耀或传播使用过程。

五、免责
在适用法律允许的最大范围内,作者不对因使用或无法使用本程序而产生的任何直接、间接、附带或后果性损失承担任何责任。

六、接受
若你不同意上述任何条款,请退出并停止使用。继续使用即视为完全接受本协议。
"""


def _show_eula_gate():
    """首次启动弹 EULA / 注入风险 / 封禁 / 保密声明的同意框。已同意过(config 里
    eula_accepted)则直接放行。勾选并同意→记 config 返回 True;不同意/关窗→返回 False
    (调用方应退出)。GUI 起不来(headless/异常)时放行,避免误锁用户。"""
    try:
        if _load_cfg().get("eula_accepted"):
            return True
        import tkinter as tk
        from tkinter import scrolledtext
        st = {"ok": False}
        root = tk.Tk()
        root.title("YiXianHUD — 使用须知与最终用户许可协议(EULA)")
        root.geometry("600x560")
        root.attributes("-topmost", True)
        txt = scrolledtext.ScrolledText(root, wrap="word", font=("", 10))
        txt.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        txt.insert("1.0", EULA_TEXT)
        txt.config(state="disabled")
        bar = tk.Frame(root)
        bar.pack(fill="x", padx=12, pady=(0, 12))
        var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="我已阅读并同意上述全部条款", variable=var).pack(anchor="w")
        btns = tk.Frame(bar)
        btns.pack(fill="x", pady=(6, 0))

        def _agree():
            if not var.get():
                return
            st["ok"] = True
            cfg = _load_cfg()
            cfg["eula_accepted"] = True
            _save_cfg(cfg)
            root.destroy()

        def _decline():
            st["ok"] = False
            root.destroy()
        tk.Button(btns, text="不同意,退出", command=_decline).pack(side="right", padx=4)
        tk.Button(btns, text="同意并继续", command=_agree).pack(side="right", padx=4)
        root.protocol("WM_DELETE_WINDOW", _decline)
        root.mainloop()
        return st["ok"]
    except Exception:
        return True


def main():
    # 首次启动:弹 EULA / 注入风险 / 封禁 / 保密声明,必须勾选同意才继续(已同意过则跳过)。
    if not _show_eula_gate():
        print("[eula] 未同意条款,已退出。", flush=True)
        return
    # YX_ATTACH=1 → attach to the ALREADY-RUNNING game (no spawn / no restart).
    # Damage/opponent/warning are correct immediately; 剩X is only fully correct
    # if attached before the match started (it needs the opening deal). Default
    # is spawn (launch the game ourselves → everything correct from round 1).
    # Default: SPAWN (launch the game through frida → hook before frame 1 → counts
    # correct from round 1). Set YX_ATTACH=1 to attach to an already-running game.
    attach_mode = os.environ.get("YX_ATTACH", "0") != "0"
    pid = None
    if attach_mode:
        print("attach %s (运行中的游戏)…" % PROCESS, flush=True)
        try:
            feed_session = frida.attach(PROCESS)
            hud_session = frida.attach(PROCESS)
        except Exception as e:
            print("\n[!] 挂载失败:%s" % e, flush=True)
            print("[!] 请先从 Steam 打开弈仙牌(到登录/大厅),再运行本程序。", flush=True)
            try:
                input("\n按回车键退出…")
            except Exception:
                pass
            return
    else:
        game_exe = resolve_game_exe()
        if not game_exe:
            print("[err] 未选择游戏路径,退出。", flush=True)
            return
        print("spawn %s …" % game_exe, flush=True)
        pid = frida.spawn([game_exe])
        feed_session = frida.attach(pid)
        hud_session = frida.attach(pid)
    feed_script = feed_session.create_script(open(CAPTURE, encoding="utf-8").read(), runtime="qjs")
    feed_script.on("message", on_feed)
    feed_script.load()
    hud_script = hud_session.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    hud_script.load()
    _hud_ex["ex"] = hud_script.exports_sync
    if not attach_mode:
        frida.resume(pid)
    print(">>> capture+glue 已挂 (%s). 进对局后自动加载HUD. Ctrl-C 停 <<<"
          % ("attach" if attach_mode else "spawn"), flush=True)
    threading.Thread(target=hud_loader, daemon=True).start()
    threading.Thread(target=consumer, daemon=True).start()
    threading.Thread(target=total_loop, daemon=True).start()
    threading.Thread(target=_hotkey_loop, daemon=True).start()

    def _cleanup():
        try:
            feed_session.detach()
            hud_session.detach()
        except Exception:
            pass
        if pid is not None:
            try:
                frida.kill(pid)
            except Exception:
                pass

    def _status():
        hud = "已挂✓" if _hud_ready.is_set() else "等待对局…"
        return "HUD: %s\nin=%d out=%d (%s)" % (
            hud, _counts["in"], _counts["out"], "attach" if attach_mode else "spawn")


    # GUI settings window (default). YX_NOGUI=1 → headless console (Ctrl-C to stop).
    if os.environ.get("YX_NOGUI", "0") != "0":
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        _cleanup()
    else:
        try:
            from hud_gui import run_gui
            run_gui(SETTINGS, on_exit=_cleanup, status_get=_status,
                    pos_get=_pos_get, on_pos=_make_on_pos(),
                    hotkey_label=_hotkey_label, hotkey_capture=_capture_hotkey)
        except Exception as e:
            print("[gui] %s — 退回控制台(Ctrl-C 停)" % e, flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            _cleanup()


if __name__ == "__main__":
    main()
