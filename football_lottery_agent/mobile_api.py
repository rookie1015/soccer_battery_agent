from __future__ import annotations

from .models import Choose9Plan, DrawHedgePlan, LinePortfolioPlan, Prediction, TicketPlan
from .predictor import OUTCOME_LABELS


def serialize_ticket_plan(plan: TicketPlan, include_review_fields: bool = False) -> dict[str, object]:
    predictions = list(plan.predictions)
    draw_hedge = getattr(plan, "draw_hedge", None)
    draw_hedge = draw_hedge if isinstance(draw_hedge, DrawHedgePlan) else None
    line_portfolio = getattr(plan, "line_portfolio", None)
    line_portfolio = line_portfolio if isinstance(line_portfolio, LinePortfolioPlan) else None
    main_cost_yuan = _int_plan_attr(plan, "main_cost_yuan")
    foreign_odds_status = plan.issue.metadata.get("foreign_odds_audit")
    if not isinstance(foreign_odds_status, dict) or not foreign_odds_status.get("requested"):
        foreign_odds_status = None
    low_risk = sum(1 for prediction in predictions if prediction.risk == "低")
    model_singles = sum(1 for prediction in predictions if len(prediction.analysis_picks) == 1)
    ticket_singles = sum(1 for prediction in predictions if len(prediction.picks) == 1)
    forced_singles = sum(1 for prediction in predictions if prediction.budget_forced_single)
    tactical_draws = sum(1 for prediction in predictions if prediction.tactical_draw)
    avg_confidence = (
        sum(prediction.confidence for prediction in predictions) / len(predictions)
        if predictions
        else 0
    )
    metrics: dict[str, object] = {
        "match_count": len(predictions),
        "single_count": model_singles,
        "ticket_single_count": ticket_singles,
        "budget_forced_single_count": forced_singles,
        "tactical_draw_count": tactical_draws,
        "draw_hedge_count": int(draw_hedge is not None),
        "line_portfolio_count": line_portfolio.line_count if line_portfolio else 0,
        "draw_candidate_count": len(line_portfolio.draw_coverages) if line_portfolio else 0,
        "average_confidence": round(avg_confidence, 1),
    }
    if include_review_fields:
        metrics["low_risk_count"] = low_risk
    return {
        "issue": plan.issue.issue,
        "purchase_deadline": plan.issue.metadata.get("purchase_deadline", ""),
        "purchase_deadline_source": plan.issue.metadata.get("purchase_deadline_source", ""),
        "sale_begin_time": plan.issue.metadata.get("sale_begin_time", ""),
        "analysis_mode": plan.issue.metadata.get("analysis_mode", "full"),
        "analysis_mode_message": plan.issue.metadata.get("analysis_mode_message", ""),
        "foreign_odds_status": foreign_odds_status,
        "budget": {
            "limit_yuan": _int_plan_attr(plan, "max_ticket_cost_yuan"),
            "main_allocated_yuan": _int_plan_attr(plan, "main_allocated_budget_yuan"),
            "main_cost_yuan": _int_plan_attr(plan, "main_cost_yuan"),
            "hedge_allocated_yuan": draw_hedge.allocated_budget_yuan if draw_hedge else 0,
            "hedge_cost_yuan": draw_hedge.cost_yuan if draw_hedge else 0,
            "total_cost_yuan": main_cost_yuan + (draw_hedge.cost_yuan if draw_hedge else 0),
        },
        "draw_hedge": _serialize_draw_hedge(plan),
        "line_portfolio": _serialize_line_portfolio(plan),
        "metrics": metrics,
        "choose9_keep": list(plan.choose9_keep),
        "choose9_drop": list(plan.choose9_drop),
        "choose9": _serialize_choose9(plan),
        "predictions": [_serialize_prediction(prediction, include_review_fields) for prediction in predictions],
    }


def _serialize_choose9(plan: TicketPlan) -> dict[str, object] | None:
    choose9 = getattr(plan, "choose9_plan", None)
    if not isinstance(choose9, Choose9Plan):
        return None
    all_sequences = {prediction.match.seq for prediction in plan.predictions}
    keep = set(choose9.keep)
    return {
        "mode": "independent",
        "budget_scope": "separate",
        "limit_yuan": choose9.allocated_budget_yuan,
        "line_count": choose9.line_count,
        "cost_yuan": choose9.cost_yuan,
        "joint_coverage_probability": round(choose9.joint_coverage_probability * 100, 2),
        "keep": list(choose9.keep),
        "drop": sorted(all_sequences - keep),
        "selections": [
            {
                "seq": prediction.match.seq,
                "home": prediction.match.home,
                "away": prediction.match.away,
                "pick_text": prediction.pick_text,
                "picks": list(prediction.picks),
                "pick_labels": [OUTCOME_LABELS[pick] for pick in prediction.picks],
                "coverage_probability": round(
                    min(
                        1.0,
                        sum(
                            prediction.probabilities.get(outcome, 0.0)
                            for outcome in prediction.picks
                        ),
                    )
                    * 100,
                    1,
                ),
            }
            for prediction in choose9.predictions
        ],
    }


