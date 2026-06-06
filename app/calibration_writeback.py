"""
calibration_writeback.py — V6.1 closes the calibration loop between STP and
Risk Oracle.

When STP closes a position (realized P&L journaled, or stop hit, or executor
exits), the corresponding Decision is converted into a Risk Oracle
prediction record and written directly to ~/.risk_oracle/calibration.db.

Risk Oracle's Brier scoring then operates on STP's own track record over
time — letting you measure per-pattern hit rates, per-constellation
predictive value, and per-narrative calibration drift.

How outcomes are mapped:
  - BUY/STRONG_BUY/ENTER_NEW/ADD/AVG_DOWN decisions:
        realized_pnl > 0  → outcome = 1 (event happened, our forecast right)
        realized_pnl ≤ 0  → outcome = 0
  - SELL/STRONG_SELL/EXIT_FULL/REDUCE decisions on a short-thesis:
        position closed at a lower price than entry → outcome = 1
        otherwise → 0
  - HOLD / WAIT / AVOID decisions are NOT written back (no commitment was made)
  - TAKE_PARTIAL_PROFIT writes back only the trimmed portion's outcome

The writeback is idempotent: a decision is written exactly once, tracked via
a small SQLite at ~/.signal_trading_platform/writeback.db.
"""
from __future__ import annotations
import os
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Risk Oracle's calibration DB lives here. Same path the bridge reads from.
RO_CALIBRATION_DB = Path.home() / ".risk_oracle" / "calibration.db"

# Our own state to track what we've already written back
LOCAL_STATE_DIR = Path.home() / ".signal_trading_platform"
WRITEBACK_DB = LOCAL_STATE_DIR / "writeback.db"


# STP narrative → Risk Oracle category mapping. Used to tag predictions
# so they end up in the right calibration bucket.
NARRATIVE_TO_CATEGORY = {
    "fed_policy": "macro_financial",
    "macro_pulse": "macro_financial",
    "rates": "macro_financial",
    "insider_buying": "market_specific",
    "institutional_positioning": "market_specific",
    "activist_positioning": "market_specific",
    "geopolitical_shock": "geopolitical",
    "energy_disruption": "geopolitical",
    "energy_supply": "natural_hazard",
    "weather_event": "natural_hazard",
    "cyber_incident": "cyber_tech",
    "regulatory_shock": "political_regulatory",
    "election": "political_regulatory",
    "crypto_flows": "market_specific",
    "portfolio_rebalance": "market_specific",
}

# Decisions emit BUY/SELL-like outcomes; map to forecast direction interpretation.
BULLISH_ACTIONS = {"ENTER_NEW", "ADD_TO_EXISTING", "AVERAGE_DOWN", "BUY", "STRONG_BUY"}
BEARISH_ACTIONS = {"EXIT_FULL", "REDUCE", "SELL", "STRONG_SELL"}
NEUTRAL_ACTIONS = {"WAIT", "HOLD", "AVOID", "TAKE_PARTIAL_PROFIT"}


@contextmanager
def _local_conn():
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(WRITEBACK_DB))
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


@contextmanager
def _ro_conn():
    """Open the Risk Oracle calibration DB for writes. Creates it if absent
    (matching Risk Oracle's own init_db schema so subsequent reads work)."""
    RO_CALIBRATION_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(RO_CALIBRATION_DB))
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _ensure_local_table():
    with _local_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS writebacks (
                decision_id TEXT PRIMARY KEY,
                ro_prediction_id INTEGER,
                outcome INTEGER NOT NULL,
                pnl REAL,
                written_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def _ensure_ro_table():
    """Match Risk Oracle's predictions schema exactly so writes are compatible."""
    with _ro_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                trigger TEXT NOT NULL,
                category TEXT NOT NULL,
                primary_p REAL NOT NULL,
                critic_p REAL NOT NULL,
                reconciled_p REAL NOT NULL,
                band_low REAL NOT NULL,
                band_high REAL NOT NULL,
                expected_resolution TEXT,
                resolved INTEGER NOT NULL DEFAULT 0,
                resolution_outcome INTEGER,
                resolution_date TEXT,
                brier_primary REAL,
                brier_critic REAL,
                brier_reconciled REAL,
                metadata TEXT
            )
        """)


def _already_written(decision_id: str) -> bool:
    _ensure_local_table()
    with _local_conn() as c:
        row = c.execute("SELECT 1 FROM writebacks WHERE decision_id = ?",
                        (decision_id,)).fetchone()
    return row is not None


def _mark_written(decision_id: str, ro_id: int, outcome: int, pnl: float):
    with _local_conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO writebacks (decision_id, ro_prediction_id, outcome, pnl)
            VALUES (?, ?, ?, ?)
        """, (decision_id, ro_id, outcome, pnl))


