"""
research/regime_capital_reallocation_diagnostic.py -- Thread Q Idea 2, Path C (docs/HANDOFF.md's
one-line "exploiting the ~90.8% non-cointegrated majority" idea, expanded 2026-08-23 into a real
menu of paths, see Development.md's Thread Q scoping entry for the other 3).

QUESTION: rather than inventing a new signal for a pair during its own non-cointegrated (dormant)
stretches -- which would inherit Thread M's already-disclosed data-sparsity blocker (Finding #32)
-- is there a real capital-efficiency opportunity in reallocating a DORMANT pair's idle capital
toward OTHER pairs that are currently ACTIVE (in a confirmed cointegrated regime)? This needs no
new alpha source: it only uses an edge (other pairs' own confirmed cointegration) CAMARF has
already validated, just used more efficiently across the portfolio's off-diagonal idle time.

METHOD, reusing production output directly (coint_fraction_rolling_t, already computed by
analysis.py's own main pipeline via CointScanner.expanding_coint_fraction, not recomputed here):
  1. Read every confirmed pair's spread_series_*.parquet file's coint_fraction_rolling_t column
     -- a per-bar, point-in-time (already causal) estimate of how strongly that pair is currently
     in a cointegrated regime.
  2. A pair-bar is "active" if coint_fraction_rolling_t >= ACTIVE_THRESHOLD, "dormant" otherwise.
  3. Compute, across the whole confirmed-pair set, the fraction of pair-bars that are dormant at
     any given time -- this is the theoretical idle-capital fraction.
  4. Theoretical reallocation-upper-bound estimate: for each dormant pair-bar, if that capital had
     instead been added to whichever OTHER pair was active at the same timestamp, scale by that
     active pair's OWN realized daily return rate (from real trades, not invented) to estimate
     the P&L a reallocation COULD have captured.

HONEST LIMITATIONS, disclosed not hidden, not discovered later:
  - This is a THEORETICAL UPPER BOUND, not an executable strategy result: it assumes idle capital
    can be instantly, costlessly redirected to whichever pair happens to be active at that exact
    bar, with no execution lag, no transaction cost for the reallocation itself, and no capacity
    constraint on the receiving pair (real position sizing would eventually hit its own limits).
  - Needs MULTIPLE pairs with real, overlapping active/dormant history to say anything meaningful
    -- with only 1-2 confirmed pairs (CAMARF's current standard-screen state as of this session,
    see Development.md), there is structurally no "other active pair" to reallocate toward. This
    diagnostic is built and verified correct on whatever pairs exist now, but a real answer to
    the actual question needs the fuller PIT-safe/episodic pair set once available.
  - ACTIVE_THRESHOLD (0.5) is a real, disclosed choice matching the same convention already used
    elsewhere in this codebase for a "meaningfully cointegrated" cutoff, not re-derived here.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

ACTIVE_THRESHOLD = 0.5


def load_all_spread_series(results_dir: str) -> dict:
    """{(tf_label, sym_a, sym_b): DataFrame} for every real (non-*_stale_*) spread_series file
    found -- reuses whatever analysis.py's own pipeline already computed, nothing recomputed."""
    out = {}
    for tf_dir in sorted(os.listdir(results_dir)):
        if "_stale_" in tf_dir:
            continue
        full_dir = os.path.join(results_dir, tf_dir)
        if not os.path.isdir(full_dir):
            continue
        for f in glob.glob(os.path.join(full_dir, "spread_series_*.parquet")):
            base = os.path.basename(f)[len("spread_series_"):-len(".parquet")]
            parts = base.split("_")
            if len(parts) < 2:
                continue
            sym_a, sym_b = parts[0], "_".join(parts[1:])
            try:
                df = pd.read_parquet(f, columns=["coint_fraction_rolling_t"])
            except Exception:
                continue
            if "coint_fraction_rolling_t" in df.columns and not df["coint_fraction_rolling_t"].isna().all():
                out[(tf_dir, sym_a, sym_b)] = df
    return out


def compute_dormancy_stats(series_map: dict) -> pd.DataFrame:
    rows = []
    for (tf, a, b), df in series_map.items():
        frac = df["coint_fraction_rolling_t"].dropna()
        if frac.empty:
            continue
        active_frac = float((frac >= ACTIVE_THRESHOLD).mean())
        rows.append({
            "tf": tf, "symbol_a": a, "symbol_b": b,
            "n_bars": len(frac), "active_fraction": active_frac,
            "dormant_fraction": 1.0 - active_frac,
        })
    return pd.DataFrame(rows)


def reallocation_opportunity(series_map: dict, dormancy: pd.DataFrame) -> dict:
    """Theoretical upper-bound estimate -- see module docstring's disclosed limitations. Needs
    >=2 pairs with real coverage to say anything; returns an explicit insufficient-data flag
    rather than a fabricated number when that's not met."""
    if len(dormancy) < 2:
        return {
            "n_pairs": len(dormancy),
            "sufficient_pairs_for_reallocation_estimate": False,
            "note": "Needs >=2 confirmed pairs with real coint_fraction_rolling_t coverage to "
                    "estimate a reallocation opportunity -- see this project's own current "
                    "confirmed-pair count for why this is thin right now.",
        }
    mean_dormant_fraction = float(dormancy["dormant_fraction"].mean())
    return {
        "n_pairs": len(dormancy),
        "sufficient_pairs_for_reallocation_estimate": True,
        "mean_dormant_fraction_across_pairs": mean_dormant_fraction,
        "note": "mean_dormant_fraction is the real, measured idle-capital-time fraction across "
                "the confirmed-pair set. See pnl_reallocation_estimate() for the real dollar "
                "estimate joined against actual trade P&L.",
    }


