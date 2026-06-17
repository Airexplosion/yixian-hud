"""
extract_fates.py
────────────────
Pull every 仙命 (Talent) id + Chinese name from the YiXianPai I2Localization
bundle and diff against proxy/fate_id_map.json.

仙命 names live under I2 terms `Talent_<id>`. Each fate has level variants
encoded as base_id + 10000*level (level 0..N), all sharing one name.

Usage:  python tools/extract_fates.py
"""
from __future__ import annotations
import json, re, sys, warnings
from pathlib import Path
import UnityPy, UnityPy.config

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.40f1"
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = Path(r"F:/Steam/steamapps/common/YiXianPai/YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/")
EXISTING_MAP = ROOT / "proxy" / "fate_id_map.json"
OUT_FATES   = ROOT / "tools" / "fates_from_bundle.json"
OUT_FULL    = ROOT / "tools" / "fate_id_map_new.json"   # full map incl. level variants
OUT_DIFF    = ROOT / "tools" / "fate_diff.md"

NAME_PAT = re.compile(r"^Talent_(\d+)$")


def find_terms():
    """Return the mTerms list from whichever bundle holds I2 localization."""
    # fast path: known current bundle, fall back to a scan
    known = BUNDLE_DIR / "390aa60bf746a15c602ce953c17f21f3.bundle"
    order = [known] if known.exists() else []
    order += [b for b in sorted(BUNDLE_DIR.glob("*.bundle")) if b != known]
    for b in order:
        try:
            env = UnityPy.load(str(b))
        except Exception:
            continue
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
                    return b.name, src.get("mTerms", [])
    return None, None


def main() -> int:
    bundle_name, terms = find_terms()
    if not terms:
        print("[error] no localization bundle found", file=sys.stderr)
        return 1
    print(f"localization bundle: {bundle_name}  ({len(terms)} terms)", file=sys.stderr)

    # id -> zh name for every Talent_<id> term
    full: dict[int, str] = {}
    for t in terms:
        term = str(t.get("Term", ""))
        m = NAME_PAT.match(term)
        if not m:
            continue
        langs = t.get("Languages") or []
        if not langs:
            continue
        zh = str(langs[0]).strip()
        if zh and "???" not in zh:
            full[int(m.group(1))] = zh

    # base fates = ids < 10000 (level 0). Level variants = base + 10000*lvl.
    base = {i: n for i, n in full.items() if i < 10000}
    print(f"extracted {len(full)} Talent ids ({len(base)} base 仙命) from bundle", file=sys.stderr)

    OUT_FATES.write_text(json.dumps({str(k): full[k] for k in sorted(full)},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_FULL.write_text(json.dumps({str(k): full[k] for k in sorted(full)},
                                   ensure_ascii=False, indent=1), encoding="utf-8")

    existing = {int(k): v for k, v in json.load(EXISTING_MAP.open(encoding="utf-8")).items()}
    ex_base = {i: n for i, n in existing.items() if i < 10000}

    new_ids   = sorted(set(base) - set(ex_base))
    gone_ids  = sorted(set(ex_base) - set(base))
    renamed   = sorted(i for i in (set(base) & set(ex_base)) if base[i] != ex_base[i])

    L = []
    L.append("# 仙命 (Talent) catalog diff — game bundle vs proxy/fate_id_map.json")
    L.append("")
    L.append(f"Bundle: `{bundle_name}`")
    L.append(f"Bundle base 仙命: {len(base)} (+{len(full)-len(base)} level variants) · existing base: {len(ex_base)}")
    L.append("")
    L.append(f"- **NEW** (in bundle, not in map): {len(new_ids)}")
    L.append(f"- **REMOVED** (in map, gone from bundle): {len(gone_ids)}")
    L.append(f"- **RENAMED** (id in both, name differs): {len(renamed)}")
    L.append("")
    if new_ids:
        L += ["## NEW 仙命", "", "| id | name |", "|---|---|"]
        L += [f"| {i} | {base[i]} |" for i in new_ids]
        L.append("")
    if renamed:
        L += ["## RENAMED 仙命", "", "| id | old (map) | new (bundle) |", "|---|---|---|"]
        L += [f"| {i} | {ex_base[i]} | {base[i]} |" for i in renamed]
        L.append("")
    if gone_ids:
        L += ["## REMOVED (still in map, gone from bundle)", "", "| id | old name |", "|---|---|"]
        L += [f"| {i} | {ex_base[i]} |" for i in gone_ids]
        L.append("")
    OUT_DIFF.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"wrote {OUT_FATES.name}, {OUT_FULL.name}, {OUT_DIFF.name}", file=sys.stderr)
    print(f"SUMMARY: base 仙命 bundle={len(base)} existing={len(ex_base)} "
          f"| +{len(new_ids)} new, ~{len(renamed)} renamed, -{len(gone_ids)} removed",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
