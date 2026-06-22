from __future__ import annotations

from html import escape
from pathlib import Path

from .models import Prediction, TicketPlan
from .predictor import OUTCOME_LABELS
from .review import ReviewReport


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
    low_risk = sum(1 for pred in plan.predictions if pred.risk == "低")
    singles = sum(1 for pred in plan.predictions if len(pred.picks) == 1)
    avg_confidence = sum(pred.confidence for pred in plan.predictions) / len(plan.predictions)
    outcome_rows = "\n".join(_analysis_row(pred, plan) for pred in plan.predictions)
    score_rows = "\n".join(_score_prediction_row(pred) for pred in plan.predictions)
    cards = "\n".join(
        [
            _metric_card("14场", str(len(plan.predictions)), "本期比赛数量"),
            _metric_card("单选", str(singles), "模型倾向最明确"),
            _metric_card("低风险", str(low_risk), "适合作胆材候选"),
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
            <h1>足球彩票分析报告：{escape(plan.issue.issue)}</h1>
            <p class="subtle">胜平负、比分倾向、任九取舍集中展示。仅供信息分析和娱乐参考。</p>
          </div>
        </section>
        <div class="tabs" role="tablist" aria-label="预测类型">
          <button class="tab-button active" id="outcome-tab" role="tab" aria-selected="true" aria-controls="outcome-panel" data-tab="outcome-panel">胜平负预测</button>
          <button class="tab-button" id="score-tab" role="tab" aria-selected="false" aria-controls="score-panel" data-tab="score-panel">单场比分预测</button>
        </div>
        <div class="tab-panel active" id="outcome-panel" role="tabpanel" aria-labelledby="outcome-tab">
          <section class="metrics">{cards}</section>
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
          <details class="panel prediction-fold">
            <summary>
              <span class="fold-title">展开本期 {len(plan.predictions)} 场胜平负预测</span>
              <span class="fold-hint">点击展开 · 3=主胜，1=平，0=客胜</span>
            </summary>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>对阵</th>
                    <th>推荐</th>
                    <th>概率</th>
                    <th>风险</th>
                    <th>任九</th>
                  </tr>
                </thead>
                <tbody>{outcome_rows}</tbody>
              </table>
            </div>
          </details>
        </div>
        <section class="panel tab-panel" id="score-panel" role="tabpanel" aria-labelledby="score-tab" hidden>
          <div class="section-title">
            <h2>单场比分预测</h2>
            <span>首选比分 + 两个备选比分，百分比为模型估算概率</span>
          </div>
          <div class="table-wrap">
            <table class="score-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>对阵</th>
                  <th>首选比分</th>
                  <th>备选比分</th>
                  <th>胜平负倾向</th>
                  <th>风险</th>
                </tr>
              </thead>
              <tbody>{score_rows}</tbody>
            </table>
          </div>
        </section>
        """,
    )


def render_review_html(report: ReviewReport) -> str:
    rows = "\n".join(_review_row(row) for row in report.rows)
    major_misses = _major_miss_section(report)
    total = report.total
    single_total = len(report.single_rows)
    keep_total = len(report.keep_rows)
    drop_total = len(report.drop_rows)
    cards = "\n".join(
        [
            _rate_card("胜平负命中", report.outcome_hits, total),
            _rate_card("单选命中", report.single_hits, single_total),
            _rate_card("比分 Top1", report.top_score_hits, total),
            _rate_card("比分 Top3", report.score_top3_hits, total),
            _rate_card("任九保留", report.keep_hits, keep_total),
            _rate_card("剔除有效", report.effective_drops, drop_total),
        ]
    )
    return _page(
        title=f"足球彩票复盘报告 {escape(report.plan.issue.issue)}",
        body=f"""
        <section class="hero">
          <div>
            <p class="eyebrow">Review Dashboard</p>
            <h1>足球彩票复盘报告：{escape(report.plan.issue.issue)}</h1>
            <p class="subtle">复盘用于校验模型与记录决策质量，不代表后续场次必然延续同样表现。</p>
          </div>
        </section>
        <section class="metrics rates">{cards}</section>
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
                  <th>赛果</th>
                  <th>推荐</th>
                  <th>胜平负</th>
                  <th>比分倾向</th>
                  <th>比分</th>
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
      <td>{_risk_badge(prediction.risk)}</td>
      <td>{_bucket_badge("保留" if keep else "剔除", keep)}</td>
    </tr>
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
    score_class = "hit" if row.score_top3_hit else "miss"
    score_mark = "Top1" if row.top_score_hit else ("Top3" if row.score_top3_hit else "未中")
    return f"""
    <tr>
      <td class="seqno">{match.seq}</td>
      <td>
        <strong>{escape(match.home)} vs {escape(match.away)}</strong>
        <span class="meta">{escape(match.league)}</span>
      </td>
      <td><span class="score-final">{escape(row.result.score_text)}</span><span class="meta">{escape(OUTCOME_LABELS[row.result.outcome])}</span></td>
      <td>{_pick_badge(prediction)}</td>
      <td><span class="badge {outcome_class}">{"命中" if row.outcome_hit else "未中"}</span></td>
      <td>{_scoreline_tags(prediction)}</td>
      <td><span class="badge {score_class}">{escape(score_mark)}</span></td>
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
      <span>推荐 <b>{escape(prediction.pick_text)}</b>，实际 <b>{escape(row.result.score_text)}（{escape(OUTCOME_LABELS[row.result.outcome])}）</b></span>
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


def _rate_card(label: str, count: int, total: int) -> str:
    rate = 0 if total <= 0 else count / total
    return f"""
    <article class="metric">
      <span>{escape(label)}</span>
      <strong>{count}/{total}</strong>
      <div class="meter"><i style="width:{rate:.0%}"></i></div>
      <small>{rate:.0%}</small>
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
      width: min(1320px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }}
    .hero {{
      background: #101828;
      color: white;
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 16px;
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
    h1 {{ margin-bottom: 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin-bottom: 0; font-size: 18px; letter-spacing: 0; }}
    .subtle, .meta, small {{ color: var(--muted); }}
    .hero .subtle {{ color: #d0d5dd; margin-bottom: 0; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .rates {{ grid-template-columns: repeat(6, minmax(0, 1fr)); }}
    .metric, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 14px; min-height: 106px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; margin: 6px 0; font-size: 26px; letter-spacing: 0; }}
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
      gap: 12px;
      margin-bottom: 16px;
    }}
    .panel {{ padding: 16px; }}
    .prediction-fold {{ padding: 0; overflow: hidden; }}
    .prediction-fold summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px;
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
    .prediction-fold .fold-title {{ margin-right: auto; font-size: 18px; font-weight: 700; }}
    .prediction-fold .fold-hint {{ color: var(--muted); font-size: 12px; }}
    .prediction-fold .table-wrap {{ padding: 0 16px 16px; }}
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
      padding: 10px 16px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .tab-button:hover {{ color: var(--blue); }}
    .tab-button.active {{ color: var(--blue); border-bottom-color: var(--blue); }}
    .tab-button:focus-visible {{ outline: 2px solid var(--blue); outline-offset: 2px; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .seq {{ margin: 10px 0 0; font-size: 20px; font-weight: 700; }}
    .seq.keep {{ color: var(--green); }}
    .seq.drop {{ color: var(--red); }}
    .section-title {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .section-title span {{ color: var(--muted); font-size: 12px; }}
    .callout {{ margin-bottom: 16px; }}
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
      padding: 10px 8px;
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
    .meta {{ display: block; margin-top: 2px; font-size: 12px; }}
    .pick {{
      display: inline-block;
      min-width: 48px;
      padding: 4px 8px;
      border-radius: 6px;
      background: #e8f0fb;
      color: var(--blue);
      font-weight: 700;
      text-align: center;
    }}
    .score-tag {{
      display: inline-block;
      margin: 2px 4px 2px 0;
      padding: 4px 7px;
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
      gap: 6px;
      margin: 3px 0;
      font-size: 12px;
    }}
    .prob i {{
      display: block;
      height: 7px;
      border-radius: 999px;
      background: var(--blue);
    }}
    .prob b {{ font-weight: 700; }}
    .badge {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 6px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .badge.low, .badge.keep, .badge.hit {{ color: var(--green); background: #e9f8f1; }}
    .badge.mid {{ color: var(--amber); background: #fff5df; }}
    .badge.high, .badge.drop, .badge.miss {{ color: var(--red); background: #fff0ed; }}
    @media (max-width: 900px) {{
      main {{ width: min(100% - 20px, 1320px); padding-top: 12px; }}
      h1 {{ font-size: 22px; }}
      .metrics, .rates, .split {{ grid-template-columns: 1fr 1fr; }}
      .upset-grid {{ grid-template-columns: 1fr; }}
      .hero, .panel, .metric {{ border-radius: 6px; }}
    }}
    @media (max-width: 560px) {{
      .metrics, .rates, .split {{ grid-template-columns: 1fr; }}
      .section-title {{ display: block; }}
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