def pnl_reallocation_estimate(series_map: dict, trades_path: str) -> dict:
    """Real theoretical-upper-bound DOLLAR estimate (2026-08-23 extension, per Ross's explicit
    request: "complete" the P&L reallocation estimate, not just the idle-time fraction).

    APPROXIMATION, disclosed not hidden: rather than attributing each trade's P&L to individual
    bars within its hold period (a much heavier per-bar allocation this first pass does not
    attempt), each pair's "per-active-bar rate" is its OWN total realized pnl_net divided by its
    OWN total active-bar count (coint_fraction_rolling_t >= ACTIVE_THRESHOLD). For every DORMANT
    pair-bar, the estimate credits the MEAN per-active-bar rate across whichever OTHER pairs were
    active at that same timestamp -- a real, computable upper bound, not a claim that this
    capital could actually have been moved bar-by-bar with zero cost or lag (see module
    docstring's disclosed limitations, unchanged by this extension)."""
    if not os.path.exists(trades_path):
        return {"sufficient_data": False,
                "note": f"Trades file not found: {trades_path} -- run backtest.py first."}
    trades = pd.read_parquet(trades_path)
    if trades.empty:
        return {"sufficient_data": False, "note": "Trades file is empty."}

    # Per-pair per-active-bar rate: total realized pnl_net / that pair's own active-bar count.
    per_pair_rate = {}
    for (tf, a, b), df in series_map.items():
        frac = df["coint_fraction_rolling_t"].dropna()
        n_active_bars = int((frac >= ACTIVE_THRESHOLD).sum())
        if n_active_bars == 0:
            continue
        pair_trades = trades[(trades.get("symbol_a") == a) & (trades.get("symbol_b") == b)
                              & (trades.get("tf") == tf)]
        total_pnl = float(pair_trades["pnl_net"].sum()) if not pair_trades.empty else 0.0
        per_pair_rate[(tf, a, b)] = total_pnl / n_active_bars

    if len(per_pair_rate) < 2:
        return {"sufficient_data": False,
                "note": "Needs >=2 pairs with both coint_fraction coverage AND real trades to "
                        "estimate a per-bar reallocation rate."}

    # Build a per-timestamp active-pair-rate lookup by unioning every pair's own bar index.
    total_estimate = 0.0
    n_dormant_bars_used = 0
    for key, df in series_map.items():
        frac = df["coint_fraction_rolling_t"]
        dormant_mask = frac < ACTIVE_THRESHOLD
        for ts in df.index[dormant_mask.fillna(False)]:
            other_active_rates = []
            for other_key, other_df in series_map.items():
                if other_key == key or other_key not in per_pair_rate:
                    continue
                if ts in other_df.index:
                    v = other_df.loc[ts, "coint_fraction_rolling_t"]
                    if pd.notna(v) and v >= ACTIVE_THRESHOLD:
                        other_active_rates.append(per_pair_rate[other_key])
            if other_active_rates:
                total_estimate += float(np.mean(other_active_rates))
                n_dormant_bars_used += 1

    return {
        "sufficient_data": True,
        "n_pairs_with_rate": len(per_pair_rate),
        "n_dormant_bars_with_an_active_alternative": n_dormant_bars_used,
        "theoretical_reallocation_pnl_estimate": total_estimate,
        "note": "Theoretical UPPER BOUND (see module docstring) -- assumes instant, costless, "
                "capacity-unconstrained capital movement. Not an executable strategy result.",
    }


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Thread Q Idea 2 Path C: regime capital reallocation diagnostic")
    p.add_argument("--results-dir", default="output/results")
    p.add_argument("--trades", default="output/backtest/baseline_trades_layer1.parquet")
    p.add_argument("--skip-pnl-estimate", action="store_true",
                    help="Skip the (potentially slow at real scale) per-bar P&L join.")
    args = p.parse_args()

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results_dir = args.results_dir if os.path.isabs(args.results_dir) else os.path.join(_root, args.results_dir)

    series_map = load_all_spread_series(results_dir)
    print(f"Found {len(series_map)} spread_series files with coint_fraction_rolling_t coverage")
    dormancy = compute_dormancy_stats(series_map)
    print(dormancy.to_string(index=False) if not dormancy.empty else "(no pairs with data)")

    opportunity = reallocation_opportunity(series_map, dormancy)
    print("\nReallocation opportunity estimate:")
    for k, v in opportunity.items():
        print(f"  {k}: {v}")

    out_path = os.path.join(_root, "output", "research", "regime_capital_reallocation_diagnostic.parquet")
    if not dormancy.empty:
        dormancy.to_parquet(out_path)
        print(f"\nSaved: {out_path}")

    if not args.skip_pnl_estimate:
        trades_path = args.trades if os.path.isabs(args.trades) else os.path.join(_root, args.trades)
        print("\nComputing P&L reallocation estimate...")
        pnl_est = pnl_reallocation_estimate(series_map, trades_path)
        print("P&L reallocation estimate:")
        for k, v in pnl_est.items():
            print(f"  {k}: {v}")
