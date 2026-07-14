"""
CAMARF cross_session_leadlag.py — exploratory diagnostic, NOT part of the
production pipeline.

Distinct from lead_lag_scan.py / near_miss_lag_scan.py, which test only the
SAME-SESSION, bar-to-bar lead-lag relationship (found null: lag-0 dominant
for all confirmed pairs, see Development.md Session 16 and this file's own
docstrings). This module tests two mechanisms those scripts cannot see at
all, because both operate entirely within a single session's intraday bars:

  (a) Overnight-gap lead-lag: does leg A's overnight gap (prior session's
      close to today's open) predict leg B's SAME-DAY overnight gap, at a
      lag measured in trading DAYS (not bars)? This is a genuinely different
      question from "does A's 10am move predict B's 11am move" — it asks
      whether information priced into A overnight (after-hours news, index
      rebalancing, macro releases) propagates into B's own overnight gap on
      a lag, rather than being contemporaneously absorbed.

  (b) Cross-timezone lead-lag: does an earlier-closing session's return
      predict a later-opening/closing session's return for economically
      linked instruments? Tested here on REAL cross-listing pairs (same
      underlying company, two exchanges, two timezones) rather than
      confirmed cointegrated pairs, because no confirmed pair in this
      project's manifest currently spans two timezones — the existing
      international confirmed pair (7267.T/8058.T) is two Tokyo-listed
      names, both on the same exchange clock, and is 1M-only (see
      Development.md, BUG-D57 production exercise, 2026-07-12). VOD (Nasdaq
      ADR) / VOD.L (LSE ordinary) and HMC (NYSE ADR) / 7267.T (Tokyo
      ordinary) are the SAME company on two exchanges — a real, strong
      economic link, not a "plausible" proxy — and both have real cached
      1h data from this session's BUG-D57 production exercise. This is
      explicitly flagged as illustrative/diagnostic, not a confirmed-pair
      finding: passing this test would motivate confirming a real
      international pair eventually, not itself constitute one.

Timestamp convention (verified directly, not assumed): all cached 1h data
is already snapped onto a single reference clock by data.py's exchange-aware
`snap_timestamps()` (BUG-D57) — VOD.L bars start at 03:00 (matching London's
08:00 local open), 7267.T bars start at 20:00 the prior US calendar date
(matching Tokyo's ~09:00 JST open). No further timezone conversion is
needed; grouping by calendar date on the existing index is correct.

Read-only. Loads cached price data via aligned_pair_loader.load_aligned_pair
or data.DataStore.load directly — never fetches.

Usage:
    python research/cross_session_leadlag.py --hypothesis overnight
    python research/cross_session_leadlag.py --hypothesis crosstz
    python research/cross_session_leadlag.py --hypothesis both
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aligned_pair_loader import load_aligned_pair
from data import DataStore

_MIN_DAYS = 60
_MAX_DAY_LAG = 5
_N_PERM = 500
_SEED = 42

# Same-company cross-listing pairs — genuine economic link, real cached 1h
# data from this session's BUG-D57 production exercise. NOT confirmed pairs.
_CROSS_TZ_PAIRS = [
    ("VOD", "VOD.L", "Vodafone: Nasdaq ADR vs. LSE ordinary"),
    ("HMC", "7267.T", "Honda: NYSE ADR vs. Tokyo ordinary"),
]


def _daily_sessions(df):
    """Group 1h bars by calendar date. Returns a DataFrame indexed by date
    with columns open (first bar's open), close (last bar's close)."""
    d = df.copy()
    d["date"] = pd.to_datetime(d.index).date
    g = d.groupby("date")
    return pd.DataFrame({
        "open": g["open"].first(),
        "close": g["close"].last(),
    })


def overnight_gap_series(df):
    """log(today's open) - log(yesterday's close), indexed by date."""
    sess = _daily_sessions(df)
    prev_close = sess["close"].shift(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = np.log(sess["open"]) - np.log(prev_close)
    return gap.replace([np.inf, -np.inf], np.nan)


def close_to_close_series(df):
    """log(today's close) - log(yesterday's close), indexed by date."""
    sess = _daily_sessions(df)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.log(sess["close"]).diff()
    return ret.replace([np.inf, -np.inf], np.nan)


def daily_lagged_corr_scan(series_a, series_b, max_lag):
    """Like lead_lag_scan.lagged_corr_scan but for day-indexed (not
    bar-indexed) series with an explicit integer trading-day lag, aligned by
    position after a date-index join (irregular calendars — holidays differ
    across exchanges — so position-based shift after alignment, not a
    fixed-frequency shift, is deliberate)."""
    joined = pd.concat([series_a, series_b], axis=1, join="inner").dropna()
    joined.columns = ["a", "b"]
    n = len(joined)
    out = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a_ = joined["a"].values[: n - lag] if lag > 0 else joined["a"].values
            b_ = joined["b"].values[lag:]
        else:
            a_ = joined["a"].values[-lag:]
            b_ = joined["b"].values[: n + lag]
        m = min(len(a_), len(b_))
        if m < _MIN_DAYS:
            out[lag] = (None, m)
            continue
        c = float(np.corrcoef(a_[:m], b_[:m])[0, 1])
        out[lag] = (c if np.isfinite(c) else None, m)
    return out, n


def best_lag(scan):
    valid = {k: v for k, v in scan.items() if v[0] is not None}
    if not valid:
        return None, None, None
    k_star = max(valid, key=lambda k: abs(valid[k][0]))
    c_star, n_star = valid[k_star]
    return k_star, c_star, n_star


def permutation_pvalue(series_a, series_b, max_lag, real_abs_corr, n_perm=_N_PERM, seed=_SEED):
    """Circular-shift null on series_b (day-indexed), same discipline as
    lead_lag_permutation_check.py's bar-indexed version: preserves series_b's
    own autocorrelation, breaks only true cross-alignment with series_a."""
    rng = np.random.default_rng(seed)
    joined = pd.concat([series_a, series_b], axis=1, join="inner").dropna()
    joined.columns = ["a", "b"]
    n = len(joined)
    if n < _MIN_DAYS:
        return None, 0
    a_vals = joined["a"].values
    b_vals = joined["b"].values
    null_abs_corrs = []
    for _ in range(n_perm):
        shift = int(rng.integers(1, n))
        b_shifted = np.roll(b_vals, shift)
        scan = {}
        for lag in range(-max_lag, max_lag + 1):
            if lag >= 0:
                a_ = a_vals[: n - lag] if lag > 0 else a_vals
                b_ = b_shifted[lag:]
            else:
                a_ = a_vals[-lag:]
                b_ = b_shifted[: n + lag]
            m = min(len(a_), len(b_))
            if m < _MIN_DAYS:
                continue
            c = np.corrcoef(a_[:m], b_[:m])[0, 1]
            if np.isfinite(c):
                scan[lag] = abs(c)
        if scan:
            null_abs_corrs.append(max(scan.values()))
    null_abs_corrs = np.array(null_abs_corrs)
    if len(null_abs_corrs) == 0:
        return None, 0
    pval = (1 + np.sum(null_abs_corrs >= real_abs_corr)) / (len(null_abs_corrs) + 1)
    return float(pval), len(null_abs_corrs)


def run_overnight_hypothesis(max_lag=_MAX_DAY_LAG, n_perm=_N_PERM):
    rows = []
    for tf_dir, tf_label in [("1hr", "1h")]:
        path = f"output/results/{tf_dir}/pairs.parquet"
        if not os.path.exists(path):
            print(f"No pairs file at {path}, skipping.")
            continue
        df = pd.read_parquet(path)
        for _, row in df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None:
                print(f"SKIP {sym_a}/{sym_b}: cache missing for one leg")
                continue
            gap_a = overnight_gap_series(df_a)
            gap_b = overnight_gap_series(df_b)
            scan, n = daily_lagged_corr_scan(gap_a, gap_b, max_lag)
            k_star, c_star, n_star = best_lag(scan)
            c0, n0 = scan.get(0, (None, 0))
            if k_star is None or c0 is None:
                print(f"SKIP {sym_a}/{sym_b}: insufficient overlapping overnight-gap "
                      f"days (need >={_MIN_DAYS})")
                continue
            lift = abs(c_star) - abs(c0)
            perm_p, n_perm_eff = permutation_pvalue(gap_a, gap_b, max_lag, abs(c_star), n_perm=n_perm)
            flagged = (k_star != 0) and (perm_p is not None) and (perm_p < 0.05)
            rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b, "n_days": n,
                "best_lag_days": k_star, "corr_at_best_lag": c_star,
                "corr_at_lag0": c0, "lift": lift,
                "perm_pvalue": perm_p, "n_perm": n_perm_eff,
                "flagged_significant_nonzero_lag": flagged,
            })
            sig = "SIG" if flagged else "ns "
            print(f"{sig} {sym_a}/{sym_b}: best_lag={k_star}d corr*={c_star:.3f} "
                  f"corr0={c0:.3f} lift={lift:.3f} perm_p={perm_p}")
    result_df = pd.DataFrame(rows)
    n_sig = int(result_df["flagged_significant_nonzero_lag"].sum()) if len(result_df) else 0
    print(f"\nOVERNIGHT-GAP HYPOTHESIS: {n_sig}/{len(result_df)} confirmed 1h pairs show a "
          f"permutation-significant (p<0.05) non-zero-day-lag overnight-gap relationship.")
    if n_sig == 0:
        print("GATE RESULT: null. Overnight-gap-to-overnight-gap lead-lag across trading days "
              "shows no significant structure among the confirmed pair set, mirroring the "
              "same-session null result (lead_lag_scan.py) — the contemporaneous assumption "
              "extends to this different mechanism as well for THIS pair set. Does not rule out "
              "the effect existing among pairs that never reach the confirmed list.")
    else:
        print("GATE RESULT: at least one confirmed pair shows a permutation-significant "
              "overnight-gap lead-lag. NOT a promotion — per this project's findings-promotion "
              "discipline, this needs independent scrutiny (out-of-sample check, economic "
              "rationale) before being cited as a finding, let alone wired into production.")
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "cross_session_leadlag_overnight.parquet")
    result_df.to_parquet(out_path)
    print(f"Full results written to {out_path}")
    return result_df


def run_crosstz_hypothesis(max_lag=2, n_perm=_N_PERM):
    print("\nCROSS-TIMEZONE HYPOTHESIS — illustrative only: real same-company cross-listing "
          "pairs, NOT confirmed cointegrated pairs (no confirmed pair currently spans two "
          "timezones). Chosen for a genuine economic link, not as a proxy stand-in.")
    rows = []
    for sym_a, sym_b, desc in _CROSS_TZ_PAIRS:
        df_a = DataStore.load(sym_a, "1h")
        df_b = DataStore.load(sym_b, "1h")
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            print(f"SKIP {sym_a}/{sym_b} ({desc}): cache missing")
            continue
        ret_a = close_to_close_series(df_a)
        ret_b = close_to_close_series(df_b)
        scan, n = daily_lagged_corr_scan(ret_a, ret_b, max_lag)
        k_star, c_star, n_star = best_lag(scan)
        c0, n0 = scan.get(0, (None, 0))
        if k_star is None or c0 is None:
            print(f"SKIP {sym_a}/{sym_b}: insufficient overlapping days")
            continue
        perm_p, n_perm_eff = permutation_pvalue(ret_a, ret_b, max_lag, abs(c_star), n_perm=n_perm)
        c1, n1 = scan.get(1, (None, 0))
        flagged = (perm_p is not None) and (perm_p < 0.05)
        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "description": desc, "n_days": n,
            "corr_lag0": c0, "corr_lag_plus1": c1, "best_lag_days": k_star,
            "corr_at_best_lag": c_star, "perm_pvalue": perm_p, "n_perm": n_perm_eff,
            "flagged_significant": flagged,
        })
        sig = "SIG" if flagged else "ns "
        print(f"{sig} {sym_a}/{sym_b} ({desc}): n={n} corr_lag0={c0:.3f} "
              f"corr_lag+1={c1 if c1 is not None else float('nan'):.3f} "
              f"best_lag={k_star}d corr*={c_star:.3f} perm_p={perm_p}")
    result_df = pd.DataFrame(rows)
    n_sig = int(result_df["flagged_significant"].sum()) if len(result_df) else 0
    print(f"\nCROSS-TIMEZONE HYPOTHESIS: {n_sig}/{len(result_df)} cross-listing pairs show a "
          f"permutation-significant cross-timezone lead-lag relationship.")
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "cross_session_leadlag_crosstz.parquet")
    result_df.to_parquet(out_path)
    print(f"Full results written to {out_path}")
    return result_df


def main():
    p = argparse.ArgumentParser(description="Cross-session lead-lag: overnight-gap and cross-timezone hypotheses (2026-07-13)")
    p.add_argument("--hypothesis", choices=["overnight", "crosstz", "both"], default="both")
    p.add_argument("--max-lag-days", type=int, default=_MAX_DAY_LAG)
    p.add_argument("--n-perm", type=int, default=_N_PERM)
    args = p.parse_args()

    if args.hypothesis in ("overnight", "both"):
        run_overnight_hypothesis(max_lag=args.max_lag_days, n_perm=args.n_perm)
    if args.hypothesis in ("crosstz", "both"):
        run_crosstz_hypothesis(n_perm=args.n_perm)


if __name__ == "__main__":
    main()
