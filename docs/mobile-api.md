# Mobile API

The iPhone app should call the existing HTTP server and consume JSON rather than parsing generated HTML.

## Generate Analysis

`POST /api/analysis`

Request:

```json
{
  "issue": "26090",
  "max_ticket_cost_yuan": 500,
  "no_history": false
}
```

Response includes the existing report links plus an app-ready `report` object:

```json
{
  "ok": true,
  "message": "26090 分析报告已生成。",
  "report": {
    "issue": "26090",
    "purchase_deadline": "2026-07-04 23:00:00",
    "purchase_deadline_source": "中国体彩网官方",
    "sale_begin_time": "2026-07-04 18:00:00",
    "analysis_mode": "full",
    "analysis_mode_message": "已完成完整分析，增强样本固定为最近 20 场。",
    "metrics": {
      "match_count": 14,
      "single_count": 4,
      "tactical_draw_count": 1,
      "average_confidence": 47.2
    },
    "choose9_keep": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "choose9_drop": [10, 11, 12, 13, 14],
    "predictions": [
      {
        "seq": 1,
        "league": "世界杯",
        "kickoff": "2026-07-04T23:00+08:00",
        "kickoff_display": "07-04 23:00",
        "home": "主队",
        "away": "客队",
        "pick_text": "3/1",
        "pick_labels": ["主胜", "平"],
        "picks": ["3", "1"],
        "tactical_draw": false,
        "confidence": 48.6,
        "probabilities": {
          "home": 48.6,
          "draw": 28.1,
          "away": 23.3
        },
        "market_probabilities": {
          "home": 49.8,
          "draw": 27.4,
          "away": 22.8
        },
        "blend_weights": {
          "market": 0.61,
          "information": 0.22,
          "mathematical": 0.17
        },
        "reasons": ["主胜优势较明确，可作为候选胆材。"]
      }
    ]
  },
  "html_url": "/reports/26090_report.html",
  "markdown_url": "/reports/26090_report.md",
  "history_url": "/reports/history/analysis.html"
}
```

分析接口固定优先执行完整分析，并固定使用最近 20 场增强样本。客户端传入旧的模式或样本参数不会改变这一行为；关键资料源出现大范围网络请求失败时，`analysis_mode` 会返回 `simple_fallback`。

新分析的 `line_portfolio` 为 `null`。14 场实际出票使用 `predictions[].picks` 作为各场预算票面，注数等于各场 `picks` 数量的乘积，总成本等于注数乘以 2 元；`predictions[].analysis_picks` 仅保留预算压缩前的模型判断范围，不参与出票计价。`budget.total_cost_yuan` 必须与该复式乘积一致且不超过 `budget.limit_yuan`。

`choose9` 是独立任九方案：`selections` 只包含联合优化后入选的 9 场及各自票面，`line_count` 等于这 9 场选择数的乘积，`cost_yuan = line_count * 2`。任九与十四场共享基础概率，但使用独立的场次、票面和预算优化；`budget_scope` 为 `separate`，表示两种玩法的成本不合并，若同时购买应将两项成本相加。旧版客户端仍可使用兼容字段 `choose9_keep` 与 `choose9_drop`。

`tactical_draw` 为 `true` 时表示本场是每期最多一场的高风险战术单平，不是稳胆。`market_probabilities` 是去水后的市场锚点，`blend_weights` 记录本场实际使用的市场、有效信息和数学模型权重。

## Single Prediction

`POST /api/single-prediction`

This endpoint already returns app-ready JSON and can be used directly by the iPhone app.

## History

`GET /api/history`

Response:

```json
{
  "ok": true,
  "entries": [
    {
      "id": "20260703200000-26090-analysis",
      "kind": "analysis",
      "issue": "26090",
      "title": "分析报告：26090",
      "created_at": "2026-07-03T20:00:00",
      "html": "items/20260703200000-26090-analysis.html",
      "markdown": "items/20260703200000-26090-analysis.md",
      "html_url": "/reports/history/items/20260703200000-26090-analysis.html",
      "markdown_url": "/reports/history/items/20260703200000-26090-analysis.md"
    }
  ]
}
```
