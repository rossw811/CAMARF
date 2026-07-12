"""
distance.py — Gatev-style distance method baseline

Implements the Gatev, Goetzmann & Rouwenhorst (2006) pairs trading baseline:

  Formation period: normalize each price series to start at 1.0, then compute
  the sum of squared deviations (SSD) between each candidate pair.  Select the
  top-K pairs with lowest SSD (most co-moving prices).

  Trading period: generate entry/exit signals from the normalized spread
  (|spread| > 2σ of the formation period spread → entry; spread crosses 0 → exit).

Comparison: for each confirmed cointegration pair (from cointegration_tiers.parquet)
we check whether it was also selected by the distance method over the same
formation period.  We then run both sets of pairs through the same backtest
engine (no STORM flags, no ML gate) and compare OOS Sharpe side by side.

Output:
  output/stats/distance_baseline.parquet  — per-pair metrics from both methods
  output/stats/distance_summary.json      — aggregate comparison table
  latest_run_distance.log                 — run log
"""

import os
import sys
import json
import logging
import time
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest import BacktestEngine, RegimeConditioner, MLConditioner

_ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")
_OUT_DIR = _STATS_DIR

_TF_DIRS = [
    ("1hr", "1h"),
]

# Fraction of the price series used as "formation" vs "trading".
# BUG-D61 fix (2026-07-12): this was hardcoded to 0.5 (a 50/50 split), while the cointegration
# side of this same comparison (run_coint_pair_oos_trades, below) uses
# holdout_only=True -- backtest.py's own 80/20 IS/OOS split (Config.BACKTEST.HOLDOUT_PCT).
# The two sides of the comparison were therefore NEVER testing the same date window (confirmed
# directly: a 2026-07-12 run showed the distance side trading over 2025-01-15 to 2026-07-10 --
# ~18 months -- while the cointegration side's holdout is ~7 months, Dec 2025 to Jul 2026). This
# is very likely the primary driver of PAPER.md's old "-0.208 vs. ~11.7" GGR distance comparison
# looking implausible (Ross flagged this directly), independent of BUG-D59's separate
# aggregation fix. Aligned to the SAME convention so both sides genuinely trade the same window.
_FORMATION_FRAC = 1.0 - 0.20  # matches Config.BACKTEST.HOLDOUT_PCT (kept as a literal here,
                               # not imported, since distance.py doesn't otherwise depend on
                               # backtest.py's Config wiring -- see run_coint_pair_oos_trades'
                               # own __import__("config") pattern for the one place it does)
# Top-K pairs by SSD to select
_TOP_K = 20
# Entry z-score for distance strategy
_ENTRY_ZSCORE = 2.0

log = logging.getLogger("distance")


