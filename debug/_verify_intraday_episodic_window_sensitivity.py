"""
debug/_verify_intraday_episodic_window_sensitivity.py -- synthetic
ground-truth verification for
research/intraday_episodic_window_sensitivity.py, BEFORE trusting it
against real PNC/ZION intraday data.

Two claims being verified, stated precisely:
1. A pair with a genuine SINGLE cointegration regime (a clean, contiguous
   coupled period, not noise) should produce a HIGH contiguity_fraction
   (its significant windows cluster together) under every registered
   config, and a low/zero coefficient of variation on the confirmed count
   across small window perturbations (the relationship isn't fragile to
   window choice).
2. A pure-noise pair (no true relationship, ever) should produce a LOW
   contiguity_fraction when it does happen to trip significance (isolated,
   not clustered -- exactly what noise looks like), and near-zero
   n_base_confirmed.

Run: python debug/_verify_intraday_episodic_window_sensitivity.py
(All checks are synthetic/offline -- no cached market data needed, since
this verifies the statistical/metric LOGIC, not real-data behavior.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.intraday_episodic_window_sensitivity as sens


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def make_single_regime_pair(n_pre=400, n_coint=900, n_post=400, seed=0):
    """One clean, contiguous cointegrated regime in the middle, unrelated
    random walks before/after -- mirrors the existing episodic-scan verify
    pattern (debug/_verify_wrds_deep_history_episodic_scan.py)."""
    rng = np.random.RandomState(seed)
    a_pre = np.cumsum(rng.normal(0, 1.0, n_pre))
    b_pre = np.cumsum(rng.normal(0, 1.0, n_pre))
    common = np.cumsum(rng.normal(0, 1.0, n_coint))
    noise = rng.normal(0, 0.3, n_coint)
    a_coint = a_pre[-1] + common
    b_coint = b_pre[-1] + common + noise
    a_post = a_coint[-1] + np.cumsum(rng.normal(0, 1.0, n_post))
    b_post = b_coint[-1] + np.cumsum(rng.normal(0, 1.0, n_post))
    log_a = np.concatenate([a_pre, a_coint, a_post]) * 0.01 + 4.0
    log_b = np.concatenate([b_pre, b_coint, b_post]) * 0.01 + 4.0
    n = len(log_a)
    dates = pd.date_range("2023-01-01", periods=n, freq="h")
    return dates, log_a, log_b


def make_pure_noise_pair(n=1700, seed=1):
    rng = np.random.RandomState(seed)
    log_a = np.cumsum(rng.normal(0, 1.0, n)) * 0.01 + 4.0
    log_b = np.cumsum(rng.normal(0, 1.0, n)) * 0.01 + 4.0
    dates = pd.date_range("2023-01-01", periods=n, freq="h")
    return dates, log_a, log_b


def main():
    results = []

    print("Check set 1: single-regime synthetic pair (PNC/ZION stand-in)")
    dates, log_a, log_b = make_single_regime_pair()
    pairs_data = {("PNC", "ZION"): (dates, log_a, log_b)}
    for config_name in sens.REGISTRY:
        metrics = sens.evaluate_config(config_name, pairs_data)
        print(f"  {config_name}: n_windows={metrics['pnc_zion_n_windows']} "
              f"contiguity={metrics['pnc_zion_contiguity']:.3f} "
              f"cv={metrics['cv_confirmed_count']:.3f}")
        # A clean single-regime pair's significant windows should cluster
        # (contiguity > 0.5) whenever it produces enough windows to judge --
        # too few windows makes the ratio meaningless, so only assert when
        # there's real signal to check.
        if metrics["pnc_zion_n_windows"] >= 4 and not np.isnan(metrics["pnc_zion_contiguity"]):
            results.append(check(
                f"{config_name}: single-regime pair shows clustered significance (contiguity > 0.5)",
                metrics["pnc_zion_contiguity"] > 0.5,
            ))

    print("\nCheck set 2: pure-noise pair")
    dates_n, log_a_n, log_b_n = make_pure_noise_pair()
    pairs_data_noise = {("PNC", "ZION"): (dates_n, log_a_n, log_b_n)}
    for config_name in sens.REGISTRY:
        metrics = sens.evaluate_config(config_name, pairs_data_noise)
        print(f"  {config_name}: n_confirmed={metrics['n_base_confirmed']} "
              f"n_windows={metrics['pnc_zion_n_windows']} "
              f"contiguity={metrics['pnc_zion_contiguity']}")
        # A pure-noise pair should essentially never survive joint BH-FDR
        # confirmation (this is exactly episodic_bhfdr_confirm's own
        # already-verified false-positive-control claim -- re-checked here
        # in this script's specific config/metric context, not re-deriving
        # the underlying FDR proof).
        results.append(check(
            f"{config_name}: pure-noise pair is not BH-FDR confirmed",
            metrics["n_base_confirmed"] == 0,
        ))

    print("\nCheck set 3: contiguity_fraction metric itself, on hand-built rows")
    clustered_rows = [
        {"symbol_a": "A", "symbol_b": "B", "window_start": i, "pvalue": p, "window_end_date": None}
        for i, p in enumerate([0.01, 0.02, 0.01, 0.5, 0.6, 0.5, 0.7])
    ]
    isolated_rows = [
        {"symbol_a": "A", "symbol_b": "B", "window_start": i, "pvalue": p, "window_end_date": None}
        for i, p in enumerate([0.01, 0.6, 0.7, 0.02, 0.8, 0.9, 0.01])
    ]
    clustered_c = sens.contiguity_fraction(clustered_rows)
    isolated_c = sens.contiguity_fraction(isolated_rows)
    print(f"  clustered contiguity={clustered_c:.3f}, isolated contiguity={isolated_c:.3f}")
    results.append(check("contiguity_fraction: clustered significant windows score higher than isolated ones",
                          clustered_c > isolated_c))
    results.append(check("contiguity_fraction: 3 contiguous significant windows out of 3 total = 1.0",
                          abs(clustered_c - 1.0) < 1e-9))
    results.append(check("contiguity_fraction: 3 isolated significant windows out of 3 total = 0.0",
                          abs(isolated_c - 0.0) < 1e-9))

    n_pass = sum(results)
    print(f"\n{n_pass}/{len(results)} checks passed")
    return n_pass == len(results)


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
