# -*- coding: utf-8 -*-
"""Settings window + system-tray for the native HUD.

run_gui(settings, on_exit, status_get): a small always-on-top tkinter panel with
show/hide checkboxes (bound live to `settings`), a solo/matchup radio, a status
line, and an Exit button. Closing the window minimizes to the tray (pystray) if
available; the tray menu can re-show or quit. Exit calls on_exit() (which stops
the HUD and closes the spawned game)."""
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk
from tkinter import font as tkfont

try:                                   # 版本号(发布版由 build_hud 从 tag 注入)
    from hud_version import HUD_VERSION
except Exception:
    HUD_VERSION = "?"
try:                                   # 更新检测(多源轮询);缺失则"关于"里降级显示
    import update_check
except Exception:
    update_check = None
try:                                   # Lite 版:隐藏伤害相关 UI(无 yisim)
    from hud_edition import LITE
except Exception:
    LITE = False

ELEMENTS = [
    ("remaining", "记牌器 剩X"),
    ("damage", "造伤 T1–T8"),
    ("opponent", "对手 命/修"),
    ("warning", "危险牌警告"),
    ("skip", "跳过战斗按钮"),
]
if LITE:                               # 精简版去掉造伤显示项
    ELEMENTS = [e for e in ELEMENTS if e[0] != "damage"]

HELP_TEXT = """YiXianHUD 使用说明

【游戏内显示】
· 每张卡右上「剩X」= 该牌在牌库的剩余张数
· 顶部 T1–T8 = 八回合造伤预估
· 左上「敌 命/修」= 对手生命/修为预估
· 红字闪烁 = 对手有危险牌

【快捷键】(可在下方「快捷键」分区自定义)
· Tab = 打开 / 关闭卡池浏览
· D = 鼠标悬浮某张手牌时按 D 换掉它
· 战斗时右上「跳过战斗」按钮 = 跳过动画直接回摆牌

【卡池浏览 (按 Tab)】
· 显示本宗门当前阶段的全部常规牌 + 各牌剩余数
· 右侧「手牌 / 已空 / 危险」切换哪类置顶,其余按剩少在前
· 鼠标滚轮上下滚动,再按 Tab 关闭

【设置面板】
· 显示元素:勾选开关各项显示
· 伤害模式:对打对手(matchup) / 自身输出(solo)
· 位置:填 X,Y 调各文字 / 跳过按钮的位置
· 快捷键:点「改键」后按目标键(支持 Ctrl 组合、鼠标侧键)

提示:本程序仅供个人学习研究,注入有风险、使用可能被封号,详见 EULA。
"""


def _show_help(parent=None):
    """弹出使用说明窗口(设置面板按钮 / 托盘菜单都用它)。"""
    from tkinter import scrolledtext
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    win.title("YiXianHUD 使用说明")
    win.geometry("470x560")
    win.attributes("-topmost", True)
    txt = scrolledtext.ScrolledText(win, wrap="word", font=("", 10))
    txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))
    txt.insert("1.0", HELP_TEXT)
    txt.config(state="disabled")
    ttk.Button(win, text="知道了", command=win.destroy).pack(pady=(0, 10))


def _open_releases():
    """打开发布页(给"关于"里的【去下载】用)。"""
    url = update_check.RELEASES_URL if update_check else \
        "https://github.com/Airexplosion/yixian-hud/releases"
    try:
        webbrowser.open(url)
    except Exception:
        pass


# 关于窗的署名(作者 + 鸣谢),每项 (显示文字, 链接 url)。点击用浏览器打开主页/项目。
ABOUT_CREDITS = [
    ("作者", [
        ("Airexplosion", "https://github.com/Airexplosion"),
        ("Kiven", "https://github.com/0w0k"),
    ]),
    ("鸣谢", [
        ("sharp —— yisim(伤害模拟引擎)", "https://github.com/sharpobject/yisim"),
        ("hiddensquid —— yixiancardcounter(记牌器)",
         "https://gitee.com/hiddensquid12321/yixian-card-counter-with-proxy"),
    ]),
]


def _link_label(parent, text, url):
    """蓝色下划线可点链接:点击用浏览器打开 url,悬停变手型。"""
    lbl = ttk.Label(parent, text="· " + text, foreground="#1a6fd4", cursor="hand2")
    f = tkfont.Font(font=lbl.cget("font"))
    f.configure(underline=True)
    lbl.configure(font=f)
    lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))
    return lbl


