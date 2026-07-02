"""
research/corporate_actions_audit.py — spot-check that data.py's corporate-
actions handling (yfinance auto_adjust=True, set at data.py:1698,1782,1994)
is actually behaving correctly on real data, not just requested.

Motivation (STORM infrastructure gap analysis, 2026-07-01): corporate-actions
handling was rated "Partial" — yfinance adjusts at the source, but nothing in
this project had ever independently verified that adjustment is actually
landing correctly in the cached data. This is the cheap spot-check that
rating called for, not a full reconciliation module: yfinance already
handles corporate actions upstream, so the only real question is whether
CAMARF's fetch is actually requesting and receiving adjusted data, which
`auto_adjust=True` in the fetch call answers at the code level, and this
script confirms empirically for known, real splits.

Method: known real-world stock splits with public effective dates are
checked against CAMARF's own cached 1D series. If auto_adjust is NOT working,
the split date would show a huge single-bar return (e.g., -90% for a 10:1
split) and a price level roughly `ratio`x higher before the split than after.
If auto_adjust IS working (as data.py requests), the price series is smooth
through the split date at the already-adjusted level throughout.

This audits data.py's OWN mechanism (yfinance auto-adjustment), not a
CAMARF-built corporate-actions module — there isn't one, and per the STORM
gap analysis this is correctly lower-priority than building one, since the
upstream adjustment already appears to be working.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from data import DataStore

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("corporate_actions_audit")

# (symbol, effective split date, ratio, description) — all within CAMARF's
# cached 1D history window, all real, publicly documented splits.
_KNOWN_SPLITS = [
    ("NVDA", "2024-06-10", 10, "NVIDIA 10-for-1"),
    ("WMT", "2024-02-26", 3, "Walmart 3-for-1"),
    ("SMCI", "2024-10-01", 10, "Super Micro Computer 10-for-1"),
    ("CMG", "2024-06-25", 50, "Chipotle 50-for-1"),
]

# A single-bar |return| above this, right at a known split date, would
# indicate the split was NOT adjusted for (a true unadjusted N:1 split
# produces a ~(1 - 1/N) single-bar drop — e.g. -90% for 10:1).
_UNADJUSTED_RETURN_THRESHOLD = 0.25


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_corporate_actions_audit.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def check_split(symbol: str, split_date: str, ratio: int, description: str) -> dict:
    """Returns a result dict; does not raise on missing data (logs and skips)."""
    df = DataStore.load(symbol, "1D")
    if df is None:
        return {"symbol": symbol, "description": description, "status": "NOT_IN_CACHE"}

    sd = pd.Timestamp(split_date)
    window = df.loc[(df.index >= sd - pd.Timedelta(days=3)) & (df.index <= sd + pd.Timedelta(days=3))]
    if window.empty or len(window) < 2:
        return {"symbol": symbol, "description": description, "status": "NO_DATA_NEAR_SPLIT_DATE"}

    closes = window["close"]
    rets = closes.pct_change().dropna()
    max_abs_ret = float(rets.abs().max())
    unadjusted = max_abs_ret > _UNADJUSTED_RETURN_THRESHOLD

    return {
        "symbol": symbol,
        "description": description,
        "split_date": split_date,
        "ratio": ratio,
        "status": "UNADJUSTED_ARTIFACT_FOUND" if unadjusted else "ADJUSTED_CORRECTLY",
        "max_abs_return_near_split": max_abs_ret,
        "price_before": float(closes.iloc[0]),
        "price_after": float(closes.iloc[-1]),
    }


def main():
    _setup_logging()
    log.info("=== corporate_actions_audit.py: spot-check yfinance auto_adjust on real known splits ===")

    results = [check_split(*args) for args in _KNOWN_SPLITS]
    checked = [r for r in results if r["status"] in ("ADJUSTED_CORRECTLY", "UNADJUSTED_ARTIFACT_FOUND")]
    skipped = [r for r in results if r["status"] not in ("ADJUSTED_CORRECTLY", "UNADJUSTED_ARTIFACT_FOUND")]

    for r in results:
        if r["status"] == "ADJUSTED_CORRECTLY":
            log.info(
                f"  {r['symbol']} ({r['description']}, {r['ratio']}:1 on {r['split_date']}): "
                f"ADJUSTED_CORRECTLY — max |return| near split = {r['max_abs_return_near_split']:.4f}, "
                f"price ${r['price_before']:.2f} -> ${r['price_after']:.2f} (already at post-split scale)"
            )
        elif r["status"] == "UNADJUSTED_ARTIFACT_FOUND":
            log.warning(
                f"  {r['symbol']} ({r['description']}): UNADJUSTED_ARTIFACT_FOUND — "
                f"max |return| near split = {r['max_abs_return_near_split']:.4f} exceeds "
                f"{_UNADJUSTED_RETURN_THRESHOLD:.0%} threshold"
            )
        else:
            log.info(f"  {r['symbol']} ({r['description']}): {r['status']} — skipped, not a finding either way")

    n_adjusted = sum(1 for r in checked if r["status"] == "ADJUSTED_CORRECTLY")
    n_unadjusted = sum(1 for r in checked if r["status"] == "UNADJUSTED_ARTIFACT_FOUND")
    log.info(f"--- Result: {n_adjusted}/{len(checked)} known splits show correctly-adjusted prices "
              f"({len(skipped)} symbols not in cache, skipped) ---")
    if n_unadjusted:
        log.warning(f"{n_unadjusted} UNADJUSTED ARTIFACT(S) FOUND — investigate data.py's auto_adjust path")
    elif checked:
        log.info("No unadjusted-split artifacts found in any checked symbol. "
                 "data.py's auto_adjust=True is confirmed working correctly on real data, "
                 "not just requested in code.")
    else:
        log.warning("No known-split symbols were found in cache — audit inconclusive this run.")

    out_df = pd.DataFrame(results)
    out_path = os.path.join(_ROOT, "output", "research", "corporate_actions_audit.parquet")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out_df.to_parquet(out_path, index=False)
    log.info(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
