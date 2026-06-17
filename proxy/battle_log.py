"""
battle_log.py
─────────────
Fallback source for HP / tipo / maxTipo from the local game's BattleLog.json
file (Unity-style player data at AppData\\LocalLow\\DarkSunStudio\\YiXianPai).

The wire protocol doesn't carry pre-battle HP or current/max tipo as direct
integers — those values are computed client-side from base + xiuwei + class
tables. The game's own client writes them to BattleLog.json at the start of
each round, which gives us an authoritative (if slightly delayed) source.

File format
-----------
JSON Lines. First line is a numeric session id we ignore. Each subsequent
line is `{"round": N, "players": [{<player>, …}]}` where each player has:
  - `username` (utf-8 Chinese display name; matches protobuf p[2] bytes)
  - `life`     (current 命元 / destiny resource, starts at 100)
  - `exp`      (xiuwei 修为)
  - `tiPo`     (current tipo 体魄, dynamic during play)
  - `maxTiPo`  (max tipo)
  - `maxHp`    (max battle HP — what the user wanted)
  - `level`    (realm tier 1..5)
  - `opponentUsername`, `usedCards`, …

Caveats
-------
- The file is sometimes slow to update (game writes lazily). Treat values
  as a HINT, not ground truth — always fall back to wire-derived values if
  the log is stale or missing the current round.
- Some entries have the username key typo'd as `userxname` (observed in
  the 2026-05-27 capture). We handle both keys.
- The reader re-parses the file when its mtime changes; cheap enough to
  call once per view-model build.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


DEFAULT_PATH = Path(
    os.path.expandvars(r"%LOCALAPPDATA%\..\LocalLow\DarkSunStudio\YiXianPai\BattleLog.json")
).resolve()


class BattleLogReader:
    """Tail-style reader for BattleLog.json with mtime-based refresh."""

    def __init__(self, path: Optional[Path] = None):
        self.path: Path = Path(path) if path else DEFAULT_PATH
        self._cache: dict[tuple[int, str], dict] = {}
        self._mtime: float = 0.0
        self._latest_round: int = 0
        self._last_error: Optional[str] = None

    @property
    def latest_round(self) -> int:
        return self._latest_round

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def refresh(self) -> bool:
        """Re-read the file if mtime changed. Returns True iff cache was updated."""
        if not self.path.exists():
            self._last_error = f"not found: {self.path}"
            return False
        try:
            mtime = self.path.stat().st_mtime
        except OSError as e:
            self._last_error = f"stat failed: {e}"
            return False
        if mtime == self._mtime and self._cache:
            return False
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            self._last_error = f"read failed: {e}"
            return False
        new_cache: dict[tuple[int, str], dict] = {}
        latest = 0
        # First line is the session id (an integer); subsequent lines are
        # round JSON objects. Be lenient: skip any non-JSON line silently.
        for line in text.splitlines():
            line = line.strip()
            if not line or line[0] != "{":
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            r = rec.get("round")
            if not isinstance(r, int):
                continue
            latest = max(latest, r)
            for p in rec.get("players", []):
                if not isinstance(p, dict):
                    continue
                # The game has been observed to typo `username` as `userxname`
                # on some entries. Accept either to be safe.
                uname = p.get("username") or p.get("userxname")
                if not uname:
                    continue
                new_cache[(r, uname)] = p
        self._cache = new_cache
        self._mtime = mtime
        self._latest_round = latest
        self._last_error = None
        return True

    def lookup(self, round_num: int, username: str) -> Optional[dict]:
        """Per-player record for (round, username).

        Falls back to the most recent round ≤ requested round for that
        username if the exact round isn't in the file yet — the log is
        slower than the wire, so an opponent's data for the upcoming round
        is often only stamped after the round actually starts.
        Returns None when the username has no records at all.
        """
        self.refresh()
        if not username:
            return None
        key = (round_num, username)
        if key in self._cache:
            return self._cache[key]
        # Fallback: walk backwards from requested round
        best_round = -1
        for (rr, uu) in self._cache:
            if uu == username and rr <= round_num and rr > best_round:
                best_round = rr
        if best_round < 0:
            return None
        return self._cache[(best_round, username)]

    def extract_stats(self, round_num: int, username: str) -> Optional[dict]:
        """Return the four stat fields the parser cares about, or None.

        Output: `{life, xiuwei, tipo, max_tipo, max_hp, realm_tier,
                 from_round}` — `from_round` is the round number the data
        was actually read from (may differ from the requested round if we
        had to fall back).
        """
        rec = self.lookup(round_num, username)
        if not rec:
            return None
        return {
            "life":       int(rec.get("life", 0) or 0),
            "xiuwei":     int(rec.get("exp", 0) or 0),
            "tipo":       int(rec.get("tiPo", 0) or 0),
            "max_tipo":   int(rec.get("maxTiPo", 0) or 0),
            "max_hp":     int(rec.get("maxHp", 0) or 0),
            "realm_tier": int(rec.get("level", 1) or 1),
            "from_round": int(rec.get("round", round_num) or round_num),
        }


# Module-level singleton; lazily instantiated.
_singleton: Optional[BattleLogReader] = None


def get_reader() -> BattleLogReader:
    global _singleton
    if _singleton is None:
        _singleton = BattleLogReader()
    return _singleton
