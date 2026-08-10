from __future__ import annotations

from pathlib import Path

from .models import Prediction, TicketPlan
from .predictor import OUTCOME_LABELS


def render_markdown(plan: TicketPlan) -> str:
    lines: list[str] = []
    lines.append(f"# 足球彩票分析报告：{plan.issue.issue}")
    lines.append("")
    lines.append("> 仅供信息分析和娱乐参考，不保证中奖。请控制预算，理性购彩。")
    lines.append("")
    metadata = plan.issue.metadata
    purchase_deadline = str(metadata.get("purchase_deadline") or "").strip()
    if purchase_deadline:
        lines.append("## 期次信息")
        lines.append("")
        lines.append(f"- 购彩截止时间：{purchase_deadline}")
        purchase_deadline_source = str(metadata.get("purchase_deadline_source") or "").strip()
        if purchase_deadline_source:
            lines.append(f"- 截止时间来源：{purchase_deadline_source}")
        sale_begin_time = str(metadata.get("sale_begin_time") or "").strip()
        if sale_begin_time:
            lines.append(f"- 开售时间：{sale_begin_time}")
        lines.append("")
    analysis_mode_message = str(metadata.get("analysis_mode_message") or "").strip()
    if analysis_mode_message:
        lines.append("## 分析模式")
        lines.append("")
        lines.append(f"- {analysis_mode_message}")
        lines.append("")
    foreign_status = metadata.get("foreign_odds_audit")
    if isinstance(foreign_status, dict) and foreign_status.get("requested"):
        lines.append("## 外盘调用状态")
        lines.append("")
        lines.append(f"- 状态：{foreign_status.get('status', '')}")
        lines.append(f"- 说明：{foreign_status.get('message', '')}")
        lines.append(
            f"- 匹配：{int(foreign_status.get('matched_matches') or 0)}/"
            f"{int(foreign_status.get('total_matches') or 0)} 场"
        )
        lines.append(
            f"- 请求：本次联网 {int(foreign_status.get('attempted_queries') or 0)} 次，"
            f"成功 {int(foreign_status.get('successful_queries') or 0)} 次，"
            f"缓存命中 {int(foreign_status.get('cache_hits') or 0)} 次"
        )
        quota = _quota_text(foreign_status)
        if quota:
            lines.append(f"- 额度：{quota}")
        lines.append("")
    lines.append("## 任九建议")
    lines.append("")
    lines.append(f"- 建议保留：{_join_seq(plan.choose9_keep)}")
    lines.append(f"- 建议剔除：{_join_seq(plan.choose9_drop)}")
    lines.append("")
    lines.append("## 14场逐场建议")
    lines.append("")
    lines.append("| 序号 | 联赛 | 对阵 | 模型建议 | 预算票面 | 置信度 | 概率(3/1/0) |")
    lines.append("| --- | --- | --- | --- | --- | ---: | --- |")
    for pred in plan.predictions:
        match = pred.match
        prob_text = f"{pred.probabilities['3']:.0%}/{pred.probabilities['1']:.0%}/{pred.probabilities['0']:.0%}"
        lines.append(
            f"| {match.seq} | {match.league} | {match.home} vs {match.away} | "
            f"{pred.analysis_pick_text} | {pred.pick_text} | {pred.confidence:.1f}% | {prob_text} |"
        )

    lines.append("")
    lines.append("## 详细理由")
    lines.append("")
    for pred in plan.predictions:
        lines.extend(_render_prediction(pred))
        lines.append("")

    lines.append("## 符号说明")
    lines.append("")
    lines.append("- `3` = 主胜")
    lines.append("- `1` = 平")
    lines.append("- `0` = 客胜")
    lines.append("")
    return "\n".join(lines)


def write_report(plan: TicketPlan, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(plan), encoding="utf-8")
    return path


def _render_prediction(prediction: Prediction) -> list[str]:
    match = prediction.match
    lines = [
        f"### {match.seq}. {match.home} vs {match.away}",
        "",
        f"- 比赛：{match.league}，{match.kickoff.isoformat()}",
        f"- 模型建议：`{prediction.analysis_pick_text}`（{_pick_labels(prediction.analysis_picks)}）",
        f"- 置信度：{prediction.confidence:.1f}%",
    ]
    if prediction.budget_adjusted:
        warning = "，预算强制单选，不能视为模型胆材" if prediction.budget_forced_single else ""
        lines.append(f"- 预算票面：`{prediction.pick_text}`（{_pick_labels(prediction.picks)}）{warning}")
    for reason in prediction.reasons:
        lines.append(f"- {reason}")
    return lines


def _pick_labels(picks: tuple[str, ...]) -> str:
    return " / ".join(OUTCOME_LABELS[pick] for pick in picks)


def _scoreline_summary(prediction: Prediction) -> str:
    return "，".join(f"{item.text} {item.probability:.0%}" for item in prediction.scorelines)


def _join_seq(items: tuple[int, ...]) -> str:
    return "、".join(str(item) for item in items)


def _quota_text(status: dict[str, object]) -> str:
    parts = []
    labels = (
        ("credits_remaining", "剩余"),
        ("credits_used", "累计已用"),
        ("credits_last", "本次消耗"),
    )
    for key, label in labels:
        value = status.get(key)
        if value is not None:
            parts.append(f"{label} {value}")
    return "，".join(parts)
