from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re
import urllib.error
import urllib.parse

from .collectors import collect_issue
from .calibration import build_calibration
from .experiments import load_active_model_weights, load_active_selection_policy, run_experiment
from .history import archive_report, delete_history_entries, load_history_entries
from .html_report import write_analysis_html, write_review_html
from .loader import load_issue
from .mobile_api import serialize_ticket_plan
from .models import (
    DrawHedgePlan,
    DrawLineCoverage,
    LinePortfolioPlan,
    Match,
    Odds,
    Signals,
    TicketLine,
    TicketPlan,
)
from .notifier import send_text
from .predictor import OUTCOME_LABELS, SELECTION_REASON_PREFIX, predict_match, selection_reason_from_values
from .report import write_report
from .review import build_review, fetch_results_with_fallbacks, load_results, write_review_report
from .review_diagnostics import record_review_diagnostics
from .post_match_context import find_post_match_evidence, normalize_evidence
from .strategy import DEFAULT_MAX_TICKET_COST_YUAN, build_ticket_plan
import tempfile


STRENGTH_XG_MATCHES = 20
RECENT_SNAPSHOT_REUSE_SECONDS = 180
NETWORK_SENSITIVE_SOURCE_LABELS = {
    "injuries": "伤停信息",
    "history": "历史交锋",
    "intelligence": "赛前情报",
    "odds_movement": "赔率变化",
    "asian_handicap": "亚洲让球",
}


def run_health() -> dict[str, object]:
    return {"ok": True, "service": "football-lottery-agent-local"}


def run_foreign_odds_usage(payload: dict[str, Any]) -> dict[str, object]:
    from .foreign_odds import check_the_odds_api_usage

    usage = check_the_odds_api_usage(str(payload.get("foreign_odds_api_key") or ""))
    return {"ok": True, "usage": usage}


