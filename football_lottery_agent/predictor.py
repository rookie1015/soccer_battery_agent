from __future__ import annotations

from math import exp, factorial, sqrt

from .dixon_coles import DixonColesForecast, forecast as dixon_coles_forecast
from .models import Match, Prediction, Scoreline


OUTCOME_LABELS = {"3": "主胜", "1": "平", "0": "客胜"}
SELECTION_OUTCOME_LABELS = {"3": "主胜", "1": "平局", "0": "客胜"}
SECONDARY_RAW_GAP_LIMIT = 0.04
SECONDARY_EVIDENCE_MARGIN = 0.015
MAX_SECONDARY_SCORE_ADJUSTMENT = 0.03
DEFAULT_SELECTION_POLICY = {
    "single_top": 0.52,
    "single_spread": 0.14,
    "double_top": 0.44,
    "double_spread": 0.06,
    "triple_third": 0.25,
    "triple_gap": 0.02,
    "secondary_raw_gap": SECONDARY_RAW_GAP_LIMIT,
    "secondary_evidence_margin": SECONDARY_EVIDENCE_MARGIN,
}


def predict_match(
    match: Match,
    model_weights: dict[str, float] | None = None,
    evidence_aware_secondary: bool = False,
    selection_policy: dict[str, float] | None = None,
) -> Prediction:
    odds_probs = _odds_to_probabilities(match)
    signal_scores = _signal_scores(match)
    math_forecast = dixon_coles_forecast(match)
    odds_weight, signal_weight, math_weight = _blend_weights(match, math_forecast, model_weights)

    mixed = {
        outcome: (
            odds_weight * odds_probs[outcome]
            + signal_weight * signal_scores[outcome]
            + math_weight * math_forecast.probabilities[outcome]
        )
        for outcome in ("3", "1", "0")
    }
    probabilities = _normalize(mixed)
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)

    top_outcome, top_prob = ranked[0]
    second_outcome, second_prob = ranked[1]
    spread = top_prob - second_prob

    selection_scores = (
        _full_analysis_selection_scores(
            match,
            probabilities,
            odds_probs,
            signal_scores,
            math_forecast,
        )
        if evidence_aware_secondary
        else {}
    )
    picks = _select_picks(ranked, selection_scores=selection_scores, selection_policy=selection_policy)

    confidence = round(top_prob * 100, 1)
    risk = _risk_label(top_prob, spread, len(picks))
    scorelines = _predict_scorelines(match, probabilities, math_forecast)
    reasons = _build_reasons(match, probabilities, ranked, spread, math_forecast)
    if selection_scores:
        reasons.append(_selection_score_reason(selection_scores))
    reasons.insert(
        0,
        _selection_reason(
            picks,
            probabilities,
            selection_scores=selection_scores,
        ),
    )

    return Prediction(
        match=match,
        probabilities={key: round(value, 4) for key, value in probabilities.items()},
        picks=picks,
        scorelines=scorelines,
        confidence=confidence,
        risk=risk,
        reasons=tuple(reasons),
        selection_scores=selection_scores,
    )


SELECTION_REASON_PREFIX = "选择依据："


def selection_reason(prediction: Prediction) -> str:
    budget_adjusted = any(
        reason.startswith(("预算调整：", "预算约束："))
        for reason in prediction.reasons
    )
    return _selection_reason(
        prediction.picks,
        prediction.probabilities,
        selection_scores=prediction.selection_scores,
        budget_adjusted=budget_adjusted,
    )


def selection_reason_from_values(
    picks: tuple[str, ...],
    probabilities: dict[str, float],
) -> str:
    return _selection_reason(picks, probabilities)


