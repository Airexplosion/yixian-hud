"""
Build YiXianHUD.exe — the same-domain native-HUD injector (spawn mode).

Double-clicking the exe launches YiXianPai through frida and injects the HUD
(记牌器 剩X + T1..T8 matchup 伤害 + 对手命/修预估 + 危险牌警告). A console
window shows status; Ctrl-C stops (and closes the spawned game).

Self-contained: node.exe is bundled (for the yisim damage sim), so the published
exe runs without the user having node installed.

Run from the repo root:
  python build_hud.py
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEP = ";" if sys.platform.startswith("win") else ":"

# 版本号:CI 打 tag 触发时,用 tag(GITHUB_REF_NAME,如 v1.0.7)覆盖 hud_version.py,
# 让发布版的"当前版本"永远等于它的 release tag。本地构建无此环境变量 → 用文件里的默认值。
_ref = os.environ.get("GITHUB_REF_NAME", "")
_m = re.match(r"v?(\d+(?:\.\d+)+)$", _ref.strip())
if _m:
    _vfile = HERE / "native_hud" / "bridge" / "hud_version.py"
    _vfile.write_text(
        '# -*- coding: utf-8 -*-\n'
        '"""YiXianHUD 版本号(发布时由 build_hud.py 从 release tag 注入)。"""\n'
        'HUD_VERSION = "%s"\n' % _m.group(1), encoding="utf-8")
    print("[version] HUD_VERSION=%s (from tag %s)" % (_m.group(1), _ref), flush=True)

# 版本变体:--lite(精简,无 yisim/node)。spawn/attach 运行时自动判定,不再分变体。
LITE = "--lite" in sys.argv
NAME = "YiXianHUD-lite" if LITE else "YiXianHUD"
(HERE / "native_hud" / "bridge" / "hud_edition.py").write_text(
    "# -*- coding: utf-8 -*-\n# edition marker written by build_hud.py\nLITE = %s\n" % LITE,
    encoding="utf-8")
print("[edition] LITE=%s name=%s" % (LITE, NAME), flush=True)

# Bundle node.exe so the published exe runs the yisim damage sim WITHOUT the user
# having node installed. The builder needs node; the OUTPUT is self-contained.
NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
if not Path(NODE).exists():
    print("[!] node.exe not found — yisim damage will need a system node.", flush=True)
    NODE = None

for d in ("build", "dist"):
    p = HERE / d
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
spec = HERE / f"{NAME}.spec"
if spec.exists():
    spec.unlink()

B = "native_hud/_build"
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--onefile", "--windowed",   # --windowed: 无控制台窗口(启动不弹黑框);日志走 YiXianHUD.log
    "--uac-admin",                              # 启动自动请求管理员(WeGame 以管理员跑,需同权限才挂得上 + Tab 等热键不被 UIPI 挡)
    "--name", NAME,
    "--paths", ".", "--paths", "proxy", "--paths", "native_hud/bridge",
    # data: python modules' maps + yisim bundle + the 3 build artefacts + node sim
    "--add-data", f"proxy{SEP}proxy",
    "--add-data", f"tools{SEP}tools",
    "--add-data", f"web{SEP}web",
    "--add-data", f"{B}/capture.agent.js{SEP}{B}",
    "--add-data", f"{B}/bot_glue3.agent.js{SEP}{B}",
    "--add-data", f"{B}/YiXianHud33.dll{SEP}{B}",
    "--add-data", f"native_hud/bridge/yisim_marginal.js{SEP}native_hud/bridge",
    "--add-data", f"native_hud/bridge/yisim_server.js{SEP}native_hud/bridge",
    "--add-data", f"native_hud/bridge/hud_gui.py{SEP}native_hud/bridge",
    "--add-data", f"native_hud/bridge/hud_version.py{SEP}native_hud/bridge",
    "--add-data", f"native_hud/bridge/update_check.py{SEP}native_hud/bridge",
    "--add-data", f"native_hud/bridge/hud_edition.py{SEP}native_hud/bridge",
    "--collect-all", "frida",
    "--collect-all", "blackboxprotobuf",
    "--collect-all", "msgpack",
    "--hidden-import", "frida",
    "--hidden-import", "hud_gui",
    "--hidden-import", "hud_version",
    "--hidden-import", "update_check",
    "--hidden-import", "hud_edition",
    # tray needs only pystray + PIL Image/ImageDraw — NOT all of Pillow.
    "--hidden-import", "pystray",
    "--hidden-import", "pystray._win32",
    "--hidden-import", "PIL.Image",
    "--hidden-import", "PIL.ImageDraw",
    # drop big anaconda libs the HUD never touches (huge size win).
    "--exclude-module", "numpy",
    "--exclude-module", "scipy",
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    "--exclude-module", "PyQt5",
    "--exclude-module", "PyQt6",
    "--exclude-module", "PySide2",
    "--exclude-module", "PySide6",
    "--exclude-module", "IPython",
    "--exclude-module", "notebook",
    "--exclude-module", "pytest",
    "--exclude-module", "cv2",
    "--exclude-module", "torch",
    "--exclude-module", "tensorflow",
    "--exclude-module", "PIL.ImageQt",
    "--hidden-import", "addon",
    "--hidden-import", "shadow_state",
    "--hidden-import", "game_state",
    "--hidden-import", "state_queue",
    "--hidden-import", "decoder",
    "--hidden-import", "card_names",
    "--hidden-import", "battle_log",
    "--hidden-import", "lingyu_merge",
    "--hidden-import", "proxy_view",
    "--hidden-import", "msgpack",
    "native_hud/bridge/hud_launcher.py",
]
if NODE and not LITE:                # Lite 版不带 yisim → 不打包 node.exe(体积大头)
    cmd[-1:-1] = ["--add-binary", f"{NODE}{SEP}."]   # bundle node.exe at root
print("Running:", " ".join(cmd), flush=True)
result = subprocess.run(cmd, cwd=str(HERE))
if result.returncode != 0:
    sys.exit(result.returncode)

built = HERE / "dist" / f"{NAME}.exe"
target = HERE / f"{NAME}.exe"
if built.exists():
    if target.exists():
        target.unlink()
    shutil.move(str(built), str(target))
    print(f"\nBuilt: {target}")
else:
    print("\n[!] build produced no exe", flush=True)
    sys.exit(1)
for d in ("build", "dist"):
    shutil.rmtree(HERE / d, ignore_errors=True)
if spec.exists():
    spec.unlink()
sys.exit(0)
