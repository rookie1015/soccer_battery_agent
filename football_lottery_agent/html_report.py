from __future__ import annotations

from html import escape
from pathlib import Path

from .models import Prediction, TicketPlan
from .predictor import OUTCOME_LABELS
from .review import REVIEW_PLAY_CHOOSE9, ReviewReport


def write_analysis_html(plan: TicketPlan, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_analysis_html(plan), encoding="utf-8")
    return path


def write_review_html(report: ReviewReport, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_html(report), encoding="utf-8")
    return path


def render_analysis_html(plan: TicketPlan) -> str:
    singles = sum(1 for pred in plan.predictions if len(pred.analysis_picks) == 1)
    ticket_singles = sum(1 for pred in plan.predictions if len(pred.picks) == 1)
    ticket_units = _ticket_units(plan)
    avg_confidence = sum(pred.confidence for pred in plan.predictions) / len(plan.predictions)
    purchase_deadline = _purchase_deadline_text(plan)
    match_tabs = "\n".join(_analysis_match_tab(pred, plan) for pred in plan.predictions)
    cards = "\n".join(
        [
            _metric_card("14场", str(len(plan.predictions)), "本期比赛数量"),
            _metric_card("模型单选", str(singles), "预算压缩前"),
            _metric_card("票面单选", str(ticket_singles), "实际出票选择"),
            _metric_card("复式注数", str(ticket_units), "各场选择数相乘"),
            _metric_card("复式成本", f"{plan.total_cost_yuan}元", f"上限 {plan.max_ticket_cost_yuan}元"),
            _metric_card("平均置信", f"{avg_confidence:.1f}%", "仅代表模型置信"),
        ]
    )
    keep = "、".join(str(item) for item in plan.choose9_keep)
    drop = "、".join(str(item) for item in plan.choose9_drop)
    return _page(
        title=f"足球彩票分析报告 {escape(plan.issue.issue)}",
        body=f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Analysis Dashboard</p>
            <div class="hero-title">
              <h1>足球彩票分析报告：{escape(plan.issue.issue)}</h1>
              <span class="deadline">购彩截止时间：{escape(purchase_deadline)}</span>
            </div>
            <p class="subtle">胜平负、置信度和任九取舍集中展示。仅供信息分析和娱乐参考。</p>
          </div>
        </section>
        <div class="tab-panel active" id="outcome-panel">
          <section class="metrics">{cards}</section>
          {_rectangular_ticket_section(plan)}
          {_draw_hedge_section(plan)}
          {_choose9_ticket_section(plan)}
          <section class="split">
            <div class="panel">
              <h2>任九保留</h2>
              <p class="seq keep">{escape(keep)}</p>
            </div>
            <div class="panel">
              <h2>建议剔除</h2>
              <p class="seq drop">{escape(drop)}</p>
            </div>
          </section>
          <section class="panel match-tabs-panel">
            <div class="section-title match-tabs-title">
              <div>
                <h2>逐场胜平负分析</h2>
                <span>点击任意比赛查看结论、概率、置信度和判断依据，再点一次收起</span>
              </div>
              <span>3=主胜，1=平，0=客胜</span>
            </div>
            <div class="match-tabs">{match_tabs}</div>
          </section>
        </div>
        """,
    )


def _rectangular_ticket_section(plan: TicketPlan) -> str:
    units = _ticket_units(plan)
    selections = " · ".join(
        f"{prediction.match.seq}:{prediction.pick_text}" for prediction in plan.predictions
    )
    return f"""
    <section class="panel">
      <div class="section-title">
        <h2>正规复式出票</h2>
        <span>{units} 注 · {plan.total_cost_yuan}/{plan.max_ticket_cost_yuan} 元</span>
      </div>
      <p><strong>各场预算票面选择数相乘为 {units} 注，每注 2 元，实际成本 {plan.total_cost_yuan} 元。</strong></p>
      <p class="subtle">实际票面：{escape(selections)}</p>
      <p class="subtle">“模型建议”用于说明预算压缩前的判断范围；实际出票和计价只使用“预算票面”。</p>
    </section>
    """


def _choose9_ticket_section(plan: TicketPlan) -> str:
    choose9 = plan.choose9_plan
    if choose9 is None:
        return ""
    selections = " · ".join(
        f"{prediction.match.seq}:{prediction.pick_text}"
        for prediction in choose9.predictions
    )
    return f"""
    <section class="panel">
      <div class="section-title">
        <h2>任九独立优化</h2>
        <span>{choose9.line_count} 注 · {choose9.cost_yuan}/{choose9.allocated_budget_yuan} 元</span>
      </div>
      <p><strong>独立票面：{escape(selections)}</strong></p>
      <p class="subtle">理论联合覆盖率 {choose9.joint_coverage_probability:.2%}。任九与十四场共享基础概率，
      但场次选择、复式票面和预算压缩分别优化；若两种玩法同时购买，金额需要相加。</p>
    </section>
    """


def _ticket_units(plan: TicketPlan) -> int:
    units = 1
    for prediction in plan.predictions:
        units *= max(1, len(prediction.picks))
    return units


def _line_portfolio_section(plan: TicketPlan) -> str:
    portfolio = plan.line_portfolio
    if portfolio is None:
        return ""
    matches = {prediction.match.seq: prediction.match for prediction in plan.predictions}
    coverage_rows = "".join(
        f"<tr><td>{coverage.seq}</td><td>{escape(matches[coverage.seq].home)} vs "
        f"{escape(matches[coverage.seq].away)}</td><td>{coverage.probability:.1%}</td>"
        f"<td>{coverage.target_lines}</td><td>{coverage.actual_lines}</td>"
        f"<td>{coverage.actual_lines / max(portfolio.line_count, 1):.1%}</td></tr>"
        for coverage in portfolio.draw_coverages
    )
    line_items = "".join(
        f"<li><code>{escape(ticket_line.pick_text)}</code></li>"
        for ticket_line in portfolio.lines
    )
    return f"""
    <section class="panel">
      <div class="section-title">
        <h2>预算内多平线路组合</h2>
        <span>{portfolio.line_count} 注 · {portfolio.cost_yuan}/{portfolio.allocated_budget_yuan} 元</span>
      </div>
      <p class="subtle">模型保留的每一个平局都按概率获得线路配额；{portfolio.multi_draw_lines} 注包含至少两个候选平局，任意两场候选同时为平至少 {portfolio.minimum_draw_pair_lines} 注。</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>#</th><th>对阵</th><th>平局概率</th><th>目标注数</th><th>实际注数</th><th>覆盖比例</th></tr></thead>
          <tbody>{coverage_rows}</tbody>
        </table>
      </div>
      <details class="portfolio-lines prediction-fold">
        <summary><span class="match-name"><strong>查看全部 {portfolio.line_count} 条投注线路</strong></span></summary>
        <div><ol>{line_items}</ol></div>
      </details>
    </section>
    """


def _draw_hedge_section(plan: TicketPlan) -> str:
    hedge = plan.draw_hedge
    if hedge is None:
        return ""
    candidate = next(
        prediction for prediction in hedge.predictions if prediction.match.seq == hedge.candidate_seq
    )
    selections = " · ".join(
        f"{prediction.match.seq}:{prediction.pick_text}" for prediction in hedge.predictions
    )
    evidence = "".join(f"<li>{escape(item)}</li>" for item in hedge.evidence)
    return f"""
    <section class="panel">
      <div class="section-title">
        <h2>平局对冲分支</h2>
        <span>独立于主票，不是稳胆</span>
      </div>
      <p><strong>第 {hedge.candidate_seq} 场 {escape(candidate.match.home)} vs {escape(candidate.match.away)}：固定单选平（1）</strong></p>
      <p class="subtle">主票 {plan.main_cost_yuan} 元 + 对冲 {hedge.cost_yuan} 元（{hedge.line_count} 注）= 组合 {plan.total_cost_yuan}/{plan.max_ticket_cost_yuan} 元。</p>
      <p class="subtle">对冲票面：{escape(selections)}</p>
      <div class="analysis-reasons"><span class="detail-label">候选依据</span><ol>{evidence}</ol></div>
    </section>
    """


def render_review_html(report: ReviewReport) -> str:
    rows = "\n".join(_review_row(row) for row in report.rows)
    major_misses = _major_miss_section(report)
    total = report.total
    single_total = len(report.single_rows)
    keep_total = len(report.keep_rows)
    drop_total = len(report.drop_rows)
    play_label = "任九" if report.play_type == REVIEW_PLAY_CHOOSE9 else "14场胜平负"
    cards = "\n".join(
        [
            _rate_card(f"{play_label}命中", report.outcome_hits, total),
            _rate_card("单选命中", report.single_hits, single_total),
            _rate_card("预算漏判", report.budget_caused_misses, total),
            _rate_card("预算删平漏判", report.budget_draw_caused_misses, total),
            _rate_card("比分 Top1", report.top_score_hits, report.score_total),
            _rate_card("比分 Top3", report.score_top3_hits, report.score_total),
            _rate_card("任九保留", report.keep_hits, keep_total),
            _rate_card("剔除有效", report.effective_drops, drop_total),
        ]
    )
    hedge_review = ""
    if report.play_type != REVIEW_PLAY_CHOOSE9 and report.plan.draw_hedge:
        candidate_mark = (
            "未结算"
            if report.draw_hedge_candidate_hit is None
            else "命中"
            if report.draw_hedge_candidate_hit
            else "未中"
        )
        hedge_review = f"""
        <section class="panel">
          <div class="section-title"><h2>平局对冲复盘</h2><span>独立分支</span></div>
          <p><strong>候选单平：{candidate_mark}</strong></p>
          <p class="subtle">分支覆盖 {report.draw_hedge_outcome_hits}/{report.total}；整支组合{'命中' if report.draw_hedge_full_coverage else '未中'}。</p>
        </section>
        """
    portfolio_review = ""
    if report.play_type != REVIEW_PLAY_CHOOSE9 and report.plan.line_portfolio:
        portfolio_review = f"""
        <section class="panel">
          <div class="section-title"><h2>独立线路复盘</h2><span>{report.plan.line_portfolio.line_count} 注</span></div>
          <p><strong>最佳一注命中 {report.line_portfolio_best_hits}/{report.total}；整注{'命中' if report.line_portfolio_hit else '未中'}。</strong></p>
          <p class="subtle">本期实际出现 {report.actual_draw_total} 场平局，有 {report.actual_draw_combination_lines} 注同时覆盖全部实际平局。</p>
        </section>
        """
    return _page(
        title=f"足球彩票复盘报告 {escape(report.plan.issue.issue)}",
        body=f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Review Dashboard</p>
            <h1>足球彩票复盘报告：{escape(report.plan.issue.issue)} · {play_label}</h1>
            <p class="subtle">复盘用于校验模型与记录决策质量，不代表后续场次必然延续同样表现。</p>
          </div>
        </section>
        <section class="metrics rates">{cards}</section>
        {portfolio_review}
        {hedge_review}
        {major_misses}
        <section class="panel">
          <div class="section-title">
            <h2>逐场复盘</h2>
            <span>命中、比分、任九取舍一屏扫完</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>对阵</th>
                  <th>最终比分</th>
                  <th>彩果</th>
                  <th>推荐</th>
                  <th>胜平负</th>
                  <th>比分预测</th>
                  <th>任九</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </section>
        """,
    )


