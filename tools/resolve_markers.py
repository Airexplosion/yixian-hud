"""
DaVinci Resolve marker importer for the 2026-06-03 19:26:55 game video.

How to run:
  1. Open DaVinci Resolve.
  2. Open the project you want the markers in (or let this create a new one).
  3. Workspace -> Console -> Py3 tab.
  4. Paste the entire contents of this file into the console and press Enter.

What it does:
  - Imports the video file into the Media Pool.
  - Creates (or replaces) a timeline named "yixian 2026-06-03".
  - Drops a marker at every round start (R1..R19).
  - Drops emphasis markers (different color) at the first board appearance
    of each of the 4 focus cards: 御灵心法, 天灵曲, 天音困仙曲, 万法归灵剑.

Time anchor: user-observed video time 3:53 = clicking 剑不出鞘 fate
(SimpleClientPact frame#38 at UTC 02:30:48 = local 19:30:48).
Video start = 19:26:55 local. Offset = video_seconds = local_seconds - 19:26:55.
"""

VIDEO_PATH = r"C:\Users\raymo\OneDrive\Desktop\琴剑大师兄\2026-06-03 19-26-55.mkv"
TIMELINE_NAME = "yixian 2026-06-03"
DEFAULT_FPS = 30  # change if the source isn't 30 fps; Resolve overrides anyway

# Round-start video timestamps (seconds offset from video start).
# Derived from deck_tracker.jsonl UTC -> local (UTC-7) -> minus 19:26:55.
ROUND_STARTS = {
    1: 93,    # 1:33
    2: 149,   # 2:29
    3: 226,   # 3:46  <-- 3:53 anchor (fate pick) is mid-R3 prep
    4: 317,   # 5:17
    5: 400,   # 6:40
    6: 495,   # 8:15
    7: 595,   # 9:55
    8: 689,   # 11:29
    9: 796,   # 13:16
    10: 975,  # 16:15
    11: 1125, # 18:45
    12: 1300, # 21:40
    13: 1486, # 24:46
    14: 1651, # 27:31
    15: 1835, # 30:35
    16: 2046, # 34:06
    17: 2192, # 36:32
    18: 2388, # 39:48
    19: 2582, # 43:02
}

# Card highlight markers: (video_seconds, label).
CARD_MARKERS = [
    (330, "御灵心法 first placed (R4)"),
    (332, "天灵曲 first placed (R4)"),
    (1666, "天音困仙曲 first placed (R14)"),
    (1695, "万法归灵剑 first placed (R14)"),
]


def secs_to_frames(secs, fps):
    return int(round(secs * fps))


def main():
    # When running inside Resolve's Workspace > Console > Py3, the `resolve`
    # object is pre-populated as a global — no import needed. When running as
    # an external script, fall back to importing the bridge module (which
    # requires RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB env vars to be set).
    try:
        r = resolve  # noqa: F821 — global injected by Resolve's console
    except NameError:
        import DaVinciResolveScript as dvr_script
        r = dvr_script.scriptapp("Resolve")
    pm = r.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        project = pm.CreateProject("yixian-counter-game")
    fps = float(project.GetSetting("timelineFrameRate") or DEFAULT_FPS)

    mp = project.GetMediaPool()
    ms = r.GetMediaStorage()
    items = ms.AddItemListToMediaPool([VIDEO_PATH])
    if not items:
        # Already in pool — find by name.
        root = mp.GetRootFolder()
        for clip in root.GetClipList():
            if clip.GetClipProperty("File Path") == VIDEO_PATH:
                items = [clip]
                break
    if not items:
        raise RuntimeError("Could not import the video into the media pool")

    clip = items[0]

    # Replace existing timeline of the same name if present.
    existing = None
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        if tl.GetName() == TIMELINE_NAME:
            existing = tl
            break
    if existing:
        mp.DeleteTimelines([existing])

    timeline = mp.CreateTimelineFromClips(TIMELINE_NAME, [clip])
    if not timeline:
        raise RuntimeError("Could not create timeline")

    BLUE = "Blue"
    YELLOW = "Yellow"

    # Round start markers.
    for rn, secs in ROUND_STARTS.items():
        frame = secs_to_frames(secs, fps)
        timeline.AddMarker(frame, BLUE, f"R{rn} start", "", 1, "")

    # Card highlight markers.
    for secs, label in CARD_MARKERS:
        frame = secs_to_frames(secs, fps)
        timeline.AddMarker(frame, YELLOW, label, "", 1, "")

    print(f"Done. Timeline: {TIMELINE_NAME}, fps={fps}")
    print(f"  {len(ROUND_STARTS)} round-start markers (Blue)")
    print(f"  {len(CARD_MARKERS)} card-focus markers (Yellow)")


main()
