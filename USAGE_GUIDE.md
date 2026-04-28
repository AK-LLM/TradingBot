# Signal Trading Platform V5.2 Usage Guide

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Configure API keys

A blank/template `.env` file is included in the project root.
Open it and fill in only the keys you currently have.

Recommended starting config:

```env
OPTIONS_PROVIDER=polygon
POLYGON_API_KEY=your_polygon_or_massive_key
MARKETDATA_API_TOKEN=
TRADIER_TOKEN=
KALSHI_API_KEY=
KALSHI_API_SECRET=
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
```

### Options providers

- **Polygon/Massive**: default and recommended first provider.
- **MarketData.app**: optional backup provider if you add `MARKETDATA_API_TOKEN`.
- **Tradier**: still supported, but disabled unless `TRADIER_TOKEN` is provided.

Set the preferred provider:

```env
OPTIONS_PROVIDER=polygon
# or
OPTIONS_PROVIDER=marketdata
# or
OPTIONS_PROVIDER=tradier
```

The suite will try the selected provider first, then fail over to the other configured options providers.

## 3. Run the UI

```bash
streamlit run streamlit_app.py
```

Use the UI for:

- Feed Health
- Shark Radar
- Flash Alerts
- Risk Dashboard
- Paper/live execution review

## 4. Run the portable watchdog

For local installs, VPS, or cases where Streamlit Community cannot keep background work alive:

```bash
python monitor.py --interval 60
```

This runs monitoring independently of the Streamlit UI.

## 5. Action advice scale

The system preserves the action spectrum:

- Strong Buy
- Buy
- Hold
- Sell
- Strong Sell

Advice is only generated after confirmation and sanity checks.

## 6. Flash alerts

Flash alerts are intentionally strict. They fire only for the strongest confirmed anomalies.

Expected behavior:

- Signal detected
- Two-feed confirmation checked
- Feed-type diversity checked
- Sanity checks applied
- Flash alert generated only if the event is high-confidence

## 7. Safety notes

- Never commit your real `.env` to GitHub.
- Use paper mode first.
- Keep IBKR live routing disabled until feed health and risk behavior are verified.
- Tradier does not work without a token; leaving `TRADIER_TOKEN=` blank disables it cleanly.
