"""
Edit the 2026-06-03 19-26-55 game video: overlay each focus card image at its
first-board-placement moment with fade-in/out and a soft chime cue.

Output: <video_dir>/edited_2026-06-03.mp4

Usage:
  .venv/Scripts/python.exe tools/edit_video.py            # full render
  .venv/Scripts/python.exe tools/edit_video.py --preview  # 12s segment around the first two overlays

Design (professional editor pass):
  - Card overlay scaled to 480px tall (~2/3 of the 720px frame), aspect kept.
    Pinned right with an 80px margin and vertically centered — keeps it off
    the gameplay area on the left/center.
  - Soft drop-shadow: a blurred 60%-alpha black copy underneath, offset +10/+10.
  - Animation: 0.4s alpha fade-in, 3.0s hold, 0.6s alpha fade-out (3.8s total).
  - Chime: a pre-rendered 0.4s 880 Hz sine with quick decay, mixed at -10 dB
    so it's a "ting" cue, not an alarm. Original game audio stays primary.
  - Output: H.264 yuv420p (CRF 23, preset medium), AAC 192 kbps stereo, MP4.
"""

import argparse
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

FFMPEG = r"C:\Program Files\Krita (x64)\bin\ffmpeg.exe"
VIDEO_DIR = Path(r"C:\Users\raymo\OneDrive\Desktop\琴剑大师兄")
VIDEO_NAME = "2026-06-03 19-26-55.mkv"
OUT_NAME = "edited_2026-06-03.mp4"
CHIME_NAME = "chime_880hz.wav"

# (seconds_from_video_start, card_image_filename)
EVENTS = [
    (330,  "御灵心法.png"),
    (332,  "天灵曲.png"),
    (1666, "天音困仙.png"),
    (1695, "万法归灵剑.png"),
]

OVERLAY_HEIGHT = 480
RIGHT_MARGIN = 80
FADE_IN = 0.4
HOLD = 3.0
FADE_OUT = 0.6
TOTAL = FADE_IN + HOLD + FADE_OUT


def short_path(p) -> str:
    """Windows 8.3 short path so ffmpeg sidesteps CP1252 issues with CJK paths."""
    import ctypes
    GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
    GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    GetShortPathNameW.restype = ctypes.c_uint
    buf = ctypes.create_unicode_buffer(260)
    if GetShortPathNameW(str(p), buf, 260) == 0:
        return str(p)
    return buf.value


def make_chime(path: Path):
    """Generate a 0.9s soft bell-like cue: fundamental + a few inharmonic
    partials (bell-style ratios 2.0, 3.0, 4.2, 5.4), each with its own
    exponential decay. Bells with slightly inharmonic partials sound
    "magical / chime-like" rather than the harsh sine of a pure tone.
    16-bit PCM stereo at 48 kHz to match the game audio."""
    sr = 48000
    dur = 0.9
    n = int(sr * dur)
    fundamental = 660.0  # E5 — warm, not piercing
    partials = [
        (1.0,  0.50, 0.30),  # (ratio, amp, decay_seconds)
        (2.0,  0.30, 0.22),
        (3.0,  0.20, 0.18),
        (4.2,  0.12, 0.13),  # inharmonic — gives the "bell" shimmer
        (5.4,  0.08, 0.10),
    ]
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            t = i / sr
            attack = min(1.0, t / 0.008)  # 8ms attack — soft, not clicky
            mix = 0.0
            for ratio, amp, dec in partials:
                mix += amp * math.exp(-t / dec) * math.sin(2 * math.pi * fundamental * ratio * t)
            s = int(attack * mix * 0.55 * 32767)
            s = max(-32767, min(32767, s))
            frames += struct.pack("<hh", s, s)
        w.writeframes(bytes(frames))


def build_filtergraph(events):
    """Build the filter graph for the given events (list of (t, image_index)).
    `image_index` is the 1-based ffmpeg input slot of that card's PNG."""
    filters = []
    n = len(events)

    # Per-card: scale to height, then fade alpha in/out. Kept deliberately
    # simple — the earlier split + colorchannelmixer + blur shadow pipeline
    # was hiding the card on some renders. Alpha pass-through is the safest.
    for i, (t, img_idx) in enumerate(events):
        st_in = t
        st_out = t + FADE_IN + HOLD
        filters.append(
            f"[{img_idx}:v]format=yuva420p,scale=-1:{OVERLAY_HEIGHT},"
            f"fade=t=in:st={st_in}:d={FADE_IN}:alpha=1,"
            f"fade=t=out:st={st_out}:d={FADE_OUT}:alpha=1[c{i}]"
        )

    # Overlay chain: each card on top of the previous stage.
    chain = "[0:v]"
    for i, (t, _) in enumerate(events):
        en = f"between(t,{t},{t + TOTAL})"
        out = "[vout]" if i == n - 1 else f"[stg{i}]"
        filters.append(
            f"{chain}[c{i}]overlay=x=W-w-{RIGHT_MARGIN}:y=(H-h)/2:"
            f"enable='{en}'{out}"
        )
        chain = out

    return ";".join(filters)


def run(preview: bool):
    video_path = short_path(VIDEO_DIR / VIDEO_NAME)
    chime_path = VIDEO_DIR / CHIME_NAME
    if not chime_path.exists():
        print(f"Generating chime → {chime_path}")
        make_chime(chime_path)
    chime_path_s = short_path(chime_path)

    if preview:
        # 12s window starting just before the first card (R4 placements).
        seek = 326
        duration = 12
        seek_args = ["-ss", str(seek), "-t", str(duration)]
        # Shift event timestamps relative to the previewed segment.
        events_used = [
            (t - seek, i + 1)
            for i, (t, _) in enumerate(EVENTS)
            if seek <= t <= seek + duration - TOTAL
        ]
        out_name = "preview_2026-06-03.mp4"
    else:
        seek_args = []
        events_used = [(t, i + 1) for i, (t, _) in enumerate(EVENTS)]
        out_name = OUT_NAME

    if not events_used:
        print("No events fall within the preview window")
        sys.exit(1)

    out_path = short_path(VIDEO_DIR) + "\\" + out_name

    inputs = [*seek_args, "-i", video_path]
    for _, fname in EVENTS:
        inputs += ["-i", short_path(VIDEO_DIR / fname)]
    # One chime input per event with -itsoffset to time-align it.
    for t, _ in events_used:
        inputs += ["-itsoffset", f"{t:.3f}", "-i", chime_path_s]

    n = len(events_used)
    fc = build_filtergraph(events_used)
    # Audio mix: original at full weight, chimes at 0.35 each (~-9 dB).
    chime_labels = "".join(f"[{1 + len(EVENTS) + i}:a]" for i in range(n))
    weights = " ".join(["1.0"] + ["0.35"] * n)
    fc += (
        f";[0:a]{chime_labels}amix=inputs={n + 1}:duration=first:"
        f"dropout_transition=0:weights='{weights}'[aout]"
    )

    cmd = [
        FFMPEG, "-y", "-hide_banner",
        *inputs,
        "-filter_complex", fc,
        "-map", "[vout]", "-map", "[aout]",
        # Krita's bundled ffmpeg ships libopenh264 (libx264 is omitted). Quality
        # is comparable for gameplay content; bitrate-mode rather than CRF.
        "-c:v", "libopenh264", "-b:v", "4M",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    print(f"Output → {out_path}")
    print(f"Events:  {events_used}")
    print(f"Filter graph: {len(fc)} chars")
    p = subprocess.run(cmd)
    sys.exit(p.returncode)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="render a 12s preview segment")
    args = ap.parse_args()
    run(args.preview)
