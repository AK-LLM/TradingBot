# Signal Trading Platform — V6.1

The Decision Engine + Critic + Calibration Loop release. Builds on the V5.x
shark-radar foundation with an adversarial critic on every constellation,
explicit probability bands on every Decision, an active two-way bridge to the
Risk Oracle suite, and a multi-timeframe TA matrix that mirrors Lewis
Jackson's MAX indicator stack in pure Python (no TradingView subscription).

## What's in V6.1 (this release)

- **`app/critic_engine.py`** — adversarial counter-check on each detected
  constellation. Pattern-specific critics (Smart Money Positioning, Distribution
  Pattern, Narrative Ignition, Geopolitical Cascade, Insider Cluster, Euphoria
  Top, Crowded Long Warning, Sentiment Capitulation) each ask "what would
  make this signal wrong?" and adjust confidence + widen the uncertainty band
  if disagreement is found.
- **`app/calibration_writeback.py`** — closes the loop. Every closed Decision
  is written back to Risk Oracle's `predictions` table so its Brier-scoring
  calibration loop measures STP's actual track record per-narrative,
  per-constellation, per-conviction.
- **`app/ta_matrix.py`** — the 21-indicator × 6-timeframe matrix in Python
  (pandas-ta + yfinance). Emits Signals at confluence > 65%; constellation
  engine groups multi-timeframe agreements as a new `TA Confluence` pattern.
- **Active Risk Oracle bridge wiring** — `decision_engine._calculate_sizing()`
  now calls `risk_oracle_bridge.reconcile_decision()` and multiplies suggested
  dollars by the RO sizing multiplier. High tail risk on the matching RO
  category downgrades urgency from ACT_NOW to TODAY.
- **Probability bands on Decisions** — `Decision.point_p`, `band_low`,
  `band_high`. Replaces the implicit shark_score → conviction mapping;
  enables real Kelly sizing in IBKR-live mode.

## What V6.0 added (still in this build)

- **`app/lewis_feeds.py`** — six new public collectors:
  filtered Form 4 insider buys, 13F fund-delta tracking, on-chain whale
  transfers (CEX↔private), Fed-speech NLP tilt, STOCK Act stub, and 13D/13G
  activist stakes.
- **`app/target_drift.py`** — Janet equivalent. Compares current portfolio
  vs `config/portfolio_target.json`; emits a single drift signal per scan.
- **`app/dispatch.py`** — email + Telegram delivery for high-conviction
  decisions. Idempotent via local dispatch ledger.
- **`app/risk_oracle_bridge.py`** — bidirectional bridge to the Risk Oracle
  suite. V6.1 makes its `reconcile_decision()` function actually load-bearing.
- **`install/`** — OS-native schedulers (macOS launchd, Linux systemd-user /
  crontab fallback, Windows Task Scheduler) for running the platform headless.

## Setup

Create or edit `.env` in the project root. Use `.env.example` as the template.

Minimum recommended setup:

```env
OPTIONS_PROVIDER=polygon
POLYGON_API_KEY=your_polygon_key_here

TRADIER_TOKEN=
KALSHI_API_KEY=
KALSHI_API_SECRET=
MARKETDATA_API_TOKEN=
METACULUS_TOKEN=

# V6.0 additions
WHALE_ALERT_API_KEY=        # optional; on-chain whale collector falls back gracefully

# V6.1 TA matrix tuning (all optional)
TA_MATRIX_SYMBOLS=          # comma list, defaults to your held + recently-alerted symbols
TA_MATRIX_MAX_SYMBOLS=10
TA_MATRIX_HISTORY_DAYS=180

SIGNAL_BOT_USER_AGENT=signal-trading-platform/6.1 contact:your_email@example.com
SEC_USER_AGENT=signal-trading-platform/6.1 contact:your_email@example.com
```

Do **not** commit `.env` to GitHub.

## Run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Run as a background service

```bash
# macOS
bash install/schedule_mac.sh

# Linux
bash install/schedule_linux.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File install\schedule_windows.ps1
```

## Action advice

Decisions still come out as one of:
**ENTER_NEW, ADD, AVERAGE_DOWN, HOLD, TAKE_PARTIAL_PROFIT, REDUCE, EXIT_FULL,
WAIT, AVOID** — with conviction (HIGH/MEDIUM/LOW), urgency (ACT_NOW/TODAY/
THIS_WEEK/WATCH), and a sizing block. V6.1 adds explicit probability + band
so you can size with real Kelly when live.

## Feed status meanings

| Status | Meaning |
|---|---|
| `live` | Collector returned live items. |
| `empty` | Endpoint responded but no qualifying items were found. |
| `credential_pending` | Feed is wired but needs a token/API key to return data. |
| `access_limited` | Provider blocked/limited the request; not treated as a bot crash. |
| `geo_blocked` | Provider is unavailable in your region; fallback is attempted where available. |
| `error` | Runtime error that needs attention. |

## Per-version upgrade notes

Each release ships a focused upgrade-notes file:
- `UPGRADE_NOTES_V5.4.md` — macro/event intelligence expansion
- `UPGRADE_NOTES_V5.5.md` — velocity tracker + intelligence engine
- `UPGRADE_NOTES_V5.6.md` — risk intelligence + sell-side constellations
- `UPGRADE_NOTES_V6.0.md` — Lewis-derived feeds + Risk Oracle bridge + dispatch
- `UPGRADE_NOTES_V6.1.md` — critic + bands + active bridge + calibration loop + TA matrix
