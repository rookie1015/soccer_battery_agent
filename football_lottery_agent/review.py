from __future__ import annotations

import csv
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import Prediction, TicketPlan
from .predictor import OUTCOME_LABELS


SINA_SFC_URL = "https://view.lottery.sina.com.cn/lottery_index/sfc/index?num="


@dataclass(frozen=True)
class MatchResult:
    seq: int
    home_goals: int
    away_goals: int

    @property
    def score_text(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"

    @property
    def outcome(self) -> str:
        if self.home_goals > self.away_goals:
            return "3"
        if self.home_goals == self.away_goals:
            return "1"
        return "0"


@dataclass(frozen=True)
class MatchReview:
    prediction: Prediction
    result: MatchResult
    outcome_hit: bool
    top_score_hit: bool
    score_top3_hit: bool
    bucket: str


@dataclass(frozen=True)
class ReviewReport:
    plan: TicketPlan
    rows: tuple[MatchReview, ...]

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def outcome_hits(self) -> int:
        return sum(1 for row in self.rows if row.outcome_hit)

    @property
    def single_rows(self) -> tuple[MatchReview, ...]:
        return tuple(row for row in self.rows if len(row.prediction.picks) == 1)

    @property
    def single_hits(self) -> int:
        return sum(1 for row in self.single_rows if row.outcome_hit)

    @property
    def top_score_hits(self) -> int:
        return sum(1 for row in self.rows if row.top_score_hit)

    @property
    def score_top3_hits(self) -> int:
        return sum(1 for row in self.rows if row.score_top3_hit)

    @property
    def keep_rows(self) -> tuple[MatchReview, ...]:
        keep = set(self.plan.choose9_keep)
        return tuple(row for row in self.rows if row.result.seq in keep)

    @property
    def drop_rows(self) -> tuple[MatchReview, ...]:
        drop = set(self.plan.choose9_drop)
        return tuple(row for row in self.rows if row.result.seq in drop)

    @property
    def keep_hits(self) -> int:
        return sum(1 for row in self.keep_rows if row.outcome_hit)

    @property
    def effective_drops(self) -> int:
        return sum(1 for row in self.drop_rows if not row.outcome_hit)

    @property
    def major_misses(self) -> tuple[MatchReview, ...]:
        return tuple(row for row in self.rows if _is_major_miss(row))


def load_results(path: str | Path) -> dict[int, MatchResult]:
    results: dict[int, MatchResult] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            if not raw or not raw.get("seq"):
                continue
            result = _parse_result_row(raw)
            results[result.seq] = result
    return results


def fetch_sina_results(issue: str, cache_dir: str | Path = "data/cache") -> dict[int, MatchResult]:
    html = _fetch_text(f"{SINA_SFC_URL}{issue}", Path(cache_dir), max_age_seconds=300)
    return parse_sina_results_html(html)


def parse_sina_results_html(html: str) -> dict[int, MatchResult]:
    table = _first_match(r'(<table class="sfcPubTable">[\s\S]*?</table>)', html)
    if not table:
        return {}
    results: dict[int, MatchResult] = {}
    rows = re.findall(r"<tr[^>]*>[\s\S]*?</tr>", table)
    for row in rows:
        cells = _extract_cells(row)
        if len(cells) < 7 or not cells[0].strip().isdigit():
            continue
        seq = int(cells[0])
        score = cells[4].strip()
        if not _looks_like_score(score):
            continue
        home_goals, away_goals = _parse_score(score)
        results[seq] = MatchResult(seq=seq, home_goals=home_goals, away_goals=away_goals)
    return results


def build_review(plan: TicketPlan, results: dict[int, MatchResult]) -> ReviewReport:
    rows: list[MatchReview] = []
    missing = [prediction.match.seq for prediction in plan.predictions if prediction.match.seq not in results]
    if missing:
        raise ValueError(f"Missing results for match seq: {', '.join(str(item) for item in missing)}")

    keep = set(plan.choose9_keep)
    for prediction in plan.predictions:
        result = results[prediction.match.seq]
        score_texts = tuple(item.text for item in prediction.scorelines)
        bucket = "任九保留" if result.seq in keep else "任九剔除"
        rows.append(
            MatchReview(
                prediction=prediction,
                result=result,
                outcome_hit=result.outcome in prediction.picks,
                top_score_hit=bool(score_texts and result.score_text == score_texts[0]),
                score_top3_hit=result.score_text in score_texts,
                bucket=bucket,
            )
        )
    return ReviewReport(plan=plan, rows=tuple(rows))


def render_review_markdown(report: ReviewReport) -> str:
    lines: list[str] = []
    single_total = len(report.single_rows)
    keep_total = len(report.keep_rows)
    drop_total = len(report.drop_rows)
    lines.append(f"# 足球彩票复盘报告：{report.plan.issue.issue}")
    lines.append("")
    lines.append("> 复盘只用于校验模型与记录决策质量，不代表后续场次必然延续同样表现。")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append(f"- 胜平负命中：{report.outcome_hits}/{report.total}（{_rate(report.outcome_hits, report.total)}）")
    lines.append(f"- 单选命中：{report.single_hits}/{single_total}（{_rate(report.single_hits, single_total)}）")
    lines.append(f"- 比分 Top1 命中：{report.top_score_hits}/{report.total}（{_rate(report.top_score_hits, report.total)}）")
    lines.append(f"- 比分 Top3 命中：{report.score_top3_hits}/{report.total}（{_rate(report.score_top3_hits, report.total)}）")
    lines.append(f"- 任九保留命中：{report.keep_hits}/{keep_total}（{_rate(report.keep_hits, keep_total)}）")
    lines.append(f"- 任九剔除有效：{report.effective_drops}/{drop_total}（{_rate(report.effective_drops, drop_total)}）")
    lines.append("")
    lines.append("## 逐场复盘")
    lines.append("")
    lines.append("| 序号 | 对阵 | 赛果 | 实际 | 推荐 | 胜平负 | 比分倾向 | 比分 | 任九 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in report.rows:
        prediction = row.prediction
        match = prediction.match
        actual = OUTCOME_LABELS[row.result.outcome]
        outcome_mark = "命中" if row.outcome_hit else "未中"
        score_mark = "Top1" if row.top_score_hit else ("Top3" if row.score_top3_hit else "未中")
        lines.append(
            f"| {match.seq} | {match.home} vs {match.away} | {row.result.score_text} | {actual} | "
            f"{prediction.pick_text} | {outcome_mark} | {_scoreline_summary(prediction)} | {score_mark} | {row.bucket} |"
        )
    lines.append("")
    lines.append("## 需要关注")
    lines.append("")
    misses = [row for row in report.rows if not row.outcome_hit]
    if not misses:
        lines.append("- 胜平负推荐全部覆盖，后续重点观察比分模型是否过于保守。")
    else:
        for row in misses[:5]:
            prediction = row.prediction
            match = prediction.match
            lines.append(
                f"- {match.seq}. {match.home} vs {match.away}：推荐 `{prediction.pick_text}`，"
                f"实际 {row.result.score_text}（{OUTCOME_LABELS[row.result.outcome]}），"
                f"赛前置信度 {prediction.confidence:.1f}%，风险 {prediction.risk}。"
            )
    lines.append("")
    return "\n".join(lines)


def _is_major_miss(row: MatchReview) -> bool:
    prediction = row.prediction
    return (
        not row.outcome_hit
        and (
            len(prediction.picks) == 1
            or prediction.risk == "低"
            or prediction.confidence >= 56.0
        )
    )


def write_review_report(report: ReviewReport, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_markdown(report), encoding="utf-8")
    return path


def _parse_result_row(raw: dict[str, str]) -> MatchResult:
    seq = int((raw.get("seq") or "").strip())
    if raw.get("score"):
        home_goals, away_goals = _parse_score(raw["score"])
    else:
        home_goals = int((raw.get("home_goals") or "").strip())
        away_goals = int((raw.get("away_goals") or "").strip())
    return MatchResult(seq=seq, home_goals=home_goals, away_goals=away_goals)


def _parse_score(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*[-:：]\s*(\d+)\s*", value)
    if not match:
        raise ValueError(f"Invalid score value: {value!r}")
    return int(match.group(1)), int(match.group(2))


def _looks_like_score(value: str) -> bool:
    return bool(re.fullmatch(r"\s*\d+\s*[-:：]\s*\d+\s*", value))


def _extract_cells(row_html: str) -> list[str]:
    cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row_html)
    return [_squash(re.sub(r"<[^>]+>", " ", cell)) for cell in cells]


def _fetch_text(url: str, cache_dir: Path, max_age_seconds: int) -> str:
    import hashlib
    from datetime import datetime

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.txt"
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age <= max_age_seconds:
            return cache_path.read_text(encoding="utf-8", errors="replace")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 football-lottery-agent/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="replace")
        raise exc
    cache_path.write_text(text, encoding="utf-8")
    return text


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _scoreline_summary(prediction: Prediction) -> str:
    return "，".join(f"{item.text} {item.probability:.0%}" for item in prediction.scorelines)


def _rate(count: int, total: int) -> str:
    if total <= 0:
        return "N/A"
    return f"{count / total:.0%}"