def _selection_reason(
    picks: tuple[str, ...],
    probabilities: dict[str, float],
    *,
    selection_scores: dict[str, float] | None = None,
    budget_adjusted: bool = False,
) -> str:
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    selected = set(picks)
    coverage = sum(probabilities.get(outcome, 0.0) for outcome in picks)
    probability_text = "、".join(
        f"{SELECTION_OUTCOME_LABELS[outcome]}({outcome}) {probabilities.get(outcome, 0.0):.1%}"
        for outcome in ("3", "1", "0")
    )
    budget_text = "本场最终选择经过整张票预算压缩；被排除项仍有发生可能。" if budget_adjusted else ""

    if len(picks) == 3:
        spread = ranked[0][1] - ranked[-1][1]
        return (
            f"{SELECTION_REASON_PREFIX}3/1/0 全包。{probability_text}；"
            f"最高与最低仅差 {spread:.1%}，没有足够把握排除任何一项，"
            "因此三种赛果全部保留，覆盖模型概率 100.0%。"
        )

    selected_text = "、".join(
        f"{SELECTION_OUTCOME_LABELS[outcome]}({outcome}) {probabilities.get(outcome, 0.0):.1%}"
        for outcome in picks
    )
    excluded = [outcome for outcome in ("3", "1", "0") if outcome not in selected]
    excluded_text = "、".join(
        f"{SELECTION_OUTCOME_LABELS[outcome]}({outcome}) {probabilities.get(outcome, 0.0):.1%}"
        for outcome in excluded
    )
    evidence_text = ""
    if selection_scores and len(picks) == 2:
        evidence_text = "第二选项还结合赔率、基本面和数学模型的证据排序复核。"

    if len(picks) == 2:
        weakest_selected = min(probabilities.get(outcome, 0.0) for outcome in picks)
        best_excluded = max((probabilities.get(outcome, 0.0) for outcome in excluded), default=0.0)
        gap = weakest_selected - best_excluded
        comparison = (
            f"入选边缘项比被排除项高 {gap:.1%}。"
            if gap >= 0
            else f"入选边缘项原始概率比被排除项低 {-gap:.1%}，最终保留由证据排序决定。"
        )
        return (
            f"{SELECTION_REASON_PREFIX}双选 {picks[0]}/{picks[1]}，保留 {selected_text}，"
            f"合计覆盖模型概率 {coverage:.1%}；排除 {excluded_text}。"
            f"{comparison}{evidence_text}{budget_text}"
        )

    selected_probability = probabilities.get(picks[0], 0.0)
    best_excluded = max((probabilities.get(outcome, 0.0) for outcome in excluded), default=0.0)
    lead = selected_probability - best_excluded
    comparison = (
        f"入选项领先被排除项中的最高值 {lead:.1%}。"
        if lead >= 0
        else f"入选项原始概率低于被排除项中的最高值 {-lead:.1%}，最终取舍由证据排序或预算决定。"
    )
    return (
        f"{SELECTION_REASON_PREFIX}单选 {picks[0]}，保留 {selected_text}，"
        f"覆盖模型概率 {coverage:.1%}；排除 {excluded_text}。"
        f"{comparison}{budget_text}"
    )


def predict_issue(
    matches: tuple[Match, ...],
    model_weights: dict[str, float] | None = None,
    evidence_aware_secondary: bool = False,
    selection_policy: dict[str, float] | None = None,
) -> tuple[Prediction, ...]:
    return tuple(
        predict_match(
            match,
            model_weights=model_weights,
            evidence_aware_secondary=evidence_aware_secondary,
            selection_policy=selection_policy,
        )
        for match in matches
    )


def _select_picks(
    ranked: list[tuple[str, float]],
    selection_scores: dict[str, float] | None = None,
    selection_policy: dict[str, float] | None = None,
) -> tuple[str, ...]:
    policy = {**DEFAULT_SELECTION_POLICY, **(selection_policy or {})}
    top_outcome, top_prob = ranked[0]
    second_outcome, second_prob = ranked[1]
    third_outcome, third_prob = ranked[2]
    spread = top_prob - second_prob

    if top_prob >= policy["single_top"] and spread >= policy["single_spread"]:
        return (top_outcome,)
    if top_prob >= policy["double_top"] and spread >= policy["double_spread"]:
        evidence_choice = _resolved_secondary_choice(
            second_outcome,
            third_outcome,
            second_prob - third_prob,
            selection_scores,
            raw_gap_limit=policy["secondary_raw_gap"],
            evidence_margin=policy["secondary_evidence_margin"],
        )
        if third_prob >= policy["triple_third"] and second_prob - third_prob < policy["triple_gap"] and evidence_choice is None:
            return ("3", "1", "0")
        return (top_outcome, evidence_choice or second_outcome)
    return ("3", "1", "0")


