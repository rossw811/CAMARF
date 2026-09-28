"""
instrument_labels.py -- one label per instrument across asset classes (code review D16, 2026-09-27).

Config lists crypto and futures/commodities by bare root symbol (BTC, ES, CL, ...). Four of them are also US stock
tickers (CL Colgate / crude, ES Eversource / E-mini, CC Chemours / cocoa, LTC LTC Properties / Litecoin), and every
cache file, universe label and loader key was the bare symbol -- so the two instruments overwrote each other
(`ES_1day.parquet` held Eversource), the research loader shadowed Binance Litecoin with LTC Properties, and the daily
yfinance ticker for a future was the stock's ticker.

Rule: equities, ETFs, international listings and forex keep their labels (no collision possible: forex carries a
'.', international listings an exchange suffix). Crypto is labelled with Yahoo's ticker "<SYM>-USD"; futures and
commodities with Yahoo's continuous-contract ticker "<SYM>=F". Both are unique, self-describing, and already what
data._is_crypto / the intraday fallback expect.
"""

CRYPTO_SUFFIX = "-USD"
FUTURES_SUFFIX = "=F"
_FUTURES_CLASSES = ("futures", "commodity")


def instrument_label(symbol: str, asset_class: str) -> str:
    """Universe/cache label for a config symbol of the given asset class (idempotent)."""
    s = symbol.upper()
    if asset_class == "crypto":
        return s if s.endswith(CRYPTO_SUFFIX) else s + CRYPTO_SUFFIX
    if asset_class in _FUTURES_CLASSES:
        return s if s.endswith(FUTURES_SUFFIX) else s + FUTURES_SUFFIX
    return symbol


def root_symbol(label: str) -> str:
    """Bare root symbol for a namespaced label (what IBKR contracts and exchange maps are keyed by)."""
    for suf in (CRYPTO_SUFFIX, FUTURES_SUFFIX):
        if label.upper().endswith(suf):
            return label[: -len(suf)]
    return label