def _analysis_row(prediction: Prediction, plan: TicketPlan) -> str:
    match = prediction.match
    keep = match.seq in set(plan.choose9_keep)
    return f"""
    <tr>
      <td class="seqno">{match.seq}</td>
      <td>
        <strong>{escape(match.home)} vs {escape(match.away)}</strong>
        <span class="meta">{escape(match.league)} · {escape(match.kickoff.strftime("%m-%d %H:%M"))}</span>
      </td>
      <td>{_pick_badge(prediction)}</td>
      <td>{_probability_bars(prediction)}</td>
      <td><strong>{prediction.confidence:.1f}%</strong></td>
      <td>{_bucket_badge("保留" if keep else "剔除", keep)}</td>
    </tr>
    """


def _analysis_match_tab(prediction: Prediction, plan: TicketPlan) -> str:
    match = prediction.match
    keep = match.seq in set(plan.choose9_keep)
    pick_labels = " / ".join(OUTCOME_LABELS[pick] for pick in prediction.analysis_picks)
    budget_html = ""
    if prediction.budget_adjusted:
        budget_labels = " / ".join(OUTCOME_LABELS[pick] for pick in prediction.picks)
        warning = " · 预算强制单选，不等于模型胆材" if prediction.budget_forced_single else ""
        budget_html = (
            f'<div class="analysis-result"><span>预算票面</span>'
            f'<strong>{escape(budget_labels)}（{escape(prediction.pick_text)}）</strong>'
            f'<small>整票成本压缩{escape(warning)}</small></div>'
        )
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in prediction.reasons)
    if not reasons:
        reasons = "<li>当前没有可展示的结论依据。</li>"
    strategy_label = (
        "战术单平（高风险，不是稳胆）"
        if prediction.tactical_draw
        else "稳胆单选"
        if len(prediction.analysis_picks) == 1
        else "覆盖型选择"
    )
    return f"""
    <details class="match-tab">
      <summary>
        <span class="match-seq">{match.seq}</span>
        <span class="match-name">
          <strong>{escape(match.home)} vs {escape(match.away)}</strong>
          <small>{escape(match.league)} · {escape(match.kickoff.strftime("%m-%d %H:%M"))}</small>
        </span>
        <span class="match-tab-action"><i>查看分析</i><b>收起分析</b></span>
      </summary>
      <div class="match-tab-content">
        <div class="analysis-result">
          <span>模型建议</span>
          <strong>{escape(pick_labels)}（{escape(prediction.analysis_pick_text)}）</strong>
          <small>{escape(strategy_label)} · 风险：{escape(prediction.risk)} · 任九：{"保留" if keep else "剔除"}</small>
        </div>
        {budget_html}
        <div class="analysis-probabilities">
          <span class="detail-label">胜平负概率</span>
          {_probability_bars(prediction)}
        </div>
        <div class="analysis-confidence">
          <span class="detail-label">置信度</span>
          <strong>{prediction.confidence:.1f}%</strong>
          <div class="confidence-meter"><i style="width:{prediction.confidence:.1f}%"></i></div>
          <small>置信度代表模型对最高概率结果的判断强度，不等于命中保证。</small>
        </div>
        <div class="analysis-reasons">
          <span class="detail-label">得出结论的理由</span>
          <ol>{reasons}</ol>
        </div>
      </div>
    </details>
    """


