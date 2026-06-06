"""
Sniffer Feeds — V5.8
====================

Front-running signal sources beyond v5.4 extensions. These feeds are
specifically chosen to detect themes/events BEFORE consensus forms:

  1. FRED Leading Indices     - GPR, EPU, FSI, recession probability
  2. Treasury Liquidity       - TGA balance, reverse repo
  3. Credit Spreads           - HY OAS, BBB-AAA, EM spreads
  4. ECB Macro                - European leading indicators
  5. BOJ Yen Carry            - Global risk-on/off proxy
  6. SEC 8-K Material Events  - corporate events before news
  7. OpenInsider Cluster      - faster + cluster-filtered insider buying
  8. Short Report Feeds       - Hindenburg / Muddy Waters RSS
  9. Wikipedia Pageviews      - pre-news attention spikes
 10. USASpending Contracts    - federal money flows

All feeds use the SAME contract as v5.4 extended_feeds:
- Free, no paid subscriptions
- Graceful fallback when sources fail
- Noise-level tagged for the intelligence engine
- Failure modes return empty list, never crash

Common patterns:
- timeout=5s for fast fail
- specific User-Agent (some sources require non-default UA)
- structured signal output with feed_type + noise_level + jurisdiction metadata
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import os, re, json
import xml.etree.ElementTree as ET
import requests

from app.models import Signal, new_id, now_iso
from app.instrument_map import classify_narrative


UA = os.getenv("SIGNAL_BOT_USER_AGENT", "signal-trading-platform/5.8 contact:local@example.com")
TIMEOUT = float(os.getenv("LIVE_FEED_TIMEOUT", "5"))


@dataclass
class SnifferFeedConfig:
    key: str
    name: str
    feed_type: str
    noise_level: str
    requires_env: List[str]
    description: str


SNIFFER_FEEDS: Dict[str, SnifferFeedConfig] = {
    "fred_leading": SnifferFeedConfig(
        key="fred_leading", name="FRED Leading Indices",
        feed_type="macro_data", noise_level="low",
        requires_env=["FRED_API_KEY (optional - falls back to public CSV)"],
        description="Geopolitical Risk, Economic Policy Uncertainty, Financial Stress, Recession Probability"
    ),
    "treasury_liquidity": SnifferFeedConfig(
        key="treasury_liquidity", name="Treasury Liquidity Pulse",
        feed_type="macro_data", noise_level="low",
        requires_env=[],
        description="TGA balance + Reverse Repo facility levels — Fed liquidity early warning"
    ),
    "credit_spreads": SnifferFeedConfig(
        key="credit_spreads", name="Credit Spreads Pulse",
        feed_type="macro_data", noise_level="low",
        requires_env=["FRED_API_KEY (optional)"],
        description="High-yield OAS, BBB-AAA, EM spreads — risk-off leading indicator"
    ),
    "ecb_macro": SnifferFeedConfig(
        key="ecb_macro", name="ECB Statistical Data",
        feed_type="macro_data", noise_level="low",
        requires_env=[],
        description="European leading indicators via ECB Statistical Data Warehouse"
    ),
    "boj_yen_carry": SnifferFeedConfig(
        key="boj_yen_carry", name="Yen Carry Trade Monitor",
        feed_type="macro_data", noise_level="low",
        requires_env=[],
        description="USD/JPY rate + BoJ policy rate proxy — global risk-on/off detector"
    ),
    "sec_8k": SnifferFeedConfig(
        key="sec_8k", name="SEC 8-K Material Events",
        feed_type="filings", noise_level="low",
        requires_env=[],
        description="Corporate material events (M&A, bankruptcies, leadership changes, asset sales)"
    ),
    "openinsider_cluster": SnifferFeedConfig(
        key="openinsider_cluster", name="OpenInsider Cluster Buys",
        feed_type="filings", noise_level="low",
        requires_env=[],
        description="Insider cluster buying (multiple insiders, same name, short window)"
    ),
    "short_reports": SnifferFeedConfig(
        key="short_reports", name="Short Seller Reports",
        feed_type="news", noise_level="medium",
        requires_env=[],
        description="Hindenburg, Muddy Waters, Citron RSS — high-impact short reports"
    ),
    "wikipedia_attention": SnifferFeedConfig(
        key="wikipedia_attention", name="Wikipedia Attention Anomaly",
        feed_type="attention", noise_level="medium",
        requires_env=[],
        description="Wikipedia pageview spikes for monitored entities — pre-news attention"
    ),
    "usaspending_contracts": SnifferFeedConfig(
        key="usaspending_contracts", name="Federal Contract Awards",
        feed_type="filings", noise_level="low",
        requires_env=[],
        description="USASpending.gov contract awards — defense, healthcare, tech vendor flows"
    ),
}


# =========================================================================
# 1. FRED LEADING INDICES
# =========================================================================
# Series IDs to track (all free via FRED):
#   GPRD            = Geopolitical Risk Index (daily)
#   USEPUINDXD      = Economic Policy Uncertainty Index (daily)
#   STLFSI4         = St. Louis Fed Financial Stress Index (weekly)
#   RECPROUSM156N   = Recession Probability (NY Fed, monthly)
#   ANFCI           = Adjusted National Financial Conditions Index (weekly)

FRED_LEADING_SERIES = {
    "GPRD": ("Geopolitical Risk", "geopolitics", "low"),
    "USEPUINDXD": ("Economic Policy Uncertainty", "policy_uncertainty", "low"),
    "STLFSI4": ("Financial Stress Index", "risk_off_setup", "low"),
    "RECPROUSM156N": ("Recession Probability", "recession_risk", "low"),
    "ANFCI": ("Financial Conditions", "risk_off_setup", "low"),
}


def collect_fred_leading(max_per_feed: int = 25) -> List[Signal]:
    """Fetch leading indices from FRED. Falls back to graceful skip if all fail."""
    api_key = os.getenv("FRED_API_KEY")
    out: List[Signal] = []
    for series_id, (label, narrative, _noise) in FRED_LEADING_SERIES.items():
        try:
            if api_key:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {"series_id": series_id, "api_key": api_key, "file_type": "json",
                          "sort_order": "desc", "limit": 10}
                r = requests.get(url, params=params, timeout=TIMEOUT,
                                 headers={"User-Agent": UA})
                if r.status_code >= 400:
                    continue
                data = r.json()
                observations = data.get("observations", [])
            else:
                # Public CSV fallback (works for some series without API key)
                url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
                if r.status_code >= 400:
                    continue
                # Parse CSV - basic implementation
                lines = r.text.strip().split("\n")
                if len(lines) < 3:
                    continue
                observations = []
                for line in lines[1:][-10:]:  # Last 10 observations
                    parts = line.split(",")
                    if len(parts) >= 2:
                        observations.append({"date": parts[0].strip(), "value": parts[1].strip()})
                observations.reverse()  # Most recent first

            if len(observations) < 2:
                continue

            # Find latest valid value and prior valid value
            valid_obs = [o for o in observations if o.get("value") not in (".", "", None)]
            if len(valid_obs) < 2:
                continue
            current = float(valid_obs[0]["value"])
            prior = float(valid_obs[1]["value"])
            pct_change = ((current - prior) / abs(prior)) * 100 if prior != 0 else 0

            # Generate signal only if meaningful move
            if abs(pct_change) < 2.0:
                continue

            direction = "SELL" if pct_change > 0 and series_id in ("GPRD", "USEPUINDXD", "STLFSI4", "RECPROUSM156N", "ANFCI") else "BUY"
            confidence = min(0.85, 0.50 + abs(pct_change) / 100)
            out.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="FRED Leading",
                symbol="SPY",  # Broad market proxy for these macro indices
                direction=direction,
                confidence=round(confidence, 3),
                magnitude=round(abs(pct_change), 2),
                title=f"{label}: {pct_change:+.1f}% change",
                description=f"{label} ({series_id}) moved from {prior:.2f} to {current:.2f}. Leading indicator of {narrative}.",
                horizon="event",
                metadata={
                    "feed_type": "macro_data",
                    "noise_level": "low",
                    "narrative": narrative,
                    "fred_series": series_id,
                    "current_value": current,
                    "prior_value": prior,
                    "pct_change": round(pct_change, 2),
                    "freshness_minutes": 60,
                    "is_live": True,
                    "is_leading_indicator": True,
                }
            ))
            if len(out) >= max_per_feed:
                break
        except Exception:
            continue
    return out


# =========================================================================
# 2. TREASURY LIQUIDITY (TGA + Reverse Repo)
# =========================================================================
# TGA = Treasury General Account balance (Fed's checking account for Treasury)
# Reverse Repo = Fed's reverse repurchase agreements (drains liquidity from system)
# These two together reveal the dollar liquidity available to markets.

def collect_treasury_liquidity(max_per_feed: int = 25) -> List[Signal]:
    """Fetch TGA + RRP levels via FRED public CSV (no API key needed)."""
    out: List[Signal] = []
    # WTREGEN = Treasury General Account balance (weekly)
    # RRPONTSYD = Reverse Repo Operations (daily)
    series_to_check = [
        ("WTREGEN", "Treasury General Account", "liquidity_squeeze", 100),  # bn USD
        ("RRPONTSYD", "Reverse Repo", "liquidity_squeeze", 100),
    ]
    for series_id, label, narrative, scale_threshold in series_to_check:
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            if r.status_code >= 400:
                continue
            lines = r.text.strip().split("\n")
            if len(lines) < 3:
                continue
            valid = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 2 and parts[1].strip() not in (".", ""):
                    try:
                        valid.append((parts[0].strip(), float(parts[1].strip())))
                    except ValueError:
                        continue
            if len(valid) < 5:
                continue
            current = valid[-1][1]
            week_ago = valid[-2][1] if len(valid) >= 2 else current
            month_ago = valid[-5][1] if len(valid) >= 5 else current
            wow_change = current - week_ago
            mom_change = current - month_ago

            # TGA fill = liquidity drain (bearish equities short-term)
            # RRP drain = liquidity injection (bullish equities)
            if series_id == "WTREGEN":
                direction = "SELL" if wow_change > scale_threshold else "BUY" if wow_change < -scale_threshold else "WATCH"
                interpretation = "Treasury accumulating cash (liquidity drain)" if wow_change > 0 else "Treasury spending (liquidity injection)"
            else:  # RRPONTSYD
                direction = "BUY" if wow_change < -scale_threshold else "SELL" if wow_change > scale_threshold else "WATCH"
                interpretation = "Reverse repo draining (liquidity returning to markets)" if wow_change < 0 else "Reverse repo growing (liquidity locked up)"

            if direction == "WATCH":
                continue

            confidence = min(0.80, 0.45 + abs(wow_change) / 1000)
            out.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="Treasury Liquidity",
                symbol="SPY",
                direction=direction,
                confidence=round(confidence, 3),
                magnitude=round(abs(wow_change) / 10, 2),
                title=f"{label}: {wow_change:+.0f}bn WoW",
                description=f"{interpretation}. Current: ${current:.0f}bn, week ago: ${week_ago:.0f}bn, month ago: ${month_ago:.0f}bn.",
                horizon="event",
                metadata={
                    "feed_type": "macro_data",
                    "noise_level": "low",
                    "narrative": narrative,
                    "fred_series": series_id,
                    "current_value": current,
                    "week_change": wow_change,
                    "month_change": mom_change,
                    "freshness_minutes": 720,  # Weekly data
                    "is_live": True,
                    "is_leading_indicator": True,
                }
            ))
        except Exception:
            continue
    return out[:max_per_feed]


# =========================================================================
# 3. CREDIT SPREADS
# =========================================================================
# Credit spreads widen BEFORE equity markets sell off — classic leading indicator
# BAMLH0A0HYM2 = ICE BofA US High Yield Index Option-Adjusted Spread
# BAMLC0A4CBBB  = ICE BofA US Corporate BBB Index OAS
# BAMLEMHYHYLCRPIUSOAS = ICE BofA US EM High Yield OAS

def collect_credit_spreads(max_per_feed: int = 25) -> List[Signal]:
    out: List[Signal] = []
    series_to_check = [
        ("BAMLH0A0HYM2", "US High Yield Spread", "credit_stress", 50),  # bps move threshold
        ("BAMLC0A4CBBB", "BBB Corporate Spread", "credit_stress", 25),
    ]
    for series_id, label, narrative, threshold_bps in series_to_check:
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            if r.status_code >= 400:
                continue
            lines = r.text.strip().split("\n")
            valid = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 2 and parts[1].strip() not in (".", ""):
                    try:
                        valid.append((parts[0].strip(), float(parts[1].strip())))
                    except ValueError:
                        continue
            if len(valid) < 20:
                continue
            current = valid[-1][1]
            week_ago = valid[-5][1]
            month_avg = sum(v[1] for v in valid[-20:]) / 20

            # Move in basis points
            wow_bps = (current - week_ago) * 100
            vs_avg_bps = (current - month_avg) * 100

            if abs(wow_bps) < threshold_bps:
                continue

            # Widening spreads = risk-off = SELL signal for equities
            direction = "SELL" if wow_bps > 0 else "BUY"
            confidence = min(0.85, 0.50 + abs(wow_bps) / 200)
            interpretation = "Credit stress rising" if wow_bps > 0 else "Credit stress easing"

            out.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="Credit Spreads",
                symbol="HYG" if "HYM2" in series_id else "LQD",
                direction=direction,
                confidence=round(confidence, 3),
                magnitude=round(abs(wow_bps), 1),
                title=f"{label}: {wow_bps:+.0f} bps WoW",
                description=f"{interpretation}. Current spread {current:.2f}%, up {wow_bps:+.0f}bps WoW. {vs_avg_bps:+.0f}bps vs 20d avg.",
                horizon="event",
                metadata={
                    "feed_type": "macro_data",
                    "noise_level": "low",
                    "narrative": narrative,
                    "fred_series": series_id,
                    "current_spread_pct": current,
                    "wow_bps": wow_bps,
                    "vs_20d_avg_bps": vs_avg_bps,
                    "freshness_minutes": 1440,  # Daily updates, end-of-day
                    "is_live": True,
                    "is_leading_indicator": True,
                }
            ))
        except Exception:
            continue
    return out[:max_per_feed]


# =========================================================================
# 4. ECB STATISTICAL DATA (European leading indicators)
# =========================================================================
# ECB SDW API: free, REST-based, returns CSV/JSON
# Key series: ICP (HICP inflation), MFI (money supply), CISS (composite indicator of systemic stress)

def collect_ecb_macro(max_per_feed: int = 25) -> List[Signal]:
    """Fetch ECB Composite Indicator of Systemic Stress (CISS) — Europe's FSI equivalent."""
    out: List[Signal] = []
    try:
        # CISS = Composite Indicator of Systemic Stress, daily
        url = "https://sdw-wsrest.ecb.europa.eu/service/data/CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX"
        headers = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0", "User-Agent": UA}
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code >= 400:
            return out
        lines = r.text.strip().split("\n")
        if len(lines) < 5:
            return out
        # Parse CSV - find date and value columns
        header = lines[0].split(",")
        try:
            date_idx = next(i for i, h in enumerate(header) if "TIME_PERIOD" in h or "TIME" in h)
            value_idx = next(i for i, h in enumerate(header) if "OBS_VALUE" in h or "VALUE" in h)
        except StopIteration:
            return out
        valid = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) > max(date_idx, value_idx):
                try:
                    val = float(parts[value_idx].strip())
                    valid.append((parts[date_idx].strip(), val))
                except (ValueError, IndexError):
                    continue
        if len(valid) < 10:
            return out
        valid.sort()
        current = valid[-1][1]
        week_ago = valid[-5][1] if len(valid) >= 5 else current
        change = current - week_ago

        if abs(change) < 0.05:  # Insignificant move
            return out

        direction = "SELL" if change > 0 else "BUY"
        confidence = min(0.80, 0.50 + abs(change) * 2)
        out.append(Signal(
            id=new_id("sig"),
            created_at=now_iso(),
            source="ECB CISS",
            symbol="VGK",  # Vanguard FTSE Europe ETF
            direction=direction,
            confidence=round(confidence, 3),
            magnitude=round(abs(change) * 100, 2),
            title=f"ECB systemic stress: {change:+.3f}",
            description=f"European Composite Indicator of Systemic Stress moved from {week_ago:.3f} to {current:.3f}. {'Stress rising' if change > 0 else 'Stress easing'}.",
            horizon="event",
            metadata={
                "feed_type": "macro_data",
                "noise_level": "low",
                "narrative": "europe_stress",
                "jurisdiction": "EU",
                "current_value": current,
                "week_change": change,
                "freshness_minutes": 1440,
                "is_live": True,
                "is_leading_indicator": True,
            }
        ))
    except Exception:
        pass
    return out[:max_per_feed]


