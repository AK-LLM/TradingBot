from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import os, json, math, re, csv, io, xml.etree.ElementTree as ET
import requests
from app.models import Signal, new_id, now_iso
from app.instrument_map import classify_narrative

UA = os.getenv("SIGNAL_BOT_USER_AGENT", "signal-trading-platform-live contact:local")
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
    "binance_crypto": FeedConfig("binance_crypto", "Binance Crypto Pulse", "crypto_market_data", []),
    "options_flow": FeedConfig("options_flow", "Options Flow", "options", ["TRADIER_TOKEN or POLYGON_API_KEY"]),
}

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
            "binance_crypto": self.collect_binance_crypto,
            "options_flow": self.collect_options_flow,
        }
        for key in keys:
            cfg = LIVE_FEEDS.get(key)
            if cfg is None:
                health.append(FeedHealth(key, "disabled", "Feed is not in the live-supported registry", 0).to_dict())
                continue
            try:
                rows = collectors[key](max_per_feed=max_per_feed)
                signals.extend(rows)
                status = "live" if rows else "empty"
                msg = f"Collected {len(rows)} live item(s)" if rows else "Endpoint responded but no qualifying live items were found"
                health.append(FeedHealth(cfg.name, status, msg, len(rows)).to_dict())
            except MissingCredential as e:
                health.append(FeedHealth(cfg.name, "auth_required", str(e), 0).to_dict())
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
            direction = "BUY" if p >= 0.5 else "SELL"
            confidence = 0.48 + min(0.18, math.log10(max(vol,1))/25) + min(0.25, abs(p-0.5))
            out.append(self._signal("Polymarket", infer_symbol(title), direction, confidence, title, f"Live market probability {p:.2%}; 24h volume {vol:,.0f}; liquidity {liq:,.0f}.", abs(p-0.5)*100, {"feed_key":"polymarket", "feed_type":"prediction_market", "probability":p, "volume":vol, "liquidity":liq, "url":m.get("url") or m.get("slug"), "volume_zscore": volume_score(vol)}))
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
        data = self._get_json("https://api.manifold.markets/v0/markets", {"limit":max_per_feed, "sort":"24-hour-vol"})
        out: List[Signal] = []
        for m in data if isinstance(data, list) else []:
            title = m.get("question") or "Manifold market"
            p = as_float(m.get("probability") or 0.5)
            vol = as_float(m.get("volume24Hours"))
            out.append(self._signal("Manifold", infer_symbol(title), "BUY" if p >= .5 else "SELL", .42+abs(p-.5)+min(.15, vol/10000), title, f"Live probability {p:.2%}; 24h volume {vol:,.0f}.", abs(p-.5)*100, {"feed_key":"manifold", "feed_type":"prediction_market", "probability":p, "volume":vol, "volume_zscore":volume_score(vol), "url":m.get("url")}))
        return out

    def collect_metaculus(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://www.metaculus.com/api2/questions/", {"limit":max_per_feed, "order_by":"-activity"})
        rows = data.get("results", []) if isinstance(data, dict) else []
        out: List[Signal] = []
        for q in rows[:max_per_feed]:
            title = q.get("title") or q.get("question") or "Metaculus question"
            p = metaculus_probability(q)
            out.append(self._signal("Metaculus", infer_symbol(title), "BUY" if p >= .5 else "SELL", .42+abs(p-.5), title, f"Live active forecast. Approx community probability {p:.2%}.", abs(p-.5)*100, {"feed_key":"metaculus", "feed_type":"forecasting", "probability":p, "url":"https://www.metaculus.com/questions/"+str(q.get('id','')), "volume_zscore":1.0}))
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
        per = max(1, math.ceil(max_per_feed / max(1, len(feeds))))
        for url in feeds:
            r = self.session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA, "Accept":"application/rss+xml,application/xml,text/xml,*/*"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for item in root.findall(".//item")[:per]:
                title = clean_html(item.findtext("title") or "News headline")
                desc = clean_html(item.findtext("description") or "")[:500]
                text = f"{title} {desc}"
                narrative = classify_narrative(text)
                symbol = infer_symbol(text)
                direction = narrative_direction(narrative)
                out.append(self._signal("News RSS", symbol, direction, .53, title, desc, 4.0, {"feed_key":"news_rss", "feed_type":"news", "narrative":narrative, "url":item.findtext("link"), "volume_zscore":1.4}))
                if len(out) >= max_per_feed:
                    return out
        return out

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
            direction = "BUY" if chg >= 0 else "SELL"
            out.append(self._signal("Stooq Market Pulse", sym, direction, min(.86, .48+abs(chg)/20), f"{sym} market pulse {chg:+.2f}%", f"Live Stooq quote: open {openp}, last {close}, volume {vol:,.0f}.", abs(chg), {"feed_key":"stooq_market", "feed_type":"market_data", "price":close, "open":openp, "volume":vol, "probability_change_pct":abs(chg), "volume_zscore":volume_score(vol)}))
        return out

    def collect_sec_filings(self, max_per_feed: int = 25) -> List[Signal]:
        tickers = os.getenv("SEC_TICKERS", "AAPL,MSFT,NVDA,TSLA,META,AMZN,GOOGL,AMD,XOM,CVX,JPM,GS,BA,PLTR,COIN,MSTR,VRT,ETN,GLD,SLV").split(",")
        mapping = self._get_json("https://www.sec.gov/files/company_tickers.json")
        by_ticker = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in mapping.values()}
        out: List[Signal] = []
        for t in [x.strip().upper() for x in tickers if x.strip()][:max_per_feed]:
            cik = by_ticker.get(t)
            if not cik:
                continue
            sub = self._get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
            recent = sub.get("filings", {}).get("recent", {})
            forms = recent.get("form", []); dates = recent.get("filingDate", []); acc = recent.get("accessionNumber", [])
            if not forms:
                continue
            form, date, accno = forms[0], dates[0] if dates else "", acc[0] if acc else ""
            mag = 7 if form in {"4", "8-K", "13D", "13G"} else 3
            out.append(self._signal("SEC Filings", t, "BUY" if form in {"4", "13D", "13G"} else "WATCH", .55 if mag > 5 else .45, f"{t} SEC filing {form}", f"Live SEC filing observed: {form} filed {date}.", mag, {"feed_key":"sec_filings", "feed_type":"filings", "form":form, "filing_date":date, "accession":accno, "volume_zscore":1.0}))
        return out

    def collect_cftc_cot(self, max_per_feed: int = 25) -> List[Signal]:
        r = self.session.get("https://www.cftc.gov/dea/newcot/f_disagg.txt", timeout=TIMEOUT)
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

    def collect_binance_crypto(self, max_per_feed: int = 25) -> List[Signal]:
        data = self._get_json("https://api.binance.com/api/v3/ticker/24hr")
        wanted = {"BTCUSDT":"BTC", "ETHUSDT":"ETH", "SOLUSDT":"SOL"}
        out: List[Signal] = []
        for row in data:
            if row.get("symbol") in wanted:
                sym = wanted[row["symbol"]]
                chg = as_float(row.get("priceChangePercent"))
                qvol = as_float(row.get("quoteVolume"))
                out.append(self._signal("Binance Crypto Pulse", sym, "BUY" if chg >= 0 else "SELL", min(.85, .48+abs(chg)/30), f"{sym} crypto liquidity move {chg:+.2f}%", f"Live Binance 24h ticker. Quote volume {qvol:,.0f}.", abs(chg), {"feed_key":"binance_crypto", "feed_type":"crypto_market_data", "volume":qvol, "probability_change_pct":abs(chg), "volume_zscore":volume_score(qvol)}))
        return out[:max_per_feed]

    def collect_options_flow(self, max_per_feed: int = 25) -> List[Signal]:
        tradier = os.getenv("TRADIER_TOKEN")
        if tradier:
            return self._collect_tradier_options(max_per_feed)
        polygon = os.getenv("POLYGON_API_KEY")
        if polygon:
            return self._collect_polygon_options(max_per_feed)
        raise MissingCredential("Set TRADIER_TOKEN or POLYGON_API_KEY to enable live options flow")

    def _collect_tradier_options(self, max_per_feed: int) -> List[Signal]:
        token = os.environ["TRADIER_TOKEN"]
        base = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        underlyings = os.getenv("OPTIONS_UNDERLYINGS", "SPY,QQQ,NVDA,TSLA,XLE,USO,GLD,SLV,VRT,ETN").split(",")
        out: List[Signal] = []
        for sym in [s.strip().upper() for s in underlyings if s.strip()]:
            exp_data = self._get_json(f"{base}/markets/options/expirations", {"symbol": sym, "includeAllRoots":"true", "strikes":"false"}, headers)
            exps = exp_data.get("expirations", {}).get("date", []) if isinstance(exp_data, dict) else []
            if isinstance(exps, str):
                exps = [exps]
            if not exps:
                continue
            chain = self._get_json(f"{base}/markets/options/chains", {"symbol": sym, "expiration": exps[0], "greeks":"true"}, headers)
            options = chain.get("options", {}).get("option", []) if isinstance(chain, dict) else []
            if isinstance(options, dict):
                options = [options]
            scored = []
            for opt in options:
                vol = as_float(opt.get("volume")); oi = max(1.0, as_float(opt.get("open_interest")))
                ratio = vol / oi
                bid = as_float(opt.get("bid")); ask = as_float(opt.get("ask")); last = as_float(opt.get("last"))
                if vol <= 0 or ask <= 0:
                    continue
                scored.append((ratio, vol, opt, bid, ask, last))
            for ratio, vol, opt, bid, ask, last in sorted(scored, reverse=True)[:2]:
                right = str(opt.get("option_type", "call")).lower()
                direction = "BUY" if right == "call" else "SELL"
                title = f"{sym} unusual {right} activity"
                strike = opt.get("strike"); expiration = opt.get("expiration_date") or exps[0]
                desc = f"Live Tradier option chain: {right} {strike} exp {expiration}; volume {vol:,.0f}; volume/open-interest {ratio:.2f}; bid {bid}; ask {ask}; last {last}."
                out.append(self._signal("Tradier Options Flow", sym, direction, min(.88, .50 + min(.30, ratio/8) + min(.08, vol/5000)), title, desc, min(100, ratio*10), {"feed_key":"options_flow", "feed_type":"options", "option_type":right, "strike":strike, "expiration":expiration, "volume":vol, "open_interest":opt.get("open_interest"), "volume_oi_ratio":ratio, "volume_zscore":min(8, max(1, ratio))}))
                if len(out) >= max_per_feed:
                    return out
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
                if vol <= 0:
                    continue
                scored.append((vol/oi, vol, row, details))
            for ratio, vol, row, details in sorted(scored, reverse=True)[:2]:
                right = str(details.get("contract_type", "call")).lower()
                direction = "BUY" if right == "call" else "SELL"
                strike = details.get("strike_price"); expiration = details.get("expiration_date")
                title = f"{sym} unusual {right} activity"
                desc = f"Live Polygon option snapshot: {right} {strike} exp {expiration}; volume {vol:,.0f}; volume/open-interest {ratio:.2f}."
                out.append(self._signal("Polygon Options Flow", sym, direction, min(.88, .50 + min(.30, ratio/8) + min(.08, vol/5000)), title, desc, min(100, ratio*10), {"feed_key":"options_flow", "feed_type":"options", "option_type":right, "strike":strike, "expiration":expiration, "volume":vol, "open_interest":row.get("open_interest"), "volume_oi_ratio":ratio, "volume_zscore":min(8, max(1, ratio))}))
                if len(out) >= max_per_feed:
                    return out
        return out

