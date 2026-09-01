"""
research/decay_rate_at_entry_diagnostic.py -- Thread Q decay-rate path, step 1
(scoped 2026-08-24 in Development.md): does a decay-rate signal AT TRADE ENTRY
correlate with real trade outcome? Answered BEFORE building the sizing/gating
mechanism around it, same verify-before-building discipline as
regime_age_at_entry_diagnostic.py (Thread Q Idea 1 Path D).

For each unique (symbol_a, symbol_b, tf) in a trades file and each of the 9
(signal, smoothing) combinations from research/decay_rate_signals.py:
  - coint_fraction/half_life: reuse the pair's persisted spread_series_*.parquet
    columns (coint_fraction_rolling_t, half_life_rolling_series) directly --
    both already production-computed, causal, PIT-safe.
  - eg_pvalue: computed fresh via decay_rate_signals.expanding_eg_pvalue_series
    on the pair's aligned log-prices (no production column exists for this;
    see that module's docstring).
Each raw series is smoothed + differenced (decay_rate_series), sign-corrected
via decay_rate_direction() so positive always means "strengthening" regardless
of which raw signal, then looked up via a causal as-of (last value at or
before entry_time) at each trade's entry.

Buckets: strengthening (decay_rate > 0), weakening (decay_rate < 0), unknown
(NaN -- insufficient history for that signal/smoothing at entry time).
Reports per-bucket win_rate/mean_pnl/sharpe_proxy PER (signal, smoothing)
combination, plus a Spearman correlation between the raw decay_rate value and
pnl_net (continuous relationship, not forced into 3 buckets).

HONEST LIMITATIONS, disclosed not hidden:
  - Same trades-file staleness/thinness caveat as regime_age_at_entry_diagnostic.py
    -- this reads an EXISTING trades file, inherits its own pair set and any
    staleness relative to the current confirmed-pairs manifest.
  - eg_pvalue recomputation is real work (batched EG over many windows per
    pair) -- can be slow on a pair with a long cached history; not parallelized
    across pairs in this first version (CAMARF's current confirmed-pair count
    is thin enough that this doesn't matter yet).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from data import DataStore
from aligned_pair_loader import load_aligned_pair, resolve_tf_results_dir
from lead_lag_scan import _gap_masked_log_price
from decay_rate_signals import (
    SIGNAL_NAMES, SMOOTHING_NAMES, decay_rate_series, decay_rate_direction,
    expanding_eg_pvalue_series,
)

_MIN_CONFIDENT_N = 10


def _raw_level_series(sym_a, sym_b, tf_label, signal):
    """Returns (values, DatetimeIndex) for one raw signal, or (None, None) if
    unavailable. coint_fraction/half_life reuse the persisted spread_series
    columns directly; eg_pvalue is computed fresh from aligned log-prices."""
    if signal in ("coint_fraction", "half_life"):
        tf_dir = DataStore._TF_SAFE.get(tf_label, tf_label.lower())
        results_dir, _is_stale = resolve_tf_results_dir(tf_dir)
        path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
        if not os.path.exists(path):
            return None, None
        col = "coint_fraction_rolling_t" if signal == "coint_fraction" else "half_life_rolling_series"
        try:
            df = pd.read_parquet(path, columns=[col])
        except Exception:
            return None, None
        if col not in df.columns or df[col].isna().all():
            return None, None
        return df[col].values, df.index

    if signal == "eg_pvalue":
        df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            return None, None
        # load_aligned_pair does NOT guarantee equal-length output (its
        # drop_data_gap_rows=False default) -- the exact bug FINDINGS.md #38
        # already caught for research/ridge_hedge_ratio_comparison.py.
        # Explicit inner join on the shared index before treating the two
        # series as parallel arrays, same fix.
        common_idx = df_a.index.intersection(df_b.index)
        if len(common_idx) < 200:
            return None, None
        df_a, df_b = df_a.loc[common_idx], df_b.loc[common_idx]
        log_a = _gap_masked_log_price(df_a)
        log_b = _gap_masked_log_price(df_b)
        pvals = expanding_eg_pvalue_series(log_a, log_b, tf_label)
        return pvals, common_idx

    raise ValueError(f"Unknown signal: {signal!r}")


def _asof_lookup(values, index, ts):
    """Causal as-of lookup: last non-NaN value at or before ts. NaN if none."""
    s = pd.Series(values, index=index).sort_index()
    s = s[s.index <= ts]
    s = s.dropna()
    if s.empty:
        return np.nan
    return float(s.iloc[-1])


def _bucket(decay_rate):
    if decay_rate is None or (isinstance(decay_rate, float) and np.isnan(decay_rate)):
        return "unknown"
    return "strengthening" if decay_rate > 0 else "weakening"


def run(trades_path: str):
    """Returns (bucket_summary_df, correlation_df, trades_with_decay_rate_df)."""
    trades = pd.read_parquet(trades_path)
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])

    combo_cols = []
    series_cache = {}
    for signal in SIGNAL_NAMES:
        direction = decay_rate_direction(signal)
        for smoothing in SMOOTHING_NAMES:
            col = f"decay_rate_{signal}_{smoothing}"
            combo_cols.append((col, signal, smoothing, direction))

    values_by_col = {col: [] for col, *_ in combo_cols}

    pair_signal_cache = {}
    for _, row in trades.iterrows():
        sym_a, sym_b, tf = row["symbol_a"], row["symbol_b"], row["tf"]
        for col, signal, smoothing, direction in combo_cols:
            cache_key = (sym_a, sym_b, tf, signal, smoothing)
            if cache_key not in pair_signal_cache:
                raw_key = (sym_a, sym_b, tf, signal)
                if raw_key not in series_cache:
                    series_cache[raw_key] = _raw_level_series(sym_a, sym_b, tf, signal)
                raw_vals, raw_idx = series_cache[raw_key]
                if raw_vals is None:
                    pair_signal_cache[cache_key] = (None, None)
                else:
                    dr = decay_rate_series(raw_vals, smoothing) * direction
                    pair_signal_cache[cache_key] = (dr, raw_idx)
            dr_vals, dr_idx = pair_signal_cache[cache_key]
            if dr_vals is None:
                values_by_col[col].append(np.nan)
            else:
                values_by_col[col].append(_asof_lookup(dr_vals, dr_idx, row["entry_time"]))

    for col, vals in values_by_col.items():
        trades[col] = vals

    bucket_rows = []
    corr_rows = []
    for col, signal, smoothing, _direction in combo_cols:
        trades[f"{col}_bucket"] = trades[col].apply(_bucket)
        for bucket, grp in trades.groupby(f"{col}_bucket"):
            n = len(grp)
            pnl = grp["pnl_net"].dropna()
            win_rate = float((pnl > 0).mean()) if len(pnl) else np.nan
            mean_pnl = float(pnl.mean()) if len(pnl) else np.nan
            sharpe_proxy = float(pnl.mean() / pnl.std()) if len(pnl) > 1 and pnl.std() > 0 else np.nan
            bucket_rows.append({
                "signal": signal, "smoothing": smoothing, "bucket": bucket,
                "n_trades": n, "win_rate": win_rate, "mean_pnl_net": mean_pnl,
                "sharpe_proxy_unannualized": sharpe_proxy,
                "low_confidence": n < _MIN_CONFIDENT_N,
            })

        valid = trades[[col, "pnl_net"]].dropna()
        if len(valid) >= _MIN_CONFIDENT_N:
            rho, pval = spearmanr(valid[col], valid["pnl_net"])
        else:
            rho, pval = np.nan, np.nan
        corr_rows.append({
            "signal": signal, "smoothing": smoothing, "n": len(valid),
            "spearman_rho": float(rho) if np.isfinite(rho) else np.nan,
            "spearman_pvalue": float(pval) if np.isfinite(pval) else np.nan,
            "low_confidence": len(valid) < _MIN_CONFIDENT_N,
        })

    bucket_df = pd.DataFrame(bucket_rows).sort_values(["signal", "smoothing", "n_trades"], ascending=[True, True, False])
    corr_df = pd.DataFrame(corr_rows).sort_values("n", ascending=False)
    return bucket_df, corr_df, trades


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Thread Q decay-rate path: decay-rate-at-entry diagnostic")
    p.add_argument("--trades", default="output/backtest/baseline_trades_layer1.parquet")
    args = p.parse_args()

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    trades_path = args.trades if os.path.isabs(args.trades) else os.path.join(_root, args.trades)
    if not os.path.exists(trades_path):
        print(f"Trades file not found: {trades_path}")
        sys.exit(1)

    bucket_df, corr_df, trades_detail = run(trades_path)
    out_dir = os.path.join(_root, "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    bucket_path = os.path.join(out_dir, "decay_rate_at_entry_diagnostic_buckets.parquet")
    corr_path = os.path.join(out_dir, "decay_rate_at_entry_diagnostic_correlation.parquet")
    detail_path = os.path.join(out_dir, "decay_rate_at_entry_detail.parquet")
    bucket_df.to_parquet(bucket_path)
    corr_df.to_parquet(corr_path)
    trades_detail.to_parquet(detail_path)

    print(f"Trades source: {trades_path}")
    print("\n=== Bucket summary (win rate / pnl by strengthening vs weakening) ===")
    print(bucket_df.to_string(index=False))
    print("\n=== Spearman correlation (decay_rate vs pnl_net, continuous) ===")
    print(corr_df.to_string(index=False))
    print(f"\nSaved: {bucket_path}\nSaved: {corr_path}")
    print(f"Saved (per-trade detail, for compute_decay_rate_weights): {detail_path}")
