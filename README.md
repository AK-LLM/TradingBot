# Signal Trading Platform V5.2 — Flexible Options Provider Build

This build keeps Tradier available but makes Polygon/Massive the default options-flow provider.
It also includes `.env.example` and a blank/template `.env` so local API configuration is obvious.

## Quick start

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Portable watchdog mode:

```bash
python monitor.py --interval 60
```

## API configuration

Edit `.env` in the project root. Do not commit real keys to GitHub.

Default options-flow provider:

```env
OPTIONS_PROVIDER=polygon
POLYGON_API_KEY=lFKvsbqX5ZNGA2JephgNr4Z_OTqNHsYh
```

Optional alternatives:

```env
MARKETDATA_API_TOKEN=your_marketdata_app_token
TRADIER_TOKEN=your_tradier_token
```

Provider priority is:
1. the provider selected by `OPTIONS_PROVIDER`
2. Polygon
3. MarketData.app
4. Tradier

Tradier is left in place but disabled unless `TRADIER_TOKEN` is provided.
