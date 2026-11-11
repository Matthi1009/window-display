"""Remember configurations per combination of connected monitors."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .hypr import Monitor, MonitorSpec

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "window-display"
PROFILES_FILE = CONFIG_DIR / "profiles.json"


def key_for(monitors: list[Monitor]) -> str:
    return "\n".join(sorted(m.ident for m in monitors))


def _load() -> dict:
    try:
        return json.loads(PROFILES_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _store(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".profiles-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PROFILES_FILE)


def save(monitors: list[Monitor], specs: list[MonitorSpec], preset: str | None = None) -> None:
    by_name = {m.name: m for m in monitors}
    entries = []
    for s in specs:
        m = by_name.get(s.output)
        if m is None:
            continue
        d = s.to_dict()
        d["output"] = m.ident
        if s.mirror in by_name:
            d["mirror"] = by_name[s.mirror].ident
        entries.append(d)
    data = _load()
    data[key_for(monitors)] = {
        "labels": [m.label for m in monitors],
        "preset": preset,
        "specs": entries,
    }
    _store(data)


def lookup(monitors: list[Monitor]) -> list[MonitorSpec] | None:
    entry = _load().get(key_for(monitors))
    if not entry:
        return None
    by_ident = {m.ident: m.name for m in monitors}
    specs = []
    for d in entry.get("specs", []):
        name = by_ident.get(d.get("output"))
        if name is None:
            return None
        d = dict(d, output=name)
        if d.get("mirror"):
            d["mirror"] = by_ident.get(d["mirror"], "")
        specs.append(MonitorSpec.from_dict(d))
    # Monitors without a stored spec (shouldn't happen) are left untouched.
    return specs or None


def forget(monitors: list[Monitor]) -> bool:
    data = _load()
    if data.pop(key_for(monitors), None) is None:
        return False
    _store(data)
    return True