def run_send_feishu(payload: dict[str, Any]) -> dict[str, object]:
    webhook_url = str(payload.get("webhook_url") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not webhook_url:
        raise ValueError("请填写飞书 Webhook。")
    if not text:
        raise ValueError("飞书消息不能为空。")
    parsed = urllib.parse.urlparse(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"open.feishu.cn", "open.larksuite.com"}
        or not parsed.path.startswith("/open-apis/bot/v2/hook/")
    ):
        raise ValueError("请填写飞书自定义机器人的 HTTPS Webhook 地址。")

    result = send_text("feishu", text, webhook_url)
    try:
        response = json.loads(result.response_text or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("飞书返回了无法识别的响应。") from exc
    code = response.get("code", response.get("StatusCode", 0))
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = -1
    if numeric_code != 0:
        detail = str(response.get("msg") or response.get("StatusMessage") or "未知错误")
        raise RuntimeError(f"飞书拒绝了消息（{numeric_code}：{detail}）。")
    return {"ok": True, "message": "消息已发送到飞书。"}


def run_analysis(
    payload: dict[str, Any],
    work_dir: str | Path,
) -> dict[str, object]:
    cancel_path = _analysis_cancel_path(payload, work_dir)
    try:
        return _run_analysis(payload, work_dir, cancel_path=cancel_path)
    finally:
        if cancel_path is not None:
            cancel_path.unlink(missing_ok=True)


class AnalysisCancelledError(RuntimeError):
    """Raised when the mobile client cancels an in-flight analysis."""


class AnalysisUserError(RuntimeError):
    """A sanitized Chinese analysis error which is safe to show in the App."""


def analysis_error_message(exc: BaseException) -> str:
    """Return a Chinese user-facing message without leaking implementation details."""
    if isinstance(exc, AnalysisUserError):
        return str(exc)
    if isinstance(exc, AnalysisCancelledError):
        return "分析已取消。"

    message = str(exc).strip()
    if isinstance(exc, ValueError):
        if message.startswith("请填写期号"):
            return "完整分析失败：请填写正确的期号。"
        if "最高购彩金额" in message:
            return "完整分析失败：最高购彩金额不能低于 2 元。"
        lowered = message.casefold()
        if "returned issue" in lowered or "belongs to issue" in lowered or "mixed issue" in lowered:
            return "完整分析失败：期号与获取到的赛程不一致，请确认期号后重新分析。"
        if "sfc table not found" in lowered or "expected 14 matches" in lowered:
            return "完整分析失败：没有获取到完整的 14 场赛程，请确认该期已经开售后重试。"
        return "完整分析失败：获取到的赛程或赔率数据不完整，请稍后重新分析。"
    if isinstance(exc, TimeoutError):
        return "完整分析失败：连接数据源超时，请检查网络后重试。"
    if isinstance(exc, urllib.error.HTTPError):
        return "完整分析失败：数据服务暂时无法访问，请稍后重试。"
    if isinstance(exc, (urllib.error.URLError, ConnectionError)):
        return "完整分析失败：无法连接数据源，请检查手机网络后重试。"
    if isinstance(exc, PermissionError):
        return "完整分析失败：无法保存本机报告，请检查 App 存储空间后重试。"
    if isinstance(exc, OSError):
        return "完整分析失败：读取或保存分析数据失败，请检查网络和手机存储空间后重试。"
    return "完整分析失败：本机分析引擎遇到异常，请重新尝试；如果仍然失败，请重新打开 App。"


def _validate_analysis_issue(issue: str, *, now: datetime | None = None) -> None:
    if not re.fullmatch(r"\d{5}", issue):
        raise AnalysisUserError("完整分析失败：期号格式不正确，请输入 5 位数字，例如 26105。")

    current_year = (now or datetime.now().astimezone()).year % 100
    issue_year = int(issue[:2])
    issue_sequence = int(issue[2:])
    allowed_years = {(current_year - 1) % 100, current_year, (current_year + 1) % 100}
    if issue_year not in allowed_years or issue_sequence == 0:
        raise AnalysisUserError(f"完整分析失败：第 {issue} 期不存在，请检查期号后重试。")


def _analysis_collection_error_message(exc: BaseException, issue: str) -> str:
    message = str(exc).strip()
    lowered = message.casefold()
    if isinstance(exc, ValueError):
        if "returned issue" in lowered or "belongs to issue" in lowered or "mixed issue" in lowered:
            return f"完整分析失败：没有找到第 {issue} 期，请检查期号是否正确，或确认该期已经开售。"
        if "sfc table not found" in lowered:
            return f"完整分析失败：第 {issue} 期暂时没有可用赛程，请确认期号正确且该期已经开售。"
        match_count = re.search(r"expected 14 matches, got (\d+)", lowered)
        if match_count:
            return (
                f"完整分析失败：第 {issue} 期赛程不完整，目前只获取到 "
                f"{match_count.group(1)} 场，完整分析需要 14 场。"
            )
    return analysis_error_message(exc)


def _analysis_cancel_path(payload: dict[str, Any], work_dir: str | Path) -> Path | None:
    token = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("cancel_token") or ""))
    if not token:
        return None
    return Path(work_dir) / "cache" / f"analysis_cancel_{token}.flag"