# =========================================================================
# 5. BOJ YEN CARRY (USDJPY)
# =========================================================================
# When yen weakens (USDJPY rises), yen carry trade is funded → risk-on
# When yen strengthens (USDJPY falls), yen carry unwinds → risk-off
# This is a CRITICAL global liquidity signal that most retail misses

def collect_boj_yen_carry(max_per_feed: int = 25) -> List[Signal]:
    """USDJPY direction via FRED (DEXJPUS series)."""
    out: List[Signal] = []
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS"
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        if r.status_code >= 400:
            return out
        lines = r.text.strip().split("\n")
        valid = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip() not in (".", ""):
                try:
                    valid.append((parts[0].strip(), float(parts[1].strip())))
                except ValueError:
                    continue
        if len(valid) < 20:
            return out

        current = valid[-1][1]
        week_ago = valid[-5][1]
        month_avg = sum(v[1] for v in valid[-20:]) / 20
        wow_pct = ((current - week_ago) / week_ago) * 100
        vs_avg_pct = ((current - month_avg) / month_avg) * 100

        if abs(wow_pct) < 1.0:  # Need at least 1% move WoW
            return out

        # Yen STRENGTHENING (USDJPY falling) = carry unwind = risk-off
        # Yen WEAKENING (USDJPY rising) = carry on = risk-on
        direction = "BUY" if wow_pct > 0 else "SELL"
        confidence = min(0.80, 0.50 + abs(wow_pct) / 10)
        interpretation = "Yen weakening (carry trade funded, risk-on)" if wow_pct > 0 else "Yen strengthening (carry unwind, risk-off)"

        out.append(Signal(
            id=new_id("sig"),
            created_at=now_iso(),
            source="Yen Carry",
            symbol="FXY",  # Currency Shares Japanese Yen Trust
            direction="SELL" if wow_pct > 0 else "BUY",  # FXY is yen-long, so inverse of risk-on
            confidence=round(confidence, 3),
            magnitude=round(abs(wow_pct), 2),
            title=f"USDJPY: {wow_pct:+.2f}% WoW",
            description=f"{interpretation}. USDJPY at {current:.2f}, week ago {week_ago:.2f}, 20d avg {month_avg:.2f}.",
            horizon="event",
            metadata={
                "feed_type": "macro_data",
                "noise_level": "low",
                "narrative": "global_liquidity",
                "current_value": current,
                "week_change_pct": wow_pct,
                "vs_20d_avg_pct": vs_avg_pct,
                "freshness_minutes": 1440,
                "is_live": True,
                "is_leading_indicator": True,
                "risk_on_implied": wow_pct > 0,
            }
        ))
    except Exception:
        pass
    return out[:max_per_feed]


