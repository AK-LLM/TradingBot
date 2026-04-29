# Usage Guide — V5.3

## 1. Edit `.env`

Use `.env.example` as the template. Keep real keys only in `.env`.

Your current Canada-compatible setup can be:

```env
OPTIONS_PROVIDER=polygon
POLYGON_API_KEY=your_polygon_key_here
TRADIER_TOKEN=
KALSHI_API_KEY=
KALSHI_API_SECRET=
MARKETDATA_API_TOKEN=
METACULUS_TOKEN=
```

Tradier and Kalshi stay in the suite for future use. Leaving their fields blank should not crash the system.

## 2. Start Streamlit

```bash
streamlit run streamlit_app.py
```

Open the **Feed Health** tab after running a Shark Scan.

## 3. Start always-on local monitoring

```bash
python monitor.py --interval 60
```

Use this if Streamlit Community sleeps or if you want continuous local monitoring.

## 4. What to expect in Feed Health

Good signs:

- Polymarket: `live`
- PredictIt: `live`
- Manifold: `live`
- Stooq Market Pulse: `live`
- CFTC COT: `live`
- Options Flow: `live` once Polygon returns option rows
- News RSS: `live` if at least one RSS source parses
- Crypto Market Pulse: `live` using Binance, Kraken, or CoinGecko

Non-blocking signs:

- Metaculus: `access_limited` if anonymous API is restricted
- Options Flow: `credential_pending` if no options provider key is set
- Crypto provider internals: Binance may be blocked, but the collector falls back to Kraken/CoinGecko

Bad sign:

- `error` means a runtime bug or provider issue needs attention.

## 5. Flash Alerts

Flash alerts only promote the strongest confirmed anomalies. The system should require confirmation and sanity checks before flashing.

## 6. Action Advice

Advice scale is preserved:

- Strong Buy
- Buy
- Hold
- Sell
- Strong Sell

Use paper mode first. Do not route live orders until feed health and risk controls have been validated.
