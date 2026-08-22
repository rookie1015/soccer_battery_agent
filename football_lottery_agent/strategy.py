from __future__ import annotations

from dataclasses import replace
from math import log

from .models import DrawHedgePlan, Issue, Prediction, TicketPlan
from .predictor import (
    SELECTION_OUTCOME_LABELS,
    SELECTION_REASON_PREFIX,
    _draw_context,
    _has_informative_signals,
    predict_issue,
    selection_reason,
)


DEFAULT_MAX_TICKET_COST_YUAN = 2000
STAKE_PER_LINE_YUAN = 2
MIN_SAFE_BUDGET_SINGLE_PROBABILITY = 0.60
TACTICAL_DRAW_MIN_PROBABILITY = 0.29
TACTICAL_DRAW_MAX_TOP_GAP = 0.06
TACTICAL_DRAW_MIN_MATH_PROBABILITY = 0.30
TACTICAL_DRAW_MIN_MATH_QUALITY = 0.50
DRAW_HEDGE_BUDGET_SHARE = 0.20
DRAW_HEDGE_MIN_TOTAL_BUDGET_YUAN = 10
DRAW_HEDGE_MIN_PROBABILITY = 0.27
DRAW_HEDGE_MIN_MARKET_PROBABILITY = 0.25
DRAW_HEDGE_MAX_TOP_GAP = 0.12


def build_ticket_plan(
    issue: Issue,
    max_ticket_cost_yuan: int = DEFAULT_MAX_TICKET_COST_YUAN,
    model_weights: dict[str, float] | None = None,
    evidence_aware_secondary: bool = False,
    selection_policy: dict[str, float] | None = None,
) -> TicketPlan:
    raw_predictions = predict_issue(
        issue.matches,
        model_weights=model_weights,
        evidence_aware_secondary=evidence_aware_secondary,
        selection_policy=selection_policy,
    )
    predictions, main_budget, draw_hedge = _build_budget_portfolio(
        raw_predictions,
        max_ticket_cost_yuan=max_ticket_cost_yuan,
    )
    choose9_keep, choose9_drop = _select_choose9(predictions)

    return TicketPlan(
        issue=issue,
        predictions=predictions,
        choose9_keep=choose9_keep,
        choose9_drop=choose9_drop,
        max_ticket_cost_yuan=max_ticket_cost_yuan,
        main_allocated_budget_yuan=main_budget,
        main_cost_yuan=ticket_cost_yuan(predictions),
        draw_hedge=draw_hedge,
    )


def _build_budget_portfolio(
    predictions: tuple[Prediction, ...],
    *,
    max_ticket_cost_yuan: int,
) -> tuple[tuple[Prediction, ...], int, DrawHedgePlan | None]:
    """Build a main ticket plus an optional budget-capped draw hedge.

    The old strategy replaced an entire fixture with a draw single before the
    budget optimiser ran.  Here the main ticket is kept intact as one branch,
    while at most 20% of the total budget is used by a second branch which
    fixes one draw that the main branch had to remove.
    """
    full_budget_main = _fit_predictions_to_budget(
        predictions,
        max_ticket_cost_yuan=max_ticket_cost_yuan,
    )
    if max_ticket_cost_yuan < DRAW_HEDGE_MIN_TOTAL_BUDGET_YUAN:
        return full_budget_main, max_ticket_cost_yuan, None
    if not _draw_hedge_candidates(full_budget_main):
        return full_budget_main, max_ticket_cost_yuan, None

    hedge_budget = int(max_ticket_cost_yuan * DRAW_HEDGE_BUDGET_SHARE)
    hedge_budget -= hedge_budget % STAKE_PER_LINE_YUAN
    hedge_budget = max(STAKE_PER_LINE_YUAN, hedge_budget)
    main_budget = max_ticket_cost_yuan - hedge_budget
    main_predictions = _fit_predictions_to_budget(predictions, max_ticket_cost_yuan=main_budget)
    candidates = _draw_hedge_candidates(main_predictions)
    if not candidates:
        return full_budget_main, max_ticket_cost_yuan, None

    selected_score, _, selected, evidence = max(candidates, key=lambda item: (item[0], -item[1]))
    branch_seed = tuple(
        _fix_draw_hedge_candidate(prediction, evidence)
        if prediction.match.seq == selected.match.seq
        else prediction
        for prediction in predictions
    )
    branch_predictions = _fit_predictions_to_budget(
        branch_seed,
        max_ticket_cost_yuan=hedge_budget,
    )
    line_count = ticket_units(branch_predictions)
    draw_hedge = DrawHedgePlan(
        candidate_seq=selected.match.seq,
        predictions=branch_predictions,
        allocated_budget_yuan=hedge_budget,
        line_count=line_count,
        cost_yuan=line_count * STAKE_PER_LINE_YUAN,
        score=round(selected_score, 4),
        evidence=evidence,
    )
    return main_predictions, main_budget, draw_hedge