# =========================================================================
# 6. SEC 8-K MATERIAL EVENTS
# =========================================================================
# 8-K filings disclose: M&A, bankruptcy, leadership changes, asset sales,
# regulation FD disclosures. Hits SEC EDGAR before mainstream news catches up.

def collect_sec_8k(max_per_feed: int = 25) -> List[Signal]:
    """Recent 8-K filings from SEC EDGAR."""
    out: List[Signal] = []
    try:
        # SEC EDGAR full-text search for 8-K
        url = "https://www.sec.gov/cgi-bin/browse-edgar"
        params = {"action": "getcurrent", "type": "8-K", "company": "",
                  "datea": "", "dateb": "", "owner": "include",
                  "count": min(40, max_per_feed * 2), "action": "getcurrent",
                  "output": "atom"}
        r = requests.get(url, params=params, timeout=TIMEOUT,
                         headers={"User-Agent": UA, "Accept": "application/atom+xml"})
        if r.status_code >= 400:
            return out
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            return out

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        for entry in entries[:max_per_feed]:
            try:
                title_elem = entry.find("atom:title", ns)
                title = title_elem.text if title_elem is not None else ""
                summary_elem = entry.find("atom:summary", ns)
                summary = summary_elem.text if summary_elem is not None else ""

                # Extract ticker if present
                ticker_match = re.search(r"\(([A-Z]{1,5})\)", title)
                ticker = ticker_match.group(1) if ticker_match else ""
                if not ticker:
                    continue

                # Material event keyword detection
                material_keywords = {
                    "bankruptcy": ("SELL", "distress", 0.85),
                    "chapter 11": ("SELL", "distress", 0.90),
                    "merger": ("BUY", "ma_activity", 0.70),
                    "acquisition": ("BUY", "ma_activity", 0.70),
                    "ceo resign": ("SELL", "leadership_change", 0.65),
                    "ceo departure": ("SELL", "leadership_change", 0.65),
                    "ceo terminated": ("SELL", "leadership_change", 0.75),
                    "going concern": ("SELL", "distress", 0.80),
                    "delisting": ("SELL", "distress", 0.85),
                    "restatement": ("SELL", "accounting_concern", 0.70),
                    "material weakness": ("SELL", "accounting_concern", 0.65),
                    "dividend increase": ("BUY", "capital_return", 0.55),
                    "buyback authorization": ("BUY", "capital_return", 0.55),
                    "stock split": ("WATCH", "corporate_action", 0.45),
                    "spinoff": ("BUY", "corporate_action", 0.55),
                    "asset sale": ("WATCH", "corporate_action", 0.50),
                }

                combined_text = (title + " " + summary).lower()
                matched_event = None
                for keyword, (direction, narrative, conf) in material_keywords.items():
                    if keyword in combined_text:
                        matched_event = (keyword, direction, narrative, conf)
                        break

                if not matched_event:
                    continue  # Skip routine 8-Ks

                keyword, direction, narrative, base_conf = matched_event
                out.append(Signal(
                    id=new_id("sig"),
                    created_at=now_iso(),
                    source="SEC 8-K Sniffer",
                    symbol=ticker,
                    direction=direction,
                    confidence=base_conf,
                    magnitude=40.0 if direction != "WATCH" else 20.0,
                    title=f"{ticker}: {keyword.title()} 8-K",
                    description=title[:200] if title else summary[:200],
                    horizon="event",
                    metadata={
                        "feed_type": "filings",
                        "noise_level": "low",
                        "narrative": narrative,
                        "event_type": keyword,
                        "freshness_minutes": 60,
                        "is_live": True,
                        "form_type": "8-K",
                    }
                ))
            except Exception:
                continue
    except Exception:
        pass
    return out[:max_per_feed]


