from __future__ import annotations

import json

from football_lottery_agent.standalone_api import (
    run_analysis,
    run_health,
    run_history,
    run_single_prediction,
)


def health() -> str:
    return _json(run_health())


def analysis(payload_json: str, work_dir: str) -> str:
    return _json(run_analysis(json.loads(payload_json), work_dir))


def history(work_dir: str) -> str:
    return _json(run_history(work_dir))


def single_prediction(payload_json: str, work_dir: str) -> str:
    return _json(run_single_prediction(json.loads(payload_json), work_dir))


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)