def _show_about(parent=None, cached=None):
    """关于窗:当前版本 / 最新版本(后台检测)+ 去下载 + 作者鸣谢。
    cached:启动时已检测的结果(dict),有就直接用,免再请求一次网络。"""
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    win.title("关于 YiXianHUD")
    win.geometry("430x430")
    win.attributes("-topmost", True)
    frm = ttk.Frame(win, padding=16)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="YiXianHUD 弈仙牌悬浮助手" + ("  (Lite)" if LITE else ""),
              font=("", 12, "bold")).pack(anchor="w")
    ttk.Label(frm, text="当前版本:v%s%s" % (HUD_VERSION, "  (Lite·无伤害计算)" if LITE else "")
              ).pack(anchor="w", pady=(8, 0))
    latest = ttk.Label(frm, text="最新版本:检测中…", foreground="gray")
    latest.pack(anchor="w")
    ttk.Button(frm, text="去下载最新版", command=_open_releases).pack(anchor="w", pady=(6, 0))

    for title, items in ABOUT_CREDITS:
        ttk.Separator(frm).pack(fill="x", pady=8)
        ttk.Label(frm, text=title, font=("", 10, "bold")).pack(anchor="w")
        for text, url in items:
            _link_label(frm, text, url).pack(anchor="w")

    ttk.Button(frm, text="知道了", command=win.destroy).pack(side="bottom", pady=(10, 0))

    def _render(res):
        if not res or not res.get("ok"):
            latest.config(text="最新版本:检测失败(网络不通,可手动打开下载页)", foreground="#aa6600")
        elif res.get("has_update"):
            latest.config(text="最新版本:v%s  🔴 有新版本可更新!" % res["latest"], foreground="#cc2222")
        else:
            latest.config(text="最新版本:v%s(已是最新 ✓)" % res["latest"], foreground="#22aa66")

    if cached and cached.get("latest") is not None:
        _render(cached)
    elif update_check is not None:
        def _bg():
            res = update_check.check_update(HUD_VERSION)
            try:
                win.after(0, lambda: _render(res))
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()
    else:
        latest.config(text="最新版本:(更新检测模块不可用)", foreground="gray")


def _show_positions(parent=None, pos_get=None, on_pos=None):
    """位置设置弹窗:各 HUD 元素的 X,Y 微调(从主面板独立出来,单独菜单窗口)。"""
    pos_elems = [("total", "造伤 T1–T8"), ("warn", "危险牌警告"),
                 ("opp", "对手 命/修"), ("skip", "跳过战斗按钮")]
    if LITE:                               # 精简版无造伤,去掉其位置项
        pos_elems = [p for p in pos_elems if p[0] != "total"]
    win = tk.Toplevel(parent) if parent is not None else tk.Tk()
    win.title("位置设置")
    win.geometry("300x250")
    win.attributes("-topmost", True)
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="各元素位置 (X, Y)", font=("", 10, "bold")).pack(anchor="w", pady=(0, 6))
    for key, text in pos_elems:
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=text, width=12).pack(side="left")
        cx, cy = (pos_get(key) if pos_get else (0, 0))
        ex = ttk.Entry(row, width=6)
        ex.insert(0, str(int(cx)))
        ex.pack(side="left")
        ey = ttk.Entry(row, width=6)
        ey.insert(0, str(int(cy)))
        ey.pack(side="left", padx=(4, 0))

        def _push(k=key, exx=ex, eyy=ey):
            try:
                x, y = int(exx.get().strip()), int(eyy.get().strip())
            except ValueError:
                return
            if on_pos:
                on_pos(k, x, y)
        ttk.Button(row, text="应用", width=5, command=_push).pack(side="left", padx=4)
    ttk.Button(frm, text="关闭", command=win.destroy).pack(side="bottom", pady=(10, 0))


def _make_tray(on_show, on_quit, on_help=None, on_about=None):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None
    img = Image.new("RGB", (64, 64), (18, 26, 44))
    d = ImageDraw.Draw(img)
    d.ellipse((12, 12, 52, 52), fill=(120, 200, 255))
    items = [pystray.MenuItem("显示设置", lambda icon, item: on_show())]
    if on_help is not None:
        items.append(pystray.MenuItem("使用说明", lambda icon, item: on_help()))
    if on_about is not None:
        items.append(pystray.MenuItem("关于", lambda icon, item: on_about()))
    items.append(pystray.MenuItem("退出", lambda icon, item: on_quit()))
    return pystray.Icon("YiXianHUD", img, "弈仙牌 HUD", pystray.Menu(*items))


