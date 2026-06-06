"""
risk_oracle_bridge.py — V6.0 read-only bridge to the Risk Oracle suite
=======================================================================

Lets STP enrich its decisions with Risk Oracle's calibrated probabilities,
without coupling the two systems. Strictly READ-ONLY from STP's side — Risk
Oracle owns its own state and STP just reads.

Three calls exposed:

  read_category_priors() -> { category_key: {"point_p", "band_low", "band_high"} }
      Latest forecasted probability per Risk Oracle category. Pulled from
      the watchlist_history table — newest entry per watchlist item, grouped
      by category, simple mean inside a category.

  read_open_forecasts() -> List[ForecastSummary]
      Active watchlist items with their most recent forecast.

  reconcile_decision(decision_dict) -> AdjustmentNote
      For a given STP Decision, look up any forecast that matches its
      narrative/symbol and return:
        • A sizing multiplier (band_width → conviction adjustment)
        • A flag if Risk Oracle expects high tail risk on the category
        • A regime prior to feed into the constellation engine

Wire-in: in platform.py scan_signals(), before building decisions:

    from app.risk_oracle_bridge import read_category_priors
    self.state["risk_oracle_priors"] = read_category_priors()

The decision_engine can then read self.state["risk_oracle_priors"] and use it
in sizing. (decision_engine wiring is intentionally NOT done here — left as
an explicit opt-in by editing decision_engine.py once you've validated the
bridge is producing sensible numbers.)

Risk Oracle databases (all SQLite, all created automatically by Risk Oracle):
  ~/.risk_oracle/calibration.db   — predictions + Brier scores
  ~/.risk_oracle/watchlist.db     — watchlist items + history
  ~/.risk_oracle/portfolio.db     — positions tagged by category sensitivity
  ~/.risk_oracle/bets.db          — Polymarket bets log

The bridge degrades gracefully if Risk Oracle isn't installed — every reader
returns an empty result, never raises.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional


RISK_ORACLE_DIR = Path.home() / ".risk_oracle"
CALIBRATION_DB = RISK_ORACLE_DIR / "calibration.db"
WATCHLIST_DB = RISK_ORACLE_DIR / "watchlist.db"
PORTFOLIO_DB = RISK_ORACLE_DIR / "portfolio.db"


# Map Risk Oracle categories → STP narrative tags. Used so the constellation
# engine can find matching forecasts for an alert's narrative.
CATEGORY_TO_NARRATIVE = {
    "macro_financial": ["fed_policy", "macro_pulse", "rates"],
    "market_specific": ["single_name", "sector_shock", "earnings"],
    "geopolitical": ["geopolitical_shock", "energy_disruption"],
    "epidemic": ["public_health"],
    "natural_hazard": ["weather_event", "energy_supply"],
    "cyber_tech": ["cyber_incident"],
    "operational_corporate": ["corporate_event"],
    "political_regulatory": ["regulatory_shock", "election"],
}

NARRATIVE_TO_CATEGORY = {
    nar: cat for cat, nars in CATEGORY_TO_NARRATIVE.items() for nar in nars
}


@contextmanager
def _conn(db_path: Path):
    """Open a read-only-ish SQLite connection. Yields None if file is missing."""
    if not db_path.exists():
        yield None
        return
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


# --------------------------------------------------------------------------
# Public dataclasses
# --------------------------------------------------------------------------

@dataclass
class CategoryPrior:
    category: str
    point_p: float
    band_low: float
    band_high: float
    n_active_forecasts: int
    last_refreshed: str = ""

    def band_width(self) -> float:
        return self.band_high - self.band_low

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastSummary:
    watchlist_id: int
    trigger: str
    category: str
    point_p: float
    band_low: float
    band_high: float
    last_refreshed: str
    movement: Optional[float] = None  # vs prior_probability

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdjustmentNote:
    has_forecast: bool
    category: Optional[str] = None
    point_p: Optional[float] = None
    band_width: Optional[float] = None
    sizing_multiplier: float = 1.0
    high_tail_risk: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------

def read_category_priors() -> Dict[str, CategoryPrior]:
    """Aggregate the watchlist's most-recent forecasts per category."""
    with _conn(WATCHLIST_DB) as c:
        if c is None:
            return {}
        try:
            rows = c.execute("""
                SELECT category, last_probability, last_band_low, last_band_high,
                       last_refreshed_at
                FROM watchlist
                WHERE last_probability IS NOT NULL
            """).fetchall()
        except sqlite3.Error:
            return {}

    grouped: Dict[str, List[sqlite3.Row]] = {}
    for r in rows:
        grouped.setdefault(r["category"], []).append(r)

    out: Dict[str, CategoryPrior] = {}
    for cat, items in grouped.items():
        ps = [r["last_probability"] for r in items if r["last_probability"] is not None]
        lows = [r["last_band_low"] for r in items if r["last_band_low"] is not None]
        highs = [r["last_band_high"] for r in items if r["last_band_high"] is not None]
        last_refresh = max((r["last_refreshed_at"] or "") for r in items)
        if not ps:
            continue
        out[cat] = CategoryPrior(
            category=cat,
            point_p=sum(ps) / len(ps),
            band_low=sum(lows) / len(lows) if lows else 0.0,
            band_high=sum(highs) / len(highs) if highs else 1.0,
            n_active_forecasts=len(items),
            last_refreshed=last_refresh,
        )
    return out


