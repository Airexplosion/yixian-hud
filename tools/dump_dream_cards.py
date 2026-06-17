"""
dump_dream_cards.py
────────────────────
One-shot extraction of every 梦• (dream) card's text template from the live
弈仙牌 (YiXianPai) install. Reads the Unity LZ4HC AssetBundle at
`…/YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/d12326b1….bundle`,
decompresses it, and dumps each card's per-phase text to
`tools/dream_cards_game.json`.

Why text-only (not numbers):
  The card-numeric parameters ({attack}, {anima}, {otherParams[N]}) live in a
  binary MonoBehaviour structure around each card-text run that we haven't
  fully reverse-engineered. Text templates alone are enough to verify yisim's
  ACTION STRUCTURE (atk vs def vs qi vs conditional agility etc.) which is
  the main source of bugs we've seen.

Usage:
  .venv/Scripts/python.exe tools/dump_dream_cards.py
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

try:
    import lz4.block  # noqa
except ImportError:
    sys.exit("lz4 not installed — run: .venv/Scripts/pip.exe install lz4")

BUNDLE = Path(
    r"C:/Program Files (x86)/Steam/steamapps/common/YiXianPai/"
    r"YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/"
    r"d12326b1fac5b42fbe559c812e236800.bundle"
)
OUT = Path(__file__).resolve().parent / "dream_cards_game.json"


def decompress_unity_bundle(path: Path) -> bytes:
    """Return the concatenated decompressed data of all blocks in a UnityFS bundle.
    Supports version-7+ headers with LZ4 / LZ4HC compression."""
    data = path.read_bytes()
    assert data[:8] == b"UnityFS\x00", f"not UnityFS: {data[:8]!r}"
    pos = 8
    version = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    # null-terminated unity_version + generator strings
    z = data.index(b"\x00", pos)
    pos = z + 1
    z = data.index(b"\x00", pos)
    pos = z + 1
    bundle_size = struct.unpack_from(">q", data, pos)[0]
    pos += 8
    ci_c = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    ci_u = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    flags = struct.unpack_from(">I", data, pos)[0]
    pos += 4
    if version >= 7:
        pos = (pos + 15) & ~15
    blockinfo_at_end = bool(flags & 0x80)
    ci_pos = bundle_size - ci_c if blockinfo_at_end else pos
    ci = data[ci_pos:ci_pos + ci_c]
    ctype = flags & 0x3F
    if ctype in (2, 3):  # LZ4 / LZ4HC
        bi = lz4.block.decompress(ci, uncompressed_size=ci_u)
    elif ctype == 0:
        bi = ci
    else:
        raise NotImplementedError(f"unsupported blockinfo compression {ctype}")
    # blockinfo: 16-byte data hash + uint32 n_blocks + (u32 unc, u32 comp, u16 flags)*n
    p = 16
    n_blocks = struct.unpack_from(">I", bi, p)[0]
    p += 4
    blocks = []
    for _ in range(n_blocks):
        u = struct.unpack_from(">I", bi, p)[0]; p += 4
        c = struct.unpack_from(">I", bi, p)[0]; p += 4
        f_ = struct.unpack_from(">H", bi, p)[0]; p += 2
        blocks.append((u, c, f_))
    block_start = pos if blockinfo_at_end else pos + ci_c
    out = bytearray()
    bp = block_start
    for u, c, f_ in blocks:
        chunk = data[bp:bp + c]
        ct = f_ & 0x3F
        if ct in (2, 3):
            dec = lz4.block.decompress(chunk, uncompressed_size=u)
        elif ct == 0:
            dec = chunk
        else:
            raise NotImplementedError(f"unsupported block compression {ct}")
        out.extend(dec)
        bp += c
    return bytes(out)


# A run of CJK + ASCII (incl. [], {}, +, \n, digits, < > = ) plus CJK
# punctuation (3000-303F) and full-width forms (FF00-FFEF, includes ：；！？
# etc.) — terminating at the first NUL or non-readable byte. The card-text
# template is right after the card-name string in the bundle.
_TPL_CHARS = re.compile(
    r"["
    r"一-鿿"          # CJK Unified Ideographs
    r"　-〿"  # CJK Symbols and Punctuation (： uses full-width below)
    r"＀-￯"  # Halfwidth/Fullwidth Forms (：；！？，。etc.)
    r"A-Za-z0-9"
    r"\[\]\{\}<>=+\-/\\\n\t .,()×%≤≥"
    r"]"
)


def carve_template(blob: bytes, name_end: int, max_bytes: int = 600) -> str:
    """Starting at `name_end` (byte offset just AFTER a card-name string in
    the blob), advance past the small binary separator between name and text
    (length-prefix + a couple type tags), then read the next UTF-8 readable
    run as the effect template."""
    # Skip up to 16 bytes of binary chatter to find where the text starts.
    end_search = min(name_end + 16, len(blob))
    text_start = None
    for i in range(name_end, end_search):
        b = blob[i]
        # First text byte: high-bit (UTF-8 continuation start) or '{' / '['
        if b in (0x7B, 0x5B) or 0xE0 <= b <= 0xEF:
            text_start = i
            break
    if text_start is None:
        return ""
    # Read until we hit non-template bytes (control characters that aren't
    # \n or \t, or a long binary run).
    out = bytearray()
    i = text_start
    end = min(text_start + max_bytes, len(blob))
    while i < end:
        b = blob[i]
        if b == 0x00:
            break
        # Decode one UTF-8 codepoint
        if b < 0x80:
            ch = chr(b)
            n = 1
        elif 0xC0 <= b < 0xE0:
            ch = blob[i:i + 2].decode("utf-8", errors="replace")
            n = 2
        elif 0xE0 <= b < 0xF0:
            ch = blob[i:i + 3].decode("utf-8", errors="replace")
            n = 3
        else:
            break
        if not _TPL_CHARS.match(ch):
            break
        out.extend(blob[i:i + n])
        i += n
    return out.decode("utf-8", errors="replace").strip()


# Match: 梦 (UTF-8 E6 A2 A6) + (• as E2 80 A2  OR  · as C2 B7) + 2+ CJK chars.
# CJK in UTF-8: leading byte 0xE4–0xE9 followed by two 0x80–0xBF bytes.
CARD_NAME_PAT = re.compile(
    rb"\xe6\xa2\xa6(?:\xe2\x80\xa2|\xc2\xb7)"          # 梦 + (• | ·)
    rb"(?:[\xe4-\xe9][\x80-\xbf][\x80-\xbf]){2,8}"      # 2..8 CJK chars
)


def main() -> int:
    print(f"reading {BUNDLE}", file=sys.stderr)
    blob = decompress_unity_bundle(BUNDLE)
    print(f"decompressed {len(blob):,} bytes", file=sys.stderr)

    # Find every card-name occurrence. Each card has 5 phases → 5 hits.
    hits: dict[str, list[tuple[int, str]]] = {}
    for m in CARD_NAME_PAT.finditer(blob):
        name = m.group(0).decode("utf-8")
        # Normalize • to · for consistent grouping (yisim does the same).
        canon = name.replace("•", "·")
        tpl = carve_template(blob, m.end())
        hits.setdefault(canon, []).append((m.start(), tpl))

    # Sort each card's hits by offset (the bundle's order) and dedup templates
    # while preserving order — phases 1..N appear consecutively.
    result: dict[str, dict] = {}
    for canon, occs in sorted(hits.items()):
        occs.sort(key=lambda x: x[0])
        # Phase templates: keep duplicates so phase count = #occurrences.
        templates = [t for _, t in occs]
        # If all five phases share the same template (e.g. lv1=lv2=lv3 simple
        # cards), they'll appear identical — that's fine, the user will see
        # the repetition and know the numbers vary per phase.
        result[canon] = {
            "phases": templates,
            "phase_count": len(templates),
        }

    OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"wrote {OUT} — {len(result)} unique 梦 cards, "
        f"{sum(v['phase_count'] for v in result.values())} phase entries",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
