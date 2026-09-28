"""
Regression test for code-review finding D16 (2026-09-27): crypto/futures/commodity symbols were labelled by their
bare root (BTC, ES, CL, ...). CL/ES/CC/LTC are also US stock tickers, so both instruments shared one cache file
(ES_1day.parquet held Eversource Energy, not the E-mini), universe_loader shadowed Binance Litecoin with the LTC
Properties stock merged later from WRDS, and _to_yf_ticker had no futures branch (a daily "ES" fetch downloaded the
stock). Also data._is_crypto only recognises "-USD"-style suffixes, so bare crypto labels got equity gap handling.
Fix: instrument_labels.instrument_label -- crypto "<SYM>-USD", futures/commodity "<SYM>=F"; equities unchanged.
Checks:
  1. the raw universe has distinct labels for ES (equity) and ES=F (futures), CL / CL=F, CC / CC=F, LTC / LTC-USD;
     every crypto label ends -USD and every futures/commodity label =F; no label appears under two classes;
  2. their DataStore cache paths differ;
  3. _to_yf_ticker maps futures to "=F" (bare or labelled input) and crypto to "-USD";
  4. _is_crypto recognises every crypto label;
  5. universe_loader labels Binance files "<SYM>-USD", so Binance LTC and WRDS LTC are separate entries;
  6. root_symbol recovers the IBKR root.
Run: python debug/_verify_instrument_labels_no_collision.py
"""
import collections
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import universe_loader as ul
from data import DataStore, UniverseBuilder, _is_crypto, _to_yf_ticker
from instrument_labels import root_symbol

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    raw = UniverseBuilder()._build_raw_list()
    by = collections.defaultdict(set)
    for s, c in raw:
        by[s].add(c)
    multi = {s: c for s, c in by.items() if len(c) > 1}
    check("no_label_in_two_classes", not multi, f"{multi}")
    labels = set(by)
    check("distinct_pairs_present", {"ES", "ES=F", "CL", "CL=F", "CC", "CC=F", "LTC", "LTC-USD"} <= labels,
          f"missing={sorted({'ES', 'ES=F', 'CL', 'CL=F', 'CC', 'CC=F', 'LTC', 'LTC-USD'} - labels)}")
    bad = [(s, c) for s, c in raw if (c == "crypto" and not s.endswith("-USD"))
           or (c in ("futures", "commodity") and not s.endswith("=F"))]
    check("namespaced_classes", not bad, f"{bad[:5]}")
    check("cache_paths_differ", DataStore._path("ES", "1D") != DataStore._path("ES=F", "1D")
          and DataStore._path("LTC", "1h") != DataStore._path("LTC-USD", "1h"))
    check("yf_ticker_futures", _to_yf_ticker("ES", "futures") == "ES=F" and _to_yf_ticker("ES=F", "futures") == "ES=F"
          and _to_yf_ticker("NG=F", "commodity") == "NG=F", f"{_to_yf_ticker('ES', 'futures')}")
    check("yf_ticker_crypto", _to_yf_ticker("BTC-USD", "crypto") == "BTC-USD" and _to_yf_ticker("BTC", "crypto") == "BTC-USD")
    check("is_crypto_all_labels", all(_is_crypto(s) for s, c in raw if c == "crypto"))
    check("root_symbol", root_symbol("ES=F") == "ES" and root_symbol("LTC-USD") == "LTC" and root_symbol("AAPL") == "AAPL")

    root = tempfile.mkdtemp(prefix="verify_d16_")
    d = {k: os.path.join(root, k) for k in ("yf", "wrds", "bin", "ibkr", "memo")}
    for v in d.values():
        os.makedirs(v)
    orig = (ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR)
    ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = (
        d["yf"], d["wrds"], d["bin"], d["ibkr"], d["memo"])
    try:
        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        pd.DataFrame({"close": [44.0 + i for i in range(60)], "volume": 1.0}, index=idx).to_parquet(
            os.path.join(d["bin"], "LTC_1d.parquet"))
        pd.DataFrame({"close": [34.0 + 0.1 * i for i in range(60)], "volume": 1.0}, index=idx).to_parquet(
            os.path.join(d["wrds"], "LTC_1D.parquet"))
        m = ul.load_full_universe("1D", use_memo_cache=False, dedupe=False)
        ok = "LTC-USD" in m and "LTC" in m and float(m["LTC-USD"]["close"].iloc[0]) == 44.0 \
            and float(m["LTC"]["close"].iloc[0]) == 34.0
        check("loader_binance_not_shadowed", ok, f"keys={sorted(m)}")
    finally:
        ul._YF_CACHE_DIR, ul._WRDS_CACHE_DIR, ul._BINANCE_CACHE_DIR, ul._IBKR_CACHE_DIR, ul._MEMO_CACHE_DIR = orig
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