class MissingCredential(Exception):
    pass

def as_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default

def volume_score(volume: float) -> float:
    return round(min(8.0, max(1.0, math.log10(max(float(volume), 10.0))/2.0)), 2)

def probability_from_market(m: Dict[str, Any]) -> float:
    prices = m.get("outcomePrices") or m.get("outcomesPrices") or []
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            prices = []
    try:
        nums = [float(x) for x in prices]
        return max(nums) if nums else 0.5
    except Exception:
        return 0.5

def metaculus_probability(q: Dict[str, Any]) -> float:
    pred = q.get("community_prediction") or q.get("prediction") or {}
    if isinstance(pred, dict):
        full = pred.get("full") if isinstance(pred.get("full"), dict) else {}
        return as_float(full.get("q2", pred.get("q2", pred.get("probability", 0.5))), 0.5)
    return 0.5

def clean_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&amp;", "&").strip()

def infer_symbol(text: str) -> str:
    t = text.lower()
    rules = [
        (["oil", "crude", "opec", "venezuela", "iran", "tanker"], "CL"),
        (["natural gas", "lng", "pipeline", "power grid", "data center power"], "NG"),
        (["gold", "safe haven"], "GLD"),
        (["silver"], "SLV"),
        (["fed", "rate", "inflation", "cpi", "treasury", "bond"], "TLT"),
        (["bitcoin", "crypto", "ethereum", "stablecoin"], "BTC"),
        (["nvidia", "gpu", "semiconductor", "chip", "ai"], "NVDA"),
        (["data center", "cooling", "power demand", "grid"], "VRT"),
        (["water", "drought", "desalination"], "PHO"),
        (["taiwan", "tsmc"], "TSM"),
        (["bank", "credit", "liquidity", "recession", "vix"], "SPY"),
    ]
    for words, sym in rules:
        if any(w in t for w in words):
            return sym
    return "SPY"

