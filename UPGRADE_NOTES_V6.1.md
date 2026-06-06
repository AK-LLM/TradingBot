# Signal Trading Platform V6.1 — Critic + Bands + Active Bridge + Calibration Loop + TA Matrix

This release closes the algorithmic-parity gap with Risk Oracle. V6.0 added
Lewis-derived data feeds and dispatch; V6.1 ports Risk Oracle's adversarial
discipline and calibration loop *into* STP so the two suites share the same
epistemological patterns. Ships in parallel with Risk Oracle V2.2.

## What's New

### `app/critic_engine.py` — adversarial critic on every constellation

Mirrors Risk Oracle's primary+critic pattern. Each constellation gets routed
to a pattern-specific critic that asks "what would make this signal wrong?"
and reports one of:
- **agrees** — confidence kept as-is
- **disagrees** — confidence multiplied by 0.6, uncertainty band widened by
  20pp, critic notes attached to the constellation
- **no_opinion** — pattern has no registered critic (degrades to agrees)

Per-pattern critics implemented for: Smart Money Positioning, Distribution
Pattern, Narrative Ignition, Geopolitical Cascade, Macro Regime Shift,
Insider Cluster, Euphoria Top, Crowded Long Warning, Sentiment Capitulation,
TA Confluence.

Mutates `state["constellations"]` in place so downstream consumers
(intelligence, decision_engine, dispatch) all see the adjusted confidence.

### Probability + uncertainty band on `Decision`

The `Decision` dataclass gains:
- `point_p` — estimated probability the thesis pays off
- `band_low` / `band_high` — uncertainty band
- `critic_verdict` — agrees / disagrees / no_opinion
- `risk_oracle_category`, `risk_oracle_point_p`, `risk_oracle_band_width`,
  `risk_oracle_sizing_mult` — captured RO context when a matching forecast
  applies

Replaces the implicit shark_score → conviction mapping. Same conviction tier
labels (HIGH/MEDIUM/LOW) for compatibility, but the underlying probability
is now explicit — required input for real Kelly sizing in IBKR-live mode.

### Active Risk Oracle bridge wiring (`decision_engine.py`)

V6.0 built `risk_oracle_bridge.reconcile_decision()` but didn't call it.
V6.1 wires it into `_calculate_sizing()`:
1. Suggested dollars are multiplied by the RO sizing multiplier
2. RO category, point_p, band width, multiplier are captured as a sidecar
   on the sizing object
3. The sidecar is read in `build_decisions()` and stamped onto the Decision
4. If RO flags high tail risk on the matching category, urgency downgrades
   from ACT_NOW to TODAY

The bridge degrades silently if Risk Oracle isn't installed — STP works
standalone exactly as before.

### `app/calibration_writeback.py` — closes the calibration loop

