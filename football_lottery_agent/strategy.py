from __future__ import annotations

from .models import Issue, Prediction, TicketPlan
from .predictor import predict_issue


def build_ticket_plan(issue: Issue) -> TicketPlan:
    predictions = predict_issue(issue.matches)
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


def _uncertainty_score(prediction: Prediction) -> float:
    probs = sorted(prediction.probabilities.values(), reverse=True)
    top = probs[0]
    second = probs[1]
    pick_penalty = {1: 0.0, 2: 0.12, 3: 0.24}[len(prediction.picks)]
    return (1.0 - top) + (second - top) * 0.2 + pick_penalty