def _resolved_secondary_choice(
    second_outcome: str,
    third_outcome: str,
    raw_gap: float,
    selection_scores: dict[str, float] | None,
    raw_gap_limit: float = SECONDARY_RAW_GAP_LIMIT,
    evidence_margin: float = SECONDARY_EVIDENCE_MARGIN,
) -> str | None:
    if not selection_scores or raw_gap > raw_gap_limit:
        return None
    ranked = sorted(
        (second_outcome, third_outcome),
        key=lambda outcome: selection_scores.get(outcome, 0.0),
        reverse=True,
    )
    margin = selection_scores.get(ranked[0], 0.0) - selection_scores.get(ranked[1], 0.0)
    return ranked[0] if margin >= evidence_margin else None


def _full_analysis_selection_scores(
    match: Match,
    probabilities: dict[str, float],
    odds_probabilities: dict[str, float],
    signal_probabilities: dict[str, float],
    math_forecast: DixonColesForecast,
) -> dict[str, float]:
    """Build secondary-pick scores only when full analysis found real evidence.

    These scores do not replace or relabel the calibrated 1X2 probabilities. They
    only resolve close second/third choices and guide budget downgrades. At least
    one non-market evidence family is required, so a failed full-data collection
    cannot silently turn into a different odds-only strategy.
    """
    contributors: list[tuple[float, dict[str, float]]] = []
    if match.sources.get("odds") != "default_placeholder":
        market = _market_selection_probabilities(match, odds_probabilities)
        contributors.append((_market_evidence_weight(match), market))
    if _has_informative_signals(match):
        contributors.append((0.25, signal_probabilities))
    if math_forecast.data_quality_score >= 0.50 and math_forecast.data_quality != "signal_fallback":
        contributors.append((0.40 * math_forecast.data_quality_score, math_forecast.probabilities))

    if len(contributors) < 2:
        return {}

    total_weight = sum(weight for weight, _ in contributors)
    consensus = {
        outcome: sum(weight * values[outcome] for weight, values in contributors) / total_weight
        for outcome in ("3", "1", "0")
    }
    top_outcome = max(probabilities, key=probabilities.get)
    scores = dict(probabilities)
    for outcome in ("3", "1", "0"):
        if outcome == top_outcome:
            continue
        # Keep the primary outcome anchored to the calibrated blend. Only close
        # secondary candidates receive a bounded evidence-based adjustment.
        adjustment = 0.45 * (consensus[outcome] - probabilities[outcome])
        adjustment = max(-MAX_SECONDARY_SCORE_ADJUSTMENT, min(MAX_SECONDARY_SCORE_ADJUSTMENT, adjustment))
        scores[outcome] = probabilities[outcome] + adjustment
    return {outcome: round(score, 6) for outcome, score in scores.items()}


