from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
import re

from .collectors import collect_issue
from .calibration import build_calibration
from .experiments import load_active_model_weights, run_experiment
from .history import archive_report, load_history_entries
from .html_report import write_analysis_html, write_review_html
from .loader import load_issue
from .mobile_api import serialize_ticket_plan
from .models import Match, Odds, Signals, TicketPlan
from .predictor import OUTCOME_LABELS, predict_match
from .report import write_report
from .review import build_review, fetch_results_with_fallbacks, load_results, write_review_report
from .review_diagnostics import record_review_diagnostics
from .post_match_context import find_post_match_evidence, normalize_evidence
from .strategy import DEFAULT_MAX_TICKET_COST_YUAN, build_ticket_plan
import tempfile


def run_health() -> dict[str, object]:
    return {"ok": True, "service": "football-lottery-agent-local"}


def run_analysis(
    payload: dict[str, Any],
    work_dir: str | Path,
) -> dict[str, object]:
    issue = str(payload.get("issue") or "").strip()
    if not issue:
        raise ValueError("请填写期号。")
    strength_xg_matches = int(payload.get("strength_xg_matches") or 8)
    if strength_xg_matches < 0 or strength_xg_matches > 20:
        raise ValueError("xG 样本场次必须是 0 到 20 之间的整数。")
    max_ticket_cost_yuan = int(payload.get("max_ticket_cost_yuan") or DEFAULT_MAX_TICKET_COST_YUAN)
    if max_ticket_cost_yuan < 2:
        raise ValueError("最高购彩金额不能低于 2 元。")
    full_analysis = bool(payload.get("full_analysis", False))
    foreign_odds = bool(payload.get("foreign_odds", False))
    foreign_odds_api_key = str(payload.get("foreign_odds_api_key") or "").strip() or None
    use_foreign_odds = foreign_odds or (full_analysis and foreign_odds_api_key is not None)

    root = Path(work_dir)
    data_dir = root / "data"
    report_dir = root / "reports"
    history_dir = report_dir / "history"
    cache_dir = root / "cache"
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    issue_path = data_dir / "collected_issue.json"
    issue_archive_path = data_dir / f"{_slug(issue)}_issue.json"
    markdown_path = report_dir / f"{_slug(issue)}_report.md"
    html_path = report_dir / f"{_slug(issue)}_report.html"

    collect_issue(
        output_path=issue_path,
        issue=issue,
        cache_dir=cache_dir,
        foreign_odds=use_foreign_odds,
        foreign_odds_api_key=foreign_odds_api_key,
        strength_model=full_analysis,
        strength_xg_matches=strength_xg_matches,
        skip_context_fetches=not full_analysis,
        sina_odds_only=not full_analysis,
    )
    if issue_path.exists():
        issue_archive_path.write_text(issue_path.read_text(encoding="utf-8"), encoding="utf-8")
    calibration = build_calibration(root)
    active_weights = load_active_model_weights(root)
    if active_weights is not None:
        calibration = {
            **calibration,
            "status": "experiment_active",
            "weights": active_weights,
            "message": "当前权重已通过严格赛前、按期走步回测的晋级门槛。",
        }
    elif calibration.get("status") == "calibrated":
        calibration = {
            **calibration,
            "status": "experiment_pending_gate",
            "message": "历史样本已足够拟合，但尚未通过严格赛前回测晋级门槛，当前继续使用默认权重。",
        }
    issue_data = load_issue(issue_path)
    if active_weights is not None:
        plan = build_ticket_plan(
            issue_data,
            max_ticket_cost_yuan=max_ticket_cost_yuan,
            model_weights=active_weights,
        )
    else:
        plan = build_ticket_plan(issue_data, max_ticket_cost_yuan=max_ticket_cost_yuan)
    write_report(plan, markdown_path)
    write_analysis_html(plan, html_path)
    history_path = archive_report(
        "analysis",
        plan.issue.issue,
        html_path,
        markdown_path,
        history_dir=history_dir,
    )

    return {
        "ok": True,
        "message": f"{issue} 分析报告已在手机本机生成。",
        "report": {**serialize_ticket_plan(plan), "model_calibration": calibration},
        "html_path": str(html_path),
        "markdown_path": str(markdown_path),
        "history_path": str(history_path),
    }


