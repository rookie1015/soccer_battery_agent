from __future__ import annotations

from dataclasses import replace
from math import log

from .models import Issue, Prediction, TicketPlan
from .predictor import _draw_context, predict_issue


DEFAULT_MAX_TICKET_COST_YUAN = 2000
STAKE_PER_LINE_YUAN = 2


def build_ticket_plan(
    issue: Issue,
    max_ticket_cost_yuan: int = DEFAULT_MAX_TICKET_COST_YUAN,
    model_weights: dict[str, float] | None = None,
) -> TicketPlan:
    predictions = _fit_predictions_to_budget(
        predict_issue(issue.matches, model_weights=model_weights),
        max_ticket_cost_yuan=max_ticket_cost_yuan,
    )
    choose9_keep, choose9_drop = _select_choose9(predictions)

    return TicketPlan(
        issue=issue,
        predictions=predictions,
        choose9_keep=choose9_keep,
        choose9_drop=choose9_drop,
    )


def _select_choose9(predictions: tuple[Prediction, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Select nine fixtures for the chance that all nine recommended picks land.

    A fixture's relevant probability is the total probability covered by its selected
    outcomes, rather than its raw confidence or number of selected outcomes.
    """
    ranked = sorted(
        predictions,
        key=lambda prediction: (
            _pick_coverage_probability(prediction),
            prediction.confidence,
            -prediction.match.seq,
        ),
        reverse=True,
    )
    keep = tuple(sorted(prediction.match.seq for prediction in ranked[:9]))
    drop = tuple(sorted(prediction.match.seq for prediction in ranked[9:]))
    return keep, drop


def _pick_coverage_probability(prediction: Prediction) -> float:
    return sum(prediction.probabilities.get(outcome, 0.0) for outcome in prediction.picks)


def ticket_cost_yuan(predictions: tuple[Prediction, ...]) -> int:
    return ticket_units(predictions) * STAKE_PER_LINE_YUAN


def ticket_units(predictions: tuple[Prediction, ...]) -> int:
    units = 1
    for prediction in predictions:
        units *= max(1, len(prediction.picks))
    return units


def _fit_predictions_to_budget(
    predictions: tuple[Prediction, ...],
    max_ticket_cost_yuan: int,
) -> tuple[Prediction, ...]:
    if max_ticket_cost_yuan <= 0:
        return predictions

    max_units = max(1, max_ticket_cost_yuan // STAKE_PER_LINE_YUAN)
    adjusted = list(predictions)
    while ticket_units(tuple(adjusted)) > max_units:
        candidates = [
            (index, _downgrade_loss(prediction))
            for index, prediction in enumerate(adjusted)
            if len(prediction.picks) > 1
        ]
        if not candidates:
            break
        index, _ = min(candidates, key=lambda item: (item[1], adjusted[item[0]].confidence, adjusted[item[0]].match.seq))
        adjusted[index] = _downgrade_prediction(adjusted[index])
    return tuple(adjusted)


def _downgrade_loss(prediction: Prediction) -> float:
    values = [_coverage_value(prediction, outcome) for outcome in prediction.picks]
    if len(values) <= 1:
        return float("inf")
    removed = min(values)
    coverage = sum(values)
    remaining = coverage - removed
    if remaining <= 0:
        return float("inf")
    coverage_loss = -log(remaining / coverage)
    cost_reduction = log(len(values) / (len(values) - 1))
    return coverage_loss / cost_reduction


def _downgrade_prediction(prediction: Prediction) -> Prediction:
    ranked_selected = tuple(
        sorted(
            prediction.picks,
            key=lambda outcome: _coverage_value(prediction, outcome),
            reverse=True,
        )
    )
    downgraded = ranked_selected[:-1]
    reasons = prediction.reasons
    budget_note = "预算约束：为控制整张票成本，压缩低价值防守项。"
    if budget_note not in reasons:
        reasons = (*reasons, budget_note)
    return replace(prediction, picks=downgraded, reasons=reasons)


def _coverage_value(prediction: Prediction, outcome: str) -> float:
    probability = prediction.probabilities.get(outcome, 0.0)
    if outcome != "1" or probability < 0.26:
        return probability

    non_draw_probabilities = [
        prediction.probabilities.get(outcome, 0.0) for outcome in ("3", "0")
    ]
    nearest_non_draw_gap = min(abs(probability - value) for value in non_draw_probabilities)
    if nearest_non_draw_gap > 0.04:
        return probability

    bonus = 0.02 * (1.0 - nearest_non_draw_gap / 0.04)
    if prediction.match.sources.get("odds") == "default_placeholder":
        bonus += 0.015

    expected_total, recent_draw_rate = _draw_context(prediction.match)
    if expected_total is not None and expected_total < 2.35:
        bonus += min(0.025, (2.35 - expected_total) * 0.025)
    if recent_draw_rate is not None and recent_draw_rate > 0.27:
        bonus += min(0.02, (recent_draw_rate - 0.27) * 0.10)
    return probability + min(0.05, bonus)