# =========================================================================
# 7. OPENINSIDER CLUSTER BUYS
# =========================================================================
# OpenInsider aggregates SEC Form 4 with smart filters.
# Cluster buys (3+ insiders, same name, short window) = high signal

def collect_openinsider_cluster(max_per_feed: int = 25) -> List[Signal]:
    """Cluster insider buying from OpenInsider."""
    out: List[Signal] = []
    try:
        # OpenInsider's cluster buy screener
        url = "http://openinsider.com/screener"
        params = {
            "s": "",  # ticker filter
            "o": "",  # officer
            "pl": "",  # purchase low
            "ph": "",  # purchase high
            "tl": "100",  # transaction low ($)
            "th": "",  # transaction high
            "fdr": "30",  # filed within 30 days
            "fdlyl": "",
            "fdlyh": "",
            "daysago": "",
            "xp": "1",  # cluster filter
            "xs": "1",
            "vl": "",
            "vh": "",
            "ocl": "",
            "och": "",
            "sic1": "-1",
            "sicl": "100",
            "sich": "9999",
            "grp": "0",
            "nfl": "",
            "nfh": "",
            "nil": "",
            "nih": "",
            "nol": "",
            "noh": "",
            "v2l": "",
            "v2h": "",
            "oc2l": "",
            "oc2h": "",
            "sortcol": "0",
            "cnt": str(min(50, max_per_feed * 2)),
            "page": "1"
        }
        r = requests.get(url, params=params, timeout=TIMEOUT,
                         headers={"User-Agent": UA})
        if r.status_code >= 400:
            return out
        html = r.text

        # Very rough HTML parsing - look for table rows
        # OpenInsider's structure: <tr><td>...filing date...</td><td>...trade date...</td>...
        # We look for ticker patterns followed by transaction details
        # This is intentionally fragile; we fall back gracefully

        # Simple regex to extract clusters (ticker followed by purchase total)
        # Pattern: ticker code in <a> tag, then dollar amounts
        ticker_pattern = re.compile(r'/screener\?s=([A-Z]{1,5})"[^>]*>\1</a>')
        seen_tickers = set()
        for m in ticker_pattern.finditer(html):
            ticker = m.group(1)
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            out.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="OpenInsider Cluster",
                symbol=ticker,
                direction="BUY",
                confidence=0.72,
                magnitude=35.0,
                title=f"{ticker}: Insider cluster buying",
                description=f"Multiple insiders purchased {ticker} stock in cluster pattern (3+ insiders, <30d window).",
                horizon="event",
                metadata={
                    "feed_type": "filings",
                    "noise_level": "low",
                    "narrative": "insider_cluster",
                    "cluster_buy": True,
                    "freshness_minutes": 240,
                    "is_live": True,
                }
            ))
            if len(out) >= max_per_feed:
                break
    except Exception:
        pass
    return out[:max_per_feed]


