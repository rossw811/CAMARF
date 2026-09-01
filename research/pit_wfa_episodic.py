"""
research/pit_wfa_episodic.py -- comparison arm to pit_wfa.py's negative
finding (PAPER.md Section 7.3.1 / PAPER_MAGNITUDE.md Section 6): does
swapping the STATIC full-history + fixed-252-bar-rolling-fraction pair-
discovery method for the EPISODIC, regime-aware, decades-deep WRDS
methodology (Section 5's Finding #28 machinery) change the point-in-time
walk-forward result?

Motivation (2026-08-24 discussion with Ross): the negative PIT-WFA finding
used production's ORIGINAL screening method (Pearson prefilter -> full-
history EG+BH-FDR -> fixed 252-bar coint_fraction_rolling), which Finding
#28 itself shows is poorly matched to how episodic cointegration actually
behaves (only 9.2% of regime-spans are ever cointegrated; a fixed-window
rolling fraction can't distinguish "currently in a strong regime" from
"was cointegrated a decade ago"). This is a genuine, pre-identified next
question -- Finding #28's own writeup names it directly: "does a pair's
regime strength predict whether it survives a genuine point-in-time
re-screen? Not yet asked of the data." This script asks it, honestly,
pre-registered to report the result regardless of direction -- NOT a
parameter sweep against the same method looking for a profitable
configuration.

Design, reusing already-built production machinery rather than
reimplementing:
  - Pair discovery: `research.wrds_deep_history_episodic_scan.
    episodic_bhfdr_confirm_asof()` -- ALREADY point-in-time-safe (restricts
    to (pair, window) tests whose window_end_date <= as_of_date, re-applies
    joint BH-FDR only over that as-of-eligible subset). No new statistical
    test is introduced here; this script is a NEW CONSUMER of an existing,
    already-verified function, applied to a walk-forward comparison it was
    not previously wired into.
  - Source data: `output/research/wrds_deep_history_episodic_scan_tier3_
    windows.parquet` -- the flat (pair, window, pvalue, window_end_date)
    rows Tier 3 already computed ONCE across full history. Re-querying this
    at each checkpoint's as_of_date is vastly cheaper than re-running the
    rolling correlation+EG scan per fold (which is what pit_wfa.py's own
    screen_universe_at_cutoff() does for the static method, at real per-
    fold cost).
  - Spread construction / backtest: mirrors pit_wfa.py's own
    backtest_pair_on_test_window() exactly (same AnalysisPipeline.
    _build_pair_result, same DataAligner.align_universe(drop_data_gap_rows=
    True) fix for the calendar-padding/bar-inflation bug pit_wfa.py itself
    already caught and fixed), adapted for WRDS 1D price series instead of
    yfinance 1h cache.
  - Checkpoints: the SAME 3 calendar dates as PAPER.md Section 7.3.1's
    original checkpoint sweep (2024-02-01, 2025-01-01, 2025-08-01), test_end
    = the full available window's end ("trade forward from cutoff to now")
    -- for a direct, apples-to-apples comparison against the existing
    negative-backtest numbers, not new dates chosen after seeing results.

Honest scope note, carried into the runtime output: the underlying Tier-3
windows file this script reads may itself predate the 2026-08-24 universe-
undercount fix (see PAPER_MAGNITUDE.md Section 1.2/12) -- this is disclosed
at load time, not silently assumed current, and this script re-reads
whatever file exists at run time (a fresh, corrected-scale Tier-3 run will
be picked up automatically on the next invocation once available, no code
change needed).

Output:
  output/research/pit_wfa_episodic_fold_comparison.parquet -- per-pair,
    per-checkpoint metrics
  output/research/pit_wfa_episodic_portfolio.parquet -- portfolio-level
    per-checkpoint aggregate, directly comparable to pit_wfa.py's own
    output/backtest/pit_wfa_portfolio.parquet
  output/research/pit_wfa_episodic_pair_sets.parquet -- which pairs were
    point-in-time episodically confirmed at each checkpoint
  latest_run_pit_wfa_episodic.log

Verified against synthetic ground truth first:
debug/_verify_pit_wfa_episodic.py.
"""
import glob
import logging
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, CointScanner
from backtest import BacktestEngine, RegimeConditioner, MLConditioner, compute_metrics, aggregate_portfolio
from config import Config
from data import DataAligner
from research.wrds_deep_history_episodic_scan import episodic_bhfdr_confirm_asof

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_TIER3_WINDOWS_PATH = os.path.join(_ROOT, "output", "research",
                                    "wrds_deep_history_episodic_scan_tier3_windows.parquet")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_TF_LABEL = "1D"

