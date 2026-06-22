from __future__ import annotations

import argparse
from pathlib import Path

from .collectors import collect_issue
from .history import archive_report
from .html_report import write_analysis_html, write_review_html
from .loader import load_issue
from .notifier import NotifyError, send_report
from .report import write_report
from .review import build_review, fetch_sina_results, load_results, write_review_report
from .strategy import build_ticket_plan
from .web_ui import run_ui


def main() -> None:
    parser = argparse.ArgumentParser(prog="football-lottery-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Generate a lottery analysis report.")
    run_parser.add_argument("--input", required=True, help="Path to issue JSON.")
    run_parser.add_argument("--output", default="reports/report.md", help="Output Markdown report path.")
    run_parser.add_argument("--html-output", help="Optional output HTML dashboard path.")
    run_parser.add_argument("--history-dir", default="reports/history", help="Directory for 52-entry HTML history.")
    run_parser.add_argument("--no-history", action="store_true", help="Do not add this HTML report to history.")
    run_parser.add_argument("--send", choices=["feishu", "wechat"], help="Send report after generation.")
    run_parser.add_argument("--webhook-url", help="Webhook URL for --send.")

    send_parser = subparsers.add_parser("send-report", help="Send an existing report to Feishu or WeCom.")
    send_parser.add_argument("--channel", required=True, choices=["feishu", "wechat"], help="Target channel.")
    send_parser.add_argument("--report", required=True, help="Path to Markdown report.")
    send_parser.add_argument("--webhook-url", help="Webhook URL. If omitted, env var is used.")

    collect_parser = subparsers.add_parser("collect", help="Collect schedule/news/injury/history into issue JSON.")
    collect_parser.add_argument("--output", default="data/collected_issue.json", help="Output issue JSON path.")
    _add_collect_options(collect_parser)

    daily_parser = subparsers.add_parser("daily", help="Collect current issue, generate report, and optionally send it.")
    daily_parser.add_argument("--issue-output", default="data/collected_issue.json", help="Output issue JSON path.")
    daily_parser.add_argument("--report-output", default="reports/collected_report.md", help="Output Markdown report path.")
    daily_parser.add_argument("--html-output", default="reports/collected_report.html", help="Output HTML dashboard path.")
    daily_parser.add_argument("--history-dir", default="reports/history", help="Directory for 52-entry HTML history.")
    daily_parser.add_argument("--no-history", action="store_true", help="Do not add this HTML report to history.")
    daily_parser.add_argument("--send", choices=["feishu", "wechat"], help="Send report after generation.")
    daily_parser.add_argument("--webhook-url", help="Webhook URL for --send.")
    _add_collect_options(daily_parser)

    review_parser = subparsers.add_parser("review", help="Review predictions against final scores.")
    review_parser.add_argument("--issue", required=True, help="Path to issue JSON.")
    review_parser.add_argument("--results", help="CSV with seq,home_goals,away_goals or seq,score. If omitted, auto-fetch from Sina.")
    review_parser.add_argument("--result-issue", help="Sina issue id for auto result fetch. Defaults to issue JSON id.")
    review_parser.add_argument("--cache-dir", default="data/cache", help="HTTP cache directory for auto results.")
    review_parser.add_argument("--output", default="reports/review_report.md", help="Output Markdown review path.")
    review_parser.add_argument("--html-output", default="reports/review_report.html", help="Output HTML dashboard path.")
    review_parser.add_argument("--history-dir", default="reports/history", help="Directory for 52-entry HTML history.")
    review_parser.add_argument("--no-history", action="store_true", help="Do not add this HTML report to history.")

    ui_parser = subparsers.add_parser("ui", help="Start a local browser UI for one-click workflows.")
    ui_parser.add_argument("--host", default="127.0.0.1", help="Local UI host.")
    ui_parser.add_argument("--port", type=int, default=8765, help="Local UI port.")
    ui_parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")

    args = parser.parse_args()

    if args.command == "run":
        output = _generate_report(
            Path(args.input),
            Path(args.output),
            Path(args.html_output) if args.html_output else None,
            Path(args.history_dir),
            archive_history=not args.no_history,
        )
        if args.send:
            _send(args.send, output, args.webhook_url)
    elif args.command == "send-report":
        _send(args.channel, Path(args.report), args.webhook_url)
    elif args.command == "collect":
        output = _collect_from_args(args, Path(args.output))
        print(f"Issue data written: {output}")
    elif args.command == "daily":
        issue_output = _collect_from_args(args, Path(args.issue_output))
        print(f"Issue data written: {issue_output}")
        report_output = _generate_report(
            issue_output,
            Path(args.report_output),
            Path(args.html_output) if args.html_output else None,
            Path(args.history_dir),
            archive_history=not args.no_history,
        )
        if args.send:
            _send(args.send, report_output, args.webhook_url)
    elif args.command == "review":
        try:
            output = _generate_review(
                Path(args.issue),
                Path(args.results) if args.results else None,
                Path(args.output),
                Path(args.html_output) if args.html_output else None,
                Path(args.history_dir),
                archive_history=not args.no_history,
                result_issue=args.result_issue,
                cache_dir=Path(args.cache_dir),
            )
        except ValueError as exc:
            raise SystemExit(f"Review not ready: {exc}") from exc
        print(f"Review written: {output}")
    elif args.command == "ui":
        run_ui(host=args.host, port=args.port, open_browser=not args.no_open)


