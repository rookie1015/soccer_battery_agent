from football_lottery_agent.ticket_math import (
    conditional_prize_ev,
    expected_line_hit_counts,
    hit_distribution,
    ticket_probability_diagnostics,
)


def test_dynamic_programming_hit_distribution_without_result_enumeration() -> None:
    probabilities = [{"3": 0.5, "1": 0.3, "0": 0.2}] * 14
    selections = [("3",)] * 14
    distribution = hit_distribution(probabilities, selections)

    assert len(distribution) == 15
    assert round(sum(distribution), 12) == 1.0
    assert distribution[14] == 0.5**14


def test_generating_function_counts_expected_winning_lines_for_full_cover() -> None:
    probabilities = [{"3": 0.5, "1": 0.3, "0": 0.2}] * 2
    expected = expected_line_hit_counts(probabilities, [("3", "1", "0")] * 2)

    assert expected == (4.0, 4.0, 1.0)
    assert sum(expected) == 9.0


def test_conditional_ev_is_explicitly_not_production_eligible() -> None:
    diagnostics = ticket_probability_diagnostics(
        [{"3": 0.5, "1": 0.3, "0": 0.2}] * 2,
        [("3",)] * 2,
    )
    value = conditional_prize_ev(diagnostics, first_prize_yuan=100, second_prize_yuan=10)

    assert value["expected_gross_prize_yuan"] == 30.0
    assert value["production_eligible"] is False
    assert value["scope"] == "post_draw_conditional_on_published_per_line_prizes"
