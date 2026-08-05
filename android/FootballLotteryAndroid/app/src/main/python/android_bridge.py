from __future__ import annotations

import json

from football_lottery_agent.standalone_api import (
    run_analysis,
    run_delete_history,
    run_foreign_odds_usage,
    run_health,
    run_history,
    run_review,
    run_single_prediction,
)


def health() -> str:
    return _json(run_health())


def analysis(payload_json: str, work_dir: str) -> str:
    return _json(run_analysis(json.loads(payload_json), work_dir))


def foreign_odds_usage(payload_json: str) -> str:
    return _json(run_foreign_odds_usage(json.loads(payload_json)))


def history(work_dir: str) -> str:
    return _json(run_history(work_dir))


def delete_history(payload_json: str, work_dir: str) -> str:
    return _json(run_delete_history(json.loads(payload_json), work_dir))


def review(payload_json: str, work_dir: str) -> str:
    return _json(run_review(json.loads(payload_json), work_dir))


def single_prediction(payload_json: str, work_dir: str) -> str:
    return _json(run_single_prediction(json.loads(payload_json), work_dir))


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)