def run_history(work_dir: str | Path) -> dict[str, object]:
    history_dir = Path(work_dir) / "reports" / "history"
    entries = []
    for item in load_history_entries(history_dir):
        entry = dict(item)
        markdown = str(entry.get("markdown") or "")
        html = str(entry.get("html") or "")
        entry["html_url"] = str((history_dir / html).resolve()) if html else ""
        entry["markdown_url"] = str((history_dir / markdown).resolve()) if markdown else ""
        markdown_text = _read_history_text(history_dir, markdown)
        entry["markdown_text"] = markdown_text
        report = _parse_history_report(
            markdown_text,
            str(entry.get("issue") or ""),
            str(entry.get("kind") or ""),
        )
        if report is not None and str(entry.get("kind") or "") == "analysis":
            report = _restore_history_metadata(report, Path(work_dir), str(entry.get("issue") or ""))
        entry["report"] = report
        entries.append(entry)
    return {"ok": True, "entries": entries}


def _read_history_text(history_dir: Path, relative_path: str) -> str:
    if not relative_path:
        return ""
    path = (history_dir / relative_path).resolve()
    try:
        path.relative_to(history_dir.resolve())
    except ValueError:
        return ""
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_history_report(markdown_text: str, fallback_issue: str, kind: str = "") -> dict[str, object] | None:
    if "## 逐场复盘" in markdown_text or kind == "review":
        return _parse_review_report(markdown_text, fallback_issue)
    if "## 14场逐场建议" not in markdown_text:
        return None

    issue_match = re.search(r"^# 足球彩票分析报告：(.+)$", markdown_text, re.MULTILINE)
    issue = issue_match.group(1).strip() if issue_match else fallback_issue
    keep = _parse_sequence(markdown_text, "建议保留")
    drop = _parse_sequence(markdown_text, "建议剔除")
    kickoff_by_seq = _parse_kickoffs(markdown_text)
    predictions = []

    for line in markdown_text.splitlines():
        if not line.startswith("| "):
            continue
        if "---" in line or "序号" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 8 or not cells[0].isdigit():
            continue

        seq = int(cells[0])
        home, away = _split_matchup(cells[2])
        probabilities = _parse_probabilities(cells[7])
        predictions.append(
            {
                "seq": seq,
                "league": cells[1],
                "kickoff_display": kickoff_by_seq.get(seq, ""),
                "home": home,
                "away": away,
                "pick_text": cells[3],
                "pick_labels": [OUTCOME_LABELS.get(pick, pick) for pick in cells[3].split("/") if pick],
                "confidence": _parse_percent(cells[5]),
                "risk": cells[6],
                "probabilities": probabilities,
                "scorelines": _parse_scorelines(cells[4]),
                "reasons": [],
                "final_score": "",
                "final_result": "",
                "final_result_label": "",
                "outcome_hit": False,
            }
        )

    if not predictions:
        return None

    low_risk = sum(1 for prediction in predictions if prediction["risk"] == "低")
    singles = sum(1 for prediction in predictions if "/" not in str(prediction["pick_text"]))
    avg_confidence = sum(float(prediction["confidence"]) for prediction in predictions) / len(predictions)
    metadata = _parse_analysis_metadata(markdown_text)
    return {
        "issue": issue,
        "purchase_deadline": metadata.get("purchase_deadline", ""),
        "purchase_deadline_source": metadata.get("purchase_deadline_source", ""),
        "sale_begin_time": metadata.get("sale_begin_time", ""),
        "metrics": {
            "match_count": len(predictions),
            "single_count": singles,
            "low_risk_count": low_risk,
            "average_confidence": round(avg_confidence, 1),
        },
        "choose9_keep": keep,
        "choose9_drop": drop,
        "predictions": predictions,
    }


