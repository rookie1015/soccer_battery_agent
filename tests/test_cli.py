import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from football_lottery_agent import cli


class CliTests(unittest.TestCase):
    def test_daily_collects_and_generates_report(self) -> None:
        with (
            patch.object(sys, "argv", ["football-lottery-agent", "daily", "--strength-model"]),
            patch.object(cli, "collect_issue", return_value=Path("data/collected_issue.json")) as collect_issue,
            patch.object(cli, "load_issue", return_value=Mock()) as load_issue,
            patch.object(cli, "build_ticket_plan", return_value=Mock()) as build_ticket_plan,
            patch.object(cli, "write_report", return_value=Path("reports/collected_report.md")) as write_report,
            patch.object(cli, "write_analysis_html", return_value=Path("reports/collected_report.html")) as write_analysis_html,
            patch.object(cli, "archive_report", return_value=Path("reports/history/index.html")) as archive_report,
            patch("builtins.print"),
        ):
            cli.main()

        collect_issue.assert_called_once()
        collect_kwargs = collect_issue.call_args.kwargs
        self.assertEqual(collect_kwargs["output_path"], Path("data/collected_issue.json"))
        self.assertTrue(collect_kwargs["strength_model"])
        load_issue.assert_called_once_with(Path("data/collected_issue.json"))
        build_ticket_plan.assert_called_once()
        write_report.assert_called_once()
        write_analysis_html.assert_called_once()
        archive_report.assert_called_once()
        self.assertEqual(write_report.call_args.args[1], Path("reports/collected_report.md"))
        self.assertEqual(write_analysis_html.call_args.args[1], Path("reports/collected_report.html"))

    def test_daily_passes_send_options(self) -> None:
        with (
            patch.object(sys, "argv", ["football-lottery-agent", "daily", "--send", "feishu", "--webhook-url", "https://example.test"]),
            patch.object(cli, "collect_issue", return_value=Path("data/issue.json")),
            patch.object(cli, "load_issue", return_value=Mock()),
            patch.object(cli, "build_ticket_plan", return_value=Mock()),
            patch.object(cli, "write_report", return_value=Path("reports/report.md")),
            patch.object(cli, "write_analysis_html", return_value=Path("reports/collected_report.html")),
            patch.object(cli, "archive_report", return_value=Path("reports/history/index.html")),
            patch.object(cli, "send_report", return_value=Mock(channel="feishu", response_text="ok")) as send_report,
            patch("builtins.print"),
        ):
            cli.main()

        send_report.assert_called_once_with("feishu", Path("reports/report.md"), "https://example.test")

    def test_daily_accepts_custom_output_paths(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "football-lottery-agent",
                    "daily",
                    "--issue-output",
                    "tmp/issue.json",
                    "--report-output",
                    "tmp/report.md",
                ],
            ),
            patch.object(cli, "collect_issue", return_value=Path("tmp/issue.json")) as collect_issue,
            patch.object(cli, "load_issue", return_value=Mock()) as load_issue,
            patch.object(cli, "build_ticket_plan", return_value=Mock()),
            patch.object(cli, "write_report", return_value=Path("tmp/report.md")) as write_report,
            patch.object(cli, "write_analysis_html", return_value=Path("reports/collected_report.html")) as write_analysis_html,
            patch.object(cli, "archive_report", return_value=Path("reports/history/index.html")),
            patch("builtins.print"),
        ):
            cli.main()

        self.assertEqual(collect_issue.call_args.kwargs["output_path"], Path("tmp/issue.json"))
        load_issue.assert_called_once_with(Path("tmp/issue.json"))
        self.assertEqual(write_report.call_args.args[1], Path("tmp/report.md"))
        self.assertEqual(write_analysis_html.call_args.args[1], Path("reports/collected_report.html"))

    def test_review_generates_review_report(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "football-lottery-agent",
                    "review",
                    "--issue",
                    "data/issue.json",
                    "--results",
                    "data/results.csv",
                    "--output",
                    "reports/review.md",
                ],
            ),
            patch.object(cli, "load_issue", return_value=Mock()) as load_issue,
            patch.object(cli, "build_ticket_plan", return_value=Mock()) as build_ticket_plan,
            patch.object(cli, "load_results", return_value={}) as load_results,
            patch.object(cli, "build_review", return_value=Mock()) as build_review,
            patch.object(cli, "write_review_report", return_value=Path("reports/review.md")) as write_review_report,
            patch.object(cli, "write_review_html", return_value=Path("reports/review_report.html")) as write_review_html,
            patch.object(cli, "archive_report", return_value=Path("reports/history/index.html")) as archive_report,
            patch("builtins.print"),
        ):
            cli.main()

        load_issue.assert_called_once_with(Path("data/issue.json"))
        build_ticket_plan.assert_called_once()
        load_results.assert_called_once_with(Path("data/results.csv"))
        build_review.assert_called_once()
        write_review_report.assert_called_once()
        write_review_html.assert_called_once()
        archive_report.assert_called_once()
        self.assertEqual(write_review_report.call_args.args[1], Path("reports/review.md"))
        self.assertEqual(write_review_html.call_args.args[1], Path("reports/review_report.html"))

    def test_review_auto_fetches_results_when_csv_is_omitted(self) -> None:
        fetched = Mock(results={}, source="测试源")
        with (
            patch.object(sys, "argv", ["football-lottery-agent", "review", "--issue", "data/issue.json"]),
            patch.object(cli, "load_issue", return_value=Mock(issue="26087")) as load_issue,
            patch.object(cli, "build_ticket_plan", return_value=Mock()) as build_ticket_plan,
            patch.object(cli, "fetch_results_with_fallbacks", return_value=fetched) as fetch_results,
            patch.object(cli, "build_review", return_value=Mock()) as build_review,
            patch.object(cli, "write_review_report", return_value=Path("reports/review_report.md")),
            patch.object(cli, "write_review_html", return_value=Path("reports/review_report.html")),
            patch.object(cli, "archive_report", return_value=Path("reports/history/index.html")),
            patch("builtins.print"),
        ):
            cli.main()

        load_issue.assert_called_once_with(Path("data/issue.json"))
        build_ticket_plan.assert_called_once()
        fetch_results.assert_called_once()
        self.assertEqual(fetch_results.call_args.args[0], "26087")
        build_review.assert_called_once()


if __name__ == "__main__":
    unittest.main()