def _score_prediction_row(prediction: Prediction) -> str:
    match = prediction.match
    primary = prediction.scorelines[0] if prediction.scorelines else None
    alternatives = prediction.scorelines[1:] if len(prediction.scorelines) > 1 else ()
    primary_html = (
        f'<span class="primary-score">{escape(primary.text)}</span>'
        f'<span class="meta">概率 {primary.probability:.0%}</span>'
        if primary
        else '<span class="meta">暂无预测</span>'
    )
    alternative_html = "".join(
        f'<span class="score-tag">{escape(item.text)} <b>{item.probability:.0%}</b></span>'
        for item in alternatives
    ) or '<span class="meta">暂无备选</span>'
    return f"""
    <tr>
      <td class="seqno">{match.seq}</td>
      <td>
        <strong>{escape(match.home)} vs {escape(match.away)}</strong>
        <span class="meta">{escape(match.league)} · {escape(match.kickoff.strftime("%m-%d %H:%M"))}</span>
      </td>
      <td>{primary_html}</td>
      <td>{alternative_html}</td>
      <td>{_pick_badge(prediction)}</td>
      <td>{_risk_badge(prediction.risk)}</td>
    </tr>
    """


def _review_row(row) -> str:
    prediction = row.prediction
    match = prediction.match
    outcome_class = "hit" if row.outcome_hit else "miss"
    return f"""
    <tr>
      <td class="seqno">{match.seq}</td>
      <td>
        <strong>{escape(match.home)} vs {escape(match.away)}</strong>
        <span class="meta">{escape(match.league)}</span>
      </td>
      <td><span class="score-final">{escape(row.result.score_text)}</span></td>
      <td><span class="pick">{escape(row.result.outcome_label)}</span></td>
      <td>{_pick_badge(prediction)}</td>
      <td><span class="badge {outcome_class}">{"命中" if row.outcome_hit else "未中"}</span></td>
      <td>{_scoreline_tags(prediction)}</td>
      <td>{_bucket_badge(row.bucket.replace("任九", ""), row.bucket == "任九保留")}</td>
    </tr>
    """


