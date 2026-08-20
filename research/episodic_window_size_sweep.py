"""
research/episodic_window_size_sweep.py -- Thread J Test 1 / Thread G-Full
Tier 4: sweeps EPISODIC_WINDOW_BARS (Ross's concern, 2026-08-13: "i'm not
sure the 10 year equivalent of bars is the best target for cointegration
because different assets will be cointegrated differently and periodically").

Scope, deliberately narrower than a full wrds_deep_history_episodic_scan.py
rerun per grid point -- Tier 1 (full-sample EG) and Tier 2 (static-corr
rolling EG) are EXCLUDED here, not silently: Tier 2 was already excluded
from the PIT-safe pipeline by BUG-D112 (non-causal candidate pool), and
Tier 1's own confirmation doesn't depend on window size at all (only its
post-hoc "stability description" does, which isn't used for confirmation
per its own docstring). ONLY Tier 3 (rolling correlation prefilter +
rolling-window EG, the actual PIT-safe source per BUG-D112) is window-
dependent and re-run per grid point -- this alone is still the expensive
part (the original single-window-size run took ~14hr for Tier 3), but
skipping Tier 1/2 avoids real, unnecessary duplicate compute.

Does NOT need a live WRDS connection -- reuses wrds_deep_history_episodic_
scan.py's existing loaders, all of which read already-cached output/cache/
wrds/ files, same as that script itself.

SCOPE (decided 2026-08-13, real decision point, not assumed): `load_wrds_
universe()` globs EVERY *_1D.parquet in output/cache/wrds/ with no built-in
filtering -- since the international fetch (Thread I) landed 15,094 GVKEY*-
labeled files there, an unfiltered call now pulls in a ~17,000-symbol
combined universe, not the original ~1,700 domestic one this project's
existing baselines (Finding #23, BUG-D112's redo) were computed against.
Per Ross's explicit direction, this sweep uses the COMBINED universe,
restricted to the international_liquidity_filter.py output (liquid
symbols only, not the raw unfiltered 15,094) -- falls back to domestic-only
if that filter hasn't completed yet, never silently to the unfiltered
combined set.

Each grid point's output is saved under a window-size-specific filename
(not overwriting the production tier3_windows.parquet) and uses a distinct
checkpoint_id, so a crash/interrupt on one grid point doesn't lose progress
on others, and doesn't collide with the production scan's own checkpoint.

Usage:
    python research/episodic_window_size_sweep.py --grid 1260 2520 3780
    python research/episodic_window_size_sweep.py --grid 2520 --dry-run
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from config import Config
from research.wrds_deep_history_episodic_scan import (
    _setup_logging, _OUT_DIR, load_wrds_universe, load_wrds_universe_ohlcv,
    load_membership_gate, build_log_prices_and_returns,
    build_log_prices_and_returns_bounded, rolling_adv,
    rolling_correlation_candidate_pairs, run_rolling_eg_pool,
    episodic_bhfdr_confirm, clear_checkpoint, log,
)

# Grid centered on the current 2520-bar (~10yr) default, spanning ~2yr to
# ~20yr equivalents (252 bars/yr, matching EPISODIC_STEP_BARS' own convention
# for what "a year" means in this scan) -- not arbitrary, but not claimed
# optimal either, that's what this sweep is FOR.
DEFAULT_GRID_BARS = [504, 1260, 2520, 3780, 5040]  # ~2/5/10/15/20yr


def run_one_window_size(window_bars, step_bars, log_price_df, returns, symbols,
                         threshold, asset_class_map, adv_by_symbol,
                         membership_df, permno_by_symbol, chunk_batch_size=None):
    checkpoint_id = f"tier3_rolling_windowsweep_w{window_bars}"
    log.info(f"=== window={window_bars} bars (~{window_bars/252:.1f}yr), "
             f"step={step_bars} bars ===")

    t0 = time.time()
    tier3_pairs = rolling_correlation_candidate_pairs(
        returns, symbols, threshold, asset_class_map, window=window_bars, step=step_bars,
        chunk_batch_size=chunk_batch_size,
    )
    log.info(f"  {len(tier3_pairs)} candidate pairs at window={window_bars}")

    tier3_flat = run_rolling_eg_pool(
        tier3_pairs, log_price_df, Config.ANALYSIS.EG_MAX_LAG, window=window_bars, step=step_bars,
        adv_by_symbol=adv_by_symbol, checkpoint_id=checkpoint_id,
        membership_df=membership_df, permno_by_symbol=permno_by_symbol,
    )
    clear_checkpoint(checkpoint_id)
    tier3_confirmed = episodic_bhfdr_confirm(tier3_flat, Config.STATS.FDR_ALPHA)
    runtime_min = (time.time() - t0) / 60
    log.info(f"  window={window_bars}: {len(tier3_flat)} (pair,window) tests -> "
             f"{len(tier3_confirmed)} episodically confirmed ({runtime_min:.1f} min)")

    windows_path = os.path.join(_OUT_DIR, f"episodic_window_sweep_w{window_bars}_windows.parquet")
    confirmed_path = os.path.join(_OUT_DIR, f"episodic_window_sweep_w{window_bars}_confirmed.parquet")
    pd.DataFrame(tier3_flat).to_parquet(windows_path, index=False)
    pd.DataFrame(tier3_confirmed).to_parquet(confirmed_path, index=False)
    log.info(f"  Saved -> {windows_path}, {confirmed_path}")
    return {
        "window_bars": window_bars, "step_bars": step_bars,
        "n_candidate_pairs": len(tier3_pairs), "n_window_tests": len(tier3_flat),
        "n_confirmed": len(tier3_confirmed), "runtime_min": runtime_min,
    }


def main():
    p = argparse.ArgumentParser(description="Thread J Test 1: EPISODIC_WINDOW_BARS sweep")
    p.add_argument("--grid", type=int, nargs="+", default=DEFAULT_GRID_BARS)
    p.add_argument("--step-ratio", type=float, default=0.1,
                    help="step_bars = round(window_bars * step_ratio) -- default 0.1 matches "
                         "the production 2520/252 = 10:1 window:step ratio exactly.")
    p.add_argument("--dry-run", action="store_true", help="Load universe + print grid, run nothing")
    p.add_argument("--threshold", type=float, default=None,
                    help="Pearson correlation threshold for Tier 3's rolling candidate pool. "
                         "Defaults to Config.UNIVERSE.MIN_PEARSON_CORR (0.4) if not given. Ross's "
                         "0.4 default dated from an earlier, much smaller (~500-symbol) universe "
                         "phase where 0.6 produced no results -- with the universe now much larger "
                         "and 0.6 already the chosen threshold for the full-universe correlation/EG "
                         "cascade work (2026-08-14/15), pass --threshold 0.6 here for consistency.")
    p.add_argument("--full-universe", action="store_true",
                    help="Bypass the international liquidity filter and use ALL 44,694 cached WRDS "
                         "symbols (including illiquid international names), not just the 2,930-symbol "
                         "liquid subset. Ross's explicit choice (2026-08-15) for this sweep -- disclosed "
                         "here, not a silent default change: illiquid names carry real ADV/liquidity "
                         "risk this project otherwise screens for elsewhere (Config.DATA.MIN_DOLLAR_"
                         "VOLUME), so results from this mode should be read as 'discovery scope', not "
                         "'tradeable universe' scope.")
    args = p.parse_args()

    _setup_logging()
    log.info(f"=== episodic_window_size_sweep.py: grid={args.grid} bars "
             f"(~{[round(b/252,1) for b in args.grid]} years) ===")

    # load_wrds_universe() globs EVERY *_1D.parquet in output/cache/wrds/ with
    # no filtering -- since the international fetch (Thread I) landed
    # 15,094 GVKEY*-labeled files there, an unfiltered call now pulls in a
    # ~17,000-symbol combined universe, not the original ~1,700 domestic one.
    # Per Ross's explicit direction (2026-08-13): combined universe IS wanted
    # here, but restricted to the LIQUIDITY-FILTERED international subset
    # (output/research/international_liquid_universe.parquet), not the raw
    # unfiltered 15,094 -- avoids diluting the candidate pool with illiquid
    # junk. Falls back to domestic-only (excludes all GVKEY* symbols) if the
    # liquid list doesn't exist yet, rather than silently using the
    # unfiltered international set.
    close_by_symbol, split_only_symbols = load_wrds_universe()
    if args.full_universe:
        log.info(f"--full-universe: international liquidity filter SKIPPED (Ross's explicit choice, "
                 f"2026-08-15) -- using all {len(close_by_symbol)} cached WRDS symbols as-is, "
                 f"including illiquid international names.")
    else:
        _liquid_path = os.path.join("output", "research", "international_liquid_universe.parquet")
        if os.path.exists(_liquid_path):
            liquid_labels = set(pd.read_parquet(_liquid_path, columns=["label"])["label"])
            before = len(close_by_symbol)
            close_by_symbol = {
                s: v for s, v in close_by_symbol.items()
                if not s.startswith("GVKEY") or s in liquid_labels
            }
            log.info(f"International liquidity filter applied: {before} -> {len(close_by_symbol)} symbols "
                     f"({len(liquid_labels)} liquid international symbols allowed through)")
        else:
            before = len(close_by_symbol)
            close_by_symbol = {s: v for s, v in close_by_symbol.items() if not s.startswith("GVKEY")}
            log.warning(f"{_liquid_path} not found -- international_liquidity_filter.py hasn't "
                        f"completed yet. Falling back to DOMESTIC-ONLY ({before} -> {len(close_by_symbol)} "
                        f"symbols), NOT the unfiltered combined universe.")
    if len(close_by_symbol) < 10:
        log.warning("Fewer than 10 symbols loaded -- aborting.")
        return
    ohlcv_universe = load_wrds_universe_ohlcv()
    ohlcv_universe = {s: v for s, v in ohlcv_universe.items() if s in close_by_symbol}
    adv_by_symbol = {sym: rolling_adv(df) for sym, df in ohlcv_universe.items()}
    membership_df, permno_by_symbol = load_membership_gate()
    if args.full_universe:
        # The plain pd.DataFrame(dict-of-Series) path OOM-crashes at this scale (confirmed live,
        # 2026-08-15) -- use the memory-bounded alternative instead. lookback_years derived from
        # the requested grid's own max (+2yr safety margin) rather than a fixed guess, so a wider
        # --grid than the default automatically gets a wide-enough canonical calendar.
        lookback_years = max(b / 252 for b in args.grid) + 2
        log.info(f"--full-universe: using build_log_prices_and_returns_bounded "
                 f"(lookback_years={lookback_years:.1f}, float32) to avoid the OOM this scale hits "
                 f"with the original function.")
        log_price_df, returns = build_log_prices_and_returns_bounded(
            close_by_symbol, lookback_years=lookback_years,
        )
    else:
        log_price_df, returns = build_log_prices_and_returns(close_by_symbol)
    symbols = list(returns.columns)
    asset_class_map = {s: "equity" for s in symbols}
    threshold = args.threshold if args.threshold is not None else Config.UNIVERSE.MIN_PEARSON_CORR
    log.info(f"{len(symbols)} symbols loaded, threshold={threshold}")

    if args.dry_run:
        log.info("--dry-run: universe loaded, stopping before any grid point runs.")
        return

    summary_rows = []
    for window_bars in args.grid:
        step_bars = max(1, round(window_bars * args.step_ratio))
        row = run_one_window_size(
            window_bars, step_bars, log_price_df, returns, symbols, threshold,
            asset_class_map, adv_by_symbol, membership_df, permno_by_symbol,
            chunk_batch_size=1500 if args.full_universe else None,
        )
        summary_rows.append(row)
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_parquet(os.path.join(_OUT_DIR, "episodic_window_sweep_summary.parquet"), index=False)
        log.info(f"Progress: {len(summary_rows)}/{len(args.grid)} grid points done. "
                 f"Summary so far:\n{summary_df.to_string(index=False)}")

    log.info("=== episodic_window_size_sweep.py complete ===")
    log.info(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    main()
