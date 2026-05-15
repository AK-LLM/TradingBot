from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import os, csv, io, requests

UA = os.getenv("SIGNAL_BOT_USER_AGENT", "signal-trading-platform-live contact:local")
TIMEOUT = float(os.getenv("LIVE_FEED_TIMEOUT", "5"))  # V5.7.1: shortened from 10s to 5s; many symbols compound
QUOTE_TIMEOUT = float(os.getenv("QUOTE_TIMEOUT", "3"))  # V5.7.1: even shorter for quote calls (we have fallbacks)

SYMBOL_TO_STOOQ = {
    "SPY":"spy.us", "QQQ":"qqq.us", "IWM":"iwm.us", "TLT":"tlt.us", "GLD":"gld.us", "SLV":"slv.us", "IAU":"iau.us", "SIVR":"sivr.us", "SGOL":"sgol.us", "GDX":"gdx.us", "SIL":"sil.us",
    "USO":"uso.us", "UNG":"ung.us", "XLE":"xle.us", "VDE":"vde.us", "OIH":"oih.us", "ICLN":"icln.us", "TAN":"tan.us", "URA":"ura.us", "URNM":"urnm.us", "NLR":"nlr.us",
    "VRT":"vrt.us", "JCI":"jci.us", "TT":"tt.us", "CARR":"carr.us", "ETN":"etn.us", "XYL":"xyl.us", "AWK":"awk.us", "PHO":"pho.us", "CGW":"cgw.us", "EQIX":"eqix.us", "DLR":"dlr.us",
    "XOM":"xom.us", "CVX":"cvx.us", "NVDA":"nvda.us", "AMD":"amd.us", "MSFT":"msft.us", "TSLA":"tsla.us", "COIN":"coin.us", "MSTR":"mstr.us", "SMH":"smh.us", "VIXY":"vixy.us",
}

class MarketDataError(Exception):
    pass

class MarketDataService:
    # V5.7.1: Class-level circuit breaker — if Stooq fails N times in this process,
    # stop calling it for the rest of the scan to prevent compounding timeouts.
    _stooq_failures = 0
    _tradier_failures = 0
    CIRCUIT_BREAKER_THRESHOLD = 5

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept":"application/json,text/csv,*/*"})

    @classmethod
    def reset_circuit_breakers(cls):
        """Called at start of each scan to give services a fresh chance."""
        cls._stooq_failures = 0
        cls._tradier_failures = 0

    def quote(self, symbol: str) -> Dict[str, Any]:
        symbol = symbol.upper()
        q = self._tradier_quote(symbol) if os.getenv("TRADIER_TOKEN") else None
        if q is None:
            q = self._stooq_quote(symbol)
        if q is None:
            cached = self.state.setdefault("market_cache", {}).get(symbol)
            if cached:
                cached = dict(cached)
                cached["stale"] = True
                return cached
            raise MarketDataError(f"No live market quote available for {symbol}")
        self.state.setdefault("market_cache", {})[symbol] = q
        return q

    def context_score(self, symbol: str, desired_direction: str) -> Dict[str, Any]:
        q = self.quote(symbol)
        move_pct = float(q.get("change_pct") or 0.0)
        trend = "up" if move_pct > 0 else "down" if move_pct < 0 else "neutral"
        wanted = desired_direction.upper() in {"BUY", "LONG"}
        trend_ok = (trend == "up" and wanted) or (trend == "down" and not wanted)
        spread_bps = float(q.get("spread_bps") or 20.0)
        spread_score = max(0.0, 100.0 - spread_bps * 2.0)
        late_penalty = 20.0 if abs(move_pct) > float(self.state.get("settings", {}).get("max_move_before_entry_pct", 2.5)) else 0.0
        score = max(0.0, min(100.0, 52.0 + (22.0 if trend_ok else -10.0) + spread_score * 0.22 - late_penalty))
        return {"score": round(score, 1), "quote": q, "trend_ok": trend_ok, "chase_penalty": late_penalty}

    def _tradier_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        if MarketDataService._tradier_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            return None
        token = os.getenv("TRADIER_TOKEN")
        if not token:
            return None
        base = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1")
        try:
            r = self.session.get(f"{base}/markets/quotes", params={"symbols": symbol, "greeks":"false"}, headers={"Authorization": f"Bearer {token}", "Accept":"application/json"}, timeout=QUOTE_TIMEOUT)
            if r.status_code >= 400:
                MarketDataService._tradier_failures += 1
                return None
            data = r.json()
        except (requests.exceptions.RequestException, ValueError, Exception):
            MarketDataService._tradier_failures += 1
            return None
        quote = data.get("quotes", {}).get("quote") if isinstance(data, dict) else None
        if isinstance(quote, list):
            quote = quote[0] if quote else None
        if not quote:
            return None
        last = as_float(quote.get("last") or quote.get("close"))
        if last <= 0:
            return None
        bid = as_float(quote.get("bid"), last)
        ask = as_float(quote.get("ask"), last)
        if bid <= 0: bid = last
        if ask <= 0: ask = last
        spread_bps = abs(ask-bid)/last*10000 if last else 0
        openp = as_float(quote.get("open"), last)
        chg = ((last/openp)-1)*100 if openp else as_float(quote.get("change_percentage"))
        return {"symbol":symbol, "last":round(last,4), "bid":round(bid,4), "ask":round(ask,4), "spread_bps":round(spread_bps,1), "volume":as_float(quote.get("volume")), "change_pct":round(chg,3), "source":"tradier", "ts":datetime.now(timezone.utc).isoformat()}

    def _stooq_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        # Circuit breaker: skip if Stooq has been failing this scan
        if MarketDataService._stooq_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            return None
        code = SYMBOL_TO_STOOQ.get(symbol)
        if not code:
            return None
        try:
            r = self.session.get(f"https://stooq.com/q/l/?s={code}&f=sd2t2ohlcv&h&e=csv", timeout=QUOTE_TIMEOUT)
            if r.status_code >= 400:
                MarketDataService._stooq_failures += 1
                return None
            text = r.text
        except (requests.exceptions.RequestException, Exception):
            MarketDataService._stooq_failures += 1
            return None
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except Exception:
            return None
        if not rows:
            return None
        row = rows[0]
        last = as_float(row.get("Close") or row.get("Last"))
        if last <= 0:
            return None
        openp = as_float(row.get("Open"), last)
        high = as_float(row.get("High"), last); low = as_float(row.get("Low"), last)
        spread_bps = max(2.0, min(80.0, ((high-low)/last*10000)/10 if high and low else 15.0))
        bid = last * (1 - spread_bps/20000); ask = last * (1 + spread_bps/20000)
        chg = ((last/openp)-1)*100 if openp else 0.0
        return {"symbol":symbol, "last":round(last,4), "bid":round(bid,4), "ask":round(ask,4), "spread_bps":round(spread_bps,1), "volume":as_float(row.get("Volume")), "change_pct":round(chg,3), "source":"stooq", "ts":datetime.now(timezone.utc).isoformat()}

def as_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "": return default
        return float(str(x).replace("%", ""))
    except Exception:
        return default
