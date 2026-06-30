from __future__ import annotations

from pathlib import Path

from .json_utils import read_json
from .models import Issue


def load_issue(path: str | Path) -> Issue:
    raw = read_json(path)
    return Issue.from_dict(raw)
