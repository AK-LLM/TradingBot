# Signal Trading Platform V5.1 — Usage Guide

## What this build is

V5.1 is a portable live-intelligence trading assistant. It is designed to monitor live feeds, form confirmed anomalies, run sanity checks, produce directional advice, and surface only the strongest anomalies as Flash Alerts.

It preserves the action scale:

- Strong Buy
- Buy
- Hold
- Sell
- Strong Sell

A `Reduce` action can also appear when the system detects that trimming risk is more appropriate than a full sell.

## Modes

### 1. Streamlit UI mode

Best for interactive monitoring.

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Use this for:

- Feed Health review
- Shark Alerts
- Flash Alerts
- Action Advice
- Risk dashboard
- Paper trading review

### 2. Local watchdog mode

Best for portability and background monitoring when Streamlit Community is not suitable or may sleep.

```bash
python monitor.py --interval 60
```

This runs the same live scan + flash-alert logic without the Streamlit UI. It writes to the same state file at:

```text
data/state.json
```

Then you can open Streamlit separately to view the latest state.

One-time test:

```bash
python monitor.py --once
```

Custom state file:

```bash
python monitor.py --state data/state.json --interval 60 --signals 80
```

## Recommended setup

For reliable local use, run two terminals:

Terminal 1:

```bash
python monitor.py --interval 60
```

Terminal 2:

```bash
streamlit run streamlit_app.py
```

This gives you a portable setup where the watchdog keeps monitoring even if you refresh or close the UI.

## Streamlit Community limitation

Streamlit Community is convenient, but it is not ideal for always-on event monitoring because apps may sleep or restart. For serious monitoring, use the local watchdog mode or run the app on a VPS/cloud server you control.

## Flash Alerts

Flash Alerts are intentionally strict. They only trigger when the system sees:

- SHARK-grade anomaly
- 2-feed confirmation
- feed-type diversity
- sanity checks passed
- feed reliability is acceptable
- action is directional: Buy, Strong Buy, Sell, or Strong Sell
- trend stage is Emerging or Confirmed

Default flash thresholds:

```text
flash_min_score = 82
flash_min_confidence = 78
flash_cooldown_minutes = 20
```

Use the `Flash` tab to acknowledge active alerts.

## UI auto-watchdog

The sidebar includes `UI auto-watchdog`. This runs a watchdog cycle on each Streamlit refresh. It is useful while you have the UI open, but it is not as reliable as local watchdog mode.

Recommended:

```text
UI auto-watchdog: optional
Local monitor.py: preferred
```

## Action Advice

The Action Advice tab shows the directional recommendation. The system uses confirmation + sanity + trend staging to produce:

```text
Strong Buy / Buy / Hold / Sell / Strong Sell
```

Do not act on `Hold`. It means confirmation or sanity is incomplete.

## Paper trading workflow

1. Run `Morning Radar` or keep watchdog active.
2. Review Flash Alerts first.
3. Open Shark Alerts and check evidence.
4. Confirm action advice and trend stage.
5. Use paper trade first.
6. Review orders, fills, and journal.

## API credentials

You said you will handle Options Flow, Kalshi, and PredictIt API setup. Once added, the collectors should report real health status rather than silently faking data.

Common environment variables:

```bash
export TRADIER_TOKEN="your_token"
export POLYGON_API_KEY="your_key"
```

IBKR live execution remains disabled until you explicitly select IBKR and connect TWS / IB Gateway.

## Safety rules

- Flash Alert does not place trades automatically.
- Paper/live orders still pass through risk checks.
- SAFE_MODE blocks trade-candidate promotion when live feed redundancy is insufficient.
- Kill switch halts new trades.
- No single-feed anomaly should generate action advice.

## Recommended operating cadence

Start of day:

```text
Run Morning Radar
Review Feed Reliability
Review Flash queue
Review top 3 Shark Alerts
```

During day:

```text
Run monitor.py continuously
Keep Streamlit open if possible
Acknowledge Flash Alerts after review
Paper trade only until validated
```

End of day:

```text
Review Journal
Review Flash History
Review paper fills
Score whether alerts were early, late, correct, or noise
```
