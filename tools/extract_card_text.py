"""
extract_card_text.py
────────────────────
Pull every card's effect-text template from the YiXianPai I2Localization
bundle. Companion to `extract_cards.py` (which only extracted names).

Mechanism:
- Same bundle (`03c9b94846ca068b5185bd5085a13144.bundle` as of 2026-05-27).
- Every card has TWO terms:
    `CardName_<id>` → Chinese display name (already in card_id_map.json)
    `CardDesc_<id>` → effect template, e.g. `[灵气]+{anima}\n{attack}攻×{attackCount}`
- We pull `Languages[0]` (zh-CN) for both.

Outputs:
- `tools/all_cards_text.json` — every card id → {name, text} for future
  lookups (flat shape, keyed by stringified id).
- `tools/new_cards_text.json` — only the cards that were newly added in
  the current patch (the 144 NEW entries from card_diff.md), grouped by
  base name with phase-variant ids and texts. Shape mirrors
  `tools/dream_cards_game.json` so the yisim auditor tool can consume it.

Usage:
  .venv/Scripts/python.exe tools/extract_card_text.py
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
BUNDLE_CARDS = ROOT / "tools" / "cards_from_bundle.json"
OUT_ALL = ROOT / "tools" / "all_cards_text.json"
OUT_NEW = ROOT / "tools" / "new_cards_text.json"

NAME_PAT = re.compile(r"^CardName_(\d+)$")
DESC_PAT = re.compile(r"^CardDesc_(\d+)$")


def _clean(s: object) -> str:
    """Strip surrounding whitespace; normalize \\r\\n to \\n."""
    if not isinstance(s, str):
        return ""
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


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
        print("[error] no mTerms array found", file=sys.stderr)
        return 1

    names: dict[int, str] = {}
    descs: dict[int, str] = {}
    for t in terms:
        term = str(t.get("Term", ""))
        langs = t.get("Languages") or []
        if not langs:
            continue
        zh = _clean(langs[0])  # zh-CN
        if not zh:
            continue
        m = NAME_PAT.match(term)
        if m:
            names[int(m.group(1))] = zh
            continue
        m = DESC_PAT.match(term)
        if m:
            descs[int(m.group(1))] = zh

    print(f"loaded {len(terms)} terms · {len(names)} names · {len(descs)} descs",
          file=sys.stderr)

    # ── tools/all_cards_text.json — flat full reference ─────────────────
    all_cards: dict[str, dict[str, str]] = {}
    ids = sorted(set(names) | set(descs))
    for cid in ids:
        all_cards[str(cid)] = {
            "name": names.get(cid, ""),
            "text": descs.get(cid, ""),
        }
    OUT_ALL.write_text(
        json.dumps(all_cards, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {OUT_ALL} ({len(all_cards)} cards)")

    # ── tools/new_cards_text.json — only the NEW entries, grouped ──────
    # Definition: NEW = id present in cards_from_bundle.json but not in
    # the pre-merge card_id_map.json. We can't reconstruct "pre-merge"
    # anymore (we already merged), so use the explicit list from the most
    # recent extract_cards.py run — that file is cards_from_bundle.json
    # diffed against any earlier snapshot. For now, find NEW by the
    # diff-of-record: ids in card_diff.md. Easier: re-derive from
    # cards_from_bundle.json minus our "had it before merge" heuristic
    # (= ids the existing map ALREADY had before R29 merge added them).
    #
    # To stay robust against future re-runs, take the list of NEW ids
    # directly from the card_diff.md's NEW section by parsing it. If the
    # file isn't present, fall back to "show everything missing from the
    # 'old' card_id_map" — but since we merged, that's empty. So we
    # PARSE card_diff.md if present.
    new_ids: set[int] = set()
    diff_md = ROOT / "tools" / "card_diff.md"
    in_new_section = False
    if diff_md.exists():
        for line in diff_md.read_text(encoding="utf-8").splitlines():
            if line.startswith("## NEW cards"):
                in_new_section = True
                continue
            if line.startswith("## "):
                in_new_section = False
                continue
            if in_new_section and line.startswith("| ") and not line.startswith("| id"):
                # `| 381 | 灵羽 |` → extract first int
                parts = [p.strip() for p in line.strip("| ").split("|")]
                if parts and parts[0].isdigit():
                    new_ids.add(int(parts[0]))
    print(f"NEW ids from card_diff.md: {len(new_ids)}", file=sys.stderr)

    # Group NEW cards by base name. Cards have 3 phase variants per base
    # (`NNN / 1NNNN / 2NNNN` or similar — every step of +10000 is a phase).
    grouped: dict[str, dict] = {}
    for cid in sorted(new_ids):
        name = names.get(cid, "")
        if not name:
            continue
        # Resolve to canonical base name: same name across phase variants.
        entry = grouped.setdefault(name, {"ids": [], "phases": []})
        entry["ids"].append(cid)
        entry["phases"].append(descs.get(cid, ""))

    OUT_NEW.write_text(
        json.dumps(grouped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n_base = len(grouped)
    n_phases = sum(len(g["phases"]) for g in grouped.values())
    print(f"wrote {OUT_NEW} ({n_base} base cards, {n_phases} phase entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
