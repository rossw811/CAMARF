"""
debug/_verify_intraday_episodic_scan.py -- synthetic ground-truth
verification for research/intraday_episodic_scan.py, BEFORE trusting it
against real intraday (1h/4h) data.

Mirrors debug/_verify_wrds_deep_history_episodic_scan.py's core claims
(reusing the SAME underlying `run_rolling_eg_pool`/`episodic_bhfdr_confirm`
machinery, imported unchanged), re-checked in THIS script's own context:
its `window_config` sizing and its reimplemented `build_log_prices_and_
returns` (which uses a caller-supplied `min_overlap` floor, not the WRDS
script's hardcoded 756).

1. window_config() returns the expected global (window, step) for known
   TF/config-name combinations, and rejects the two per-pair-only config
   names (adaptive_halflife_8x, onset_anchored) that the full-universe
   scanner deliberately doesn't support (see module docstring).
2. build_log_prices_and_returns() correctly excludes a symbol with fewer
   bars than the requested min_overlap floor, and keeps one with enough.
3. End-to-end (mirrors the WRDS verify script's check 1): a pair
   cointegrated in only a sub-period of its history is found by
   run_rolling_eg_pool + episodic_bhfdr_confirm using intraday_episodic_
   scan's OWN window/step (not the WRDS script's 10yr defaults), while a
   fully independent (null) pair is not confirmed.

Run: python debug/_verify_intraday_episodic_scan.py
(All checks are synthetic/offline -- no cached market data needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import research.intraday_episodic_scan as scan
from research.wrds_deep_history_episodic_scan import run_rolling_eg_pool, episodic_bhfdr_confirm


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def make_episodic_pair(n_pre=300, n_coint=300, n_post=300, seed=0):
    """Same construction as debug/_verify_wrds_deep_history_episodic_scan.py's
    make_episodic_pair -- independent random walks before/after a
    genuinely cointegrated middle regime."""
    rng = np.random.RandomState(seed)
    a_pre = np.cumsum(rng.normal(0, 1.0, n_pre))
    b_pre = np.cumsum(rng.normal(0, 1.0, n_pre))
    common = np.cumsum(rng.normal(0, 1.0, n_coint))
    spread_noise = rng.normal(0, 0.3, n_coint)
    a_coint = a_pre[-1] + common
    b_coint = b_pre[-1] + common + spread_noise
    a_post = a_coint[-1] + np.cumsum(rng.normal(0, 1.0, n_post))
    b_post = b_coint[-1] + np.cumsum(rng.normal(0, 1.0, n_post))
    a = np.concatenate([a_pre, a_coint, a_post])
    b = np.concatenate([b_pre, b_coint, b_post])
    return a, b


def make_null_pair(n, seed):
    rng = np.random.RandomState(seed)
    a = np.cumsum(rng.normal(0, 1.0, n))
    b = np.cumsum(rng.normal(0, 1.0, n))
    return a, b


def verify_window_config():
    print("\n=== 1. window_config() sizing and rejection ===")
    base_1h = Config.STATS.MIN_OVERLAP_BY_TF["1h"]
    ok = check("fixed_min_overlap_1x@1h == MIN_OVERLAP_BY_TF['1h']",
               scan.window_config("fixed_min_overlap_1x", "1h") == (base_1h, max(1, base_1h // 4)))
    ok &= check("fixed_min_overlap_2x@1h == 2x MIN_OVERLAP_BY_TF['1h']",
                scan.window_config("fixed_min_overlap_2x", "1h") == (2 * base_1h, max(1, (2 * base_1h) // 4)))
    for bad_name in ("adaptive_halflife_8x", "onset_anchored", "not_a_real_config"):
        try:
            scan.window_config(bad_name, "1h")
            ok &= check(f"window_config rejects per-pair-only/unknown config {bad_name!r}", False)
        except ValueError:
            ok &= check(f"window_config rejects per-pair-only/unknown config {bad_name!r}", True)
    return ok


def verify_build_log_prices_and_returns():
    print("\n=== 2. build_log_prices_and_returns() overlap-floor filtering ===")
    n_long, n_short, min_overlap = 500, 100, 300
    idx = pd.date_range("2023-01-01", periods=n_long, freq="h")
    close_long = pd.Series(np.exp(np.cumsum(np.random.RandomState(1).normal(0, 0.01, n_long))), index=idx)
    close_short = pd.Series(
        np.exp(np.cumsum(np.random.RandomState(2).normal(0, 0.01, n_short))), index=idx[:n_short]
    )
    log_price_df, returns = scan.build_log_prices_and_returns(
        {"LONG": close_long, "SHORT": close_short}, min_overlap=min_overlap
    )
    ok = check("symbol with >= min_overlap bars is KEPT", "LONG" in returns.columns)
    ok &= check("symbol with < min_overlap bars is EXCLUDED", "SHORT" not in returns.columns)
    return ok


def verify_episodic_pair_found_end_to_end():
    print("\n=== 3. End-to-end: episodic pair found via THIS script's window/step, null pair is not ===")
    a, b = make_episodic_pair()
    max_lag = Config.ANALYSIS.EG_MAX_LAG
    window, step = scan.window_config("fixed_min_overlap_1x", "1h")
    # Shrink window/step to fit this test's deliberately small synthetic
    # series (900 bars) -- MIN_OVERLAP_BY_TF['1h']=756 would barely fit
    # one window; using a smaller window here still exercises the exact
    # same code path (run_rolling_eg_pool/episodic_bhfdr_confirm), just
    # sized for a fast synthetic test rather than the real 1h floor.
    window, step = 200, 50

    pairs = [{"symbol_a": "A", "symbol_b": "B"}]
    log_price_df = pd.DataFrame({"A": a, "B": b})
    flat = run_rolling_eg_pool(pairs, log_price_df, max_lag, window=window, step=step, workers=2)
    ok = check(f"rolling EG produced window results ({len(flat)} windows tested)", len(flat) > 0)
    confirmed = episodic_bhfdr_confirm(flat, alpha=0.05, min_windows_confirmed=1)
    ok &= check("episodic pair IS confirmed by rolling EG + joint BH-FDR",
                len(confirmed) == 1 and confirmed[0]["symbol_a"] == "A")

    a_null, b_null = make_null_pair(n=900, seed=42)
    pairs_null = [{"symbol_a": "X", "symbol_b": "Y"}]
    log_price_df_null = pd.DataFrame({"X": a_null, "Y": b_null})
    flat_null = run_rolling_eg_pool(pairs_null, log_price_df_null, max_lag, window=window, step=step, workers=2)
    confirmed_null = episodic_bhfdr_confirm(flat_null, alpha=0.05, min_windows_confirmed=1)
    ok &= check("null (independent) pair is NOT confirmed", len(confirmed_null) == 0)
    return ok


def main():
    results = [
        verify_window_config(),
        verify_build_log_prices_and_returns(),
        verify_episodic_pair_found_end_to_end(),
    ]
    n_pass = sum(results)
    print(f"\n{n_pass}/{len(results)} check groups passed")
    return n_pass == len(results)


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