# =============================================================================
# UTILITIES
# =============================================================================


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(os.path.join(_ROOT, "latest_run_distance.log"), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _load_prices(symbol: str, tf_dir: str) -> Optional[pd.Series]:
    """Load adjusted close price from cache."""
    # Map tf_dir to cache suffix
    _SUFFIX_MAP = {
        "1min": "1min", "2min": "2min", "3min": "3min", "5min": "5min",
        "15min": "15min", "30min": "30min", "1hr": "1hr", "4hr": "4hr",
    }
    suffix = _SUFFIX_MAP.get(tf_dir, tf_dir)
    fpath = os.path.join(_CACHE_DIR, f"{symbol}_{suffix}.parquet")
    if not os.path.exists(fpath):
        return None
    df = pd.read_parquet(fpath)
    if "close" not in df.columns:
        return None
    s = df["close"].dropna()
    s.index = pd.to_datetime(s.index)
    return s


# =============================================================================
# FORMATION PERIOD: SSD RANKING
# =============================================================================


def compute_ssd_pairs(symbols: List[str], tf_dir: str, formation_end: pd.Timestamp) -> pd.DataFrame:
    """
    For each candidate pair, compute SSD of normalized prices over [start, formation_end].
    Returns a DataFrame with columns: symbol_a, symbol_b, ssd, n_overlap.
    """
    log.info("  Loading prices for %d symbols (formation <= %s)", len(symbols), formation_end.date())

    # Load and align all price series
    prices: Dict[str, pd.Series] = {}
    for sym in symbols:
        s = _load_prices(sym, tf_dir)
        if s is None:
            continue
        s = s[s.index <= formation_end]
        if len(s) < 50:
            continue
        prices[sym] = s

    syms = sorted(prices.keys())
    log.info("  %d symbols loaded with sufficient formation data", len(syms))

    rows = []
    for i, a in enumerate(syms):
        pa = prices[a]
        for b in syms[i + 1:]:
            pb = prices[b]
            # Align
            common_idx = pa.index.intersection(pb.index)
            if len(common_idx) < 30:
                continue
            pa_c = pa.loc[common_idx]
            pb_c = pb.loc[common_idx]
            # Normalize to start at 1.0
            pa_n = pa_c / pa_c.iloc[0]
            pb_n = pb_c / pb_c.iloc[0]
            # SSD
            ssd = float(((pa_n - pb_n) ** 2).sum())
            rows.append({
                "symbol_a": a, "symbol_b": b,
                "ssd": round(ssd, 6),
                "n_overlap": len(common_idx),
            })

    ssd_df = pd.DataFrame(rows).sort_values("ssd")
    return ssd_df


# =============================================================================
# TRADING PERIOD: DISTANCE SIGNAL BACKTEST
# =============================================================================


def run_distance_trades(
    symbol_a: str,
    symbol_b: str,
    tf_dir: str,
    formation_end: pd.Timestamp,
    entry_zscore: float = _ENTRY_ZSCORE,
) -> List[dict]:
    """
    Simple distance-method trading simulation over the OOS window (formation_end → end).
    Entry: |spread_z| > entry_zscore.  Exit: spread_z crosses 0.
    Returns list of trade dicts with pnl_pct, direction, entry_time, exit_time.
    """
    pa = _load_prices(symbol_a, tf_dir)
    pb = _load_prices(symbol_b, tf_dir)
    if pa is None or pb is None:
        return []

    # Formation window
    pa_form = pa[pa.index <= formation_end]
    pb_form = pb[pb.index <= formation_end]
    common_form = pa_form.index.intersection(pb_form.index)
    if len(common_form) < 30:
        return []

    pa_form_n = pa_form.loc[common_form] / pa_form.loc[common_form].iloc[0]
    pb_form_n = pb_form.loc[common_form] / pb_form.loc[common_form].iloc[0]
    spread_form = pa_form_n - pb_form_n
    spread_mean = float(spread_form.mean())
    spread_std = float(spread_form.std())
    if spread_std < 1e-8:
        return []

    # OOS window
    pa_oos = pa[pa.index > formation_end]
    pb_oos = pb[pb.index > formation_end]
    common_oos = pa_oos.index.intersection(pb_oos.index)
    if len(common_oos) < 10:
        return []

    pa_oos_n = pa_oos.loc[common_oos] / pa_oos.loc[common_oos].iloc[0]
    pb_oos_n = pb_oos.loc[common_oos] / pb_oos.loc[common_oos].iloc[0]
    spread_oos = pa_oos_n - pb_oos_n
    spread_z = (spread_oos - spread_mean) / spread_std

    # Simulate trades
    trades = []
    in_trade = False
    direction = 0  # +1: long A short B, -1: short A long B
    entry_z = 0.0
    entry_time = None
    entry_pa = 0.0
    entry_pb = 0.0

    pa_arr = pa_oos.loc[common_oos].values
    pb_arr = pb_oos.loc[common_oos].values
    times = common_oos

    for i, t in enumerate(times):
        z = float(spread_z.iloc[i])
        if not in_trade:
            if z > entry_zscore:
                # Spread too high: short A, long B (expect convergence)
                direction = -1
                in_trade = True
                entry_z = z
                entry_time = t
                entry_pa = pa_arr[i]
                entry_pb = pb_arr[i]
            elif z < -entry_zscore:
                # Spread too low: long A, short B
                direction = +1
                in_trade = True
                entry_z = z
                entry_time = t
                entry_pa = pa_arr[i]
                entry_pb = pb_arr[i]
        else:
            # Exit when spread crosses 0
            crossed = (direction == +1 and z >= 0) or (direction == -1 and z <= 0)
            if crossed or i == len(times) - 1:
                exit_pa = pa_arr[i]
                exit_pb = pb_arr[i]
                # P&L as % return on each leg
                ret_a = (exit_pa - entry_pa) / entry_pa if entry_pa > 0 else 0.0
                ret_b = (exit_pb - entry_pb) / entry_pb if entry_pb > 0 else 0.0
                pnl_pct = direction * (ret_a - ret_b)
                trades.append({
                    "symbol_a": symbol_a, "symbol_b": symbol_b,
                    "entry_time": entry_time, "exit_time": t,
                    "direction": direction, "entry_z": round(entry_z, 3),
                    "exit_z": round(z, 3), "pnl_pct": round(pnl_pct * 100, 4),
                    "duration_bars": i - list(times).index(entry_time),
                })
                in_trade = False

    return trades


# =============================================================================
# COINTEGRATION PAIR BACKTEST (via BacktestEngine for apples-to-apples)
# =============================================================================


def run_coint_pair_oos_trades(pair_row: pd.Series, tf_dir: str) -> list:
    """Run confirmed coint pair through BacktestEngine (holdout, no STORM/ML) and return the
    raw Trade list. Split out from the old run_coint_pair_oos_sharpe (BUG-D59 fix, 2026-07-12)
    so trades can be POOLED across all pairs into one daily P&L series before computing a
    single portfolio Sharpe -- averaging small-sample PER-PAIR Sharpes (the old approach) lets
    one thinly-traded pair with a lucky few days dominate the mean; see Development.md."""
    spread_path = os.path.join(
        _RESULTS_DIR, tf_dir,
        f"spread_series_{pair_row['symbol_a']}_{pair_row['symbol_b']}.parquet"
    )
    if not os.path.exists(spread_path):
        return []

    spread_df = pd.read_parquet(spread_path)
    engine = BacktestEngine(
        cfg=__import__("config").Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
        storm_flags={},
        mm_hedge_map={},
    )
    return engine.run(pair_row, spread_df, hedge_method="ols", holdout_only=True)


def _portfolio_sharpe_from_dollar_trades(trades: list) -> float:
    """Pools raw Trade objects' pnl_net (dollars) across ALL pairs into one daily P&L series
    before computing Sharpe -- the same pooled-not-averaged methodology
    _portfolio_sharpe_from_trades (below) already uses for the distance method, and
    backtest.py's aggregate_portfolio() uses for the project's own headline Sharpe. Added for
    the BUG-D59 fix so the cointegration-vs-distance comparison is apples-to-apples (both
    pooled), not a per-pair mean vs. a pooled portfolio Sharpe."""
    if not trades:
        return float("nan")
    exit_times = [t.exit_time for t in trades if t.exit_time is not None]
    pnl = [t.pnl_net for t in trades if t.exit_time is not None]
    if not exit_times:
        return float("nan")
    df = pd.DataFrame({"exit_time": exit_times, "pnl_net": pnl})
    df["date"] = pd.to_datetime(df["exit_time"]).dt.date
    daily = df.groupby("date")["pnl_net"].sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


# =============================================================================
# MAIN
# =============================================================================


def _portfolio_sharpe_from_trades(trade_dicts: List[dict]) -> float:
    if not trade_dicts:
        return float("nan")
    df = pd.DataFrame(trade_dicts)
    df["date"] = pd.to_datetime(df["exit_time"]).dt.date
    daily = df.groupby("date")["pnl_pct"].sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def main():
    _setup_logging()
    t0 = time.time()
    log.info("distance.py — Gatev-style SSD baseline")
    log.info("=" * 60)

    os.makedirs(_OUT_DIR, exist_ok=True)

    # Load confirmed cointegration pairs
    tiers_path = os.path.join(_STATS_DIR, "cointegration_tiers.parquet")
    if not os.path.exists(tiers_path):
        log.error("cointegration_tiers.parquet not found — run stats.py first")
        return

    tiers = pd.read_parquet(tiers_path)
    log.info("Loaded %d confirmed cointegration pairs", len(tiers))

    all_results = []

    for tf_dir, tf_label in _TF_DIRS:
        log.info("\n--- Timeframe: %s ---", tf_label)

        tf_pairs = tiers[tiers["tf_label"] == tf_label].copy()
        if len(tf_pairs) == 0:
            log.info("  No confirmed pairs for %s", tf_label)
            continue

        # Collect all unique symbols appearing in this TF's confirmed pairs
        symbols_in_pairs = set(tf_pairs["symbol_a"].tolist() + tf_pairs["symbol_b"].tolist())

        # Determine formation/trading split from spread_series timestamps
        # Use median first-date across all pair spread files as formation start
        sample_spreads = []
        for _, row in tf_pairs.head(3).iterrows():
            sp = os.path.join(_RESULTS_DIR, tf_dir,
                              f"spread_series_{row['symbol_a']}_{row['symbol_b']}.parquet")
            if os.path.exists(sp):
                sample_spreads.append(pd.read_parquet(sp))

        if not sample_spreads:
            log.warning("  No spread files found for %s — skipping", tf_label)
            continue

        all_idx = pd.concat([s.index.to_frame() for s in sample_spreads], ignore_index=True)
        all_idx = pd.to_datetime(all_idx.iloc[:, 0])
        full_start = all_idx.min()
        full_end = all_idx.max()
        formation_end = full_start + (full_end - full_start) * _FORMATION_FRAC
        log.info("  Formation window: %s => %s", full_start.date(), formation_end.date())
        log.info("  Trading window:   %s => %s", formation_end.date(), full_end.date())

        # Step 1: SSD ranking over all confirmed-pair symbols
        ssd_df = compute_ssd_pairs(list(symbols_in_pairs), tf_dir, formation_end)
        if len(ssd_df) == 0:
            log.warning("  SSD computation returned no pairs for %s", tf_label)
            continue

        top_k = min(_TOP_K, len(ssd_df))
        top_ssd = ssd_df.head(top_k)
        log.info("  Top-%d distance pairs by SSD (lowest = most co-moving):", top_k)
        for _, r in top_ssd.head(5).iterrows():
            log.info("    %s/%s  SSD=%.4f  n=%d", r.symbol_a, r.symbol_b, r.ssd, r.n_overlap)

        # Which confirmed coint pairs are also in the top-K distance selection?
        confirmed_set = set(zip(tf_pairs["symbol_a"], tf_pairs["symbol_b"]))
        ssd_set = set(zip(top_ssd["symbol_a"], top_ssd["symbol_b"]))
        # Also check reversed (order may differ)
        ssd_set_rev = ssd_set | {(b, a) for a, b in ssd_set}
        overlap = {(a, b) for a, b in confirmed_set if (a, b) in ssd_set_rev or (b, a) in ssd_set_rev}
        log.info(
            "  Overlap: %d/%d confirmed pairs also selected by distance (top-%d)",
            len(overlap), len(confirmed_set), top_k,
        )

        # Step 2: Run distance trades for top-K SSD pairs
        log.info("  Running distance-method OOS simulation...")
        dist_trades: List[dict] = []
        for _, r in top_ssd.iterrows():
            t = run_distance_trades(r.symbol_a, r.symbol_b, tf_dir, formation_end)
            dist_trades.extend(t)
        dist_sharpe = _portfolio_sharpe_from_trades(dist_trades)
        n_dist = len(dist_trades)
        dist_pnl_pct = sum(t["pnl_pct"] for t in dist_trades)
        dist_wr = sum(1 for t in dist_trades if t["pnl_pct"] > 0) / n_dist if n_dist > 0 else float("nan")
        log.info(
            "  Distance portfolio: Sharpe=%.3f  n_trades=%d  total_pnl=%.2f%%  WR=%.1f%%",
            dist_sharpe, n_dist, dist_pnl_pct, dist_wr * 100 if np.isfinite(dist_wr) else float("nan"),
        )

        # Step 3: Run cointegration pairs through BacktestEngine
        log.info("  Running cointegration OOS via BacktestEngine...")
        coint_sharpes = []
        coint_all_trades: List = []
        for _, row in tf_pairs.iterrows():
            trades = run_coint_pair_oos_trades(row, tf_dir)
            coint_all_trades.extend(trades)
            # Same pooling formula applied to just this one pair's trades == the old
            # per-pair Sharpe (kept for the saved parquet's per-pair transparency column).
            coint_sharpes.append(_portfolio_sharpe_from_dollar_trades(trades))
        valid_sharpes = [s for s in coint_sharpes if np.isfinite(s)]
        # BUG-D59 fix (2026-07-12): the OLD headline stat here was mean(per-pair Sharpe) --
        # unreliable on small per-pair holdout samples (one thinly-traded pair with a lucky
        # few days could show a Sharpe in the hundreds and dominate the mean; confirmed
        # directly this session: LNT/WELL showed Sharpe=114 from just 6 days of P&L). The
        # CORRECT, apples-to-apples-with-the-distance-method figure pools every pair's trades
        # into one daily P&L series first, matching _portfolio_sharpe_from_trades's own
        # methodology and backtest.py's aggregate_portfolio(). Both stats are kept and logged
        # -- the pooled one is now what SUMMARY/the saved parquet call the headline.
        coint_port_mean_sharpe = float(np.mean(valid_sharpes)) if valid_sharpes else float("nan")
        coint_port_sharpe = _portfolio_sharpe_from_dollar_trades(coint_all_trades)
        log.info(
            "  Coint portfolio: pooled_portfolio_Sharpe=%.3f  (OLD unweighted mean_pair_Sharpe=%.3f, "
            "kept for reference only -- see BUG-D59)  n_pairs=%d/%d with valid per-pair Sharpe  "
            "n_trades_pooled=%d",
            coint_port_sharpe, coint_port_mean_sharpe, len(valid_sharpes), len(coint_sharpes),
            len(coint_all_trades),
        )

        # Per-pair results
        for (a, b), sh in zip(zip(tf_pairs["symbol_a"], tf_pairs["symbol_b"]), coint_sharpes):
            in_dist = (a, b) in ssd_set_rev or (b, a) in ssd_set_rev
            ssd_row = ssd_df[(ssd_df.symbol_a == a) & (ssd_df.symbol_b == b)]
            if len(ssd_row) == 0:
                ssd_row = ssd_df[(ssd_df.symbol_a == b) & (ssd_df.symbol_b == a)]
            ssd_val = float(ssd_row["ssd"].iloc[0]) if len(ssd_row) > 0 else float("nan")
            all_results.append({
                "tf_label": tf_label, "symbol_a": a, "symbol_b": b,
                "coint_oos_sharpe": round(sh, 3) if np.isfinite(sh) else float("nan"),
                "in_distance_top_k": in_dist,
                "ssd": round(ssd_val, 4),
                "distance_port_sharpe": round(dist_sharpe, 3),
                # BUG-D59 (2026-07-12): coint_port_pooled_sharpe is the correct, apples-to-
                # apples-with-distance_port_sharpe figure (both pooled daily P&L across all
                # trades). coint_port_mean_sharpe is the OLD unweighted mean-of-per-pair-Sharpe
                # figure, kept only for backward-compatible reference -- do not use it as the
                # headline comparison number, it's unreliable on small per-pair samples.
                "coint_port_pooled_sharpe": round(coint_port_sharpe, 3) if np.isfinite(coint_port_sharpe) else float("nan"),
                "coint_port_mean_sharpe": round(coint_port_mean_sharpe, 3) if np.isfinite(coint_port_mean_sharpe) else float("nan"),
                "n_dist_trades": n_dist,
                "n_coint_pairs": len(tf_pairs),
            })

        log.info(
            "\n  === %s SUMMARY ===\n"
            "  Distance (top-%d by SSD):  Sharpe = %.3f  n_trades = %d\n"
            "  Cointegration (%d pairs):  POOLED portfolio Sharpe = %.3f  "
            "(OLD unweighted mean-of-per-pair-Sharpe = %.3f, see BUG-D59)\n"
            "  Pairs in both selections: %d/%d",
            tf_label, top_k, dist_sharpe, n_dist,
            len(tf_pairs), coint_port_sharpe, coint_port_mean_sharpe,
            len(overlap), len(confirmed_set),
        )

    # Save results
    if all_results:
        res_df = pd.DataFrame(all_results)
        out_path = os.path.join(_OUT_DIR, "distance_baseline.parquet")
        res_df.to_parquet(out_path, index=False)
        log.info("Saved => %s (%d rows)", out_path, len(res_df))

        # Summary JSON
        summary = {
            "method": "Gatev GGR (2006) SSD distance baseline",
            "formation_frac": _FORMATION_FRAC,
            "top_k": _TOP_K,
            "entry_zscore": _ENTRY_ZSCORE,
        }
        for tf_dir, tf_label in _TF_DIRS:
            tf_rows = res_df[res_df["tf_label"] == tf_label]
            if len(tf_rows) == 0:
                continue
            r0 = tf_rows.iloc[0]
            summary[tf_label] = {
                "distance_sharpe": float(r0.get("distance_port_sharpe", float("nan"))),
                "coint_mean_sharpe": float(r0.get("coint_port_mean_sharpe", float("nan"))),
                "n_distance_trades": int(r0.get("n_dist_trades", 0)),
                "n_coint_pairs": int(r0.get("n_coint_pairs", 0)),
                "overlap_in_top_k": int(tf_rows["in_distance_top_k"].sum()),
            }

        json_path = os.path.join(_OUT_DIR, "distance_summary.json")
        with open(json_path, "w") as fh:
            json.dump(summary, fh, indent=2)
        log.info("Saved => %s", json_path)
    else:
        log.warning("No results generated — check that spread_series files exist for 1hr")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("distance.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
