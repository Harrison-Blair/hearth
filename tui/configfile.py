"""Read/merge/write helpers for the app's ``config.yaml``.

The Config tab persists its fields here. Mirrors ``envfile.py``: pure functions
over a path, so they unit-test without a running app. Uses ``pyyaml`` (already a
dep), which does not preserve comments — a Save rewrites the file's scalars while
keeping every key, but loses the hand-written annotations.
"""

from __future__ import annotations

import yaml

CONFIG_FILE = "config.yaml"
DEFAULT_CONFIG_FILE = "default-config.yaml"


def read(path: str) -> dict:
    """Parsed yaml mapping, or {} if the file is missing/empty."""
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def write_fields(path: str, values: dict[tuple[str, ...], object]) -> None:
    """Merge dotted-key values into the existing yaml and write it back.

    Only the given keys are overwritten; every other key in the file is preserved.
    Intermediate maps are created as needed."""
    data = read(path)
    for key, value in values.items():
        node = data
        for part in key[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[key[-1]] = value
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
