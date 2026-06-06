# V6.0 — Lewis-Derived Additions

This release adds the data sources and operational features from the Insider Routines
suite that STP didn't previously cover, plus a one-way bridge to the Risk Oracle
system. The existing V5.6/V5.7 risk and decision layers are unchanged.

## What's New

### Six new live feeds (`app/lewis_feeds.py`)

| Feed | Feed type | Noise | What it surfaces |
|---|---|---|---|
| `fed_speech_nlp` | macro_data | low | federalreserve.gov speeches classified hawkish/dovish/neutral by term-matching. Dovish → BUY signal on risk assets; hawkish → SELL. |
| `onchain_whale` | crypto_market_data | low | Whale Alert API (free tier). Large BTC/ETH/stablecoin transfers; CEX→private = accumulation BUY, private→CEX = distribution SELL. Falls back gracefully if no API key. |
| `thirteen_f_delta` | filings | low | Quarter-over-quarter 13F-HR diffs from Berkshire, Bridgewater, Renaissance, Citadel, Two Sigma, Tiger, Pershing, Soros. New positions ≥$50M emit BUY; exits emit SELL. Cache persisted at `~/.signal_trading_platform/thirteen_f_cache.json`. |
| `filtered_form4` | filings | low | EDGAR full-text search for recent Form 4 insider buys. Emits provisional BUY signals — primary-doc parsing for strict ≥$100k C-suite filtering is the documented follow-up. |
| `stock_act_trades` | filings | low | Stub for Senate/House Periodic Transaction Reports. Hook is wired; upstream parser is a future task. |
| `activist_stakes` | filings | low | 13D / 13G filings (≥5% stakes). 13D = active intent → BUY signal; 13G = passive → WATCH. |

All six follow the existing collector pattern: degrade to `[]` on any error, tag every signal with `feed_type` and `noise_level` so the constellation engine can weigh them.

### Portfolio drift checker (`app/target_drift.py`)

Reads `config/portfolio_target.json` (declared target weights) and live positions, emits one Signal per scan when any ticker has drifted ≥5pp from target. Overweight → SELL hint; underweight → BUY hint. Example file: `config/portfolio_target.example.json` — copy and edit to enable.

### Email + Telegram dispatch (`app/dispatch.py`)

Sends an email (and optional Telegram message) for every `ACT_NOW` + `HIGH`/`MEDIUM` conviction decision that hasn't been dispatched yet. Idempotent — journal-tracked so a decision is dispatched at most once. Capped at 5 dispatches per scan to prevent floods.

Required env (in `.env`):
- `GMAIL_USER` + `GMAIL_APP_PASSWORD` (16-char app password)
- Optional: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

### Risk Oracle bridge (`app/risk_oracle_bridge.py`)

Read-only reader for Risk Oracle's local SQLite databases at `~/.risk_oracle/`. Three accessors:
- `read_category_priors()` — current point_p + band for each of Risk Oracle's 8 categories
- `read_open_forecasts(limit)` — list of active watchlist items
- `reconcile_decision(decision)` — produces an AdjustmentNote with sizing multiplier and tail-risk flag

The bridge is populated on every `scan_signals()` into `state["risk_oracle_priors"]`. The decision engine doesn't read it yet — that's an explicit follow-up wiring step so you can validate the priors look right before sizing changes based on them.

### OS-native scheduler installers (`install/`)

Three pairs of scripts that register `monitor.py` as a background service:
- `schedule_mac.sh` / `uninstall_mac.sh` (launchd, runs at login, restarts on failure)
- `schedule_linux.sh` / `uninstall_linux.sh` (systemd-user preferred, crontab fallback)
- `schedule_windows.ps1` / `uninstall_windows.ps1` (Task Scheduler, runs at logon and at startup)

These replace the "you have to keep a terminal open" limitation of the old `python monitor.py --interval 60` flow.

## Files Changed

**New**
- `app/lewis_feeds.py`
- `app/target_drift.py`
- `app/dispatch.py`
- `app/risk_oracle_bridge.py`
- `config/portfolio_target.example.json`
- `install/schedule_{mac,linux,windows}.{sh,ps1}` and matching uninstall scripts
- `UPGRADE_NOTES_V6.0.md`

**Modified**
- `app/platform.py` — three additive hooks in `scan_signals()`:
  1. After `collect_live_signals()`, extend with `collect_all_lewis_feeds()` and `compute_drift_signal()`
  2. Populate `state["risk_oracle_priors"]` from the bridge
  3. After auto-execute, call `dispatch_pending_decisions()`
  Plus two new public accessors: `risk_oracle_bridge_status()` and `risk_oracle_priors()`
- `.env.example` — adds `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `GMAIL_TO`, `WHALE_ALERT_API_KEY`

## What Was Not Changed

- All V5.6 risk controls (kill switch, daily loss, drawdown, exposure caps, stop alerts, correlation groups, sector caps, VIX sizing) — untouched
- All 11 constellations and the 4-stage lifecycle — untouched
- Velocity tracker — untouched
- Decision engine logic — only inputs change; no algorithm changes
- Paper broker / IBKR broker — untouched
- All V5.4 anti-knee-jerk gates (low-noise anchor requirement, Reddit gate) — intact

## Testing

The new modules follow STP's existing graceful-degrade pattern: any collector that fails returns `[]` instead of raising, so a single bad feed cannot break a scan.

After install, the **Feed Health** tab should show the new feeds with `live`, `empty`, or `credential_pending` status. Check that:

1. `fed_speech_nlp` returns `live` (no key needed, just internet)
2. `onchain_whale` returns `credential_pending` until `WHALE_ALERT_API_KEY` is set
3. `thirteen_f_delta` returns `empty` on first run (it caches the current holdings and only emits on the *second* run when it has a prior quarter to compare against)
4. `filtered_form4` and `activist_stakes` return `live` once EDGAR's full-text search responds

Dispatch can be tested by manually running:
```python
from app.dispatch import dispatch_status, _send_email, _send_telegram
print(dispatch_status())
print(_send_email("STP test", "If you see this, email works."))
```

## What's NOT Wired In (Deliberate)

- **Decision engine doesn't yet use `risk_oracle_priors`.** That coupling is one further edit in `decision_engine.py` — adding a sizing-multiplier step after the existing VIX adjustment. Left unwired so you can verify the bridge produces sensible priors first.
- **No calibration backfill yet.** The richer integration — feeding STP's `decision_history` into Risk Oracle's `predictions` table so the Brier loop closes — is a separate task. The bridge gives you the read side; the write side needs Risk Oracle's `calibration.log_prediction()` to be called when STP closes a position.
- **STOCK Act collector is a stub.** Hook is in place; pick a stable upstream (capitoltrades.com aggregator API or housestockwatcher's data dumps) when you're ready.

## Migration

Drop-in compatible. No state migration needed. Existing `data/state.json` continues to load. The new keys in `.env.example` are all optional — STP will run without them, you just lose the dispatch + whale features.

To enable everything:
1. `cp config/portfolio_target.example.json config/portfolio_target.json` and edit
2. Add `GMAIL_USER` and `GMAIL_APP_PASSWORD` to `.env`
3. (Optional) Add `WHALE_ALERT_API_KEY` and `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
4. Run `bash install/schedule_<os>.sh` to install the background monitor
