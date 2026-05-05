# V5.5 Intelligence Enhancement — "Shark Radar Brain"

This release adds the **intelligence layer** to your signal-catching engine. It does not add more feeds. It makes the existing 24 feeds *think* about what they're seeing — together, over time, in patterns.

This is **encoded shark-radar intuition**. Rule-based pattern recognition that runs at machine scale across all 24 feeds simultaneously. Not ML, not learning — but genuinely smarter than rule-by-rule scoring.

## What's New

### 1. Velocity Tracker (`app/velocity_tracker.py`)

The core insight: **a signal at strength 60 that was at 20 yesterday is more interesting than a signal at strength 80 that's been at 80 for a week.** The shark cares about *more blood appearing*, not the existing blood.

- Maintains a rolling history of every signal channel `(source, narrative, symbol)` across scans
- Computes velocity ratio (recent_avg / prior_avg) and tags channels:
  - `ACCELERATING_UP` (ratio ≥ 1.30) — momentum building
  - `ACCELERATING_DOWN` (ratio ≤ 0.70) — momentum dying
  - `STABLE` — no significant change
  - `NEW` — fresh channel, not enough history yet
- Fed into the constellation engine for pattern-priority weighting

### 2. Constellation Engine (`app/constellation_engine.py`)

Detects **multi-feed patterns** that historically precede market moves. Each pattern has a lifecycle stage so you know **where you are in the wave**:

