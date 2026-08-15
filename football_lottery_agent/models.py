from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


Outcome = str


@dataclass(frozen=True)
class Scoreline:
    home_goals: int
    away_goals: int
    probability: float

    @property
    def text(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"


@dataclass(frozen=True)
class Odds:
    home: float
    draw: float
    away: float

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Odds":
        return cls(home=float(raw["home"]), draw=float(raw["draw"]), away=float(raw["away"]))


@dataclass(frozen=True)
class Signals:
    home_form: float = 0.5
    away_form: float = 0.5
    home_motivation: float = 0.5
    away_motivation: float = 0.5
    home_injury_impact: float = 0.0
    away_injury_impact: float = 0.0
    schedule_pressure_home: float = 0.0
    schedule_pressure_away: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Signals":
        if not raw:
            return cls()
        values = {field_name: _clamp01(float(raw.get(field_name, default))) for field_name, default in cls().as_dict().items()}
        return cls(**values)

    def as_dict(self) -> dict[str, float]:
        return {
            "home_form": self.home_form,
            "away_form": self.away_form,
            "home_motivation": self.home_motivation,
            "away_motivation": self.away_motivation,
            "home_injury_impact": self.home_injury_impact,
            "away_injury_impact": self.away_injury_impact,
            "schedule_pressure_home": self.schedule_pressure_home,
            "schedule_pressure_away": self.schedule_pressure_away,
        }


@dataclass(frozen=True)
class Match:
    seq: int
    kickoff: datetime
    league: str
    home: str
    away: str
    odds: Odds
    signals: Signals = field(default_factory=Signals)
    notes: tuple[str, ...] = ()
    sources: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Match":
        return cls(
            seq=int(raw["seq"]),
            kickoff=datetime.fromisoformat(raw["kickoff"]),
            league=str(raw["league"]),
            home=str(raw["home"]),
            away=str(raw["away"]),
            odds=Odds.from_dict(raw["odds"]),
            signals=Signals.from_dict(raw.get("signals")),
            notes=tuple(str(note) for note in raw.get("notes", [])),
            sources=dict(raw.get("sources", {})),
        )


@dataclass(frozen=True)
class Issue:
    issue: str
    matches: tuple[Match, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Issue":
        matches = tuple(Match.from_dict(item) for item in raw["matches"])
        if len(matches) != 14:
            raise ValueError(f"Expected 14 matches, got {len(matches)}.")
        return cls(issue=str(raw["issue"]), matches=matches, metadata=dict(raw.get("metadata", {})))


@dataclass(frozen=True)
class Prediction:
    match: Match
    probabilities: dict[Outcome, float]
    picks: tuple[Outcome, ...]
    scorelines: tuple[Scoreline, ...]
    confidence: float
    risk: str
    reasons: tuple[str, ...]
    selection_scores: dict[Outcome, float] = field(default_factory=dict)
    original_picks: tuple[Outcome, ...] = ()
    dixon_coles_probabilities: dict[Outcome, float] = field(default_factory=dict)
    dixon_coles_quality: str = ""
    dixon_coles_quality_score: float = 0.0
    market_probabilities: dict[Outcome, float] = field(default_factory=dict)
    blend_weights: dict[str, float] = field(default_factory=dict)
    budget_adjusted: bool = False
    budget_forced_single: bool = False
    budget_removed_picks: tuple[Outcome, ...] = ()
    draw_guard: bool = False
    tactical_draw: bool = False
    tactical_draw_score: float = 0.0
    tactical_draw_evidence: tuple[str, ...] = ()

    @property
    def pick_text(self) -> str:
        return "/".join(self.picks)

    @property
    def analysis_picks(self) -> tuple[Outcome, ...]:
        """Return the model selection before whole-ticket budget compression."""
        return self.original_picks or self.picks

    @property
    def analysis_pick_text(self) -> str:
        return "/".join(self.analysis_picks)


@dataclass(frozen=True)
class TicketPlan:
    issue: Issue
    predictions: tuple[Prediction, ...]
    choose9_keep: tuple[int, ...]
    choose9_drop: tuple[int, ...]


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))