def run_gui(settings, on_exit, status_get=None, pos_get=None, on_pos=None,
            hotkey_label=None, hotkey_capture=None, guard_get=None):
    root = tk.Tk()
    root.title("弈仙牌 HUD")
    root.geometry("300x730")          # 加高:容下显示元素/伤害模式/位置/快捷键/状态/守护红字 + 底部三按钮(关于/说明/退出)
    root.attributes("-topmost", True)
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    # 窗口置顶开关:默认开(保持原行为);取消后本窗口不再强制置顶,可被游戏盖住。
    top_var = tk.BooleanVar(value=True)

    def _toptoggle():
        try:
            root.attributes("-topmost", bool(top_var.get()))
        except Exception:
            pass
    ttk.Checkbutton(frm, text="窗口置顶(取消则可被游戏盖住)",
                    variable=top_var, command=_toptoggle).pack(anchor="w")
    ttk.Separator(frm).pack(fill="x", pady=6)

    ttk.Label(frm, text="显示元素", font=("", 10, "bold")).pack(anchor="w")
    for key, text in ELEMENTS:
        var = tk.BooleanVar(value=bool(settings.get(key, True)))

        def _bind(k=key, v=var):
            settings[k] = bool(v.get())
        ttk.Checkbutton(frm, text=text, variable=var, command=_bind).pack(anchor="w")

    if not LITE:                       # 伤害模式仅完整版有
        ttk.Separator(frm).pack(fill="x", pady=8)
        ttk.Label(frm, text="伤害模式", font=("", 10, "bold")).pack(anchor="w")
        mode = tk.StringVar(value="matchup" if settings.get("matchup", True) else "solo")

        def _mode():
            settings["matchup"] = (mode.get() == "matchup")
        ttk.Radiobutton(frm, text="对打对手 (matchup)", variable=mode,
                        value="matchup", command=_mode).pack(anchor="w")
        ttk.Radiobutton(frm, text="自身输出 (solo)", variable=mode,
                        value="solo", command=_mode).pack(anchor="w")

    ttk.Separator(frm).pack(fill="x", pady=8)
    ttk.Button(frm, text="📐 位置设置…",
               command=lambda: _show_positions(root, pos_get, on_pos)).pack(anchor="w")

    if hotkey_label and hotkey_capture:
        ttk.Separator(frm).pack(fill="x", pady=8)
        ttk.Label(frm, text="快捷键 (支持 Ctrl组合 / 鼠标侧键)", font=("", 10, "bold")).pack(anchor="w")
        for hk, htext in (("swap", "D牌 换牌"), ("pool", "卡池 浏览")):
            hrow = ttk.Frame(frm)
            hrow.pack(fill="x", pady=1)
            ttk.Label(hrow, text=htext, width=10).pack(side="left")
            hcur = ttk.Label(hrow, text=hotkey_label(hk), width=11, foreground="#22aa66")
            hcur.pack(side="left")

            def _rebind(k=hk, lbl=hcur):
                lbl.config(text="按键中…", foreground="#aa6600")

                def _done():
                    try:
                        lbl.config(text=hotkey_label(k), foreground="#22aa66")
                    except Exception:
                        pass
                hotkey_capture(k, lambda: root.after(0, _done))
            ttk.Button(hrow, text="改键", width=5, command=_rebind).pack(side="left", padx=4)

    ttk.Separator(frm).pack(fill="x", pady=8)
    status = ttk.Label(frm, text="启动中…", foreground="gray", wraplength=270)
    status.pack(anchor="w")
    # 被动更新提示:启动后台检测,有新版才显红字(不弹窗打断);详情在【关于】。
    update_hint = ttk.Label(frm, text="", foreground="#cc2222", wraplength=270)
    update_hint.pack(anchor="w")
    chk = {}                              # 启动检测结果(供【关于】复用,免再请求)
    # 守护提示:检测到直播软件 / 旧版本 → 红字粗体「已禁用」(内容已被 C# 总开关隐藏)。
    guard_lbl = ttk.Label(frm, text="", foreground="#cc2222", font=("", 10, "bold"), wraplength=270)
    guard_lbl.pack(anchor="w", pady=(4, 0))

    tray = {"icon": None}

    def _quit():
        if tray["icon"] is not None:
            try:
                tray["icon"].stop()
            except Exception:
                pass
        try:
            on_exit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    ttk.Button(frm, text="退出 (关HUD+游戏)", command=_quit).pack(side="bottom", fill="x", pady=(8, 0))
    # 帮助/关于按钮(pack 在退出之后 → 显示在退出上方;关于在最上)
    ttk.Button(frm, text="❓ 使用说明", command=lambda: _show_help(root)).pack(side="bottom", fill="x", pady=(8, 0))
    ttk.Button(frm, text="ℹ️ 关于 / 检查更新",
               command=lambda: _show_about(root, chk)).pack(side="bottom", fill="x", pady=(8, 0))

    # Close button → minimize to tray (don't quit) if a tray icon exists.
    def _on_close():
        if tray["icon"] is not None:
            root.withdraw()
        else:
            _quit()
    root.protocol("WM_DELETE_WINDOW", _on_close)

    icon = _make_tray(on_show=lambda: root.after(0, root.deiconify),
                      on_quit=lambda: root.after(0, _quit),
                      on_help=lambda: root.after(0, lambda: _show_help(root)),
                      on_about=lambda: root.after(0, lambda: _show_about(root, chk)))
    if icon is not None:
        tray["icon"] = icon
        threading.Thread(target=icon.run, daemon=True).start()

    # 启动后台检测最新版(多源轮询);有新版则设置窗顶显红字提示。失败静默。
    if update_check is not None:
        def _startup_check():
            res = update_check.check_update(HUD_VERSION)
            chk.clear()
            chk.update(res)
            if res.get("has_update"):
                def _show():
                    update_hint.config(
                        text="🔴 发现新版本 v%s — 点【关于 / 检查更新】下载" % res["latest"])
                try:
                    root.after(0, _show)
                except Exception:
                    pass
        threading.Thread(target=_startup_check, daemon=True).start()

    if status_get or guard_get:
        def _tick():
            if status_get:
                try:
                    status.config(text=status_get())
                except Exception:
                    pass
            if guard_get:
                try:
                    guard_lbl.config(text=guard_get() or "")
                except Exception:
                    pass
            root.after(1000, _tick)
        _tick()

    root.mainloop()
