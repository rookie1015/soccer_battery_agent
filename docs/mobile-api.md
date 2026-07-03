# Mobile API

The iPhone app should call the existing HTTP server and consume JSON rather than parsing generated HTML.

## Generate Analysis

`POST /api/analysis`

Request:

```json
{
  "issue": "26090",
  "strength_model": true,
  "strength_xg_matches": 8,
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
    "metrics": {
      "match_count": 14,
      "single_count": 4,
      "low_risk_count": 3,
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
        "confidence": 48.6,
        "risk": "中",
        "probabilities": {
          "home": 48.6,
          "draw": 28.1,
          "away": 23.3
        },
        "scorelines": [
          {"score": "1-0", "probability": 12.4}
        ],
        "reasons": ["主胜优势较明确，可作为候选胆材。"]
      }
    ]
  },
  "html_url": "/reports/26090_report.html",
  "markdown_url": "/reports/26090_report.md",
  "history_url": "/reports/history/analysis.html"
}
```

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
