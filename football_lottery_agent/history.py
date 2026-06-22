from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path


DEFAULT_HISTORY_DIR = Path("reports/history")
MAX_HISTORY_ENTRIES = 52


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    kind: str
    issue: str
    title: str
    created_at: str
    html: str
    markdown: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "issue": self.issue,
            "title": self.title,
            "created_at": self.created_at,
            "html": self.html,
            "markdown": self.markdown,
        }


def archive_report(
    kind: str,
    issue: str,
    html_path: str | Path,
    markdown_path: str | Path | None = None,
    history_dir: str | Path = DEFAULT_HISTORY_DIR,
    max_entries: int = MAX_HISTORY_ENTRIES,
    created_at: datetime | None = None,
) -> Path:
    root = Path(history_dir)
    items_dir = root / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (created_at or datetime.now()).strftime("%Y%m%d%H%M%S")
    safe_issue = _slug(issue)
    safe_kind = _slug(kind)
    entry_id = f"{timestamp}-{safe_issue}-{safe_kind}"

    html_source = Path(html_path)
    html_target = items_dir / f"{entry_id}.html"
    shutil.copyfile(html_source, html_target)

    markdown_target = ""
    if markdown_path:
        markdown_source = Path(markdown_path)
        if markdown_source.exists():
            md_target = items_dir / f"{entry_id}.md"
            shutil.copyfile(markdown_source, md_target)
            markdown_target = _relative_link(root, md_target)

    entry = HistoryEntry(
        id=entry_id,
        kind=kind,
        issue=issue,
        title=_entry_title(kind, issue),
        created_at=(created_at or datetime.now()).isoformat(timespec="seconds"),
        html=_relative_link(root, html_target),
        markdown=markdown_target,
    )
    entries = _load_entries(root)
    entries = [item for item in entries if item.get("id") != entry.id]
    entries.insert(0, entry.as_dict())
    entries = entries[:max_entries]
    _write_index_json(root, entries)
    write_history_index(root, entries)
    return root / "index.html"


def write_history_index(history_dir: str | Path = DEFAULT_HISTORY_DIR, entries: list[dict[str, str]] | None = None) -> Path:
    root = Path(history_dir)
    root.mkdir(parents=True, exist_ok=True)
    data = entries if entries is not None else _load_entries(root)
    path = root / "index.html"
    path.write_text(render_history_index(data), encoding="utf-8")
    return path


