from __future__ import annotations
from typing import Dict, List, Any

# V5.5 expansion: Added Canadian equities, FX, bonds, biotech, financials,
# agriculture, REITs. Reorganized for cleaner narrative coverage.

NARRATIVE_MAP: Dict[str, List[Dict[str, Any]]] = {
    "oil_geopolitics": [
        {"symbol":"USO", "asset_type":"stock", "direction":"BUY", "reason":"oil ETF proxy"},
        {"symbol":"XLE", "asset_type":"stock", "direction":"BUY", "reason":"US energy sector ETF"},
        {"symbol":"XOM", "asset_type":"stock", "direction":"BUY", "reason":"large-cap energy"},
        {"symbol":"CVX", "asset_type":"stock", "direction":"BUY", "reason":"large-cap energy"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"safe-haven confirmation"},
        {"symbol":"XEG.TO", "asset_type":"stock", "direction":"BUY", "reason":"Canadian energy sector ETF"},
        {"symbol":"SU.TO", "asset_type":"stock", "direction":"BUY", "reason":"Suncor - large-cap Canadian energy"},
        {"symbol":"CNQ.TO", "asset_type":"stock", "direction":"BUY", "reason":"Canadian Natural Resources"},
        {"symbol":"ENB.TO", "asset_type":"stock", "direction":"BUY", "reason":"Enbridge - midstream"},
    ],
    "energy_infrastructure": [
        {"symbol":"UNG", "asset_type":"stock", "direction":"BUY", "reason":"natural gas ETF proxy"},
        {"symbol":"XLE", "asset_type":"stock", "direction":"BUY", "reason":"traditional energy"},
        {"symbol":"VDE", "asset_type":"stock", "direction":"BUY", "reason":"broad energy ETF"},
        {"symbol":"URA", "asset_type":"stock", "direction":"BUY", "reason":"nuclear/uranium power chain"},
        {"symbol":"VRT", "asset_type":"stock", "direction":"BUY", "reason":"data-center power/cooling chain"},
        {"symbol":"CCO.TO", "asset_type":"stock", "direction":"BUY", "reason":"Cameco - Canadian uranium"},
        {"symbol":"NXE.TO", "asset_type":"stock", "direction":"BUY", "reason":"NexGen - Canadian uranium developer"},
        {"symbol":"TRP.TO", "asset_type":"stock", "direction":"BUY", "reason":"TC Energy pipelines"},
    ],
    "data_center_infrastructure": [
        {"symbol":"VRT", "asset_type":"stock", "direction":"BUY", "reason":"data center cooling and power management"},
        {"symbol":"ETN", "asset_type":"stock", "direction":"BUY", "reason":"electrical infrastructure"},
        {"symbol":"EQIX", "asset_type":"stock", "direction":"BUY", "reason":"data center REIT"},
        {"symbol":"DLR", "asset_type":"stock", "direction":"BUY", "reason":"data center REIT"},
        {"symbol":"XYL", "asset_type":"stock", "direction":"BUY", "reason":"water/cooling infrastructure"},
        {"symbol":"SMH", "asset_type":"stock", "direction":"BUY", "reason":"semiconductors powering AI"},
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
        {"symbol":"ABX.TO", "asset_type":"stock", "direction":"BUY", "reason":"Barrick Gold"},
        {"symbol":"AEM.TO", "asset_type":"stock", "direction":"BUY", "reason":"Agnico Eagle Mines"},
        {"symbol":"K.TO", "asset_type":"stock", "direction":"BUY", "reason":"Kinross Gold"},
    ],
    "rate_cuts": [
        {"symbol":"TLT", "asset_type":"stock", "direction":"BUY", "reason":"long-duration bonds"},
        {"symbol":"IEF", "asset_type":"stock", "direction":"BUY", "reason":"7-10y Treasury"},
        {"symbol":"QQQ", "asset_type":"stock", "direction":"BUY", "reason":"duration-sensitive growth"},
        {"symbol":"IWM", "asset_type":"stock", "direction":"BUY", "reason":"small-cap liquidity beta"},
        {"symbol":"XLU", "asset_type":"stock", "direction":"BUY", "reason":"utilities benefit from lower rates"},
        {"symbol":"XBB.TO", "asset_type":"stock", "direction":"BUY", "reason":"Canadian aggregate bond ETF"},
        {"symbol":"ZUT.TO", "asset_type":"stock", "direction":"BUY", "reason":"Canadian utilities ETF"},
    ],
    "rate_hikes": [
        {"symbol":"TLT", "asset_type":"stock", "direction":"SELL", "reason":"long-duration vulnerable"},
        {"symbol":"XLF", "asset_type":"stock", "direction":"BUY", "reason":"banks benefit from rate spread"},
        {"symbol":"KRE", "asset_type":"stock", "direction":"WATCH", "reason":"regional banks - mixed"},
        {"symbol":"UUP", "asset_type":"stock", "direction":"BUY", "reason":"USD strength"},
        {"symbol":"XFN.TO", "asset_type":"stock", "direction":"BUY", "reason":"Canadian financials ETF"},
        {"symbol":"RY.TO", "asset_type":"stock", "direction":"BUY", "reason":"Royal Bank of Canada"},
        {"symbol":"TD.TO", "asset_type":"stock", "direction":"BUY", "reason":"TD Bank"},
    ],
    "ai_policy": [
        {"symbol":"NVDA", "asset_type":"stock", "direction":"SELL", "reason":"AI hardware policy sensitivity"},
        {"symbol":"AMD", "asset_type":"stock", "direction":"SELL", "reason":"AI hardware policy sensitivity"},
        {"symbol":"SMH", "asset_type":"stock", "direction":"SELL", "reason":"semiconductor basket"},
        {"symbol":"MSFT", "asset_type":"stock", "direction":"SELL", "reason":"AI platform exposure"},
        {"symbol":"TSM", "asset_type":"stock", "direction":"SELL", "reason":"foundry exposure"},
    ],
    "ai_infrastructure": [
        {"symbol":"NVDA", "asset_type":"stock", "direction":"BUY", "reason":"GPU dominance"},
        {"symbol":"AMD", "asset_type":"stock", "direction":"BUY", "reason":"AI accelerators"},
        {"symbol":"SMH", "asset_type":"stock", "direction":"BUY", "reason":"semiconductor basket"},
        {"symbol":"VRT", "asset_type":"stock", "direction":"BUY", "reason":"AI data center cooling"},
        {"symbol":"ANET", "asset_type":"stock", "direction":"BUY", "reason":"AI networking"},
        {"symbol":"DELL", "asset_type":"stock", "direction":"BUY", "reason":"AI server hardware"},
    ],
    "crypto_regulation": [
        {"symbol":"BTC", "asset_type":"crypto", "direction":"BUY", "reason":"crypto beta"},
        {"symbol":"ETH", "asset_type":"crypto", "direction":"BUY", "reason":"crypto beta"},
        {"symbol":"COIN", "asset_type":"stock", "direction":"BUY", "reason":"exchange proxy"},
        {"symbol":"MSTR", "asset_type":"stock", "direction":"BUY", "reason":"BTC treasury proxy"},
        {"symbol":"IBIT", "asset_type":"stock", "direction":"BUY", "reason":"spot BTC ETF"},
        {"symbol":"FBTC", "asset_type":"stock", "direction":"BUY", "reason":"spot BTC ETF"},
        {"symbol":"HUT.TO", "asset_type":"stock", "direction":"BUY", "reason":"Canadian BTC miner"},
    ],
    "taiwan_risk": [
        {"symbol":"TSM", "asset_type":"stock", "direction":"SELL", "reason":"Taiwan direct exposure"},
        {"symbol":"SMH", "asset_type":"stock", "direction":"SELL", "reason":"semiconductor supply chain"},
        {"symbol":"LMT", "asset_type":"stock", "direction":"BUY", "reason":"defense prime"},
        {"symbol":"RTX", "asset_type":"stock", "direction":"BUY", "reason":"defense prime"},
        {"symbol":"NOC", "asset_type":"stock", "direction":"BUY", "reason":"defense prime"},
        {"symbol":"ITA", "asset_type":"stock", "direction":"BUY", "reason":"aerospace and defense ETF"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"safe-haven hedge"},
        {"symbol":"VIXY", "asset_type":"stock", "direction":"BUY", "reason":"volatility proxy"},
    ],
    "market_stress": [
        {"symbol":"SPY", "asset_type":"stock", "direction":"SELL", "reason":"broad equity risk"},
        {"symbol":"QQQ", "asset_type":"stock", "direction":"SELL", "reason":"growth risk beta"},
        {"symbol":"VIXY", "asset_type":"stock", "direction":"BUY", "reason":"volatility proxy"},
        {"symbol":"TLT", "asset_type":"stock", "direction":"BUY", "reason":"flight-to-quality proxy"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"safe-haven hedge"},
        {"symbol":"UUP", "asset_type":"stock", "direction":"BUY", "reason":"USD safe haven"},
        {"symbol":"XIU.TO", "asset_type":"stock", "direction":"SELL", "reason":"TSX 60 broad risk"},
    ],
    "biotech_catalyst": [
        {"symbol":"XBI", "asset_type":"stock", "direction":"BUY", "reason":"biotech sector ETF"},
        {"symbol":"IBB", "asset_type":"stock", "direction":"BUY", "reason":"large biotech ETF"},
        {"symbol":"LLY", "asset_type":"stock", "direction":"BUY", "reason":"GLP-1 leader"},
        {"symbol":"NVO", "asset_type":"stock", "direction":"BUY", "reason":"Novo Nordisk GLP-1"},
        {"symbol":"VRTX", "asset_type":"stock", "direction":"BUY", "reason":"diversified biotech"},
    ],
    "agriculture_food": [
        {"symbol":"DBA", "asset_type":"stock", "direction":"BUY", "reason":"agriculture ETF"},
        {"symbol":"WEAT", "asset_type":"stock", "direction":"BUY", "reason":"wheat ETF"},
        {"symbol":"CORN", "asset_type":"stock", "direction":"BUY", "reason":"corn ETF"},
        {"symbol":"MOO", "asset_type":"stock", "direction":"BUY", "reason":"agribusiness ETF"},
        {"symbol":"NTR.TO", "asset_type":"stock", "direction":"BUY", "reason":"Nutrien - Canadian potash/fertilizer"},
        {"symbol":"ADM", "asset_type":"stock", "direction":"BUY", "reason":"agricultural processing"},
    ],
    "fx_usd_strength": [
        {"symbol":"UUP", "asset_type":"stock", "direction":"BUY", "reason":"DXY proxy ETF"},
        {"symbol":"FXC", "asset_type":"stock", "direction":"SELL", "reason":"CAD weakens vs USD"},
        {"symbol":"FXE", "asset_type":"stock", "direction":"SELL", "reason":"EUR weakens vs USD"},
        {"symbol":"FXY", "asset_type":"stock", "direction":"SELL", "reason":"JPY weakens vs USD"},
        {"symbol":"EEM", "asset_type":"stock", "direction":"SELL", "reason":"EM stress on dollar strength"},
    ],
    "fx_usd_weakness": [
        {"symbol":"UDN", "asset_type":"stock", "direction":"BUY", "reason":"USD bearish ETF"},
        {"symbol":"FXC", "asset_type":"stock", "direction":"BUY", "reason":"CAD strengthens"},
        {"symbol":"GLD", "asset_type":"stock", "direction":"BUY", "reason":"gold rises on dollar weakness"},
        {"symbol":"EEM", "asset_type":"stock", "direction":"BUY", "reason":"EM benefits from weak dollar"},
    ],
    "credit_stress": [
        {"symbol":"HYG", "asset_type":"stock", "direction":"SELL", "reason":"high yield credit ETF"},
        {"symbol":"JNK", "asset_type":"stock", "direction":"SELL", "reason":"junk bond ETF"},
        {"symbol":"LQD", "asset_type":"stock", "direction":"SELL", "reason":"investment grade credit"},
        {"symbol":"XLF", "asset_type":"stock", "direction":"SELL", "reason":"banks exposed to credit"},
        {"symbol":"KRE", "asset_type":"stock", "direction":"SELL", "reason":"regional banks credit risk"},
        {"symbol":"VIXY", "asset_type":"stock", "direction":"BUY", "reason":"volatility hedge"},
        {"symbol":"TLT", "asset_type":"stock", "direction":"BUY", "reason":"flight to Treasuries"},
    ],
    "supply_chain_disruption": [
        {"symbol":"FDX", "asset_type":"stock", "direction":"WATCH", "reason":"logistics impact"},
        {"symbol":"UPS", "asset_type":"stock", "direction":"WATCH", "reason":"logistics impact"},
        {"symbol":"BDRY", "asset_type":"stock", "direction":"BUY", "reason":"shipping rates ETF"},
        {"symbol":"SEA", "asset_type":"stock", "direction":"BUY", "reason":"shipping ETF"},
        {"symbol":"ZIM", "asset_type":"stock", "direction":"BUY", "reason":"container shipping"},
        {"symbol":"USO", "asset_type":"stock", "direction":"BUY", "reason":"oil supply stress"},
    ],
    "real_estate_stress": [
        {"symbol":"VNQ", "asset_type":"stock", "direction":"SELL", "reason":"REIT ETF"},
        {"symbol":"IYR", "asset_type":"stock", "direction":"SELL", "reason":"real estate ETF"},
        {"symbol":"XLRE", "asset_type":"stock", "direction":"SELL", "reason":"real estate sector ETF"},
        {"symbol":"REZ", "asset_type":"stock", "direction":"SELL", "reason":"residential REITs"},
        {"symbol":"XRE.TO", "asset_type":"stock", "direction":"SELL", "reason":"Canadian REIT ETF"},
    ],
    "consumer_discretionary": [
        {"symbol":"XLY", "asset_type":"stock", "direction":"BUY", "reason":"consumer discretionary ETF"},
        {"symbol":"AMZN", "asset_type":"stock", "direction":"BUY", "reason":"e-commerce dominant"},
        {"symbol":"HD", "asset_type":"stock", "direction":"BUY", "reason":"home improvement"},
        {"symbol":"NKE", "asset_type":"stock", "direction":"BUY", "reason":"consumer brand"},
    ],
    "defensive_rotation": [
        {"symbol":"XLP", "asset_type":"stock", "direction":"BUY", "reason":"consumer staples"},
        {"symbol":"XLU", "asset_type":"stock", "direction":"BUY", "reason":"utilities"},
        {"symbol":"XLV", "asset_type":"stock", "direction":"BUY", "reason":"healthcare"},
        {"symbol":"VYM", "asset_type":"stock", "direction":"BUY", "reason":"high dividend"},
    ],
    "canada_specific": [
        {"symbol":"XIU.TO", "asset_type":"stock", "direction":"BUY", "reason":"TSX 60 ETF"},
        {"symbol":"XIC.TO", "asset_type":"stock", "direction":"BUY", "reason":"S&P/TSX Composite ETF"},
        {"symbol":"FXC", "asset_type":"stock", "direction":"BUY", "reason":"CAD strengthens"},
        {"symbol":"SHOP.TO", "asset_type":"stock", "direction":"WATCH", "reason":"Canadian tech"},
    ],
}