# =========================================================================
# 8. SHORT REPORT FEEDS (Hindenburg, Muddy Waters, Citron)
# =========================================================================
# Short-seller reports move stocks 20%+ same day. Getting them via RSS
# beats waiting for news aggregation.

SHORT_REPORT_FEEDS = [
    ("Hindenburg Research", "https://hindenburgresearch.com/feed/"),
    ("Muddy Waters Research", "https://www.muddywatersresearch.com/feed/"),
    ("Citron Research", "https://citronresearch.com/feed/"),
]


def collect_short_reports(max_per_feed: int = 25) -> List[Signal]:
    """Aggregate recent short reports from known short-sellers."""
    out: List[Signal] = []
    for source_name, url in SHORT_REPORT_FEEDS:
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            if r.status_code >= 400:
                continue
            try:
                root = ET.fromstring(r.text)
            except ET.ParseError:
                continue

            # Try standard RSS structure first
            items = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
            for item in items[:max_per_feed // len(SHORT_REPORT_FEEDS) + 1]:
                try:
                    title_elem = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                    title = title_elem.text if title_elem is not None else ""
                    if not title:
                        continue

                    # Extract ticker - short reports often mention ticker in title or first sentence
                    desc_elem = (item.find("description") or
                                 item.find("{http://www.w3.org/2005/Atom}summary") or
                                 item.find("{http://www.w3.org/2005/Atom}content"))
                    desc = desc_elem.text if desc_elem is not None else ""

                    # Search for $TICKER or (TICKER) patterns
                    ticker_match = (re.search(r'\$([A-Z]{2,5})\b', title + " " + desc) or
                                    re.search(r'\(([A-Z]{2,5}):', title + " " + desc) or
                                    re.search(r'NYSE:\s*([A-Z]{2,5})', title + " " + desc) or
                                    re.search(r'NASDAQ:\s*([A-Z]{2,5})', title + " " + desc))
                    if not ticker_match:
                        continue
                    ticker = ticker_match.group(1)

                    out.append(Signal(
                        id=new_id("sig"),
                        created_at=now_iso(),
                        source=source_name,
                        symbol=ticker,
                        direction="SELL",
                        confidence=0.78,
                        magnitude=60.0,  # Short reports = high magnitude expected
                        title=f"{source_name} short: {ticker}",
                        description=title[:200],
                        horizon="event",
                        metadata={
                            "feed_type": "news",
                            "noise_level": "medium",
                            "narrative": "short_report",
                            "short_seller": source_name,
                            "freshness_minutes": 240,
                            "is_live": True,
                            "high_impact": True,
                        }
                    ))
                except Exception:
                    continue
        except Exception:
            continue
    return out[:max_per_feed]


# =========================================================================
# 9. WIKIPEDIA PAGEVIEW ANOMALY DETECTION
# =========================================================================
# Wikipedia provides free pageview API. Sudden spike in a company's Wiki
# page often precedes news cycles. Same for political/geopolitical figures.

WIKIPEDIA_WATCH_LIST = [
    # Companies - high-attention names
    ("Tesla,_Inc.", "TSLA", "single_name"),
    ("Apple_Inc.", "AAPL", "single_name"),
    ("Nvidia", "NVDA", "single_name"),
    ("Microsoft", "MSFT", "single_name"),
    ("Berkshire_Hathaway", "BRK.B", "single_name"),
    ("OpenAI", "MSFT", "ai_chips"),  # Proxy via MSFT
    # Macro/Geo
    ("Federal_Reserve", "SPY", "policy_uncertainty"),
    ("United_States_dollar", "UUP", "global_liquidity"),
    ("OPEC", "USO", "oil_geopolitics"),
    ("Bank_of_Canada", "FXC", "canada_specific"),
]


def collect_wikipedia_attention(max_per_feed: int = 25) -> List[Signal]:
    """Detect anomalous Wikipedia pageview spikes."""
    out: List[Signal] = []
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=14)
    end_str = end_date.strftime("%Y%m%d")
    start_str = start_date.strftime("%Y%m%d")

    for article, ticker, narrative in WIKIPEDIA_WATCH_LIST[:max_per_feed]:
        try:
            url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
                   f"en.wikipedia/all-access/all-agents/{article}/daily/{start_str}/{end_str}")
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
            if r.status_code >= 400:
                continue
            data = r.json()
            items = data.get("items", [])
            if len(items) < 7:
                continue
            views = [int(item.get("views", 0)) for item in items]
            # Recent 2-day average vs prior 7-day average
            recent_avg = sum(views[-2:]) / 2
            prior_avg = sum(views[-9:-2]) / 7 if len(views) >= 9 else sum(views[:-2]) / max(1, len(views)-2)
            if prior_avg == 0:
                continue
            spike_ratio = recent_avg / prior_avg

            if spike_ratio < 1.8:  # Need 80%+ spike to be interesting
                continue

            # Direction is uncertain from attention alone — treat as WATCH unless very strong
            direction = "WATCH"
            if spike_ratio > 3.0:
                # Very strong spike — often associated with negative news historically
                direction = "WATCH"  # Still WATCH; let other feeds confirm direction

            confidence = min(0.70, 0.40 + (spike_ratio - 1.8) / 5)
            out.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="Wikipedia Attention",
                symbol=ticker,
                direction=direction,
                confidence=round(confidence, 3),
                magnitude=round(min(80, spike_ratio * 15), 1),
                title=f"{article.replace('_', ' ')}: {spike_ratio:.1f}x pageview spike",
                description=f"Wikipedia pageviews for {article} spiked to {recent_avg:.0f}/day, "
                            f"up from {prior_avg:.0f}/day 7-day baseline. Often precedes news cycles.",
                horizon="event",
                metadata={
                    "feed_type": "attention",
                    "noise_level": "medium",
                    "narrative": narrative,
                    "wikipedia_article": article,
                    "spike_ratio": round(spike_ratio, 2),
                    "recent_avg_views": int(recent_avg),
                    "baseline_avg_views": int(prior_avg),
                    "freshness_minutes": 720,
                    "is_live": True,
                }
            ))
        except Exception:
            continue
    return out[:max_per_feed]


