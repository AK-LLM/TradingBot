# Signal Trading Platform V5.1

Live-only macro/event intelligence platform with:

- 2-feed confirmation
- feed-type diversity checks
- sanity validation
- Strong Buy / Buy / Hold / Sell / Strong Sell action advice
- Flash Alerts for strongest confirmed anomalies
- Streamlit UI
- local CLI watchdog for portable monitoring
- paper trading and IBKR routing path
- $10K risk framework

## Run UI

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Run portable watchdog

```bash
python monitor.py --interval 60
```

## Test one cycle

```bash
python monitor.py --once
```

See `USAGE_GUIDE.md` for detailed usage.
