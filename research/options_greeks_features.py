"""
CAMARF research/options_greeks_features.py — comparison/diagnostic script,
NOT part of the production pipeline (2026-08-02).

Ross asked whether options Greeks (gamma especially) add signal to
correlation/convergence detection between a pair's two legs. `options.py`
already has Black-Scholes pricing (black_scholes_call/put) and a realized-
vol IV proxy (realized_vol_proxy) built (Session 27, no paid data) — this
reuses both directly rather than reimplementing, for consistency with
options.py's own documented conventions and limitations.

DISCLOSED LIMITATION, upfront: there is no real options-chain data anywhere
in this project (no paid data source, per options.py's own docstring). Every
Greek here is a MODEL value computed from a fixed ATM/fixed-tenor Black-
Scholes assumption fed options.py's realized-vol proxy as the "implied"
vol — NOT a market-quoted Greek. This inherits the same known
variance-risk-premium bias options.py's own docstring already discloses
(realized vol systematically understates true implied vol). Treat this as
"what would a simple options-pricing model say the convexity/vega profile
looks like," not "what the options market is actually pricing."

Method: for each leg, compute a daily ATM (K=S), fixed-tenor (30 calendar
days) Black-Scholes gamma/delta/vega time series using realized_vol_proxy
as the vol input. Correlate the pair's gamma spread (|gamma_a - gamma_b|,
a convexity-mismatch measure) against the pair's own rolling realized
return correlation, to test whether convexity mismatch coincides with
periods of stronger/weaker co-movement.

Usage:
    python research/options_greeks_features.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from options import load_price_series, realized_vol_proxy, black_scholes_greeks_vectorized
from pair_source import confirmed_pairs_list

_TENOR_DAYS = 30


def bs_greeks(S: np.ndarray, K: np.ndarray, T: float, sigma: np.ndarray, r: float = 0.0) -> dict:
    """Thin wrapper around options.py's shared black_scholes_greeks_vectorized (added
    2026-09-07, "options calc unit" work) -- this script's own local Greeks implementation was
    a byte-for-byte duplicate of that math; consolidated to a single source of truth rather
    than risking future drift between two copies of the same d1/d2 formulas."""
    return black_scholes_greeks_vectorized(S, K, T, sigma, r, option_type="call")


def rolling_correlation(ret_a: pd.Series, ret_b: pd.Series, window: int = 30) -> pd.Series:
    return ret_a.rolling(window).corr(ret_b)


def main():
    ap = argparse.ArgumentParser(description="Options Greeks vs. pair correlation diagnostic (2026-08-02)")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--pit-safe", action="store_true",
                     help="Source pairs from research/pit_pair_discovery.py's PIT-safe episodic "
                          "screen instead of the current static confirmed-pair set (task #5). "
                          "This script loads daily price series directly (not TF-aware), so only "
                          "the (symbol_a, symbol_b) part of each PIT-safe triple is used, "
                          "deduplicated.")
    args = ap.parse_args()

    T = _TENOR_DAYS / 365.0

    if args.pit_safe:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pit_pairs = discover_pit_confirmed_pairs()
        confirmed_pairs = sorted(set((a, b) for a, b, _tf in pit_pairs))
        print(f"Using PIT-safe episodic pair discovery: {len(confirmed_pairs)} unique pairs")
    else:
        confirmed_pairs = confirmed_pairs_list()
        if not confirmed_pairs:
            print("No confirmed pairs found in output/results/*/pairs.parquet -- run analysis.py first. Aborting.")
            return

    for sym_a, sym_b in confirmed_pairs:
        close_a = load_price_series(sym_a)
        close_b = load_price_series(sym_b)
        if close_a is None or close_b is None:
            print(f"skip {sym_a}/{sym_b}: no daily price cache")
            continue

        idx = close_a.index.intersection(close_b.index)
        close_a, close_b = close_a.reindex(idx), close_b.reindex(idx)
        iv_a = realized_vol_proxy(close_a)
        iv_b = realized_vol_proxy(close_b)

        greeks_a = bs_greeks(close_a.values, close_a.values, T, iv_a.values)  # ATM: K=S
        greeks_b = bs_greeks(close_b.values, close_b.values, T, iv_b.values)

        gamma_spread = pd.Series(np.abs(greeks_a["gamma"] - greeks_b["gamma"]), index=idx)
        ret_a = np.log(close_a).diff()
        ret_b = np.log(close_b).diff()
        roll_corr = rolling_correlation(ret_a, ret_b, window=args.window)

        joined = pd.DataFrame({"gamma_spread": gamma_spread, "roll_corr": roll_corr}).dropna()
        if len(joined) < 60:
            print(f"skip {sym_a}/{sym_b}: only {len(joined)} overlapping clean bars")
            continue

        r, p = pearsonr(joined["gamma_spread"], joined["roll_corr"])
        print(f"\n{sym_a}/{sym_b} (daily, ATM/{_TENOR_DAYS}d-tenor BS gamma, realized-vol proxy):")
        print(f"  n={len(joined)}")
        print(f"  mean gamma_a={np.nanmean(greeks_a['gamma']):.4f}  mean gamma_b={np.nanmean(greeks_b['gamma']):.4f}")
        print(f"  mean gamma_spread={joined['gamma_spread'].mean():.4f}  mean rolling_corr={joined['roll_corr'].mean():.4f}")
        print(f"  corr(gamma_spread, rolling_corr): r={r:.3f}, p={p:.4f}")

        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
        os.makedirs(out_dir, exist_ok=True)
        joined.to_parquet(os.path.join(out_dir, f"options_greeks_features_{sym_a}_{sym_b}.parquet"))
        print(f"  Results written to output/research/options_greeks_features_{sym_a}_{sym_b}.parquet")


if __name__ == "__main__":
    main()