KEYWORDS = {
    "oil_geopolitics": ["oil", "crude", "venezuela", "iran", "strait", "opec", "sanction", "tanker", "refinery", "wti", "brent"],
    "energy_infrastructure": ["natural gas", "lng", "pipeline", "grid", "power plant", "electricity demand", "uranium", "nuclear", "reactor", "smr"],
    "data_center_infrastructure": ["data center", "datacenter", "ai infrastructure", "cooling", "hyperscale", "power management", "electrical equipment"],
    "water_infrastructure": ["water", "drought", "desalination", "reservoir", "aquifer", "wastewater", "water treatment"],
    "precious_metals": ["gold", "silver", "bullion", "safe haven", "precious metal"],
    "rate_cuts": ["fed rate cut", "rate cut", "dovish", "easing", "fomc", "powell"],
    "rate_hikes": ["rate hike", "hawkish", "tightening", "raising rates", "inflation surge"],
    "ai_policy": ["ai regulation", "chip ban", "export control", "ai safety", "ai policy"],
    "ai_infrastructure": ["ai chip", "gpu", "nvidia", "h100", "h200", "blackwell", "ai cluster", "training cluster"],
    "crypto_regulation": ["bitcoin", "crypto", "ethereum", "etf", "coinbase", "stablecoin", "spot bitcoin"],
    "taiwan_risk": ["taiwan", "china", "tsmc", "strait", "invasion", "blockade", "xi"],
    "market_stress": ["bank failure", "default", "crisis", "liquidity", "credit crunch", "recession", "vix spike", "panic"],
    "biotech_catalyst": ["fda", "phase 3", "clinical trial", "approval", "biotech", "drug", "glp-1", "ozempic", "wegovy"],
    "agriculture_food": ["wheat", "corn", "soybean", "fertilizer", "potash", "drought", "harvest", "crop"],
    "fx_usd_strength": ["dollar strength", "dxy", "usd strength", "dollar surge", "carry trade unwind"],
    "fx_usd_weakness": ["dollar weakness", "dxy fall", "yen rally", "euro rally"],
    "credit_stress": ["credit spread", "high yield", "junk bond", "default", "bankruptcy", "downgrade"],
    "supply_chain_disruption": ["supply chain", "shipping", "container", "port", "houthi", "red sea", "panama canal", "logistics"],
    "real_estate_stress": ["commercial real estate", "office", "vacancy", "reit", "real estate", "housing", "mortgage"],
    "consumer_discretionary": ["consumer spending", "retail sales", "holiday shopping", "consumer confidence"],
    "defensive_rotation": ["defensive", "rotation", "risk off", "quality", "dividend"],
    "canada_specific": ["canada", "tsx", "boc", "bank of canada", "ontario", "alberta", "loonie", "cad"],
}

def classify_narrative(text: str, fallback_symbol: str = "SPY") -> str:
    lower = text.lower()
    scores = {k: sum(1 for w in words if w in lower) for k, words in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        sym_upper = fallback_symbol.upper()
        if sym_upper.endswith(".TO") or sym_upper.endswith(".V") or sym_upper.endswith(".CN"):
            return "canada_specific"
        if sym_upper in {"SPY", "QQQ", "IWM", "VIXY"}:
            return "market_stress"
        return "single_name"
    return best

def map_instruments(narrative: str, symbol: str, direction: str) -> List[Dict[str, Any]]:
    if narrative == "single_name":
        return [{"symbol": symbol.upper(), "asset_type": "stock", "direction": direction.upper(), "reason": "direct symbol mapping"}]
    return NARRATIVE_MAP.get(narrative, [{"symbol": symbol.upper(), "asset_type": "stock", "direction": direction.upper(), "reason": "direct mapping"}])