- **🔍 SCOUT** — Single leading-indicator signal appears (you're early)
- **🦈 STALKING** — Multiple feeds aligning (still early, smart money in)
- **⚡ STRIKING** — Full multi-feed confirmation (act now)
- **🌊 LATE** — Heavy news + retail + late attention (consensus formed, you're behind)

**Eight pattern detectors:**

| Pattern | What It Detects |
|---|---|
| **Smart Money Positioning** | Insider filings + options flow with LOW news volume = institutions accumulating quietly |
| **Narrative Ignition** | Google Trends + Reddit + News building = retail attention beginning (acceleration matters) |
| **Macro Regime Shift** | FRED + Treasury + VIX moving together = environment changing |
| **Geopolitical Cascade** | GDELT events + Polymarket odds + commodity moves = real-world event escalating |
| **Insider Cluster** | SEC + SEDI + options activity, low retail noise = smart money before retail |
| **Sentiment Capitulation** | Bearish Reddit + panic VIX + market weakness = potential bottom forming (contrarian) |
| **Echo Chamber Warning** | Heavy news + retail attention but momentum stable = wave already broke, you're late |
| **Canadian Macro Divergence** | Canadian-specific signals active without US macro confirmation = CA-specific opportunity |

### 3. Intelligence Engine Integration

The existing intelligence engine now incorporates velocity + constellations:

- **SCOUT-stage early warnings** enrich HOLD recommendations with "EARLY SIGNAL" notes — you see opportunities before they're confirmed
- **STALKING/STRIKING constellations** add context to BUY/SELL reasons, helping you understand *why* the engine recommends what it does
- **LATE-stage constellations automatically downgrade BUY → HOLD** with explicit chase warnings
- All advice now shows constellation context: `⭐ Smart Money Positioning [STALKING]`

### 4. Expanded Instrument Map

**Before V5.5:** 11 narratives, ~55 US-only instruments, almost no Canadian coverage.

**After V5.5:** 22 narratives, 133 instrument mappings, 22 Canadian (.TO) tickers across all relevant narratives.

**New narratives added:**
- `rate_hikes` (separate from rate_cuts; opposite trade)
- `ai_infrastructure` (separate from ai_policy; bullish AI vs bearish AI)
- `biotech_catalyst` (XBI, IBB, GLP-1 plays)
- `agriculture_food` (DBA, WEAT, CORN, MOO, Nutrien)
- `fx_usd_strength` and `fx_usd_weakness` (DXY, FXC, FXE, FXY)
- `credit_stress` (HYG, JNK, LQD, KRE)
- `supply_chain_disruption` (BDRY, SEA, ZIM)
- `real_estate_stress` (VNQ, IYR, XLRE, XRE.TO)
- `consumer_discretionary` (XLY)
- `defensive_rotation` (XLP, XLU, XLV, VYM)
- `canada_specific` (XIU.TO, XIC.TO, FXC, SHOP.TO)

**Canadian instruments now mapped across:** energy (XEG, SU, CNQ, ENB), uranium (CCO, NXE), gold (ABX, AEM, K), banks (RY, TD, XFN), bonds (XBB), utilities (ZUT), REITs (XRE), agriculture (NTR), crypto (HUT), broad market (XIU, XIC).

## The "Pre-Consensus Detection" Mode in Action

This is the part you specifically asked for — catching waves before consensus forms.

### Example flow:

1. **First scan**: SEC files an insider purchase on XLE. *Polygon options shows unusual call buying.* News quiet. Reddit silent.
2. **Constellation engine fires**: `Smart Money Positioning [SCOUT]` — confidence 0.50
3. **Intelligence engine enriches advice**: "EARLY SIGNAL: Smart Money Positioning pattern detected (SCOUT). Watch for confirmation."
4. **Two scans later**: Velocity tracker detects insider channel `ACCELERATING_UP`
5. **Constellation upgrades to STALKING**: confidence boosted to 0.80
6. **Few more scans**: News begins to mention the catalyst, Polymarket odds shift
7. **Constellation upgrades to STRIKING**: full confirmation across feed types

You're already positioned by step 3-4. By step 7, retail is just discovering it.

### Conversely — late-warning example:

1. News volume spikes about Bitcoin ETF
2. Reddit r/wallstreetbets mentions explode
3. Google Trends spikes
4. Velocity tracker shows attention/Reddit channels are *no longer* accelerating
5. **Constellation fires**: `Echo Chamber Warning [LATE]`
6. **Intelligence engine downgrades any BUY to HOLD** with explicit "consensus already formed; chasing not advised"

## What Did NOT Change

- ✅ All 24 existing feeds remain (Polymarket, Kalshi, PredictIt, Manifold, Metaculus, SEC, CFTC, news, options, FRED, Treasury, EIA, NOAA, grid, shipping, BoC, Stooq, crypto, GDELT, plus the 5 V5.4 additions)
- ✅ All V5.4 anti-knee-jerk safeguards intact (Reddit gates, noise-aware confirmation)
- ✅ Paper broker and IBKR broker integration unchanged
- ✅ Existing intelligence engine logic preserved; constellation enrichment is *additive*
- ✅ Watchdog, risk module, sanity checks all untouched

## Files Changed

- **NEW**: `app/velocity_tracker.py` (temporal acceleration detection)
- **NEW**: `app/constellation_engine.py` (8 multi-feed pattern detectors with lifecycle stages)
- **MODIFIED**: `app/instrument_map.py` (22 narratives, 133 instruments, full Canadian coverage)
- **MODIFIED**: `app/intelligence.py` (constellation-aware advice with SCOUT/STALKING/STRIKING/LATE handling)
- **MODIFIED**: `app/platform.py` (wires velocity + constellation into scan pipeline; new accessor methods)

## Honest Limits — What This Is and Isn't

**What it IS:**
- Sophisticated rule-based pattern recognition
- Encoded human market intuition running at machine scale
- A genuinely smarter engine than V5.4
- Capable of pre-consensus detection on the patterns it knows

**What it IS NOT:**
- Truly intelligent (no learning loop, no memory of outcomes)
- Adaptive (won't reweight feeds based on track record)
- Predictive in the ML sense (no model, no embeddings)
- A guarantee — patterns can be wrong; rules can over-fire

**The intelligence comes from how the patterns are designed, not from learning.**
When you have capital for a true ML/learning system, this becomes the foundation.

## Total System Snapshot

- **24 feeds** across 5 categories (regulated US, decentralized, AI-powered, forecasting, traditional)
- **5 V5.4 additions** (SEDI, StatCan, VIX/regime, Trends, Reddit) with noise tagging
- **22 narratives** with **133 instruments** including 22 Canadian
- **8 constellation patterns** with **4 lifecycle stages** each
- **Velocity tracking** across all signal channels
- **Anti-knee-jerk gates** at multiple layers
- **Paper trading + IBKR integration** unchanged

## Next Steps for You

1. **Install dependencies** (if you haven't already): `pip install -r requirements.txt`
2. **Run as usual**: `streamlit run streamlit_app.py`
3. **Trigger a few scans** — velocity needs ≥4 scans before it computes meaningful acceleration
4. **Watch for SCOUT/STALKING constellations** — these are your pre-consensus opportunities
5. **Heed LATE-stage warnings** — these are the chase-trap detector
