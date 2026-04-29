from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import os, json, math, re, csv, io, xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests
from app.models import Signal, new_id, now_iso
from app.instrument_map import classify_narrative

UA = os.getenv("SIGNAL_BOT_USER_AGENT", "signal-trading-platform/5.3 contact:local@example.com")
SEC_UA = os.getenv("SEC_USER_AGENT", UA)
TIMEOUT = float(os.getenv("LIVE_FEED_TIMEOUT", "10"))

@dataclass
class FeedConfig:
    key: str
    name: str
    feed_type: str
    requires_env: List[str]

@dataclass
class FeedHealth:
    feed: str
    status: str
    message: str
    count: int = 0
    ts: str = ""
    def __post_init__(self):
        if not self.ts:
            self.ts = now_iso()
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

LIVE_FEEDS: Dict[str, FeedConfig] = {
    "polymarket": FeedConfig("polymarket", "Polymarket", "prediction_market", []),
    "predictit": FeedConfig("predictit", "PredictIt", "prediction_market", []),
    "manifold": FeedConfig("manifold", "Manifold", "prediction_market", []),
    "metaculus": FeedConfig("metaculus", "Metaculus", "forecasting", []),
    "kalshi": FeedConfig("kalshi", "Kalshi", "prediction_market", []),
    "sec_filings": FeedConfig("sec_filings", "SEC Filings", "filings", []),
    "cftc_cot": FeedConfig("cftc_cot", "CFTC COT", "positioning", []),
    "news_rss": FeedConfig("news_rss", "News RSS", "news", []),
    "stooq_market": FeedConfig("stooq_market", "Stooq Market Pulse", "market_data", []),
    "crypto_market": FeedConfig("crypto_market", "Crypto Market Pulse", "crypto_market_data", []),
    "options_flow": FeedConfig("options_flow", "Options Flow", "options", ["POLYGON_API_KEY or MARKETDATA_API_TOKEN or TRADIER_TOKEN"]),
    "gdelt_events": FeedConfig("gdelt_events", "GDELT Global Events", "news", []),
    "fred_macro": FeedConfig("fred_macro", "FRED Macro Pulse", "macro_data", []),
    "treasury_rates": FeedConfig("treasury_rates", "Treasury Yield Pulse", "rates", []),
    "eia_energy": FeedConfig("eia_energy", "EIA Energy Pulse", "energy_data", []),
    "noaa_alerts": FeedConfig("noaa_alerts", "NOAA Weather/Drought Alerts", "weather", []),
    "grid_power": FeedConfig("grid_power", "Power Grid Pulse", "power_grid", []),
    "shipping_events": FeedConfig("shipping_events", "Shipping/Supply Chain Events", "supply_chain", []),
    "bank_of_canada": FeedConfig("bank_of_canada", "Bank of Canada Macro", "canada_macro", []),
}

class FeedAccessLimited(Exception):
    pass

class MissingCredential(Exception):
    pass