def _has_informative_signals(match: Match) -> bool:
    audit = match.sources.get("collection_audit") if isinstance(match.sources, dict) else None
    if isinstance(audit, dict) and audit.get("mode") == "full":
        injuries = audit.get("injuries") if isinstance(audit.get("injuries"), dict) else {}
        intelligence = audit.get("intelligence") if isinstance(audit.get("intelligence"), dict) else {}
        history = audit.get("history") if isinstance(audit.get("history"), dict) else {}
        strength = audit.get("strength") if isinstance(audit.get("strength"), dict) else {}
        xg = audit.get("xg") if isinstance(audit.get("xg"), dict) else {}
        return bool(
            (injuries.get("status") == "available" and int(injuries.get("count") or 0) > 0)
            or intelligence.get("status") == "available"
            or history.get("status") == "available"
            or strength.get("status") in {"complete", "partial"}
            or xg.get("status") in {"complete", "partial"}
        )

    signals = match.signals
    return any(
        abs(value - baseline) >= 0.02
        for value, baseline in (
            (signals.home_form, 0.5),
            (signals.away_form, 0.5),
            (signals.home_motivation, 0.5),
            (signals.away_motivation, 0.5),
            (signals.home_injury_impact, 0.0),
            (signals.away_injury_impact, 0.0),
            (signals.schedule_pressure_home, 0.0),
            (signals.schedule_pressure_away, 0.0),
        )
    )


def _market_evidence_weight(match: Match) -> float:
    market = match.sources.get("odds_market") if isinstance(match.sources, dict) else {}
    market = market if isinstance(market, dict) else {}
    dispersion = market.get("market_dispersion")
    if not isinstance(dispersion, dict):
        return 0.35
    values = [_probability_number(dispersion.get(outcome)) for outcome in ("3", "1", "0")]
    available = [value for value in values if value is not None]
    average = sum(available) / len(available) if available else 0.0
    return 0.35 * max(0.60, 1.0 - average * 2.0)


def _market_selection_probabilities(match: Match, fallback: dict[str, float]) -> dict[str, float]:
    market = match.sources.get("odds_market") if isinstance(match.sources, dict) else {}
    market = market if isinstance(market, dict) else {}
    consensus = market.get("market_consensus")
    values = dict(fallback)
    if isinstance(consensus, dict):
        parsed = {outcome: _probability_number(consensus.get(outcome)) for outcome in ("3", "1", "0")}
        if all(value is not None for value in parsed.values()):
            values = _normalize({outcome: float(value) for outcome, value in parsed.items()})

    movement = market.get("market_movement")
    if isinstance(movement, dict):
        for outcome in ("3", "1", "0"):
            try:
                shift = float(movement.get(outcome) or 0.0)
            except (TypeError, ValueError):
                shift = 0.0
            values[outcome] += max(-0.012, min(0.012, shift * 0.30))

    try:
        handicap = float(
            market.get("asian_current_line")
            if market.get("asian_current_line") is not None
            else market.get("spread_home_point") or 0.0
        )
        price_edge = float(market.get("asian_home_price_edge") or 0.0)
    except (TypeError, ValueError):
        handicap = 0.0
        price_edge = 0.0
    home_adjustment = max(-0.015, min(0.015, -handicap * 0.009 + price_edge * 0.025))
    values["3"] += home_adjustment
    values["0"] -= home_adjustment
    return _normalize({outcome: max(0.01, value) for outcome, value in values.items()})


def _selection_score_reason(selection_scores: dict[str, float]) -> str:
    ordered = sorted(selection_scores, key=selection_scores.get, reverse=True)
    summary = "/".join(
        f"{OUTCOME_LABELS[outcome]} {selection_scores[outcome]:.1%}"
        for outcome in ordered
    )
    return f"完整分析第二选项复核：赔率、基本面与数学模型的证据排序分为 {summary}。"


