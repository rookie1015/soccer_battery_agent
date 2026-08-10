from __future__ import annotations

from dataclasses import replace
from math import log

from .models import Issue, Prediction, TicketPlan
from .predictor import SELECTION_OUTCOME_LABELS, SELECTION_REASON_PREFIX, _draw_context, predict_issue, selection_reason


DEFAULT_MAX_TICKET_COST_YUAN = 2000
STAKE_PER_LINE_YUAN = 2
MIN_SAFE_BUDGET_SINGLE_PROBABILITY = 0.60


def build_ticket_plan(
    issue: Issue,
    max_ticket_cost_yuan: int = DEFAULT_MAX_TICKET_COST_YUAN,
    model_weights: dict[str, float] | None = None,
    evidence_aware_secondary: bool = False,
    selection_policy: dict[str, float] | None = None,
) -> TicketPlan:
    predictions = _fit_predictions_to_budget(
        predict_issue(
            issue.matches,
            model_weights=model_weights,
            evidence_aware_secondary=evidence_aware_secondary,
            selection_policy=selection_policy,
        ),
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
    if ticket_units(predictions) <= max_units:
        return predictions

    # Exact dynamic programming over the discrete 1/2/3-choice products. The
    # former greedy loop could remove a locally cheap option and still end with
    # a lower global coverage probability. States are keyed by ticket units, so
    # the search remains small even for fourteen fixtures.
    # State value is (number of unsafe budget-forced singles, log coverage,
    # selections).  Fewer forced singles wins before raw coverage, preventing
    # a 43%-50% uncertain fixture from being presented as a normal banker when
    # an equally affordable safer compression exists elsewhere.
    states: dict[int, tuple[int, float, tuple[Prediction, ...]]] = {1: (0, 0.0, ())}
    for prediction in predictions:
        options = _prediction_budget_options(prediction)
        next_states: dict[int, tuple[int, float, tuple[Prediction, ...]]] = {}
        for units, (forced_singles, score, selected) in states.items():
            for option in options:
                new_units = units * max(1, len(option.picks))
                if new_units > max_units:
                    continue
                coverage = sum(_coverage_value(option, outcome) for outcome in option.picks)
                option_score = log(max(coverage, 1e-12))
                candidate = (
                    forced_singles + int(option.budget_forced_single),
                    score + option_score,
                    (*selected, option),
                )
                existing = next_states.get(new_units)
                if existing is None or _budget_state_key(candidate) > _budget_state_key(existing):
                    next_states[new_units] = candidate
        states = next_states
        if not states:
            return tuple(_single_only(prediction) for prediction in predictions)

    _, best = max(
        states.items(),
        key=lambda item: (*_budget_state_key(item[1]), item[0]),
    )
    return best[2]


def _budget_state_key(state: tuple[int, float, tuple[Prediction, ...]]) -> tuple[int, float]:
    forced_singles, score, _ = state
    return -forced_singles, score


def _prediction_budget_options(prediction: Prediction) -> tuple[Prediction, ...]:
    options = [prediction]
    current = prediction
    while len(current.picks) > 1:
        current = _downgrade_prediction(current)
        options.append(current)
    return tuple(options)


def _single_only(prediction: Prediction) -> Prediction:
    current = prediction
    while len(current.picks) > 1:
        current = _downgrade_prediction(current)
    return current


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
    removed = ranked_selected[-1]
    original_picks = prediction.analysis_picks
    forced_single = (
        prediction.budget_forced_single
        or (len(downgraded) == 1 and not _safe_budget_single(prediction, downgraded[0]))
    )
    remaining_text = "/".join(downgraded)
    budget_note = (
        f"预算调整：为控制整张票总成本，本场移除{SELECTION_OUTCOME_LABELS[removed]}({removed}) "
        f"{prediction.probabilities.get(removed, 0.0):.1%}，最终保留 {remaining_text}；"
        "这是成本取舍，不代表被移除赛果不可能发生。"
    )
    reasons = tuple(
        reason
        for reason in prediction.reasons
        if not reason.startswith(SELECTION_REASON_PREFIX)
    )
    adjusted = replace(
        prediction,
        picks=downgraded,
        original_picks=original_picks,
        reasons=(*reasons, budget_note),
        risk="高" if forced_single else prediction.risk,
        budget_adjusted=True,
        budget_forced_single=forced_single,
        budget_removed_picks=(*prediction.budget_removed_picks, removed),
    )
    return replace(adjusted, reasons=(selection_reason(adjusted), *adjusted.reasons))


def _safe_budget_single(prediction: Prediction, outcome: str) -> bool:
    """Only allow budget compression to call a genuinely strong result a single."""
    if prediction.draw_guard:
        return False
    probabilities = prediction.probabilities
    top_outcome, top_probability = max(probabilities.items(), key=lambda item: item[1])
    if outcome != top_outcome or top_probability < MIN_SAFE_BUDGET_SINGLE_PROBABILITY:
        return False

    math_probabilities = prediction.dixon_coles_probabilities
    if prediction.dixon_coles_quality_score >= 0.50 and math_probabilities:
        math_top = max(math_probabilities, key=math_probabilities.get)
        if math_top != top_outcome:
            return False

    audit = prediction.match.sources.get("collection_audit") if isinstance(prediction.match.sources, dict) else None
    if isinstance(audit, dict) and audit.get("mode") == "full":
        strength = audit.get("strength") if isinstance(audit.get("strength"), dict) else {}
        xg = audit.get("xg") if isinstance(audit.get("xg"), dict) else {}
        strength_ok = strength.get("status") in {"complete", "partial"}
        xg_ok = xg.get("status") in {"complete", "partial"}
        if not strength_ok and not xg_ok:
            return False
    return True


def _coverage_value(prediction: Prediction, outcome: str) -> float:
    probability = prediction.probabilities.get(outcome, 0.0)
    if prediction.selection_scores:
        return prediction.selection_scores.get(outcome, probability)
    audit = prediction.match.sources.get("collection_audit") if isinstance(prediction.match.sources, dict) else {}
    if isinstance(audit, dict) and audit.get("mode") == "full":
        # A full analysis with insufficient corroborating evidence must stay
        # neutral. The legacy simple-mode draw bonus is not evidence.
        return probability
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
