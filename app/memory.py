import json
import os
from copy import deepcopy
from datetime import datetime


DEFAULT_MEMORY = {
    "past_shifts": [],
    "recurring_sites": {},
    "escalations": [],
    "stats": {"total_shifts": 0, "total_srs": 0},
}


def _ensure_dir(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def load_memory(path):
    if not path:
        return deepcopy(DEFAULT_MEMORY)
    if not os.path.exists(path):
        return deepcopy(DEFAULT_MEMORY)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = deepcopy(DEFAULT_MEMORY)
    return data


def save_memory(path, memory):
    if not path:
        return False
    _ensure_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
    return True


def update_memory(memory, report, classifications, persistent_sites, stats):
    memory = memory or deepcopy(DEFAULT_MEMORY)

    memory["stats"]["total_shifts"] = int(memory["stats"].get("total_shifts", 0)) + 1
    memory["stats"]["total_srs"] = int(memory["stats"].get("total_srs", 0)) + int(
        stats.get("total", 0)
    )

    shift_record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "shift_id": report.get("shift_id"),
        "summary": report.get("summary"),
        "stats": stats,
    }
    memory.setdefault("past_shifts", []).append(shift_record)
    memory["past_shifts"] = memory["past_shifts"][-50:]

    for site in persistent_sites or []:
        memory.setdefault("recurring_sites", {})
        memory["recurring_sites"][site] = int(
            memory["recurring_sites"].get(site, 0)
        ) + 1

    for esc in classifications.get("escalations", []):
        memory.setdefault("escalations", []).append(esc)
    memory["escalations"] = memory["escalations"][-200:]

    return memory
