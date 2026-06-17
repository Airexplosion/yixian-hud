import re
import blackboxprotobuf
import msgpack

# Chinese character range + common card punctuation (dot, middot, dream prefix)
_CHINESE_RE = re.compile(r'[一-鿿㐀-䶿•·]{2,}[一-鿿㐀-䶿•·\w\s]*')

# Colyseus protocol type byte names (from Colyseus SDK source)
_COLYSEUS_TYPES = {
    0x00: "Handshake",
    0x01: "JoinRoom",
    0x02: "JoinError",
    0x03: "LeaveRoom",
    0x08: "RoomData",
    0x09: "RoomDataCustom",
    0x0a: "FullRoomState",
    0x0b: "RoomStatePatch",
    0x0c: "Ping",
    0x0d: "RoomMessage",
    0x0e: "RoomDataSchema",
}

def extract_strings(raw: bytes) -> list:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return []
    return [m.strip() for m in _CHINESE_RE.findall(text) if len(m.strip()) >= 2]

def decode_protobuf(raw: bytes):
    try:
        msg, _ = blackboxprotobuf.decode_message(raw)
        return msg
    except Exception:
        return None

def decode_msgpack_stream(raw: bytes):
    """Read all consecutive msgpack values from raw bytes using a streaming unpacker."""
    try:
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        unpacker.feed(raw)
        values = list(unpacker)
        if not values:
            return None
        return values[0] if len(values) == 1 else values
    except Exception:
        return None

def _make_serializable(obj):
    """Recursively convert bytes keys/values to strings so json.dumps won't fail."""
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return obj.hex()
    if isinstance(obj, dict):
        return {_make_serializable(k): _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(i) for i in obj]
    return obj

def decode_frame(raw: bytes) -> dict:
    """Best-effort decode of a WebSocket binary frame."""
    result = {
        "raw_len": len(raw),
        "raw_hex_prefix": raw[:16].hex()
    }

    if len(raw) == 0:
        return result

    # Colyseus frames: first byte is message type, rest is msgpack stream
    type_byte = raw[0]
    result["colyseus_type"] = _COLYSEUS_TYPES.get(type_byte, f"0x{type_byte:02x}")

    # Schema-encoded frames (ROOM_STATE / ROOM_STATE_PATCH) use the
    # @colyseus/schema binary format, NOT msgpack. Don't attempt msgpack on
    # these — let the caller capture them as ws_undecoded with full raw bytes
    # for later schema-aware decoding. NOTE: only 0x0e (and likely 0x0f for
    # patches) are confirmed schema; 0x0b is custom msgpack room-data in
    # current Colyseus, so we explicitly do NOT include it.
    _SCHEMA_OPCODES = {0x0e, 0x0f}
    if type_byte in _SCHEMA_OPCODES:
        return result

    if len(raw) > 1:
        mp = decode_msgpack_stream(raw[1:])
        if mp is not None:
            result["msgpack"] = _make_serializable(mp)

    # Fallback: try protobuf on full frame
    if "msgpack" not in result:
        pb = decode_protobuf(raw)
        if pb:
            result["protobuf"] = _make_serializable(pb)

    # Always extract readable Chinese strings
    strings = extract_strings(raw)
    if strings:
        result["strings"] = strings

    return result
