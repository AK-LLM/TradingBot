from __future__ import annotations
from typing import Dict, List, Any

NARRATIVE_MAP: Dict[str, List[Dict[str, Any]]] = {
    "oil_geopolitics": [
        {"symbol":"USO", "asset_type":"stock", "direction":"BUY", "reason":"oil ETF proxy"},
        {"symbol":"XLE", "asset_type":"stock", "direction":"BUY", "reason":"energy sector ETF"},
        {"symbol":"XOM", "asset_type":"stock", "direction":"BUY", "reason":"large-cap energy"},
        {"symbol":"CVX", "asset_type":"stock", "direction":"BUY", "reason":"large-cap energy"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"safe-haven confirmation"},
    ],
    "energy_infrastructure": [
        {"symbol":"UNG", "asset_type":"stock", "direction":"BUY", "reason":"natural gas ETF proxy"},
        {"symbol":"XLE", "asset_type":"stock", "direction":"BUY", "reason":"traditional energy"},
        {"symbol":"VDE", "asset_type":"stock", "direction":"BUY", "reason":"broad energy ETF"},
        {"symbol":"URA", "asset_type":"stock", "direction":"BUY", "reason":"nuclear/uranium power chain"},
        {"symbol":"VRT", "asset_type":"stock", "direction":"BUY", "reason":"data-center power/cooling chain"},
    ],
    "data_center_infrastructure": [
        {"symbol":"VRT", "asset_type":"stock", "direction":"BUY", "reason":"data center cooling and power management"},
        {"symbol":"ETN", "asset_type":"stock", "direction":"BUY", "reason":"electrical infrastructure"},
        {"symbol":"EQIX", "asset_type":"stock", "direction":"BUY", "reason":"data center REIT"},
        {"symbol":"DLR", "asset_type":"stock", "direction":"BUY", "reason":"data center REIT"},
        {"symbol":"XYL", "asset_type":"stock", "direction":"BUY", "reason":"water/cooling infrastructure"},
    ],
    "water_infrastructure": [
        {"symbol":"PHO", "asset_type":"stock", "direction":"BUY", "reason":"water infrastructure ETF"},
        {"symbol":"CGW", "asset_type":"stock", "direction":"BUY", "reason":"global water ETF"},
        {"symbol":"XYL", "asset_type":"stock", "direction":"BUY", "reason":"water technology"},
        {"symbol":"AWK", "asset_type":"stock", "direction":"BUY", "reason":"water utility"},
        {"symbol":"VRT", "asset_type":"stock", "direction":"BUY", "reason":"cooling dependency"},
    ],
    "precious_metals": [
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"gold ETF"},
        {"symbol":"IAU", "asset_type":"stock", "direction":"BUY", "reason":"gold ETF"},
        {"symbol":"SLV", "asset_type":"stock", "direction":"BUY", "reason":"silver ETF"},
        {"symbol":"SIVR", "asset_type":"stock", "direction":"BUY", "reason":"silver ETF"},
        {"symbol":"GDX", "asset_type":"stock", "direction":"BUY", "reason":"gold miners"},
    ],
    "rate_cuts": [
        {"symbol":"TLT", "asset_type":"stock", "direction":"BUY", "reason":"long-duration bonds"},
        {"symbol":"QQQ", "asset_type":"stock", "direction":"BUY", "reason":"duration-sensitive growth"},
        {"symbol":"IWM", "asset_type":"stock", "direction":"BUY", "reason":"small-cap liquidity beta"},
    ],
    "ai_policy": [
        {"symbol":"NVDA", "asset_type":"stock", "direction":"SELL", "reason":"AI hardware policy sensitivity"},
        {"symbol":"AMD", "asset_type":"stock", "direction":"SELL", "reason":"AI hardware policy sensitivity"},
        {"symbol":"SMH", "asset_type":"stock", "direction":"SELL", "reason":"semiconductor basket"},
        {"symbol":"MSFT", "asset_type":"stock", "direction":"SELL", "reason":"AI platform exposure"},
    ],
    "crypto_regulation": [
        {"symbol":"BTC", "asset_type":"crypto", "direction":"BUY", "reason":"crypto beta"},
        {"symbol":"ETH", "asset_type":"crypto", "direction":"BUY", "reason":"crypto beta"},
        {"symbol":"COIN", "asset_type":"stock", "direction":"BUY", "reason":"exchange proxy"},
        {"symbol":"MSTR", "asset_type":"stock", "direction":"BUY", "reason":"BTC treasury proxy"},
    ],
    "taiwan_risk": [
        {"symbol":"TSM", "asset_type":"stock", "direction":"SELL", "reason":"Taiwan direct exposure"},
        {"symbol":"SMH", "asset_type":"stock", "direction":"SELL", "reason":"semiconductor supply chain"},
        {"symbol":"LMT", "asset_type":"stock", "direction":"BUY", "reason":"defense prime"},
        {"symbol":"RTX", "asset_type":"stock", "direction":"BUY", "reason":"defense prime"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"safe-haven hedge"},
        {"symbol":"VIXY", "asset_type":"stock", "direction":"BUY", "reason":"volatility proxy"},
    ],
    "market_stress": [
        {"symbol":"SPY", "asset_type":"stock", "direction":"SELL", "reason":"broad equity risk"},
        {"symbol":"QQQ", "asset_type":"stock", "direction":"SELL", "reason":"growth risk beta"},
        {"symbol":"VIXY", "asset_type":"stock", "direction":"BUY", "reason":"volatility proxy"},
        {"symbol":"TLT", "asset_type":"stock", "direction":"BUY", "reason":"flight-to-quality proxy"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"safe-haven hedge"},
    ],
}

KEYWORDS = {
    "oil_geopolitics": ["oil", "crude", "venezuela", "iran", "strait", "opec", "sanction", "tanker", "refinery"],
    "energy_infrastructure": ["natural gas", "lng", "pipeline", "grid", "power plant", "electricity demand", "uranium", "nuclear", "reactor"],
    "data_center_infrastructure": ["data center", "datacenter", "ai infrastructure", "cooling", "hyperscale", "power management", "electrical equipment"],
    "water_infrastructure": ["water", "drought", "desalination", "reservoir", "aquifer", "wastewater", "water treatment"],
    "precious_metals": ["gold", "silver", "bullion", "safe haven", "precious metal"],
    "rate_cuts": ["fed", "rate", "cut", "inflation", "cpi", "fomc", "powell", "treasury", "bond"],
    "ai_policy": ["ai", "chip", "semiconductor", "export", "nvidia", "gpu", "regulation"],
    "crypto_regulation": ["bitcoin", "crypto", "ethereum", "etf", "coinbase", "stablecoin"],
    "taiwan_risk": ["taiwan", "china", "tsmc", "strait", "invasion", "blockade"],
    "market_stress": ["bank", "default", "crisis", "liquidity", "credit", "recession", "vix"],
}

def classify_narrative(text: str, fallback_symbol: str = "SPY") -> str:
    lower = text.lower()
    scores = {k: sum(1 for w in words if w in lower) for k, words in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "market_stress" if fallback_symbol.upper() in {"SPY", "QQQ", "IWM", "VIXY"} else "single_name"
    return best

def map_instruments(narrative: str, symbol: str, direction: str) -> List[Dict[str, Any]]:
    if narrative == "single_name":
        return [{"symbol": symbol.upper(), "asset_type": "stock", "direction": direction.upper(), "reason": "direct symbol mapping"}]
    return NARRATIVE_MAP.get(narrative, [{"symbol": symbol.upper(), "asset_type": "stock", "direction": direction.upper(), "reason": "direct mapping"}])
