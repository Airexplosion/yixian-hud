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
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEP = ";" if sys.platform.startswith("win") else ":"

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
spec = HERE / "YiXianHUD.spec"
if spec.exists():
    spec.unlink()

B = "native_hud/_build"
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--onefile",
    "--name", "YiXianHUD",
    "--paths", ".", "--paths", "proxy", "--paths", "native_hud/bridge",
    # data: python modules' maps + yisim bundle + the 3 build artefacts + node sim
    "--add-data", f"proxy{SEP}proxy",
    "--add-data", f"tools{SEP}tools",
    "--add-data", f"web{SEP}web",
    "--add-data", f"{B}/capture.agent.js{SEP}{B}",
    "--add-data", f"{B}/bot_glue3.agent.js{SEP}{B}",
    "--add-data", f"{B}/YiXianHud32.dll{SEP}{B}",
    "--add-data", f"native_hud/bridge/yisim_marginal.js{SEP}native_hud/bridge",
    "--add-data", f"native_hud/bridge/hud_gui.py{SEP}native_hud/bridge",
    "--collect-all", "frida",
    "--collect-all", "blackboxprotobuf",
    "--collect-all", "msgpack",
    "--hidden-import", "frida",
    "--hidden-import", "hud_gui",
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
if NODE:
    cmd[-1:-1] = ["--add-binary", f"{NODE}{SEP}."]   # bundle node.exe at root
print("Running:", " ".join(cmd), flush=True)
result = subprocess.run(cmd, cwd=str(HERE))
if result.returncode != 0:
    sys.exit(result.returncode)

built = HERE / "dist" / "YiXianHUD.exe"
target = HERE / "YiXianHUD.exe"
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
