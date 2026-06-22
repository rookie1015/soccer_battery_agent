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
    lines.append("## 任九建议")
    lines.append("")
    lines.append(f"- 建议保留：{_join_seq(plan.choose9_keep)}")
    lines.append(f"- 建议剔除：{_join_seq(plan.choose9_drop)}")
    lines.append("")
    lines.append("## 14场逐场建议")
    lines.append("")
    lines.append("| 序号 | 联赛 | 对阵 | 推荐 | 比分倾向 | 置信度 | 风险 | 概率(3/1/0) |")
    lines.append("| --- | --- | --- | --- | --- | ---: | --- | --- |")
    for pred in plan.predictions:
        match = pred.match
        prob_text = f"{pred.probabilities['3']:.0%}/{pred.probabilities['1']:.0%}/{pred.probabilities['0']:.0%}"
        lines.append(
            f"| {match.seq} | {match.league} | {match.home} vs {match.away} | "
            f"{pred.pick_text} | {_scoreline_summary(pred)} | {pred.confidence:.1f}% | {pred.risk} | {prob_text} |"
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
        f"- 推荐：`{prediction.pick_text}`（{_pick_labels(prediction.picks)}）",
        f"- 比分倾向：{_scoreline_summary(prediction)}",
        f"- 风险：{prediction.risk}",
    ]
    for reason in prediction.reasons:
        lines.append(f"- {reason}")
    return lines


def _pick_labels(picks: tuple[str, ...]) -> str:
    return " / ".join(OUTCOME_LABELS[pick] for pick in picks)


def _scoreline_summary(prediction: Prediction) -> str:
    return "，".join(f"{item.text} {item.probability:.0%}" for item in prediction.scorelines)


def _join_seq(items: tuple[int, ...]) -> str:
    return "、".join(str(item) for item in items)