def _run_analysis(
    payload: dict[str, Any],
    work_dir: str | Path,
    *,
    cancel_path: Path | None,
) -> dict[str, object]:
    def check_cancelled() -> None:
        if cancel_path is not None and cancel_path.exists():
            raise AnalysisCancelledError("分析已取消。")

    issue = str(payload.get("issue") or "").strip()
    if not issue:
        raise ValueError("请填写期号。")
    _validate_analysis_issue(issue)
    max_ticket_cost_yuan = int(payload.get("max_ticket_cost_yuan") or DEFAULT_MAX_TICKET_COST_YUAN)
    if max_ticket_cost_yuan < 2:
        raise ValueError("最高购彩金额不能低于 2 元。")
    # 手机端只执行完整分析。样本数是模型参数，不再暴露给用户调整。
    foreign_odds = bool(payload.get("foreign_odds", False))
    foreign_odds_api_key = str(payload.get("foreign_odds_api_key") or "").strip() or None
    football_data_api_key = str(payload.get("football_data_api_key") or "").strip() or None
    use_foreign_odds = foreign_odds or foreign_odds_api_key is not None

    root = Path(work_dir)
    data_dir = root / "data"
    report_dir = root / "reports"
    history_dir = report_dir / "history"
    cache_dir = root / "cache"
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    check_cancelled()

    issue_path = data_dir / "collected_issue.json"
    issue_archive_path = data_dir / f"{_slug(issue)}_issue.json"
    markdown_path = report_dir / f"{_slug(issue)}_report.md"
    html_path = report_dir / f"{_slug(issue)}_report.html"

    reused_snapshot = False
    if not bool(payload.get("force_refresh", False)):
        reused_snapshot = _reuse_recent_issue_snapshot(
            issue_archive_path,
            issue_path,
            issue=issue,
            foreign_odds_configured=foreign_odds_api_key is not None,
            football_data_configured=football_data_api_key is not None,
        )
    check_cancelled()

    if not reused_snapshot:
        try:
            _collect_mobile_analysis(
                issue_path=issue_path,
                issue=issue,
                cache_dir=cache_dir,
                use_foreign_odds=use_foreign_odds,
                foreign_odds_api_key=foreign_odds_api_key,
                football_data_api_key=football_data_api_key,
                cancel_check=check_cancelled,
            )
        except AnalysisCancelledError:
            raise
        except Exception as exc:
            # Preserve the original cause for developer diagnostics. The App
            # still receives only the sanitized Chinese AnalysisUserError.
            raise AnalysisUserError(_analysis_collection_error_message(exc, issue)) from exc
    if _full_collection_has_broad_critical_failure(issue_path):
        unavailable = _full_collection_failed_sources(issue_path)
        source_text = "、".join(str(item) for item in unavailable)
        detail = f"（{source_text}）" if source_text else ""
        raise AnalysisUserError(
            "完整分析失败：多个关键资料源大范围不可用"
            f"{detail}。请检查网络后重试，本次未生成分析报告。"
        )
    check_cancelled()
    _record_analysis_mode(issue_path)
    check_cancelled()
    if issue_path.exists():
        issue_archive_path.write_text(issue_path.read_text(encoding="utf-8"), encoding="utf-8")
    check_cancelled()
    calibration = build_calibration(root)
    active_weights = load_active_model_weights(root)
    active_selection_policy = load_active_selection_policy(root)
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
    strategy_options: dict[str, Any] = {"max_ticket_cost_yuan": max_ticket_cost_yuan}
    if active_weights is not None:
        strategy_options["model_weights"] = active_weights
    if active_selection_policy is not None:
        strategy_options["selection_policy"] = active_selection_policy
    strategy_options["evidence_aware_secondary"] = True
    plan = build_ticket_plan(issue_data, **strategy_options)
    check_cancelled()
    with tempfile.TemporaryDirectory(prefix="analysis-", dir=report_dir) as temp_dir:
        temporary_markdown_path = Path(temp_dir) / markdown_path.name
        temporary_html_path = Path(temp_dir) / html_path.name
        write_report(plan, temporary_markdown_path)
        write_analysis_html(plan, temporary_html_path)
        check_cancelled()
        if temporary_markdown_path.exists():
            temporary_markdown_path.replace(markdown_path)
        if temporary_html_path.exists():
            temporary_html_path.replace(html_path)
    check_cancelled()
    history_path = archive_report(
        "analysis",
        plan.issue.issue,
        html_path,
        markdown_path,
        history_dir=history_dir,
        snapshot_path=issue_path,
        condition_key=_analysis_condition_key(issue, max_ticket_cost_yuan),
    )

    return {
        "ok": True,
        "message": f"{issue} 分析报告已在手机本机生成。",
        "report": {**serialize_ticket_plan(plan), "model_calibration": calibration},
        "html_path": str(html_path),
        "markdown_path": str(markdown_path),
        "history_path": str(history_path),
    }


def _analysis_condition_key(issue: str, max_ticket_cost_yuan: int) -> str:
    return f"analysis|issue={issue.strip()}|max_ticket_cost_yuan={max_ticket_cost_yuan}"


