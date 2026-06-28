from __future__ import annotations

import json
import re
import shutil
import tempfile
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .collectors import collect_issue
from .history import archive_report
from .html_report import write_analysis_html, write_review_html
from .loader import load_issue
from .models import Match, Odds, Signals
from .notifier import NotifyError, send_report, send_text
from .predictor import OUTCOME_LABELS, predict_match
from .report import write_report
from .review import build_review, fetch_results_with_fallbacks, load_results, write_review_report
from .strategy import build_ticket_plan


def run_ui(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), _handler(Path.cwd()))
    url = f"http://{host}:{port}/"
    print(f"Football Lottery Agent UI: {url}")
    print("Close this window to stop the local UI.")
    if open_browser:
        webbrowser.open(url)
    server.serve_forever()


def render_ui() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>足球彩票助手控制台</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #18202f;
      --muted: #667085;
      --line: #dbe1ea;
      --green: #16845b;
      --blue: #2364aa;
      --red: #b42318;
      --amber: #b76e00;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }
    main {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }
    .hero {
      padding: 24px;
      margin-bottom: 16px;
      border-radius: 8px;
      background: #101828;
      color: white;
    }
    .eyebrow {
      margin: 0 0 6px;
      color: #8bd3dd;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    h1, h2, p { margin-top: 0; }
    h1 { margin-bottom: 8px; font-size: 28px; letter-spacing: 0; }
    h2 { margin-bottom: 12px; font-size: 18px; letter-spacing: 0; }
    .hero p { margin-bottom: 0; color: #d0d5dd; }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    .panel.wide { grid-column: 1 / -1; }
    label {
      display: block;
      margin: 12px 0 6px;
      color: #475467;
      font-weight: 700;
      font-size: 12px;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }
    input[type="password"] { font-family: Consolas, monospace; }
    textarea {
      min-height: 220px;
      resize: vertical;
      font-family: Consolas, "Microsoft YaHei", monospace;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .row.odds-row { grid-template-columns: repeat(3, 1fr); }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 12px 0;
      color: #475467;
      font-weight: 700;
    }
    .check input { width: auto; }
    button, .link-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border: 0;
      border-radius: 6px;
      padding: 0 14px;
      background: var(--blue);
      color: white;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
    }
    button.secondary, .link-button.secondary { background: #344054; }
    button:disabled { opacity: 0.62; cursor: wait; }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }
    .status {
      margin-top: 14px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f8fafc;
      min-height: 44px;
      white-space: pre-wrap;
    }
    .status.ok { border-color: #b7e3cf; background: #f3fbf7; color: var(--green); }
    .status.err { border-color: #ffd0c7; background: #fff7f5; color: var(--red); }
    .prediction-result {
      margin-top: 14px;
      padding: 16px;
      border: 1px solid #b7e3cf;
      border-radius: 6px;
      background: #f3fbf7;
      white-space: pre-wrap;
      font-size: 15px;
      line-height: 1.8;
    }
    .result-links {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }
    .hint { color: var(--muted); margin-bottom: 0; }
    code {
      padding: 2px 5px;
      border-radius: 4px;
      background: #edf1f7;
    }
    @media (max-width: 860px) {
      main { width: min(100% - 20px, 1180px); padding-top: 12px; }
      h1 { font-size: 22px; }
      .grid, .row, .row.odds-row, .result-links { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <p class="eyebrow">Local Control Panel</p>
      <h1>足球彩票助手控制台</h1>
      <p>填期号、点按钮，自动生成分析报告、可视化页面和历史记录。</p>
    </section>

    <section class="grid">
      <article class="panel wide">
        <h2>飞书推送</h2>
        <p class="hint">开启后，生成分析、单场预测或赛后复盘时自动发送到飞书群机器人。Webhook 只在当前页面使用，不会保存到项目文件。</p>
        <label class="check"><input id="sendFeishu" type="checkbox"> 每次生成后自动发送到飞书</label>
        <label for="feishuWebhook">飞书机器人 Webhook</label>
        <input id="feishuWebhook" type="password" placeholder="可留空，改用 FEISHU_WEBHOOK_URL 环境变量" autocomplete="off">
      </article>

      <article class="panel wide">
        <h2>单场比分预测</h2>
        <p class="hint">输入任意一场比赛即可预测。若对阵存在于当前期数据中，将自动复用已采集资料；其他比赛可选填欧洲赔率提高参考价值。</p>
        <div class="row">
          <div>
            <label for="singleHome">主队</label>
            <input id="singleHome" placeholder="例如：荷兰" autocomplete="off" required>
          </div>
          <div>
            <label for="singleAway">客队</label>
            <input id="singleAway" placeholder="例如：瑞典" autocomplete="off" required>
          </div>
        </div>
        <div class="row odds-row">
          <div>
            <label for="singleHomeOdds">主胜欧赔（可选）</label>
            <input id="singleHomeOdds" type="number" min="1.01" step="0.01" placeholder="2.35">
          </div>
          <div>
            <label for="singleDrawOdds">平局欧赔（可选）</label>
            <input id="singleDrawOdds" type="number" min="1.01" step="0.01" placeholder="3.20">
          </div>
          <div>
            <label for="singleAwayOdds">客胜欧赔（可选）</label>
            <input id="singleAwayOdds" type="number" min="1.01" step="0.01" placeholder="2.95">
          </div>
        </div>
        <div class="actions"><button id="runSinglePrediction">预测这场比赛</button></div>
        <div id="singleStatus" class="status">请输入主队和客队。</div>
        <div id="singleResult" class="prediction-result" hidden></div>
      </article>

      <article class="panel">
        <h2>生成赛前分析</h2>
        <p class="hint">日常只需要填正在发售的期号，然后点生成。生成过程可能需要几十秒到两三分钟。</p>
        <div class="row">
          <div>
            <label for="issue">期号</label>
            <input id="issue" value="26087" autocomplete="off" required>
          </div>
          <div>
            <label for="xgMatches">xG 样本场次</label>
            <input id="xgMatches" type="number" min="0" max="20" value="8" required>
          </div>
        </div>
        <label class="check"><input id="strengthModel" type="checkbox" checked> 启用球队实力模型</label>
        <label class="check"><input id="noHistory" type="checkbox"> 本次不写入历史中心</label>
        <div class="actions">
          <button id="runAnalysis">生成分析报告</button>
          <a class="link-button secondary" href="/reports/history/index.html" target="_blank">打开历史中心</a>
        </div>
        <div id="analysisStatus" class="status">准备就绪。</div>
        <div id="analysisLinks" class="result-links"></div>
      </article>

      <article class="panel">
        <h2>生成赛后复盘</h2>
        <p class="hint">填写期号后，会优先使用该期已生成的赛前数据并从多个来源自动拉取赛果；如果来源未更新，再取消自动拉取并粘贴 CSV。</p>
        <label for="reviewIssue">期号</label>
        <input id="reviewIssue" value="26087" autocomplete="off" required>
        <label class="check"><input id="autoResults" type="checkbox" checked> 多来源自动拉取赛果</label>
        <label for="resultsCsv">赛果 CSV</label>
        <textarea id="resultsCsv">seq,score
1,2-1
2,1-1
3,0-2</textarea>
        <label class="check"><input id="reviewNoHistory" type="checkbox"> 本次不写入历史中心</label>
        <div class="actions">
          <button id="runReview">生成复盘报告</button>
          <a class="link-button secondary" href="/reports/history/index.html" target="_blank">打开历史中心</a>
        </div>
        <div id="reviewStatus" class="status">等待赛果。</div>
        <div id="reviewLinks" class="result-links"></div>
      </article>
    </section>
  </main>

  <script>
    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "执行失败");
      }
      return data;
    }

    function setStatus(id, text, kind) {
      const el = document.getElementById(id);
      el.className = "status" + (kind ? " " + kind : "");
      el.textContent = text;
    }

    function setLinks(id, result) {
      const el = document.getElementById(id);
      const links = [
        ["HTML 报告", result.html_url],
        ["Markdown", result.markdown_url],
        ["历史中心", result.history_url]
      ].filter((item) => item[1]);
      el.innerHTML = links.map(([label, href]) => `<a class="link-button" href="${href}" target="_blank">${label}</a>`).join("");
    }

    function rejectField(statusId, field, message) {
      setStatus(statusId, message, "err");
      field.focus();
      field.reportValidity();
      return false;
    }

    function requireTextField(fieldId, statusId, message) {
      const field = document.getElementById(fieldId);
      if (!field.value.trim()) {
        field.setCustomValidity(message);
        return rejectField(statusId, field, message);
      }
      field.setCustomValidity("");
      return true;
    }

    function requireNumberField(fieldId, statusId, message) {
      const field = document.getElementById(fieldId);
      if (!field.value.trim()) {
        field.setCustomValidity(message);
        return rejectField(statusId, field, message);
      }
      if (!field.checkValidity()) {
        field.setCustomValidity("");
        return rejectField(statusId, field, "请填写允许范围内的数字。");
      }
      field.setCustomValidity("");
      return true;
    }

    function validateOddsGroup(statusId) {
      const fields = ["singleHomeOdds", "singleDrawOdds", "singleAwayOdds"].map((id) => document.getElementById(id));
      const filled = fields.filter((field) => field.value.trim());
      if (filled.length > 0 && filled.length < fields.length) {
        return rejectField(statusId, fields.find((field) => !field.value.trim()), "欧赔请填写完整的主胜、平局和客胜三项，或全部留空。");
      }
      const invalid = filled.find((field) => !field.checkValidity());
      if (invalid) {
        return rejectField(statusId, invalid, "欧赔必须是大于 1.00 的数字。");
      }
      return true;
    }

    function validateSinglePrediction() {
      return requireTextField("singleHome", "singleStatus", "请填写主队。")
        && requireTextField("singleAway", "singleStatus", "请填写客队。")
        && validateOddsGroup("singleStatus");
    }

    function validateAnalysis() {
      return requireTextField("issue", "analysisStatus", "请填写期号。")
        && requireNumberField("xgMatches", "analysisStatus", "请填写 xG 样本场次。");
    }

    function validateReview() {
      const autoResults = document.getElementById("autoResults").checked;
      return requireTextField("reviewIssue", "reviewStatus", "请填写期号。")
        && (autoResults || requireTextField("resultsCsv", "reviewStatus", "请粘贴赛果 CSV。"));
    }

    function updateReviewMode() {
      const autoResults = document.getElementById("autoResults").checked;
      const resultsCsv = document.getElementById("resultsCsv");
      resultsCsv.disabled = autoResults;
      resultsCsv.required = !autoResults;
      resultsCsv.setCustomValidity("");
    }

    document.getElementById("runSinglePrediction").addEventListener("click", async () => {
      const button = document.getElementById("runSinglePrediction");
      const result = document.getElementById("singleResult");
      result.hidden = true;
      if (!validateSinglePrediction()) {
        return;
      }
      button.disabled = true;
      setStatus("singleStatus", "正在计算单场预测。");
      try {
        const data = await postJson("/api/single-prediction", {
          home: document.getElementById("singleHome").value.trim(),
          away: document.getElementById("singleAway").value.trim(),
          home_odds: document.getElementById("singleHomeOdds").value,
          draw_odds: document.getElementById("singleDrawOdds").value,
          away_odds: document.getElementById("singleAwayOdds").value,
          send_feishu: document.getElementById("sendFeishu").checked,
          feishu_webhook: document.getElementById("feishuWebhook").value.trim()
        });
        setStatus("singleStatus", data.message, "ok");
        result.textContent = [
          `${data.home} vs ${data.away}`,
          `首选比分：${data.scorelines[0].score}（${data.scorelines[0].probability}%）`,
          `备选比分：${data.scorelines.slice(1).map(item => `${item.score}（${item.probability}%）`).join("、")}`,
          `胜平负概率：主胜 ${data.probabilities.home}%　平 ${data.probabilities.draw}%　客胜 ${data.probabilities.away}%`,
          `建议：${data.pick_label}　置信度：${data.confidence}%　风险：${data.risk}`,
          `数据依据：${data.data_source}`,
          ...data.reasons.map(item => `• ${item}`)
        ].join("\\n");
        result.hidden = false;
      } catch (error) {
        setStatus("singleStatus", error.message, "err");
      } finally {
        button.disabled = false;
      }
    });

    document.getElementById("runAnalysis").addEventListener("click", async () => {
      const button = document.getElementById("runAnalysis");
      if (!validateAnalysis()) {
        return;
      }
      button.disabled = true;
      setStatus("analysisStatus", "正在生成分析报告，请稍等。窗口不要关。");
      document.getElementById("analysisLinks").innerHTML = "";
      try {
        const data = await postJson("/api/analysis", {
          issue: document.getElementById("issue").value.trim(),
          strength_model: document.getElementById("strengthModel").checked,
          strength_xg_matches: Number(document.getElementById("xgMatches").value),
          no_history: document.getElementById("noHistory").checked,
          send_feishu: document.getElementById("sendFeishu").checked,
          feishu_webhook: document.getElementById("feishuWebhook").value.trim()
        });
        setStatus("analysisStatus", data.message, "ok");
        setLinks("analysisLinks", data);
      } catch (error) {
        setStatus("analysisStatus", error.message, "err");
      } finally {
        button.disabled = false;
      }
    });

    document.getElementById("runReview").addEventListener("click", async () => {
      const button = document.getElementById("runReview");
      if (!validateReview()) {
        return;
      }
      button.disabled = true;
      const autoResults = document.getElementById("autoResults").checked;
      setStatus("reviewStatus", autoResults ? "正在从多个来源自动拉取赛果并生成复盘报告。" : "正在使用手工 CSV 生成复盘报告。");
      document.getElementById("reviewLinks").innerHTML = "";
      try {
        const data = await postJson("/api/review", {
          issue: document.getElementById("reviewIssue").value.trim(),
          auto_results: autoResults,
          results_csv: document.getElementById("resultsCsv").value,
          no_history: document.getElementById("reviewNoHistory").checked,
          send_feishu: document.getElementById("sendFeishu").checked,
          feishu_webhook: document.getElementById("feishuWebhook").value.trim()
        });
        setStatus("reviewStatus", data.message, "ok");
        setLinks("reviewLinks", data);
      } catch (error) {
        setStatus("reviewStatus", error.message, "err");
      } finally {
        button.disabled = false;
      }
    });

    document.getElementById("autoResults").addEventListener("change", updateReviewMode);
    updateReviewMode();
  </script>
</body>
</html>
"""


def _handler(root: Path):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                self._send_html(render_ui())
                return
            super().do_GET()

        def do_POST(self) -> None:
            try:
                if self.path == "/api/analysis":
                    self._send_json(_run_analysis(_read_json(self)))
                    return
                if self.path == "/api/review":
                    self._send_json(_run_review(_read_json(self)))
                    return
                if self.path == "/api/single-prediction":
                    self._send_json(_run_single_prediction(_read_json(self)))
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def _send_html(self, content: str) -> None:
            raw = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args) -> None:
            print(f"[ui] {self.address_string()} - {format % args}")

    return Handler


def _read_json(handler: SimpleHTTPRequestHandler) -> dict[str, object]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8")
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid request body.")
    return data


def _run_analysis(payload: dict[str, object]) -> dict[str, object]:
    issue = str(payload.get("issue") or "").strip()
    if not issue:
        raise ValueError("请填写期号。")
    strength_xg_matches = _parse_required_int(
        payload,
        "strength_xg_matches",
        empty_message="请填写 xG 样本场次。",
        invalid_message="xG 样本场次必须是 0 到 20 之间的整数。",
        minimum=0,
        maximum=20,
    )
    slug = _slug(issue)
    issue_path = Path("data/collected_issue.json")
    issue_archive_path = _issue_data_path(issue)
    markdown_path = Path("reports") / f"{slug}_report.md"
    html_path = Path("reports") / f"{slug}_report.html"
    history_dir = Path("reports/history")

    collect_issue(
        output_path=issue_path,
        issue=issue,
        strength_model=bool(payload.get("strength_model", True)),
        strength_xg_matches=strength_xg_matches,
    )
    issue_archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(issue_path, issue_archive_path)
    plan = build_ticket_plan(load_issue(issue_path))
    write_report(plan, markdown_path)
    write_analysis_html(plan, html_path)
    history_path = None
    if not bool(payload.get("no_history", False)):
        history_path = archive_report("analysis", plan.issue.issue, html_path, markdown_path, history_dir=history_dir)
    delivery = _feishu_delivery_suffix(payload, report_path=markdown_path)

    return {
        "ok": True,
        "message": f"{issue} 分析报告已生成{delivery}。",
        "html_url": _url_for(html_path),
        "markdown_url": _url_for(markdown_path),
        "history_url": _url_for(history_path or history_dir / "index.html"),
    }


def _run_single_prediction(payload: dict[str, object]) -> dict[str, object]:
    home = str(payload.get("home") or "").strip()
    away = str(payload.get("away") or "").strip()
    if not home or not away:
        raise ValueError("请填写主队和客队。")
    if home.casefold() == away.casefold():
        raise ValueError("主队和客队不能相同。")

    match = _find_collected_match(home, away)
    if match:
        data_source = "当前期已采集的赔率、球队状态和伤停信号"
    else:
        odds_values = [str(payload.get(key) or "").strip() for key in ("home_odds", "draw_odds", "away_odds")]
        if any(odds_values) and not all(odds_values):
            raise ValueError("欧赔请填写完整的主胜、平局和客胜三项，或全部留空。")
        if all(odds_values):
            try:
                values = [float(value) for value in odds_values]
            except ValueError as exc:
                raise ValueError("欧赔必须是数字。") from exc
            if any(value <= 1.0 for value in values):
                raise ValueError("欧赔必须大于 1.00。")
            odds = Odds(home=values[0], draw=values[1], away=values[2])
            data_source = "手工填写的欧洲赔率；球队状态按中性值处理"
        else:
            odds = Odds(home=2.60, draw=3.20, away=2.70)
            data_source = "未匹配当前期且未填写赔率，使用均衡基准；参考价值较低"
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
    response = {
        "ok": True,
        "message": "单场比分预测已生成",
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
    delivery = _feishu_delivery_suffix(payload, text=_single_prediction_text(response))
    response["message"] = f"单场比分预测已生成{delivery}。"
    return response


def _find_collected_match(home: str, away: str) -> Match | None:
    issue_path = Path("data/collected_issue.json")
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
    return re.sub(r"[\s·・._-]+", "", value).casefold()


def _run_review(payload: dict[str, object]) -> dict[str, object]:
    requested_issue = str(payload.get("issue") or "").strip()
    issue_path = _resolve_review_issue_path(requested_issue, payload)
    results_csv = str(payload.get("results_csv") or "").strip()
    auto_results = bool(payload.get("auto_results", True))
    if not auto_results and not results_csv:
        raise ValueError("请粘贴赛果 CSV。")

    issue = load_issue(issue_path)
    slug = _slug(issue.issue)
    markdown_path = Path("reports") / f"{slug}_review.md"
    html_path = Path("reports") / f"{slug}_review.html"
    history_dir = Path("reports/history")
    _remove_stale_review_outputs(markdown_path, html_path)

    plan = build_ticket_plan(issue)
    if auto_results:
        try:
            fetched = fetch_results_with_fallbacks(issue.issue)
        except Exception as exc:
            raise ValueError(f"自动拉取赛果失败：{exc}") from exc
        results = fetched.results
        results_source = fetched.source
        if not results:
            raise ValueError("多个赛果来源暂时都没有返回本期赛果。请稍后再试，或取消自动拉取后粘贴赛果 CSV。")
        missing = [prediction.match.seq for prediction in plan.predictions if prediction.match.seq not in results]
        if missing:
            missing_text = "、".join(str(item) for item in missing)
            raise ValueError(f"{results_source} 赛果还不完整，缺少第 {missing_text} 场。请稍后再试，或取消自动拉取后粘贴赛果 CSV。")
    else:
        results_source = "手工 CSV"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as handle:
            handle.write(results_csv)
            temp_results = Path(handle.name)
        try:
            results = load_results(temp_results)
        finally:
            temp_results.unlink(missing_ok=True)
    review = build_review(plan, results)

    write_review_report(review, markdown_path)
    write_review_html(review, html_path)
    history_path = None
    if not bool(payload.get("no_history", False)):
        history_path = archive_report("review", issue.issue, html_path, markdown_path, history_dir=history_dir)
    delivery = _feishu_delivery_suffix(payload, report_path=markdown_path)

    return {
        "ok": True,
        "message": f"{issue.issue} 复盘报告已生成，赛果来源：{results_source}{delivery}。",
        "html_url": _url_for(html_path),
        "markdown_url": _url_for(markdown_path),
        "history_url": _url_for(history_path or history_dir / "index.html"),
    }


def _issue_data_path(issue: str) -> Path:
    return Path("data") / f"{_slug(issue)}_issue.json"


def _resolve_review_issue_path(requested_issue: str, payload: dict[str, object]) -> Path:
    if requested_issue:
        issue_path = _issue_data_path(requested_issue)
        if issue_path.exists():
            return issue_path

        current_path = Path("data/collected_issue.json")
        if current_path.exists():
            current_issue = load_issue(current_path)
            if current_issue.issue == requested_issue:
                return current_path

        raise ValueError(f"找不到 {requested_issue} 的赛前数据。请先在上方生成该期赛前分析。")

    issue_path_value = str(payload.get("issue_path") or "data/collected_issue.json").strip()
    issue_path = Path(issue_path_value)
    if not issue_path.exists():
        raise ValueError(f"找不到赛前数据：{issue_path}。请先生成赛前分析，或填写正确的数据文件路径。")
    return issue_path


def _remove_stale_review_outputs(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _parse_required_int(
    payload: dict[str, object],
    key: str,
    *,
    empty_message: str,
    invalid_message: str,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(payload.get(key) if payload.get(key) is not None else "").strip()
    if not raw:
        raise ValueError(empty_message)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(invalid_message) from exc
    if value < minimum or value > maximum:
        raise ValueError(invalid_message)
    return value


def _feishu_delivery_suffix(
    payload: dict[str, object],
    *,
    report_path: Path | None = None,
    text: str | None = None,
) -> str:
    if not bool(payload.get("send_feishu", False)):
        return ""
    webhook = str(payload.get("feishu_webhook") or "").strip() or None
    try:
        if report_path is not None:
            send_report("feishu", report_path, webhook)
        else:
            send_text("feishu", text or "", webhook)
    except NotifyError as exc:
        return f"，但飞书发送失败：{exc}"
    return "，并已发送到飞书"


def _single_prediction_text(result: dict[str, object]) -> str:
    scorelines = result["scorelines"]
    probabilities = result["probabilities"]
    scores = "、".join(f"{item['score']}（{item['probability']}%）" for item in scorelines)
    return (
        f"单场比分预测：{result['home']} vs {result['away']}\n"
        f"比分倾向：{scores}\n"
        f"胜平负概率：主胜 {probabilities['home']}% / 平 {probabilities['draw']}% / 客胜 {probabilities['away']}%\n"
        f"建议：{result['pick_label']}，置信度 {result['confidence']}%，风险 {result['risk']}\n"
        f"数据依据：{result['data_source']}"
    )


def _url_for(path: Path) -> str:
    return "/" + unquote(path.as_posix())


def _slug(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip())
    clean = clean.strip("-")
    return clean or "report"