def _blend_weights(
    match: Match,
    math_forecast: DixonColesForecast,
    model_weights: dict[str, float] | None,
) -> tuple[float, float, float]:
    placeholder_odds = match.sources.get("odds") == "default_placeholder"
    if not model_weights:
        if placeholder_odds:
            if math_forecast.data_quality == "strength":
                return (0.20, 0.52, 0.28)
            if math_forecast.data_quality in {"partial_strength", "hierarchical"}:
                return (0.20, 0.56, 0.24)
            return (0.20, 0.60, 0.20)
        return {
            "strength": (0.55, 0.22, 0.23),
            "partial_strength": (0.58, 0.23, 0.19),
            "hierarchical": (0.59, 0.23, 0.18),
            "hybrid_fallback": (0.61, 0.24, 0.15),
            "signal_fallback": (0.63, 0.25, 0.12),
        }.get(math_forecast.data_quality, (0.63, 0.25, 0.12))

    odds = max(0.0, float(model_weights.get("odds", 0.55)))
    signals = max(0.0, float(model_weights.get("signals", 0.22)))
    math = max(0.0, float(model_weights.get("dixon_coles", 0.23)))
    total = odds + signals + math
    if total <= 0:
        return (0.20, 0.60, 0.20) if placeholder_odds else (0.55, 0.22, 0.23)
    odds, signals, math = odds / total, signals / total, math / total

    if placeholder_odds and odds > 0.20:
        odds = 0.20
        non_market_total = signals + math
        if non_market_total <= 0:
            signals, math = 0.60, 0.20
        else:
            signals, math = (
                0.80 * signals / non_market_total,
                0.80 * math / non_market_total,
            )
    return odds, signals, math


def _odds_to_probabilities(match: Match) -> dict[str, float]:
    if match.sources.get("odds") == "default_placeholder":
        return {"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}
    market = match.sources.get("odds_market") if isinstance(match.sources, dict) else {}
    consensus = market.get("market_consensus") if isinstance(market, dict) else None
    if isinstance(consensus, dict):
        parsed = {outcome: _probability_number(consensus.get(outcome)) for outcome in ("3", "1", "0")}
        if all(value is not None for value in parsed.values()):
            return _normalize({outcome: float(value) for outcome, value in parsed.items()})
    implied = {
        "3": 1.0 / match.odds.home,
        "1": 1.0 / match.odds.draw,
        "0": 1.0 / match.odds.away,
    }
    return _normalize(implied)


def _signal_scores(match: Match) -> dict[str, float]:
    s = match.signals
    home_strength = 0.52 + 0.28 * (s.home_form - s.away_form)
    home_strength += 0.16 * (s.home_motivation - s.away_motivation)
    home_strength += 0.14 * (s.away_injury_impact - s.home_injury_impact)
    home_strength += 0.10 * (s.schedule_pressure_away - s.schedule_pressure_home)

    away_strength = 1.0 - home_strength
    balance = 1.0 - abs(home_strength - 0.5) * 2.0
    balance = max(0.0, balance)
    draw_score = 0.20 + 0.30 * balance

    expected_total, recent_draw_rate = _draw_context(match)
    if expected_total is not None:
        low_score_adjustment = min(0.18, max(-0.12, (2.35 - expected_total) * 0.18))
        draw_score += low_score_adjustment * balance
    if recent_draw_rate is not None:
        draw_rate_adjustment = min(0.08, max(-0.08, (recent_draw_rate - 0.27) * 0.40))
        draw_score += draw_rate_adjustment * balance

    raw = {
        "3": max(0.05, home_strength),
        "1": max(0.08, draw_score),
        "0": max(0.05, away_strength),
    }
    return _normalize(raw)


def _draw_context(match: Match) -> tuple[float | None, float | None]:
    source = match.sources.get("strength_model") if isinstance(match.sources, dict) else {}
    source = source if isinstance(source, dict) else {}

    expected_total = None
    market = match.sources.get("odds_market") if isinstance(match.sources, dict) else {}
    market = market if isinstance(market, dict) else {}
    market_total = _positive_number(market.get("total_points"))
    for prefix in ("xg", "goals"):
        home_for = _positive_number(source.get(f"home_{prefix}_for"))
        home_against = _positive_number(source.get(f"home_{prefix}_against"))
        away_for = _positive_number(source.get(f"away_{prefix}_for"))
        away_against = _positive_number(source.get(f"away_{prefix}_against"))
        if None not in (home_for, home_against, away_for, away_against):
            expected_home = sqrt(home_for * away_against)
            expected_away = sqrt(away_for * home_against)
            expected_total = expected_home + expected_away
            break
    if expected_total is None and market_total is not None:
        expected_total = market_total

    draw_rates = [
        value
        for value in (
            _probability_number(source.get("home_draw_rate")),
            _probability_number(source.get("away_draw_rate")),
        )
        if value is not None
    ]
    sina_detail = match.sources.get("sina_detail") if isinstance(match.sources, dict) else {}
    sina_detail = sina_detail if isinstance(sina_detail, dict) else {}
    history_draw_rate = _probability_number(sina_detail.get("history_draw_rate"))
    history_matches = int(sina_detail.get("history_matches") or 0)
    if history_draw_rate is not None and history_matches:
        # H2H is supporting evidence, not a standalone forecast. Shrink it
        # toward the generic draw baseline before combining it with team form.
        shrunk_history_rate = (history_draw_rate * min(history_matches, 10) + 0.27 * 6) / (min(history_matches, 10) + 6)
        draw_rates.append(shrunk_history_rate)
    recent_draw_rate = sum(draw_rates) / len(draw_rates) if draw_rates else None
    return expected_total, recent_draw_rate


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _probability_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, number))


