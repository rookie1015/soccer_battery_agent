from __future__ import annotations

from dataclasses import replace

from .models import Issue, Prediction, TicketPlan
from .predictor import predict_issue


DEFAULT_MAX_TICKET_COST_YUAN = 2000
STAKE_PER_LINE_YUAN = 2


def build_ticket_plan(issue: Issue, max_ticket_cost_yuan: int = DEFAULT_MAX_TICKET_COST_YUAN) -> TicketPlan:
    predictions = _fit_predictions_to_budget(
        predict_issue(issue.matches),
        max_ticket_cost_yuan=max_ticket_cost_yuan,
    )
    uncertainty = sorted(
        predictions,
        key=lambda item: (_uncertainty_score(item), -item.match.seq),
        reverse=True,
    )
    choose9_drop = tuple(sorted(pred.match.seq for pred in uncertainty[:5]))
    choose9_keep = tuple(seq for seq in range(1, 15) if seq not in choose9_drop)

    return TicketPlan(
        issue=issue,
        predictions=predictions,
        choose9_keep=choose9_keep,
        choose9_drop=choose9_drop,
    )


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
    ranked_selected = sorted(
        prediction.picks,
        key=lambda outcome: prediction.probabilities.get(outcome, 0.0),
        reverse=True,
    )
    removed = ranked_selected[-1]
    return prediction.probabilities.get(removed, 0.0)


def _downgrade_prediction(prediction: Prediction) -> Prediction:
    ranked_selected = tuple(
        sorted(
            prediction.picks,
            key=lambda outcome: prediction.probabilities.get(outcome, 0.0),
            reverse=True,
        )
    )
    downgraded = ranked_selected[:-1]
    reasons = prediction.reasons
    budget_note = "预算约束：为控制整张票成本，压缩低价值防守项。"
    if budget_note not in reasons:
        reasons = (*reasons, budget_note)
    return replace(prediction, picks=downgraded, reasons=reasons)


def _uncertainty_score(prediction: Prediction) -> float:
    probs = sorted(prediction.probabilities.values(), reverse=True)
    top = probs[0]
    second = probs[1]
    pick_penalty = {1: 0.0, 2: 0.12, 3: 0.24}[len(prediction.picks)]
    return (1.0 - top) + (second - top) * 0.2 + pick_penalty