# =========================================================================
# 10. USASpending FEDERAL CONTRACTS
# =========================================================================
# Federal contract awards often precede stock moves for defense, healthcare,
# tech vendors. USASpending.gov provides a free API.

def collect_usaspending_contracts(max_per_feed: int = 25) -> List[Signal]:
    """Recent significant federal contract awards."""
    out: List[Signal] = []
    try:
        url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
        # Last 7 days, awards > $10M
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=7)
        payload = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],  # Definitive Contract types
                "time_period": [{
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d")
                }],
                "award_amounts": [{"lower_bound": 10000000}],  # $10M+
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount",
                       "Awarding Agency", "Award Type", "Description"],
            "limit": min(50, max_per_feed * 2),
            "page": 1,
            "sort": "Award Amount",
            "order": "desc"
        }
        r = requests.post(url, json=payload, timeout=TIMEOUT,
                          headers={"User-Agent": UA, "Content-Type": "application/json"})
        if r.status_code >= 400:
            return out
        data = r.json()
        results = data.get("results", [])

        # Map recipient names to tickers (common defense/healthcare/tech contractors)
        recipient_to_ticker = {
            "lockheed martin": "LMT", "raytheon": "RTX", "northrop": "NOC",
            "boeing": "BA", "general dynamics": "GD", "l3harris": "LHX",
            "huntington ingalls": "HII", "leidos": "LDOS", "booz allen": "BAH",
            "caci": "CACI", "saic": "SAIC", "kbr": "KBR",
            "honeywell": "HON", "textron": "TXT", "harris": "HRS",
            "microsoft": "MSFT", "oracle": "ORCL", "amazon": "AMZN",
            "google": "GOOGL", "alphabet": "GOOGL", "ibm": "IBM",
            "accenture": "ACN", "palantir": "PLTR",
            "pfizer": "PFE", "moderna": "MRNA", "merck": "MRK",
            "johnson & johnson": "JNJ", "j&j": "JNJ",
            "humana": "HUM", "cvs": "CVS", "unitedhealth": "UNH",
        }

        for award in results[:max_per_feed]:
            try:
                recipient = str(award.get("Recipient Name", "")).lower()
                amount = float(award.get("Award Amount", 0))
                agency = award.get("Awarding Agency", "")
                desc = award.get("Description", "") or ""

                # Match recipient to ticker
                ticker = None
                for name, tkr in recipient_to_ticker.items():
                    if name in recipient:
                        ticker = tkr
                        break
                if not ticker:
                    continue

                # Threshold: only large ($50M+) contracts as signals
                if amount < 50_000_000:
                    continue

                confidence = min(0.70, 0.45 + (amount / 1_000_000_000) * 0.1)
                magnitude = min(50, amount / 10_000_000)  # $10M = 1.0, $500M = 50.0
                narrative = "defense" if any(d in str(agency).lower() for d in ["defense", "army", "navy", "air force"]) else "government_contract"

                out.append(Signal(
                    id=new_id("sig"),
                    created_at=now_iso(),
                    source="USASpending",
                    symbol=ticker,
                    direction="BUY",
                    confidence=round(confidence, 3),
                    magnitude=round(magnitude, 2),
                    title=f"{ticker}: ${amount/1_000_000:.0f}M federal contract",
                    description=f"{ticker} ({recipient.title()}) awarded ${amount/1_000_000:.0f}M from {agency}. {desc[:100]}",
                    horizon="event",
                    metadata={
                        "feed_type": "filings",
                        "noise_level": "low",
                        "narrative": narrative,
                        "contract_amount": amount,
                        "awarding_agency": str(agency),
                        "freshness_minutes": 480,
                        "is_live": True,
                    }
                ))
            except Exception:
                continue
    except Exception:
        pass
    return out[:max_per_feed]


# =========================================================================
# Dispatch table for live_feeds integration
# =========================================================================

SNIFFER_COLLECTORS = {
    "fred_leading": collect_fred_leading,
    "treasury_liquidity": collect_treasury_liquidity,
    "credit_spreads": collect_credit_spreads,
    "ecb_macro": collect_ecb_macro,
    "boj_yen_carry": collect_boj_yen_carry,
    "sec_8k": collect_sec_8k,
    "openinsider_cluster": collect_openinsider_cluster,
    "short_reports": collect_short_reports,
    "wikipedia_attention": collect_wikipedia_attention,
    "usaspending_contracts": collect_usaspending_contracts,
}
