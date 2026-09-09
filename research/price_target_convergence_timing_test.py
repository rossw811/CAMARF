"""
Tier B item #13 of the 2026-09-08 caveat/limitation search: the pairs-
relative price-target overlay (`price_target_pairs_overlay.py`) tested
one specific hypothesis -- does agreement with the analyst-implied
direction predict trade P&L -- and found an honest negative result
(Finding #65). This tests a genuinely DIFFERENT hypothesis with the same
already-computed data: does the MAGNITUDE of relative analyst-target
divergence predict how a trade actually resolves -- faster convergence
(fewer hold_bars) or a genuine signal-exit (real spread convergence)
rather than a stop-out or max-hold timeout -- regardless of whether the
trade's OWN direction agreed with the analyst-implied one.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

import price_target_pairs_overlay as pto

_TRADES_PATH = os.path.join(_ROOT, "output", "backtest", "baseline_trades_layer1.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "price_target_convergence_timing_test.parquet")


def main():
    trades = pd.read_parquet(_TRADES_PATH)
    permno_map = pto.load_permno_map()
    ibes_df = pd.read_parquet(pto._IBES_PATH)

    print(f"Computing relative divergence for {len(trades)} trades (reusing price_target_"
          f"pairs_overlay.py's exact causal/staleness-gated lookup)...")
    overlay = pto.compute_overlay(trades, permno_map, ibes_df)
    overlay["abs_relative_divergence"] = overlay["relative_divergence"].abs()

    merged = overlay.merge(
        trades[["symbol_a", "symbol_b", "entry_time", "hold_bars", "exit_reason"]],
        on=["symbol_a", "symbol_b", "entry_time"], how="left",
    )
    scored = merged[merged["abs_relative_divergence"].notna()].copy()
    print(f"Scored {len(scored)}/{len(merged)} trades with a usable |relative_divergence|.")

    # --- Test 1: does |relative_divergence| correlate with hold_bars (time to resolution)? ---
    valid = scored.dropna(subset=["hold_bars"])
    r, p = stats.pearsonr(valid["abs_relative_divergence"], valid["hold_bars"])
    print(f"\nTest 1 -- |relative_divergence| vs. hold_bars (n={len(valid)}): "
          f"Pearson r={r:.4f}, p={p:.4f}")

    # --- Test 2: does higher |relative_divergence| predict a genuine signal-exit
    # (real convergence) vs. a stop-out or max-hold timeout? ---
    scored["genuine_convergence_exit"] = scored["exit_reason"] == "signal_exit"
    high_div = scored[scored["abs_relative_divergence"] >= scored["abs_relative_divergence"].median()]
    low_div = scored[scored["abs_relative_divergence"] < scored["abs_relative_divergence"].median()]
    rate_high = high_div["genuine_convergence_exit"].mean()
    rate_low = low_div["genuine_convergence_exit"].mean()
    print(f"\nTest 2 -- signal-exit rate, high vs. low |relative_divergence| "
          f"(split at median): {rate_high:.2%} (n={len(high_div)}) vs. {rate_low:.2%} "
          f"(n={len(low_div)})")
    n1, n2 = high_div["genuine_convergence_exit"].sum(), low_div["genuine_convergence_exit"].sum()
    p_pool = (n1 + n2) / (len(high_div) + len(low_div))
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / len(high_div) + 1 / len(low_div)))
    z = (rate_high - rate_low) / se if se > 0 else float("nan")
    p_val = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else float("nan")
    print(f"  z={z:.4f}, p={p_val:.4f}")

    result = {
        "n_scored": len(scored), "hold_bars_corr_r": r, "hold_bars_corr_p": p,
        "signal_exit_rate_high_div": rate_high, "signal_exit_rate_low_div": rate_low,
        "signal_exit_z": z, "signal_exit_p": p_val,
    }
    pd.DataFrame([result]).to_parquet(_OUT_PATH)
    print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
