from __future__ import annotations

from math import exp, factorial

from .dixon_coles import DixonColesForecast, forecast as dixon_coles_forecast
from .models import Match, Prediction, Scoreline


OUTCOME_LABELS = {"3": "主胜", "1": "平", "0": "客胜"}


def predict_match(match: Match, model_weights: dict[str, float] | None = None) -> Prediction:
    odds_probs = _odds_to_probabilities(match)
    signal_scores = _signal_scores(match)
    math_forecast = dixon_coles_forecast(match)
    odds_weight, signal_weight, math_weight = _blend_weights(math_forecast, model_weights)

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

    if top_prob >= 0.52 and spread >= 0.14:
        picks = (top_outcome,)
    elif top_prob >= 0.44 and spread >= 0.06:
        picks = (top_outcome, second_outcome)
    else:
        picks = ("3", "1", "0")

    confidence = round(top_prob * 100, 1)
    risk = _risk_label(top_prob, spread, len(picks))
    scorelines = _predict_scorelines(match, probabilities, math_forecast)
    reasons = _build_reasons(match, probabilities, ranked, spread, math_forecast)

    return Prediction(
        match=match,
        probabilities={key: round(value, 4) for key, value in probabilities.items()},
        picks=picks,
        scorelines=scorelines,
        confidence=confidence,
        risk=risk,
        reasons=tuple(reasons),
    )


def predict_issue(matches: tuple[Match, ...], model_weights: dict[str, float] | None = None) -> tuple[Prediction, ...]:
    return tuple(predict_match(match, model_weights=model_weights) for match in matches)


def _blend_weights(
    math_forecast: DixonColesForecast,
    model_weights: dict[str, float] | None,
) -> tuple[float, float, float]:
    if math_forecast.data_quality != "strength" or not model_weights:
        return (0.63, 0.25, 0.12) if math_forecast.data_quality != "strength" else (0.55, 0.22, 0.23)
    odds = max(0.0, float(model_weights.get("odds", 0.55)))
    signals = max(0.0, float(model_weights.get("signals", 0.22)))
    math = max(0.0, float(model_weights.get("dixon_coles", 0.23)))
    total = odds + signals + math
    if total <= 0:
        return (0.55, 0.22, 0.23)
    return (odds / total, signals / total, math / total)


def _odds_to_probabilities(match: Match) -> dict[str, float]:
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
    draw_score = 0.20 + 0.22 * max(0.0, balance)

    raw = {
        "3": max(0.05, home_strength),
        "1": max(0.08, draw_score),
        "0": max(0.05, away_strength),
    }
    return _normalize(raw)


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
    if math_forecast and math_forecast.data_quality == "strength":
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
    if math_forecast.data_quality != "strength":
        reasons.append("数学模型当前未取得完整 xG/xGA 样本，已降为低权重基线。")

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


def _select_notes(notes: tuple[str, ...]) -> list[str]:
    selected = list(notes[:2])
    priority_keywords = ("实力模型", "阵容模型", "外盘赔率", "伤停数据", "情报", "主流媒体")
    for note in notes:
        if any(keyword in note for keyword in priority_keywords) and note not in selected:
            selected.append(note)
        if len(selected) >= 8:
            break
    return selected
