# -*- coding: utf-8 -*-
"""通用 callPrivate 探针:用 bot_glue3 的堆扫描抓某类型的活实例 + 调它的私有无参方法。
绕开 FindILRSubPanel(对 TempHidePanelBase 模态面板无效)。

用法:  python native_hud/bridge/callpriv.py <Type> <Method>
例:    python native_hud/bridge/callpriv.py FateStrategyPanel OnConfirmButtonClick
       python native_hud/bridge/callpriv.py FateBranchPanel OnConfirmButtonClick

弹窗弹出时运行。找到活实例就调用(确认默认高亮的选项=通常第0个)。
"""
import os
import sys
import time
from pathlib import Path

import frida

REPO = Path(__file__).resolve().parents[2]
GLUE = str(Path(os.environ.get("YX_HUD_BUILD", REPO / "native_hud" / "_build")) / "bot_glue3.agent.js")
PROC = os.environ.get("YX_PROC", "YiXianPai.exe")

# 候选:不给参数时,依次探测常见选择面板的确认/选择方法,报告哪个有活实例。
CANDIDATES = [
    ("FateStrategyPanel", "OnConfirmButtonClick"),       # 选天衍仙命
    ("FateBranchPanel", "OnConfirmButtonClick"),         # 选择仙命
    ("CareerSelectionPanel", "OnConfirmButtonClick"),    # 选副职业
    ("BattleDaoYunSelectionPanel", "OnSelected"),        # 选道韵
    ("TalentSelectionPanel", "OnConfirmButtonClick"),    # 天赋/天命
]


def main():
    args = sys.argv[1:]
    sess = frida.attach(PROC)
    sc = sess.create_script(open(GLUE, encoding="utf-8").read(), runtime="qjs")
    sc.load()
    ex = sc.exports_sync

    if len(args) >= 2:
        probes = [(args[0], args[1])]
    else:
        print("(无参数 → 依次探测候选面板,只有活着的那个会真正触发)", flush=True)
        probes = CANDIDATES

    for typ, method in probes:
        try:
            r = ex.call_private(typ, method)
            print("callPrivate %-28s %-22s -> %s" % (typ, method, r), flush=True)
        except Exception as e:
            print("callPrivate %-28s %-22s ERR %r" % (typ, method, e), flush=True)
        time.sleep(0.2)

    time.sleep(0.5)
    try:
        sc.unload(); sess.detach()
    except Exception:
        pass


if __name__ == "__main__":
    main()
