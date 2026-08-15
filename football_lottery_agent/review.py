from __future__ import annotations

import csv
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .json_utils import loads_json
from .models import Prediction, TicketPlan
from .predictor import OUTCOME_LABELS


SINA_SFC_URL = "https://view.lottery.sina.com.cn/lottery_index/sfc/index?num="
SPORTTERY_HISTORY_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
EASTMONEY_SFC_URL = "https://caipiao.eastmoney.com/Result/Category/sfc"
EASTMONEY_HISTORY_URL = "https://caipiao.eastmoney.com/Result/History/sfc"
WUBAI_SFC_URL = "https://kaijiang.500.com/sfc.shtml"


@dataclass(frozen=True)
class ResultsFetch:
    results: dict[int, "MatchResult"]
    source: str


@dataclass(frozen=True)
class MatchResult:
    seq: int
    home_goals: int
    away_goals: int
    score_exact: bool = True

    @property
    def score_text(self) -> str:
        if not self.score_exact:
            return f"{OUTCOME_LABELS[self.outcome]}（仅彩果）"
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
    analysis_outcome_hit: bool
    top_score_hit: bool
    score_top3_hit: bool
    bucket: str
    diagnostic_tags: tuple[str, ...] = ()


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
        return tuple(row for row in self.rows if len(row.prediction.analysis_picks) == 1)

    @property
    def single_hits(self) -> int:
        return sum(1 for row in self.single_rows if row.analysis_outcome_hit)

    @property
    def budget_caused_misses(self) -> int:
        return sum(
            1
            for row in self.rows
            if not row.outcome_hit and row.analysis_outcome_hit and row.prediction.budget_adjusted
        )

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

    @property
    def score_total(self) -> int:
        return sum(1 for row in self.rows if row.result.score_exact)

    @property
    def diagnostic_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            for tag in row.diagnostic_tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts


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


def fetch_sporttery_results(issue: str, cache_dir: str | Path = "data/cache") -> dict[int, MatchResult]:
    params = {
        "gameNo": "90",
        "provinceId": "0",
        "pageSize": "10",
        "pageNo": "1",
        "startTerm": issue,
        "endTerm": issue,
    }
    url = f"{SPORTTERY_HISTORY_URL}?{urllib.parse.urlencode(params)}"
    raw = loads_json(_fetch_text(url, Path(cache_dir), max_age_seconds=300))
    if str(raw.get("errorCode")) != "0":
        raise ValueError(str(raw.get("errorMessage") or "Sporttery result request failed."))
    value = raw.get("value") or {}
    rows = value.get("list") or []
    for row in rows:
        if str(row.get("lotteryDrawNum") or "").strip() == issue:
            return parse_sporttery_result_row(row)
    return {}


def fetch_results_with_fallbacks(issue: str, cache_dir: str | Path = "data/cache") -> ResultsFetch:
    errors: list[str] = []
    providers = (
        ("中国体彩网官方开奖", lambda: fetch_sporttery_results(issue, cache_dir=cache_dir)),
    )
    best = ResultsFetch(results={}, source="")
    for source, fetcher in providers:
        try:
            results = fetcher()
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue
        if len(results) > len(best.results):
            best = ResultsFetch(results=results, source=source)
        if len(results) >= 14:
            return ResultsFetch(results=results, source=source)
    if best.results:
        return best
    detail = "；".join(errors)
    if detail:
        raise ValueError(f"中国体彩网官方开奖结果暂时不可用。{detail}")
    raise ValueError(f"中国体彩网官方暂未返回 {issue} 期开奖结果。请确认该期已经开奖。")


def fetch_eastmoney_results(issue: str, cache_dir: str | Path = "data/cache") -> dict[int, MatchResult]:
    html = _fetch_text(EASTMONEY_SFC_URL, Path(cache_dir), max_age_seconds=300)
    return parse_outcome_results_html(html, issue)


def fetch_eastmoney_history_results(issue: str, cache_dir: str | Path = "data/cache") -> dict[int, MatchResult]:
    html = _fetch_text(EASTMONEY_HISTORY_URL, Path(cache_dir), max_age_seconds=300)
    return parse_outcome_results_html(html, issue)


def fetch_wubai_results(issue: str, cache_dir: str | Path = "data/cache") -> dict[int, MatchResult]:
    html = _fetch_text(WUBAI_SFC_URL, Path(cache_dir), max_age_seconds=300)
    return parse_outcome_results_html(html, issue)


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


