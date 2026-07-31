"""
CAMARF research/earnings_structural_break_correlation.py — comparison/
diagnostic script, NOT part of the production pipeline (2026-07-14, task
#69 Piece A, built alongside Piece B per Ross's explicit request "let's
also do A for comparison").

Question: do detected structural breaks (Zivot-Andrews, CUSUM first
excursion — analysis.py's coint_frac secondary-evidence fields) land
disproportionately close to either pair leg's earnings announcements,
versus what would happen by chance given each symbol's own earnings
frequency and the pair's available date range?

This is a pure diagnostic cross-reference, not a new trading signal —
reuses earnings.py's EarningsCalendar (already built for
backtest.py --storm-earnings-blackout) and analysis.py's already-persisted
zivot_andrews_break / cusum_first_excursion date fields. No new fetching
of price data; earnings dates are fetched read-only via yfinance exactly
as earnings.py already does elsewhere.

Data source note: aggregates break-date fields from every
output/results/*/all_candidates.parquet found on disk, INCLUDING the
2026-07-14 stale (pre-BUG-D65-fix, contaminated-cache) 1hr archive — the
largest available sample (353 candidates, 144 ZA breaks, 276 CUSUM
excursions). This is explicitly a diagnostic use of the break-DATE
distribution, not a production claim resting on those candidates' pair
confirmations — flagged plainly in the output, not silently used as if
it were current/clean data.

Method: for each real break date, check whether it falls within a window
(3/5/10 days) of either leg's nearest earnings date. Compare the observed
rate against an empirical null built by resampling random dates from each
pair's own available range (same symbols, same earnings frequency, same
span) many times — controls for the base rate at which ANY random date
would land near an earnings announcement, rather than comparing against a
naive/uncontrolled assumption.

Usage:
    python research/earnings_structural_break_correlation.py
    python research/earnings_structural_break_correlation.py --windows 3 5 10 --n-null 2000
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from earnings import EarningsCalendar
from data import DataStore


def _load_all_candidates():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = glob.glob(os.path.join(root, "output", "results", "*", "all_candidates.parquet"))
    frames = []
    for f in files:
        try:
            df = pd.read_parquet(
                f, columns=["symbol_a", "symbol_b", "tf_label",
                            "zivot_andrews_break", "cusum_first_excursion"]
            )
        except Exception:
            continue
        df["_source_file"] = os.path.relpath(f, root)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _break_events(df):
    """One row per (symbol_a, symbol_b, break_date, break_type)."""
    events = []
    for _, r in df.iterrows():
        for col, kind in (("zivot_andrews_break", "zivot_andrews"),
                           ("cusum_first_excursion", "cusum")):
            d = r.get(col)
            if pd.isna(d):
                continue
            try:
                dt = pd.Timestamp(d)
            except Exception:
                continue
            events.append({
                "symbol_a": r["symbol_a"], "symbol_b": r["symbol_b"],
                "tf_label": r["tf_label"], "break_type": kind, "break_date": dt,
            })
    return pd.DataFrame(events)


def _pair_date_range(symbol_a, symbol_b):
    """Available daily-bar date range for a pair, used to sample the null."""
    ranges = []
    for sym in (symbol_a, symbol_b):
        df = DataStore.load(sym, "1D")
        if df is not None and not df.empty:
            ranges.append((df.index.min(), df.index.max()))
    if not ranges:
        return None, None
    start = max(r[0] for r in ranges)
    end = min(r[1] for r in ranges)
    if start >= end:
        return None, None
    return start, end


def _run_windows(events, pair_ranges, cal, windows, n_null, rng, label):
    """Core per-window permutation test, factored out (Tier 4.2 fix, Grand
    Sweep 2026-07-20) so it can be run twice: once on the full event set,
    once with the dominant hub symbol's pairs excluded (see run()'s
    docstring note on why)."""
    results = []
    for w in windows:
        n_near = 0
        n_valid = 0
        for _, ev in events.iterrows():
            key = (ev["symbol_a"], ev["symbol_b"])
            start, end = pair_ranges.get(key, (None, None))
            if start is None:
                continue
            n_valid += 1
            if cal.near_earnings(ev["symbol_a"], ev["break_date"], window_days=w) or \
               cal.near_earnings(ev["symbol_b"], ev["break_date"], window_days=w):
                n_near += 1

        if n_valid == 0:
            continue
        observed_rate = n_near / n_valid

        null_rates = []
        for _ in range(n_null):
            n_null_near = 0
            for _, ev in events.iterrows():
                key = (ev["symbol_a"], ev["symbol_b"])
                start, end = pair_ranges.get(key, (None, None))
                if start is None:
                    continue
                span_days = (end - start).days
                if span_days <= 0:
                    continue
                rand_offset = rng.integers(0, span_days + 1)
                rand_date = start + pd.Timedelta(days=int(rand_offset))
                if cal.near_earnings(ev["symbol_a"], rand_date, window_days=w) or \
                   cal.near_earnings(ev["symbol_b"], rand_date, window_days=w):
                    n_null_near += 1
            null_rates.append(n_null_near / n_valid)

        null_rates = np.array(null_rates)
        p_value = float(np.mean(null_rates >= observed_rate))
        results.append({
            "subset": label, "window_days": w, "n_events": n_valid, "n_near_earnings": n_near,
            "observed_rate": observed_rate, "null_mean_rate": float(null_rates.mean()),
            "null_p95_rate": float(np.percentile(null_rates, 95)),
            "empirical_p_value": p_value,
        })
        print(f"[{label}] window=±{w}d: observed={observed_rate:.3f} ({n_near}/{n_valid}) "
              f"vs null_mean={null_rates.mean():.3f} (p95={np.percentile(null_rates, 95):.3f}) "
              f"-> empirical p={p_value:.4f}")

    if results:
        res_df = pd.DataFrame(results)
        # Tier 4.2 fix (part 1): 3 window sizes were previously tested with
        # no multiple-comparisons correction across them.
        reject, p_adj, _, _ = multipletests(res_df["empirical_p_value"].values, method="fdr_bh")
        res_df["empirical_p_bh_adjusted"] = p_adj
        res_df["significant_bh"] = reject
        results = res_df.to_dict("records")
    return results


def run(windows, n_null, seed):
    """
    Tier 4.2 fix (Grand Sweep 2026-07-20): the original single-pass version
    pooled break events across pairs as if independent Bernoulli trials,
    but many pairs share a common leg (DD alone is 73.4% of the 1h
    candidate pool per trend_dominance_diagnostic.py) — a symbol-specific
    quirk in ONE hub leg's own earnings-timing behavior could masquerade
    as a broad, multi-symbol phenomenon. The permutation null already uses
    the SAME pair/event structure as the observed data (so the p-value
    comparison itself is not invalidated by hub concentration), but the
    finding's INTERPRETABILITY as "broad" evidence is. Fixed by running
    the identical analysis twice: once on the FULL event set (as before),
    once with every pair involving the single most common leg symbol
    excluded — if the finding survives hub exclusion, it is not just a
    DD-specific (or whichever symbol is dominant) artifact. Also applies
    BH-FDR correction across the (3, by default) window-size p-values,
    previously untested for multiple comparisons.
    """
    rng = np.random.default_rng(seed)

    raw = _load_all_candidates()
    if raw.empty:
        print("No all_candidates.parquet files found — nothing to analyze.")
        return
    events = _break_events(raw)
    if events.empty:
        print("No non-null break dates found in any all_candidates.parquet.")
        return
    print(f"Loaded {len(events)} break events from {raw['_source_file'].nunique()} "
          f"result files ({events['symbol_a'].nunique() + events['symbol_b'].nunique()} "
          f"distinct symbols involved).")

    all_symbols = sorted(set(events["symbol_a"]) | set(events["symbol_b"]))
    cal = EarningsCalendar.load_or_build(all_symbols)

    pair_ranges = {}
    for sym_a, sym_b in events[["symbol_a", "symbol_b"]].drop_duplicates().itertuples(index=False):
        pair_ranges[(sym_a, sym_b)] = _pair_date_range(sym_a, sym_b)

    leg_counts = pd.concat([events["symbol_a"], events["symbol_b"]]).value_counts()
    hub_symbol = leg_counts.index[0]
    hub_frac = leg_counts.iloc[0] / len(events)
    print(f"Dominant hub leg: {hub_symbol} appears in {leg_counts.iloc[0]}/{len(events)} "
          f"events ({hub_frac:.1%}).")

    all_results = _run_windows(events, pair_ranges, cal, windows, n_null, rng, "full_sample")

    non_hub_events = events[(events["symbol_a"] != hub_symbol) & (events["symbol_b"] != hub_symbol)]
    print(f"\n=== Hub-exclusion robustness check: excluding all {hub_symbol}-involving pairs "
          f"({len(events) - len(non_hub_events)}/{len(events)} events removed) ===")
    if non_hub_events.empty:
        print(f"No events remain after excluding {hub_symbol} — cannot run the exclusion check.")
    else:
        all_results += _run_windows(non_hub_events, pair_ranges, cal, windows, n_null, rng,
                                     f"excl_{hub_symbol}")

    out_df = pd.DataFrame(all_results)
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "earnings_structural_break_correlation.parquet")
    out_df.to_parquet(out_path)
    print(f"\nResults written to {out_path}")
    print("\nInterpretation: empirical_p_value is the fraction of null draws (random dates, "
          "same pairs/symbols/date ranges) whose near-earnings rate was AT LEAST as high as the "
          "real breaks' rate. A small p-value means structural breaks land near earnings more "
          "often than chance alone would produce for these symbols. empirical_p_bh_adjusted "
          "corrects for testing multiple window sizes. Compare the 'full_sample' subset against "
          f"'excl_{hub_symbol}' to check whether any significant finding survives removing the "
          "dominant hub leg, rather than being that one symbol's own idiosyncratic behavior.")


def main():
    p = argparse.ArgumentParser(description="Earnings-proximity correlation for structural breaks (2026-07-14)")
    p.add_argument("--windows", type=int, nargs="+", default=[3, 5, 10])
    p.add_argument("--n-null", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    run(args.windows, args.n_null, args.seed)


if __name__ == "__main__":
    main()
