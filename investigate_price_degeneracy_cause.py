"""
CAMARF investigate_price_degeneracy_cause.py — research script, NOT part
of the production pipeline.

Follow-up to BUG-D49's universe-wide audit (32% of the 1m universe
flagged as genuinely liquid but showing degenerate intraday prices).
Confirmed NOT a fetch bug (corroborated against IBKR). Open question:
is there a characterizable pattern among the flagged symbols (sector,
exchange tier, market cap, float) that would explain WHY, turning this
from "we found an anomaly" into "we found and explained a mechanism" —
directly informs whether this becomes a third paper pillar.

Fetches yfinance .info metadata (sector, industry, exchange, market cap,
float) for every symbol evaluated in the 1m price-density audit —
read-only company metadata, NOT historical bars; does not touch data.py's
cache or pipeline. Courteous inter-request delay per this project's own
established convention (data.py's _inter_request_delay) given this
project's prior history with yfinance rate-limiting (BUG-D31).

Usage:
    python investigate_price_degeneracy_cause.py
"""
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

_INTER_REQUEST_DELAY = 0.3


def fetch_metadata(symbol: str) -> dict:
    try:
        info = yf.Ticker(symbol).info
    except Exception as e:
        return {"symbol": symbol, "fetch_ok": False, "error": str(e)[:100]}
    if not info or "quoteType" not in info:
        return {"symbol": symbol, "fetch_ok": False, "error": "empty_info"}
    shares_out = info.get("sharesOutstanding")
    float_shares = info.get("floatShares")
    float_ratio = (float_shares / shares_out) if (shares_out and float_shares) else None
    return {
        "symbol": symbol, "fetch_ok": True,
        "sector": info.get("sector"), "industry": info.get("industry"),
        "exchange": info.get("exchange"), "full_exchange_name": info.get("fullExchangeName"),
        "market_cap": info.get("marketCap"),
        "shares_outstanding": shares_out, "float_shares": float_shares,
        "float_ratio": float_ratio,
        "average_volume": info.get("averageVolume"),
    }


def main():
    audit_path = "output/research/price_degeneracy_audit_1m.parquet"
    if not os.path.exists(audit_path):
        print(f"Missing {audit_path} — run audit_price_degeneracy.py --tf 1m first.")
        return
    audit = pd.read_parquet(audit_path)
    audit["distinct_ratio"] = audit["n_distinct_close"] / audit["n_non_nan"]
    audit["flagged"] = (audit["n_distinct_close"] < 20) | (audit["distinct_ratio"] < 0.02)

    symbols = audit["symbol"].tolist()
    print(f"Fetching yfinance .info metadata for {len(symbols)} symbols "
          f"(~{len(symbols)*_INTER_REQUEST_DELAY/60:.1f} min minimum, plus request latency)...")

    rows = []
    n_failed = 0
    for i, sym in enumerate(symbols):
        if i > 0 and i % 100 == 0:
            print(f"  {i}/{len(symbols)} ({n_failed} failed so far)...")
        meta = fetch_metadata(sym)
        if not meta.get("fetch_ok"):
            n_failed += 1
        rows.append(meta)
        time.sleep(_INTER_REQUEST_DELAY)

    meta_df = pd.DataFrame(rows)
    print(f"\nFetched metadata for {len(meta_df)} symbols, {n_failed} failed.")

    merged = audit.merge(meta_df, on="symbol", how="left")
    out_dir = "output/research"
    os.makedirs(out_dir, exist_ok=True)
    merged.to_parquet(os.path.join(out_dir, "price_degeneracy_with_metadata.parquet"))

    ok = merged[merged["fetch_ok"] == True].copy()
    flagged = ok[ok["flagged"]]
    clean = ok[~ok["flagged"]]
    print(f"\n=== Comparing {len(flagged)} flagged vs {len(clean)} clean symbols ===")

    print("\n--- Exchange tier ---")
    print("Flagged:")
    print((flagged["full_exchange_name"].value_counts(normalize=True) * 100).round(1))
    print("Clean:")
    print((clean["full_exchange_name"].value_counts(normalize=True) * 100).round(1))

    print("\n--- Sector ---")
    print("Flagged:")
    print((flagged["sector"].value_counts(normalize=True) * 100).round(1))
    print("Clean:")
    print((clean["sector"].value_counts(normalize=True) * 100).round(1))

    print("\n--- Market cap (median, $) ---")
    print(f"Flagged: {flagged['market_cap'].median():,.0f}   Clean: {clean['market_cap'].median():,.0f}")

    print("\n--- Float ratio (float_shares / shares_outstanding, median) ---")
    print(f"Flagged: {flagged['float_ratio'].median():.3f}   Clean: {clean['float_ratio'].median():.3f}")

    print("\n--- Average daily volume (median) ---")
    print(f"Flagged: {flagged['average_volume'].median():,.0f}   Clean: {clean['average_volume'].median():,.0f}")

    print(f"\nFull merged data: {out_dir}/price_degeneracy_with_metadata.parquet")


if __name__ == "__main__":
    main()
