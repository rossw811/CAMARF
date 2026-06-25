"""
CAMARF annotate_symbol_metadata.py — reproducibility utility, NOT part
of the production pipeline.

Built 2026-06-24 because the "the 9 near_miss_lag_scan.py flagged pairs
cluster by sector" claim (Development.md Session 11 — regional banks
around UCB, asset managers BX/ARES leading STEP, semiconductors
DIOD/VSH) was originally checked with a one-off `python -c` command,
not a saved, rerunnable script — exactly the kind of claim CLAUDE.md's
"always verify file changes actually landed" discipline is meant to
guard against drifting into an untraceable assertion. This makes that
check reproducible: given a parquet file with symbol_a/symbol_b columns
(e.g. near_miss_lag_scan.py's output), looks up each unique symbol's
longName/sector/industry via yfinance .info and writes an annotated
copy alongside the original.

Read-only company metadata (yfinance .info), not historical bars — does
not touch data.py's cache/pipeline. Courteous inter-request delay
(0.3s, matching data.py's own convention and
investigate_price_degeneracy_cause.py's precedent) given this project's
yfinance rate-limit history (BUG-D31).

Usage:
    python annotate_symbol_metadata.py --pairs-file output/research/near_miss_lag_scan_1h.parquet --flagged-only
    python annotate_symbol_metadata.py --symbols CATY UCB FIBK
"""
import argparse
import os
import time

import pandas as pd
import yfinance as yf

_DELAY_SECONDS = 0.3


def lookup_metadata(symbols):
    rows = []
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            rows.append({
                "symbol": sym,
                "long_name": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            })
        except Exception as e:
            rows.append({
                "symbol": sym, "long_name": None, "sector": None,
                "industry": f"ERROR: {type(e).__name__}: {e}",
            })
        time.sleep(_DELAY_SECONDS)
    return pd.DataFrame(rows).set_index("symbol")


def main():
    p = argparse.ArgumentParser(description="Annotate symbols with yfinance sector/industry metadata")
    p.add_argument("--pairs-file", default=None,
                    help="Parquet with symbol_a/symbol_b columns")
    p.add_argument("--flagged-only", action="store_true",
                    help="If --pairs-file has a 'flagged' column, only use flagged rows")
    p.add_argument("--symbols", nargs="+", default=None)
    args = p.parse_args()

    if args.pairs_file:
        df = pd.read_parquet(args.pairs_file)
        if args.flagged_only and "flagged" in df.columns:
            df = df[df["flagged"]]
        symbols = sorted(set(df["symbol_a"]) | set(df["symbol_b"]))
    elif args.symbols:
        symbols = args.symbols
        df = None
    else:
        print("Provide either --pairs-file or --symbols.")
        return

    print(f"Looking up metadata for {len(symbols)} unique symbols...")
    meta = lookup_metadata(symbols)
    print(meta.to_string())

    if df is not None:
        annotated = df.copy()
        annotated["sector_a"] = annotated["symbol_a"].map(meta["sector"])
        annotated["industry_a"] = annotated["symbol_a"].map(meta["industry"])
        annotated["long_name_a"] = annotated["symbol_a"].map(meta["long_name"])
        annotated["sector_b"] = annotated["symbol_b"].map(meta["sector"])
        annotated["industry_b"] = annotated["symbol_b"].map(meta["industry"])
        annotated["long_name_b"] = annotated["symbol_b"].map(meta["long_name"])
        annotated["same_industry"] = annotated["industry_a"] == annotated["industry_b"]

        print(f"\n{annotated['same_industry'].sum()}/{len(annotated)} pairs share the "
              f"identical yfinance industry classification.")

        base, ext = os.path.splitext(args.pairs_file)
        out_path = f"{base}_annotated{ext}"
        annotated.to_parquet(out_path)
        print(f"\nAnnotated copy written to {out_path}")


if __name__ == "__main__":
    main()
