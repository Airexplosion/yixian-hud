"""
extract_cards.py
────────────────
Pull every card name + ID from the YiXianPai I2Localization bundle and
diff against `proxy/card_id_map.json` to report cards added in the
current game patch.

Mechanism:
- Locate the localization bundle (found via `find_card_bundle.py`):
  `03c9b94846ca068b5185bd5085a13144.bundle` as of 2026-05-27.
- Read its single Localization MonoBehaviour. `mSource.mTerms` is a
  list of `{Term, Languages, Flags}` — `Term` is the I2 key, `Languages`
  is `[zh-CN, en, zh-TW]`.
- Card entries have terms shaped like `Card_<id>` or `CardName_<id>` or
  raw integer IDs as string keys (varies by patch); we detect by both
  Term-prefix and by Term-is-numeric heuristics.
- Load `proxy/card_id_map.json` and report:
    * NEW cards (in bundle, not in map)
    * REMOVED cards (in map, not in bundle)
    * RENAMED cards (id present in both but Chinese name differs)

Usage:
  .venv/Scripts/python.exe tools/extract_cards.py
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

try:
    import UnityPy
    import UnityPy.config
except ImportError:
    sys.exit("UnityPy not installed — run: .venv/Scripts/pip.exe install UnityPy")

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.40f1"
warnings.filterwarnings("ignore", category=UserWarning, module="UnityPy")

ROOT = Path(__file__).resolve().parent.parent
LOCALIZATION_BUNDLE = Path(
    r"C:/Program Files (x86)/Steam/steamapps/common/YiXianPai/"
    r"YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/"
    r"03c9b94846ca068b5185bd5085a13144.bundle"
)
EXISTING_MAP = ROOT / "proxy" / "card_id_map.json"
OUT_DIFF = ROOT / "tools" / "card_diff.md"
OUT_CARDS = ROOT / "tools" / "cards_from_bundle.json"


# I2Localization stores card names under `CardName_<id>` and card
# descriptions under `CardDesc_<id>`. We ONLY want the name field —
# descriptions are long `{anima}`/`[灵气]` templates, not the human-readable
# label that should land in card_id_map.json.
NAME_PATTERN = re.compile(r"^CardName_(\d+)$")


def extract_id(term: str) -> int | None:
    """Extract the numeric card id from an I2 term key, or None."""
    m = NAME_PATTERN.match(term)
    return int(m.group(1)) if m else None


def main() -> int:
    if not LOCALIZATION_BUNDLE.exists():
        print(f"[error] bundle not found: {LOCALIZATION_BUNDLE}", file=sys.stderr)
        return 1
    env = UnityPy.load(str(LOCALIZATION_BUNDLE))
    terms = None
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if isinstance(tree, dict):
            src = tree.get("mSource", {})
            if isinstance(src, dict) and "mTerms" in src:
                terms = src.get("mTerms", [])
                break
    if not terms:
        print("[error] no mTerms array found in any MonoBehaviour", file=sys.stderr)
        return 1
    print(f"loaded {len(terms)} localization terms", file=sys.stderr)

    # Bucket terms by prefix to see what schemes the game uses for cards.
    from collections import Counter
    prefix_count: Counter = Counter()
    for t in terms:
        term = str(t.get("Term", ""))
        prefix = term.split("_", 1)[0] if "_" in term else (
            term.split("/", 1)[0] if "/" in term else term[:8]
        )
        prefix_count[prefix] += 1
    print(f"\nTerm-prefix tally (top 20):", file=sys.stderr)
    for p, n in prefix_count.most_common(20):
        print(f"  {p!r}: {n}", file=sys.stderr)

    # First pass: try the obvious card-name prefixes.
    bundle_cards: dict[int, str] = {}  # card_id -> Chinese name
    for t in terms:
        term = str(t.get("Term", ""))
        cid = extract_id(term)
        if cid is None:
            continue
        langs = t.get("Languages") or []
        if not langs:
            continue
        # Languages: [zh-CN, en, zh-TW] (3 entries by convention)
        zh = str(langs[0]).strip()
        if zh and not zh.startswith("{") and "???" not in zh:
            bundle_cards[cid] = zh

    print(f"\nExtracted {len(bundle_cards)} card-id→name entries from bundle",
          file=sys.stderr)

    # Save the raw extraction.
    OUT_CARDS.write_text(
        json.dumps(
            {str(k): v for k, v in sorted(bundle_cards.items())},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT_CARDS}")

    # Diff against existing map.
    with EXISTING_MAP.open(encoding="utf-8") as f:
        existing = {int(k): v for k, v in json.load(f).items()}
    print(f"existing map has {len(existing)} entries", file=sys.stderr)

    new_ids = sorted(set(bundle_cards) - set(existing))
    removed_ids = sorted(set(existing) - set(bundle_cards))
    renamed = sorted(
        cid for cid in (set(bundle_cards) & set(existing))
        if bundle_cards[cid] != existing[cid]
    )

    lines = []
    lines.append("# Card catalog diff — game bundle vs proxy/card_id_map.json")
    lines.append("")
    lines.append(f"Bundle: `{LOCALIZATION_BUNDLE.name}`")
    lines.append(f"Bundle cards: {len(bundle_cards)} · existing map: {len(existing)}")
    lines.append("")
    lines.append(f"- **NEW** (in bundle, not in map): {len(new_ids)}")
    lines.append(f"- **REMOVED** (in map, not in bundle): {len(removed_ids)}")
    lines.append(f"- **RENAMED** (id present in both, name differs): {len(renamed)}")
    lines.append("")

    if new_ids:
        lines.append("## NEW cards")
        lines.append("")
        lines.append("| id | name |")
        lines.append("|---|---|")
        for cid in new_ids:
            lines.append(f"| {cid} | {bundle_cards[cid]} |")
        lines.append("")

    if renamed:
        lines.append("## RENAMED cards")
        lines.append("")
        lines.append("| id | old (map) | new (bundle) |")
        lines.append("|---|---|---|")
        for cid in renamed:
            lines.append(f"| {cid} | {existing[cid]} | {bundle_cards[cid]} |")
        lines.append("")

    if removed_ids:
        lines.append("## REMOVED cards (still in map, gone from bundle)")
        lines.append("")
        lines.append("First 40 (likely either renamed away or game-purged):")
        lines.append("")
        lines.append("| id | old name |")
        lines.append("|---|---|")
        for cid in removed_ids[:40]:
            lines.append(f"| {cid} | {existing[cid]} |")
        if len(removed_ids) > 40:
            lines.append(f"| … | …{len(removed_ids) - 40} more |")
        lines.append("")

    OUT_DIFF.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_DIFF}")
    print(f"\nSummary: +{len(new_ids)} new, ~{len(renamed)} renamed, -{len(removed_ids)} removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