def _parse_analysis_metadata(markdown_text: str) -> dict[str, str]:
    labels = {
        "purchase_deadline": "购彩截止时间",
        "purchase_deadline_source": "截止时间来源",
        "sale_begin_time": "开售时间",
    }
    result: dict[str, str] = {}
    for key, label in labels.items():
        match = re.search(rf"^- {label}：(.+)$", markdown_text, re.MULTILINE)
        if match:
            result[key] = match.group(1).strip()
    return result


def _restore_history_metadata(report: dict[str, object], work_dir: Path, issue: str) -> dict[str, object]:
    if report.get("purchase_deadline"):
        return report
    data_dir = work_dir / "data"
    candidates = (data_dir / f"{_slug(issue)}_issue.json", data_dir / "collected_issue.json")
    for path in candidates:
        if not path.exists():
            continue
        try:
            archived_issue = load_issue(path)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if archived_issue.issue != issue:
            continue
        metadata = archived_issue.metadata
        if not metadata.get("purchase_deadline"):
            continue
        restored = dict(report)
        for key in ("purchase_deadline", "purchase_deadline_source", "sale_begin_time"):
            value = metadata.get(key)
            if value:
                restored[key] = value
        return restored
    return report


def _parse_review_report(markdown_text: str, fallback_issue: str) -> dict[str, object] | None:
    if "## 逐场复盘" not in markdown_text:
        return None

    issue_match = re.search(r"^# 足球彩票复盘报告：(.+)$", markdown_text, re.MULTILINE)
    issue = issue_match.group(1).strip() if issue_match else fallback_issue
    overview = _parse_review_overview(markdown_text)
    predictions = []
    keep: list[int] = []
    drop: list[int] = []

    for line in markdown_text.splitlines():
        if not line.startswith("| "):
            continue
        if "---" in line or "序号" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 8 or not cells[0].isdigit():
            continue

        seq = int(cells[0])
        home, away = _split_matchup(cells[1])
        pick_text = cells[4]
        if cells[7] == "任九保留":
            keep.append(seq)
        elif cells[7] == "任九剔除":
            drop.append(seq)
        predictions.append(
            {
                "seq": seq,
                "league": "复盘",
                "kickoff_display": "",
                "home": home,
                "away": away,
                "pick_text": pick_text,
                "pick_labels": [OUTCOME_LABELS.get(pick, pick) for pick in pick_text.split("/") if pick],
                "confidence": 0.0,
                "risk": cells[7],
                "probabilities": {"home": 0.0, "draw": 0.0, "away": 0.0},
                "scorelines": _parse_scorelines(cells[6]),
                "reasons": [],
                "final_score": cells[2],
                "final_result": _outcome_code(cells[3]),
                "final_result_label": cells[3],
                "outcome_hit": cells[5] == "命中",
                "diagnostic_tags": [] if len(cells) < 9 or cells[8] == "-" else cells[8].split("、"),
                "post_match_evidence": (
                    []
                    if len(cells) < 10 or cells[9] == "-"
                    else [{"label": label, "summary": label, "sources": []} for label in cells[9].split("、")]
                ),
            }
        )

    if not predictions:
        return None

    return {
        "issue": issue,
        "purchase_deadline": "",
        "purchase_deadline_source": "复盘报告",
        "sale_begin_time": "",
        "metrics": {
            "match_count": len(predictions),
            "single_count": overview.get("single_hits", 0),
            "low_risk_count": overview.get("outcome_hits", 0),
            "average_confidence": overview.get("outcome_rate", 0.0),
        },
        "choose9_keep": keep,
        "choose9_drop": drop,
        "predictions": predictions,
    }


def _parse_review_overview(markdown_text: str) -> dict[str, float]:
    overview: dict[str, float] = {}
    outcome = re.search(r"- 胜平负命中：(\d+)/(\d+)（([0-9.]+)%", markdown_text)
    if outcome:
        overview["outcome_hits"] = float(outcome.group(1))
        overview["outcome_rate"] = float(outcome.group(3))
    single = re.search(r"- 单选命中：(\d+)/", markdown_text)
    if single:
        overview["single_hits"] = float(single.group(1))
    return overview


