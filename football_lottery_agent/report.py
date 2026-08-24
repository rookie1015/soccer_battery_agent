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
    lines.append("## 正规复式出票")
    lines.append("")
    if plan.line_portfolio:
        portfolio = plan.line_portfolio
        lines.append(
            f"- 独立线路：{portfolio.line_count} 注，实际成本 "
            f"{portfolio.cost_yuan}/{portfolio.allocated_budget_yuan} 元。"
        )
        lines.append(
            f"- 多平组合：{portfolio.multi_draw_lines} 注至少包含两个候选平局；"
            f"任意两场候选同时为平至少 {portfolio.minimum_draw_pair_lines} 注。"
        )
        lines.append("- 规则：模型建议中保留的每一个平局都按概率获得线路配额，不再只选一场对冲。")
    else:
        units = _ticket_units(plan.predictions)
        lines.append(
            f"- 主票：各场预算票面选择数相乘为 {units} 注，每注 2 元，"
            f"实际 {plan.main_cost_yuan}/{plan.main_allocated_budget_yuan} 元。"
        )
        lines.append("- 计价规则：仅以“预算票面”列作为实际复式选择；“模型建议”列不参与出票计价。")
    if plan.draw_hedge and not plan.line_portfolio:
        hedge = plan.draw_hedge
        candidate = next(
            prediction for prediction in hedge.predictions if prediction.match.seq == hedge.candidate_seq
        )
        selections = "-".join(prediction.pick_text for prediction in hedge.predictions)
        lines.append(
            f"- 平局对冲：第 {hedge.candidate_seq} 场 {candidate.match.home} vs {candidate.match.away} "
            f"固定单选平；分配 {hedge.allocated_budget_yuan} 元，{hedge.line_count} 注，"
            f"实际 {hedge.cost_yuan} 元。"
        )
        lines.append(f"- 对冲分支票面：`{selections}`")
        lines.append(f"- 对冲依据：{'；'.join(hedge.evidence)}。")
        lines.append("- 风险说明：对冲分支不是稳胆，与主票共同计算总预算。")
    elif not plan.line_portfolio:
        lines.append("- 平局对冲：本期没有通过门槛且被主票删除的候选，不强行设置单平。")
    lines.append(
        f"- 组合总成本：{plan.total_cost_yuan}/{plan.max_ticket_cost_yuan} 元。"
    )
    lines.append("")
    lines.append("## 任九建议（独立优化）")
    lines.append("")
    if plan.choose9_plan:
        choose9 = plan.choose9_plan
        lines.append(
            f"- 任九票：独立选择 9 场，{choose9.line_count} 注，每注 2 元，"
            f"实际 {choose9.cost_yuan}/{choose9.allocated_budget_yuan} 元。"
        )
        lines.append(
            "- 预算口径：任九与十四场共享基础概率，但场次和票面分别优化；"
            "两种玩法的金额各自计算，若同时购买需要相加。"
        )
        lines.append(
            f"- 理论联合覆盖率：{choose9.joint_coverage_probability:.2%}；"
            "这是按各场概率近似独立计算的模型值，不代表中奖保证。"
        )
    lines.append(f"- 建议保留：{_join_seq(plan.choose9_keep)}")
    lines.append(f"- 建议剔除：{_join_seq(plan.choose9_drop)}")
    lines.append("")
    if plan.choose9_plan:
        lines.append("| 序号 | 对阵 | 任九票面 | 本场覆盖率 |")
        lines.append("| --- | --- | --- | ---: |")
        for prediction in plan.choose9_plan.predictions:
            coverage = sum(
                prediction.probabilities.get(outcome, 0.0) for outcome in prediction.picks
            )
            lines.append(
                f"| {prediction.match.seq} | {prediction.match.home} vs {prediction.match.away} | "
                f"{prediction.pick_text} | {min(1.0, coverage):.1%} |"
            )
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
    if plan.line_portfolio:
        portfolio = plan.line_portfolio
        lines.append("## 平局线路配额")
        lines.append("")
        lines.append("| 序号 | 对阵 | 模型平局概率 | 目标注数 | 实际注数 | 覆盖比例 |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
        match_by_seq = {prediction.match.seq: prediction.match for prediction in plan.predictions}
        for coverage in portfolio.draw_coverages:
            match = match_by_seq[coverage.seq]
            lines.append(
                f"| {coverage.seq} | {match.home} vs {match.away} | {coverage.probability:.1%} | "
                f"{coverage.target_lines} | {coverage.actual_lines} | "
                f"{coverage.actual_lines / max(portfolio.line_count, 1):.1%} |"
            )
        lines.append("")
        lines.append("## 完整投注线路")
        lines.append("")
        lines.append("> 每行是一注完整14场结果，顺序对应第1至第14场。")
        lines.append("")
        for number, ticket_line in enumerate(portfolio.lines, start=1):
            lines.append(f"{number}. `{ticket_line.pick_text}`")
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


def _ticket_units(predictions: tuple[Prediction, ...]) -> int:
    units = 1
    for prediction in predictions:
        units *= max(1, len(prediction.picks))
    return units


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
        f"- 策略类型：{_strategy_label(prediction)}",
        f"- 置信度：{prediction.confidence:.1f}%",
    ]
    if prediction.budget_adjusted:
        warning = "，预算强制单选，不能视为模型胆材" if prediction.budget_forced_single else ""
        lines.append(f"- 预算票面：`{prediction.pick_text}`（{_pick_labels(prediction.picks)}）{warning}")
    for reason in prediction.reasons:
        lines.append(f"- {reason}")
    return lines


def _strategy_label(prediction: Prediction) -> str:
    if prediction.tactical_draw:
        return "战术单平（高风险，不是稳胆）"
    if len(prediction.analysis_picks) == 1:
        return "稳胆单选"
    return "覆盖型选择"


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
