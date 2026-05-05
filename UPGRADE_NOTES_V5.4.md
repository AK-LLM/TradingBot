# V5.4 Upgrade Notes — Surgical Feed Additions

This patch adds **5 new feeds** without removing any existing functionality. All existing
feeds and behavior are preserved.

## What's New

### 1. SEDI Canadian Insider Trades (low noise)
- **Source**: SEDI public disclosure summaries
- **Type**: `canada_filings`
- **What it does**: Detects insider activity clusters for Canadian-listed equities (.TO/.V/.CN)
- **Noise level**: LOW — regulatory filings are authoritative
- **No API key required**

### 2. StatCan Economic Pulse (low noise)
- **Source**: Statistics Canada Web Data Service (WDS) API
- **Type**: `canada_macro`
- **What it does**: Pulls headline Canadian economic indicators (CPI, unemployment, GDP, retail trade) and emits directional signals based on month-over-month changes
- **Noise level**: LOW — government statistics
- **No API key required**

### 3. Volatility Regime (low noise)
- **Source**: FRED (with Stooq fallback for VIX)
- **Type**: `regime_context`
- **What it does**: Provides VIX and high-yield credit spread regime context
- **Noise level**: LOW
- **Important**: This feed produces **REGIME CONTEXT** signals tagged `is_regime_context: true`. These do NOT trigger trades on their own. The intelligence engine uses them as modifiers when interpreting other signals.
- **API key**: Optional `FRED_API_KEY` for richer history; falls back to Stooq for VIX

### 4. Google Trends Attention (medium noise)
- **Source**: Google Trends (via pytrends if installed, RSS fallback otherwise)
- **Type**: `attention`
- **What it does**: Detects search-attention spikes for narrative-aligned keywords (uranium, AI chips, lithium, etc.)
- **Noise level**: MEDIUM
- **Optional dependency**: `pip install pytrends` for richer signal; degrades gracefully without it

### 5. Reddit Crowd Sentiment (high noise — with safeguards)
- **Source**: Reddit public JSON endpoints across r/wallstreetbets, r/stocks, r/investing, r/options, r/SecurityAnalysis
- **Type**: `crowd_sentiment`
- **What it does**: Aggregates ticker mentions and naive sentiment across subreddits
- **Noise level**: HIGH
- **Anti-knee-jerk safeguards baked in**:
  1. **Confirmation gate**: requires ≥10 mentions before emitting any signal
  2. **Subreddit diversity gate**: requires mentions across ≥2 subreddits (not just one echo chamber)
  3. **Age floor**: only counts posts >2 hours old (lets initial reaction settle)
  4. **Upvote floor**: posts must have ≥25 upvotes (filters spam/brigading)
  5. **Confidence cap**: confidence is capped at 0.65 (Reddit can never be a high-confidence signal alone)
  6. **Default direction is WATCH** unless very strong consensus
- **No API key required**

## Intelligence Engine Updates

The `TrendIntelligenceEngine.advise()` method now applies two new gates:

### Gate 1: `not_only_high_noise`
If the ONLY signals contributing to an alert are high-noise (e.g., Reddit-only), the action is forced to HOLD with the message:

> *"Signal cluster is dominated by high-noise sources (e.g., social sentiment) without confirmation from authoritative feeds. Knee-jerk gate active."*

This is the **anti-knee-jerk safeguard** specifically designed to prevent the engine from acting on pure social media chatter.

### Gate 2: `has_low_noise_anchor`
At least one contributing signal must be from a low-noise source (regulatory filings, macro data, regime context, etc.) for any action recommendation. If no low-noise anchor exists, the action is HOLD with the message:

> *"No low-noise anchor signal (regulatory, macro, or filings). Holding for confirmation."*

### Regime Context Modifiers
When the engine detects an active VIX regime, it modifies recommendations:
- **Panic regime**: STRONG_BUY signals are downgraded to BUY (be more cautious in chaos)
- **Complacent regime**: SELL signals carry a "short squeeze possible" note

### Enriched Confirmation Summary
The summary now includes a noise breakdown like `noise[L:2/M:1/H:0]` so you can see at a glance how authoritative the contributing signal mix is. Example:

> `3 source(s) | 3 feed type(s) | noise[L:2/M:1/H:0] | regime:normal: canada_macro, filings, prediction_market`

## What Did NOT Change

- ✅ All 19 existing feeds remain in place (Polymarket, Kalshi, PredictIt, Manifold, Metaculus, SEC, CFTC, news, options, FRED, Treasury, EIA, NOAA, grid, shipping, Bank of Canada, Stooq, crypto, GDELT)
- ✅ All existing intelligence engine logic remains
- ✅ Kalshi/PredictIt are kept in the registry even though you can't use them (per your request)
- ✅ Paper broker and IBKR broker integration unchanged
- ✅ All existing UI screens, sanity checks, watchdog, and risk modules untouched

## Geographic Notes

For your Canadian usage:
- **SEDI**, **StatCan**, **Bank of Canada** are all CA-native and unrestricted
- **Volatility regime** uses US data (VIX, US HY spreads) but it's the global benchmark for risk regime
- **Google Trends** is global; the curated narrative keywords are equity-aligned regardless of jurisdiction
- **Reddit** is global; mentions are not filtered by user geography
- **Kalshi/PredictIt** remain US-only — they will appear in your registry as `geo_blocked` but won't break anything

## Files Changed

- **NEW**: `app/extended_feeds.py` (the 5 new collectors + noise tagging)
- **MODIFIED**: `app/live_feeds.py` (registry entries + dispatcher hook)
- **MODIFIED**: `app/intelligence.py` (noise-aware gates + regime modifiers)
- **MODIFIED**: `requirements.txt` (added optional pytrends)

## Total Feed Count

- Before: 19 feeds
- After: 24 feeds (19 original + 5 new)

## Optional Setup

For the best Google Trends signal, install pytrends:

```bash
pip install pytrends
```

Without it, Google Trends falls back to a simpler RSS-based scan that still works.

For a richer volatility regime signal, get a free FRED API key at https://fred.stlouisfed.org/docs/api/api_key.html and add to `.env`:

```env
FRED_API_KEY=your_key_here
```

Without it, VIX falls back to Stooq (still works, less history).