def _serialize_line_portfolio(plan: TicketPlan) -> dict[str, object] | None:
    portfolio = getattr(plan, "line_portfolio", None)
    if not isinstance(portfolio, LinePortfolioPlan):
        return None
    matches = {prediction.match.seq: prediction.match for prediction in plan.predictions}
    return {
        "line_count": portfolio.line_count,
        "allocated_budget_yuan": portfolio.allocated_budget_yuan,
        "cost_yuan": portfolio.cost_yuan,
        "multi_draw_lines": portfolio.multi_draw_lines,
        "minimum_draw_pair_lines": portfolio.minimum_draw_pair_lines,
        "draw_coverages": [
            {
                "seq": coverage.seq,
                "home": matches[coverage.seq].home,
                "away": matches[coverage.seq].away,
                "probability": round(coverage.probability * 100, 1),
                "target_lines": coverage.target_lines,
                "actual_lines": coverage.actual_lines,
                "actual_share": round(coverage.actual_lines / max(portfolio.line_count, 1) * 100, 1),
            }
            for coverage in portfolio.draw_coverages
        ],
        "lines": [
            {
                "number": number,
                "pick_text": line.pick_text,
                "outcomes": list(line.outcomes),
                "joint_probability": line.joint_probability,
            }
            for number, line in enumerate(portfolio.lines, start=1)
        ],
    }


def _serialize_draw_hedge(plan: TicketPlan) -> dict[str, object] | None:
    hedge = getattr(plan, "draw_hedge", None)
    if not isinstance(hedge, DrawHedgePlan):
        return None
    candidate = next(
        prediction for prediction in hedge.predictions if prediction.match.seq == hedge.candidate_seq
    )
    return {
        "candidate_seq": hedge.candidate_seq,
        "home": candidate.match.home,
        "away": candidate.match.away,
        "fixed_pick": "1",
        "fixed_pick_label": OUTCOME_LABELS["1"],
        "allocated_budget_yuan": hedge.allocated_budget_yuan,
        "line_count": hedge.line_count,
        "cost_yuan": hedge.cost_yuan,
        "main_cost_yuan": plan.main_cost_yuan,
        "total_cost_yuan": plan.total_cost_yuan,
        "score": round(hedge.score * 100, 1),
        "evidence": list(hedge.evidence),
        "selections": [
            {
                "seq": prediction.match.seq,
                "pick_text": prediction.pick_text,
                "pick_labels": [OUTCOME_LABELS[pick] for pick in prediction.picks],
            }
            for prediction in hedge.predictions
        ],
    }


def _int_plan_attr(plan: TicketPlan, name: str) -> int:
    value = getattr(plan, name, 0)
    return value if isinstance(value, int) else 0


def _serialize_prediction(prediction: Prediction, include_review_fields: bool) -> dict[str, object]:
    match = prediction.match
    result: dict[str, object] = {
        "seq": match.seq,
        "league": match.league,
        "kickoff": match.kickoff.isoformat(timespec="minutes"),
        "kickoff_display": match.kickoff.strftime("%m-%d %H:%M"),
        "home": match.home,
        "away": match.away,
        "pick_text": prediction.pick_text,
        "pick_labels": [OUTCOME_LABELS[pick] for pick in prediction.picks],
        "picks": list(prediction.picks),
        "analysis_pick_text": prediction.analysis_pick_text,
        "analysis_pick_labels": [OUTCOME_LABELS[pick] for pick in prediction.analysis_picks],
        "analysis_picks": list(prediction.analysis_picks),
        "budget_adjusted": prediction.budget_adjusted,
        "budget_forced_single": prediction.budget_forced_single,
        "budget_removed_picks": list(prediction.budget_removed_picks),
        "draw_guard": prediction.draw_guard,
        "tactical_draw": prediction.tactical_draw,
        "tactical_draw_score": round(prediction.tactical_draw_score * 100, 1),
        "tactical_draw_evidence": list(prediction.tactical_draw_evidence),
        "confidence": prediction.confidence,
        "probabilities": {
            "home": round(prediction.probabilities["3"] * 100, 1),
            "draw": round(prediction.probabilities["1"] * 100, 1),
            "away": round(prediction.probabilities["0"] * 100, 1),
        },
        "market_probabilities": {
            "home": round(prediction.market_probabilities.get("3", 0.0) * 100, 1),
            "draw": round(prediction.market_probabilities.get("1", 0.0) * 100, 1),
            "away": round(prediction.market_probabilities.get("0", 0.0) * 100, 1),
        },
        "blend_weights": dict(prediction.blend_weights),
        "reasons": list(prediction.reasons),
    }
    if include_review_fields:
        result["risk"] = prediction.risk
        result["scorelines"] = [
            {"score": item.text, "probability": round(item.probability * 100, 1)}
            for item in prediction.scorelines
        ]
    return result