def parse_outcome_results_html(html: str, issue: str) -> dict[int, MatchResult]:
    normalized = _squash(re.sub(r"<[^>]+>", " ", html))
    section = _issue_section(normalized, issue)
    if not section:
        return {}
    outcomes = _extract_outcomes(section)
    return {
        seq: _result_from_outcome(seq, outcome)
        for seq, outcome in enumerate(outcomes[:14], start=1)
    }


def parse_sporttery_result_row(row: dict[str, object]) -> dict[int, MatchResult]:
    matches = row.get("matchList")
    if isinstance(matches, list) and matches:
        results: dict[int, MatchResult] = {}
        for index, match in enumerate(matches, start=1):
            if not isinstance(match, dict):
                continue
            outcome = str(match.get("result") or "").strip()
            score = str(match.get("czScore") or "").strip()
            if not outcome and not score:
                continue
            seq = int(match.get("matchNum") or index)
            if _looks_like_score(score):
                home_goals, away_goals = _parse_score(score)
                result = MatchResult(seq=seq, home_goals=home_goals, away_goals=away_goals)
                if not outcome or result.outcome == _normalize_outcome_label(outcome):
                    results[seq] = result
                    continue
            results[seq] = _result_from_outcome(seq, outcome)
        return results

    outcomes = str(row.get("lotteryDrawResult") or "").split()
    return {seq: _result_from_outcome(seq, outcome) for seq, outcome in enumerate(outcomes[:14], start=1)}


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
                analysis_outcome_hit=result.outcome in prediction.analysis_picks,
                top_score_hit=result.score_exact and bool(score_texts and result.score_text == score_texts[0]),
                score_top3_hit=result.score_exact and result.score_text in score_texts,
                bucket=bucket,
                diagnostic_tags=_diagnostic_tags(prediction, result),
            )
        )
    return ReviewReport(plan=plan, rows=tuple(rows))


