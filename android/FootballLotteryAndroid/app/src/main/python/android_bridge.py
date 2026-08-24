from __future__ import annotations

import json
import traceback
from pathlib import Path

from football_lottery_agent.standalone_api import (
    analysis_error_message,
    run_analysis,
    run_delete_history,
    run_foreign_odds_usage,
    run_health,
    run_history,
    run_review,
    run_send_feishu,
    run_single_prediction,
)


def health() -> str:
    return _json(run_health())


def analysis(payload_json: str, work_dir: str) -> str:
    try:
        return _json(run_analysis(json.loads(payload_json), work_dir))
    except Exception as exc:
        _write_analysis_error_log(work_dir)
        return _json({"ok": False, "error": analysis_error_message(exc)})


def _write_analysis_error_log(work_dir: str) -> None:
    """Persist the original Python traceback for local Android diagnostics."""
    try:
        report_dir = Path(work_dir) / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "last_analysis_error.log").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
    except Exception:
        # Diagnostics must never replace the user-facing analysis error.
        pass


def foreign_odds_usage(payload_json: str) -> str:
    return _json(run_foreign_odds_usage(json.loads(payload_json)))


def send_feishu(payload_json: str) -> str:
    return _json(run_send_feishu(json.loads(payload_json)))


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