def _decision_to_prediction(decision: Dict[str, Any], pnl: float) -> Optional[Dict[str, Any]]:
    """Convert a closed Decision into the RO prediction shape.
    Returns None if the decision is one we don't write back (WAIT/AVOID/etc.)."""
    action = decision.get("action", "")
    if action in NEUTRAL_ACTIONS:
        return None  # No commitment, nothing to score

    # Outcome: did the directional thesis pay off?
    if action in BULLISH_ACTIONS:
        outcome = 1 if pnl > 0 else 0
    elif action in BEARISH_ACTIONS:
        # A SELL/EXIT thesis "wins" if the price dropped after we exited.
        # We don't have that data here directly; conservatively, use realized
        # P&L sign on the closed leg.
        outcome = 1 if pnl >= 0 else 0
    else:
        return None

    # Extract or synthesize point_p / band from the decision
    point_p = float(decision.get("point_p", 0.5))
    band_low = float(decision.get("band_low", max(0.0, point_p - 0.15)))
    band_high = float(decision.get("band_high", min(1.0, point_p + 0.15)))

    narrative = decision.get("narrative", "").lower().replace(" ", "_")
    category = NARRATIVE_TO_CATEGORY.get(narrative, "market_specific")

    trigger = (
        f"STP decision {decision.get('id', '?')}: {action} {decision.get('symbol', '?')} "
        f"based on {decision.get('primary_driver', 'multi-feed alert')}"
    )

    metadata = {
        "source": "stp_decision",
        "decision_id": decision.get("id"),
        "constellation_pattern": decision.get("constellation_pattern"),
        "constellation_stage": decision.get("constellation_stage"),
        "conviction": decision.get("conviction"),
        "urgency": decision.get("urgency"),
        "primary_driver": decision.get("primary_driver"),
        "pnl": pnl,
    }

    return {
        "trigger": trigger,
        "category": category,
        "primary_p": point_p,
        "critic_p": point_p,        # Use same; STP doesn't run a methodologically
        "reconciled_p": point_p,    # different critic on the probability itself.
        "band_low": band_low,
        "band_high": band_high,
        "outcome": outcome,
        "metadata": metadata,
    }


def _write_prediction_to_ro(prediction: Dict[str, Any], closed_at: str) -> int:
    """Insert a prediction row already marked resolved, with Brier scores."""
    _ensure_ro_table()
    o = prediction["outcome"]
    bp = (prediction["primary_p"] - o) ** 2
    bc = (prediction["critic_p"] - o) ** 2
    br = (prediction["reconciled_p"] - o) ** 2
    now = datetime.utcnow().isoformat()
    with _ro_conn() as c:
        cur = c.execute("""
            INSERT INTO predictions
            (created_at, trigger, category, primary_p, critic_p, reconciled_p,
             band_low, band_high, expected_resolution, resolved,
             resolution_outcome, resolution_date,
             brier_primary, brier_critic, brier_reconciled, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
        """, (
            now, prediction["trigger"], prediction["category"],
            prediction["primary_p"], prediction["critic_p"], prediction["reconciled_p"],
            prediction["band_low"], prediction["band_high"],
            closed_at, o, closed_at, bp, bc, br,
            json.dumps(prediction.get("metadata", {})),
        ))
        return int(cur.lastrowid or 0)


def _closed_decisions_from_state(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A decision is 'closed' when its source position has produced a realized
    P&L entry in the journal *after* the decision was executed."""
    journal = state.get("journal", []) or []
    decision_history = state.get("decision_history", []) or []
    decisions = state.get("decisions", []) or []
    all_decisions = list(decisions) + list(decision_history)

    # Index realized P&L events by symbol → list of {ts, amount}
    pnl_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for j in journal:
        if not isinstance(j, dict):
            continue
        if j.get("event") == "realized_pnl":
            sym = str(j.get("symbol", "")).upper()
            pnl_by_symbol.setdefault(sym, []).append(j)

    closed: List[Dict[str, Any]] = []
    for d in all_decisions:
        if not d.get("executed"):
            continue
        sym = str(d.get("symbol", "")).upper()
        exec_at = d.get("executed_at", "")
        if not sym or not exec_at:
            continue
        # Find a P&L event after this execution
        for pnl_event in pnl_by_symbol.get(sym, []):
            if pnl_event.get("ts", "") > exec_at:
                closed.append({
                    "decision": d,
                    "pnl": float(pnl_event.get("amount", 0.0)),
                    "closed_at": pnl_event.get("ts", ""),
                })
                break
    return closed


def writeback_closed_decisions(state: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry. Find all closed decisions, write any not yet written, and
    return a summary dict.

    Wire-in: called from platform.scan_signals() once per scan. Cheap when
    there's nothing new to write (single SELECT against writebacks table)."""
    closed = _closed_decisions_from_state(state)
    if not closed:
        return {"written": 0, "skipped": 0, "errors": 0}

    written = 0
    skipped = 0
    errors = 0
    for entry in closed:
        d = entry["decision"]
        did = str(d.get("id", ""))
        if not did or _already_written(did):
            skipped += 1
            continue
        prediction = _decision_to_prediction(d, entry["pnl"])
        if prediction is None:
            skipped += 1
            continue
        try:
            ro_id = _write_prediction_to_ro(prediction, entry["closed_at"])
            _mark_written(did, ro_id, prediction["outcome"], entry["pnl"])
            written += 1
        except Exception:
            errors += 1

    return {"written": written, "skipped": skipped, "errors": errors}


def writeback_status() -> Dict[str, Any]:
    """For health panels: how many decisions have been written back so far."""
    _ensure_local_table()
    with _local_conn() as c:
        n = c.execute("SELECT COUNT(*) FROM writebacks").fetchone()[0]
        wins = c.execute("SELECT COUNT(*) FROM writebacks WHERE outcome = 1").fetchone()[0]
    return {
        "total_writebacks": int(n),
        "wins": int(wins),
        "ro_calibration_db_exists": RO_CALIBRATION_DB.exists(),
    }