def _draw_hedge_candidates(
    predictions: tuple[Prediction, ...],
) -> list[tuple[float, int, Prediction, tuple[str, ...]]]:
    return [
        (score, prediction.match.seq, prediction, evidence)
        for prediction in predictions
        for score, evidence in [_draw_hedge_assessment(prediction)]
        if score is not None
    ]


def _draw_hedge_assessment(prediction: Prediction) -> tuple[float | None, tuple[str, ...]]:
    """Score a draw only after the main ticket has removed it.

    Market probability is the anchor.  Goal-model and contextual data can
    support the candidate, but implausible derived totals are ignored instead
    of being treated as extra independent evidence.
    """
    if "1" not in prediction.analysis_picks or "1" in prediction.picks:
        return None, ()
    market = prediction.market_probabilities
    if not market:
        return None, ()

    draw_probability = prediction.probabilities.get("1", 0.0)
    market_draw = market.get("1", 0.0)
    top_gap = max(prediction.probabilities.values()) - draw_probability
    if (
        draw_probability < DRAW_HEDGE_MIN_PROBABILITY
        or market_draw < DRAW_HEDGE_MIN_MARKET_PROBABILITY
        or top_gap > DRAW_HEDGE_MAX_TOP_GAP
        or draw_probability < market_draw - 0.02
    ):
        return None, ()

    math_draw = prediction.dixon_coles_probabilities.get("1", 0.0)
    math_quality = prediction.dixon_coles_quality_score
    if math_quality >= 0.50 and math_draw and math_draw < market_draw - 0.04:
        return None, ()

    market_support, market_text = _tactical_market_draw_support(prediction)
    information_support, information_text = _draw_hedge_information_support(prediction)
    math_support = math_quality >= 0.25 and math_draw >= market_draw - 0.01
    if not market_support and not information_support and not math_support:
        return None, ()

    evidence = [f"模型平局 {draw_probability:.1%}，市场平局 {market_draw:.1%}"]
    if math_support:
        evidence.append(f"数学平局 {math_draw:.1%}（质量 {math_quality:.0%}）")
    if market_support:
        evidence.append(market_text)
    if information_support:
        evidence.append(information_text)

    # Candidate ranking remains market anchored.  Context and the goal model
    # qualify a candidate but are not added as independent bonuses because
    # they often originate from overlapping match data.
    score = (
        0.80 * market_draw
        + 0.20 * draw_probability
        + 0.10 * max(0.0, draw_probability - market_draw)
        - 0.05 * top_gap
    )
    return score, tuple(evidence)


def _draw_hedge_information_support(prediction: Prediction) -> tuple[bool, str]:
    if not _has_informative_signals(prediction.match):
        return False, ""
    expected_total, recent_draw_rate = _draw_context(prediction.match)
    # Values below 1.2 were observed when incomplete xG inputs collapsed.  They
    # are not credible enough to qualify a hedge candidate.
    credible_low_scoring = expected_total is not None and 1.20 <= expected_total <= 2.40
    draw_prone = recent_draw_rate is not None and recent_draw_rate >= 0.30
    if not credible_low_scoring and not draw_prone:
        return False, ""
    details = []
    if credible_low_scoring:
        details.append(f"预期总进球 {expected_total:.2f}")
    if draw_prone:
        details.append(f"近期/交锋平局率 {recent_draw_rate:.1%}")
    return True, "信息支持：" + "、".join(details)


def _fix_draw_hedge_candidate(
    prediction: Prediction,
    evidence: tuple[str, ...],
) -> Prediction:
    original_picks = prediction.analysis_picks
    reasons = tuple(
        reason for reason in prediction.reasons if not reason.startswith(SELECTION_REASON_PREFIX)
    )
    updated = replace(
        prediction,
        picks=("1",),
        original_picks=original_picks,
        risk="高",
        reasons=reasons,
        budget_adjusted=False,
        budget_forced_single=False,
        budget_removed_picks=(),
        tactical_draw=False,
        tactical_draw_score=0.0,
        tactical_draw_evidence=(),
    )
    hedge_reason = (
        "平局对冲分支：主票因预算删除本场平局，本分支仅用独立小预算固定单选平；"
        f"它不是稳胆，也不会替换主票。证据：{'；'.join(evidence)}。"
    )
    return replace(updated, reasons=(selection_reason(updated), hedge_reason, *updated.reasons))


