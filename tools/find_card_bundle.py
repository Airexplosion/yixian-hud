"""
find_card_bundle.py
───────────────────
Scan every Unity AssetBundle in the YiXianPai install (via UnityPy) for
known card-name strings and identify the current card-text bundle.

Each game patch shuffles bundle filenames AND the bundle format now has
an obfuscation flag (0x200) plus stripped `unity_version` metadata
('5.x.x'), so our hand-rolled LZ4 decoder doesn't work anymore.
UnityPy with a forced FALLBACK_UNITY_VERSION handles it cleanly.

Usage:
  .venv/Scripts/python.exe tools/find_card_bundle.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

try:
    import UnityPy
    import UnityPy.config
except ImportError:
    sys.exit("UnityPy not installed — run: .venv/Scripts/pip.exe install UnityPy")

# Bundle metadata is stripped on these files (`unity_version` reads as
# '5.x.x'); force a real-looking version so UnityPy parses them.
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.40f1"
warnings.filterwarnings("ignore", category=UserWarning, module="UnityPy")

BUNDLE_DIR = Path(
    r"C:/Program Files (x86)/Steam/steamapps/common/YiXianPai/"
    r"YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/"
)

MARKERS = [
    "三峰剑",       # vanilla Sword class
    "云剑•探云",    # bullet-form
    "云剑·探云",    # mid-dot form
    "灵气灌注",     # vanilla qi
    "护身灵气",     # vanilla def
    "剑挡",         # very common
]


def scan_bundle(path: Path, marker_bytes: list[bytes]) -> dict[str, int]:
    """Read every TextAsset / MonoBehaviour's raw data from `path` and
    count marker hits. Returns {marker_utf8: count} for any non-zero hit.
    """
    try:
        env = UnityPy.load(str(path))
    except Exception:
        return {}
    hits: dict[str, int] = {}
    for obj in env.objects:
        # We mostly care about MonoBehaviour (ScriptableObject card data)
        # and TextAsset (raw JSON/CSV catalogs). Other types like Texture
        # won't have CJK strings.
        if obj.type.name not in ("MonoBehaviour", "TextAsset", "MonoScript"):
            continue
        try:
            data = bytes(obj.get_raw_data() or b"")
        except Exception:
            continue
        if not data:
            continue
        for marker, mb in zip(MARKERS, marker_bytes):
            n = data.count(mb)
            if n > 0:
                hits[marker] = hits.get(marker, 0) + n
    return hits


def main() -> int:
    if not BUNDLE_DIR.exists():
        print(f"[error] bundle dir not found: {BUNDLE_DIR}", file=sys.stderr)
        return 1
    bundles = sorted(BUNDLE_DIR.glob("*.bundle"))
    print(f"scanning {len(bundles)} bundles via UnityPy for known card names…", file=sys.stderr)
    marker_bytes = [m.encode("utf-8") for m in MARKERS]

    candidates: list[tuple[str, int, dict[str, int]]] = []
    failed = 0
    for i, bundle in enumerate(bundles, 1):
        if i % 25 == 0:
            print(f"  …{i}/{len(bundles)}", file=sys.stderr)
        hits = scan_bundle(bundle, marker_bytes)
        if hits:
            candidates.append((bundle.name, bundle.stat().st_size, hits))

    candidates.sort(key=lambda x: -sum(x[2].values()))
    print()
    print(f"{'Bundle':<48} {'Size':>12}  Hits per marker")
    print("-" * 100)
    for name, size, hits in candidates:
        h = ", ".join(f"{k}={v}" for k, v in hits.items())
        print(f"{name:<48} {size:>12,}  {h}")
    print()
    print(f"Found {len(candidates)} bundle(s) with card markers.")
    if candidates:
        print(f"\nTop candidate: {candidates[0][0]}")
        print(f"  → run dump_cards.py on this bundle next")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
