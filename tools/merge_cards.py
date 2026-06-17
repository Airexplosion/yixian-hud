"""
merge_cards.py
──────────────
Apply the card_diff.md option-1 merge to `proxy/card_id_map.json`:
- ADD all NEW cards from `cards_from_bundle.json`.
- FIX the one rename (id 321: clean whitespace around `幻•镜像鲛珠`).
- REMOVE the one real card the bundle no longer has (id 7375763 = 梦•星弈挡).
- LEAVE all 116 junk-name entries (UI sprites, prefab labels) alone —
  they're inert in the running app, and removing them would change line
  counts in version control across many rows for no functional gain.

Output: rewrites `proxy/card_id_map.json` in place, alphabetically
keyed by stringified id (same shape as the existing file).

Usage:
  .venv/Scripts/python.exe tools/merge_cards.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "proxy" / "card_id_map.json"
BUNDLE_PATH = ROOT / "tools" / "cards_from_bundle.json"

# Explicit removal list — only entries the bundle considers REAL cards
# that genuinely disappeared. Junk entries (Skeleton Prefab / Light2D /
# button labels / etc.) we leave alone.
REMOVE_IDS = {"7375763"}  # 梦•星弈挡 — gone from the new bundle


def main() -> int:
    with MAP_PATH.open(encoding="utf-8") as f:
        existing = json.load(f)
    with BUNDLE_PATH.open(encoding="utf-8") as f:
        bundle = json.load(f)

    added = 0
    renamed = 0
    removed = 0

    # 1. Add NEW cards (in bundle, not in map).
    for cid, name in bundle.items():
        if cid not in existing:
            existing[cid] = name
            added += 1

    # 2. Fix renames (whitespace cleanup for id 321 etc.).
    for cid, name in bundle.items():
        if cid in existing and existing[cid] != name:
            existing[cid] = name
            renamed += 1

    # 3. Remove explicit dead-card ids.
    for cid in REMOVE_IDS:
        if cid in existing:
            del existing[cid]
            removed += 1

    # Stable sort by integer id so the file diff is readable.
    sorted_items = sorted(existing.items(), key=lambda kv: int(kv[0]))
    out_obj = dict(sorted_items)

    # Match the existing file's indent style (2-space, ensure_ascii=False).
    MAP_PATH.write_text(
        json.dumps(out_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {MAP_PATH}")
    print(f"  added:   {added}")
    print(f"  renamed: {renamed}")
    print(f"  removed: {removed}")
    print(f"  total entries: {len(out_obj)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
