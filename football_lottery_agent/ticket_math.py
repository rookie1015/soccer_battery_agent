from __future__ import annotations

from typing import Iterable, Mapping, Sequence


OUTCOMES = ("3", "1", "0")


def hit_distribution(
    probabilities: Sequence[Mapping[str, float]],
    selections: Sequence[Iterable[str]],
) -> tuple[float, ...]:
    """Return P(exactly k fixtures are covered), without enumerating 3**n results."""
    if len(probabilities) != len(selections):
        raise ValueError("Probabilities and selections must have equal lengths.")
    coefficients = [1.0]
    for probability, selected in zip(probabilities, selections):
        picks = {str(value) for value in selected if str(value) in OUTCOMES}
        if not picks:
            raise ValueError("Every fixture must contain at least one valid outcome.")
        covered = min(1.0, max(0.0, sum(float(probability.get(pick, 0.0)) for pick in picks)))
        next_coefficients = [0.0] * (len(coefficients) + 1)
        for hits, value in enumerate(coefficients):
            next_coefficients[hits] += value * (1.0 - covered)
            next_coefficients[hits + 1] += value * covered
        coefficients = next_coefficients
    return tuple(coefficients)


def expected_line_hit_counts(
    probabilities: Sequence[Mapping[str, float]],
    selections: Sequence[Iterable[str]],
) -> tuple[float, ...]:
    """Return expected number of Cartesian ticket lines with exactly k correct picks.

    The generating factor for one fixture is ``(|S|-q) + q*x``, where q is
    the probability mass covered by its selected outcomes.  Multiplication is
    O(n**2), and therefore avoids expanding every ticket line or match result.
    """
    if len(probabilities) != len(selections):
        raise ValueError("Probabilities and selections must have equal lengths.")
    coefficients = [1.0]
    for probability, selected in zip(probabilities, selections):
        picks = {str(value) for value in selected if str(value) in OUTCOMES}
        if not picks:
            raise ValueError("Every fixture must contain at least one valid outcome.")
        covered = min(1.0, max(0.0, sum(float(probability.get(pick, 0.0)) for pick in picks)))
        missed_line_mass = len(picks) - covered
        next_coefficients = [0.0] * (len(coefficients) + 1)
        for hits, value in enumerate(coefficients):
            next_coefficients[hits] += value * missed_line_mass
            next_coefficients[hits + 1] += value * covered
        coefficients = next_coefficients
    return tuple(coefficients)


def ticket_probability_diagnostics(
    probabilities: Sequence[Mapping[str, float]],
    selections: Sequence[Iterable[str]],
) -> dict[str, object]:
    distribution = hit_distribution(probabilities, selections)
    expected_lines = expected_line_hit_counts(probabilities, selections)
    fixture_count = len(probabilities)
    line_count = 1
    for selected in selections:
        line_count *= len({str(value) for value in selected if str(value) in OUTCOMES})
    return {
        "method": "dynamic_programming_generating_function",
        "fixture_count": fixture_count,
        "line_count": line_count,
        "cost_yuan": line_count * 2,
        "coverage_probability": round(distribution[fixture_count], 10),
        "at_least_n_minus_1_probability": round(sum(distribution[max(0, fixture_count - 1) :]), 10),
        "hit_distribution": [round(value, 10) for value in distribution],
        "expected_exact_hit_lines": [round(value, 10) for value in expected_lines],
    }


def conditional_prize_ev(
    diagnostics: Mapping[str, object],
    *,
    first_prize_yuan: int | None,
    second_prize_yuan: int | None = None,
) -> dict[str, object]:
    expected = diagnostics.get("expected_exact_hit_lines")
    fixture_count = int(diagnostics.get("fixture_count") or 0)
    cost = int(diagnostics.get("cost_yuan") or 0)
    values = expected if isinstance(expected, list) else []
    if first_prize_yuan is None or len(values) <= fixture_count:
        gross = None
    else:
        gross = float(values[fixture_count]) * first_prize_yuan
        if second_prize_yuan is not None and fixture_count > 0:
            gross += float(values[fixture_count - 1]) * second_prize_yuan
    return {
        "scope": "post_draw_conditional_on_published_per_line_prizes",
        "production_eligible": False,
        "expected_gross_prize_yuan": round(gross, 2) if gross is not None else None,
        "expected_net_yuan": round(gross - cost, 2) if gross is not None else None,
        "expected_roi_percent": round((gross - cost) / cost * 100, 2) if gross is not None and cost else None,
        "warning": "使用开奖后才知道的单注奖金，仅用于验证计算与奖金结构研究，不能作为赛前策略收益预测。",
    }