def read_open_forecasts(limit: int = 50) -> List[ForecastSummary]:
    """List all watchlist items with their latest forecast for the UI."""
    with _conn(WATCHLIST_DB) as c:
        if c is None:
            return []
        try:
            rows = c.execute("""
                SELECT id, trigger, category, last_probability,
                       last_band_low, last_band_high, previous_probability,
                       last_refreshed_at
                FROM watchlist
                WHERE last_probability IS NOT NULL
                ORDER BY last_refreshed_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        except sqlite3.Error:
            return []

    out: List[ForecastSummary] = []
    for r in rows:
        movement = None
        if r["previous_probability"] is not None and r["last_probability"] is not None:
            movement = r["last_probability"] - r["previous_probability"]
        out.append(ForecastSummary(
            watchlist_id=r["id"],
            trigger=r["trigger"],
            category=r["category"],
            point_p=r["last_probability"] or 0.0,
            band_low=r["last_band_low"] or 0.0,
            band_high=r["last_band_high"] or 1.0,
            last_refreshed=r["last_refreshed_at"] or "",
            movement=movement,
        ))
    return out


def read_brier_weights() -> Dict[str, Dict[str, float]]:
    """Per-category mean Brier scores. Lower = better calibrated."""
    with _conn(CALIBRATION_DB) as c:
        if c is None:
            return {}
        try:
            rows = c.execute("""
                SELECT category,
                       AVG(brier_primary)    AS bp,
                       AVG(brier_critic)     AS bc,
                       AVG(brier_reconciled) AS br,
                       COUNT(*) AS n
                FROM predictions
                WHERE resolved = 1
                GROUP BY category
            """).fetchall()
        except sqlite3.Error:
            return {}
    return {
        r["category"]: {
            "n": int(r["n"] or 0),
            "brier_primary": r["bp"] or 0.0,
            "brier_critic": r["bc"] or 0.0,
            "brier_reconciled": r["br"] or 0.0,
        }
        for r in rows
    }


# --------------------------------------------------------------------------
# Decision reconciliation
# --------------------------------------------------------------------------

def reconcile_decision(decision: Dict[str, Any]) -> AdjustmentNote:
    """Given a Decision dict, find a matching forecast and return an
    adjustment recommendation.

    Sizing multiplier logic:
      band_width ≤ 0.15  → 1.0 (forecast is precise — trust it)
      band_width ≤ 0.30  → 0.75 (medium uncertainty — trim 25%)
      band_width > 0.30   → 0.50 (wide uncertainty — half size)

    High tail risk flag triggers when point_p × band_high suggests a
    category likely to spill over (uses Risk Oracle's contagion philosophy
    in spirit, though contagion itself is computed inside Risk Oracle).
    """
    narrative = (decision.get("narrative") or "").lower().replace(" ", "_")
    category = NARRATIVE_TO_CATEGORY.get(narrative)
    if not category:
        return AdjustmentNote(has_forecast=False)

    priors = read_category_priors()
    prior = priors.get(category)
    if not prior:
        return AdjustmentNote(has_forecast=False)

    band_width = prior.band_width()
    if band_width <= 0.15:
        mult = 1.0
        note = f"{category} forecast tight ({prior.point_p:.0%}, ±{band_width/2:.0%})"
    elif band_width <= 0.30:
        mult = 0.75
        note = f"{category} forecast medium uncertainty — trim 25%"
    else:
        mult = 0.50
        note = f"{category} forecast wide uncertainty — half size"

    high_tail = prior.point_p > 0.4 and band_width > 0.25

    return AdjustmentNote(
        has_forecast=True,
        category=category,
        point_p=prior.point_p,
        band_width=band_width,
        sizing_multiplier=mult,
        high_tail_risk=high_tail,
        notes=[note],
    )


# --------------------------------------------------------------------------
# Quick check — used by UI/health panel
# --------------------------------------------------------------------------

def bridge_status() -> Dict[str, Any]:
    """Are Risk Oracle's DBs visible and queryable?"""
    return {
        "risk_oracle_dir_exists": RISK_ORACLE_DIR.exists(),
        "calibration_db": CALIBRATION_DB.exists(),
        "watchlist_db": WATCHLIST_DB.exists(),
        "portfolio_db": PORTFOLIO_DB.exists(),
        "category_priors_loaded": len(read_category_priors()),
        "open_forecasts": len(read_open_forecasts(limit=200)),
    }