def render_review_markdown(
    report: ReviewReport,
    post_match_evidence: dict[int, list[dict[str, object]]] | None = None,
) -> str:
    evidence_by_seq = post_match_evidence or {}
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
    lines.append(f"- 预算压缩导致漏判：{report.budget_caused_misses} 场")
    lines.append(f"- 比分 Top1 命中：{report.top_score_hits}/{report.score_total}（{_rate(report.top_score_hits, report.score_total)}）")
    lines.append(f"- 比分 Top3 命中：{report.score_top3_hits}/{report.score_total}（{_rate(report.score_top3_hits, report.score_total)}）")
    lines.append(f"- 任九保留命中：{report.keep_hits}/{keep_total}（{_rate(report.keep_hits, keep_total)}）")
    lines.append(f"- 任九剔除有效：{report.effective_drops}/{drop_total}（{_rate(report.effective_drops, drop_total)}）")
    lines.append("")
    lines.append("## 错因记录")
    lines.append("")
    if report.diagnostic_counts:
        lines.append("- 本期失手标签：" + "；".join(f"{tag} {count} 场" for tag, count in report.diagnostic_counts.items()))
        lines.append("- 标签用于定位后续可验证的改进方向，不等同于赛后因果结论。")
    else:
        lines.append("- 本期胜平负推荐全部覆盖，无失手标签。")
    lines.append("")
    lines.append("## 逐场复盘")
    lines.append("")
    lines.append("| 序号 | 对阵 | 最终比分 | 彩果 | 推荐 | 胜平负 | 比分预测 | 任九 | 错因标签 | 赛后外部线索 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in report.rows:
        prediction = row.prediction
        match = prediction.match
        actual = OUTCOME_LABELS[row.result.outcome]
        outcome_mark = "命中" if row.outcome_hit else "未中"
        lines.append(
            f"| {match.seq} | {match.home} vs {match.away} | {row.result.score_text} | {actual} | "
            f"{_review_pick_text(prediction)} | {outcome_mark} | {_scoreline_summary(prediction)} | {row.bucket} | {'、'.join(row.diagnostic_tags) or '-'} | {_evidence_summary(evidence_by_seq.get(match.seq, []))} |"
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


def _diagnostic_tags(prediction: Prediction, result: MatchResult) -> tuple[str, ...]:
    if result.outcome in prediction.picks:
        return ()

    tags: list[str] = []
    actual_probability = prediction.probabilities.get(result.outcome, 0.0)
    top_outcome, top_probability = max(prediction.probabilities.items(), key=lambda item: item[1])
    if result.outcome == "1" and "1" not in prediction.picks:
        tags.append("平局漏判")
    if prediction.tactical_draw:
        tags.append("战术单平失误")
    if prediction.budget_adjusted and result.outcome in prediction.analysis_picks:
        tags.append("预算压缩导致漏判")
    elif prediction.budget_forced_single:
        tags.append("预算强制单选")
    if len(prediction.picks) == 1:
        tags.append("单选覆盖不足")
    if prediction.risk == "低" or prediction.confidence >= 56.0:
        tags.append("高置信反转")
    if top_outcome != result.outcome and top_probability - actual_probability >= 0.20:
        tags.append("强弱判断偏差")
    if actual_probability <= 0.25:
        tags.append("冷门结果")
    return tuple(tags or ["赛前概率偏差"])


def _review_pick_text(prediction: Prediction) -> str:
    if not prediction.budget_adjusted:
        return prediction.pick_text
    return f"模型 {prediction.analysis_pick_text} → 预算 {prediction.pick_text}"


def write_review_report(
    report: ReviewReport,
    output_path: str | Path,
    post_match_evidence: dict[int, list[dict[str, object]]] | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_review_markdown(report, post_match_evidence), encoding="utf-8")
    return path


def _parse_result_row(raw: dict[str, str]) -> MatchResult:
    seq = int((raw.get("seq") or "").strip())
    if raw.get("score"):
        home_goals, away_goals = _parse_score(raw["score"])
        return MatchResult(seq=seq, home_goals=home_goals, away_goals=away_goals)
    if raw.get("outcome"):
        return _result_from_outcome(seq, raw["outcome"])
    if raw.get("result"):
        return _result_from_outcome(seq, raw["result"])
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


def _issue_section(text: str, issue: str) -> str:
    start = text.find(issue)
    if start < 0:
        return ""
    tail = text[start : start + 3000]
    next_issue = re.search(rf"\b(?!{re.escape(issue)}\b)\d{{5}}\b", tail[20:])
    if next_issue:
        return tail[: 20 + next_issue.start()]
    return tail


def _extract_outcomes(section: str) -> list[str]:
    candidates = re.findall(r"[310]{14}", section)
    if candidates:
        return list(candidates[0])
    spaced = re.findall(r"(?:^|[^\d])((?:[310]\s+){13}[310])(?:[^\d]|$)", section)
    if spaced:
        return re.findall(r"[310]", spaced[0])
    labels = re.findall(r"[胜平负]", section)
    if len(labels) >= 14:
        return [_normalize_outcome_label(label) for label in labels[:14]]
    return []


def _normalize_outcome_label(value: str) -> str:
    cleaned = value.strip()
    if cleaned in {"3", "胜", "主胜"}:
        return "3"
    if cleaned in {"1", "平", "平局"}:
        return "1"
    if cleaned in {"0", "负", "客胜"}:
        return "0"
    raise ValueError(f"Invalid outcome value: {value!r}")


def _result_from_outcome(seq: int, outcome: str) -> MatchResult:
    normalized = _normalize_outcome_label(outcome)
    if normalized == "3":
        return MatchResult(seq=seq, home_goals=1, away_goals=0, score_exact=False)
    if normalized == "1":
        return MatchResult(seq=seq, home_goals=0, away_goals=0, score_exact=False)
    return MatchResult(seq=seq, home_goals=0, away_goals=1, score_exact=False)


def _fetch_text(url: str, cache_dir: Path, max_age_seconds: int) -> str:
    import hashlib
    from datetime import datetime

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.txt"
    if cache_path.exists():
        age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if age <= max_age_seconds:
            return cache_path.read_text(encoding="utf-8", errors="replace")
    user_agent = "Mozilla/5.0 football-lottery-agent/0.1"
    if "webapi.sporttery.cn" in url:
        user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://m.sporttery.cn/mctzc/wqkj/?typeId=1",
            "User-Agent": user_agent,
        },
    )
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


def _evidence_summary(evidence: list[dict[str, object]]) -> str:
    labels = [str(item.get("label") or "") for item in evidence if item.get("label")]
    return "、".join(labels) or "-"
