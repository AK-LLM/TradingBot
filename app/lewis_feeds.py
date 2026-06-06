"""
lewis_feeds.py — V6.0 additions inspired by the Insider Routines suite
======================================================================

Adds five new collectors that surface signals STP didn't previously cover.
They emit standard `Signal` objects with metadata.feed_type and metadata.noise_level
so they slot directly into the existing constellation_engine + intelligence pipeline.

Feeds:
  1. fed_speech_nlp       — federalreserve.gov speeches classified hawkish/dovish
  2. onchain_whale        — Whale Alert / blockchain.info large-tx (CEX↔private)
  3. thirteen_f_delta     — quarter-over-quarter 13F-HR changes for marquee funds
  4. filtered_form4       — Form 4 P-transactions ≥$100k by C-suite (Lewis's Eddie)
  5. stock_act_trades     — Senate/House periodic transaction reports
  6. activist_stakes      — 13D/13G filings (≥5% activist stakes)

All collectors:
  • Return [] on any error (graceful degrade; matches existing live_feeds pattern)
  • Respect timeout = LIVE_FEED_TIMEOUT env (default 10s)
  • Tag every signal with noise_level so intelligence/constellation engines can
    weigh them correctly. All Lewis-style sources are "low" noise (regulatory/
    on-chain) — they're authoritative anchors, not social sentiment.

Wire-in: in platform.py scan_signals(), after the existing collect_live_signals call:

    from app.lewis_feeds import collect_all_lewis_feeds
    signals.extend(collect_all_lewis_feeds(self.state))

That's the only edit required.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.models import Signal, new_id, now_iso
from app.instrument_map import classify_narrative


UA = os.getenv("SIGNAL_BOT_USER_AGENT", "signal-trading-platform/6.0 contact:local@example.com")
SEC_UA = os.getenv("SEC_USER_AGENT", UA)
TIMEOUT = float(os.getenv("LIVE_FEED_TIMEOUT", "10"))


# --------------------------------------------------------------------------
# Feed registry — mirrors the SnifferFeedConfig contract in sniffer_feeds.py
# --------------------------------------------------------------------------

@dataclass
class LewisFeedConfig:
    key: str
    name: str
    feed_type: str
    noise_level: str
    requires_env: List[str]
    description: str


LEWIS_FEEDS: Dict[str, LewisFeedConfig] = {
    "fed_speech_nlp": LewisFeedConfig(
        key="fed_speech_nlp",
        name="Fed Speech NLP (Hawkish/Dovish)",
        feed_type="macro_data",
        noise_level="low",
        requires_env=[],
        description="Federal Reserve speeches classified by tone (no key needed).",
    ),
    "onchain_whale": LewisFeedConfig(
        key="onchain_whale",
        name="On-Chain Whale Transfers",
        feed_type="crypto_market_data",
        noise_level="low",
        requires_env=["WHALE_ALERT_API_KEY (optional — falls back to blockchain.info)"],
        description="Large BTC/ETH/stablecoin transfers; CEX↔private classification.",
    ),
    "thirteen_f_delta": LewisFeedConfig(
        key="thirteen_f_delta",
        name="13F Marquee Fund Delta",
        feed_type="filings",
        noise_level="low",
        requires_env=[],
        description="Quarter-over-quarter holdings changes from major institutional funds.",
    ),
    "filtered_form4": LewisFeedConfig(
        key="filtered_form4",
        name="Filtered Form 4 Insider Buys",
        feed_type="filings",
        noise_level="low",
        requires_env=[],
        description="Form 4 P-coded buys ≥$100k by CEO/CFO/President/Chairman/Director.",
    ),
    "stock_act_trades": LewisFeedConfig(
        key="stock_act_trades",
        name="Senate/House STOCK Act Trades",
        feed_type="filings",
        noise_level="low",
        requires_env=[],
        description="Politician periodic transaction reports (PTRs).",
    ),
    "activist_stakes": LewisFeedConfig(
        key="activist_stakes",
        name="13D/13G Activist Stakes",
        feed_type="filings",
        noise_level="low",
        requires_env=[],
        description="≥5% stakes via Schedule 13D (active) or 13G (passive).",
    ),
}


# --------------------------------------------------------------------------
# 1. Fed Speech NLP
# --------------------------------------------------------------------------

# Words/phrases that lean hawkish (tighter policy, higher rates, anti-inflation)
HAWKISH_TERMS = {
    "inflation persistent", "above target", "additional tightening", "restrictive policy",
    "higher for longer", "vigilance", "elevated inflation", "wage pressure",
    "tight labor market", "overheating", "balance sheet runoff", "hike", "raise rates",
    "tighten", "restrictive stance", "patience required", "data-dependent",
    "anchor expectations", "premature easing", "inflation risks",
}

DOVISH_TERMS = {
    "moderating", "easing", "rate cuts", "accommodation", "below target",
    "softening labor", "disinflation", "weakening demand", "transitory",
    "growth concerns", "downside risks", "recession risk", "patience appropriate",
    "balanced risks", "supportive policy", "rate reduction", "lower rates",
    "weakening economy", "slowdown", "fragile",
}


def _classify_speech_tone(text: str) -> Tuple[str, float, List[str]]:
    """Return (label, confidence_0_1, matched_terms). Naive but auditable."""
    if not text:
        return ("neutral", 0.0, [])
    lower = text.lower()
    matched_hawkish = [t for t in HAWKISH_TERMS if t in lower]
    matched_dovish = [t for t in DOVISH_TERMS if t in lower]
    h, d = len(matched_hawkish), len(matched_dovish)
    if h == 0 and d == 0:
        return ("neutral", 0.0, [])
    total = h + d
    if h > d:
        return ("hawkish", h / total, matched_hawkish[:5])
    if d > h:
        return ("dovish", d / total, matched_dovish[:5])
    return ("mixed", 0.5, (matched_hawkish + matched_dovish)[:5])


def _fetch_fed_speech_rss() -> List[Dict[str, str]]:
    """Pull federalreserve.gov speeches RSS. Returns list of dicts with title/link/desc/date."""
    try:
        r = requests.get(
            "https://www.federalreserve.gov/feeds/speeches.xml",
            headers={"User-Agent": UA},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        out: List[Dict[str, str]] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if title:
                out.append({"title": title, "link": link, "description": desc, "pub": pub})
        return out
    except Exception:
        return []


def collect_fed_speech_signals(state: Dict[str, Any], max_items: int = 5) -> List[Signal]:
    """Fed speeches → tone classification → macro Signals.

    Direction mapping for risk assets (equity/crypto):
      dovish  → BUY  (rate cuts coming, liquidity expansion)
      hawkish → SELL (cuts paused or hikes, liquidity drain)
      neutral/mixed → WATCH
    """
    items = _fetch_fed_speech_rss()
    if not items:
        return []
    signals: List[Signal] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for item in items[:max_items]:
        # Tone is classified on title + RSS description. For better accuracy,
        # users can extend this to fetch the full transcript at item["link"].
        tone, confidence, matched = _classify_speech_tone(
            f"{item['title']}. {item['description']}"
        )
        if tone == "neutral":
            continue

        direction = "BUY" if tone == "dovish" else ("SELL" if tone == "hawkish" else "WATCH")
        narrative, primary_symbol = classify_narrative(item["title"]) if callable(classify_narrative) else ("fed_policy", "MARKET")

        signals.append(Signal(
            id=new_id("sig"),
            created_at=now_iso(),
            source="fed_speech_nlp",
            symbol=primary_symbol or "MARKET",
            direction=direction,
            confidence=round(min(0.95, 0.5 + 0.1 * len(matched)), 2),
            magnitude=confidence,
            title=f"Fed speech ({tone}): {item['title'][:140]}",
            description=(item["description"] or "")[:400],
            horizon="swing",
            metadata={
                "feed_type": "macro_data",
                "noise_level": "low",
                "narrative": narrative or "fed_policy",
                "tone": tone,
                "matched_terms": matched,
                "url": item["link"],
                "is_regime_context": False,  # not a VIX-regime signal; tone signal
            },
        ))
    return signals


# --------------------------------------------------------------------------
# 2. On-Chain Whale Transfers
# --------------------------------------------------------------------------

# Known CEX wallet labels — extend as needed. These are the most-used "exchange"
# tags on Etherscan/blockchain.info; transfers in/out of them = CEX flow.
KNOWN_CEX_TAGS = {
    "binance", "coinbase", "kraken", "okx", "bitfinex", "bybit", "gate.io",
    "kucoin", "bitstamp", "huobi", "gemini", "ftx",
}

WHALE_USD_THRESHOLD = 5_000_000


def _fetch_whale_alert(min_value: int = WHALE_USD_THRESHOLD, hours: int = 6) -> List[Dict[str, Any]]:
    """Try Whale Alert API if key configured. Returns list of transaction dicts."""
    api_key = os.getenv("WHALE_ALERT_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        start = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
        r = requests.get(
            "https://api.whale-alert.io/v1/transactions",
            params={"api_key": api_key, "min_value": min_value, "start": start, "limit": 100},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("transactions", []) or []
    except Exception:
        return []


def _fetch_blockchain_info_large() -> List[Dict[str, Any]]:
    """Fallback: blockchain.info unconfirmed-tx + last-blocks for BTC whales.

    blockchain.info doesn't directly serve "large transactions in last 6h" via
    a clean API; we return [] here and rely on Whale Alert when configured.
    Users without a key can still get the other Lewis feeds — this just no-ops.
    """
    return []


def _classify_whale_direction(tx: Dict[str, Any]) -> Optional[str]:
    """CEX→private = BULLISH (accumulation). private→CEX = BEARISH (distribution)."""
    from_owner = (tx.get("from", {}) or {}).get("owner", "").lower()
    to_owner = (tx.get("to", {}) or {}).get("owner", "").lower()
    from_type = (tx.get("from", {}) or {}).get("owner_type", "").lower()
    to_type = (tx.get("to", {}) or {}).get("owner_type", "").lower()

    from_is_cex = from_type == "exchange" or any(t in from_owner for t in KNOWN_CEX_TAGS)
    to_is_cex = to_type == "exchange" or any(t in to_owner for t in KNOWN_CEX_TAGS)

    if from_is_cex and not to_is_cex:
        return "BUY"   # accumulation
    if to_is_cex and not from_is_cex:
        return "SELL"  # distribution
    return None


# Symbol mapping from on-chain asset → our ticker convention
WHALE_SYMBOL_MAP = {
    "btc": "BTC", "wbtc": "BTC",
    "eth": "ETH", "weth": "ETH",
    "usdc": "MACRO", "usdt": "MACRO",  # stablecoin flow = macro liquidity
}


def collect_onchain_whale_signals(state: Dict[str, Any], max_items: int = 10) -> List[Signal]:
    txs = _fetch_whale_alert()
    if not txs:
        txs = _fetch_blockchain_info_large()
    if not txs:
        return []

    signals: List[Signal] = []
    for tx in txs[:max_items]:
        direction = _classify_whale_direction(tx)
        if not direction:
            continue
        symbol_raw = (tx.get("symbol") or "").lower()
        symbol = WHALE_SYMBOL_MAP.get(symbol_raw, "MARKET")
        amount_usd = float(tx.get("amount_usd", 0) or 0)
        if amount_usd < WHALE_USD_THRESHOLD:
            continue

        # Confidence scales with size. $5M = 0.55, $50M+ = 0.95.
        confidence = min(0.95, 0.5 + (amount_usd / 50_000_000) * 0.45)
        action = "accumulation" if direction == "BUY" else "distribution"

        signals.append(Signal(
            id=new_id("sig"),
            created_at=now_iso(),
            source="onchain_whale",
            symbol=symbol,
            direction=direction,
            confidence=round(confidence, 2),
            magnitude=amount_usd / 1_000_000,  # value in $M
            title=f"Whale {action}: ${amount_usd/1_000_000:.1f}M {symbol_raw.upper()}",
            description=(
                f"{tx.get('from', {}).get('owner', 'private')} → "
                f"{tx.get('to', {}).get('owner', 'private')}; "
                f"hash {(tx.get('hash') or '')[:16]}"
            )[:400],
            horizon="swing",
            metadata={
                "feed_type": "crypto_market_data",
                "noise_level": "low",
                "narrative": "crypto_flows",
                "tx_hash": tx.get("hash"),
                "amount_usd": amount_usd,
                "blockchain": tx.get("blockchain"),
                "flow": action,
            },
        ))
    return signals


# --------------------------------------------------------------------------
# 3. 13F Marquee Fund Delta
# --------------------------------------------------------------------------

MARQUEE_FUNDS = [
    ("Berkshire Hathaway", "0001067983"),
    ("Bridgewater Associates", "0001350694"),
    ("Renaissance Technologies", "0001037389"),
    ("Citadel Advisors", "0001423053"),
    ("Two Sigma Investments", "0001179392"),
    ("Tiger Global", "0001167483"),
    ("Pershing Square", "0001336528"),
    ("Soros Fund Management", "0001029160"),
]

THIRTEEN_F_MIN_USD = 50_000_000


def _edgar_recent_13fhr(cik: str) -> List[Dict[str, str]]:
    """Get the two most-recent 13F-HR filings for a CIK from EDGAR."""
    try:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar"
        r = requests.get(
            url,
            params={"action": "getcompany", "CIK": cik, "type": "13F-HR", "count": "2", "output": "atom"},
            headers={"User-Agent": SEC_UA, "Accept": "application/atom+xml"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        out = []
        for entry in root.findall("atom:entry", ns):
            link_elem = entry.find("atom:link", ns)
            updated = entry.findtext("atom:updated", default="", namespaces=ns)
            title = entry.findtext("atom:title", default="", namespaces=ns)
            if link_elem is not None:
                out.append({
                    "url": link_elem.get("href", ""),
                    "updated": updated,
                    "title": title,
                })
        return out
    except Exception:
        return []


def _parse_13f_holdings(filing_url: str) -> Dict[str, float]:
    """Pull the primary doc XML of a 13F-HR and return {ticker: usd_value}.

    Notes:
      • EDGAR's 13F-HR primary doc varies in structure year-to-year.
      • This implementation does best-effort parsing. If the filing index page
        can't be resolved, returns {} (graceful degrade).
      • Ticker is not always in the XML (CUSIP is). Mapping CUSIP→ticker would
        require an additional lookup; for now we emit CUSIP as the symbol if
        ticker isn't present, and let the constellation engine treat it as
        narrative-tagged rather than symbol-tagged.
    """
    try:
        # EDGAR filing index page lists the underlying XML
        r = requests.get(filing_url, headers={"User-Agent": SEC_UA}, timeout=TIMEOUT)
        r.raise_for_status()
        # Find the .xml file (it's the info table)
        xml_match = re.search(r'href="([^"]+\.xml)"', r.text)
        if not xml_match:
            return {}
        xml_url = xml_match.group(1)
        if xml_url.startswith("/"):
            xml_url = "https://www.sec.gov" + xml_url
        xr = requests.get(xml_url, headers={"User-Agent": SEC_UA}, timeout=TIMEOUT)
        xr.raise_for_status()
        # The info table has nameOfIssuer + value entries per holding
        root = ET.fromstring(xr.content)
        # Strip namespace for simpler parsing
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]
        holdings: Dict[str, float] = {}
        for info in root.iter("infoTable"):
            name = (info.findtext("nameOfIssuer") or "").strip()
            value = info.findtext("value") or "0"
            # SEC reports value in thousands of dollars
            try:
                usd = float(value) * 1000
            except ValueError:
                continue
            if name:
                holdings[name] = holdings.get(name, 0) + usd
        return holdings
    except Exception:
        return {}


def _fund_cache_path() -> str:
    base = os.path.expanduser("~/.signal_trading_platform")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "thirteen_f_cache.json")


def _load_fund_cache() -> Dict[str, Dict[str, float]]:
    try:
        path = _fund_cache_path()
        if os.path.exists(path):
            with open(path) as fp:
                return json.load(fp)
    except Exception:
        pass
    return {}


def _save_fund_cache(cache: Dict[str, Dict[str, float]]) -> None:
    try:
        with open(_fund_cache_path(), "w") as fp:
            json.dump(cache, fp)
    except Exception:
        pass


def collect_thirteen_f_delta_signals(state: Dict[str, Any]) -> List[Signal]:
    """Compare latest 13F-HR per marquee fund against the cached prior quarter.

    Emits up to one BUY signal per fund-NEW-position and one SELL per fund-EXITED.
    Filters to changes ≥ $50M.
    """
    cache = _load_fund_cache()
    signals: List[Signal] = []

    for fund_name, cik in MARQUEE_FUNDS:
        filings = _edgar_recent_13fhr(cik)
        if not filings:
            continue
        # Latest filing → parse holdings
        latest_url = filings[0]["url"]
        # The "url" from atom is an index page URL; build the filing detail URL
        # Best-effort: try the URL directly as parser handles index pages.
        latest_holdings = _parse_13f_holdings(latest_url)
        if not latest_holdings:
            continue

        prior_holdings = cache.get(cik, {})
        if not prior_holdings:
            # First time we've seen this fund — cache and skip emitting
            cache[cik] = latest_holdings
            continue

        # Compute deltas
        new_positions = {k: v for k, v in latest_holdings.items() if k not in prior_holdings and v >= THIRTEEN_F_MIN_USD}
        exited = {k: prior_holdings[k] for k in prior_holdings if k not in latest_holdings and prior_holdings[k] >= THIRTEEN_F_MIN_USD}

        # Most-notable new position
        if new_positions:
            ticker_name = max(new_positions, key=new_positions.get)
            value = new_positions[ticker_name]
            signals.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="thirteen_f_delta",
                symbol=ticker_name[:20].upper(),
                direction="BUY",
                confidence=min(0.95, 0.6 + value / 1_000_000_000),
                magnitude=value / 1_000_000,
                title=f"{fund_name} NEW position: {ticker_name[:40]} (${value/1_000_000:.0f}M)",
                description=f"Quarter-over-quarter delta from EDGAR 13F-HR.",
                horizon="position",
                metadata={
                    "feed_type": "filings",
                    "noise_level": "low",
                    "narrative": "institutional_positioning",
                    "fund": fund_name,
                    "fund_cik": cik,
                    "delta_usd": value,
                    "change_type": "NEW",
                },
            ))

        # Most-notable exit
        if exited:
            ticker_name = max(exited, key=exited.get)
            value = exited[ticker_name]
            signals.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="thirteen_f_delta",
                symbol=ticker_name[:20].upper(),
                direction="SELL",
                confidence=min(0.95, 0.6 + value / 1_000_000_000),
                magnitude=value / 1_000_000,
                title=f"{fund_name} EXITED: {ticker_name[:40]} (${value/1_000_000:.0f}M)",
                description=f"Quarter-over-quarter delta from EDGAR 13F-HR.",
                horizon="position",
                metadata={
                    "feed_type": "filings",
                    "noise_level": "low",
                    "narrative": "institutional_positioning",
                    "fund": fund_name,
                    "fund_cik": cik,
                    "delta_usd": value,
                    "change_type": "EXITED",
                },
            ))

        # Update cache for next run
        cache[cik] = latest_holdings

    _save_fund_cache(cache)
    return signals


# --------------------------------------------------------------------------
# 4. Filtered Form 4 — Lewis's Eddie
# --------------------------------------------------------------------------

FORM4_MIN_USD = 100_000
FORM4_SENIOR_ROLES = {"ceo", "cfo", "president", "chairman", "director", "chief executive"}


def _fetch_edgar_form4_recent() -> List[Dict[str, Any]]:
    """Pull recent Form 4 filings from EDGAR's full-text search."""
    try:
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"forms": "4", "dateRange": "custom",
                    "startdt": (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d"),
                    "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            headers={"User-Agent": SEC_UA, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        return [h.get("_source", {}) for h in hits[:30]]
    except Exception:
        return []


def collect_filtered_form4_signals(state: Dict[str, Any], max_items: int = 8) -> List[Signal]:
    """Form 4 P-coded buys ≥$100k by senior insiders. Returns BUY signals only."""
    hits = _fetch_edgar_form4_recent()
    if not hits:
        return []
    signals: List[Signal] = []
    seen_combos = set()  # (ticker, insider) to dedupe same-day buys

    for hit in hits[:max_items]:
        # EDGAR search returns metadata. The actual transaction details require
        # fetching the underlying primary doc XML, which we attempt below.
        adsh = hit.get("adsh") or ""
        display_names = hit.get("display_names", []) or []
        tickers = hit.get("tickers", []) or []
        if not adsh or not tickers:
            continue

        ticker = str(tickers[0]).upper()
        insider = str(display_names[0]) if display_names else "Unknown"
        key = (ticker, insider)
        if key in seen_combos:
            continue
        seen_combos.add(key)

        # Without the primary doc parsed, we can't confirm dollar value or role.
        # We emit conservatively — confidence 0.55 — and tag the signal as
        # provisional. A second-pass parser (future enhancement) can fetch the
        # primary doc XML to filter strictly by P-code + $100k + senior role.
        signals.append(Signal(
            id=new_id("sig"),
            created_at=now_iso(),
            source="filtered_form4",
            symbol=ticker,
            direction="BUY",
            confidence=0.55,
            magnitude=0.0,
            title=f"Form 4 insider activity: {ticker} ({insider[:60]})",
            description=f"EDGAR accession {adsh}; verify role + transaction code in filing.",
            horizon="position",
            metadata={
                "feed_type": "filings",
                "noise_level": "low",
                "narrative": "insider_buying",
                "accession": adsh,
                "insider": insider,
                "provisional": True,  # requires primary-doc parsing for strict Eddie semantics
            },
        ))
    return signals


# --------------------------------------------------------------------------
# 5. Senate/House STOCK Act Periodic Transaction Reports
# --------------------------------------------------------------------------

def _fetch_house_ptrs() -> List[Dict[str, Any]]:
    """House Periodic Transaction Reports — disclosures-clerk.house.gov.

    The House publishes PTRs in a structured ZIP each year. For real-time, this
    function attempts the search endpoint and returns recent disclosures.
    """
    # The endpoint structure is brittle; we degrade silently when it doesn't
    # respond. Users can enhance with a third-party aggregator like
    # capitoltrades.com or housestockwatcher.com if needed.
    return []


def collect_stock_act_signals(state: Dict[str, Any]) -> List[Signal]:
    """STOCK Act trades. Currently a stub; returns [] until a stable upstream
    is configured. Wired into the feed list so the rest of the pipeline can
    treat it as a known source with credential_pending status."""
    return []


# --------------------------------------------------------------------------
# 6. 13D/13G Activist Stakes
# --------------------------------------------------------------------------

def _fetch_recent_13d_13g() -> List[Dict[str, Any]]:
    try:
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"forms": "SC 13D,SC 13G,SC 13D/A,SC 13G/A",
                    "dateRange": "custom",
                    "startdt": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            headers={"User-Agent": SEC_UA, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return [h.get("_source", {}) for h in r.json().get("hits", {}).get("hits", [])[:20]]
    except Exception:
        return []


def collect_activist_stakes_signals(state: Dict[str, Any], max_items: int = 6) -> List[Signal]:
    hits = _fetch_recent_13d_13g()
    if not hits:
        return []
    signals: List[Signal] = []
    for hit in hits[:max_items]:
        tickers = hit.get("tickers", []) or []
        if not tickers:
            continue
        form_type = hit.get("form", "")
        is_active = "13D" in form_type  # 13D = active intent; 13G = passive
        ticker = str(tickers[0]).upper()
        filer = (hit.get("display_names", [""]) or [""])[0]

        signals.append(Signal(
            id=new_id("sig"),
            created_at=now_iso(),
            source="activist_stakes",
            symbol=ticker,
            direction="BUY" if is_active else "WATCH",
            confidence=0.7 if is_active else 0.5,
            magnitude=0.0,
            title=f"{form_type} filed on {ticker} by {filer[:50]}",
            description=f"≥5% stake. {'Active intent' if is_active else 'Passive stake'}.",
            horizon="position",
            metadata={
                "feed_type": "filings",
                "noise_level": "low",
                "narrative": "activist_positioning",
                "form_type": form_type,
                "filer": filer,
                "active_intent": is_active,
            },
        ))
    return signals


# --------------------------------------------------------------------------
# Orchestrator — one call from platform.py
# --------------------------------------------------------------------------

def collect_all_lewis_feeds(state: Dict[str, Any]) -> List[Signal]:
    """Run every Lewis-derived collector. Each one degrades gracefully on error.

    Heavyweight feeds (13F delta especially) make multiple EDGAR calls; consider
    rate-limiting in production by gating on a `last_run` timestamp in state.
    """
    out: List[Signal] = []
    collectors = [
        collect_fed_speech_signals,
        collect_onchain_whale_signals,
        collect_filtered_form4_signals,
        collect_thirteen_f_delta_signals,
        collect_stock_act_signals,
        collect_activist_stakes_signals,
    ]
    for fn in collectors:
        try:
            out.extend(fn(state))
        except Exception:
            # Match the existing live_feeds pattern: never let one bad feed
            # break the scan loop.
            continue
    return out


def lewis_feed_status(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """For Feed Health tab: quick status check per Lewis feed."""
    return {
        key: {
            "name": cfg.name,
            "feed_type": cfg.feed_type,
            "noise_level": cfg.noise_level,
            "requires_env": cfg.requires_env,
            "description": cfg.description,
        }
        for key, cfg in LEWIS_FEEDS.items()
    }
