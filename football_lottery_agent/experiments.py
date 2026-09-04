from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .calibration import DEFAULT_WEIGHTS, CalibrationSample, fit_weights
from .dixon_coles import forecast as dixon_coles_forecast
from .draw_calibration import (
    DEFAULT_DRAW_CALIBRATION_COEFFICIENTS,
    build_draw_calibration_profile,
    draw_calibration_corrections_from_features,
    fit_draw_calibration_coefficients,
    valid_draw_calibration_coefficients,
)
from .fundamentals import (
    DEFAULT_FUNDAMENTAL_COEFFICIENTS,
    apply_logit_corrections,
    build_fundamental_profile,
    fit_fundamental_coefficients,
    mathematical_corrections,
    predict_with_fundamental_coefficients,
    valid_fundamental_coefficients,
)
from .history import load_history_entries
from .loader import load_issue
from .models import Match
from .predictor import DEFAULT_SELECTION_POLICY, _odds_to_probabilities, _select_picks, _signal_scores


OUTCOMES = ("3", "1", "0")
MODEL_VERSION = "market-residual-1x2-v5"
SNAPSHOT_SCHEMA_VERSION = "1"
DEFAULT_MIN_TRAIN_MATCHES = 84
DEFAULT_MIN_TEST_MATCHES = 84
DEFAULT_MIN_TEST_ISSUES = 6
DEFAULT_MIN_BRIER_GAIN = 0.002
UPSET_MARKET_PROBABILITY = 0.25

STATIC_MODELS = {
    "odds_only": {"odds": 1.0, "signals": 0.0, "dixon_coles": 0.0},
    "signals_only": {"odds": 0.0, "signals": 1.0, "dixon_coles": 0.0},
    "dixon_coles_only": {"odds": 0.0, "signals": 0.0, "dixon_coles": 1.0},
    "production_default": DEFAULT_WEIGHTS,
}


@dataclass(frozen=True)
class ExperimentSample:
    issue: str
    seq: int
    kickoff: datetime
    league: str
    outcome: str
    components: dict[str, dict[str, float]]
    data_quality: str
    snapshot_status: str
    fundamental_features: dict[str, float] = field(default_factory=dict)
    data_quality_score: float = 0.0
    draw_calibration_features: dict[str, float] = field(default_factory=dict)
    draw_calibration_available: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionRecord:
    sample: ExperimentSample
    probabilities: dict[str, float]


def build_current_model_status(work_dir: str | Path) -> dict[str, Any]:
    """Return production-facing status for the current experiment architecture.

    Older releases displayed the result of ``calibration.py``'s linear blend
    beside predictions produced by the residual model.  Apart from giving the
    same weights two different meanings, that allowed a stale v1 experiment
    report to look like evidence for v2.  The production status now comes from
    the same versioned walk-forward experiment which owns model promotion.

    A missing report, a report from another model version, or a review newer
    than the report is refreshed without promotion.  Promotion remains an
    explicit action and still has to pass every out-of-sample gate.
    """
    root = Path(work_dir)
    latest_path = root / "reports" / "experiments" / "latest.json"
    payload = _read_experiment_payload(latest_path)
    refresh_reason = _experiment_refresh_reason(root, latest_path, payload)
    if refresh_reason:
        try:
            payload = run_experiment(root, promote=False)
        except Exception as exc:
            return {
                "status": "experiment_refresh_error",
                "model_version": MODEL_VERSION,
                "sample_count": 0,
                "minimum_samples": DEFAULT_MIN_TRAIN_MATCHES + DEFAULT_MIN_TEST_MATCHES,
                "minimum_train_samples": DEFAULT_MIN_TRAIN_MATCHES,
                "minimum_test_samples": DEFAULT_MIN_TEST_MATCHES,
                "minimum_test_issues": DEFAULT_MIN_TEST_ISSUES,
                "test_matches": 0,
                "test_issues": 0,
                "weights": dict(DEFAULT_WEIGHTS),
                "message": f"当前模型回测刷新失败，继续使用默认参数：{exc}",
                "refresh_reason": refresh_reason,
            }

    if not isinstance(payload, dict):
        payload = {}
    audit = ((payload.get("dataset") or {}).get("audit") or {})
    strict = payload.get("strict") or {}
    walk = strict.get("walk_forward") or {}
    promotion = payload.get("promotion") or {}
    active_weights = load_active_model_weights(root)
    promotion_status = str(promotion.get("status") or "collecting")
    if active_weights is not None:
        status = "experiment_active"
        weights = active_weights
        message = "当前残差模型参数已通过严格赛前、按期走步回测的晋级门槛。"
    else:
        status = {
            "eligible": "experiment_eligible",
            "hold": "experiment_pending_gate",
        }.get(promotion_status, "collecting")
        weights = dict(DEFAULT_WEIGHTS)
        message = str(
            promotion.get("message")
            or "严格赛前样本不足，当前残差模型继续使用默认修正强度。"
        )
    return {
        "status": status,
        "model_version": MODEL_VERSION,
        "experiment_id": str(payload.get("experiment_id") or ""),
        "sample_count": int(audit.get("strict_sample_count") or strict.get("sample_count") or 0),
        # Passing the production gate requires both the initial training window
        # and a genuinely unseen test window.  Reporting only 84 here made the
        # old UI imply that fitting alone was enough.
        "minimum_samples": DEFAULT_MIN_TRAIN_MATCHES + DEFAULT_MIN_TEST_MATCHES,
        "minimum_train_samples": DEFAULT_MIN_TRAIN_MATCHES,
        "minimum_test_samples": DEFAULT_MIN_TEST_MATCHES,
        "minimum_test_issues": DEFAULT_MIN_TEST_ISSUES,
        "test_matches": int(walk.get("test_matches") or 0),
        "test_issues": int(walk.get("test_issues") or 0),
        "weights": weights,
        "message": message,
        "refresh_reason": refresh_reason or "current",
    }