def narrative_direction(narr: str) -> str:
    return {
        "oil_geopolitics":"BUY", "rate_cuts":"BUY", "ai_policy":"SELL", "crypto_regulation":"BUY",
        "taiwan_risk":"SELL", "market_stress":"SELL", "precious_metals":"BUY",
        "energy_infrastructure":"BUY", "water_infrastructure":"BUY", "data_center_infrastructure":"BUY"
    }.get(narr, "WATCH")

def news_feed_urls() -> List[str]:
    raw = os.getenv("NEWS_RSS_URLS")
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return [
        "https://www.investing.com/rss/news_25.rss",
        "https://www.investing.com/rss/news_301.rss",
        "https://www.marketwatch.com/rss/topstories",
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://www.cftc.gov/PressRoom/PressReleases/rss.xml",
        "https://www.sec.gov/news/pressreleases.rss",
    ]

def stooq_symbols() -> List[Tuple[str, str]]:
    raw = os.getenv("STOOQ_SYMBOLS")
    if raw:
        pairs = []
        for chunk in raw.split(","):
            if ":" in chunk:
                code, sym = chunk.split(":", 1)
            else:
                code, sym = chunk, chunk.split(".")[0]
            pairs.append((code.strip().lower(), sym.strip().upper()))
        return pairs
    syms = ["spy","qqq","iwm","tlt","gld","slv","iau","sivr","sgol","gdx","sil","uso","ung","xle","vde","oih","icln","tan","ura","urnm","nlr","vrt","jci","tt","carr","etn","xyl","awk","pho","cgw","eqix","dlr","xom","cvx","nvda","amd","tsla","coin","mstr"]
    return [(f"{s}.us", s.upper()) for s in syms]

def fetch_stooq_quote(session: requests.Session, stooq_code: str) -> Optional[Dict[str, float]]:
    url = f"https://stooq.com/q/l/?s={stooq_code}&f=sd2t2ohlcv&h&e=csv"
    r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows:
        return None
    row = rows[0]
    last = as_float(row.get("Close") or row.get("Last"))
    if last <= 0:
        return None
    return {"last": last, "open": as_float(row.get("Open"), last), "high": as_float(row.get("High"), last), "low": as_float(row.get("Low"), last), "volume": as_float(row.get("Volume"))}

def collect_live_signals(state: Dict[str, Any], max_per_feed: int = 25, enabled_feeds: Optional[List[str]] = None) -> Tuple[List[Signal], List[Dict[str, Any]]]:
    return LiveFeedCollector(state).collect_all(max_per_feed=max_per_feed, enabled_feeds=enabled_feeds)