def _major_miss_section(report: ReviewReport) -> str:
    rows = report.major_misses
    if not rows:
        return """
        <section class="panel callout ok">
          <div>
            <h2>重大意外</h2>
            <p>高置信、低风险或单选场未出现明显失手。</p>
          </div>
        </section>
        """
    cards = "\n".join(_major_miss_card(row) for row in rows)
    return f"""
    <section class="panel callout danger">
      <div class="section-title">
        <h2>重大意外</h2>
        <span>单选、低风险或高置信未命中的场次</span>
      </div>
      <div class="upset-grid">{cards}</div>
    </section>
    """


def _major_miss_card(row) -> str:
    prediction = row.prediction
    match = prediction.match
    top = max(prediction.probabilities.items(), key=lambda item: item[1])
    return f"""
    <article class="upset-card">
      <strong>{match.seq}. {escape(match.home)} vs {escape(match.away)}</strong>
      <span>推荐 <b>{escape(prediction.pick_text)}</b>，实际 <b>{escape(row.result.score_text)}（{escape(row.result.outcome_label)}）</b></span>
      <small>赛前最高概率：{escape(OUTCOME_LABELS[top[0]])} {top[1]:.0%} · 置信度 {prediction.confidence:.1f}% · 风险 {escape(prediction.risk)}</small>
    </article>
    """


