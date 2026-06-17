"""
verify_all_battle_logs.py
─────────────────────────
Batch-run verify_damage.py over every battle_log/<timestamp>/ folder that
has a non-empty battle_log.json (i.e. games where the BL captured at least
one round of authoritative HP/maxHp/tipo data). Skips empty captures.

For each game, runs the existing verify_damage.py and parses the per-round
match table from its output. Then aggregates a master summary across all
games: per-game match rate + overall match rate + which rounds mismatched.

Output:
  - stdout: per-game summary + aggregate
  - tools/verify_all_battle_logs.md — saved report
  - Each game's own report still lands at tools/verify_<timestamp>.md
    (produced by verify_damage.py as usual)

Usage:
  .venv/Scripts/python.exe tools/verify_all_battle_logs.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATTLE_LOG_DIR = ROOT / "battle_log"
VERIFY_SCRIPT = Path(__file__).parent / "verify_damage.py"
REPORT_OUT = Path(__file__).parent / "verify_all_battle_logs.md"

# Match the table rows from verify_damage's markdown output. Format is:
#   | R3 | 文赐 | win | 27 | 29 | -2 | ✗ |  |
ROW_RE = re.compile(
    r"^\|\s*R(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(-?\d+|—)\s*\|"
    r"\s*(-?\d+|—)\s*\|\s*(-?\d+|—|[+-]\d+)\s*\|\s*([✓✗]|\s*)\s*\|"
    r"\s*(🎲|\s*)\s*\|$"
)
SUMMARY_RE = re.compile(r"\*\*Exact ΔHP match: (\d+)/(\d+) \(\d+%\)\*\*")
ERROR_RE = re.compile(r"\*\*Mean abs error: ([\d.]+)\*\*")


def bl_has_data(folder: Path) -> int:
    """Return the number of round entries in battle_log.json (0 if missing/empty)."""
    bl = folder / "battle_log.json"
    if not bl.exists() or bl.stat().st_size == 0:
        return 0
    try:
        text = bl.read_text(encoding="utf-8")
    except Exception:
        return 0
    n = 0
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            n += 1
    return n


def msgdump_round_count(folder: Path) -> int:
    """Count GameStatus round numbers in msgdump.jsonl (rough heuristic for
    total game rounds — actual extract_rounds may give a slightly different
    number but this is fast and good enough for the coverage check)."""
    md = folder / "msgdump.jsonl"
    if not md.exists():
        return 0
    rounds_seen: set[int] = set()
    import json as _json
    import base64 as _b64
    try:
        import blackboxprotobuf as _bbp
    except Exception:
        return 0
    try:
        with md.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = _json.loads(line)
                except Exception:
                    continue
                if e.get("type") != "ws_frame":
                    continue
                mp = (e.get("decoded") or {}).get("msgpack")
                if not (isinstance(mp, list) and len(mp) >= 2 and isinstance(mp[1], dict)):
                    continue
                if mp[1].get("type") != "GameStatus":
                    continue
                data_b64 = mp[1].get("data")
                if not data_b64:
                    continue
                try:
                    pb, _ = _bbp.decode_message(_b64.b64decode(data_b64))
                except Exception:
                    continue
                rn = pb.get("1")
                if isinstance(rn, int) and rn > 0:
                    rounds_seen.add(rn)
    except Exception:
        return 0
    return len(rounds_seen)


# Minimum BL coverage to include a game in verify: BL must cover at least
# this fraction of msgdump's rounds. Below this we can't trust OPP's HP
# (HP isn't on the wire — falls back to a formula that's often wrong for
# OPPs whose progression deviates from the standard pattern).
MIN_BL_COVERAGE = 0.75


def run_verify(folder: Path) -> tuple[str, list[dict], int, int, float]:
    """Run verify_damage.py on `folder` and return:
      (stdout_text, rows, matched, total, mean_err)
    where `rows` is a list of {round, opp, yisim_out, yisim_hp, actual_hp,
    diff, match, rng}.
    """
    cmd = [sys.executable, "-X", "utf8", str(VERIFY_SCRIPT), str(folder)]
    res = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    out = res.stdout + "\n" + res.stderr
    rows: list[dict] = []
    for line in out.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        rows.append({
            "round": int(m.group(1)),
            "opp": m.group(2),
            "yisim_out": m.group(3),
            "yisim_hp": m.group(4),
            "actual_hp": m.group(5),
            "diff": m.group(6),
            "match": m.group(7).strip() == "✓",
            "rng": m.group(8).strip() == "🎲",
        })
    matched = total = 0
    mean_err = 0.0
    if (m := SUMMARY_RE.search(out)):
        matched, total = int(m.group(1)), int(m.group(2))
    if (m := ERROR_RE.search(out)):
        mean_err = float(m.group(1))
    return out, rows, matched, total, mean_err


def main() -> int:
    if not BATTLE_LOG_DIR.is_dir():
        print(f"No battle_log folder at {BATTLE_LOG_DIR}", file=sys.stderr)
        return 2
    folders = sorted(p for p in BATTLE_LOG_DIR.iterdir() if p.is_dir())
    # Filter: require BL to cover at least MIN_BL_COVERAGE of msgdump rounds.
    # Without enough BL coverage, OPP HP comes from a fragile formula and
    # the verify diff becomes uninformative.
    candidates = []
    skipped_partial = []
    for p in folders:
        bl_rounds = bl_has_data(p)
        if bl_rounds == 0:
            continue
        total_rounds = msgdump_round_count(p)
        if total_rounds == 0:
            continue
        coverage = bl_rounds / total_rounds
        if coverage < MIN_BL_COVERAGE:
            skipped_partial.append((p.name, bl_rounds, total_rounds, coverage))
            continue
        candidates.append((p, bl_rounds))
    eligible = candidates

    print(f"Found {len(folders)} battle_log folders, "
          f"{len(eligible)} with full BL coverage (≥{int(MIN_BL_COVERAGE*100)}%).")
    if skipped_partial:
        print(f"Skipped {len(skipped_partial)} games with partial BL coverage:")
        for name, br, tr, cov in skipped_partial:
            print(f"  {name}: BL has {br}/{tr} rounds ({int(cov*100)}%)")
    print()
    if not eligible:
        print("No games have battle_log data. Capture a game with YX_DEBUG=1 first.")
        return 1

    # Per-game results
    per_game: list[dict] = []
    for folder, bl_rounds in eligible:
        name = folder.name
        print(f"--- {name} ({bl_rounds} BL rounds)")
        try:
            _out, rows, matched, total, mean_err = run_verify(folder)
        except Exception as e:
            print(f"    FAILED: {e}")
            continue
        if total == 0:
            print(f"    skipped: no comparison rows in output")
            continue
        mismatch_rounds = [r for r in rows if not r["match"]]
        print(f"    Exact match: {matched}/{total} ({matched*100//total}%) · "
              f"mean abs err: {mean_err:.1f} · "
              f"mismatches: {len(mismatch_rounds)}")
        per_game.append({
            "name": name, "bl_rounds": bl_rounds,
            "matched": matched, "total": total,
            "mean_err": mean_err, "rows": rows,
        })

    if not per_game:
        print("\nNo games produced a comparison.")
        return 1

    # Aggregate
    total_matched = sum(g["matched"] for g in per_game)
    total_rounds = sum(g["total"] for g in per_game)
    overall_err = sum(g["mean_err"] * g["total"] for g in per_game) / max(1, total_rounds)

    print()
    print(f"=== Overall ===")
    print(f"Games: {len(per_game)}")
    print(f"Rounds compared: {total_rounds}")
    print(f"Exact ΔHP match: {total_matched}/{total_rounds} "
          f"({total_matched*100//total_rounds if total_rounds else 0}%)")
    print(f"Weighted mean abs error: {overall_err:.2f}")

    # Write master report
    lines: list[str] = []
    lines.append("# Damage Verification — All Games with BattleLog")
    lines.append("")
    lines.append(f"Aggregate across **{len(per_game)} games** "
                 f"with non-empty `battle_log.json`.")
    lines.append("")
    lines.append("## Per-game summary")
    lines.append("")
    lines.append("| Game | BL rounds | Compared | Exact match | Mean err | Mismatch rounds |")
    lines.append("|---|---:|---:|---|---:|---|")
    for g in per_game:
        mismatch_rs = [f"R{r['round']}" for r in g["rows"] if not r["match"]]
        mm_str = ", ".join(mismatch_rs) if mismatch_rs else "—"
        pct = g["matched"] * 100 // g["total"] if g["total"] else 0
        lines.append(f"| `{g['name']}` | {g['bl_rounds']} | {g['total']} | "
                     f"{g['matched']}/{g['total']} ({pct}%) | {g['mean_err']:.1f} | "
                     f"{mm_str} |")
    lines.append("")
    lines.append(f"**Total: {total_matched}/{total_rounds} rounds match "
                 f"({total_matched*100//total_rounds if total_rounds else 0}%) "
                 f"· weighted mean abs error: {overall_err:.2f}**")
    lines.append("")
    lines.append("## Per-round detail (only mismatched rounds)")
    lines.append("")
    lines.append("| Game | R | Opp | yisim out | yisim ΔHP | actual ΔHP | diff | RNG |")
    lines.append("|---|---:|---|---|---:|---:|---:|:---:|")
    any_mismatch = False
    for g in per_game:
        for r in g["rows"]:
            if r["match"]:
                continue
            any_mismatch = True
            lines.append(f"| `{g['name']}` | R{r['round']} | {r['opp']} | "
                         f"{r['yisim_out']} | {r['yisim_hp']} | {r['actual_hp']} | "
                         f"{r['diff']} | {'🎲' if r['rng'] else ''} |")
    if not any_mismatch:
        lines.append("| — | — | — | — | — | — | — | — |")
        lines.append("")
        lines.append("_All rounds matched! 🎉_")
    lines.append("")
    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nMaster report: {REPORT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