def _reuse_recent_issue_snapshot(
    archive_path: Path,
    output_path: Path,
    *,
    issue: str,
    foreign_odds_configured: bool,
    football_data_configured: bool = False,
    now: datetime | None = None,
) -> bool:
    """Reuse only an immediately preceding equivalent full collection.

    This protects against double taps and an accidental immediate rerun while
    keeping live odds fresh during normal use.  The original collection time
    remains unchanged, so repeated reuse cannot extend the three-minute window.
    """
    try:
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    metadata = payload.get("metadata")
    matches = payload.get("matches")
    if (
        str(payload.get("issue") or "").strip() != issue.strip()
        or not isinstance(metadata, dict)
        or metadata.get("analysis_mode") != "full"
        or not isinstance(matches, list)
        or len(matches) != 14
    ):
        return False
    audit = metadata.get("foreign_odds_audit")
    previous_foreign_configured = bool(audit.get("configured")) if isinstance(audit, dict) else False
    if previous_foreign_configured != foreign_odds_configured:
        return False
    auxiliary_audit = metadata.get("free_auxiliary_sources_audit")
    auxiliary_providers = auxiliary_audit.get("providers") if isinstance(auxiliary_audit, dict) else {}
    football_data_audit = (
        auxiliary_providers.get("football-data.org") if isinstance(auxiliary_providers, dict) else {}
    )
    previous_football_data_configured = (
        bool(football_data_audit.get("configured")) if isinstance(football_data_audit, dict) else False
    )
    if previous_football_data_configured != football_data_configured:
        return False
    try:
        collected_at = datetime.fromisoformat(str(metadata.get("snapshot_collected_at") or ""))
    except ValueError:
        return False
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age_seconds = (current.astimezone(timezone.utc) - collected_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age_seconds <= RECENT_SNAPSHOT_REUSE_SECONDS:
        return False

    metadata["snapshot_reused"] = True
    metadata["snapshot_reused_at"] = current.astimezone(timezone.utc).isoformat()
    metadata["snapshot_reuse_age_seconds"] = round(age_seconds, 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _collect_mobile_analysis(
    *,
    issue_path: Path,
    issue: str,
    cache_dir: Path,
    use_foreign_odds: bool,
    foreign_odds_api_key: str | None,
    football_data_api_key: str | None = None,
    cancel_check: Any | None = None,
) -> None:
    collect_issue(
        output_path=issue_path,
        issue=issue,
        cache_dir=cache_dir,
        foreign_odds=use_foreign_odds,
        foreign_odds_requested=True,
        foreign_odds_api_key=foreign_odds_api_key,
        football_data_api_key=football_data_api_key,
        strength_model=True,
        strength_xg_matches=STRENGTH_XG_MATCHES,
        skip_context_fetches=False,
        sina_odds_only=False,
        cancel_check=cancel_check,
    )


def _full_collection_has_broad_critical_failure(issue_path: Path) -> bool:
    try:
        payload = json.loads(issue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    audits = []
    for match in payload.get("matches", []):
        sources = match.get("sources") if isinstance(match, dict) else None
        audit = sources.get("collection_audit") if isinstance(sources, dict) else None
        if isinstance(audit, dict):
            audits.append(audit)
    if not audits:
        return False
    broad_failures = 0
    for audit in audits:
        failed = sum(
            1
            for key in NETWORK_SENSITIVE_SOURCE_LABELS
            if isinstance(audit.get(key), dict)
            and audit[key].get("status") in {"request_failed", "provider_error", "missing_match_id"}
        )
        if failed >= 3:
            broad_failures += 1
    threshold = max(3, (len(audits) * 2 + 2) // 3)
    return broad_failures >= threshold


def _full_collection_failed_sources(issue_path: Path) -> list[str]:
    try:
        payload = json.loads(issue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(NETWORK_SENSITIVE_SOURCE_LABELS.values())

    all_missing: list[str] = []
    for match in payload.get("matches", []):
        if not isinstance(match, dict):
            continue
        sources = match.get("sources") if isinstance(match.get("sources"), dict) else {}
        audit = sources.get("collection_audit") if isinstance(sources, dict) else {}
        if not isinstance(audit, dict):
            continue
        missing = [
            label
            for key, label in NETWORK_SENSITIVE_SOURCE_LABELS.items()
            if isinstance(audit.get(key), dict)
            and audit[key].get("status") in {"request_failed", "provider_error", "missing_match_id"}
        ]
        if not missing:
            continue
        for label in missing:
            if label not in all_missing:
                all_missing.append(label)
    return all_missing or list(NETWORK_SENSITIVE_SOURCE_LABELS.values())


def _record_analysis_mode(
    issue_path: Path,
) -> None:
    try:
        payload = json.loads(issue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    metadata = payload.setdefault("metadata", {})
    metadata["analysis_mode_requested"] = "full"
    metadata["analysis_mode"] = "full"
    metadata["analysis_mode_message"] = "已完成完整分析，增强样本固定为最近 20 场。"
    metadata.pop("analysis_unavailable_sources", None)
    issue_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def run_delete_history(payload: dict[str, Any], work_dir: str | Path) -> dict[str, object]:
    raw_ids = payload.get("entry_ids")
    entry_ids = [str(item).strip() for item in raw_ids] if isinstance(raw_ids, list) else []
    entry_ids = [item for item in entry_ids if item]
    if not entry_ids:
        raise ValueError("没有选择要删除的分析记录。")
    history_dir = Path(work_dir) / "reports" / "history"
    deleted_ids = delete_history_entries(history_dir, entry_ids, kind="analysis")
    if not deleted_ids:
        raise ValueError("所选分析记录不存在或已经删除。")
    return {
        "ok": True,
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "message": f"已删除 {len(deleted_ids)} 条分析记录。",
    }


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
    reasons_by_seq = _parse_analysis_reasons(markdown_text)
    predictions = []

    for line in markdown_text.splitlines():
        if not line.startswith("| "):
            continue
        if "---" in line or "序号" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue

        seq = int(cells[0])
        home, away = _split_matchup(cells[2])
        legacy_layout = len(cells) >= 8
        dual_selection_layout = len(cells) == 7
        confidence_cell = cells[5] if legacy_layout or dual_selection_layout else cells[4]
        probability_cell = cells[7] if legacy_layout else cells[6] if dual_selection_layout else cells[5]
        analysis_pick_text = cells[3]
        pick_text = cells[4] if dual_selection_layout else analysis_pick_text
        picks = tuple(pick for pick in pick_text.split("/") if pick in OUTCOME_LABELS)
        probabilities = _parse_probabilities(probability_cell)
        reasons = list(reasons_by_seq.get(seq, []))
        if picks and not any(reason.startswith(SELECTION_REASON_PREFIX) for reason in reasons):
            outcome_probabilities = {
                "3": float(probabilities["home"]) / 100.0,
                "1": float(probabilities["draw"]) / 100.0,
                "0": float(probabilities["away"]) / 100.0,
            }
            reasons.insert(0, selection_reason_from_values(picks, outcome_probabilities))
        predictions.append(
            {
                "seq": seq,
                "league": cells[1],
                "kickoff_display": kickoff_by_seq.get(seq, ""),
                "home": home,
                "away": away,
                "pick_text": pick_text,
                "pick_labels": [OUTCOME_LABELS.get(pick, pick) for pick in pick_text.split("/") if pick],
                "analysis_pick_text": analysis_pick_text,
                "analysis_pick_labels": [
                    OUTCOME_LABELS.get(pick, pick) for pick in analysis_pick_text.split("/") if pick
                ],
                "budget_adjusted": pick_text != analysis_pick_text,
                "budget_forced_single": pick_text != analysis_pick_text and "/" not in pick_text,
                "tactical_draw": any("战术单平" in reason for reason in reasons),
                "confidence": _parse_percent(confidence_cell),
                "risk": cells[6] if legacy_layout else "",
                "probabilities": probabilities,
                "scorelines": _parse_scorelines(cells[4]) if legacy_layout else [],
                "reasons": reasons,
                "final_score": "",
                "final_result": "",
                "final_result_label": "",
                "outcome_hit": False,
            }
        )

    if not predictions:
        return None

    low_risk = sum(1 for prediction in predictions if prediction["risk"] == "低")
    singles = sum(1 for prediction in predictions if "/" not in str(prediction["analysis_pick_text"]))
    ticket_singles = sum(1 for prediction in predictions if "/" not in str(prediction["pick_text"]))
    forced_singles = sum(1 for prediction in predictions if prediction["budget_forced_single"])
    tactical_draws = sum(1 for prediction in predictions if prediction["tactical_draw"])
    avg_confidence = sum(float(prediction["confidence"]) for prediction in predictions) / len(predictions)
    metadata = _parse_analysis_metadata(markdown_text)
    return {
        "issue": issue,
        "purchase_deadline": metadata.get("purchase_deadline", ""),
        "purchase_deadline_source": metadata.get("purchase_deadline_source", ""),
        "sale_begin_time": metadata.get("sale_begin_time", ""),
        "analysis_mode": "full",
        "analysis_mode_message": "",
        "foreign_odds_status": None,
        "metrics": {
            "match_count": len(predictions),
            "single_count": singles,
            "ticket_single_count": ticket_singles,
            "budget_forced_single_count": forced_singles,
            "tactical_draw_count": tactical_draws,
            "low_risk_count": low_risk,
            "average_confidence": round(avg_confidence, 1),
        },
        "choose9_keep": keep,
        "choose9_drop": drop,
        "predictions": predictions,
    }


def _parse_analysis_reasons(markdown_text: str) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    in_details = False
    current_seq: int | None = None
    metadata_prefixes = (
        "比赛：",
        "推荐：",
        "模型建议：",
        "预算票面：",
        "比分倾向：",
        "置信度：",
        "风险：",
    )
    for line in markdown_text.splitlines():
        if line.strip() == "## 详细理由":
            in_details = True
            current_seq = None
            continue
        if not in_details:
            continue
        if line.startswith("## "):
            break
        header = re.match(r"^###\s+(\d+)\.", line)
        if header:
            current_seq = int(header.group(1))
            result.setdefault(current_seq, [])
            continue
        if current_seq is None or not line.startswith("- "):
            continue
        reason = line[2:].strip()
        if reason and not reason.startswith(metadata_prefixes):
            result[current_seq].append(reason)
    return result


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
    if report.get("purchase_deadline") and report.get("foreign_odds_status"):
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
        restored = dict(report)
        for key in (
            "purchase_deadline",
            "purchase_deadline_source",
            "sale_begin_time",
            "analysis_mode",
            "analysis_mode_message",
            "analysis_unavailable_sources",
        ):
            value = metadata.get(key)
            if value:
                restored[key] = value
        foreign_odds_status = metadata.get("foreign_odds_audit")
        if isinstance(foreign_odds_status, dict):
            restored["foreign_odds_status"] = foreign_odds_status
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
        analysis_pick_text, pick_text = _parse_review_selection(cells[4])
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
                "analysis_pick_text": analysis_pick_text,
                "analysis_pick_labels": [
                    OUTCOME_LABELS.get(pick, pick) for pick in analysis_pick_text.split("/") if pick
                ],
                "budget_adjusted": pick_text != analysis_pick_text,
                "budget_forced_single": pick_text != analysis_pick_text and "/" not in pick_text,
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


def _parse_review_selection(value: str) -> tuple[str, str]:
    cleaned = value.strip()
    adjusted = re.fullmatch(
        r"模型\s*([310](?:\s*/\s*[310])*)\s*(?:→|->)\s*预算\s*([310](?:\s*/\s*[310])*)",
        cleaned,
    )
    if adjusted:
        analysis = re.sub(r"\s+", "", adjusted.group(1))
        ticket = re.sub(r"\s+", "", adjusted.group(2))
        return analysis, ticket
    picks = re.findall(r"[310]", cleaned)
    normalized = "/".join(picks)
    return normalized, normalized


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
    analysis_id = str(payload.get("analysis_id") or "").strip()
    plan = _load_analysis_plan(issue_path, history_dir, issue, analysis_id)
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
    archive_report(
        "review",
        plan.issue.issue,
        html_path,
        markdown_path,
        history_dir=history_dir,
        snapshot_path=_resolve_analysis_snapshot(history_dir, issue, analysis_id, issue_path),
    )
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


def _load_analysis_plan(
    issue_path: Path,
    history_dir: Path,
    issue: str,
    analysis_id: str = "",
) -> TicketPlan:
    entries = [
        entry
        for entry in load_history_entries(history_dir)
        if entry.get("kind") == "analysis" and str(entry.get("issue") or "").strip() == issue
    ]
    if analysis_id:
        entries = [entry for entry in entries if str(entry.get("id") or "") == analysis_id]
        if not entries:
            raise ValueError("找不到所选的分析记录，请重新选择后再复盘。")
    elif len(entries) > 1:
        raise ValueError(f"发现 {len(entries)} 次分析结果，请先选择要依据哪一次分析进行复盘。")

    selected_issue_path = _entry_snapshot_path(history_dir, entries[0]) if entries else None
    plan = build_ticket_plan(load_issue(selected_issue_path or issue_path))

    for entry in entries:
        report = _parse_history_report(
            _read_history_text(history_dir, str(entry.get("markdown") or "")),
            fallback_issue=issue,
            kind="analysis",
        )
        restored = _restore_analysis_recommendations(plan, report)
        if restored:
            return restored
        if analysis_id:
            raise ValueError("所选分析记录不完整，无法用于复盘，请选择其他记录。")
    return plan


def _resolve_analysis_snapshot(
    history_dir: Path,
    issue: str,
    analysis_id: str,
    fallback: Path,
) -> Path:
    entries = [
        entry
        for entry in load_history_entries(history_dir)
        if entry.get("kind") == "analysis"
        and str(entry.get("issue") or "").strip() == issue
        and (not analysis_id or str(entry.get("id") or "") == analysis_id)
    ]
    if len(entries) == 1:
        return _entry_snapshot_path(history_dir, entries[0]) or fallback
    return fallback


def _entry_snapshot_path(history_dir: Path, entry: dict[str, str]) -> Path | None:
    relative = str(entry.get("snapshot") or "").strip()
    if not relative:
        return None
    candidate = history_dir / relative
    return candidate if candidate.exists() else None


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
    saved_original_picks: dict[int, tuple[str, ...]] = {}
    saved_budget_flags: dict[int, tuple[bool, bool]] = {}
    saved_tactical_draws: dict[int, bool] = {}
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
        original_picks = tuple(
            item
            for item in str(saved.get("analysis_pick_text") or saved.get("pick_text") or "").split("/")
            if item in OUTCOME_LABELS
        )
        saved_original_picks[seq] = original_picks or picks
        saved_budget_flags[seq] = (
            bool(saved.get("budget_adjusted")),
            bool(saved.get("budget_forced_single")),
        )
        saved_tactical_draws[seq] = bool(saved.get("tactical_draw"))

    current_sequences = {prediction.match.seq for prediction in plan.predictions}
    if set(saved_picks) != current_sequences:
        return None

    saved_keep = _valid_sequence_list(report.get("choose9_keep"), current_sequences, expected_count=9)
    saved_drop = _valid_sequence_list(report.get("choose9_drop"), current_sequences, expected_count=5)
    if saved_keep is None or saved_drop is None or set(saved_keep) & set(saved_drop):
        return None

    restored_predictions = tuple(
            replace(
                prediction,
                picks=saved_picks[prediction.match.seq],
                original_picks=saved_original_picks[prediction.match.seq],
                budget_adjusted=saved_budget_flags[prediction.match.seq][0],
                budget_forced_single=saved_budget_flags[prediction.match.seq][1],
                tactical_draw=saved_tactical_draws[prediction.match.seq],
            )
            for prediction in plan.predictions
        )
    budget = report.get("budget") if isinstance(report.get("budget"), dict) else {}
    restored_hedge = _restore_draw_hedge(plan, report.get("draw_hedge"))
    restored_portfolio = _restore_line_portfolio(report.get("line_portfolio"))
    return TicketPlan(
        issue=plan.issue,
        predictions=restored_predictions,
        choose9_keep=saved_keep,
        choose9_drop=saved_drop,
        max_ticket_cost_yuan=int(budget.get("limit_yuan") or plan.max_ticket_cost_yuan),
        main_allocated_budget_yuan=int(
            budget.get("main_allocated_yuan") or plan.main_allocated_budget_yuan
        ),
        main_cost_yuan=int(budget.get("main_cost_yuan") or plan.main_cost_yuan),
        draw_hedge=restored_hedge,
        line_portfolio=restored_portfolio,
    )


def _restore_line_portfolio(value: object) -> LinePortfolioPlan | None:
    if not isinstance(value, dict):
        return None
    raw_lines = value.get("lines")
    raw_coverages = value.get("draw_coverages")
    if not isinstance(raw_lines, list) or not isinstance(raw_coverages, list):
        return None
    try:
        lines = tuple(
            TicketLine(
                outcomes=tuple(str(outcome) for outcome in item["outcomes"]),
                joint_probability=float(item.get("joint_probability") or 0.0),
            )
            for item in raw_lines
            if isinstance(item, dict) and isinstance(item.get("outcomes"), list)
        )
        coverages = tuple(
            DrawLineCoverage(
                seq=int(item["seq"]),
                probability=float(item.get("probability") or 0.0) / 100.0,
                target_lines=int(item.get("target_lines") or 0),
                actual_lines=int(item.get("actual_lines") or 0),
            )
            for item in raw_coverages
            if isinstance(item, dict)
        )
        if not lines or any(len(line.outcomes) != 14 for line in lines):
            return None
        return LinePortfolioPlan(
            lines=lines,
            draw_coverages=coverages,
            allocated_budget_yuan=int(value.get("allocated_budget_yuan") or 0),
            cost_yuan=int(value.get("cost_yuan") or 0),
            multi_draw_lines=int(value.get("multi_draw_lines") or 0),
            minimum_draw_pair_lines=int(value.get("minimum_draw_pair_lines") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _restore_draw_hedge(plan: TicketPlan, value: object) -> DrawHedgePlan | None:
    if not isinstance(value, dict):
        return None
    selections = value.get("selections")
    if not isinstance(selections, list):
        return None
    saved: dict[int, tuple[str, ...]] = {}
    for item in selections:
        if not isinstance(item, dict):
            return None
        try:
            seq = int(item.get("seq"))
        except (TypeError, ValueError):
            return None
        picks = tuple(
            pick for pick in str(item.get("pick_text") or "").split("/") if pick in OUTCOME_LABELS
        )
        if not picks:
            return None
        saved[seq] = picks
    current = {prediction.match.seq: prediction for prediction in plan.predictions}
    if set(saved) != set(current):
        return None
    try:
        candidate_seq = int(value.get("candidate_seq"))
        line_count = int(value.get("line_count"))
        cost_yuan = int(value.get("cost_yuan"))
        allocated = int(value.get("allocated_budget_yuan"))
        score = float(value.get("score") or 0.0) / 100.0
    except (TypeError, ValueError):
        return None
    if candidate_seq not in current or saved.get(candidate_seq) != ("1",):
        return None
    return DrawHedgePlan(
        candidate_seq=candidate_seq,
        predictions=tuple(
            replace(current[seq], picks=saved[seq], original_picks=current[seq].analysis_picks)
            for seq in sorted(current)
        ),
        allocated_budget_yuan=allocated,
        line_count=line_count,
        cost_yuan=cost_yuan,
        score=score,
        evidence=tuple(str(item) for item in value.get("evidence") or ()),
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
    report = serialize_ticket_plan(review.plan, include_review_fields=True)
    by_seq = {row.prediction.match.seq: row for row in review.rows}
    predictions = []
    for prediction in report["predictions"]:
        row = by_seq.get(int(prediction["seq"]))
        if row:
            prediction = dict(prediction)
            prediction["final_score"] = row.result.score_text
            prediction["final_result"] = row.result.outcome
            prediction["final_result_label"] = row.result.outcome_label
            prediction["outcome_hit"] = row.outcome_hit
            prediction["analysis_outcome_hit"] = row.analysis_outcome_hit
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
        "ticket_single_count": sum(
            1 for row in review.rows if len(row.prediction.picks) == 1 and row.outcome_hit
        ),
        "budget_forced_single_count": review.budget_caused_misses,
        "draw_hedge_count": int(review.plan.draw_hedge is not None),
        "line_portfolio_count": review.plan.line_portfolio.line_count if review.plan.line_portfolio else 0,
        "line_portfolio_best_hits": review.line_portfolio_best_hits,
        "actual_draw_combination_lines": review.actual_draw_combination_lines,
        "low_risk_count": review.outcome_hits,
        "average_confidence": round(review.outcome_hits / review.total * 100, 1) if review.total else 0.0,
    }
    if isinstance(report.get("draw_hedge"), dict):
        report["draw_hedge"] = {
            **report["draw_hedge"],
            "candidate_hit": review.draw_hedge_candidate_hit,
            "outcome_hits": review.draw_hedge_outcome_hits,
            "outcome_total": review.total,
            "full_coverage": review.draw_hedge_full_coverage,
        }
    if isinstance(report.get("line_portfolio"), dict):
        report["line_portfolio"] = {
            **report["line_portfolio"],
            "portfolio_hit": review.line_portfolio_hit,
            "best_line_hits": review.line_portfolio_best_hits,
            "actual_draw_total": review.actual_draw_total,
            "actual_draw_combination_lines": review.actual_draw_combination_lines,
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