def _metric_card(label: str, value: str, note: str) -> str:
    return f"""
    <article class="metric">
      <span>{escape(label)}</span>
      <strong>{escape(value)}</strong>
      <small>{escape(note)}</small>
    </article>
    """


def _purchase_deadline_text(plan: TicketPlan) -> str:
    return str(plan.issue.metadata.get("purchase_deadline") or "官方截止时间暂未获取")


def _rate_card(label: str, count: int, total: int) -> str:
    rate = 0 if total <= 0 else count / total
    value = f"{count}/{total}" if total > 0 else "N/A"
    rate_text = f"{rate:.0%}" if total > 0 else "仅彩果"
    return f"""
    <article class="metric">
      <span>{escape(label)}</span>
      <strong>{escape(value)}</strong>
      <div class="meter"><i style="width:{rate:.0%}"></i></div>
      <small>{escape(rate_text)}</small>
    </article>
    """


def _pick_badge(prediction: Prediction) -> str:
    label = " / ".join(OUTCOME_LABELS[pick] for pick in prediction.picks)
    return f"<span class=\"pick\">{escape(prediction.pick_text)}</span><span class=\"meta\">{escape(label)}</span>"


def _scoreline_tags(prediction: Prediction) -> str:
    return "".join(
        f"<span class=\"score-tag\">{escape(item.text)} <b>{item.probability:.0%}</b></span>"
        for item in prediction.scorelines
    )


