from __future__ import annotations

from .models import Prediction, TicketPlan
from .predictor import OUTCOME_LABELS


def serialize_ticket_plan(plan: TicketPlan) -> dict[str, object]:
    predictions = list(plan.predictions)
    low_risk = sum(1 for prediction in predictions if prediction.risk == "低")
    singles = sum(1 for prediction in predictions if len(prediction.picks) == 1)
    avg_confidence = (
        sum(prediction.confidence for prediction in predictions) / len(predictions)
        if predictions
        else 0
    )
    return {
        "issue": plan.issue.issue,
        "purchase_deadline": plan.issue.metadata.get("purchase_deadline", ""),
        "purchase_deadline_source": plan.issue.metadata.get("purchase_deadline_source", ""),
        "sale_begin_time": plan.issue.metadata.get("sale_begin_time", ""),
        "metrics": {
            "match_count": len(predictions),
            "single_count": singles,
            "low_risk_count": low_risk,
            "average_confidence": round(avg_confidence, 1),
        },
        "choose9_keep": list(plan.choose9_keep),
        "choose9_drop": list(plan.choose9_drop),
        "predictions": [_serialize_prediction(prediction) for prediction in predictions],
    }


def _serialize_prediction(prediction: Prediction) -> dict[str, object]:
    match = prediction.match
    return {
        "seq": match.seq,
        "league": match.league,
        "kickoff": match.kickoff.isoformat(timespec="minutes"),
        "kickoff_display": match.kickoff.strftime("%m-%d %H:%M"),
        "home": match.home,
        "away": match.away,
        "pick_text": prediction.pick_text,
        "pick_labels": [OUTCOME_LABELS[pick] for pick in prediction.picks],
        "picks": list(prediction.picks),
        "confidence": prediction.confidence,
        "risk": prediction.risk,
        "probabilities": {
            "home": round(prediction.probabilities["3"] * 100, 1),
            "draw": round(prediction.probabilities["1"] * 100, 1),
            "away": round(prediction.probabilities["0"] * 100, 1),
        },
        "scorelines": [
            {"score": item.text, "probability": round(item.probability * 100, 1)}
            for item in prediction.scorelines
        ],
        "reasons": list(prediction.reasons),
    }
