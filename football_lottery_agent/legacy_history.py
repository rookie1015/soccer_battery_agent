"""Compatibility parsers for report formats which predate structured snapshots.

New analysis and review code must not add fields here.  This module is kept at
the history boundary so legacy line portfolios do not leak into new contracts.
"""

from __future__ import annotations

import re


def parse_line_portfolio_markdown(
    markdown_text: str,
    predictions: list[dict[str, object]],
) -> dict[str, object] | None:
    summary = re.search(
        r"^- 独立线路：(\d+) 注，实际成本 (\d+)/(\d+) 元。?$",
        markdown_text,
        re.MULTILINE,
    )
    if not summary:
        return None
    line_count, cost, allocated = map(int, summary.groups())
    combination = re.search(
        r"^- 多平组合：(\d+) 注至少包含两个候选平局；任意两场候选同时为平至少 (\d+) 注。?$",
        markdown_text,
        re.MULTILINE,
    )
    matches = {
        int(prediction["seq"]): (str(prediction["home"]), str(prediction["away"]))
        for prediction in predictions
    }
    coverages: list[dict[str, object]] = []
    if "## 平局线路配额" in markdown_text:
        coverage_text = markdown_text.split("## 平局线路配额", 1)[1].split("\n## ", 1)[0]
        for line in coverage_text.splitlines():
            if not line.startswith("| ") or "---" in line or "序号" in line:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 6 or not cells[0].isdigit():
                continue
            seq = int(cells[0])
            home, away = matches.get(seq, _split_matchup(cells[1]))
            coverages.append(
                {
                    "seq": seq,
                    "home": home,
                    "away": away,
                    "probability": _parse_percent(cells[2]),
                    "target_lines": int(cells[3]),
                    "actual_lines": int(cells[4]),
                    "actual_share": _parse_percent(cells[5]),
                }
            )
    lines: list[dict[str, object]] = []
    if "## 完整投注线路" in markdown_text:
        lines_text = markdown_text.split("## 完整投注线路", 1)[1].split("\n## ", 1)[0]
        for match in re.finditer(r"^(\d+)\. `([310](?:-[310]){13})`$", lines_text, re.MULTILINE):
            lines.append(
                {
                    "number": int(match.group(1)),
                    "pick_text": match.group(2),
                    "outcomes": match.group(2).split("-"),
                    "joint_probability": 0.0,
                }
            )
    if len(lines) != line_count:
        return None
    return {
        "legacy_schema": "legacy-line-portfolio-v1",
        "line_count": line_count,
        "allocated_budget_yuan": allocated,
        "cost_yuan": cost,
        "multi_draw_lines": int(combination.group(1)) if combination else 0,
        "minimum_draw_pair_lines": int(combination.group(2)) if combination else 0,
        "draw_coverages": coverages,
        "lines": lines,
    }


def _parse_percent(value: str) -> float:
    match = re.search(r"([0-9.]+)%?", value)
    return float(match.group(1)) if match else 0.0


def _split_matchup(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+(?:vs|VS|v|V|—|–|-|对)\s+", value.strip(), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (value.strip(), "")