# Identical to PAPER.md Section 7.3.1's original checkpoint sweep -- same
# dates, for direct comparability against the existing negative-backtest
# numbers. test_end is always "now" (the full available window's end),
# matching that sweep's own "trade forward from cutoff to now" convention.
CHECKPOINT_DATES = ["2024-02-01", "2025-01-01", "2025-08-01"]

log = logging.getLogger("pit_wfa_episodic")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_pit_wfa_episodic.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_tier3_windows(path: str = _TIER3_WINDOWS_PATH) -> Tuple[List[Dict], float]:
    """Loads the flat (pair, window) p-value rows Tier 3 already computed.
    Returns (rows_as_dicts, file_mtime_unix) -- the caller logs the mtime so
    a stale (pre-universe-fix) file is visible in the run log, not hidden."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} does not exist -- run research/wrds_deep_history_episodic_scan.py "
            f"first (Tier 3 writes this file). Cannot compute anything without it."
        )
    df = pd.read_parquet(path)
    mtime = os.path.getmtime(path)
    rows = df[["symbol_a", "symbol_b", "pvalue", "window_end_date"]].to_dict("records")
    return rows, mtime


def load_symbol_close(symbol: str) -> pd.DataFrame:
    """Single-symbol WRDS 1D loader -- reads exactly one *_1D.parquet file,
    NOT the full ~43,700-symbol universe. This script only ever needs the
    handful of symbols that show up in a checkpoint's confirmed-pair set,
    so loading the whole universe (as load_wrds_universe() does for the
    main scan) would be wasteful here -- same close_total_return-with-
    split-only-fallback convention as that function, not reimplemented
    differently."""
    path = os.path.join(_WRDS_CACHE_DIR, f"{symbol}_1D.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    if "close_total_return" in df.columns and df["close_total_return"].notna().any():
        close = df["close_total_return"]
    elif "close" in df.columns:
        close = df["close"]
    else:
        return pd.DataFrame()
    out = pd.DataFrame({"close": close}, index=df.index)
    out.index.name = "date"
    return out


def screen_at_checkpoint(tier3_rows: List[Dict], as_of_date: pd.Timestamp, alpha: float) -> List[Dict]:
    """Point-in-time episodic pair discovery as of `as_of_date` -- thin
    wrapper around the already-verified episodic_bhfdr_confirm_asof(), the
    entire causal-safety mechanism this script relies on."""
    confirmed = episodic_bhfdr_confirm_asof(tier3_rows, alpha, as_of_date, min_windows_confirmed=1)
    return confirmed


def backtest_pair_on_test_window(
    sym_a: str, sym_b: str, cutoff: pd.Timestamp, test_start: pd.Timestamp, test_end: pd.Timestamp,
) -> Tuple[List, Dict]:
    """Mirrors pit_wfa.py's backtest_pair_on_test_window() exactly (same
    _build_pair_result / DataAligner(drop_data_gap_rows=True) / BacktestEngine
    pattern, same reason for drop_data_gap_rows=True -- a single-pair/real-
    timestamp-join consumer, not the main pipeline's dense cross-symbol
    matrix), adapted for WRDS 1D price series."""
    df_a, df_b = load_symbol_close(sym_a), load_symbol_close(sym_b)
    if df_a.empty or df_b.empty:
        return [], {}

    full_slice = {
        sym_a: df_a.loc[(df_a.index >= cutoff) & (df_a.index <= test_end)],
        sym_b: df_b.loc[(df_b.index >= cutoff) & (df_b.index <= test_end)],
    }
    aligned = DataAligner.align_universe(
        {f"{sym}_{_TF_LABEL}": df for sym, df in full_slice.items()}, _TF_LABEL,
        drop_data_gap_rows=True,
    )
    if sym_a not in aligned or sym_b not in aligned:
        return [], {}

    common_idx = aligned[sym_a].index.intersection(aligned[sym_b].index)
    if len(common_idx) < 60:
        return [], {}
    aligned = {sym_a: aligned[sym_a].loc[common_idx], sym_b: aligned[sym_b].loc[common_idx]}

    built = AnalysisPipeline._build_pair_result(
        {"symbol_a": sym_a, "symbol_b": sym_b}, aligned, _TF_LABEL
    )
    if built is None:
        return [], {}
    full_pair_result, per_bar = built

    spread_df = pd.DataFrame(
        {
            "spread": per_bar["spread"],
            "z_rolling": per_bar["z_rolling"],
            "z_expanding": per_bar["z_expanding"],
            "half_life_rolling": per_bar["half_life_rolling_series"],
            "gap_flag_a": per_bar["gap_flag_a"],
            "gap_flag_b": per_bar["gap_flag_b"],
            "hedge_ratio_ols_t": per_bar.get("hedge_ratio_ols_t"),
            "hedge_ratio_kalman_t": per_bar.get("hedge_ratio_kalman_t"),
            "coint_fraction_rolling_t": per_bar.get("coint_fraction_rolling_t"),
            "half_life_trend_slope_t": per_bar.get("half_life_trend_slope_t"),
            "mean_reversion_speed_t": per_bar.get("mean_reversion_speed_t"),
            "hurst_rs_t": per_bar.get("hurst_rs_t"),
        },
        index=per_bar["index"],
    )
    test_slice = spread_df.loc[(spread_df.index >= test_start) & (spread_df.index <= test_end)]
    if len(test_slice) < 30:
        return [], {}

    # None -> np.nan coercion (found live 2026-08-24): _build_pair_result can leave scalar
    # fields (e.g. hurst_rs) as a genuine None rather than np.nan on a short WRDS slice --
    # backtest.py's engine.run() does `float(pair_row.get("hurst_rs", np.nan))`, and a
    # dict.get()/getattr() default only applies when the KEY IS MISSING, not when it's present
    # with value None, so this crashed with "float() argument must be a string or a real
    # number, not 'NoneType'" instead of silently using the nan default. Explicit coercion here
    # rather than touching pit_wfa.py's own copy of this pattern, which may never hit this path
    # on its own 1h yfinance data.
    pair_row = pd.Series({**vars(full_pair_result), "tf_label": _TF_LABEL})
    pair_row = pair_row.map(lambda v: np.nan if v is None else v)
    engine = BacktestEngine(
        cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
    )
    trades = engine.run(pair_row, test_slice, hedge_method="ols", holdout_only=False)
    metrics = compute_metrics(trades, _TF_LABEL, sym_a, sym_b, "ols") if trades else {}
    return trades, metrics


def run_checkpoint(tier3_rows: List[Dict], checkpoint_date: str, overall_end: pd.Timestamp) -> Tuple[List[Dict], Dict, List[Dict]]:
    cutoff = pd.Timestamp(checkpoint_date)
    alpha = Config.STATS.FDR_ALPHA

    log.info("[checkpoint_%s] screening episodically as-of %s (point-in-time, windows concluded by this date only)...",
              checkpoint_date, cutoff.date())
    t0 = time.time()
    confirmed = screen_at_checkpoint(tier3_rows, cutoff, alpha)
    log.info("[checkpoint_%s] %d pairs point-in-time episodically confirmed (%.1fs)",
              checkpoint_date, len(confirmed), time.time() - t0)

    pair_set_rows = [
        {"checkpoint": checkpoint_date, "symbol_a": c["symbol_a"], "symbol_b": c["symbol_b"],
         "episodic_fraction_fdr": c["episodic_fraction_fdr"], "min_adjusted_pvalue": c["min_adjusted_pvalue"],
         "n_windows_tested": c["n_windows_tested"], "n_windows_fdr_rejected": c["n_windows_fdr_rejected"]}
        for c in confirmed
    ]

    all_trades, all_metrics = [], []
    for c in confirmed:
        trades, metrics = backtest_pair_on_test_window(
            c["symbol_a"], c["symbol_b"], cutoff, cutoff, overall_end
        )
        if trades:
            all_trades.extend(trades)
            if metrics:
                all_metrics.append(metrics)

    portfolio_stats = aggregate_portfolio(all_trades, all_metrics)
    portfolio_stats.update({
        "checkpoint": checkpoint_date,
        "n_pit_confirmed_pairs": len(confirmed),
        "n_pairs_with_trades": len(all_metrics),
    })
    log.info("[checkpoint_%s] backtest: %d pairs traded, %d trades, portfolio Sharpe=%.4f",
              checkpoint_date, len(all_metrics), len(all_trades),
              portfolio_stats.get("sharpe_portfolio", float("nan")))

    return all_metrics, portfolio_stats, pair_set_rows


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== pit_wfa_episodic.py: does swapping static full-history screening for the "
             "episodic/regime-aware method change the PIT-WFA negative finding? "
             "Pre-registered to report the result regardless of direction. ===")

    tier3_rows, mtime = load_tier3_windows()
    mtime_str = pd.Timestamp(mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"Loaded {len(tier3_rows)} (pair, window) rows from "
             f"wrds_deep_history_episodic_scan_tier3_windows.parquet (file mtime: {mtime_str})")
    all_end_dates = [r["window_end_date"] for r in tier3_rows if r.get("window_end_date") is not None]
    overall_end = max(all_end_dates)
    log.info(f"Overall available window ends {pd.Timestamp(overall_end).date()} "
             f"-- each checkpoint trades forward from its cutoff to this date.")

    all_metrics_rows, portfolio_rows, pair_set_rows = [], [], []
    for cp in CHECKPOINT_DATES:
        metrics, portfolio, pairs = run_checkpoint(tier3_rows, cp, pd.Timestamp(overall_end))
        all_metrics_rows.extend(metrics)
        portfolio_rows.append(portfolio)
        pair_set_rows.extend(pairs)

    os.makedirs(_OUT_DIR, exist_ok=True)
    pd.DataFrame(all_metrics_rows).to_parquet(os.path.join(_OUT_DIR, "pit_wfa_episodic_fold_comparison.parquet"), index=False)
    pd.DataFrame(portfolio_rows).to_parquet(os.path.join(_OUT_DIR, "pit_wfa_episodic_portfolio.parquet"), index=False)
    pd.DataFrame(pair_set_rows).to_parquet(os.path.join(_OUT_DIR, "pit_wfa_episodic_pair_sets.parquet"), index=False)

    log.info("=" * 70)
    log.info("SUMMARY (reported regardless of direction -- this is a pre-registered comparison arm):")
    for row in portfolio_rows:
        log.info(f"  checkpoint={row['checkpoint']}: {row['n_pit_confirmed_pairs']} pairs confirmed, "
                 f"{row['n_pairs_with_trades']} traded, Sharpe={row.get('sharpe_portfolio', float('nan')):.4f}")
    log.info(f"pit_wfa_episodic.py complete ({(time.time() - t0) / 60:.1f} min)")


if __name__ == "__main__":
    main()