def _probability_bars(prediction: Prediction) -> str:
    labels = (("3", "主"), ("1", "平"), ("0", "客"))
    rows = []
    for key, label in labels:
        value = prediction.probabilities[key]
        rows.append(
            f"<div class=\"prob\"><span>{label}</span><i style=\"width:{value:.0%}\"></i><b>{value:.0%}</b></div>"
        )
    return "".join(rows)


def _risk_badge(risk: str) -> str:
    css = {"低": "low", "中": "mid", "高": "high"}.get(risk, "mid")
    return f"<span class=\"badge {css}\">{escape(risk)}</span>"


def _bucket_badge(label: str, positive: bool) -> str:
    css = "keep" if positive else "drop"
    return f"<span class=\"badge {css}\">{escape(label)}</span>"


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #18202f;
      --muted: #667085;
      --line: #dbe1ea;
      --green: #16845b;
      --red: #b42318;
      --amber: #b76e00;
      --blue: #2364aa;
      --cyan: #087f8c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }}
    main {{
      width: min(1800px, calc(100% - 20px));
      margin: 0 auto;
      padding: 14px 0 24px;
    }}
    .hero {{
      background: #101828;
      color: white;
      border-radius: 8px;
      padding: 16px 18px;
      margin-bottom: 10px;
      border: 1px solid #101828;
    }}
    .eyebrow {{
      margin: 0 0 6px;
      color: #8bd3dd;
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 700;
    }}
    h1, h2, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: 6px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin-bottom: 0; font-size: 17px; letter-spacing: 0; }}
    .subtle, .meta, small {{ color: var(--muted); }}
    .hero-title {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
    }}
    .deadline {{
      flex: 0 0 auto;
      color: #d0d5dd;
      font-size: 14px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .hero .subtle {{ color: #d0d5dd; margin-bottom: 0; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 10px;
    }}
    .rates {{ grid-template-columns: repeat(6, minmax(0, 1fr)); }}
    .metric, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 10px 12px; min-height: 78px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; margin: 4px 0; font-size: 23px; letter-spacing: 0; }}
    .metric small {{ display: block; }}
    .meter {{
      height: 8px;
      background: #edf1f7;
      border-radius: 999px;
      overflow: hidden;
      margin: 10px 0 6px;
    }}
    .meter i {{ display: block; height: 100%; background: var(--green); }}
    .split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-bottom: 10px;
    }}
    .panel {{ padding: 12px; }}
    .prediction-fold {{ padding: 0; overflow: hidden; }}
    .prediction-fold summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 11px 12px;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }}
    .prediction-fold summary::-webkit-details-marker {{ display: none; }}
    .prediction-fold summary::before {{
      content: "＋";
      color: var(--blue);
      font-size: 20px;
      font-weight: 700;
    }}
    .prediction-fold[open] summary::before {{ content: "－"; }}
    .prediction-fold[open] summary {{ border-bottom: 1px solid var(--line); }}
    .prediction-fold .fold-title {{ margin-right: auto; font-size: 17px; font-weight: 700; }}
    .prediction-fold .fold-hint {{ color: var(--muted); font-size: 12px; }}
    .prediction-fold .table-wrap {{ padding: 0 10px 10px; }}
    .match-tabs-panel {{ padding: 0; overflow: hidden; }}
    .match-tabs-title {{ padding: 14px 16px; margin: 0; background: #f8fafc; border-bottom: 1px solid var(--line); }}
    .match-tabs-title > div > span {{ display: block; margin-top: 3px; }}
    .match-tabs {{ display: grid; gap: 8px; padding: 10px; }}
    .match-tab {{ border: 1px solid var(--line); border-radius: 8px; background: #fff; overflow: hidden; }}
    .match-tab[open] {{ border-color: #a9c5e8; box-shadow: 0 3px 12px rgba(35, 100, 170, 0.08); }}
    .match-tab summary {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 64px;
      padding: 10px 12px;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }}
    .match-tab summary::-webkit-details-marker {{ display: none; }}
    .match-tab summary:focus-visible {{ outline: 2px solid var(--blue); outline-offset: -2px; }}
    .match-tab[open] summary {{ background: #f7faff; border-bottom: 1px solid var(--line); }}
    .match-seq {{
      display: grid;
      place-items: center;
      flex: 0 0 34px;
      width: 34px;
      height: 34px;
      border-radius: 7px;
      color: var(--blue);
      background: #e8f0fb;
      font-weight: 800;
    }}
    .match-name {{ min-width: 0; flex: 1; }}
    .match-name strong, .match-name small {{ display: block; }}
    .match-name strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .match-name small {{ margin-top: 2px; color: var(--muted); }}
    .match-tab-action {{ color: var(--blue); font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .match-tab-action::after {{ content: "＋"; display: inline-block; margin-left: 7px; font-size: 18px; vertical-align: -1px; }}
    .match-tab-action b {{ display: none; }}
    .match-tab-action i {{ font-style: normal; }}
    .match-tab[open] .match-tab-action::after {{ content: "－"; }}
    .match-tab[open] .match-tab-action i {{ display: none; }}
    .match-tab[open] .match-tab-action b {{ display: inline; }}
    .match-tab-content {{
      display: grid;
      grid-template-columns: minmax(180px, .8fr) minmax(250px, 1fr) minmax(180px, .8fr) minmax(300px, 1.6fr);
      gap: 10px;
      padding: 12px;
    }}
    .match-tab-content > div {{ padding: 12px; border-radius: 7px; background: #f8fafc; }}
    .detail-label {{ display: block; margin-bottom: 8px; color: #475467; font-size: 12px; font-weight: 700; }}
    .analysis-result strong {{ display: block; margin: 6px 0; color: var(--blue); font-size: 18px; }}
    .analysis-result > span, .analysis-result small {{ display: block; color: var(--muted); }}
    .analysis-confidence > strong {{ display: block; color: var(--blue); font-size: 24px; line-height: 1.2; }}
    .confidence-meter {{ height: 7px; margin: 9px 0; border-radius: 999px; background: #e4eaf2; overflow: hidden; }}
    .confidence-meter i {{ display: block; height: 100%; border-radius: inherit; background: var(--blue); }}
    .analysis-reasons ol {{ margin: 0; padding-left: 20px; color: #344054; }}
    .analysis-reasons li + li {{ margin-top: 6px; }}
    .tabs {{
      display: flex;
      gap: 8px;
      margin: 0 0 10px;
      border-bottom: 1px solid var(--line);
    }}
    .tab-button {{
      appearance: none;
      border: 0;
      border-bottom: 3px solid transparent;
      background: transparent;
      color: var(--muted);
      padding: 8px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .tab-button:hover {{ color: var(--blue); }}
    .tab-button.active {{ color: var(--blue); border-bottom-color: var(--blue); }}
    .tab-button:focus-visible {{ outline: 2px solid var(--blue); outline-offset: 2px; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .seq {{ margin: 6px 0 0; font-size: 18px; font-weight: 700; }}
    .seq.keep {{ color: var(--green); }}
    .seq.drop {{ color: var(--red); }}
    .section-title {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .section-title span {{ color: var(--muted); font-size: 12px; }}
    .callout {{ margin-bottom: 10px; }}
    .callout.ok {{ border-color: #b7e3cf; background: #f3fbf7; }}
    .callout.danger {{ border-color: #ffd0c7; background: #fff7f5; }}
    .callout p {{ margin-bottom: 0; color: var(--muted); }}
    .upset-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .upset-card {{
      padding: 12px;
      border: 1px solid #ffd0c7;
      border-radius: 8px;
      background: #ffffff;
    }}
    .upset-card strong, .upset-card span, .upset-card small {{ display: block; }}
    .upset-card span {{ margin: 6px 0; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{
      padding: 6px 7px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      color: #475467;
      font-size: 12px;
      background: #f8fafc;
      position: sticky;
      top: 0;
    }}
    .seqno {{ width: 36px; font-weight: 700; color: var(--blue); }}
    .meta {{ display: block; margin-top: 1px; font-size: 12px; }}
    .pick {{
      display: inline-block;
      min-width: 48px;
      padding: 3px 7px;
      border-radius: 6px;
      background: #e8f0fb;
      color: var(--blue);
      font-weight: 700;
      text-align: center;
    }}
    .score-tag {{
      display: inline-block;
      margin: 2px 4px 2px 0;
      padding: 3px 6px;
      border-radius: 6px;
      border: 1px solid #c7e6ea;
      color: var(--cyan);
      background: #f0fbfc;
      white-space: nowrap;
    }}
    .score-final {{
      display: block;
      font-size: 18px;
      font-weight: 800;
    }}
    .primary-score {{
      display: block;
      color: var(--cyan);
      font-size: 24px;
      font-weight: 800;
      line-height: 1.2;
    }}
    .score-table {{ min-width: 820px; }}
    .prob {{
      display: grid;
      grid-template-columns: 22px 88px 42px;
      align-items: center;
      gap: 5px;
      margin: 2px 0;
      font-size: 12px;
    }}
    .prob i {{
      display: block;
      height: 6px;
      border-radius: 999px;
      background: var(--blue);
    }}
    .prob b {{ font-weight: 700; }}
    .badge {{
      display: inline-block;
      padding: 3px 7px;
      border-radius: 6px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .badge.low, .badge.keep, .badge.hit {{ color: var(--green); background: #e9f8f1; }}
    .badge.mid {{ color: var(--amber); background: #fff5df; }}
    .badge.high, .badge.drop, .badge.miss {{ color: var(--red); background: #fff0ed; }}
    @media (max-width: 900px) {{
      main {{ width: min(100% - 20px, 1800px); padding-top: 12px; }}
      h1 {{ font-size: 22px; }}
      .metrics, .rates, .split {{ grid-template-columns: 1fr 1fr; }}
      .upset-grid {{ grid-template-columns: 1fr; }}
      .hero, .panel, .metric {{ border-radius: 6px; }}
      .match-tab-content {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 560px) {{
      .metrics, .rates, .split {{ grid-template-columns: 1fr; }}
      .hero-title {{ display: block; }}
      .deadline {{ display: block; margin: -2px 0 6px; white-space: normal; }}
      .section-title {{ display: block; }}
      .match-tabs-title > span {{ display: block; margin-top: 6px; }}
      .match-tab-content {{ grid-template-columns: 1fr; }}
      .match-tab summary {{ gap: 9px; }}
      .match-tab-action i, .match-tab-action b {{ font-size: 0; }}
      .match-tab-action i::before {{ content: "查看"; font-size: 12px; }}
      .match-tab-action b::before {{ content: "收起"; font-size: 12px; }}
    }}
  </style>
</head>
<body>
  <main>{body}</main>
  <script>
    document.querySelectorAll(".tab-button").forEach((button) => {{
      button.addEventListener("click", () => {{
        document.querySelectorAll(".tab-button").forEach((item) => {{
          const selected = item === button;
          item.classList.toggle("active", selected);
          item.setAttribute("aria-selected", String(selected));
        }});
        document.querySelectorAll(".tab-panel").forEach((panel) => {{
          const selected = panel.id === button.dataset.tab;
          panel.classList.toggle("active", selected);
          panel.hidden = !selected;
        }});
      }});
    }});
  </script>
</body>
</html>
"""