def _apply_tactical_draw_strategy(predictions: tuple[Prediction, ...]) -> tuple[Prediction, ...]:
    """Select at most one explicitly high-risk draw single for the whole issue.

    A tactical draw is not a 60% banker. It is allowed only when a real market,
    a sufficiently reliable goal model, and at least one supporting market or
    information condition agree that the draw is unusually competitive.
    """
    candidates = [
        (score, prediction.match.seq, prediction, evidence)
        for prediction in predictions
        for score, evidence in [_tactical_draw_assessment(prediction)]
        if score is not None
    ]
    if not candidates:
        return predictions

    selected_score, _, selected, evidence = max(candidates, key=lambda item: (item[0], -item[1]))
    updated = replace(
        selected,
        picks=("1",),
        original_picks=("1",),
        risk="高",
        tactical_draw=True,
        tactical_draw_score=round(selected_score, 4),
        tactical_draw_evidence=evidence,
    )
    reasons = tuple(reason for reason in updated.reasons if not reason.startswith(SELECTION_REASON_PREFIX))
    tactical_reason = (
        "战术单平：这不是稳胆；市场、数学模型与赛前结构共同确认平局具有竞争力，"
        f"本期只选择评分最高的一场主动博平。证据：{'；'.join(evidence)}。"
    )
    updated = replace(updated, reasons=(selection_reason(updated), tactical_reason, *reasons))
    return tuple(updated if prediction.match.seq == selected.match.seq else prediction for prediction in predictions)


def _tactical_draw_assessment(prediction: Prediction) -> tuple[float | None, tuple[str, ...]]:
    market = prediction.market_probabilities
    if not market:
        return None, ()

    probabilities = prediction.probabilities
    draw_probability = probabilities.get("1", 0.0)
    top_probability = max(probabilities.values())
    top_gap = top_probability - draw_probability
    math_draw = prediction.dixon_coles_probabilities.get("1", 0.0)
    if (
        draw_probability < TACTICAL_DRAW_MIN_PROBABILITY
        or top_gap > TACTICAL_DRAW_MAX_TOP_GAP
        or prediction.dixon_coles_quality_score < TACTICAL_DRAW_MIN_MATH_QUALITY
        or math_draw < TACTICAL_DRAW_MIN_MATH_PROBABILITY
    ):
        return None, ()

    evidence = [
        f"数学平局 {math_draw:.1%}（质量 {prediction.dixon_coles_quality_score:.0%}）",
    ]
    market_support, market_text = _tactical_market_draw_support(prediction)
    information_support, information_text = _tactical_information_draw_support(prediction)
    if market_support:
        evidence.append(market_text)
    if information_support:
        evidence.append(information_text)
    if not market_support and not information_support:
        return None, ()

    market_draw = market.get("1", 0.0)
    score = (
        draw_probability
        - 0.60 * top_gap
        + 0.35 * max(0.0, math_draw - market_draw)
        + 0.008 * int(market_support)
        + 0.008 * int(information_support)
    )
    return score, tuple(evidence)


def _tactical_market_draw_support(prediction: Prediction) -> tuple[bool, str]:
    market_draw = prediction.market_probabilities.get("1", 0.0)
    market = prediction.match.sources.get("odds_market") if isinstance(prediction.match.sources, dict) else {}
    market = market if isinstance(market, dict) else {}
    movement = market.get("market_movement") if isinstance(market.get("market_movement"), dict) else {}
    try:
        draw_movement = float(movement.get("1") or 0.0)
    except (TypeError, ValueError):
        draw_movement = 0.0
    total = _number_or_none(market.get("total_points"))
    handicap = _number_or_none(
        market.get("asian_current_line")
        if market.get("asian_current_line") is not None
        else market.get("spread_home_point")
    )
    structural = draw_movement >= 0.005 or (total is not None and total <= 2.5) or (
        handicap is not None and abs(handicap) <= 0.25
    )
    supported = market_draw >= 0.28 and structural
    details = [f"市场平局 {market_draw:.1%}"]
    if draw_movement >= 0.005:
        details.append(f"较初盘上升 {draw_movement:.1%}")
    if total is not None and total <= 2.5:
        details.append(f"大小球 {total:g}")
    if handicap is not None and abs(handicap) <= 0.25:
        details.append(f"浅盘 {handicap:+g}")
    return supported, "市场支持：" + "、".join(details)


def _tactical_information_draw_support(prediction: Prediction) -> tuple[bool, str]:
    if not _has_informative_signals(prediction.match):
        return False, ""
    expected_total, recent_draw_rate = _draw_context(prediction.match)
    low_scoring = expected_total is not None and expected_total <= 2.40
    draw_prone = recent_draw_rate is not None and recent_draw_rate >= 0.30
    if not low_scoring and not draw_prone:
        return False, ""
    details = []
    if low_scoring:
        details.append(f"预期总进球 {expected_total:.2f}")
    if draw_prone:
        details.append(f"近期/交锋平局率 {recent_draw_rate:.1%}")
    return True, "信息支持：" + "、".join(details)


def _number_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