def _normalize(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        return {key: 1.0 / len(values) for key in values}
    return {key: value / total for key, value in values.items()}


def _risk_label(top_prob: float, spread: float, pick_count: int) -> str:
    if pick_count == 1 and top_prob >= 0.56 and spread >= 0.18:
        return "低"
    if pick_count <= 2 and top_prob >= 0.46 and spread >= 0.07:
        return "中"
    return "高"


def _predict_scorelines(
    match: Match,
    probabilities: dict[str, float],
    math_forecast: DixonColesForecast | None = None,
    limit: int = 3,
) -> tuple[Scoreline, ...]:
    if math_forecast and math_forecast.data_quality_score >= 0.50:
        home_xg, away_xg = math_forecast.home_xg, math_forecast.away_xg
    else:
        home_xg, away_xg = _fit_expected_goals(match, probabilities)
    raw: list[Scoreline] = []
    for home_goals in range(6):
        for away_goals in range(6):
            probability = _poisson_probability(home_goals, home_xg) * _poisson_probability(away_goals, away_xg)
            raw.append(Scoreline(home_goals, away_goals, probability))

    total = sum(item.probability for item in raw)
    normalized = [
        Scoreline(item.home_goals, item.away_goals, item.probability / total)
        for item in raw
        if total > 0
    ]
    return tuple(
        sorted(normalized, key=lambda item: item.probability, reverse=True)[:limit]
    )


def _fit_expected_goals(match: Match, probabilities: dict[str, float]) -> tuple[float, float]:
    target_home = probabilities["3"]
    target_draw = probabilities["1"]
    target_away = probabilities["0"]
    target_total = _target_total_goals(match, probabilities)
    best_home = 1.2
    best_away = 1.0
    best_error = float("inf")

    for home_step in range(25, 71):
        home_xg = home_step / 20.0
        for away_step in range(10, 61):
            away_xg = away_step / 20.0
            outcome = _score_outcome_probabilities(home_xg, away_xg)
            total_goals = home_xg + away_xg
            error = (
                (outcome["3"] - target_home) ** 2
                + (outcome["1"] - target_draw) ** 2
                + (outcome["0"] - target_away) ** 2
                + 0.10 * (total_goals - target_total) ** 2
            )
            if error < best_error:
                best_error = error
                best_home = home_xg
                best_away = away_xg
    return best_home, best_away


def _target_total_goals(match: Match, probabilities: dict[str, float]) -> float:
    s = match.signals
    mismatch = abs(probabilities["3"] - probabilities["0"])
    form_gap = abs(s.home_form - s.away_form)
    injury_drag = 0.15 * (s.home_injury_impact + s.away_injury_impact)
    schedule_drag = 0.10 * (s.schedule_pressure_home + s.schedule_pressure_away)
    total = 2.25 + 0.50 * mismatch + 0.20 * form_gap - injury_drag - schedule_drag
    return min(3.20, max(1.80, total))


def _score_outcome_probabilities(home_xg: float, away_xg: float) -> dict[str, float]:
    result = {"3": 0.0, "1": 0.0, "0": 0.0}
    for home_goals in range(8):
        home_prob = _poisson_probability(home_goals, home_xg)
        for away_goals in range(8):
            score_prob = home_prob * _poisson_probability(away_goals, away_xg)
            if home_goals > away_goals:
                result["3"] += score_prob
            elif home_goals == away_goals:
                result["1"] += score_prob
            else:
                result["0"] += score_prob
    return _normalize(result)


def _poisson_probability(goals: int, expected_goals: float) -> float:
    return exp(-expected_goals) * expected_goals**goals / factorial(goals)


def _build_reasons(
    match: Match,
    probabilities: dict[str, float],
    ranked: list[tuple[str, float]],
    spread: float,
    math_forecast: DixonColesForecast,
) -> list[str]:
    top, top_prob = ranked[0]
    second, second_prob = ranked[1]
    reasons = [
        f"综合赔率和基本面，{OUTCOME_LABELS[top]}最高，约 {top_prob:.0%}；次选{OUTCOME_LABELS[second]}约 {second_prob:.0%}。",
    ]
    math_probs = math_forecast.probabilities
    reasons.append(
        "Dixon-Coles 数学模型："
        f"预期进球 {math_forecast.home_xg:.2f}-{math_forecast.away_xg:.2f}，"
        f"胜/平/负 {math_probs['3']:.0%}/{math_probs['1']:.0%}/{math_probs['0']:.0%}。"
    )
    if math_forecast.data_quality == "partial_strength":
        reasons.append("数学模型取得部分 xG/xGA，已按样本量向联赛均值收缩，避免少量比赛被过度放大。")
    elif math_forecast.data_quality == "hierarchical":
        reasons.append("数学模型暂缺完整 xG，已用近期进失球与联赛先验做分层估计，保留中等权重。")
    elif math_forecast.data_quality == "hybrid_fallback":
        reasons.append("仅一方取得可靠实力样本，另一方使用近期状态先验，数学权重已按数据质量调整。")
    elif math_forecast.data_quality == "signal_fallback":
        reasons.append("数学模型未取得球队进失球或 xG 样本，仅保留低权重状态基线。")

    audit_reason = _collection_audit_reason(match)
    if audit_reason:
        reasons.append(audit_reason)

    fallback_reason = _network_fallback_reason(match)
    if fallback_reason:
        reasons.append(fallback_reason)

    if spread < 0.06:
        reasons.append("前两项概率接近，建议提高防守或在任9中谨慎处理。")
    elif top == "3" and probabilities["3"] >= 0.5:
        reasons.append("主胜优势较明确，可作为候选胆材。")
    elif top == "0" and probabilities["0"] >= 0.42:
        reasons.append("客胜倾向不弱，但客场天然波动更高。")

    s = match.signals
    if s.home_injury_impact >= 0.25:
        reasons.append("主队伤停影响偏高。")
    if s.away_injury_impact >= 0.25:
        reasons.append("客队伤停影响偏高。")
    if s.schedule_pressure_home >= 0.35 or s.schedule_pressure_away >= 0.35:
        reasons.append("赛程压力需要临场继续跟踪。")
    reasons.extend(_select_notes(match.notes))
    return reasons


def _collection_audit_reason(match: Match) -> str:
    audit = match.sources.get("collection_audit") if isinstance(match.sources, dict) else {}
    if not isinstance(audit, dict) or audit.get("mode") != "full":
        return ""
    labels = {
        "odds": "赔率",
        "news": "新闻",
        "injuries": "伤停",
        "intelligence": "情报",
        "strength": "实力",
        "xg": "xG",
        "history": "交锋",
        "odds_movement": "赔率变化",
        "asian_handicap": "亚洲让球",
        "totals": "大小球",
        "mainstream_media": "主流媒体",
        "polymarket": "Polymarket",
    }
    available = []
    missing = []
    for key, label in labels.items():
        item = audit.get(key) if isinstance(audit.get(key), dict) else {}
        status = str(item.get("status") or "")
        if status in {"available", "complete", "partial", "confirmed_empty"}:
            available.append(label)
        else:
            explanation = _collection_gap_explanation(key, item)
            missing.append(f"{label}（{explanation}）" if explanation else label)
    available_text = "、".join(available) or "无"
    missing_text = "、".join(missing) or "无"
    usage = match.sources.get("data_usage") if isinstance(match.sources, dict) else {}
    numerical = "、".join(usage.get("numerical") or []) if isinstance(usage, dict) else ""
    display_only = "、".join(usage.get("display_only") or []) if isinstance(usage, dict) else ""
    suffix = f"；数值判断 {numerical or '无'}；仅展示 {display_only or '无'}"
    return f"完整分析资料审计：有效 {available_text}；缺失或未匹配 {missing_text}{suffix}。"


def _collection_gap_explanation(key: str, item: dict[str, object]) -> str:
    status = str(item.get("status") or "")
    if key == "news" and status == "empty_after_fallbacks":
        return "多源检索后没有同时匹配主客队的标题"
    if key == "mainstream_media" and status == "empty":
        return "主流媒体标题未匹配到本场球队"
    if key == "strength":
        reason = str(item.get("reason") or "")
        count = int(item.get("candidate_count") or 0)
        sofa = str(item.get("sofascore_status") or "")
        if status == "matched_no_samples":
            detail = "FotMob球队身份已匹配，但双方近期赛果或可比较实力样本不足"
        elif reason == "ambiguous_context_missing_aliases":
            detail = f"FotMob同联赛同时间存在{count}场候选，双语球队身份未唯一确认"
        elif reason == "no_fixture_at_kickoff":
            detail = "FotMob没有同联赛同开球时间的赛事"
        elif reason == "no_candidates":
            detail = "FotMob没有赛事候选"
        else:
            detail = "FotMob球队身份未匹配"
        return f"{detail}，SofaScore访问受限" if sofa == "blocked" else detail
    if key == "xg":
        reason = str(item.get("reason") or "")
        if reason == "team_identity_unmatched":
            return "球队身份未匹配，无法取得球队ID和xG样本"
        if reason == "provider_has_no_xg_samples":
            return "球队已匹配，但供应商近期比赛没有xG样本"
    if key == "totals" and status == "not_available_from_provider":
        return "当前赔率源没有提供大小球盘口"
    if key == "polymarket" and status == "unmatched":
        return "活跃市场中没有匹配到本场比赛"
    return {
        "request_failed": "数据源请求失败",
        "provider_error": "供应商返回错误",
        "missing_match_id": "赛程缺少供应商比赛ID",
        "not_requested": "本次未请求",
        "not_available_from_provider": "当前供应商不提供",
        "empty": "接口返回空或没有匹配记录",
        "unmatched": "没有匹配到对应记录",
        "missing": "没有有效样本",
    }.get(status, "")


def _network_fallback_reason(match: Match) -> str:
    fallback = match.sources.get("analysis_network_fallback") if isinstance(match.sources, dict) else {}
    if not isinstance(fallback, dict):
        return ""
    unavailable = [str(item).strip() for item in fallback.get("unavailable_sources") or [] if str(item).strip()]
    if not unavailable:
        return ""
    scope = "本场" if fallback.get("scope") == "match" else "本期"
    return (
        "完整分析资料审计（网络降级）：完整分析未执行；"
        f"{scope}因网络未获得的信息来源：{'、'.join(unavailable)}；"
        "当前结论已改用简单分析，这些资料未参与判断。"
    )


def _select_notes(notes: tuple[str, ...]) -> list[str]:
    selected = list(notes[:2])
    priority_keywords = ("实力模型", "阵容模型", "外盘赔率", "伤停数据", "情报", "主流媒体")
    for note in notes:
        if any(keyword in note for keyword in priority_keywords) and note not in selected:
            selected.append(note)
        if len(selected) >= 8:
            break
    return selected
