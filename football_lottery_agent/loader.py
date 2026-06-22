from __future__ import annotations

import json
from pathlib import Path

from .models import Issue


def load_issue(path: str | Path) -> Issue:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Issue.from_dict(raw)