class LiveFeedCollector:
    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "application/json,text/xml,text/csv,*/*"})

    def collect_all(self, max_per_feed: int = 25, enabled_feeds: Optional[List[str]] = None) -> Tuple[List[Signal], List[Dict[str, Any]]]:
        signals: List[Signal] = []
        health: List[Dict[str, Any]] = []
        keys = enabled_feeds or list(LIVE_FEEDS.keys())
        collectors = {
            "polymarket": self.collect_polymarket,
            "predictit": self.collect_predictit,
            "manifold": self.collect_manifold,
            "metaculus": self.collect_metaculus,
            "kalshi": self.collect_kalshi,
            "sec_filings": self.collect_sec_filings,
            "cftc_cot": self.collect_cftc_cot,
            "news_rss": self.collect_news_rss,
            "stooq_market": self.collect_stooq_market_pulse,
            "crypto_market": self.collect_crypto_market,
            "binance_crypto": self.collect_crypto_market,
            "options_flow": self.collect_options_flow,
            "gdelt_events": self.collect_gdelt_events,
            "fred_macro": self.collect_fred_macro,
            "treasury_rates": self.collect_treasury_rates,
            "eia_energy": self.collect_eia_energy,
            "noaa_alerts": self.collect_noaa_alerts,
            "grid_power": self.collect_grid_power,
            "shipping_events": self.collect_shipping_events,
            "bank_of_canada": self.collect_bank_of_canada,
        }
        for key in keys:
            cfg = LIVE_FEEDS.get(key)
            if key == "binance_crypto":
                cfg = LIVE_FEEDS["crypto_market"]
            if cfg is None or key not in collectors:
                health.append(FeedHealth(key, "not_supported", "Feed is not in the live-supported registry", 0).to_dict())
                continue
            try:
                rows = collectors[key](max_per_feed=max_per_feed)
                signals.extend(rows)
                status = "live" if rows else "empty"
                msg = f"Collected {len(rows)} live item(s)" if rows else "Endpoint responded but no qualifying live items were found"
                health.append(FeedHealth(cfg.name, status, msg, len(rows)).to_dict())
            except MissingCredential as e:
                health.append(FeedHealth(cfg.name, "credential_pending", str(e), 0).to_dict())
            except FeedAccessLimited as e:
                health.append(FeedHealth(cfg.name, "access_limited", str(e), 0).to_dict())
            except requests.HTTPError as e:
                code = getattr(e.response, "status_code", None)
                if code == 451:
                    health.append(FeedHealth(cfg.name, "geo_blocked", f"Provider returned 451/geographic restriction: {short_err(e)}", 0).to_dict())
                elif code in (401, 403):
                    health.append(FeedHealth(cfg.name, "access_limited", f"Provider returned {code}: {short_err(e)}", 0).to_dict())
                else:
                    health.append(FeedHealth(cfg.name, "error", f"HTTP {code}: {short_err(e)}", 0).to_dict())
            except Exception as e:
                health.append(FeedHealth(cfg.name, "error", f"{type(e).__name__}: {str(e)[:220]}", 0).to_dict())
        self.state["feed_health"] = health
        self.state["active_feed_count"] = sum(1 for h in health if h["status"] == "live")
        return signals, health

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        h = dict(self.session.headers)
        if headers:
            h.update(headers)
        r = self.session.get(url, params=params, timeout=TIMEOUT, headers=h)
        r.raise_for_status()
        return r.json()

    def _signal(self, source: str, symbol: str, direction: str, confidence: float, title: str, desc: str, magnitude: float = 0.0, meta: Optional[Dict[str, Any]] = None) -> Signal:
        meta = meta or {}
        meta.setdefault("narrative", classify_narrative(f"{title} {desc}", symbol))
        meta.setdefault("freshness_minutes", 5)
        meta.setdefault("is_live", True)
        return Signal(new_id("sig"), now_iso(), source, symbol.upper(), direction.upper(), round(max(0.05, min(0.99, confidence)), 3), round(float(magnitude or 0), 3), title, desc, "event", meta)

    def collect_polymarket(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://gamma-api.polymarket.com/markets", {"active":"true", "closed":"false", "limit":max_per_feed, "order":"volume24hr", "ascending":"false"})
        rows = data if isinstance(data, list) else data.get("markets", [])
        out: List[Signal] = []
        for m in rows[:max_per_feed]:
            title = m.get("question") or m.get("title") or m.get("slug") or "Polymarket market"
            vol = as_float(m.get("volume24hr") or m.get("volume"))
            liq = as_float(m.get("liquidity"))
            p = probability_from_market(m)
            out.append(self._signal("Polymarket", infer_symbol(title), "BUY" if p >= 0.5 else "SELL", 0.48 + min(0.18, math.log10(max(vol,1))/25) + min(0.25, abs(p-0.5)), title, f"Live market probability {p:.2%}; 24h volume {vol:,.0f}; liquidity {liq:,.0f}.", abs(p-0.5)*100, {"feed_key":"polymarket", "feed_type":"prediction_market", "probability":p, "volume":vol, "liquidity":liq, "url":m.get("url") or m.get("slug"), "volume_zscore": volume_score(vol)}))
        return out

    def collect_predictit(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://www.predictit.org/api/marketdata/all")
        out: List[Signal] = []
        for market in data.get("markets", [])[:max_per_feed]:
            name = market.get("name", "PredictIt market")
            contracts = market.get("contracts", []) or []
            if not contracts:
                continue
            c = max(contracts, key=lambda x: as_float(x.get("lastTradePrice") or x.get("bestBuyYesCost")))
            p = as_float(c.get("lastTradePrice") or c.get("bestBuyYesCost") or 0.5)
            out.append(self._signal("PredictIt", infer_symbol(name), "BUY" if p >= 0.5 else "SELL", 0.45+abs(p-.5), name, f"Live market. Leading contract: {c.get('name','')} at {p:.2%}.", abs(p-.5)*100, {"feed_key":"predictit", "feed_type":"prediction_market", "probability":p, "url":market.get("url"), "volume_zscore":1.2}))
        return out

    def collect_manifold(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.manifold.markets/v0/markets", {"limit": min(max_per_feed, 100)})
        markets = data if isinstance(data, list) else []
        markets = [m for m in markets if not m.get("isResolved")]
        markets.sort(key=lambda m: (as_float(m.get("volume24Hours")), as_float(m.get("volume")), as_float(m.get("totalLiquidity"))), reverse=True)
        out: List[Signal] = []
        for m in markets[:max_per_feed]:
            title = m.get("question") or "Manifold market"
            p = as_float(m.get("probability") or 0.5)
            vol = as_float(m.get("volume24Hours") or m.get("volume"))
            out.append(self._signal("Manifold", infer_symbol(title), "BUY" if p >= .5 else "SELL", .42+abs(p-.5)+min(.15, vol/10000), title, f"Live probability {p:.2%}; recent/total volume {vol:,.0f}.", abs(p-.5)*100, {"feed_key":"manifold", "feed_type":"prediction_market", "probability":p, "volume":vol, "volume_zscore":volume_score(vol), "url":m.get("url")}))
        return out

    def collect_metaculus(self, max_per_feed: int = 25) -> List[Signal]:
        token = os.getenv("METACULUS_TOKEN") or os.getenv("METACULUS_API_TOKEN")
        headers = {"User-Agent": UA, "Accept":"application/json"}
        if token:
            headers["Authorization"] = f"Token {token}"
        try:
            data = self._get_json("https://www.metaculus.com/api/posts/", {"statuses":"open", "limit":max_per_feed, "order_by":"-activity"}, headers=headers)
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) in (401, 403) and not token:
                raise FeedAccessLimited("Metaculus public API limited this request. Add METACULUS_TOKEN if your account has API access; feed remains visible but not counted as failed.")
            raise
        rows = data.get("results", []) if isinstance(data, dict) else []
        out: List[Signal] = []
        for post in rows[:max_per_feed]:
            title = post.get("title") or post.get("short_title") or "Metaculus forecast"
            p = metaculus_post_probability(post)
            out.append(self._signal("Metaculus", infer_symbol(title), "BUY" if p >= .5 else "SELL", .42+abs(p-.5), title, f"Live open Metaculus post. Approx community probability {p:.2%}.", abs(p-.5)*100, {"feed_key":"metaculus", "feed_type":"forecasting", "probability":p, "url":"https://www.metaculus.com/questions/"+str(post.get('id','')), "volume_zscore":1.0}))
        return out

    def collect_kalshi(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.elections.kalshi.com/trade-api/v2/markets", {"limit":max_per_feed, "status":"open"})
        rows = data.get("markets", []) if isinstance(data, dict) else []
        out: List[Signal] = []
        for m in rows:
            title = m.get("title") or m.get("subtitle") or m.get("ticker") or "Kalshi market"
            yes = as_float(m.get("yes_ask") or m.get("yes_bid") or m.get("last_price") or 50) / 100.0
            vol = as_float(m.get("volume"))
            out.append(self._signal("Kalshi", infer_symbol(title), "BUY" if yes >= .5 else "SELL", .44+abs(yes-.5), title, f"Live public market. Yes price approx {yes:.2%}; volume {vol:,.0f}.", abs(yes-.5)*100, {"feed_key":"kalshi", "feed_type":"prediction_market", "probability":yes, "volume":vol, "volume_zscore":volume_score(vol), "ticker":m.get("ticker")}))
        return out

    def collect_news_rss(self, max_per_feed: int = 25) -> List[Signal]:
        feeds = news_feed_urls()
        out: List[Signal] = []
        errors: List[str] = []
        per = max(1, math.ceil(max_per_feed / max(1, len(feeds))))
        for url in feeds:
            try:
                r = self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA, "Accept":"application/rss+xml,application/atom+xml,application/xml,text/xml,*/*"})
                r.raise_for_status()
                root = ET.fromstring(r.content)
                items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
                for item in items[:per]:
                    title = clean_html(find_text(item, ["title", "{http://www.w3.org/2005/Atom}title"]) or "News headline")
                    desc = clean_html(find_text(item, ["description", "summary", "{http://www.w3.org/2005/Atom}summary"]) or "")[:500]
                    link = find_text(item, ["link", "{http://www.w3.org/2005/Atom}link"])
                    if not link:
                        link_node = item.find("{http://www.w3.org/2005/Atom}link")
                        link = link_node.attrib.get("href") if link_node is not None else None
                    text = f"{title} {desc}"
                    narrative = classify_narrative(text)
                    symbol = infer_symbol(text)
                    out.append(self._signal("News RSS", symbol, narrative_direction(narrative), .53, title, desc, 4.0, {"feed_key":"news_rss", "feed_type":"news", "narrative":narrative, "url":link, "source_url":url, "volume_zscore":1.4}))
                    if len(out) >= max_per_feed:
                        return out
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__} {str(exc)[:80]}")
                continue
        if out:
            return out
        raise RuntimeError("All RSS sources failed or returned no parseable items. " + " | ".join(errors[:4]))

    def collect_stooq_market_pulse(self, max_per_feed: int = 25) -> List[Signal]:
        symbols = stooq_symbols()[:max_per_feed]
        out: List[Signal] = []
        for code, sym in symbols:
            row = fetch_stooq_quote(self.session, code)
            if not row:
                continue
            close = row["last"]
            openp = row.get("open") or close
            vol = row.get("volume") or 0
            chg = ((close/openp)-1)*100 if openp else 0.0
            out.append(self._signal("Stooq Market Pulse", sym, "BUY" if chg >= 0 else "SELL", min(.86, .48+abs(chg)/20), f"{sym} market pulse {chg:+.2f}%", f"Live Stooq quote: open {openp}, last {close}, volume {vol:,.0f}.", abs(chg), {"feed_key":"stooq_market", "feed_type":"market_data", "price":close, "open":openp, "volume":vol, "probability_change_pct":abs(chg), "volume_zscore":volume_score(vol)}))
        return out

    def collect_sec_filings(self, max_per_feed: int = 25) -> List[Signal]:
        headers = {"User-Agent": SEC_UA, "Accept":"application/json,application/atom+xml,application/xml,*/*"}
        tickers = [x.strip().upper() for x in os.getenv("SEC_TICKERS", "AAPL,MSFT,NVDA,TSLA,META,AMZN,GOOGL,AMD,XOM,CVX,JPM,GS,BA,PLTR,COIN,MSTR,VRT,ETN,GLD,SLV").split(",") if x.strip()]
        try:
            mapping = self._get_json("https://www.sec.gov/files/company_tickers.json", headers=headers)
            by_ticker = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in mapping.values()}
            out: List[Signal] = []
            for t in tickers[:max_per_feed]:
                cik = by_ticker.get(t)
                if not cik:
                    continue
                sub = self._get_json(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers)
                recent = sub.get("filings", {}).get("recent", {})
                forms = recent.get("form", []); dates = recent.get("filingDate", []); acc = recent.get("accessionNumber", [])
                if not forms:
                    continue
                form, date, accno = forms[0], dates[0] if dates else "", acc[0] if acc else ""
                mag = 7 if form in {"4", "8-K", "13D", "13G"} else 3
                out.append(self._signal("SEC Filings", t, "BUY" if form in {"4", "13D", "13G"} else "WATCH", .55 if mag > 5 else .45, f"{t} SEC filing {form}", f"Live SEC filing observed: {form} filed {date}.", mag, {"feed_key":"sec_filings", "feed_type":"filings", "form":form, "filing_date":date, "accession":accno, "volume_zscore":1.0}))
            if out:
                return out
        except Exception:
            pass
        return self.collect_sec_current_atom(max_per_feed=max_per_feed, headers=headers)

    def collect_sec_current_atom(self, max_per_feed: int, headers: Dict[str, str]) -> List[Signal]:
        r = self.session.get("https://www.sec.gov/cgi-bin/browse-edgar", params={"action":"getcurrent", "output":"atom", "count":max_per_feed}, timeout=TIMEOUT, headers=headers)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        out: List[Signal] = []
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:max_per_feed]:
            title = clean_html(entry.findtext("{http://www.w3.org/2005/Atom}title") or "SEC current filing")
            summary = clean_html(entry.findtext("{http://www.w3.org/2005/Atom}summary") or "")
            form_match = re.search(r"\b(8-K|10-K|10-Q|4|13D|13G|S-1)\b", title + " " + summary)
            form = form_match.group(1) if form_match else "FILING"
            sym = infer_symbol(title + " " + summary)
            out.append(self._signal("SEC Filings", sym, "BUY" if form in {"4", "13D", "13G"} else "WATCH", .50, f"SEC current filing {form}", title, 3.0, {"feed_key":"sec_filings", "feed_type":"filings", "form":form, "volume_zscore":1.0}))
        return out

    def collect_cftc_cot(self, max_per_feed: int = 25) -> List[Signal]:
        r = self.session.get("https://www.cftc.gov/dea/newcot/f_disagg.txt", timeout=TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
        text = r.text
        out: List[Signal] = []
        patterns = [("CRUDE OIL", "CL", "oil_geopolitics"), ("GOLD", "GC", "precious_metals"), ("SILVER", "SI", "precious_metals"), ("NATURAL GAS", "NG", "energy_infrastructure"), ("NASDAQ", "NQ", "market_stress"), ("S&P", "ES", "market_stress")]
        for name, sym, narr in patterns:
            idx = text.upper().find(name)
            if idx >= 0:
                snippet = text[idx:idx+650]
                out.append(self._signal("CFTC COT", sym, "WATCH", .50, f"CFTC COT positioning available for {name}", snippet[:350], 3.0, {"feed_key":"cftc_cot", "feed_type":"positioning", "narrative":narr, "volume_zscore":1.0}))
        return out[:max_per_feed]

    def collect_crypto_market(self, max_per_feed: int = 25) -> List[Signal]:
        errors: List[str] = []
        for fn in (self._collect_binance_crypto, self._collect_kraken_crypto, self._collect_coingecko_crypto):
            try:
                rows = fn(max_per_feed)
                if rows:
                    return rows
            except Exception as exc:
                errors.append(f"{fn.__name__}: {type(exc).__name__} {str(exc)[:90]}")
        raise RuntimeError("All crypto market providers failed. " + " | ".join(errors))

    def _collect_binance_crypto(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.binance.com/api/v3/ticker/24hr")
        wanted = {"BTCUSDT":"BTC", "ETHUSDT":"ETH", "SOLUSDT":"SOL"}
        out: List[Signal] = []
        for row in data:
            if row.get("symbol") in wanted:
                sym = wanted[row["symbol"]]
                chg = as_float(row.get("priceChangePercent")); qvol = as_float(row.get("quoteVolume"))
                out.append(self._signal("Crypto Market Pulse", sym, "BUY" if chg >= 0 else "SELL", min(.85, .48+abs(chg)/30), f"{sym} crypto liquidity move {chg:+.2f}%", f"Live Binance 24h ticker. Quote volume {qvol:,.0f}.", abs(chg), {"feed_key":"crypto_market", "feed_type":"crypto_market_data", "provider":"binance", "volume":qvol, "probability_change_pct":abs(chg), "volume_zscore":volume_score(qvol)}))
        return out[:max_per_feed]

    def _collect_kraken_crypto(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.kraken.com/0/public/Ticker", {"pair":"XBTUSD,ETHUSD,SOLUSD"})
        result = data.get("result", {}) if isinstance(data, dict) else {}
        aliases = {"XXBTZUSD":"BTC", "XBTUSD":"BTC", "XETHZUSD":"ETH", "ETHUSD":"ETH", "SOLUSD":"SOL"}
        out: List[Signal] = []
        for key, row in result.items():
            sym = aliases.get(key, key.replace("ZUSD", "").replace("X", ""))
            last = as_float((row.get("c") or [0])[0])
            openp = as_float(row.get("o"), last)
            vol = as_float((row.get("v") or [0,0])[1])
            chg = ((last/openp)-1)*100 if openp else 0
            out.append(self._signal("Crypto Market Pulse", sym, "BUY" if chg >= 0 else "SELL", min(.85, .48+abs(chg)/30), f"{sym} crypto liquidity move {chg:+.2f}%", f"Live Kraken ticker. Last {last}; 24h volume {vol:,.0f}.", abs(chg), {"feed_key":"crypto_market", "feed_type":"crypto_market_data", "provider":"kraken", "volume":vol, "price":last, "probability_change_pct":abs(chg), "volume_zscore":volume_score(vol)}))
        return out[:max_per_feed]

    def _collect_coingecko_crypto(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.coingecko.com/api/v3/simple/price", {"ids":"bitcoin,ethereum,solana", "vs_currencies":"usd", "include_24hr_change":"true", "include_24hr_vol":"true"})
        mapping = {"bitcoin":"BTC", "ethereum":"ETH", "solana":"SOL"}
        out: List[Signal] = []
        for coin, sym in mapping.items():
            row = data.get(coin, {}) if isinstance(data, dict) else {}
            chg = as_float(row.get("usd_24h_change")); vol = as_float(row.get("usd_24h_vol")); price = as_float(row.get("usd"))
            out.append(self._signal("Crypto Market Pulse", sym, "BUY" if chg >= 0 else "SELL", min(.85, .48+abs(chg)/30), f"{sym} crypto liquidity move {chg:+.2f}%", f"Live CoinGecko ticker. Last {price}; 24h volume {vol:,.0f}.", abs(chg), {"feed_key":"crypto_market", "feed_type":"crypto_market_data", "provider":"coingecko", "volume":vol, "price":price, "probability_change_pct":abs(chg), "volume_zscore":volume_score(vol)}))
        return out[:max_per_feed]

    def collect_gdelt_events(self, max_per_feed: int = 25) -> List[Signal]:
        query = os.getenv("GDELT_QUERY", "(oil OR energy OR sanctions OR war OR conflict OR drought OR datacenter OR data center OR power grid OR nuclear OR shipping OR tanker OR semiconductor OR rates OR inflation)")
        data = self._get_json("https://api.gdeltproject.org/api/v2/doc/doc", {"query": query, "mode":"ArtList", "format":"json", "maxrecords":min(max_per_feed, 50), "sort":"hybridrel"})
        articles = data.get("articles", []) if isinstance(data, dict) else []
        out: List[Signal] = []
        for a in articles[:max_per_feed]:
            title = clean_html(a.get("title") or "GDELT global event")
            desc = clean_html((a.get("seendate") or "") + " " + (a.get("sourceCountry") or "") + " " + (a.get("domain") or ""))
            text = f"{title} {desc}"
            narr = classify_narrative(text)
            out.append(self._signal("GDELT Global Events", infer_symbol(text), narrative_direction(narr), .54, title, desc, 5.0, {"feed_key":"gdelt_events", "feed_type":"news", "narrative":narr, "url":a.get("url"), "domain":a.get("domain"), "country":a.get("sourceCountry"), "volume_zscore":1.6}))
        return out

    def collect_fred_macro(self, max_per_feed: int = 25) -> List[Signal]:
        series = [x.strip().upper() for x in os.getenv("FRED_SERIES", "DGS10,DGS2,T10Y2Y,DFF,DTWEXBGS,DEXUSEU,DEXCAUS,BAMLH0A0HYM2").split(",") if x.strip()]
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + ",".join(series)
        r = self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
        if len(rows) < 2: return []
        latest, prev = rows[-1], rows[-2]
        out: List[Signal] = []
        for sid in series[:max_per_feed]:
            cur = as_float(latest.get(sid), None); old = as_float(prev.get(sid), None)
            if cur is None or old is None or latest.get(sid) in {".", ""} or prev.get(sid) in {".", ""}: continue
            delta = cur - old
            narr = "rate_cuts" if sid in {"DGS10", "DGS2", "T10Y2Y", "DFF"} else "market_stress"
            direction = "BUY" if (sid in {"T10Y2Y", "DFF"} and delta < 0) or (sid == "BAMLH0A0HYM2" and delta < 0) else "SELL" if abs(delta) > 0 else "WATCH"
            out.append(self._signal("FRED Macro Pulse", "TLT" if narr=="rate_cuts" else "SPY", direction, min(.80, .50 + min(.25, abs(delta)/2)), f"{sid} macro move {delta:+.3f}", f"FRED latest {latest.get('observation_date')}: {sid}={cur}; prior={old}.", abs(delta)*10, {"feed_key":"fred_macro", "feed_type":"macro_data", "series":sid, "current":cur, "previous":old, "delta":delta, "narrative":narr, "volume_zscore":1.2}))
        return out

    def collect_treasury_rates(self, max_per_feed: int = 25) -> List[Signal]:
        now = datetime.now(timezone.utc)
        months = [(now.year, now.month), (now.year if now.month > 1 else now.year-1, now.month-1 if now.month > 1 else 12)]
        root = None
        for y, m in months:
            url = f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month={y}{m:02d}"
            r = self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA, "Accept":"application/xml,text/xml,*/*"})
            if r.status_code == 200 and r.content:
                root = ET.fromstring(r.content); break
        if root is None: return []
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        if not entries: return []
        text = ET.tostring(entries[-1], encoding="unicode")
        vals = {name: extract_xml_float(text, name) for name in ["BC_2YEAR", "BC_10YEAR", "BC_30YEAR", "BC_3MONTH"]}
        out: List[Signal] = []
        if vals.get("BC_10YEAR") is not None and vals.get("BC_2YEAR") is not None:
            spread = vals["BC_10YEAR"] - vals["BC_2YEAR"]
            direction = "BUY" if spread > -0.25 else "SELL"
            out.append(self._signal("Treasury Yield Pulse", "TLT", direction, .58 + min(.18, abs(spread)/3), f"2Y/10Y yield spread {spread:+.2f}", f"Latest Treasury curve: 2Y={vals['BC_2YEAR']}, 10Y={vals['BC_10YEAR']}, 30Y={vals.get('BC_30YEAR')}.", abs(spread)*10, {"feed_key":"treasury_rates", "feed_type":"rates", "narrative":"rate_cuts", "spread_2s10s":spread, "volume_zscore":1.3}))
        return out[:max_per_feed]

    def collect_eia_energy(self, max_per_feed: int = 25) -> List[Signal]:
        return self._collect_rss_bundle("EIA Energy Pulse", "eia_energy", "energy_data", energy_feed_urls(), max_per_feed, default_narrative="energy_infrastructure")

    def collect_grid_power(self, max_per_feed: int = 25) -> List[Signal]:
        return self._collect_rss_bundle("Power Grid Pulse", "grid_power", "power_grid", grid_feed_urls(), max_per_feed, default_narrative="energy_infrastructure")

    def _collect_rss_bundle(self, source: str, feed_key: str, feed_type: str, feeds: List[str], max_per_feed: int, default_narrative: str) -> List[Signal]:
        out: List[Signal] = []; errors: List[str] = []
        per = max(1, math.ceil(max_per_feed / max(1, len(feeds))))
        for url in feeds:
            try:
                r = self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA, "Accept":"application/rss+xml,application/xml,text/xml,*/*"})
                r.raise_for_status(); root = ET.fromstring(r.content)
                items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
                for item in items[:per]:
                    title = clean_html(find_text(item, ["title", "{http://www.w3.org/2005/Atom}title"]) or source)
                    desc = clean_html(find_text(item, ["description", "summary", "{http://www.w3.org/2005/Atom}summary"]) or "")[:500]
                    text = f"{title} {desc}"
                    narr = classify_narrative(text)
                    if narr == "single_name": narr = default_narrative
                    out.append(self._signal(source, infer_symbol(text), narrative_direction(narr), .55, title, desc, 5.0, {"feed_key":feed_key, "feed_type":feed_type, "narrative":narr, "source_url":url, "volume_zscore":1.5}))
                    if len(out) >= max_per_feed: return out
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__} {str(exc)[:80]}"); continue
        if out: return out
        raise RuntimeError(f"All {source} public feeds failed. " + " | ".join(errors[:4]))

    def collect_noaa_alerts(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.weather.gov/alerts/active", {"status":"actual", "message_type":"alert", "limit":min(max_per_feed, 50)}, {"User-Agent": UA, "Accept":"application/geo+json,application/json"})
        features = data.get("features", []) if isinstance(data, dict) else []
        out: List[Signal] = []
        for f in features[:max_per_feed]:
            props = f.get("properties", {}) if isinstance(f, dict) else {}
            title = props.get("headline") or props.get("event") or "NOAA alert"
            severity = str(props.get("severity") or "").lower(); area = props.get("areaDesc") or ""
            text = f"{title} {area} {props.get('description','')}"
            narr = "energy_infrastructure" if any(x in text.lower() for x in ["heat", "winter", "storm", "hurricane", "fire"]) else "water_infrastructure" if any(x in text.lower() for x in ["drought", "flood"]) else classify_narrative(text)
            conf = .54 + (.12 if severity in {"severe", "extreme"} else .04)
            out.append(self._signal("NOAA Weather/Drought Alerts", infer_symbol(text), narrative_direction(narr), conf, title, area, 6.0 if severity in {"severe","extreme"} else 3.0, {"feed_key":"noaa_alerts", "feed_type":"weather", "narrative":narr, "severity":severity, "volume_zscore":1.4}))
        return out

    def collect_shipping_events(self, max_per_feed: int = 25) -> List[Signal]:
        query = os.getenv("SHIPPING_GDELT_QUERY", "(shipping OR tanker OR freight OR port congestion OR Red Sea OR Suez OR Panama Canal OR supply chain OR container) (oil OR energy OR trade OR disruption)")
        data = self._get_json("https://api.gdeltproject.org/api/v2/doc/doc", {"query":query, "mode":"ArtList", "format":"json", "maxrecords":min(max_per_feed, 50), "sort":"hybridrel"})
        articles = data.get("articles", []) if isinstance(data, dict) else []
        out: List[Signal] = []
        for a in articles[:max_per_feed]:
            title = clean_html(a.get("title") or "Shipping event")
            desc = clean_html((a.get("sourceCountry") or "") + " " + (a.get("domain") or ""))
            text = f"{title} {desc}"
            narr = "oil_geopolitics" if any(x in text.lower() for x in ["tanker", "oil", "red sea", "suez"]) else "market_stress"
            out.append(self._signal("Shipping/Supply Chain Events", infer_symbol(text), narrative_direction(narr), .54, title, desc, 5.0, {"feed_key":"shipping_events", "feed_type":"supply_chain", "narrative":narr, "url":a.get("url"), "domain":a.get("domain"), "volume_zscore":1.5}))
        return out

    def collect_bank_of_canada(self, max_per_feed: int = 25) -> List[Signal]:
        series = [x.strip().upper() for x in os.getenv("BOC_SERIES", "FXUSDCAD,V39079,V39065,V39063").split(",") if x.strip()]
        data = self._get_json("https://www.bankofcanada.ca/valet/observations/" + ",".join(series) + "/json", {"recent":5})
        obs = data.get("observations", []) if isinstance(data, dict) else []
        if len(obs) < 2: return []
        latest, prev = obs[-1], obs[-2]
        out: List[Signal] = []
        for sid in series[:max_per_feed]:
            cur = as_float((latest.get(sid) or {}).get("v"), None); old = as_float((prev.get(sid) or {}).get("v"), None)
            if cur is None or old is None: continue
            delta = cur - old; sym = "CAD" if sid.startswith("FX") else "TLT"
            direction = "BUY" if delta > 0 and sid.startswith("FX") else "SELL" if abs(delta) > 0 else "WATCH"
            out.append(self._signal("Bank of Canada Macro", sym, direction, min(.80, .50+min(.22, abs(delta)/2)), f"{sid} Canada macro move {delta:+.4f}", f"Bank of Canada Valet latest {latest.get('d')}: {sid}={cur}; prior={old}.", abs(delta)*10, {"feed_key":"bank_of_canada", "feed_type":"canada_macro", "series":sid, "current":cur, "previous":old, "delta":delta, "narrative":"rate_cuts", "volume_zscore":1.2}))
        return out

    def collect_options_flow(self, max_per_feed: int = 25) -> List[Signal]:
        provider = os.getenv("OPTIONS_PROVIDER", "polygon").strip().lower()
        providers = [provider] + [p for p in ["polygon", "marketdata", "tradier"] if p != provider]
        errors = []
        for p in providers:
            try:
                if p == "polygon" and os.getenv("POLYGON_API_KEY"):
                    rows = self._collect_polygon_options(max_per_feed)
                    if rows: return rows
                    errors.append("Polygon returned no qualifying options-flow rows")
                elif p == "marketdata" and os.getenv("MARKETDATA_API_TOKEN"):
                    rows = self._collect_marketdata_options(max_per_feed)
                    if rows: return rows
                    errors.append("MarketData.app returned no qualifying options-flow rows")
                elif p == "tradier" and os.getenv("TRADIER_TOKEN"):
                    rows = self._collect_tradier_options(max_per_feed)
                    if rows: return rows
                    errors.append("Tradier returned no qualifying options-flow rows")
            except Exception as exc:
                errors.append(f"{p}: {exc}")
        raise MissingCredential("Options flow is live-capable, but no configured provider returned usable rows. Set POLYGON_API_KEY, MARKETDATA_API_TOKEN, or TRADIER_TOKEN. " + "; ".join(errors[-3:]))

    def _collect_tradier_options(self, max_per_feed: int) -> List[Signal]:
        token = os.environ["TRADIER_TOKEN"]
        base = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        underlyings = os.getenv("OPTIONS_UNDERLYINGS", "SPY,QQQ,NVDA,TSLA,XLE,USO,GLD,SLV,VRT,ETN").split(",")
        out: List[Signal] = []
        for sym in [s.strip().upper() for s in underlyings if s.strip()]:
            exp_data = self._get_json(f"{base}/markets/options/expirations", {"symbol": sym, "includeAllRoots":"true", "strikes":"false"}, headers)
            exps = exp_data.get("expirations", {}).get("date", []) if isinstance(exp_data, dict) else []
            if isinstance(exps, str): exps = [exps]
            if not exps: continue
            chain = self._get_json(f"{base}/markets/options/chains", {"symbol": sym, "expiration": exps[0], "greeks":"true"}, headers)
            options = chain.get("options", {}).get("option", []) if isinstance(chain, dict) else []
            if isinstance(options, dict): options = [options]
            scored = []
            for opt in options:
                vol = as_float(opt.get("volume")); oi = max(1.0, as_float(opt.get("open_interest")))
                ratio = vol / oi; bid = as_float(opt.get("bid")); ask = as_float(opt.get("ask")); last = as_float(opt.get("last"))
                if vol <= 0 or ask <= 0: continue
                scored.append((ratio, vol, opt, bid, ask, last))
            for ratio, vol, opt, bid, ask, last in sorted(scored, reverse=True)[:2]:
                right = str(opt.get("option_type", "call")).lower(); direction = "BUY" if right == "call" else "SELL"
                strike = opt.get("strike"); expiration = opt.get("expiration_date") or exps[0]
                desc = f"Live Tradier option chain: {right} {strike} exp {expiration}; volume {vol:,.0f}; volume/open-interest {ratio:.2f}; bid {bid}; ask {ask}; last {last}."
                out.append(self._signal("Tradier Options Flow", sym, direction, min(.88, .50 + min(.30, ratio/8) + min(.08, vol/5000)), f"{sym} unusual {right} activity", desc, min(100, ratio*10), {"feed_key":"options_flow", "feed_type":"options", "provider":"tradier", "option_type":right, "strike":strike, "expiration":expiration, "volume":vol, "open_interest":opt.get("open_interest"), "volume_oi_ratio":ratio, "volume_zscore":min(8, max(1, ratio))}))
                if len(out) >= max_per_feed: return out
        return out

    def _collect_marketdata_options(self, max_per_feed: int) -> List[Signal]:
        token = os.environ["MARKETDATA_API_TOKEN"]
        underlyings = os.getenv("OPTIONS_UNDERLYINGS", "SPY,QQQ,NVDA,TSLA,XLE,USO,GLD,SLV,VRT,ETN").split(",")
        out: List[Signal] = []
        for sym in [s.strip().upper() for s in underlyings if s.strip()]:
            data = self._get_json(f"https://api.marketdata.app/v1/options/chain/{sym}/", {"token": token})
            for ratio, vol, opt in score_option_rows(normalize_marketdata_chain(data))[:2]:
                right = str(opt.get("side") or opt.get("type") or opt.get("optionType") or "call").lower()
                direction = "BUY" if right.startswith("c") else "SELL"
                strike = opt.get("strike") or opt.get("strikePrice"); expiration = opt.get("expiration") or opt.get("expirationDate")
                desc = f"Live MarketData.app option chain: {right} {strike} exp {expiration}; volume {vol:,.0f}; volume/open-interest {ratio:.2f}."
                out.append(self._signal("MarketData.app Options Flow", sym, direction, min(.88, .50 + min(.30, ratio/8) + min(.08, vol/5000)), f"{sym} unusual {right} activity", desc, min(100, ratio*10), {"feed_key":"options_flow", "feed_type":"options", "provider":"marketdata", "option_type":right, "strike":strike, "expiration":expiration, "volume":vol, "open_interest":opt.get("openInterest") or opt.get("open_interest"), "volume_oi_ratio":ratio, "volume_zscore":min(8, max(1, ratio))}))
                if len(out) >= max_per_feed: return out
        return out

    def _collect_polygon_options(self, max_per_feed: int) -> List[Signal]:
        key = os.environ["POLYGON_API_KEY"]
        underlyings = os.getenv("OPTIONS_UNDERLYINGS", "SPY,QQQ,NVDA,TSLA,XLE,USO,GLD,SLV,VRT,ETN").split(",")
        out: List[Signal] = []
        for sym in [s.strip().upper() for s in underlyings if s.strip()]:
            data = self._get_json(f"https://api.polygon.io/v3/snapshot/options/{sym}", {"apiKey": key, "limit": max_per_feed})
            rows = data.get("results", []) if isinstance(data, dict) else []
            scored = []
            for row in rows:
                day = row.get("day", {}) or {}; details = row.get("details", {}) or {}
                vol = as_float(day.get("volume")); oi = max(1.0, as_float(row.get("open_interest")))
                if vol <= 0: continue
                scored.append((vol/oi, vol, row, details))
            for ratio, vol, row, details in sorted(scored, reverse=True)[:2]:
                right = str(details.get("contract_type", "call")).lower(); direction = "BUY" if right == "call" else "SELL"
                strike = details.get("strike_price"); expiration = details.get("expiration_date")
                desc = f"Live Polygon option snapshot: {right} {strike} exp {expiration}; volume {vol:,.0f}; volume/open-interest {ratio:.2f}."
                out.append(self._signal("Polygon Options Flow", sym, direction, min(.88, .50 + min(.30, ratio/8) + min(.08, vol/5000)), f"{sym} unusual {right} activity", desc, min(100, ratio*10), {"feed_key":"options_flow", "feed_type":"options", "provider":"polygon", "option_type":right, "strike":strike, "expiration":expiration, "volume":vol, "open_interest":row.get("open_interest"), "volume_oi_ratio":ratio, "volume_zscore":min(8, max(1, ratio))}))
                if len(out) >= max_per_feed: return out
        return out

def short_err(e: Exception) -> str:
    return str(e).replace("\n", " ")[:180]

def find_text(node: ET.Element, names: List[str]) -> Optional[str]:
    for name in names:
        child = node.find(name)
        if child is not None and child.text:
            return child.text
    return None

def normalize_marketdata_chain(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict): return []
    if isinstance(data.get("results"), list): return [x for x in data.get("results", []) if isinstance(x, dict)]
    columns = ["optionSymbol", "expiration", "strike", "side", "bid", "ask", "last", "volume", "openInterest"]
    lengths = [len(data.get(c, [])) for c in columns if isinstance(data.get(c), list)]
    if not lengths: return []
    rows: List[Dict[str, Any]] = []
    for i in range(max(lengths)):
        row: Dict[str, Any] = {}
        for c in columns:
            values = data.get(c)
            if isinstance(values, list) and i < len(values): row[c] = values[i]
        rows.append(row)
    return rows

def score_option_rows(rows: List[Dict[str, Any]]) -> List[Tuple[float, float, Dict[str, Any]]]:
    scored: List[Tuple[float, float, Dict[str, Any]]] = []
    for opt in rows:
        vol = as_float(opt.get("volume")); oi = max(1.0, as_float(opt.get("openInterest") or opt.get("open_interest")))
        if vol > 0: scored.append((vol/oi, vol, opt))
    return sorted(scored, reverse=True)

def as_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "": return default
        return float(x)
    except Exception:
        return default

def volume_score(volume: float) -> float:
    return round(min(8.0, max(1.0, math.log10(max(float(volume), 10.0))/2.0)), 2)

def probability_from_market(m: Dict[str, Any]) -> float:
    prices = m.get("outcomePrices") or m.get("outcomesPrices") or []
    if isinstance(prices, str):
        try: prices = json.loads(prices)
        except Exception: prices = []
    try:
        nums = [float(x) for x in prices]
        return max(nums) if nums else 0.5
    except Exception:
        return 0.5

def metaculus_post_probability(post: Dict[str, Any]) -> float:
    vals: List[float] = []
    wanted = {"q2", "probability", "community_prediction", "recency_weighted", "metaculus_prediction"}
    def walk(obj: Any, depth: int = 0):
        if depth > 5: return
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in wanted and isinstance(v, (int, float, str)):
                    f = as_float(v, -1)
                    if 0 <= f <= 1: vals.append(f)
                elif lk in wanted and isinstance(v, dict):
                    for kk in ["q2", "median", "probability"]:
                        f = as_float(v.get(kk), -1)
                        if 0 <= f <= 1: vals.append(f)
                walk(v, depth+1)
        elif isinstance(obj, list):
            for x in obj[:10]: walk(x, depth+1)
    walk(post)
    return vals[0] if vals else 0.5

def clean_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&amp;", "&").strip()

def infer_symbol(text: str) -> str:
    t = text.lower()
    rules = [
        (["oil", "crude", "opec", "venezuela", "iran", "tanker"], "CL"),
        (["natural gas", "lng", "pipeline", "power grid", "data center power"], "NG"),
        (["gold", "safe haven"], "GLD"), (["silver"], "SLV"),
        (["fed", "rate", "inflation", "cpi", "treasury", "bond"], "TLT"),
        (["bitcoin", "crypto", "ethereum", "stablecoin"], "BTC"),
        (["nvidia", "gpu", "semiconductor", "chip", "ai"], "NVDA"),
        (["data center", "cooling", "power demand", "grid"], "VRT"),
        (["water", "drought", "desalination"], "PHO"),
        (["taiwan", "tsmc"], "TSM"),
        (["bank", "credit", "liquidity", "recession", "vix"], "SPY"),
    ]
    for words, sym in rules:
        if any(w in t for w in words): return sym
    return "SPY"

def narrative_direction(narr: str) -> str:
    return {"oil_geopolitics":"BUY", "rate_cuts":"BUY", "ai_policy":"SELL", "crypto_regulation":"BUY", "taiwan_risk":"SELL", "market_stress":"SELL", "precious_metals":"BUY", "energy_infrastructure":"BUY", "water_infrastructure":"BUY", "data_center_infrastructure":"BUY"}.get(narr, "WATCH")

def extract_xml_float(text: str, tag: str) -> Optional[float]:
    m = re.search(rf"<(?:[^:<>]+:)?{tag}[^>]*>([^<]+)</(?:[^:<>]+:)?{tag}>", text)
    if not m: return None
    return as_float(m.group(1), None)

def energy_feed_urls() -> List[str]:
    raw = os.getenv("EIA_RSS_URLS") or os.getenv("ENERGY_RSS_URLS")
    if raw: return [x.strip() for x in raw.split(",") if x.strip()]
    return ["https://www.eia.gov/rss/todayinenergy.xml", "https://www.eia.gov/rss/petroleum.xml", "https://www.eia.gov/rss/naturalgas.xml", "https://www.eia.gov/rss/electricity.xml"]

def grid_feed_urls() -> List[str]:
    raw = os.getenv("GRID_RSS_URLS")
    if raw: return [x.strip() for x in raw.split(",") if x.strip()]
    return ["https://www.eia.gov/rss/electricity.xml", "https://www.ercot.com/news/rss", "https://www.caiso.com/Documents/RSSFeed.xml"]

def news_feed_urls() -> List[str]:
    raw = os.getenv("NEWS_RSS_URLS")
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,NVDA,TSLA,XLE,GLD,SLV&region=US&lang=en-US",
        "https://www.marketwatch.com/rss/topstories",
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.cftc.gov/PressRoom/PressReleases/rss.xml",
        "https://www.sec.gov/news/pressreleases.rss",
        "https://www.investing.com/rss/news_25.rss",
        "https://www.investing.com/rss/news_301.rss",
    ]

