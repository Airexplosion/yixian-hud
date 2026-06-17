import json
from pathlib import Path

def load_card_names(lib_paths: list) -> set:
    names = set()
    for p in lib_paths:
        path = Path(p)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and "name" in entry:
                        names.add(entry["name"])
            elif isinstance(data, dict):
                for entry in data.values():
                    if isinstance(entry, dict) and "name" in entry:
                        names.add(entry["name"])
    return names

# CARD_NAMES = load_card_names(["card_lib.json", "seasonal_card_lib.json"])
