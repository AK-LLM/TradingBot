# Signal Trading Platform — V5.3 Live Feed Patch

This build keeps the original shark-radar concept intact while cleaning up live feed behavior.

## What changed in V5.3

- Kalshi and Tradier are **kept in the suite** for later use.
- Missing Tradier/Kalshi credentials are now treated meaningfully, not as broken bot logic.
- Manifold endpoint was fixed to avoid the bad request caused by fragile sort parameters.
- SEC now sends a proper User-Agent and falls back to the SEC current-filings Atom feed if the company ticker endpoint is blocked.
- News RSS now skips malformed feeds instead of failing the whole news collector.
- Binance 451/region blocking is handled by falling back to Kraken and CoinGecko.
- Feed Reliability now distinguishes runtime errors from credential/access/geo limitations.
- Polygon/Massive remains the default options-flow provider.

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

SIGNAL_BOT_USER_AGENT=signal-trading-platform/5.3 contact:your_email@example.com
SEC_USER_AGENT=signal-trading-platform/5.3 contact:your_email@example.com
```

Do **not** commit `.env` to GitHub.

## Feed status meanings

| Status | Meaning |
|---|---|
| `live` | Collector returned live items. |
| `empty` | Endpoint responded but no qualifying items were found. |
| `credential_pending` | Feed is wired but needs a token/API key to return data. |
| `access_limited` | Provider blocked/limited the request; not treated as a bot crash. |
| `geo_blocked` | Provider is unavailable in your region; fallback is attempted where available. |
| `error` | Runtime error that needs attention. |

## Run UI

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Run local watchdog

```bash
python monitor.py --interval 60
```

## Active confirmation pool

The system looks for confirmation across feed categories, not just individual providers:

- Prediction/probability: Polymarket, PredictIt, Manifold, Kalshi, Metaculus when available
- Options/positioning: Polygon, MarketData.app, Tradier when configured
- Market movement: Stooq
- Crypto movement: Binance if available, otherwise Kraken/CoinGecko fallback
- News/macro: RSS/news collector
- Filings/positioning: SEC and CFTC

Action advice remains: **Strong Buy, Buy, Hold, Sell, Strong Sell**.