def stooq_symbols() -> List[Tuple[str, str]]:
    raw = os.getenv("STOOQ_SYMBOLS")
    if raw:
        pairs = []
        for chunk in raw.split(","):
            if ":" in chunk: code, sym = chunk.split(":", 1)
            else: code, sym = chunk, chunk.split(".")[0]
            pairs.append((code.strip().lower(), sym.strip().upper()))
        return pairs
    syms = ["spy","qqq","iwm","tlt","gld","slv","iau","sivr","sgol","gdx","sil","uso","ung","xle","vde","oih","icln","tan","ura","urnm","nlr","vrt","jci","tt","carr","etn","xyl","awk","pho","cgw","eqix","dlr","xom","cvx","nvda","amd","tsla","coin","mstr"]
    return [(f"{s}.us", s.upper()) for s in syms]

def fetch_stooq_quote(session: requests.Session, stooq_code: str) -> Optional[Dict[str, float]]:
    url = f"https://stooq.com/q/l/?s={stooq_code}&f=sd2t2ohlcv&h&e=csv"
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows: return None
    row = rows[0]
    last = as_float(row.get("Close") or row.get("Last"))
    if last <= 0: return None
    return {"last": last, "open": as_float(row.get("Open"), last), "high": as_float(row.get("High"), last), "low": as_float(row.get("Low"), last), "volume": as_float(row.get("Volume"))}

def collect_live_signals(state: Dict[str, Any], max_per_feed: int = 25, enabled_feeds: Optional[List[str]] = None) -> Tuple[List[Signal], List[Dict[str, Any]]]:
    return LiveFeedCollector(state).collect_all(max_per_feed=max_per_feed, enabled_feeds=enabled_feeds)