When STP closes a position (a realized P&L event lands in the journal
*after* a Decision's `executed_at` timestamp), the Decision is converted
to a Risk Oracle prediction record and inserted into RO's `predictions`
table at `~/.risk_oracle/calibration.db`.

This lets Risk Oracle's Brier scoring measure STP's actual track record
over time, per-narrative and per-constellation. Idempotent — every
decision is written exactly once, tracked at
`~/.signal_trading_platform/writeback.db`.

WAIT/HOLD/AVOID decisions are not written back (no committed forecast to
score). BUY/SELL-side actions are scored on realized P&L sign.

### `app/ta_matrix.py` — multi-timeframe TA confluence in Python

The 21-indicator × 6-timeframe matrix Lewis Jackson built in Pine for
TradingView, ported to Python via pandas-ta + yfinance. Runs on the symbols
STP is already tracking (current positions + symbols mentioned in recent
alerts; override with `TA_MATRIX_SYMBOLS` env var). Capped at 10 symbols
per scan to keep yfinance traffic bounded.

Indicators: EMA 9/21/50/200 crossovers, RSI, Stochastic, MACD (line +
histogram), CCI, MFI, ADX, +DI/-DI, Bollinger %B, Williams %R, ROC, ATR%,
OBV trend, SuperTrend, Momentum, SMA20, SMA50, close-vs-10-bars-ago.

Emits a Signal per (symbol, timeframe) only when ≥65% of indicators agree
on direction. The constellation engine groups multi-timeframe agreements
(by symbol+direction) into a new `TA Confluence` pattern:
- 2 timeframes agree → SCOUT
- 3 timeframes agree → STALKING
- 4+ timeframes agree → STRIKING

Soft imports — if pandas-ta or yfinance aren't installed, the module
returns []. No-op rather than failure.

## Files Changed

**New**
- `app/critic_engine.py`
- `app/calibration_writeback.py`
- `app/ta_matrix.py`
- `UPGRADE_NOTES_V6.1.md`

**Modified**
- `app/decision_engine.py` — Decision gets point_p/band/critic_verdict/ro_*
  fields; `_calculate_sizing` calls `reconcile_decision` and applies the
  sizing multiplier; `build_decisions` computes the probability band
  (widened by critic disagreement and by RO band width) and downgrades
  urgency on RO high-tail-risk flags
- `app/constellation_engine.py` — adds `_detect_ta_confluence()` pattern
  registered in `detect_all()`
- `app/platform.py` — imports critic_engine, calibration_writeback,
  ta_matrix; calls compute_ta_matrix_signals alongside lewis_feeds;
  runs critique_all after constellation detection; calls
  writeback_closed_decisions after dispatch; exposes critic_summary,
  writeback_status, ta_matrix_status as public accessors
- `app/ui.py` — title banner V5.8 → V6.1 (page title + main header)
- `requirements.txt` — adds pandas-ta, yfinance (both soft deps)
- `.env.example` — adds TA_MATRIX_SYMBOLS, TA_MATRIX_MAX_SYMBOLS, TA_MATRIX_HISTORY_DAYS
- `README.md` — rewritten for V6.1

## What Was Not Changed

- Auto-executor stays paper-only (paper_broker only — IBKR live path
  remains explicitly disabled in `decision_executor.py` from V5.7)
- No new alert/dispatch channels — V6.0 email + Telegram still the only ones
- No UI changes beyond banner — the new Decision fields are accessible
  programmatically and via the existing decision card renderer (which
  automatically displays new dataclass fields)
- All V5.4–V6.0 modules are byte-for-byte unchanged

## Migration

Drop-in compatible. No schema changes to any existing SQLite databases.

The first scan after upgrade will:
- Create `~/.signal_trading_platform/writeback.db` (local writeback ledger)
- Create or augment `~/.risk_oracle/calibration.db` (matches RO's schema
  exactly so RO can read what STP writes)

If pandas-ta or yfinance aren't installed, `ta_matrix.py` returns [] and
no `TA Confluence` constellations fire — everything else works normally.

## Cross-suite alignment

Risk Oracle V2.2 (built in parallel with this release) gets STP's
disciplines in the other direction:
- Watchlist items get lifecycle staging (SCOUT/STALKING/STRIKING/LATE)
- Probability movement is tracked for velocity/acceleration
- VIX-driven regime context modulates reconciliation + alert thresholds
- OSINT signals are noise-weighted

Ship the two releases together. The bridge between them is now load-bearing
on both sides.

## What's still NOT closed (the IBKR-live readiness gap)

V6.1 makes STP epistemologically ready for live trading. It does NOT make
it operationally ready. Before flipping `auto_execute` to IBKR, you still
need:
- Kill-switch wiring (emergency exit-all + halt-new-orders)
- Position reconciliation against IBKR's reported state on every scan
- Order rejection handling (margin, halt, after-hours, fat-finger)
- A few weeks of paper running first to populate Brier scores per
  constellation so you have empirical priors on what actually works

That's the V7.0 scope. Don't skip it.
