"""
dream_audit.py
──────────────
Compares the game-text dump from `dump_dream_cards.py` against yisim's
**actual** card-action implementations.

yisim has a 2-level card-action system:
  - `vendor/yisim/swogi.json` — declarative `actions[]` for simple cards
    (fallback / catalog of card metadata).
  - `vendor/yisim/card_actions.js` — JavaScript function bodies for complex
    cards. When `card_actions[card_id]` exists, the engine runs the JS
    function INSTEAD of the swogi `actions` array.

An earlier version of this audit only read `swogi.json`, which produced false
positives for every dream card that has a JS override (which is most of them).
This version reads `card_actions.js` first and falls back to `swogi.json`.

The audit emits a markdown report:
  - Missing from yisim entirely  (no override AND no swogi entry, OR empty)
  - Likely buggy / mismatched    (keyword in game text not found in JS body)
  - Probably fine                 (heuristic finds no issue)

Run:
  .venv/Scripts/python.exe tools/dream_audit.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME = Path(__file__).resolve().parent / "dream_cards_game.json"
SWOGI = ROOT / "vendor" / "yisim" / "swogi.json"
NAMES = ROOT / "vendor" / "yisim" / "names.json"
CARD_ACTIONS_JS = ROOT / "vendor" / "yisim" / "card_actions.js"
OUT_MD = Path(__file__).resolve().parent / "dream_audit_report.md"


# Game keyword → list of yisim terms that, if present anywhere in the JS body
# (or swogi actions string), satisfy the keyword. Multi-term lists treat any
# match as OK (handles synonyms like 身法 → agility or chase).
HINTS = {
    "[身法]":   ["agility", "chase"],
    "[再次行动]": ["chase"],
    "[剑意]":    ["sword_intent"],
    "[内伤]":    ["internal_injury"],
    "[防]":      ["def", "increase_idx_def"],
    "[攻]":      ["atk(", "atk,"],         # match `game.atk(N)` calls; avoid hitting `attack` substring
    "[灵气]":    ["qi"],
    "[剑气]":    ["sword_qi"],
    "[云海]":    ["cloud_sea"],
    "[水月]":    ["moon_water"],
    "[持续]":    ["continuous", "increase_idx_x_by_c"],
    "[力量]":    ["force"],
    "[消耗]":    ["consumption", "exhaust"],
    "[剑阵]":    ["sword_formation"],
    "[卦象]":    ["hexagram"],
    "[体魄]":    ["physique"],
    "[加攻]":    ["increase_atk"],
    "[星点]":    ["star_point"],
    "[崩拳]":    ["crash_fist"],
    "[闪避]":    ["dodge"],
    "[剑]":      ["sword"],
}


JS_BLOCK_RE = re.compile(
    r'card_actions\["(D\d+)"\]\s*=\s*\([^)]*\)\s*=>\s*\{(.*?)^\}',
    re.MULTILINE | re.DOTALL,
)


def load_js_bodies(path: Path) -> dict[str, str]:
    """Return a dict { 'D11141': '<body source>', … } extracted from card_actions.js."""
    src = path.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for m in JS_BLOCK_RE.finditer(src):
        cid = m.group(1)
        body = m.group(2).strip()
        bodies[cid] = body
    return bodies


def normalize(name: str) -> str:
    return name.replace("•", "·").strip()


def main() -> int:
    game = json.loads(GAME.read_text(encoding="utf-8"))
    swogi = json.loads(SWOGI.read_text(encoding="utf-8"))
    names = json.loads(NAMES.read_text(encoding="utf-8"))
    js_bodies = load_js_bodies(CARD_ACTIONS_JS)
    print(f"loaded {len(js_bodies)} JS function bodies from card_actions.js",
          file=sys.stderr)

    name_to_id: dict[str, str] = {}
    for n in names:
        if isinstance(n, dict):
            namecn = n.get("namecn")
            if isinstance(namecn, str) and namecn.startswith("梦"):
                name_to_id[normalize(namecn)] = str(n.get("id", ""))

    missing: list[str] = []
    buggy: list[tuple[str, str, list[str]]] = []
    fine: list[tuple[str, str]] = []

    def yisim_repr_for_phase(base_id: str, phase: int) -> tuple[str, str]:
        """Return (source_tag, source_text) — JS body if available, else swogi
        actions JSON, else 'MISSING'."""
        yid = f"{base_id[:-1]}{phase}"
        if yid in js_bodies:
            return ("card_actions.js", js_bodies[yid])
        entry = swogi.get(yid, {})
        if isinstance(entry, dict) and entry.get("actions") is not None:
            return ("swogi.json",
                    json.dumps(entry.get("actions"), ensure_ascii=False))
        return ("MISSING", "")

    for raw_name, info in sorted(game.items()):
        name = normalize(raw_name)
        phases = info["phases"]
        base_id = name_to_id.get(name)
        if not base_id:
            missing.append(name)
            continue

        problems: list[str] = []
        for ph, tpl in enumerate(phases, start=1):
            yid = f"{base_id[:-1]}{ph}"
            tag, src = yisim_repr_for_phase(base_id, ph)
            if tag == "MISSING":
                problems.append(f"phase{ph} ({yid}): NO entry in card_actions.js or swogi.json")
                continue
            # Suppress trigger-keyword flags when the JS body declares a
            # "continuous + custom-stack" pattern. These cards rely on
            # engine-side hooks that consume the stack on the right event;
            # the trigger term won't appear in the card's own JS body but the
            # effect IS implemented correctly. Pattern: body has `continuous(`
            # AND a card-specific stack variable (contains `_stacks` and is
            # NOT just `agility` / `qi` / `force` etc.).
            uses_continuous_stack = (
                ("continuous(" in src or "continuous_" in src or "[\"continuous\"]" in src)
                and re.search(r'\b\w*_stacks\b', src) is not None
            )
            for kw, expected in HINTS.items():
                if kw not in tpl:
                    continue
                if any(t in src for t in expected):
                    continue
                # Suppress noise on trigger-style keywords for continuous-stack cards.
                if uses_continuous_stack and kw in ("[灵气]", "[卦象]", "[剑意]",
                                                    "[身法]", "[剑气]", "[剑]",
                                                    "[再次行动]"):
                    continue
                problems.append(
                    f"phase{ph} ({yid}, {tag}): text has `{kw}` but body lacks any of "
                    f"{expected}"
                )

        if problems:
            buggy.append((name, base_id, problems))
        else:
            fine.append((name, base_id))

    # ──────── report ────────
    lines: list[str] = []
    lines.append("# 梦 dream-card audit report (v2: reads card_actions.js)\n")
    lines.append(
        f"- Game-side dream cards: **{len(game)}**\n"
        f"- yisim base dream IDs (names.json): **{len(name_to_id)}**\n"
        f"- Cards with JS overrides loaded: **{len(js_bodies)}** "
        f"(includes non-dream cards)\n"
        f"- Missing from yisim entirely: **{len(missing)}**\n"
        f"- Likely buggy / mismatched: **{len(buggy)}**\n"
        f"- Probably fine: **{len(fine)}**\n"
    )

    lines.append("\n---\n\n## Missing from yisim entirely\n")
    if missing:
        for m in missing:
            phs = game.get(m) or game.get(m.replace("·", "•")) or {"phases": []}
            sample = phs["phases"][0] if phs["phases"] else "(no text)"
            lines.append(f"- **{m}** ({len(phs['phases'])} phases) — sample: `{sample!r}`")
    else:
        lines.append("_(none)_")

    lines.append("\n\n## Likely buggy / mismatched (against card_actions.js)\n")
    if buggy:
        for name, base_id, problems in buggy:
            phs = game.get(name) or game.get(name.replace("·", "•")) or {"phases": []}
            lines.append(f"\n### {name}  ({base_id} family)")
            for ph, tpl in enumerate(phs["phases"], start=1):
                yid = f"{base_id[:-1]}{ph}"
                tag, src = yisim_repr_for_phase(base_id, ph)
                # Trim body for display
                disp = src.replace("\n", " ").strip()
                if len(disp) > 280:
                    disp = disp[:280] + "…"
                lines.append(f"- **phase {ph}** ({yid}, {tag})")
                lines.append(f"  - game: `{tpl}`")
                lines.append(f"  - yisim: `{disp}`")
            lines.append("\n  Flags:")
            for p in problems:
                lines.append(f"  - {p}")
    else:
        lines.append("_(none — every card with a heuristic match looks consistent)_")

    lines.append("\n\n## Probably fine\n")
    for name, base_id in fine:
        lines.append(f"- {name} ({base_id})")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT_MD} — missing={len(missing)} buggy={len(buggy)} fine={len(fine)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
