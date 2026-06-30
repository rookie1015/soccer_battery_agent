from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def loads_json(text: str) -> Any:
    return json.loads(text.lstrip("\ufeff"))


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
