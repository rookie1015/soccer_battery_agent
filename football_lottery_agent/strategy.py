from __future__ import annotations

from dataclasses import replace
from heapq import heappop, heappush
from itertools import product
from math import exp, log
from random import Random

from .fundamentals import build_fundamental_profile
from .models import (
    Choose9Plan,
    DrawHedgePlan,
    DrawLineCoverage,
    Issue,
    LinePortfolioPlan,
    Prediction,
    TicketLine,
    TicketPlan,
)
from .predictor import (
    SELECTION_OUTCOME_LABELS,
    SELECTION_REASON_PREFIX,
    _draw_context,
    predict_issue,
    selection_reason,
)


DEFAULT_MAX_TICKET_COST_YUAN = 2000
STAKE_PER_LINE_YUAN = 2
DEFAULT_BUDGET_OVERAGE_TOLERANCE_YUAN = 50
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
    budget_overage_tolerance_yuan: int = DEFAULT_BUDGET_OVERAGE_TOLERANCE_YUAN,
    model_weights: dict[str, float] | None = None,
    fundamental_coefficients: dict[str, float] | None = None,
    draw_calibration_coefficients: dict[str, float] | None = None,
    evidence_aware_secondary: bool = False,
    selection_policy: dict[str, float] | None = None,
) -> TicketPlan:
    raw_predictions = predict_issue(
        issue.matches,
        model_weights=model_weights,
        fundamental_coefficients=fundamental_coefficients,
        draw_calibration_coefficients=draw_calibration_coefficients,
        evidence_aware_secondary=evidence_aware_secondary,
        selection_policy=selection_policy,
    )
    ticket_predictions = _fit_predictions_to_budget(
        raw_predictions,
        max_ticket_cost_yuan=max_ticket_cost_yuan,
        budget_overage_tolerance_yuan=budget_overage_tolerance_yuan,
    )
    choose9_plan = _build_choose9_plan(
        raw_predictions,
        max_ticket_cost_yuan=max_ticket_cost_yuan,
        budget_overage_tolerance_yuan=budget_overage_tolerance_yuan,
    )
    choose9_keep = choose9_plan.keep
    choose9_drop = tuple(
        sorted(
            prediction.match.seq
            for prediction in raw_predictions
            if prediction.match.seq not in choose9_keep
        )
    )
    main_cost_yuan = ticket_cost_yuan(ticket_predictions)

    return TicketPlan(
        issue=issue,
        predictions=ticket_predictions,
        choose9_keep=choose9_keep,
        choose9_drop=choose9_drop,
        max_ticket_cost_yuan=max_ticket_cost_yuan,
        main_allocated_budget_yuan=max_ticket_cost_yuan,
        main_cost_yuan=main_cost_yuan,
        draw_hedge=None,
        line_portfolio=None,
        choose9_plan=choose9_plan,
        budget_tolerance_yuan=max(0, budget_overage_tolerance_yuan),
    )