def _add_collect_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--issue", help="Issue id. Defaults to source issue.")
    parser.add_argument("--source", default="sina", choices=["sina"], help="Schedule source.")
    parser.add_argument("--seed", help="Fallback CSV with seq,kickoff,league,home,away.")
    parser.add_argument("--odds", help="Optional odds CSV with seq,home,draw,away.")
    parser.add_argument("--cache-dir", default="data/cache", help="HTTP cache directory.")
    parser.add_argument("--offline", action="store_true", help="Skip news/history network collection.")
    parser.add_argument("--foreign-odds", action="store_true", help="Use foreign bookmaker odds from The Odds API.")
    parser.add_argument("--foreign-odds-regions", default="uk,eu", help="The Odds API regions, for example uk,eu,us.")
    parser.add_argument("--foreign-odds-bookmakers", default="", help="Comma-separated bookmaker keys. Empty means API region defaults.")
    parser.add_argument("--foreign-odds-sports", default="", help="Comma-separated The Odds API sport keys.")
    parser.add_argument("--strength-model", action="store_true", help="Build FotMob-based team strength model.")
    parser.add_argument("--strength-team-ids", help="Optional CSV mapping name,fotmob_id.")
    parser.add_argument("--strength-lookback", type=int, default=20, help="Number of past matches for form model.")
    parser.add_argument("--strength-xg-matches", type=int, default=8, help="Recent matches to fetch matchDetails xG for.")


def _collect_from_args(args: argparse.Namespace, output_path: Path) -> Path:
    return collect_issue(
        output_path=output_path,
        issue=args.issue,
        source=args.source,
        seed_path=Path(args.seed) if args.seed else None,
        odds_path=Path(args.odds) if args.odds else None,
        cache_dir=Path(args.cache_dir),
        offline=args.offline,
        foreign_odds=args.foreign_odds,
        foreign_odds_regions=args.foreign_odds_regions,
        foreign_odds_bookmakers=args.foreign_odds_bookmakers,
        foreign_odds_sports=args.foreign_odds_sports,
        strength_model=args.strength_model,
        strength_team_ids=Path(args.strength_team_ids) if args.strength_team_ids else None,
        strength_lookback=args.strength_lookback,
        strength_xg_matches=args.strength_xg_matches,
    )


def _generate_report(
    input_path: Path,
    output_path: Path,
    html_output_path: Path | None = None,
    history_dir: Path = Path("reports/history"),
    archive_history: bool = True,
) -> Path:
    issue = load_issue(input_path)
    plan = build_ticket_plan(issue)
    output = write_report(plan, output_path)
    print(f"Report written: {output}")
    if html_output_path:
        html_output = write_analysis_html(plan, html_output_path)
        print(f"HTML report written: {html_output}")
        if archive_history:
            history_index = archive_report("analysis", plan.issue.issue, html_output, output, history_dir=history_dir)
            print(f"History index written: {history_index}")
    return output


def _generate_review(
    issue_path: Path,
    results_path: Path | None,
    output_path: Path,
    html_output_path: Path | None = None,
    history_dir: Path = Path("reports/history"),
    archive_history: bool = True,
    result_issue: str | None = None,
    cache_dir: Path = Path("data/cache"),
) -> Path:
    issue = load_issue(issue_path)
    plan = build_ticket_plan(issue)
    results = load_results(results_path) if results_path else fetch_sina_results(result_issue or issue.issue, cache_dir=cache_dir)
    review = build_review(plan, results)
    output = write_review_report(review, output_path)
    if html_output_path:
        html_output = write_review_html(review, html_output_path)
        print(f"HTML review written: {html_output}")
        if archive_history:
            history_index = archive_report("review", plan.issue.issue, html_output, output, history_dir=history_dir)
            print(f"History index written: {history_index}")
    return output


def _send(channel: str, report_path: Path, webhook_url: str | None) -> None:
    try:
        result = send_report(channel, report_path, webhook_url)
    except NotifyError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Report sent to {result.channel}: {result.response_text}")