def _outcome_code(label: str) -> str:
    for code, text in OUTCOME_LABELS.items():
        if label == text:
            return code
    return label if label in OUTCOME_LABELS else ""


def _parse_sequence(markdown_text: str, label: str) -> list[int]:
    match = re.search(rf"- {label}：([0-9、,\s]+)", markdown_text)
    if not match:
        return []
    return [int(value) for value in re.findall(r"\d+", match.group(1))]


def _parse_kickoffs(markdown_text: str) -> dict[int, str]:
    result: dict[int, str] = {}
    current_seq: int | None = None
    for line in markdown_text.splitlines():
        header = re.match(r"^###\s+(\d+)\.", line)
        if header:
            current_seq = int(header.group(1))
            continue
        if current_seq is None:
            continue
        match = re.match(r"^- 比赛：.*?，(.+)$", line)
        if match:
            result[current_seq] = _format_kickoff(match.group(1).strip())
            current_seq = None
    return result


def _format_kickoff(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def _split_matchup(value: str) -> tuple[str, str]:
    if " vs " not in value:
        return value, ""
    home, away = value.split(" vs ", 1)
    return home.strip(), away.strip()


def _parse_probabilities(value: str) -> dict[str, float]:
    parts = [_parse_percent(part) for part in value.split("/")]
    parts = (parts + [0.0, 0.0, 0.0])[:3]
    return {"home": parts[0], "draw": parts[1], "away": parts[2]}


def _parse_scorelines(value: str) -> list[dict[str, object]]:
    scorelines = []
    for item in re.split(r"[，,]", value):
        match = re.search(r"(\d+\s*-\s*\d+)\s+([0-9.]+)%", item.strip())
        if match:
            scorelines.append(
                {
                    "score": match.group(1).replace(" ", ""),
                    "probability": float(match.group(2)),
                }
            )
    return scorelines


def _parse_percent(value: str) -> float:
    match = re.search(r"([0-9.]+)%?", value)
    return float(match.group(1)) if match else 0.0


def run_review(payload: dict[str, Any], work_dir: str | Path) -> dict[str, object]:
    issue = str(payload.get("issue") or "").strip()
    if not issue:
        raise ValueError("请填写期号。")

    root = Path(work_dir)
    data_dir = root / "data"
    report_dir = root / "reports"
    history_dir = report_dir / "history"
    cache_dir = root / "cache"
    report_dir.mkdir(parents=True, exist_ok=True)

    issue_path = _resolve_local_issue_path(data_dir, issue)
    plan = _load_latest_analysis_plan(issue_path, history_dir, issue)
    auto_results = bool(payload.get("auto_results", True))
    results_csv = str(payload.get("results_csv") or "").strip()

    if auto_results:
        fetched = fetch_results_with_fallbacks(plan.issue.issue, cache_dir=cache_dir)
        results = fetched.results
        results_source = fetched.source
    else:
        if not results_csv:
            raise ValueError("请粘贴赛果 CSV，或打开自动拉取赛果。")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
            handle.write(results_csv)
            temp_results = Path(handle.name)
        try:
            results = load_results(temp_results)
        finally:
            temp_results.unlink(missing_ok=True)
        results_source = "手工 CSV"

    missing = [prediction.match.seq for prediction in plan.predictions if prediction.match.seq not in results]
    if missing:
        missing_text = "、".join(str(item) for item in missing)
        raise ValueError(f"{results_source} 赛果不完整，缺少第 {missing_text} 场。")

    review = build_review(plan, results)
    post_match_evidence = find_post_match_evidence(review, cache_dir / "post_match_evidence")
    diagnostics = record_review_diagnostics(review, report_dir)
    markdown_path = report_dir / f"{_slug(plan.issue.issue)}_review.md"
    html_path = report_dir / f"{_slug(plan.issue.issue)}_review.html"
    write_review_report(review, markdown_path, post_match_evidence)
    write_review_html(review, html_path)
    archive_report("review", plan.issue.issue, html_path, markdown_path, history_dir=history_dir)
    experiment = _refresh_model_experiment(root)

    return {
        "ok": True,
        "message": f"{plan.issue.issue} 复盘报告已生成，赛果来源：{results_source}。",
        "report": _serialize_review_report(review, diagnostics, post_match_evidence),
        "html_path": str(html_path),
        "markdown_path": str(markdown_path),
        "model_experiment": experiment,
    }


def _refresh_model_experiment(root: Path) -> dict[str, object]:
    try:
        result = run_experiment(root, promote=True)
    except Exception as exc:
        return {
            "status": "error",
            "message": f"复盘已保存，但模型回测刷新失败：{exc}",
        }
    promotion = result["promotion"]
    return {
        "status": promotion["status"],
        "message": promotion["message"],
        "experiment_id": result["experiment_id"],
        "report_path": result["artifacts"]["markdown"],
    }


def _resolve_local_issue_path(data_dir: Path, issue: str) -> Path:
    issue_path = data_dir / f"{_slug(issue)}_issue.json"
    if issue_path.exists():
        return issue_path
    collected = data_dir / "collected_issue.json"
    if collected.exists() and load_issue(collected).issue == issue:
        return collected
    raise ValueError(f"找不到 {issue} 的赛前数据。请先生成该期分析。")


def _load_latest_analysis_plan(issue_path: Path, history_dir: Path, issue: str) -> TicketPlan:
    plan = build_ticket_plan(load_issue(issue_path))
    for entry in load_history_entries(history_dir):
        if entry.get("kind") != "analysis" or str(entry.get("issue") or "").strip() != issue:
            continue
        report = _parse_history_report(
            _read_history_text(history_dir, str(entry.get("markdown") or "")),
            fallback_issue=issue,
            kind="analysis",
        )
        restored = _restore_analysis_recommendations(plan, report)
        if restored:
            return restored
    return plan


def _restore_analysis_recommendations(
    plan: TicketPlan,
    report: dict[str, object] | None,
) -> TicketPlan | None:
    if not report:
        return None
    saved_predictions = report.get("predictions")
    if not isinstance(saved_predictions, list):
        return None

    saved_picks: dict[int, tuple[str, ...]] = {}
    for saved in saved_predictions:
        if not isinstance(saved, dict):
            return None
        try:
            seq = int(saved.get("seq"))
        except (TypeError, ValueError):
            return None
        picks = tuple(item for item in str(saved.get("pick_text") or "").split("/") if item in OUTCOME_LABELS)
        if not picks:
            return None
        saved_picks[seq] = picks

    current_sequences = {prediction.match.seq for prediction in plan.predictions}
    if set(saved_picks) != current_sequences:
        return None

    saved_keep = _valid_sequence_list(report.get("choose9_keep"), current_sequences, expected_count=9)
    saved_drop = _valid_sequence_list(report.get("choose9_drop"), current_sequences, expected_count=5)
    if saved_keep is None or saved_drop is None or set(saved_keep) & set(saved_drop):
        return None

    return TicketPlan(
        issue=plan.issue,
        predictions=tuple(replace(prediction, picks=saved_picks[prediction.match.seq]) for prediction in plan.predictions),
        choose9_keep=saved_keep,
        choose9_drop=saved_drop,
    )


def _valid_sequence_list(value: object, sequences: set[int], expected_count: int) -> tuple[int, ...] | None:
    if not isinstance(value, list):
        return None
    try:
        items = tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return None
    if len(items) != expected_count or len(set(items)) != expected_count or not set(items) <= sequences:
        return None
    return tuple(sorted(items))


def _serialize_review_report(
    review,
    diagnostics: dict[str, object] | None = None,
    post_match_evidence: dict[int, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    report = serialize_ticket_plan(review.plan)
    by_seq = {row.prediction.match.seq: row for row in review.rows}
    predictions = []
    for prediction in report["predictions"]:
        row = by_seq.get(int(prediction["seq"]))
        if row:
            prediction = dict(prediction)
            prediction["final_score"] = row.result.score_text
            prediction["final_result"] = row.result.outcome
            prediction["final_result_label"] = OUTCOME_LABELS[row.result.outcome]
            prediction["outcome_hit"] = row.outcome_hit
            prediction["diagnostic_tags"] = list(row.diagnostic_tags)
            prediction["post_match_evidence"] = normalize_evidence(
                (post_match_evidence or {}).get(row.prediction.match.seq)
            )
        predictions.append(prediction)
    report["predictions"] = predictions
    report["purchase_deadline_source"] = "复盘报告"
    report["metrics"] = {
        "match_count": review.total,
        "single_count": review.single_hits,
        "low_risk_count": review.outcome_hits,
        "average_confidence": round(review.outcome_hits / review.total * 100, 1) if review.total else 0.0,
    }
    report["review_diagnostics"] = diagnostics or {
        "issue_miss_count": review.total - review.outcome_hits,
        "issue_tags": [],
        "history_issue_count": 0,
        "history_tags": [],
    }
    return report


def run_single_prediction(payload: dict[str, Any], work_dir: str | Path) -> dict[str, object]:
    home = str(payload.get("home") or "").strip()
    away = str(payload.get("away") or "").strip()
    if not home or not away:
        raise ValueError("请填写主队和客队。")
    if home.casefold() == away.casefold():
        raise ValueError("主队和客队不能相同。")

    match = _find_collected_match(home, away, Path(work_dir) / "data" / "collected_issue.json")
    if match:
        data_source = "手机本机最近一次采集的赔率、球队状态和伤停信号"
    else:
        odds_values = [str(payload.get(key) or "").strip() for key in ("home_odds", "draw_odds", "away_odds")]
        if any(odds_values) and not all(odds_values):
            raise ValueError("欧赔请填写完整的主胜、平局和客胜三项，或全部留空。")
        if all(odds_values):
            values = [float(value) for value in odds_values]
            if any(value <= 1.0 for value in values):
                raise ValueError("欧赔必须大于 1.00。")
            odds = Odds(home=values[0], draw=values[1], away=values[2])
            data_source = "手工填写的欧洲赔率；球队状态按中性值处理"
        else:
            odds = Odds(home=2.60, draw=3.20, away=2.70)
            data_source = "未匹配最近采集赛事且未填写赔率，使用均衡基准"
        match = Match(
            seq=1,
            kickoff=datetime.now().astimezone(),
            league="单场预测",
            home=home,
            away=away,
            odds=odds,
            signals=Signals(),
        )

    prediction = predict_match(match)
    return {
        "ok": True,
        "message": "单场比分预测已在手机本机生成。",
        "home": prediction.match.home,
        "away": prediction.match.away,
        "scorelines": [
            {"score": item.text, "probability": round(item.probability * 100, 1)}
            for item in prediction.scorelines
        ],
        "probabilities": {
            "home": round(prediction.probabilities["3"] * 100, 1),
            "draw": round(prediction.probabilities["1"] * 100, 1),
            "away": round(prediction.probabilities["0"] * 100, 1),
        },
        "pick_label": " / ".join(OUTCOME_LABELS[item] for item in prediction.picks),
        "confidence": prediction.confidence,
        "risk": prediction.risk,
        "reasons": list(prediction.reasons),
        "data_source": data_source,
    }


def _find_collected_match(home: str, away: str, issue_path: Path) -> Match | None:
    if not issue_path.exists():
        return None
    issue = load_issue(issue_path)
    home_key = _team_key(home)
    away_key = _team_key(away)
    return next(
        (
            match
            for match in issue.matches
            if _team_key(match.home) == home_key and _team_key(match.away) == away_key
        ),
        None,
    )


def _team_key(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _slug(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())
    clean = clean.strip("-")
    return clean or "report"