def _build_line_portfolio(
    predictions: tuple[Prediction, ...],
    *,
    max_ticket_cost_yuan: int,
) -> LinePortfolioPlan:
    """Create distinct full-ticket lines with draw marginals preserved.

    Every draw retained by the model selection receives a line quota derived
    from its probability.  Quota lines are selected first and may cover
    several draw candidates at once; the remaining budget is filled with the
    highest-probability distinct candidates.  When every possible distinct
    line is purchased, the quota is capped at that finite combination space.
    """
    requested_lines = max(1, max_ticket_cost_yuan // STAKE_PER_LINE_YUAN)
    choice_sets = tuple(_line_choices(prediction) for prediction in predictions)
    total_combinations = 1
    for choices in choice_sets:
        total_combinations *= len(choices)
    line_limit = min(requested_lines, total_combinations)

    draw_targets: dict[int, int] = {}
    draw_probabilities: dict[int, float] = {}
    for index, (prediction, choices) in enumerate(zip(predictions, choice_sets)):
        counts = _allocate_line_counts(prediction, choices, line_limit)
        if "1" in choices:
            draw_targets[index] = counts.get("1", 0)
            draw_probabilities[index] = prediction.probabilities.get("1", 0.0)

    candidates = _portfolio_candidate_lines(
        predictions,
        choice_sets,
        draw_targets,
        line_limit=line_limit,
        total_combinations=total_combinations,
    )
    if line_limit == total_combinations:
        selected = set(candidates)
        full_coverage = _draw_line_counts(selected, draw_targets)
        draw_targets = {
            index: full_coverage[index]
            for index in draw_targets
        }
    else:
        selected = _select_quota_lines(
            candidates,
            predictions,
            draw_targets,
            line_limit=line_limit,
        )
    ordered = sorted(selected, key=lambda line: _line_log_probability(line, predictions), reverse=True)
    ordered = ordered[:line_limit]
    final_coverage = _draw_line_counts(ordered, draw_targets)
    candidate_indexes = tuple(index for index, target in draw_targets.items() if target > 0)
    pair_counts = [
        sum(1 for line in ordered if line[left] == "1" and line[right] == "1")
        for offset, left in enumerate(candidate_indexes)
        for right in candidate_indexes[offset + 1 :]
    ]
    draw_coverages = tuple(
        DrawLineCoverage(
            seq=predictions[index].match.seq,
            probability=round(draw_probabilities[index], 4),
            target_lines=target,
            actual_lines=final_coverage.get(index, 0),
        )
        for index, target in draw_targets.items()
        if target > 0
    )
    ticket_lines = tuple(
        TicketLine(
            outcomes=line,
            joint_probability=round(exp(_line_log_probability(line, predictions)), 12),
        )
        for line in ordered
    )
    return LinePortfolioPlan(
        lines=ticket_lines,
        draw_coverages=draw_coverages,
        allocated_budget_yuan=max_ticket_cost_yuan,
        cost_yuan=len(ticket_lines) * STAKE_PER_LINE_YUAN,
        multi_draw_lines=sum(
            1 for line in ordered if sum(line[index] == "1" for index in candidate_indexes) >= 2
        ),
        minimum_draw_pair_lines=min(pair_counts) if pair_counts else 0,
    )


def _portfolio_candidate_lines(
    predictions: tuple[Prediction, ...],
    choice_sets: tuple[tuple[str, ...], ...],
    draw_targets: dict[int, int],
    *,
    line_limit: int,
    total_combinations: int,
) -> set[tuple[str, ...]]:
    if total_combinations <= 20_000:
        return set(product(*choice_sets))

    candidates = {
        line
        for line, _ in _top_probability_lines(
            predictions,
            choice_sets,
            limit=min(500, total_combinations),
        )
    }
    rng = Random(310_032 + line_limit * 101 + total_combinations)

    def random_line(forced_draw_index: int | None = None) -> tuple[str, ...]:
        return tuple(
            "1" if index == forced_draw_index else rng.choice(choices)
            for index, choices in enumerate(choice_sets)
        )

    general_target = min(total_combinations, max(line_limit * 3, 2_000))
    attempts = 0
    while len(candidates) < general_target and attempts < general_target * 20:
        candidates.add(random_line())
        attempts += 1

    for index, target in draw_targets.items():
        required_candidates = min(total_combinations, max(target * 2, line_limit // 2, 100))
        available = sum(1 for line in candidates if line[index] == "1")
        attempts = 0
        while available < required_candidates and attempts < required_candidates * 40:
            line = random_line(index)
            before = len(candidates)
            candidates.add(line)
            if len(candidates) > before:
                available += 1
            attempts += 1
    return candidates


def _select_quota_lines(
    candidates: set[tuple[str, ...]],
    predictions: tuple[Prediction, ...],
    draw_targets: dict[int, int],
    *,
    line_limit: int,
) -> set[tuple[str, ...]]:
    draw_indexes = tuple(draw_targets)
    indexed = [
        (
            line,
            _line_log_probability(line, predictions),
            sum(1 << bit for bit, index in enumerate(draw_indexes) if line[index] == "1"),
        )
        for line in candidates
    ]
    indexed.sort(key=lambda item: item[1], reverse=True)
    selected: set[tuple[str, ...]] = set()
    coverage = {index: 0 for index in draw_indexes}

    while any(coverage[index] < draw_targets[index] for index in draw_indexes):
        deficit_mask = sum(
            1 << bit
            for bit, index in enumerate(draw_indexes)
            if coverage[index] < draw_targets[index]
        )
        best: tuple[tuple[str, ...], float, int] | None = None
        best_key = (-1, float("-inf"))
        for item in indexed:
            line, score, mask = item
            if line in selected:
                continue
            key = ((mask & deficit_mask).bit_count(), score)
            if key > best_key:
                best = item
                best_key = key
        if best is None or best_key[0] == 0 or len(selected) >= line_limit:
            raise ValueError("无法在唯一线路上限内满足全部平局配额。")
        line, _, _ = best
        selected.add(line)
        for index in draw_indexes:
            coverage[index] += int(line[index] == "1")

    for line, _, _ in indexed:
        if len(selected) >= line_limit:
            break
        selected.add(line)
    if len(selected) != line_limit:
        raise ValueError("候选线路不足，无法填满预算线路组合。")
    return selected


def _line_choices(prediction: Prediction) -> tuple[str, ...]:
    choices = prediction.analysis_picks or prediction.picks
    return tuple(
        sorted(set(choices), key=lambda outcome: prediction.probabilities.get(outcome, 0.0), reverse=True)
    )


def _allocate_line_counts(
    prediction: Prediction,
    choices: tuple[str, ...],
    line_count: int,
) -> dict[str, int]:
    total = sum(prediction.probabilities.get(outcome, 0.0) for outcome in choices)
    weights = {
        outcome: prediction.probabilities.get(outcome, 0.0) / max(total, 1e-12)
        for outcome in choices
    }
    exact = {outcome: weights[outcome] * line_count for outcome in choices}
    counts = {outcome: int(exact[outcome]) for outcome in choices}
    remaining = line_count - sum(counts.values())
    ranked = sorted(
        choices,
        key=lambda outcome: (exact[outcome] - counts[outcome], weights[outcome], outcome),
        reverse=True,
    )
    for outcome in ranked[:remaining]:
        counts[outcome] += 1
    return counts


def _top_probability_lines(
    predictions: tuple[Prediction, ...],
    choice_sets: tuple[tuple[str, ...], ...],
    *,
    limit: int,
) -> list[tuple[tuple[str, ...], float]]:
    start = tuple(0 for _ in choice_sets)
    start_line = tuple(choices[0] for choices in choice_sets)
    heap: list[tuple[float, tuple[int, ...]]] = [
        (-_line_log_probability(start_line, predictions), start)
    ]
    visited = {start}
    result: list[tuple[tuple[str, ...], float]] = []
    while heap and len(result) < limit:
        negative_score, indexes = heappop(heap)
        line = tuple(choices[index] for choices, index in zip(choice_sets, indexes))
        result.append((line, -negative_score))
        for dimension, choices in enumerate(choice_sets):
            if indexes[dimension] + 1 >= len(choices):
                continue
            neighbor = list(indexes)
            neighbor[dimension] += 1
            state = tuple(neighbor)
            if state in visited:
                continue
            visited.add(state)
            neighbor_line = tuple(
                dimension_choices[index]
                for dimension_choices, index in zip(choice_sets, state)
            )
            heappush(heap, (-_line_log_probability(neighbor_line, predictions), state))
    return result


def _line_log_probability(line: tuple[str, ...], predictions: tuple[Prediction, ...]) -> float:
    return sum(
        log(max(prediction.probabilities.get(outcome, 0.0), 1e-12))
        for prediction, outcome in zip(predictions, line)
    )


def _draw_line_counts(
    lines: object,
    draw_targets: dict[int, int],
) -> dict[int, int]:
    return {
        index: sum(1 for line in lines if line[index] == "1")
        for index in draw_targets
    }


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

    # The gates above may veto unsupported candidates, but ranking uses the
    # final model output once. Market and mathematical values are already in
    # that probability and must not be added again as separate bonuses.
    score = draw_probability - 0.05 * top_gap
    return score, tuple(evidence)


def _draw_hedge_information_support(prediction: Prediction) -> tuple[bool, str]:
    return _independent_draw_information_support(prediction, minimum_total=1.20)


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

    # Supporting sources are admission gates only. The final probability has
    # already blended them, so candidate ranking must not award them again.
    score = draw_probability - 0.60 * top_gap
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
    return _independent_draw_information_support(prediction)


def _independent_draw_information_support(
    prediction: Prediction,
    *,
    minimum_total: float = 0.0,
) -> tuple[bool, str]:
    """Return only draw context owned by the information layer.

    Reliability is zero for xG/goals and draw-rate features already assigned
    to Dixon-Coles, preventing those values from qualifying twice under two
    different labels.
    """
    profile = build_fundamental_profile(prediction.match)
    expected_total, recent_draw_rate = _draw_context(prediction.match)
    low_scoring = (
        profile.reliabilities.get("low_total", 0.0) > 0
        and expected_total is not None
        and minimum_total <= expected_total <= 2.40
    )
    draw_prone = (
        profile.reliabilities.get("draw_rate", 0.0) > 0
        and recent_draw_rate is not None
        and recent_draw_rate >= 0.30
    )
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


def _build_choose9_plan(
    predictions: tuple[Prediction, ...],
    *,
    max_ticket_cost_yuan: int,
    budget_overage_tolerance_yuan: int = 0,
) -> Choose9Plan:
    """Jointly optimize the nine fixtures and their rectangular selections.

    This is intentionally independent from the fourteen-match ticket.  Each
    fixture offers its strongest single, double, and three-way coverage; an
    exact dynamic program then chooses exactly nine fixtures and a product of
    choice counts that fits the choose-nine budget while maximizing estimated
    joint coverage.
    """
    effective_budget_yuan = max_ticket_cost_yuan + max(0, budget_overage_tolerance_yuan)
    max_units = max(1, effective_budget_yuan // STAKE_PER_LINE_YUAN)
    # (selected fixture count, ticket units) -> (log coverage, predictions)
    states: dict[tuple[int, int], tuple[float, tuple[Prediction, ...]]] = {
        (0, 1): (0.0, ())
    }
    for prediction in predictions:
        next_states = dict(states)  # Skipping this fixture is a valid choice.
        for (selected_count, units), (score, selected) in states.items():
            if selected_count >= 9:
                continue
            for option in _choose9_prediction_options(prediction):
                new_units = units * len(option.picks)
                if new_units > max_units:
                    continue
                coverage = _choose9_coverage_probability(option)
                key = (selected_count + 1, new_units)
                candidate = (score + log(max(coverage, 1e-12)), (*selected, option))
                existing = next_states.get(key)
                if existing is None or _choose9_state_key(candidate) > _choose9_state_key(existing):
                    next_states[key] = candidate
        states = next_states

    candidates = [
        (units, value)
        for (selected_count, units), value in states.items()
        if selected_count == 9
    ]
    if not candidates:
        raise ValueError("任九预算不足，至少需要 2 元购买 1 注。")

    units, (score, selected_predictions) = max(
        candidates,
        key=lambda item: (_choose9_state_key(item[1]), item[0]),
    )
    ordered = tuple(sorted(selected_predictions, key=lambda item: item.match.seq))
    return Choose9Plan(
        predictions=ordered,
        allocated_budget_yuan=max_ticket_cost_yuan,
        line_count=units,
        cost_yuan=units * STAKE_PER_LINE_YUAN,
        joint_coverage_probability=round(exp(score), 8),
        budget_tolerance_yuan=max(0, budget_overage_tolerance_yuan),
    )


def _choose9_prediction_options(prediction: Prediction) -> tuple[Prediction, ...]:
    ranked_outcomes = tuple(
        sorted(
            ("3", "1", "0"),
            key=lambda outcome: (
                _coverage_value(prediction, outcome),
                prediction.probabilities.get(outcome, 0.0),
                -("3", "1", "0").index(outcome),
            ),
            reverse=True,
        )
    )
    return tuple(
        replace(
            prediction,
            picks=("3", "1", "0") if choice_count == 3 else ranked_outcomes[:choice_count],
            original_picks=prediction.analysis_picks,
            budget_adjusted=(
                (("3", "1", "0") if choice_count == 3 else ranked_outcomes[:choice_count])
                != prediction.analysis_picks
            ),
            budget_forced_single=False,
            budget_removed_picks=tuple(
                outcome
                for outcome in prediction.analysis_picks
                if outcome
                not in (("3", "1", "0") if choice_count == 3 else ranked_outcomes[:choice_count])
            ),
        )
        for choice_count in (1, 2, 3)
    )


def _choose9_coverage_probability(prediction: Prediction) -> float:
    return min(
        1.0,
        sum(prediction.probabilities.get(outcome, 0.0) for outcome in prediction.picks),
    )


def _choose9_state_key(
    state: tuple[float, tuple[Prediction, ...]],
) -> tuple[float, float, tuple[int, ...]]:
    score, selected = state
    # Deterministic ties: prefer stronger top outcomes and then earlier issue
    # sequence numbers.  The coverage objective remains the primary criterion.
    top_sum = sum(max(prediction.probabilities.values()) for prediction in selected)
    sequences = tuple(-prediction.match.seq for prediction in selected)
    return score, top_sum, sequences


def _pick_coverage_probability(prediction: Prediction) -> float:
    return sum(prediction.probabilities.get(outcome, 0.0) for outcome in prediction.analysis_picks)


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
    budget_overage_tolerance_yuan: int = 0,
) -> tuple[Prediction, ...]:
    if max_ticket_cost_yuan <= 0:
        return predictions

    effective_budget_yuan = max_ticket_cost_yuan + max(0, budget_overage_tolerance_yuan)
    max_units = max(1, effective_budget_yuan // STAKE_PER_LINE_YUAN)
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
