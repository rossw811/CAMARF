"""
CAMARF research/rough_volatility.py — comparison/diagnostic script, NOT
part of the production pipeline (2026-08-02).

Ross asked for a comparison arm against wfa.py's existing GARCH-based
garch_stop vol-regime detection: is realized volatility itself "rough"
(Gatheral, Jaisson & Rosenbaum, 2018, "Volatility is Rough" — real-market
realized vol has a Hurst exponent H around 0.1, far rougher/more anti-
persistent than a standard diffusive process's H=0.5), and if so, does
garch_stop's implicit assumption (vol evolves smoothly/persistently, the
standard GARCH picture) hold up against CAMARF's own confirmed pairs?

Method: build a realized-volatility series (rolling std of returns), work
in LOG space (matching Gatheral et al.'s convention — log-RV, not RV
levels), then estimate its Hurst exponent with the SAME three already-
verified estimators this project already uses for spread mean-reversion
quality (analysis.py::HurstEstimator.hurst_rs/hurst_dfa,
wavelet_hurst_comparison.py::wavelet_hurst) — reused directly, not
reimplemented, for a true apples-to-apples reading against every other H
number already in this project's record.

DISCLOSED LIMITATION: this is a diagnostic-only comparison (Ross's
"research/comparison sake first" framing) — it does NOT wire a rough-vol
model into wfa.py/backtest.py. Whether to build a rough-vol-based
alternative to garch_stop is a separate, later decision.

Usage:
    python research/rough_volatility.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price
from analysis import HurstEstimator
from wavelet_hurst_comparison import wavelet_hurst

_CONFIRMED_PAIRS = [("KVUE", "KMB")]
_CONFIRMED_TFS = ["2min", "3min"]


def realized_vol_series(returns: np.ndarray, window: int = 30) -> np.ndarray:
    """Rolling std of returns, log-transformed (Gatheral et al.'s log-RV
    convention). NaN for the first (window-1) bars (insufficient history)."""
    r = pd.Series(returns)
    rv = r.rolling(window).std().values
    with np.errstate(divide="ignore", invalid="ignore"):
        log_rv = np.log(rv)
    return log_rv


def vol_roughness(log_rv: np.ndarray) -> dict:
    """H_rs/H_dfa/H_wavelet of the log-realized-vol series, using this
    project's existing, already-verified estimators unchanged."""
    clean = log_rv[np.isfinite(log_rv)]
    if len(clean) < 100:
        return {"h_rs": np.nan, "h_dfa": np.nan, "h_wavelet": np.nan, "n": len(clean)}
    return {
        "h_rs": float(HurstEstimator.hurst_rs(clean)),
        "h_dfa": float(HurstEstimator.hurst_dfa(clean)),
        "h_wavelet": float(wavelet_hurst(clean)),
        "n": len(clean),
    }


def main():
    ap = argparse.ArgumentParser(description="Rough volatility diagnostic (2026-08-02)")
    ap.add_argument("--rv-window", type=int, default=30)
    args = ap.parse_args()

    rows = []
    for sym_a, sym_b in _CONFIRMED_PAIRS:
        for tf in _CONFIRMED_TFS:
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf)
            if df_a is None or df_b is None or df_a.empty or df_b.empty:
                print(f"skip {sym_a}/{sym_b}@{tf}: no aligned data")
                continue
            for sym, df in ((sym_a, df_a), (sym_b, df_b)):
                log_p = _gap_masked_log_price(df)
                r = np.diff(log_p)
                r = r[np.isfinite(r)]
                if len(r) < 200:
                    print(f"skip {sym}@{tf}: only {len(r)} clean returns")
                    continue
                log_rv = realized_vol_series(r, window=args.rv_window)
                rough = vol_roughness(log_rv)
                print(f"\n{sym}@{tf}: n_rv_bars={rough['n']}")
                print(f"  H_rs={rough['h_rs']:.3f}  H_dfa={rough['h_dfa']:.3f}  "
                      f"H_wavelet={rough['h_wavelet']:.3f}  (H=0.5 -> smooth/diffusive, H<<0.5 -> rough)")
                rows.append({"symbol": sym, "tf": tf, **rough})

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    if rows:
        pd.DataFrame(rows).to_parquet(os.path.join(out_dir, "rough_volatility.parquet"))
        print(f"\nResults written to output/research/rough_volatility.parquet")
    else:
        print("\nNo usable output — nothing written.")


if __name__ == "__main__":
    main()
