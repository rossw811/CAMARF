"""
CAMARF research/hub_leg_stop_conditioning.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #62).

Scoped with Ross 2026-07-13 as idea (4) of the relational-adaptation
program — explicitly flagged as the most speculative of the four and
scoped last. A dynamic extension of the STATIC correlation-cluster
exposure caps already built (task #20,
research/stop_loss_correlation_caps.py): instead of a fixed, always-on
cap based on cluster membership, condition the STOP-LOSS threshold for
pairs sharing a "hub" leg (a symbol appearing in multiple pairs) on that
hub leg's OWN current realized volatility — tighter stop when the hub is
unusually volatile right now, normal stop otherwise.

Honest scope note, stated up front: this session's 9-pair stable set has
only ONE real hub — LNT, appearing in both LNT/VTR and LNT/WELL. This is
a genuinely thin test (2 pairs, not the richer multi-pair hub structure
DD had historically per this project's DD-hub effective-bets work before
BUG-D65's contamination was found) — reported as exactly that thin, not
inflated into a broader claim than 2 pairs supports.

Rule: baseline uses production's fixed STOP_ZSCORE (config.py, 3.5,
matching config.BACKTEST.STOP_ZSCORE default). The hub-conditioned
variant computes the hub leg's own trailing 20-bar realized volatility
percentile (vs. its own trailing 252-bar history) at each entry; if
above the 80th percentile (hub currently unusually volatile), tightens
the stop to 2.5; otherwise uses the same 3.5 baseline.

Usage:
    python research/hub_leg_stop_conditioning.py --tf 1hr
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
from lead_lag_scan import _gap_masked_log_price

_DEFAULT_PAIRS = [
    ("LNT", "VTR"), ("LNT", "WELL"), ("AME", "MAR"), ("CMS", "DUK"),
    ("EG", "WRB"), ("HAL", "NOV"), ("MET", "TMHC"), ("PFG", "STLD"),
    ("UMBF", "FHB"),
]

ENTRY_Z = 2.0
EXIT_Z = 0.0
BASELINE_STOP_Z = 3.5   # matches config.py's Config.BACKTEST.STOP_ZSCORE default
TIGHT_STOP_Z = 2.5
MAX_HOLD_BARS = 100
HUB_VOL_PERCENTILE_THRESHOLD = 0.80


def _find_hubs(pairs):
    counts = {}
    for a, b in pairs:
        counts[a] = counts.get(a, 0) + 1
        counts[b] = counts.get(b, 0) + 1
    return {sym: n for sym, n in counts.items() if n > 1}


def build_spread_z(symbol_a, symbol_b, tf_label, z_window=60):
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    log_a, log_b = log_a.reindex(common_idx), log_b.reindex(common_idx)
    mask = log_a.notna() & log_b.notna()
    la, lb = log_a[mask], log_b[mask]
    if len(la) < 100:
        return None
    beta = np.dot(lb - lb.mean(), la - la.mean()) / np.dot(lb - lb.mean(), lb - lb.mean())
    alpha = la.mean() - beta * lb.mean()
    spread = la - (alpha + beta * lb)
    z = (spread - spread.rolling(z_window).mean()) / spread.rolling(z_window).std()
    return z.dropna()


def hub_vol_percentile_series(hub_symbol, tf_label, index, vol_window=20, hist_window=252):
    """Same bug class caught and fixed in big_move_lead_lag.py this
    session: _gap_aware_returns masks roughly 1-in-6 bars to NaN
    (DATA_GAP/gap-flag masking), so a naive .rolling(vol_window).std()
    on the raw gap-aware series essentially NEVER sees a NaN-free window
    (pandas rolling defaults to min_periods=window, so ANY NaN inside a
    20-bar window kills that window's result) — first version of this
    function returned an all-NaN percentile series (0/4452 valid, caught
    directly, not assumed correct), which silently made the hub-
    conditioning comparison a no-op (identical results to baseline).
    Fixed the same way: compute rolling stats on the COMPACTED
    (dropna()'d) series, then reindex back onto the target index."""
    df = DataStore.load(hub_symbol, tf_label)
    if df is None or df.empty:
        return pd.Series(np.nan, index=index)
    ret = pd.Series(_gap_aware_returns(df), index=df.index).dropna()
    trailing_vol = ret.rolling(vol_window).std()
    pctile = trailing_vol.rolling(hist_window).apply(
        lambda w: (w[-1] > w[:-1]).mean() if len(w) > 1 else np.nan, raw=True
    )
    return pctile.reindex(index, method="ffill")


def simulate(z: pd.Series, stop_z_series):
    """stop_z_series: either a scalar (baseline) or a per-bar Series
    (hub-conditioned). Every entry exits via EXIT_Z, the stop, or
    MAX_HOLD_BARS/end-of-series — same completeness guarantee established
    in breakout_vs_reversion.py."""
    trades = []
    i, n, vals = 0, len(z), z.values
    stop_vals = stop_z_series.reindex(z.index).values if isinstance(stop_z_series, pd.Series) \
        else np.full(n, stop_z_series)
    while i < n:
        if abs(vals[i]) >= ENTRY_Z:
            direction = -1 if vals[i] > 0 else 1
            entry_val = vals[i]
            stop_thr = stop_vals[i] if not np.isnan(stop_vals[i]) else BASELINE_STOP_Z
            j = i + 1
            stopped_out = False
            while j < n and j - i < MAX_HOLD_BARS:
                if (direction == -1 and vals[j] <= EXIT_Z) or (direction == 1 and vals[j] >= -EXIT_Z):
                    break
                if abs(vals[j]) >= stop_thr:
                    stopped_out = True
                    break
                j += 1
            exit_val = vals[min(j, n - 1)]
            pnl = direction * (exit_val - entry_val)
            trades.append({"entry_idx": i, "exit_idx": min(j, n - 1), "hold": j - i,
                            "pnl_z": pnl, "stopped_out": stopped_out})
            i = j + 1
        else:
            i += 1
    return trades


def _summarize(trades, label):
    if not trades:
        return {"strategy": label, "n_trades": 0}
    pnls = np.array([t["pnl_z"] for t in trades])
    n_stopped = sum(1 for t in trades if t["stopped_out"])
    std_pnl = pnls.std()
    return {
        "strategy": label, "n_trades": len(trades), "win_rate": float((pnls > 0).mean()),
        "total_pnl_z": float(pnls.sum()),
        "sharpe_like": float(pnls.mean() / std_pnl) if std_pnl > 1e-9 else np.nan,
        "n_stopped_out": n_stopped,
    }


def main():
    p = argparse.ArgumentParser(description="Hub-leg dynamic stop-loss conditioning (2026-07-14)")
    p.add_argument("--tf", default="1hr")
    args = p.parse_args()

    hubs = _find_hubs(_DEFAULT_PAIRS)
    print(f"Hub legs in this 9-pair set (appearing in >1 pair): {hubs}")
    if not hubs:
        print("No hub legs found — nothing to test.")
        return
    hub_pairs = [(a, b) for a, b in _DEFAULT_PAIRS if a in hubs or b in hubs]
    print(f"Hub-involving pairs tested: {hub_pairs}\n")

    rows = []
    for sym_a, sym_b in hub_pairs:
        z = build_spread_z(sym_a, sym_b, args.tf)
        if z is None:
            print(f"{sym_a}/{sym_b}: insufficient data")
            continue
        hub_symbol = sym_a if sym_a in hubs else sym_b
        vol_pctile = hub_vol_percentile_series(hub_symbol, args.tf, z.index)
        conditioned_stop = pd.Series(
            np.where(vol_pctile >= HUB_VOL_PERCENTILE_THRESHOLD, TIGHT_STOP_Z, BASELINE_STOP_Z),
            index=z.index,
        )

        base_trades = simulate(z, BASELINE_STOP_Z)
        cond_trades = simulate(z, conditioned_stop)
        base_sum = _summarize(base_trades, "baseline_fixed_stop")
        cond_sum = _summarize(cond_trades, "hub_conditioned_stop")
        base_sum.update({"symbol_a": sym_a, "symbol_b": sym_b, "hub": hub_symbol})
        cond_sum.update({"symbol_a": sym_a, "symbol_b": sym_b, "hub": hub_symbol})
        rows.append(base_sum)
        rows.append(cond_sum)
        print(f"{sym_a}/{sym_b}@{args.tf} (hub={hub_symbol}): "
              f"baseline total_pnl_z={base_sum.get('total_pnl_z',float('nan')):.2f} "
              f"stopped={base_sum.get('n_stopped_out',0)}/{base_sum.get('n_trades',0)} | "
              f"hub-conditioned total_pnl_z={cond_sum.get('total_pnl_z',float('nan')):.2f} "
              f"stopped={cond_sum.get('n_stopped_out',0)}/{cond_sum.get('n_trades',0)}")

    df = pd.DataFrame(rows)
    print(f"\nHonest scope note: {len(hub_pairs)} hub-involving pair(s) tested "
          f"({len(hubs)} hub symbol(s): {list(hubs.keys())}) — a thin sample, not a broad claim.")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"hub_leg_stop_conditioning_{args.tf}.parquet")
    df.to_parquet(out_path)
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
