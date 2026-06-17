# -*- coding: utf-8 -*-
"""同域 bot 测试面板 (Bot6) — 常驻 Frida 会话, 点按钮在游戏里执行, 日志区看结果.
全部走客户端自己的方法 (无 gc.choose, 无裸发 pact). 已验证: 读/摆/炼/换/突破/准备/选天衍."""
import threading, traceback
import tkinter as tk
from tkinter import ttk, scrolledtext
import frida

BOT_DLL = r"F:\桌面\弈仙牌外挂\_recon_hotfix\bot8\bin\Release\net40\YiXianBot8.dll"
AGENT   = r"F:\桌面\弈仙牌外挂\_recon_hotfix\cverify\bot_glue3.agent.js"
T = "YiXianBot.Bot8"

class Panel:
    def __init__(self):
        self.ex = None
        self.root = tk.Tk()
        self.root.title("弈仙牌 同域Bot 测试面板 (Bot6)")
        self.root.geometry("580x860")
        self._build()
        self._attach()
        self.root.mainloop()

    def _attach(self):
        try:
            self.session = frida.attach("YiXianPai.exe")
            self.script = self.session.create_script(open(AGENT, encoding="utf-8").read())
            self.script.on("message", lambda m, d: self.log("AGENT ERR: " + str(m.get("description"))) if m.get("type") == "error" else None)
            self.script.load()
            self.ex = self.script.exports_sync
            r = self.ex.load_bot(open(BOT_DLL, "rb").read())
            p = self.ex.ping(T)
            self.log(f"已附加. loadBot={r} ping={p}")
            self.status.config(text="● 已连接", foreground="green")
        except Exception as e:
            self.log("附加失败: " + str(e))
            self.status.config(text="✗ 未连接(游戏没开?)", foreground="red")

    def call(self, label, method, ints=None):
        def work():
            try:
                if self.ex is None: self.log(label + ": 未连接"); return
                res = self.ex.call_s(T, method, ints or [])
                self.log(f"{label}: {res}")
            except Exception as e:
                self.log(f"{label}: EXC {e}")
        threading.Thread(target=work, daemon=True).start()

    def _i(self, entry, default=0):
        try: return int(entry.get())
        except Exception: return default

    def _build(self):
        top = ttk.Frame(self.root, padding=8); top.pack(fill="x")
        self.status = ttk.Label(top, text="…连接中", foreground="orange", font=("", 11, "bold")); self.status.pack(side="left")
        ttk.Button(top, text="重新连接", command=self._reattach).pack(side="right")

        def row(parent, label):
            f = ttk.Frame(parent, padding=(8, 3)); f.pack(fill="x")
            ttk.Label(f, text=label, width=8).pack(side="left"); return f
        def entry(f, w=4, val=""):
            e = ttk.Entry(f, width=w); e.insert(0, val); e.pack(side="left", padx=3); return e

        lf1 = ttk.LabelFrame(self.root, text="读取 / 诊断", padding=4); lf1.pack(fill="x", padx=8, pady=2)
        f = row(lf1, "状态")
        ttk.Button(f, text="读手牌", command=lambda: self.call("手牌", "ReadHand")).pack(side="left")
        ttk.Button(f, text="读牌面", command=lambda: self.call("牌面", "ReadBoard")).pack(side="left", padx=4)
        ttk.Button(f, text="诊断", command=lambda: self.call("诊断", "Diag")).pack(side="left", padx=4)

        lf2 = ttk.LabelFrame(self.root, text="摆牌 (强类型)", padding=4); lf2.pack(fill="x", padx=8, pady=2)
        f = row(lf2, "放牌"); ttk.Label(f, text="手牌#").pack(side="left"); self.e_ph = entry(f, val="0")
        ttk.Label(f, text="→格#(-1空)").pack(side="left"); self.e_pg = entry(f, val="-1")
        ttk.Button(f, text="放", command=lambda: self.call("放牌", "Place", [self._i(self.e_ph), self._i(self.e_pg, -1)])).pack(side="left", padx=6)
        f = row(lf2, "撤回"); ttk.Label(f, text="格#").pack(side="left"); self.e_eg = entry(f, val="0")
        ttk.Button(f, text="撤", command=lambda: self.call("撤回", "Evict", [self._i(self.e_eg)])).pack(side="left", padx=6)
        f = row(lf2, "合成"); ttk.Label(f, text="手牌#").pack(side="left"); self.e_ma = entry(f, val="0")
        ttk.Label(f, text="+#").pack(side="left"); self.e_mb = entry(f, val="1")
        ttk.Button(f, text="合", command=lambda: self.call("合成", "Merge", [self._i(self.e_ma), self._i(self.e_mb)])).pack(side="left", padx=6)

        lf3 = ttk.LabelFrame(self.root, text="炼化 / 换牌", padding=4); lf3.pack(fill="x", padx=8, pady=2)
        f = row(lf3, "炼化"); ttk.Label(f, text="手牌#").pack(side="left"); self.e_rf = entry(f, val="0")
        ttk.Button(f, text="炼", command=lambda: self.call("炼化", "Refine", [self._i(self.e_rf)])).pack(side="left", padx=6)
        f = row(lf3, "换牌"); ttk.Label(f, text="手牌#").pack(side="left"); self.e_rp = entry(f, val="0")
        ttk.Button(f, text="换", command=lambda: self.call("换牌", "Replace", [self._i(self.e_rp)])).pack(side="left", padx=6)

        lf4 = ttk.LabelFrame(self.root, text="回合流程 (客户端方法)", padding=4); lf4.pack(fill="x", padx=8, pady=2)
        f = row(lf4, "回合")
        ttk.Button(f, text="突破", command=lambda: self.call("突破", "Breakthrough")).pack(side="left")
        ttk.Button(f, text="准备", command=lambda: self.call("准备", "Ready")).pack(side="left", padx=6)
        ttk.Button(f, text="触发道韵", command=lambda: self.call("触发道韵", "TriggerDaoYun")).pack(side="left", padx=6)

        lf5 = ttk.LabelFrame(self.root, text="选仙命 (突破后, TalentSelectionPanel)", padding=4); lf5.pack(fill="x", padx=8, pady=2)
        f = row(lf5, "仙命")
        ttk.Button(f, text="读仙命选项", command=lambda: self.call("读仙命", "ReadTalents")).pack(side="left")
        ttk.Label(f, text="选第#").pack(side="left"); self.e_tal = entry(f, val="0")
        ttk.Button(f, text="选仙命", command=lambda: self.call("选仙命", "SelectTalentByIndex", [self._i(self.e_tal)])).pack(side="left", padx=6)

        lf5b = ttk.LabelFrame(self.root, text="选天衍 (2轮后, FateStrategyPanel)", padding=4); lf5b.pack(fill="x", padx=8, pady=2)
        f = row(lf5b, "天衍")
        ttk.Button(f, text="读天衍选项", command=lambda: self.call("读天衍", "ReadFates")).pack(side="left")
        ttk.Label(f, text="选第#").pack(side="left"); self.e_fate = entry(f, val="0")
        ttk.Button(f, text="选天衍", command=lambda: self.call("选天衍", "SelectFateByIndex", [self._i(self.e_fate)])).pack(side="left", padx=6)

        lf6 = ttk.LabelFrame(self.root, text="选道韵 (触发道韵后)", padding=4); lf6.pack(fill="x", padx=8, pady=2)
        f = row(lf6, "道韵")
        ttk.Button(f, text="读道韵选项", command=lambda: self.call("读道韵", "ReadDaoyuns")).pack(side="left")
        ttk.Label(f, text="选第#").pack(side="left"); self.e_dao = entry(f, val="0")
        ttk.Button(f, text="选道韵", command=lambda: self.call("选道韵", "SelectDaoyunByIndex", [self._i(self.e_dao)])).pack(side="left", padx=6)

        lf7 = ttk.LabelFrame(self.root, text="选副职业 (副职选择界面)", padding=4); lf7.pack(fill="x", padx=8, pady=2)
        f = row(lf7, "副职")
        ttk.Button(f, text="读副职选项", command=lambda: self.call("读副职", "ReadCareers")).pack(side="left")
        ttk.Label(f, text="选第#").pack(side="left"); self.e_car = entry(f, val="0")
        ttk.Button(f, text="选副职", command=lambda: self.call("选副职", "SelectCareerByIndex", [self._i(self.e_car)])).pack(side="left", padx=6)

        ttk.Label(self.root, text="日志").pack(anchor="w", padx=8)
        self.txt = scrolledtext.ScrolledText(self.root, height=14, font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _reattach(self):
        try: self.session.detach()
        except Exception: pass
        self._attach()

    def log(self, s):
        self.txt.insert("end", str(s) + "\n"); self.txt.see("end")

if __name__ == "__main__":
    Panel()
