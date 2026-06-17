"""
build_fate_map.py
─────────────────
Generates proxy/fate_talent_map.json — a lookup from the game's fate id
(as seen in PendingTalentResp / SimpleClientPact) to the yi-sim talent
metadata the damage simulator needs (name_en, simulationKind, runtimeKey,
grantedCardBaseIds).

Replicates talent_catalog.js's classification:
  • runtimeKey comes from talents.json[name_en],
  • TALENT_CLASSIFICATION_OVERRIDES pin the special cases,
  • otherwise: runtime-stack if a runtimeKey exists, else non-combat.

Each fate-level id (entry.ids — base + +10000 per level) maps to the same
talent metadata. Run after updating the yi-sim talent data:
    python build_fate_map.py
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
YISIM = BASE / "vendor" / "yisim"
OUT = BASE / "proxy" / "fate_talent_map.json"

# Mirrors TALENT_CLASSIFICATION_OVERRIDES in talent_catalog.js.
OVERRIDES = {
    "Surge of Qi": {"simulationKind": "runtime-stack", "runtimeKey": "surge_of_qi_stacks"},
    "Indomitable Will": {"simulationKind": "runtime-stack", "runtimeKey": "indomitable_will_stacks"},
    "Counter Move": {"simulationKind": "card-grant", "grantedCardBaseIds": [221]},
    "Shift Stance": {"simulationKind": "card-grant", "grantedCardBaseIds": [222]},
    "Attain Qi": {"simulationKind": "transform"},
    "Wind in Sky": {"simulationKind": "non-combat-or-unsupported"},
    "Jade Scroll of Yin Symbol": {"simulationKind": "card-grant", "grantedCardBaseIds": [214]},
    "Spirit Hexagram Evolves": {"simulationKind": "runtime-stack", "runtimeKey": "spirit_hexagram_evolves_stacks"},
    "Hexagrams Explain": {"simulationKind": "runtime-stack", "runtimeKey": "hexagrams_explain_stacks"},
    "Solitary Void Golden Scroll": {"simulationKind": "transform", "grantedCardBaseIds": [215]},
}


def _norm(name: str) -> str:
    return " ".join(str(name or "").split()).strip()


def build_entry(analysis: dict, runtime_key):
    name = _norm(analysis.get("name_en", ""))
    override = OVERRIDES.get(name)
    sim_kind = "non-combat-or-unsupported"
    resolved_key = runtime_key.strip() if isinstance(runtime_key, str) and runtime_key.strip() else None
    granted = []
    if override:
        sim_kind = override["simulationKind"]
        if override.get("runtimeKey"):
            resolved_key = override["runtimeKey"]
        if isinstance(override.get("grantedCardBaseIds"), list):
            granted = [int(x) for x in override["grantedCardBaseIds"]]
    elif resolved_key:
        sim_kind = "runtime-stack"
    return {
        "name": name,
        "nameCn": analysis.get("name_cn"),
        "simulationKind": sim_kind,
        "runtimeKey": resolved_key if sim_kind == "runtime-stack" else None,
        "grantedCardBaseIds": granted or None,
    }


def main():
    runtime_map = json.loads((YISIM / "talents.json").read_text(encoding="utf-8"))
    analysis = json.loads((YISIM / "talent_analysis.json").read_text(encoding="utf-8"))

    fate_map = {}
    for entry in analysis:
        name = _norm(entry.get("name_en"))
        if not name:
            continue
        meta = build_entry(entry, runtime_map.get(name))
        # Map every level-variant fate id to the same metadata.
        for fid in entry.get("ids", []) or []:
            fate_map[str(int(fid))] = meta

    OUT.write_text(json.dumps(fate_map, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {}
    for v in fate_map.values():
        kinds[v["simulationKind"]] = kinds.get(v["simulationKind"], 0) + 1
    print(f"wrote {OUT} — {len(fate_map)} fate ids")
    print("simulationKind distribution:", kinds)


if __name__ == "__main__":
    main()
