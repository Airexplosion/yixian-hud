"""
extract_card_phases.py
──────────────────────
Pull every card's phase number from `CardConfig` (the protobuf-encoded
export of `CardConfig.xlsx`) inside
  …/StreamingAssets/aa/StandaloneWindows64/f7985c00863ddfeb40a2c42aa61e8905.bundle

The CardConfig schema per entry (decoded via blackboxprotobuf):
  field 1 = card id (int)
  field 2 = Chinese name (utf-8 bytes)
  field 3 = effect template (utf-8 bytes — same as new_cards_text.json `phases`)
  field 4 = sect / class id
  field 6 = **phase** (game-version tier this card was added in: 1..6)
  field 8 = ?
  field 9 = ?
  field 100, 101, 106 = various binary metadata

Verified against user-supplied ground truth (2026-05-28):
  4000091 犀牛望月    phase 3
  4000092 伤魂咒阵    phase 4
  4000094 星弈•劫争   phase 5

Output: tools/card_phases.json
  {
    "<id>": {"name": "...", "phase": N, "sect": S},
    ...
  }
Only base (lv1) ids are emitted; leveled mirrors (+10000 per level) share
the base card's phase.

Usage:
  .venv/Scripts/python.exe tools/extract_card_phases.py
"""
from __future__ import annotations

import json
import struct
import sys
import warnings
from pathlib import Path

try:
    import UnityPy
    import UnityPy.config
    import blackboxprotobuf
except ImportError:
    sys.exit("UnityPy / blackboxprotobuf not installed")

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.40f1"
warnings.filterwarnings("ignore", category=UserWarning, module="UnityPy")

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = Path(
    r"C:/Program Files (x86)/Steam/steamapps/common/YiXianPai/"
    r"YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/"
    r"f7985c00863ddfeb40a2c42aa61e8905.bundle"
)
OUT = ROOT / "tools" / "card_phases.json"


def extract_script_bytes(raw: bytes, asset_name: str) -> bytes | None:
    """TextAsset binary layout in this bundle:
       <u32 name_len> <name bytes> <align4> <u32 script_len> <script bytes>
    """
    name_b = asset_name.encode("utf-8")
    idx = raw.find(name_b)
    if idx < 0:
        return None
    name_len_pos = idx - 4
    name_len = struct.unpack_from("<I", raw, name_len_pos)[0]
    if name_len != len(name_b):
        return None
    after_name = idx + name_len
    align = (4 - (after_name % 4)) % 4
    pos = after_name + align
    script_len = struct.unpack_from("<I", raw, pos)[0]
    pos += 4
    return raw[pos:pos + script_len]


def main() -> int:
    if not BUNDLE.exists():
        sys.exit(f"bundle not found: {BUNDLE}")
    env = UnityPy.load(str(BUNDLE))
    script_b = None
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        raw = bytes(obj.get_raw_data() or b"")
        if b"CardConfig" not in raw:
            continue
        script_b = extract_script_bytes(raw, "CardConfig")
        if script_b:
            break
    if not script_b:
        sys.exit("CardConfig TextAsset not found in bundle")

    pb, _ = blackboxprotobuf.decode_message(script_b)
    cards = pb.get("2", [])
    print(f"loaded {len(cards)} CardConfig entries", file=sys.stderr)

    out: dict[str, dict] = {}
    for c in cards:
        if not isinstance(c, dict):
            continue
        cid = c.get("1", 0)
        if not isinstance(cid, int) or cid <= 0:
            continue
        # Only emit base ids (lv1). Leveled mirrors are +10000 / +20000 etc.
        # The lv-digit lives in the ten-thousands place.
        is_base = cid < 10000 or (cid // 10000) % 10 == 0
        if not is_base:
            continue
        name_b = c.get("2", b"")
        name = name_b.decode("utf-8", "replace") if isinstance(name_b, (bytes, bytearray)) else str(name_b)
        phase = c.get("6", 0)
        sect = c.get("4", 0)
        out[str(cid)] = {"name": name, "phase": phase, "sect": sect}

    # Sort by id (numeric) for stable diffs.
    sorted_out = {k: out[k] for k in sorted(out.keys(), key=int)}
    OUT.write_text(json.dumps(sorted_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} — {len(sorted_out)} base cards", file=sys.stderr)

    # Phase distribution summary
    from collections import Counter
    phases = Counter(v["phase"] for v in sorted_out.values())
    print("\nPhase distribution:")
    for p in sorted(phases):
        print(f"  phase {p}: {phases[p]} cards")

    # Spot-check the user's three cards
    print("\nSpot check:")
    for cid in (4000091, 4000092, 4000094):
        e = sorted_out.get(str(cid))
        if e:
            print(f"  {cid}: name={e['name']!r:20s} phase={e['phase']} sect={e['sect']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