def render_history_index(entries: list[dict[str, str]]) -> str:
    options = "\n".join(
        f"<option value=\"{index}\">{escape(_option_label(item))}</option>"
        for index, item in enumerate(entries)
    )
    cards = _grouped_history_cards(entries)
    entries_json = json.dumps(entries, ensure_ascii=False)
    empty = "" if entries else "<p class=\"empty\">还没有历史记录。生成带 HTML 的分析或复盘报告后，这里会自动出现。</p>"
    first_src = escape(entries[0]["html"]) if entries else ""
    first_title = escape(entries[0]["title"]) if entries else "历史报告"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>足球彩票历史报告</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #18202f;
      --muted: #667085;
      --line: #dbe1ea;
      --green: #16845b;
      --blue: #2364aa;
      --red: #b42318;
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
      width: min(1440px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 18px;
      align-items: end;
      padding: 24px;
      margin-bottom: 16px;
      border-radius: 8px;
      background: #101828;
      color: white;
    }}
    .eyebrow {{
      margin: 0 0 6px;
      color: #8bd3dd;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    h1, h2, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin-bottom: 10px; font-size: 18px; letter-spacing: 0; }}
    .subtle, small {{ color: var(--muted); }}
    .hero .subtle {{ color: #d0d5dd; margin-bottom: 0; }}
    label {{ display: block; margin-bottom: 6px; color: #d0d5dd; font-size: 12px; }}
    select {{
      width: 100%;
      height: 42px;
      padding: 0 12px;
      border: 1px solid #475467;
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      font: inherit;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      gap: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .history-list {{
      max-height: 760px;
      overflow: auto;
      display: grid;
      gap: 8px;
    }}
    .issue-group {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f8fafc;
      overflow: hidden;
    }}
    .issue-group summary {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 11px;
      cursor: pointer;
      list-style: none;
      font-weight: 700;
    }}
    .issue-group summary::-webkit-details-marker {{ display: none; }}
    .issue-group summary::before {{ content: "＋"; color: var(--blue); font-size: 18px; }}
    .issue-group[open] summary::before {{ content: "－"; }}
    .issue-group summary span {{ margin-left: auto; color: var(--muted); font-size: 12px; font-weight: 400; }}
    .issue-entries {{ display: grid; gap: 8px; padding: 0 8px 8px; }}
    .history-card {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 10px;
      text-align: left;
      cursor: pointer;
      font: inherit;
    }}
    .history-card.active {{ border-color: var(--blue); background: #edf5ff; }}
    .history-card strong {{ display: block; margin-bottom: 4px; }}
    .history-card span {{ display: block; color: var(--muted); font-size: 12px; }}
    .kind {{
      display: inline-block;
      padding: 3px 7px;
      margin-bottom: 6px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 700;
      color: var(--blue);
      background: #e8f0fb;
    }}
    .kind.review {{ color: var(--green); background: #e9f8f1; }}
    .viewer-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }}
    .viewer-head a {{
      color: var(--blue);
      text-decoration: none;
      font-weight: 700;
    }}
    iframe {{
      width: 100%;
      height: 820px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
    }}
    .empty {{
      padding: 20px;
      color: var(--muted);
      background: white;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    @media (max-width: 980px) {{
      main {{ width: min(100% - 20px, 1440px); padding-top: 12px; }}
      .hero, .layout {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 22px; }}
      iframe {{ height: 720px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <p class="eyebrow">History Center</p>
        <h1>足球彩票历史报告</h1>
        <p class="subtle">自动保留最近 52 条分析/复盘 HTML，方便按期次回看。</p>
      </div>
      <div>
        <label for="entrySelect">选择历史报告</label>
        <select id="entrySelect">{options}</select>
      </div>
    </section>
    {empty}
    <section class="layout">
      <aside class="panel">
        <h2>历史列表</h2>
        <div class="history-list">{cards}</div>
      </aside>
      <section class="panel">
        <div class="viewer-head">
          <div>
            <h2 id="viewerTitle">{first_title}</h2>
            <small id="viewerMeta"></small>
          </div>
          <a id="openLink" href="{first_src}" target="_blank" rel="noreferrer">单独打开</a>
        </div>
        <iframe id="viewer" src="{first_src}" title="历史报告"></iframe>
      </section>
    </section>
  </main>
  <script>
    const entries = {entries_json};
    const select = document.getElementById("entrySelect");
    const viewer = document.getElementById("viewer");
    const openLink = document.getElementById("openLink");
    const title = document.getElementById("viewerTitle");
    const meta = document.getElementById("viewerMeta");
    const cards = Array.from(document.querySelectorAll(".history-card"));

    function showEntry(index) {{
      const entry = entries[index];
      if (!entry) return;
      viewer.src = entry.html;
      openLink.href = entry.html;
      title.textContent = entry.title;
      meta.textContent = `查询时间：${{formatQueryTime(entry.created_at)}} · 期次 ${{entry.issue}}`;
      select.value = String(index);
      cards.forEach((card, cardIndex) => card.classList.toggle("active", cardIndex === index));
    }}

    function formatQueryTime(value) {{
      return String(value || "").replace("T", " ");
    }}

    select?.addEventListener("change", (event) => showEntry(Number(event.target.value)));
    cards.forEach((card) => card.addEventListener("click", () => showEntry(Number(card.dataset.index))));
    showEntry(0);
  </script>
</body>
</html>
"""


def _load_entries(root: Path) -> list[dict[str, str]]:
    path = root / "index.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _write_index_json(root: Path, entries: list[dict[str, str]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _history_card(item: dict[str, str], index: int) -> str:
    kind = item.get("kind", "")
    kind_label = "复盘" if kind == "review" else "分析"
    active = " active" if index == 0 else ""
    return f"""
    <button class="history-card{active}" type="button" data-index="{index}">
      <span class="kind {escape(kind)}">{kind_label}</span>
      <strong>{escape(item.get("title", ""))}</strong>
      <span>查询时间：{escape(_display_time(item.get("created_at", "")))}</span>
    </button>
    """


def _grouped_history_cards(entries: list[dict[str, str]]) -> str:
    groups: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for index, item in enumerate(entries):
        groups.setdefault(item.get("issue", "未知期次"), []).append((index, item))
    sections = []
    for group_index, (issue, items) in enumerate(groups.items()):
        cards = "\n".join(_history_card(item, index) for index, item in items)
        open_attr = " open" if group_index == 0 else ""
        sections.append(
            f"""
            <details class="issue-group"{open_attr}>
              <summary>期号 {escape(issue)}<span>{len(items)} 次查询</span></summary>
              <div class="issue-entries">{cards}</div>
            </details>
            """
        )
    return "\n".join(sections)


def _display_time(value: str) -> str:
    return value.replace("T", " ")


def _entry_title(kind: str, issue: str) -> str:
    prefix = "复盘报告" if kind == "review" else "分析报告"
    return f"{prefix}：{issue}"


def _option_label(item: dict[str, str]) -> str:
    kind = "复盘" if item.get("kind") == "review" else "分析"
    return f"{item.get('created_at', '')} · {kind} · {item.get('issue', '')}"


def _relative_link(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


def _slug(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip())
    clean = clean.strip("-")
    return clean or "report"