def _read_experiment_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _experiment_refresh_reason(
    root: Path,
    latest_path: Path,
    payload: dict[str, Any] | None,
) -> str:
    if payload is None:
        return "missing_or_invalid_latest_experiment"
    if payload.get("model_version") != MODEL_VERSION:
        return "model_version_changed"
    try:
        experiment_mtime = latest_path.stat().st_mtime_ns
    except OSError:
        return "missing_or_invalid_latest_experiment"
    history_dir = root / "reports" / "history"
    for entry in load_history_entries(history_dir):
        if entry.get("kind") != "review":
            continue
        for field in ("markdown", "snapshot"):
            relative = str(entry.get(field) or "").strip()
            if not relative:
                continue
            review_path = history_dir / relative
            try:
                if review_path.stat().st_mtime_ns > experiment_mtime:
                    return "review_data_changed"
            except OSError:
                continue
    return ""


def run_experiment(
    work_dir: str | Path,
    output_dir: str | Path | None = None,
    *,
    min_train_matches: int = DEFAULT_MIN_TRAIN_MATCHES,
    min_test_matches: int = DEFAULT_MIN_TEST_MATCHES,
    min_test_issues: int = DEFAULT_MIN_TEST_ISSUES,
    min_brier_gain: float = DEFAULT_MIN_BRIER_GAIN,
    promote: bool = False,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    root = Path(work_dir)
    samples, audit = load_experiment_samples(root)
    strict = [sample for sample in samples if sample.snapshot_status == "verified_pre_match"]
    exploratory = [sample for sample in samples if sample.snapshot_status != "post_kickoff_excluded"]
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    experiment_id = f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{MODEL_VERSION}"

    strict_track = evaluate_track(strict, min_train_matches=min_train_matches)
    exploratory_track = evaluate_track(exploratory, min_train_matches=min_train_matches)
    promotion = _promotion_decision(
        strict_track,
        min_test_matches=min_test_matches,
        min_test_issues=min_test_issues,
        min_brier_gain=min_brier_gain,
    )
    ticket_strategy = evaluate_ticket_strategy(strict)
    if ticket_strategy["status"] == "evaluated":
        gate = {
            "name": "选项策略样本外效率",
            "passed": bool(ticket_strategy["gate_passed"]),
            "detail": ticket_strategy["gate_detail"],
        }
        promotion["gates"].append(gate)
        if not gate["passed"] and promotion["status"] == "eligible":
            promotion["status"] = "hold"
            promotion["message"] = "概率模型达标，但单/双/全包策略未通过样本外效率门槛，保持当前生产策略。"
    result: dict[str, Any] = {
        "experiment_id": experiment_id,
        "model_version": MODEL_VERSION,
        "created_at": timestamp.isoformat(),
        "config": {
            "min_train_matches": min_train_matches,
            "min_test_matches": min_test_matches,
            "min_test_issues": min_test_issues,
            "min_brier_gain": min_brier_gain,
            "upset_market_probability": UPSET_MARKET_PROBABILITY,
            "static_models": STATIC_MODELS,
        },
        "dataset": {
            "sample_count": len(samples),
            "issue_count": len({sample.issue for sample in samples}),
            "fingerprint": _dataset_fingerprint(samples),
            "audit": audit,
        },
        "strict": strict_track,
        "exploratory": exploratory_track,
        "promotion": promotion,
        "ticket_strategy": ticket_strategy,
    }

    target = Path(output_dir) if output_dir else root / "reports" / "experiments"
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / f"{experiment_id}.json"
    markdown_path = target / f"{experiment_id}.md"
    result["artifacts"] = {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "latest_json": str(target / "latest.json"),
        "latest_markdown": str(target / "latest.md"),
    }
    if promote and promotion["status"] == "eligible":
        active = {
            "status": "active",
            "experiment_id": experiment_id,
            "model_version": MODEL_VERSION,
            "activated_at": timestamp.isoformat(),
            "weights": strict_track["walk_forward"]["final_weights"],
            "fundamental_coefficients": strict_track["walk_forward"]["final_fundamental_coefficients"],
            "draw_calibration_coefficients": strict_track["walk_forward"]["final_draw_calibration_coefficients"],
            "selection_policy": ticket_strategy.get("final_policy", DEFAULT_SELECTION_POLICY),
            "gates": promotion["gates"],
            "strict_test_metrics": strict_track["walk_forward"]["models"]["walk_forward_blend"]["metrics"],
        }
        active_path = target / "active_model.json"
        active_path.write_text(json.dumps(active, ensure_ascii=False, indent=2), encoding="utf-8")
        result["promotion"]["status"] = "promoted"
        result["promotion"]["active_model_path"] = str(active_path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_experiment_markdown(result), encoding="utf-8")
    shutil.copyfile(json_path, target / "latest.json")
    shutil.copyfile(markdown_path, target / "latest.md")
    return result


def load_experiment_samples(root: str | Path) -> tuple[list[ExperimentSample], dict[str, Any]]:
    work_dir = Path(root)
    history_dir = work_dir / "reports" / "history"
    latest_reviews: dict[str, dict[str, str]] = {}
    for entry in load_history_entries(history_dir):
        if entry.get("kind") != "review":
            continue
        if "play_type=choose9" in str(entry.get("condition_key") or ""):
            continue
        issue = str(entry.get("issue") or "").strip()
        if issue and issue not in latest_reviews:
            latest_reviews[issue] = entry

    samples: list[ExperimentSample] = []
    issue_audit: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for issue, entry in latest_reviews.items():
        issue_path = _history_snapshot_path(history_dir, entry) or work_dir / "data" / f"{_slug(issue)}_issue.json"
        markdown_path = history_dir / str(entry.get("markdown") or "")
        if not issue_path.exists() or not markdown_path.exists():
            skipped["missing_issue_or_review"] = skipped.get("missing_issue_or_review", 0) + 1
            continue
        outcomes = _review_outcomes(markdown_path)
        if not outcomes:
            skipped["missing_outcomes"] = skipped.get("missing_outcomes", 0) + 1
            continue
        try:
            loaded = load_issue(issue_path)
        except (OSError, ValueError, KeyError, TypeError):
            skipped["invalid_issue"] = skipped.get("invalid_issue", 0) + 1
            continue

        snapshot_status, snapshot_reason = audit_snapshot(loaded.metadata, loaded.matches)
        status_counts[snapshot_status] = status_counts.get(snapshot_status, 0) + 1
        issue_audit.append(
            {
                "issue": issue,
                "status": snapshot_status,
                "reason": snapshot_reason,
                "outcomes": len(outcomes),
            }
        )
        for match in loaded.matches:
            outcome = outcomes.get(match.seq)
            if outcome not in OUTCOMES:
                continue
            math = dixon_coles_forecast(match)
            profile = build_fundamental_profile(match)
            draw_profile = build_draw_calibration_profile(match, math)
            samples.append(
                ExperimentSample(
                    issue=issue,
                    seq=match.seq,
                    kickoff=match.kickoff,
                    league=match.league,
                    outcome=outcome,
                    components={
                        "odds": _odds_to_probabilities(match),
                        "signals": _signal_scores(match),
                        "dixon_coles": math.probabilities,
                    },
                    data_quality=math.data_quality,
                    snapshot_status=snapshot_status,
                    fundamental_features=dict(profile.features),
                    data_quality_score=math.data_quality_score,
                    draw_calibration_features=dict(draw_profile.features),
                    draw_calibration_available=dict(draw_profile.available),
                )
            )
    samples.sort(key=lambda item: (item.kickoff, item.issue, item.seq))
    return samples, {
        "issue_status_counts": status_counts,
        "issues": issue_audit,
        "skipped": skipped,
        "strict_sample_count": sum(item.snapshot_status == "verified_pre_match" for item in samples),
        "exploratory_sample_count": sum(item.snapshot_status != "post_kickoff_excluded" for item in samples),
        "excluded_sample_count": sum(item.snapshot_status == "post_kickoff_excluded" for item in samples),
    }


def audit_snapshot(metadata: dict[str, Any], matches: Iterable[Match]) -> tuple[str, str]:
    items = list(matches)
    if not items:
        return "post_kickoff_excluded", "快照没有比赛。"
    collected_text = str(metadata.get("snapshot_collected_at") or "").strip()
    if not collected_text:
        return "legacy_unverified", "旧快照缺少采集时间，只进入探索性回测。"
    collected = _parse_datetime(collected_text)
    if collected is None:
        return "post_kickoff_excluded", "快照采集时间无法解析。"
    first_kickoff = min(_as_utc(match.kickoff) for match in items)
    if _as_utc(collected) >= first_kickoff:
        return "post_kickoff_excluded", "快照生成时已有比赛开赛，存在赛后信息泄漏风险。"
    try:
        schema_version = int(metadata.get("snapshot_schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version < 2:
        return "legacy_unverified", "旧快照没有逐场拟合历史，只进入探索性回测。"
    return "verified_pre_match", "采集时间早于本期全部比赛，且包含当前模型所需的逐场历史结构。"


def evaluate_track(samples: Iterable[ExperimentSample], *, min_train_matches: int) -> dict[str, Any]:
    items = sorted(samples, key=lambda item: (item.kickoff, item.issue, item.seq))
    models: dict[str, Any] = {}
    for name, weights in STATIC_MODELS.items():
        records = [
            _record(
                sample,
                _candidate_probabilities(sample, weights, DEFAULT_FUNDAMENTAL_COEFFICIENTS)
                if name == "production_default"
                else _blend(sample.components, weights),
            )
            for sample in items
        ]
        models[name] = {"weights": weights, "metrics": evaluate_records(records)}

    walk_forward = walk_forward_evaluate(items, min_train_matches=min_train_matches)
    return {
        "sample_count": len(items),
        "issue_count": len({sample.issue for sample in items}),
        "models": models,
        "walk_forward": walk_forward,
        "slices": {
            "production_default": slice_metrics(
                [
                    _record(
                        sample,
                        _candidate_probabilities(sample, DEFAULT_WEIGHTS, DEFAULT_FUNDAMENTAL_COEFFICIENTS),
                    )
                    for sample in items
                ]
            ),
            "walk_forward_blend": slice_metrics(walk_forward["records_internal"]),
        },
    } | {"walk_forward": {key: value for key, value in walk_forward.items() if key != "records_internal"}}


def walk_forward_evaluate(
    samples: Iterable[ExperimentSample],
    *,
    min_train_matches: int,
) -> dict[str, Any]:
    items = sorted(samples, key=lambda item: (item.kickoff, item.issue, item.seq))
    grouped: dict[str, list[ExperimentSample]] = {}
    order: list[str] = []
    for sample in items:
        if sample.issue not in grouped:
            grouped[sample.issue] = []
            order.append(sample.issue)
        grouped[sample.issue].append(sample)
    order.sort(key=lambda issue: min(sample.kickoff for sample in grouped[issue]))

    training: list[ExperimentSample] = []
    candidate_records: list[PredictionRecord] = []
    folds: list[dict[str, Any]] = []
    for issue in order:
        test = sorted(grouped[issue], key=lambda item: item.seq)
        if len(training) >= min_train_matches:
            coefficients = fit_fundamental_coefficients(_fundamental_training_samples(training))
            weights = _fit_candidate_weights(training, coefficients)
            draw_coefficients = _fit_draw_coefficients(training, weights, coefficients)
            fold_records = [
                _record(
                    sample,
                    _candidate_probabilities(sample, weights, coefficients, draw_coefficients),
                )
                for sample in test
            ]
            candidate_records.extend(fold_records)
            folds.append(
                {
                    "test_issue": issue,
                    "train_matches": len(training),
                    "train_issues": len({sample.issue for sample in training}),
                    "test_matches": len(test),
                    "weights": weights,
                    "fundamental_coefficients": coefficients,
                    "draw_calibration_coefficients": draw_coefficients,
                    "metrics": evaluate_records(fold_records),
                }
            )
        training.extend(test)

    test_samples = [record.sample for record in candidate_records]
    compared_models: dict[str, Any] = {
        "walk_forward_blend": {"metrics": evaluate_records(candidate_records)}
    }
    for name in ("odds_only", "production_default"):
        weights = STATIC_MODELS[name]
        records = [
            _record(
                sample,
                _blend(sample.components, weights)
                if name == "odds_only"
                else _candidate_probabilities(sample, weights, DEFAULT_FUNDAMENTAL_COEFFICIENTS),
            )
            for sample in test_samples
        ]
        compared_models[name] = {"weights": weights, "metrics": evaluate_records(records)}
    final_coefficients = (
        fit_fundamental_coefficients(_fundamental_training_samples(items))
        if items
        else dict(DEFAULT_FUNDAMENTAL_COEFFICIENTS)
    )
    final_weights = _fit_candidate_weights(items, final_coefficients) if items else dict(DEFAULT_WEIGHTS)
    final_draw_coefficients = (
        _fit_draw_coefficients(items, final_weights, final_coefficients)
        if items
        else dict(DEFAULT_DRAW_CALIBRATION_COEFFICIENTS)
    )
    return {
        "min_train_matches": min_train_matches,
        "fold_count": len(folds),
        "test_matches": len(candidate_records),
        "test_issues": len({record.sample.issue for record in candidate_records}),
        "folds": folds,
        "models": compared_models,
        "final_weights": final_weights,
        "final_fundamental_coefficients": final_coefficients,
        "final_draw_calibration_coefficients": final_draw_coefficients,
        "predictions": [_serialize_record(record) for record in candidate_records],
        "records_internal": candidate_records,
    }


def evaluate_records(records: Iterable[PredictionRecord]) -> dict[str, Any]:
    items = list(records)
    if not items:
        return _empty_metrics()
    correct = 0
    top2_hits = 0
    brier_total = 0.0
    log_loss_total = 0.0
    confusion = {actual: {predicted: 0 for predicted in OUTCOMES} for actual in OUTCOMES}
    actual_counts = {outcome: 0 for outcome in OUTCOMES}
    predicted_counts = {outcome: 0 for outcome in OUTCOMES}
    correct_counts = {outcome: 0 for outcome in OUTCOMES}
    upset_total = 0
    upset_hits = 0
    calibration_rows: list[tuple[float, float]] = []

    for record in items:
        sample = record.sample
        probabilities = record.probabilities
        ranked = sorted(OUTCOMES, key=lambda outcome: probabilities[outcome], reverse=True)
        predicted = ranked[0]
        hit = predicted == sample.outcome
        correct += int(hit)
        top2_hits += int(sample.outcome in ranked[:2])
        actual_counts[sample.outcome] += 1
        predicted_counts[predicted] += 1
        correct_counts[sample.outcome] += int(hit)
        confusion[sample.outcome][predicted] += 1
        for outcome in OUTCOMES:
            brier_total += (probabilities[outcome] - float(outcome == sample.outcome)) ** 2
        log_loss_total += -math.log(max(1e-12, probabilities[sample.outcome]))
        confidence = probabilities[predicted]
        calibration_rows.append((confidence, float(hit)))
        if sample.components["odds"][sample.outcome] <= UPSET_MARKET_PROBABILITY:
            upset_total += 1
            upset_hits += int(hit)

    class_metrics = {}
    for outcome in OUTCOMES:
        recall = correct_counts[outcome] / actual_counts[outcome] if actual_counts[outcome] else None
        precision = correct_counts[outcome] / predicted_counts[outcome] if predicted_counts[outcome] else None
        class_metrics[outcome] = {
            "support": actual_counts[outcome],
            "predicted": predicted_counts[outcome],
            "recall": _rounded(recall),
            "precision": _rounded(precision),
        }
    return {
        "matches": len(items),
        "issues": len({record.sample.issue for record in items}),
        "accuracy": round(correct / len(items), 4),
        "top2_accuracy": round(top2_hits / len(items), 4),
        "brier_score": round(brier_total / (len(items) * len(OUTCOMES)), 4),
        "log_loss": round(log_loss_total / len(items), 4),
        "ece": round(_ece(calibration_rows), 4),
        "draw_recall": class_metrics["1"]["recall"],
        "upset_support": upset_total,
        "upset_recall": round(upset_hits / upset_total, 4) if upset_total else None,
        "class_metrics": class_metrics,
        "confusion_matrix": confusion,
        "calibration_bins": _calibration_bins(calibration_rows),
    }


def slice_metrics(records: Iterable[PredictionRecord]) -> dict[str, Any]:
    items = list(records)
    by_league: dict[str, list[PredictionRecord]] = {}
    by_quality: dict[str, list[PredictionRecord]] = {}
    for record in items:
        by_league.setdefault(record.sample.league or "未知联赛", []).append(record)
        by_quality.setdefault(record.sample.data_quality, []).append(record)
    return {
        "league": {
            name: evaluate_records(group)
            for name, group in sorted(by_league.items(), key=lambda item: (-len(item[1]), item[0]))
        },
        "data_quality": {
            name: evaluate_records(group)
            for name, group in sorted(by_quality.items(), key=lambda item: (-len(item[1]), item[0]))
        },
    }


def render_experiment_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# 纯胜平负模型实验：{result['experiment_id']}",
        "",
        f"- 模型版本：`{result['model_version']}`",
        f"- 数据指纹：`{result['dataset']['fingerprint']}`",
        f"- 总样本：{result['dataset']['sample_count']} 场 / {result['dataset']['issue_count']} 期",
        f"- 严格赛前样本：{result['dataset']['audit']['strict_sample_count']} 场",
        f"- 探索性样本：{result['dataset']['audit']['exploratory_sample_count']} 场",
        f"- 排除样本：{result['dataset']['audit']['excluded_sample_count']} 场",
        "",
        "## 严格赛前回测",
        "",
    ]
    lines.extend(_track_markdown(result["strict"]))
    lines.extend(["", "## 探索性回测（不具备晋级资格）", ""])
    lines.extend(_track_markdown(result["exploratory"]))
    promotion = result["promotion"]
    lines.extend(
        [
            "",
            "## 模型晋级",
            "",
            f"- 状态：{promotion['status']}",
            f"- 结论：{promotion['message']}",
        ]
    )
    for gate in promotion.get("gates", []):
        lines.append(f"- {'通过' if gate['passed'] else '未通过'}：{gate['name']}（{gate['detail']}）")
    strategy = result.get("ticket_strategy") or {}
    lines.extend(["", "## 单/双/全包策略", ""])
    if strategy.get("status") == "evaluated":
        lines.append(f"- 样本外门禁：{'通过' if strategy.get('gate_passed') else '未通过'}")
        lines.append(f"- 对比：{strategy.get('gate_detail', '')}")
        lines.append(f"- 候选阈值：`{json.dumps(strategy.get('tested_policy', {}), ensure_ascii=False)}`")
    else:
        lines.append(
            f"- 状态：继续收集（训练 {strategy.get('train_matches', 0)} / "
            f"测试 {strategy.get('test_matches', 0)} 场）"
        )
    lines.extend(["", "## 快照审计", ""])
    for item in result["dataset"]["audit"]["issues"]:
        lines.append(f"- {item['issue']}：{item['status']}；{item['reason']}")
    lines.append("")
    return "\n".join(lines)


def load_active_model_weights(work_dir: str | Path) -> dict[str, float] | None:
    path = Path(work_dir) / "reports" / "experiments" / "active_model.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("status") != "active" or payload.get("model_version") != MODEL_VERSION:
        return None
    return _valid_weights(payload.get("weights"))


def load_active_selection_policy(work_dir: str | Path) -> dict[str, float] | None:
    path = Path(work_dir) / "reports" / "experiments" / "active_model.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("status") != "active" or payload.get("model_version") != MODEL_VERSION:
        return None
    policy = payload.get("selection_policy")
    if not isinstance(policy, dict):
        return None
    result = dict(DEFAULT_SELECTION_POLICY)
    for key in result:
        try:
            result[key] = float(policy.get(key, result[key]))
        except (TypeError, ValueError):
            return None
    return result


def load_active_fundamental_coefficients(work_dir: str | Path) -> dict[str, float] | None:
    path = Path(work_dir) / "reports" / "experiments" / "active_model.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("status") != "active" or payload.get("model_version") != MODEL_VERSION:
        return None
    return valid_fundamental_coefficients(payload.get("fundamental_coefficients"))


def load_active_draw_calibration_coefficients(work_dir: str | Path) -> dict[str, float] | None:
    path = Path(work_dir) / "reports" / "experiments" / "active_model.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if payload.get("status") != "active" or payload.get("model_version") != MODEL_VERSION:
        return None
    return valid_draw_calibration_coefficients(payload.get("draw_calibration_coefficients"))


def evaluate_ticket_strategy(samples: Iterable[ExperimentSample]) -> dict[str, Any]:
    train, test = _strategy_train_test(list(samples))
    if len(train) < DEFAULT_MIN_TRAIN_MATCHES or len(test) < DEFAULT_MIN_TEST_MATCHES:
        return {
            "status": "collecting",
            "train_matches": len(train),
            "test_matches": len(test),
            "minimum_train_matches": DEFAULT_MIN_TRAIN_MATCHES,
            "minimum_test_matches": DEFAULT_MIN_TEST_MATCHES,
            "final_policy": dict(DEFAULT_SELECTION_POLICY),
        }
    learned = fit_selection_policy(train)
    baseline = _selection_policy_metrics(test, DEFAULT_SELECTION_POLICY)
    candidate = _selection_policy_metrics(test, learned)
    passed = candidate["loss"] <= baseline["loss"] and candidate["coverage"] + 0.01 >= baseline["coverage"]
    return {
        "status": "evaluated",
        "train_matches": len(train),
        "test_matches": len(test),
        "baseline": baseline,
        "candidate": candidate,
        "gate_passed": passed,
        "gate_detail": (
            f"损失 {candidate['loss']:.4f}/{baseline['loss']:.4f}，"
            f"覆盖 {candidate['coverage']:.1%}/{baseline['coverage']:.1%}，"
            f"场均选项 {candidate['average_choices']:.2f}/{baseline['average_choices']:.2f}"
        ),
        "tested_policy": learned,
        "final_policy": fit_selection_policy(list(samples)) if passed else dict(DEFAULT_SELECTION_POLICY),
    }


def fit_selection_policy(samples: Iterable[ExperimentSample]) -> dict[str, float]:
    items = list(samples)
    best = dict(DEFAULT_SELECTION_POLICY)
    best_loss = _selection_policy_metrics(items, best)["loss"]
    for single_top in (0.56, 0.58, 0.60, 0.62):
        for single_spread in (0.16, 0.18, 0.20, 0.22):
            for double_top in (0.42, 0.44, 0.46):
                for double_spread in (0.04, 0.06, 0.08):
                    for triple_gap in (0.015, 0.02, 0.03):
                        candidate = {
                            **DEFAULT_SELECTION_POLICY,
                            "single_top": single_top,
                            "single_spread": single_spread,
                            "double_top": double_top,
                            "double_spread": double_spread,
                            "triple_gap": triple_gap,
                        }
                        loss = _selection_policy_metrics(items, candidate)["loss"]
                        if loss < best_loss:
                            best, best_loss = candidate, loss
    return {key: round(value, 3) for key, value in best.items()}


def _selection_policy_metrics(samples: list[ExperimentSample], policy: dict[str, float]) -> dict[str, float]:
    if not samples:
        return {"loss": 1.0, "coverage": 0.0, "average_choices": 0.0}
    covered = 0
    choices = 0
    for sample in samples:
        probabilities = _blend(sample.components, DEFAULT_WEIGHTS)
        ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        picks = _select_picks(ranked, selection_policy=policy)
        covered += int(sample.outcome in picks)
        choices += len(picks)
    coverage = covered / len(samples)
    average_choices = choices / len(samples)
    loss = (1.0 - coverage) + 0.055 * max(0.0, average_choices - 1.0)
    return {
        "loss": round(loss, 6),
        "coverage": round(coverage, 6),
        "average_choices": round(average_choices, 4),
    }


def _strategy_train_test(samples: list[ExperimentSample]) -> tuple[list[ExperimentSample], list[ExperimentSample]]:
    ordered = sorted(samples, key=lambda sample: (sample.kickoff, sample.issue, sample.seq))
    grouped: dict[str, list[ExperimentSample]] = {}
    for sample in ordered:
        grouped.setdefault(sample.issue, []).append(sample)
    train: list[ExperimentSample] = []
    test: list[ExperimentSample] = []
    training_complete = False
    for issue_samples in grouped.values():
        if not training_complete:
            train.extend(issue_samples)
            training_complete = len(train) >= DEFAULT_MIN_TRAIN_MATCHES
        else:
            test.extend(issue_samples)
    return train, test


def _history_snapshot_path(history_dir: Path, entry: dict[str, str]) -> Path | None:
    relative = str(entry.get("snapshot") or "").strip()
    if not relative:
        return None
    path = history_dir / relative
    return path if path.exists() else None


def _promotion_decision(
    track: dict[str, Any],
    *,
    min_test_matches: int,
    min_test_issues: int,
    min_brier_gain: float,
) -> dict[str, Any]:
    walk = track["walk_forward"]
    candidate = walk["models"]["walk_forward_blend"]["metrics"]
    production = walk["models"]["production_default"]["metrics"]
    odds = walk["models"]["odds_only"]["metrics"]
    gates = [
        {
            "name": "严格测试样本",
            "passed": walk["test_matches"] >= min_test_matches,
            "detail": f"{walk['test_matches']}/{min_test_matches} 场",
        },
        {
            "name": "严格测试期数",
            "passed": walk["test_issues"] >= min_test_issues,
            "detail": f"{walk['test_issues']}/{min_test_issues} 期",
        },
    ]
    if candidate["matches"]:
        gates.extend(
            [
                {
                    "name": "Brier优于生产基线",
                    "passed": candidate["brier_score"] <= production["brier_score"] - min_brier_gain,
                    "detail": f"{candidate['brier_score']:.4f} vs {production['brier_score']:.4f}",
                },
                {
                    "name": "Brier优于赔率基线",
                    "passed": candidate["brier_score"] <= odds["brier_score"] - min_brier_gain,
                    "detail": f"{candidate['brier_score']:.4f} vs {odds['brier_score']:.4f}",
                },
                {
                    "name": "Log Loss不退化",
                    "passed": candidate["log_loss"] <= production["log_loss"],
                    "detail": f"{candidate['log_loss']:.4f} vs {production['log_loss']:.4f}",
                },
                {
                    "name": "Log Loss优于赔率基线",
                    "passed": candidate["log_loss"] <= odds["log_loss"],
                    "detail": f"{candidate['log_loss']:.4f} vs {odds['log_loss']:.4f}",
                },
                {
                    "name": "Top1命中率不明显退化",
                    "passed": candidate["accuracy"] + 0.01 >= production["accuracy"],
                    "detail": f"{candidate['accuracy']:.1%} vs {production['accuracy']:.1%}",
                },
                {
                    "name": "Top2命中率不明显退化",
                    "passed": candidate["top2_accuracy"] + 0.01 >= odds["top2_accuracy"],
                    "detail": f"{candidate['top2_accuracy']:.1%} vs {odds['top2_accuracy']:.1%}",
                },
                _non_regression_gate("平局召回", candidate["draw_recall"], production["draw_recall"]),
                _non_regression_gate("冷门召回", candidate["upset_recall"], production["upset_recall"]),
            ]
        )
    else:
        gates.append({"name": "存在样本外预测", "passed": False, "detail": "尚未形成walk-forward测试折"})
    passed = all(gate["passed"] for gate in gates)
    enough_data = gates[0]["passed"] and gates[1]["passed"]
    return {
        "status": "eligible" if passed else ("hold" if enough_data else "collecting"),
        "message": (
            "候选模型通过全部严格门禁，等待用户确认后才能启用。"
            if passed
            else "严格样本仍不足，继续收集赛前快照和真实赛果。"
            if not enough_data
            else "候选模型未同时超过赔率与生产基线，保持当前生产模型。"
        ),
        "gates": gates,
    }


def _non_regression_gate(name: str, candidate: float | None, baseline: float | None) -> dict[str, Any]:
    if candidate is None or baseline is None:
        return {"name": name, "passed": True, "detail": "当前测试窗无该类样本，不作为阻断项"}
    return {
        "name": f"{name}不明显退化",
        "passed": candidate + 0.05 >= baseline,
        "detail": f"{candidate:.1%} vs {baseline:.1%}",
    }


def _track_markdown(track: dict[str, Any]) -> list[str]:
    lines = [
        f"- 样本：{track['sample_count']} 场 / {track['issue_count']} 期",
        f"- Walk-forward：{track['walk_forward']['fold_count']} 折，"
        f"{track['walk_forward']['test_matches']} 场样本外预测",
        "",
        "| 模型 | 场次 | Top1 | Top2 | Brier | Log Loss | ECE | 平局召回 | 冷门召回 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    models = dict(track["models"])
    models["walk_forward_blend"] = track["walk_forward"]["models"]["walk_forward_blend"]
    for name, payload in models.items():
        metrics = payload["metrics"]
        lines.append(
            f"| {name} | {metrics['matches']} | {_percent(metrics['accuracy'])} | "
            f"{_percent(metrics['top2_accuracy'])} | {metrics['brier_score']:.4f} | "
            f"{metrics['log_loss']:.4f} | {metrics['ece']:.4f} | "
            f"{_percent(metrics['draw_recall'])} | {_percent(metrics['upset_recall'])} |"
        )
    return lines


def _record(sample: ExperimentSample, probabilities: dict[str, float]) -> PredictionRecord:
    return PredictionRecord(sample=sample, probabilities=probabilities)


def _blend(
    components: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> dict[str, float]:
    values = {
        outcome: sum(float(weights.get(name, 0.0)) * component[outcome] for name, component in components.items())
        for outcome in OUTCOMES
    }
    total = sum(values.values())
    return {outcome: values[outcome] / total for outcome in OUTCOMES} if total > 0 else {outcome: 1 / 3 for outcome in OUTCOMES}


def _candidate_probabilities(
    sample: ExperimentSample,
    weights: dict[str, float],
    coefficients: dict[str, float],
    draw_coefficients: dict[str, float] | None = None,
) -> dict[str, float]:
    # Synthetic/legacy experiment rows have no auditable raw features. Keep
    # their historical blend behaviour so older reports and tests remain
    # readable; verified current-version snapshots always take this market-offset branch.
    if not sample.fundamental_features:
        return _blend(sample.components, weights)
    probabilities = _candidate_probabilities_without_draw(sample, weights, coefficients)
    draw_corrections = draw_calibration_corrections_from_features(
        sample.draw_calibration_features,
        sample.draw_calibration_available,
        mathematical_quality=sample.data_quality_score,
        coefficients=draw_coefficients or DEFAULT_DRAW_CALIBRATION_COEFFICIENTS,
    )
    return apply_logit_corrections(probabilities, draw_corrections)


def _candidate_probabilities_without_draw(
    sample: ExperimentSample,
    weights: dict[str, float],
    coefficients: dict[str, float],
) -> dict[str, float]:
    if not sample.fundamental_features:
        return _blend(sample.components, weights)
    market = sample.components["odds"]
    signal_scale = max(0.0, float(weights.get("signals", 0.0))) / max(DEFAULT_WEIGHTS["signals"], 1e-9)
    scaled_coefficients = {name: value * signal_scale for name, value in coefficients.items()}
    probabilities = predict_with_fundamental_coefficients(
        market,
        sample.fundamental_features,
        scaled_coefficients,
    )
    math_strength = max(0.0, float(weights.get("dixon_coles", 0.0))) * sample.data_quality_score
    corrections = mathematical_corrections(
        market,
        sample.components["dixon_coles"],
        strength=math_strength,
        quality=sample.data_quality,
    )
    return apply_logit_corrections(probabilities, corrections)


def _fit_draw_coefficients(
    samples: Iterable[ExperimentSample],
    weights: dict[str, float],
    fundamental_coefficients: dict[str, float],
) -> dict[str, float]:
    return fit_draw_calibration_coefficients(
        (
            sample.draw_calibration_features,
            sample.draw_calibration_available,
            _candidate_probabilities_without_draw(sample, weights, fundamental_coefficients),
            sample.outcome,
            sample.data_quality_score,
        )
        for sample in samples
        if sample.fundamental_features
    )


def _fit_candidate_weights(
    samples: Iterable[ExperimentSample],
    coefficients: dict[str, float],
) -> dict[str, float]:
    items = list(samples)
    if not items:
        return dict(DEFAULT_WEIGHTS)
    if not any(sample.fundamental_features for sample in items):
        return fit_weights(_calibration_samples(items))
    best = dict(DEFAULT_WEIGHTS)
    best_score = _candidate_brier(items, best, coefficients)
    # In the residual architecture market is always the anchor. These values
    # control correction strength and may legitimately shrink to zero.
    for signal_step in range(0, 7):
        for math_step in range(0, 7):
            signals = signal_step * 0.05
            dixon_coles = math_step * 0.05
            if signals + dixon_coles > 0.60:
                continue
            weights = {
                "odds": 1.0 - signals - dixon_coles,
                "signals": signals,
                "dixon_coles": dixon_coles,
            }
            score = _candidate_brier(items, weights, coefficients)
            if score < best_score:
                best, best_score = weights, score
    return {name: round(value, 2) for name, value in best.items()}


def _candidate_brier(
    samples: list[ExperimentSample],
    weights: dict[str, float],
    coefficients: dict[str, float],
) -> float:
    total = 0.0
    for sample in samples:
        probabilities = _candidate_probabilities(sample, weights, coefficients)
        total += sum(
            (probabilities[outcome] - float(outcome == sample.outcome)) ** 2
            for outcome in OUTCOMES
        )
    return total / (len(samples) * len(OUTCOMES))


def _calibration_samples(samples: Iterable[ExperimentSample]) -> list[CalibrationSample]:
    return [
        CalibrationSample(kickoff=sample.kickoff, outcome=sample.outcome, components=sample.components)
        for sample in samples
    ]


def _fundamental_training_samples(
    samples: Iterable[ExperimentSample],
) -> list[tuple[dict[str, float], dict[str, float], str]]:
    return [
        (sample.fundamental_features, sample.components["odds"], sample.outcome)
        for sample in samples
        if sample.fundamental_features
    ]


def _serialize_record(record: PredictionRecord) -> dict[str, Any]:
    ranked = sorted(OUTCOMES, key=lambda outcome: record.probabilities[outcome], reverse=True)
    return {
        "issue": record.sample.issue,
        "seq": record.sample.seq,
        "kickoff": record.sample.kickoff.isoformat(),
        "league": record.sample.league,
        "actual": record.sample.outcome,
        "predicted": ranked[0],
        "probabilities": {key: round(value, 6) for key, value in record.probabilities.items()},
        "data_quality": record.sample.data_quality,
        "snapshot_status": record.sample.snapshot_status,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "matches": 0,
        "issues": 0,
        "accuracy": 0.0,
        "top2_accuracy": 0.0,
        "brier_score": 0.0,
        "log_loss": 0.0,
        "ece": 0.0,
        "draw_recall": None,
        "upset_support": 0,
        "upset_recall": None,
        "class_metrics": {
            outcome: {"support": 0, "predicted": 0, "recall": None, "precision": None}
            for outcome in OUTCOMES
        },
        "confusion_matrix": {actual: {predicted: 0 for predicted in OUTCOMES} for actual in OUTCOMES},
        "calibration_bins": [],
    }


def _ece(rows: list[tuple[float, float]], bins: int = 10) -> float:
    if not rows:
        return 0.0
    total = len(rows)
    result = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [row for row in rows if lower <= row[0] < upper or (index == bins - 1 and row[0] == 1.0)]
        if bucket:
            confidence = sum(row[0] for row in bucket) / len(bucket)
            accuracy = sum(row[1] for row in bucket) / len(bucket)
            result += len(bucket) / total * abs(confidence - accuracy)
    return result


def _calibration_bins(rows: list[tuple[float, float]], bins: int = 10) -> list[dict[str, Any]]:
    result = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [row for row in rows if lower <= row[0] < upper or (index == bins - 1 and row[0] == 1.0)]
        if not bucket:
            continue
        result.append(
            {
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "count": len(bucket),
                "mean_confidence": round(sum(row[0] for row in bucket) / len(bucket), 4),
                "accuracy": round(sum(row[1] for row in bucket) / len(bucket), 4),
            }
        )
    return result


def _dataset_fingerprint(samples: Iterable[ExperimentSample]) -> str:
    payload = [
        {
            "issue": item.issue,
            "seq": item.seq,
            "kickoff": item.kickoff.isoformat(),
            "league": item.league,
            "outcome": item.outcome,
            "components": item.components,
            "data_quality": item.data_quality,
            "snapshot_status": item.snapshot_status,
            "fundamental_features": item.fundamental_features,
            "data_quality_score": item.data_quality_score,
        }
        for item in samples
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _review_outcomes(path: Path) -> dict[int, str]:
    result: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        outcome = {"主胜": "3", "平": "1", "客胜": "0"}.get(cells[3])
        if outcome:
            result[int(cells[0])] = outcome
    return result


def _valid_weights(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        weights = {name: max(0.0, float(value[name])) for name in ("odds", "signals", "dixon_coles")}
    except (KeyError, TypeError, ValueError):
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    return {name: weight / total for name, weight in weights.items()}


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "issue"
