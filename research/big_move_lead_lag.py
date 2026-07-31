"""
CAMARF research/big_move_lead_lag.py — comparison/diagnostic script, NOT
part of the production pipeline (2026-07-14, task #69 Piece C, built per
Ross's direction: generalize earnings_lead_lag.py's earnings-window
conditioning to ANY large, volatility-standardized move on one leg, so
the test isn't limited to (and doesn't require) scheduled earnings
events).

Question: when one leg has a large idiosyncratic move (relative to its
OWN recent volatility, not an absolute threshold), does the other leg's
subsequent move show a genuine LAG — a delayed reaction distinct from
plain contemporaneous co-movement, which is already what the existing
cointegration/mean-reversion signal captures. Earnings moves are one
source of such shocks (and are captured here as a subset, with no
earnings-specific machinery), but this also captures any other
idiosyncratic jump — guidance, analyst actions, single-name news — that
a cointegrated leg might or might not transmit to its partner.

Deliberately mirrors earnings_lead_lag.py's structure (same
lagged_corr_scan/best_lag foundation, same bootstrap-null-by-random-
anchor-window comparison) so results are directly comparable across the
two scripts for the same pairs.

Methodological care, stated up front:
  - Volatility standardization is CAUSAL/TRAILING ONLY: bar t's threshold
    uses a rolling window of the PRECEDING `vol_window` bars (shifted by
    1, so bar t's own return never contributes to its own threshold).
    Using a centered or full-sample vol estimate here would be a
    lookahead bug — a move only counts as "big" if it would have looked
    big using information available strictly before it happened.
  - The z-score threshold (2.0) and vol window (20 bars) are fixed
    BEFORE running, not tuned by trying several and reporting the best
    — per this project's Garden-of-Forking-Paths discipline, sweeping
    thresholds after seeing results would be its own set of undisclosed
    trials.
  - The result to watch is the BEST-LAG value, not just significance:
    lag=0 with a strong correlation is indistinguishable from "these are
    cointegrated, they move together" (already known, not new). A
    genuinely new, exploitable finding needs a non-zero best_lag with a
    real bootstrap-significant correlation at that lag.
  - Read-only: loads cached price data via aligned_pair_loader, no
    external fetch of any kind (unlike Piece B, no yfinance dependency
    at all).

Usage:
    python research/big_move_lead_lag.py
    python research/big_move_lead_lag.py --tf 1h --z-threshold 2.0 --vol-window 20 --window-days 3
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from data import DataStore, _gap_aware_returns
from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import best_lag, _MIN_CORR_N

# Same stable starting set as earnings_lead_lag.py, for direct comparability.
_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]


def _big_move_dates(ret: pd.Series, z_threshold: float, vol_window: int) -> list:
    """Dates where |ret| exceeds z_threshold * trailing (shifted) rolling
    std — causal only, bar t's own value never contributes to its own
    threshold.

    ret comes from a dense calendar-grid-aligned series (aligned_pair_loader)
    where most rows are NaN placeholders for non-trading time — only a
    minority of rows are real bars. Rolling stats MUST be computed on the
    compacted (NaN-dropped) real-bar series, not the dense grid directly:
    a rolling window over the dense grid almost never lands on `vol_window`
    consecutive real values, so trailing_vol would come back all-NaN and
    silently find zero events (caught directly on real LNT/VTR data,
    2026-07-14 — see debug/_verify_big_move_lead_lag.py).
    """
    compact = ret.dropna()
    trailing_vol = compact.rolling(vol_window).std().shift(1)
    z = compact / trailing_vol
    big = (z.abs() > z_threshold).reindex(ret.index, fill_value=False)
    return sorted(set(pd.DatetimeIndex(big[big].index).normalize()))


def _window_mask(index: pd.DatetimeIndex, event_dates, window_days: int) -> np.ndarray:
    if not event_dates:
        return np.zeros(len(index), dtype=bool)
    dates_only = index.normalize()
    mask = np.zeros(len(index), dtype=bool)
    for d in event_dates:
        mask |= (np.abs((dates_only - d).days) <= window_days)
    return mask


def _event_windows(index: pd.DatetimeIndex, event_dates, window_days: int):
    """Returns a list of (start_ts, end_ts) CONTIGUOUS windows, one per
    event date, instead of one combined boolean mask -- kept separate so a
    later lagged shift/join never crosses from the tail of one event's
    window into the head of an unrelated, possibly months-distant one.
    Fixes Tier 2.3 (Grand Sweep 2026-07-20), same defect class copied
    verbatim from earnings_lead_lag.py: boolean-masking all events into one
    compacted array and shifting THAT loses each window's real-time
    boundary, since pandas .shift() is purely positional."""
    windows = []
    dates_only = index.normalize()
    for d in event_dates:
        in_window = np.abs((dates_only - d).days) <= window_days
        if in_window.any():
            windows.append((index[in_window].min(), index[in_window].max()))
    return windows


def _pooled_scan(ret_a: pd.Series, ret_b: pd.Series, mask: np.ndarray, windows, max_lag: int):
    """Runs the lagged-correlation scan across multiple disjoint contiguous
    `windows` without ever shifting across a window boundary -- see
    earnings_lead_lag.py's identical fix for the full mechanism. `mask` is
    used only for the cheap pre-check; the real scan uses `windows`."""
    if mask.sum() < 10 or not windows:
        return None
    scan = {}
    for lag in range(-max_lag, max_lag + 1):
        pooled_a, pooled_b = [], []
        for start, end in windows:
            sub_a = ret_a.loc[start:end]
            sub_b = ret_b.loc[start:end]
            if sub_a.empty or sub_b.empty:
                continue
            shifted_b = sub_b.shift(-lag)
            joined = pd.concat([sub_a, shifted_b], axis=1, join="inner").dropna()
            if joined.empty:
                continue
            pooled_a.append(joined.iloc[:, 0].values)
            pooled_b.append(joined.iloc[:, 1].values)
        if not pooled_a:
            scan[lag] = (None, 0)
            continue
        a_vals = np.concatenate(pooled_a)
        b_vals = np.concatenate(pooled_b)
        n = len(a_vals)
        if n < _MIN_CORR_N:
            scan[lag] = (None, n)
            continue
        c = float(np.corrcoef(a_vals, b_vals)[0, 1])
        if not np.isfinite(c):
            c = None
        scan[lag] = (c, n)
    return best_lag(scan)


def run_pair(symbol_a, symbol_b, tf_label, z_threshold, vol_window, window_days,
             max_lag, n_boot, seed, min_prior_events=5):
    rng = np.random.default_rng(seed)
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return {"symbol_a": symbol_a, "symbol_b": symbol_b, "status": "no_data"}

    ret_a = pd.Series(_gap_aware_returns(df_a), index=df_a.index)
    ret_b = pd.Series(_gap_aware_returns(df_b), index=df_b.index)
    common_idx = ret_a.index.intersection(ret_b.index)
    ret_a, ret_b = ret_a.reindex(common_idx), ret_b.reindex(common_idx)

    results = []
    for mover_series, mover_name, other_name in ((ret_a, symbol_a, symbol_b),
                                                    (ret_b, symbol_b, symbol_a)):
        event_dates = _big_move_dates(mover_series, z_threshold, vol_window)
        event_dates = [d for d in event_dates if common_idx.min() <= d <= common_idx.max()]
        if len(event_dates) < min_prior_events:
            results.append({
                "mover": mover_name, "other_leg": other_name,
                "status": "insufficient_big_move_events",
                "n_events": len(event_dates),
            })
            continue

        mask = _window_mask(common_idx, event_dates, window_days)
        n_bars_in_windows = int(mask.sum())
        windows = _event_windows(common_idx, event_dates, window_days)
        real = _pooled_scan(ret_a, ret_b, mask, windows, max_lag)
        if real is None or real[0] is None:
            results.append({
                "mover": mover_name, "other_leg": other_name,
                "status": "insufficient_pooled_bars",
                "n_events": len(event_dates), "n_bars_in_windows": n_bars_in_windows,
            })
            continue
        real_lag, real_corr, real_n = real

        span_start, span_end = common_idx.min(), common_idx.max()
        span_days = (span_end - span_start).days
        null_abs_corrs = []
        for _ in range(n_boot):
            rand_anchors = [
                span_start + pd.Timedelta(days=int(rng.integers(0, span_days + 1)))
                for _ in range(len(event_dates))
            ]
            null_mask = _window_mask(common_idx, rand_anchors, window_days)
            null_windows = _event_windows(common_idx, rand_anchors, window_days)
            null_result = _pooled_scan(ret_a, ret_b, null_mask, null_windows, max_lag)
            if null_result is not None and null_result[0] is not None:
                null_abs_corrs.append(abs(null_result[1]))

        if not null_abs_corrs:
            results.append({
                "mover": mover_name, "other_leg": other_name,
                "status": "bootstrap_failed", "n_events": len(event_dates),
            })
            continue

        null_abs_corrs = np.array(null_abs_corrs)
        p_value = float(np.mean(null_abs_corrs >= abs(real_corr)))
        results.append({
            "mover": mover_name, "other_leg": other_name, "status": "ok",
            "n_events": len(event_dates), "n_bars_in_windows": n_bars_in_windows,
            "real_best_lag": real_lag, "real_best_corr": real_corr, "real_n": real_n,
            "null_mean_abs_corr": float(null_abs_corrs.mean()),
            "null_p95_abs_corr": float(np.percentile(null_abs_corrs, 95)),
            "bootstrap_p_value": p_value,
        })
    return {"symbol_a": symbol_a, "symbol_b": symbol_b, "legs": results}


def main():
    p = argparse.ArgumentParser(description="Volatility-standardized big-move lead-lag test (2026-07-14)")
    p.add_argument("--tf", default="1h")
    p.add_argument("--z-threshold", type=float, default=2.0)
    p.add_argument("--vol-window", type=int, default=20)
    p.add_argument("--window-days", type=int, default=3)
    p.add_argument("--max-lag", type=int, default=10)
    p.add_argument("--n-boot", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    all_rows = []
    for sym_a, sym_b in _DEFAULT_PAIRS:
        res = run_pair(sym_a, sym_b, args.tf, args.z_threshold, args.vol_window,
                        args.window_days, args.max_lag, args.n_boot, args.seed)
        if "legs" not in res:
            print(f"{sym_a}/{sym_b}: {res.get('status')}")
            continue
        for leg in res["legs"]:
            row = {"symbol_a": sym_a, "symbol_b": sym_b, **leg}
            all_rows.append(row)
            if leg["status"] == "ok":
                sig = "SIG" if leg["bootstrap_p_value"] < 0.05 else "ns "
                lag_note = "LAGGED" if leg["real_best_lag"] != 0 else "lag=0 (contemporaneous)"
                print(f"{sig} {leg['mover']}->{leg['other_leg']} ({sym_a}/{sym_b}@{args.tf}): "
                      f"n_events={leg['n_events']} best_lag={leg['real_best_lag']} ({lag_note}) "
                      f"corr={leg['real_best_corr']:.3f} vs null_mean={leg['null_mean_abs_corr']:.3f} "
                      f"(p95={leg['null_p95_abs_corr']:.3f}) -> boot_p={leg['bootstrap_p_value']:.4f}")
            else:
                print(f"    {leg['mover']}->{leg['other_leg']} ({sym_a}/{sym_b}@{args.tf}): "
                      f"{leg['status']} (n_events={leg.get('n_events', 'n/a')})")

    if not all_rows:
        print("No results.")
        return
    out_df = pd.DataFrame(all_rows)
    ok_df = out_df[out_df["status"] == "ok"]
    if not ok_df.empty:
        sig_df = ok_df[ok_df["bootstrap_p_value"] < 0.05]
        sig_lagged_df = sig_df[sig_df["real_best_lag"] != 0]
        print(f"\n{len(sig_df)}/{len(ok_df)} mover->other_leg tests significant "
              f"(bootstrap_p_value < 0.05); {len(sig_lagged_df)} of those at a NON-ZERO lag "
              f"(the only subset that's a genuinely new signal, not just cointegration restated).")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    safe_tf = DataStore._TF_SAFE.get(args.tf, args.tf.lower())
    out_path = os.path.join(out_dir, f"big_move_lead_lag_{safe_tf}.parquet")
    out_df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
