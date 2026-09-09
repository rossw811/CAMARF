"""
research/pit_wfa_wrds_daily.py -- Point-In-Time Portfolio-Wide Walk-Forward
Analysis on WRDS DAILY bars, full ~44,840-symbol merged universe.

Motivation (2026-09-03, Ross: "let's get the corrected scale to be on WRDS
bars... change the 1580 cap to the WRDS bars. WRDS takes complete priority
over other providers of data."): `pit_wfa.py` (PAPER_MAGNITUDE.md §4's
causal-validity finding) is explicitly, deliberately scoped to 1h bars from
whatever's cached in `output/cache/*_1hr.parquet` (~1,580 symbols) -- its
own docstring discloses this as a real cost tradeoff (~45-50 min per fold
cutoff at that scale), not a bug. WRDS/CRSP carries ZERO intraday data
(disclosed throughout this project), so §4 can never reach anywhere near
§5's ~44,840-symbol daily scale while staying at 1h -- the only way to
reach real scale is a genuinely different script at daily granularity, not
a parameter tweak to the existing one. Built here as a NEW comparison-arm
script (`pit_wfa.py` is unmodified, still cited as-is in the paper) rather
than mutated in place, matching this project's own established convention
(Tier 1/2/3, the DCC-GARCH comparison, etc. -- a new methodology gets its
own script, not an overwrite of the one already producing cited results).

Reuses pit_wfa.py's pure, timeframe-agnostic functions directly (fold
fraction definitions, fold-date computation, analysis-window detection) --
only the universe-loading and screening functions are genuinely different,
for two real reasons: (1) universe source -- `universe_loader.load_full_
universe(tf_label="1D", ...)` instead of a raw `output/cache` glob (WRDS
already wins on any symbol collision per that loader's own merge order:
"WRDS, then Binance, then IBKR override yfinance" -- already satisfies
"WRDS takes complete priority," no new logic needed there); (2) the
CORRELATION step must be memory-bounded at this scale -- pit_wfa.py's
dense `UniverseFilter.run()` call would need a ~44,840x44,840 float64
matrix (~16GB) just for correlation; this uses `UniverseFilter.chunked_
pearson_candidate_pairs` instead, the same memory-bounded primitive Tier 3
(`wrds_deep_history_episodic_scan.py`) already proved at this exact scale.

Verified against synthetic ground truth first:
debug/_verify_pit_wfa_wrds_daily.py.

Usage:
    python research/pit_wfa_wrds_daily.py --variant both
"""
import logging
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, UniverseFilter, CointScanner, CrossAssetTagger
from backtest import BacktestEngine, RegimeConditioner, MLConditioner, compute_metrics, aggregate_portfolio
from config import Config
from data import DataAligner
from pit_wfa import compute_fold_dates, FOLD_EXPANDING, FOLD_ROLLING

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "backtest")

_TF_LABEL = "1D"

log = logging.getLogger("pit_wfa_wrds_daily")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_pit_wfa_wrds_daily.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_universe_wrds_daily(columns=None) -> Dict[str, pd.DataFrame]:
    """Full merged daily universe via the canonical loader -- WRDS wins on
    any symbol collision per the loader's own documented merge order
    (WRDS, then Binance, then IBKR override yfinance), satisfying "WRDS
    takes complete priority" without any new merge logic. yfinance/Binance/
    IBKR stay included: they fill genuine coverage gaps (crypto, forex,
    international names outside WRDS's US+Compustat-Global scope), they
    just never override a WRDS-sourced symbol where both exist.

    Normalizes every symbol's index to tz-NAIVE here, once, at the single
    point every downstream consumer (determine_analysis_window,
    screen_universe_at_cutoff, backtest_pair_on_test_window) draws from --
    found live, real bug (2026-09-03): 15 of 43,883 symbols (Binance
    crypto: ADA, ATOM, AVAX, BCH, BTC, ...) have tz-AWARE (UTC) indices
    while every other source is tz-naive, and comparing a tz-naive fold
    cutoff against a tz-aware symbol's index raises TypeError, not a
    silent wrong answer -- crashed the live full-scale run on its very
    first call to determine_analysis_window(). Fixing it once here, not
    per call-site, guarantees every later comparison in this module is
    safe, not just the one that happened to crash first."""
    import universe_loader
    universe = universe_loader.load_full_universe(
        tf_label=_TF_LABEL, include_yfinance=True, include_wrds=True,
        include_binance=True, include_ibkr=True, columns=columns,
    )
    for sym, df in universe.items():
        if df is not None and not df.empty and df.index.tz is not None:
            universe[sym] = df.tz_localize(None)
    return universe


def _tz_naive(ts: pd.Timestamp) -> pd.Timestamp:
    """Strips timezone info if present, otherwise returns unchanged --
    found live, real bug (2026-09-03): at full-universe scale, 15 of
    43,883 symbols (all Binance crypto: ADA, ATOM, AVAX, BCH, BTC, ...)
    have tz-AWARE (UTC) indices while every other source (WRDS, yfinance,
    IBKR) is tz-naive, and Python's builtin `min()`/`max()` cannot compare
    tz-naive and tz-aware Timestamps at all (raises TypeError, not a
    silent wrong answer) -- crashed the live full-scale run immediately.
    A small, uniform synthetic verify test (all tz-naive throughout)
    could not have caught this; only real, heterogeneous-source data
    surfaced it. Wall-clock date value is kept as-is, tz dropped -- this
    project's daily-bar convention elsewhere already treats dates as
    calendar dates without timezone arithmetic, so dropping tz here
    matches existing practice, not a new convention invented for this
    function alone."""
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def determine_analysis_window(universe: Dict[str, pd.DataFrame]) -> Tuple[pd.Timestamp, pd.Timestamp]:
    starts = [_tz_naive(df.index.min()) for df in universe.values() if df is not None and not df.empty]
    ends = [_tz_naive(df.index.max()) for df in universe.values() if df is not None and not df.empty]
    return min(starts), max(ends)


def screen_universe_at_cutoff(
    universe: Dict[str, pd.DataFrame], train_start: pd.Timestamp, train_end: pd.Timestamp,
    n_workers: int, correlation_batch_size: int = 1500,
) -> List["object"]:
    """Daily-scale, memory-bounded equivalent of pit_wfa.py's own
    screen_universe_at_cutoff -- identical screening SEQUENCE (Pearson
    prefilter -> EG+BH-FDR -> rolling coint_fraction -> per-pair modeling
    -> structural exclusion -> coint_frac threshold + secondary-evidence
    override), the only real difference is the memory-bounded correlation
    step (chunked_pearson_candidate_pairs instead of the dense
    UniverseFilter.run(), required at ~44,840-symbol scale, not optional)."""
    truncated = {
        sym: df.loc[(df.index >= train_start) & (df.index <= train_end)]
        for sym, df in universe.items()
    }
    truncated = {sym: df for sym, df in truncated.items() if len(df) >= 60}
    if len(truncated) < 10:
        return []

    aligned = DataAligner.align_universe(
        {f"{sym}_{_TF_LABEL}": df for sym, df in truncated.items()}, _TF_LABEL,
    )
    if not aligned:
        return []

    returns, syms, _dates = UniverseFilter.build_returns_matrix(aligned)
    if len(syms) < 10:
        return []
    candidates = UniverseFilter.chunked_pearson_candidate_pairs(
        returns, syms, threshold=Config.UNIVERSE.MIN_PEARSON_CORR, asset_class_map={},
        batch_size=correlation_batch_size, progress_every=50,
        progress_label=f"[{train_end.date()}] ",
    )
    if not candidates:
        return []

    confirmed_dicts, _eg_stats = CointScanner.scan(
        candidate_pairs=candidates, aligned_data=aligned,
        symbols_in_corr=syms, tf_label=_TF_LABEL, n_workers=n_workers,
    )
    if not confirmed_dicts:
        return []

    confirmed_dicts = CointScanner.rolling_fraction(confirmed_dicts, aligned, _TF_LABEL, n_workers=n_workers)

    pair_results = []
    for pd_meta in confirmed_dicts:
        built = AnalysisPipeline._build_pair_result(pd_meta, aligned, _TF_LABEL)
        if built is not None:
            pair_results.append(built[0])

    pair_results = [
        p for p in pair_results
        if not CrossAssetTagger._shared_currency(p.symbol_a, p.symbol_b)
        and not CrossAssetTagger._is_share_class_pair(p.symbol_a, p.symbol_b)
        and not CrossAssetTagger._is_index_tracking_pair(p.symbol_a, p.symbol_b)
    ]

    min_coint_frac = getattr(Config.UNIVERSE, "MIN_COINT_FRAC", 0.40)
    confirmed = []
    for p in pair_results:
        cf = getattr(p, "coint_fraction_rolling", np.nan)
        if not np.isfinite(cf) or cf >= min_coint_frac:
            confirmed.append(p)
        elif AnalysisPipeline.passes_coint_frac_secondary_evidence(p):
            confirmed.append(p)
    return confirmed


def backtest_pair_on_test_window(
    pair_result, universe: Dict[str, pd.DataFrame],
    train_start: pd.Timestamp, test_start: pd.Timestamp, test_end: pd.Timestamp,
) -> Tuple[List, Dict]:
    """Identical to pit_wfa.py's own backtest_pair_on_test_window, just at
    _TF_LABEL="1D" -- copied rather than imported because pit_wfa.py's
    version has _TF_LABEL baked in as a module constant throughout its
    body, not passed as a parameter; duplicating this one function (not
    the whole module) keeps pit_wfa.py itself completely unmodified."""
    sym_a, sym_b = pair_result.symbol_a, pair_result.symbol_b
    if sym_a not in universe or sym_b not in universe:
        return [], {}

    full_slice = {
        sym: universe[sym].loc[(universe[sym].index >= train_start) & (universe[sym].index <= test_end)]
        for sym in (sym_a, sym_b)
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

    built = AnalysisPipeline._build_pair_result({"symbol_a": sym_a, "symbol_b": sym_b}, aligned, _TF_LABEL)
    if built is None:
        return [], {}
    full_pair_result, per_bar = built

    # Register this pair's in-memory close/spread series with portfolio_sim so the
    # capital-constrained replay (main()) can causally look up prices and spread history for
    # get_price_at()/get_spread_at() -- WRDS-daily pairs never write the 1h-cache/spread_series
    # disk files portfolio_sim's file-based fallback reads, which otherwise silently makes
    # EVERY capital-constrained trade unsizeable (real bug found live, 2026-09-03: 0/21 trades
    # taken under flat_2pct on fold1_exp, reproduced identically across relaunches -- traced to
    # this wiring gap, not a fold-specific data artifact). Registers the FULL aligned window
    # (train_start..test_end), not just the test slice, so causal_rolling_std_at_entry has
    # enough trailing history right at test_start.
    import portfolio_sim
    portfolio_sim.register_price_series(sym_a, aligned[sym_a][["close"]])
    portfolio_sim.register_price_series(sym_b, aligned[sym_b][["close"]])

    spread_df = pd.DataFrame({
        "spread": per_bar["spread"], "z_rolling": per_bar["z_rolling"],
        "z_expanding": per_bar["z_expanding"], "half_life_rolling": per_bar["half_life_rolling_series"],
        "gap_flag_a": per_bar["gap_flag_a"], "gap_flag_b": per_bar["gap_flag_b"],
        "hedge_ratio_ols_t": per_bar.get("hedge_ratio_ols_t"),
        "hedge_ratio_kalman_t": per_bar.get("hedge_ratio_kalman_t"),
        "coint_fraction_rolling_t": per_bar.get("coint_fraction_rolling_t"),
        "half_life_trend_slope_t": per_bar.get("half_life_trend_slope_t"),
        "mean_reversion_speed_t": per_bar.get("mean_reversion_speed_t"),
        "hurst_rs_t": per_bar.get("hurst_rs_t"),
    }, index=per_bar["index"])
    portfolio_sim.register_spread_series(sym_a, sym_b, _TF_LABEL, spread_df[["spread"]])
    test_slice = spread_df.loc[(spread_df.index >= test_start) & (spread_df.index <= test_end)]
    if len(test_slice) < 30:
        return [], {}

    pair_row = pd.Series({
        **vars(full_pair_result),
        "coint_fraction_rolling": getattr(pair_result, "coint_fraction_rolling", np.nan),
        "half_life_trend_slope": getattr(pair_result, "half_life_trend_slope", np.nan),
        "mean_reversion_speed": getattr(pair_result, "mean_reversion_speed", np.nan),
        "hurst_rs": getattr(pair_result, "hurst_rs", np.nan),
        "tf_label": _TF_LABEL,
    })
    engine = BacktestEngine(cfg=Config.BACKTEST, regime_cond=RegimeConditioner(enabled=False),
                             ml_cond=MLConditioner(enabled=False))
    trades = engine.run(pair_row, test_slice, hedge_method="ols", holdout_only=False)
    metrics = compute_metrics(trades, _TF_LABEL, sym_a, sym_b, "ols") if trades else {}
    return trades, metrics


def run_fold(universe: Dict[str, pd.DataFrame], fold_dates: Dict, wfa_variant: str, n_workers: int
             ) -> Tuple[List[Dict], Dict, List[Dict], List]:
    label = fold_dates["label"]
    log.info(f"[{wfa_variant}/{label}] screening train window [{fold_dates['train_start'].date()}, "
             f"{fold_dates['train_end'].date()}] (point-in-time, no test-period data used)...")
    t0 = time.time()
    confirmed = screen_universe_at_cutoff(universe, fold_dates["train_start"], fold_dates["train_end"], n_workers)
    log.info(f"[{wfa_variant}/{label}] {len(confirmed)} pairs point-in-time confirmed "
             f"({(time.time()-t0)/60:.1f} min)")

    pair_set_rows = [
        {"wfa_variant": wfa_variant, "fold": label, "symbol_a": p.symbol_a, "symbol_b": p.symbol_b,
         "coint_fraction_rolling": p.coint_fraction_rolling, "half_life_rolling": p.half_life_rolling}
        for p in confirmed
    ]

    all_trades, all_metrics = [], []
    for p in confirmed:
        trades, metrics = backtest_pair_on_test_window(
            p, universe, fold_dates["train_start"], fold_dates["test_start"], fold_dates["test_end"]
        )
        if trades:
            all_trades.extend(trades)
            if metrics:
                all_metrics.append(metrics)

    portfolio_stats = aggregate_portfolio(all_trades, all_metrics)
    portfolio_stats.update({
        "wfa_variant": wfa_variant, "fold": label,
        "n_pit_confirmed_pairs": len(confirmed), "n_pairs_with_trades": len(all_metrics),
    })
    log.info(f"[{wfa_variant}/{label}] backtest: {len(all_metrics)} pairs traded, "
             f"{len(all_trades)} trades, portfolio Sharpe={portfolio_stats.get('sharpe_portfolio', float('nan')):.4f}")
    return all_metrics, portfolio_stats, pair_set_rows, all_trades


def trades_to_replay_df(trades: List) -> pd.DataFrame:
    """Converts a list of backtest.py Trade dataclass instances into the
    plain DataFrame shape portfolio_sim.py's replay_portfolio() requires
    (symbol_a, symbol_b, tf, entry_time, exit_time, entry_spread, entry_z,
    half_life_at_entry, side, n_shares_a, n_shares_b, pnl_net) -- Trade
    already carries every one of these fields directly (dataclasses.asdict,
    not a re-derivation), so this is pure reshaping, no new computation."""
    import dataclasses
    if not trades:
        return pd.DataFrame(columns=["symbol_a", "symbol_b", "tf", "entry_time", "exit_time",
                                      "entry_spread", "entry_z", "half_life_at_entry", "side",
                                      "n_shares_a", "n_shares_b", "pnl_net"])
    return pd.DataFrame([dataclasses.asdict(t) for t in trades])


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Point-in-time portfolio-wide WFA (WRDS daily, full universe)")
    parser.add_argument("--workers", type=int, default=Config.RUNTIME.N_WORKERS)
    parser.add_argument("--variant", choices=["expanding", "rolling", "both"], default="both")
    # Capital-constrained, risk-managed measurement (2026-09-03, Ross: "for the trades make
    # sure capital constraints also apply, and measure using per risk management optimization
    # style") -- reuses portfolio_sim.py's replay_portfolio() directly, the SAME machinery
    # backtest.py's own --capital-sim flag already uses elsewhere in this project, not a new
    # implementation. Matches CLAUDE.md's own standing rule: "Portfolio-level, capital-
    # constrained (--capital-sim) PIT backtest results are the headline over per-pair
    # backtests" -- reported as the PRIMARY result here (not opt-in/additive the way
    # backtest.py's CLI treats it), since this whole script exists specifically to produce a
    # corrected-scale headline number, not a per-pair diagnostic.
    parser.add_argument("--capital-account-size", type=float, default=100_000)
    parser.add_argument("--capital-sizing", default="flat_2pct",
                         choices=["fixed", "equity_proportional", "flat_2pct",
                                  "quarter_kelly", "third_kelly", "half_kelly", "full_kelly"],
                         help="Risk-based sizing off the causal stop-distance estimate "
                              "(default: flat_2pct -- a real risk-management method, not the "
                              "naive 'fixed' notional-per-trade convention).")
    parser.add_argument("--concentration-cap", type=float, default=Config.BACKTEST.MAX_CONCENTRATION_PCT,
                         help="Max fraction of current equity in any single position. Defaults "
                              "to Config.BACKTEST.MAX_CONCENTRATION_PCT (0.20) -- a value this "
                              "project's own config.py already declares but which was, until "
                              "this script, never actually enforced anywhere (backtest.py's own "
                              "CLI still defaults to None, matching its own per-pair, "
                              "capital-unaware design; this script's whole purpose is a "
                              "portfolio-level, capital-constrained headline number, so a real "
                              "cap belongs here). Real finding, 2026-09-03 (Ross's call after "
                              "confirming 0/21 trades taken was a genuine capital-scale effect, "
                              "not a bug -- see Finding #47): uncapped flat_2pct risk sizing can "
                              "demand a position notional far larger than the account can fund "
                              "when a pair's risk-per-share estimate is small, rejecting the "
                              "trade outright at the 5% min_size_scale floor instead of "
                              "partially funding it. Pass None to restore the uncapped default.")
    args = parser.parse_args()

    _setup_logging()
    t0 = time.time()
    log.info("=== pit_wfa_wrds_daily.py: Point-In-Time Portfolio-Wide Walk-Forward Analysis "
             "(WRDS daily, full merged universe) ===")
    log.info("Comparison arm to pit_wfa.py's own 1h/~1,580-symbol result -- NOT a replacement, "
             "a genuinely different scale/granularity test. See PAPER_MAGNITUDE.md §4/§8 for "
             "why 1h can never reach this scale (WRDS has no intraday data at all).")

    # columns=["close"] (2026-09-03, proactive, per a real DOCUMENTED near-miss in
    # universe_loader.py's own load_full_universe() docstring: loading all ~44,840 symbols'
    # full OHLCV once already pushed this project's machine to within ~600MB of an OOM crash
    # -- close-only is ~17% of a row's memory, and every downstream step here (correlation,
    # EG, spread construction) only ever reads close, matching every other current caller of
    # this loader per its own docstring's own audit).
    universe = load_universe_wrds_daily(columns=["close"])
    log.info(f"Universe: {len(universe)} symbols with daily data (WRDS-primary merged universe)")
    start, end = determine_analysis_window(universe)
    log.info(f"Analysis window: [{start.date()}, {end.date()}]")

    variants = []
    if args.variant in ("expanding", "both"):
        variants.append(("expanding", FOLD_EXPANDING))
    if args.variant in ("rolling", "both"):
        variants.append(("rolling", FOLD_ROLLING))

    import portfolio_sim

    os.makedirs(_OUT_DIR, exist_ok=True)
    fold_metric_rows, portfolio_rows, pair_set_rows, capital_sim_rows = [], [], [], []
    taken_trade_rows = []  # per-fold capital-constrained realized trades (exit_time, actual_pnl)
    # -- added 2026-09-08 for equity-curve stitching (PAPER_MAGNITUDE.md §10's open
    # pooled-headline-Sharpe item): replay_portfolio() already computes this per fold but the
    # prior version of this script discarded it after extracting summary metrics, matching
    # Development.md's own note that a genuine pooled figure "would need equity-curve
    # stitching... not built here" -- this is that missing persistence step, not a new metric.
    for wfa_variant, fold_specs in variants:
        for fold_spec in fold_specs:
            fold_dates = compute_fold_dates(start, end, fold_spec)
            metrics, portfolio_stats, pair_sets, trades = run_fold(universe, fold_dates, wfa_variant, args.workers)
            fold_metric_rows.extend(metrics)
            portfolio_rows.append(portfolio_stats)
            pair_set_rows.extend(pair_sets)

            label = fold_dates["label"]
            if trades:
                trades_df = trades_to_replay_df(trades)
                replay = portfolio_sim.replay_portfolio(
                    trades_df, starting_capital=args.capital_account_size,
                    sizing_method=args.capital_sizing, concentration_cap=args.concentration_cap,
                )
                cs_sharpe = portfolio_sim.portfolio_sharpe_from_replay(replay)
                cs_dd = portfolio_sim.max_drawdown_pct(replay["equity_curve"])
                cs_pf = portfolio_sim.profit_factor_from_replay(replay)
                cs_pdr = portfolio_sim.pdr_from_replay(replay)

                taken_df = replay["taken"]
                if taken_df is not None and len(taken_df):
                    fold_taken = taken_df[["exit_time", "actual_pnl"]].copy()
                    fold_taken["wfa_variant"] = wfa_variant
                    fold_taken["fold"] = label
                    taken_trade_rows.append(fold_taken)
                log.info(f"[{wfa_variant}/{label}] CAPITAL-CONSTRAINED ({args.capital_sizing}, "
                         f"${args.capital_account_size:,.0f} account): {len(replay['taken'])}/"
                         f"{len(trades)} trades taken, Sharpe={cs_sharpe:.4f}, max_dd={cs_dd:.2%}, "
                         f"profit_factor={cs_pf:.4f}, PDR={cs_pdr:.4f}")
                capital_sim_rows.append({
                    "wfa_variant": wfa_variant, "fold": label,
                    "sizing_method": args.capital_sizing,
                    "starting_capital": args.capital_account_size,
                    "n_trades_raw": len(trades), "n_trades_taken": len(replay["taken"]),
                    "n_trades_skipped": len(trades) - len(replay["taken"]),
                    "sharpe_capital_constrained": cs_sharpe, "max_drawdown_pct": cs_dd,
                    "profit_factor": cs_pf, "pdr": cs_pdr,
                    "sharpe_unconstrained": portfolio_stats.get("sharpe_portfolio", float("nan")),
                })
            else:
                capital_sim_rows.append({
                    "wfa_variant": wfa_variant, "fold": label, "sizing_method": args.capital_sizing,
                    "starting_capital": args.capital_account_size, "n_trades_raw": 0,
                    "n_trades_taken": 0, "n_trades_skipped": 0,
                    "sharpe_capital_constrained": float("nan"), "max_drawdown_pct": float("nan"),
                    "profit_factor": float("nan"), "pdr": float("nan"),
                    "sharpe_unconstrained": float("nan"),
                })

    _merge_and_save(pd.DataFrame(fold_metric_rows), os.path.join(_OUT_DIR, "pit_wfa_wrds_daily_fold_comparison.parquet"))
    _merge_and_save(pd.DataFrame(portfolio_rows), os.path.join(_OUT_DIR, "pit_wfa_wrds_daily_portfolio.parquet"))
    _merge_and_save(pd.DataFrame(pair_set_rows), os.path.join(_OUT_DIR, "pit_wfa_wrds_daily_pair_sets.parquet"))
    _merge_and_save(pd.DataFrame(capital_sim_rows), os.path.join(_OUT_DIR, "pit_wfa_wrds_daily_capital_sim.parquet"))
    if taken_trade_rows:
        _merge_and_save(pd.concat(taken_trade_rows, ignore_index=True),
                         os.path.join(_OUT_DIR, "pit_wfa_wrds_daily_taken_trades.parquet"))
    log.info(f"pit_wfa_wrds_daily.py complete in {(time.time()-t0)/60:.1f} min")


def _merge_and_save(new_df: pd.DataFrame, path: str) -> None:
    """Merges this run's rows into the existing parquet at `path` instead of overwriting it --
    real data-loss bug found live (2026-09-04): running `--variant expanding` then, in a SEPARATE
    invocation, `--variant rolling` silently destroyed expanding's saved parquet output (fixed
    output filenames, no variant suffix) even though both variants' real numbers had already been
    logged and manually recovered from the log files. Keyed on (wfa_variant, fold) -- every one of
    these 4 output dataframes carries both columns -- so re-running the SAME variant still
    correctly replaces its own prior rows (no duplication), while a DIFFERENT variant's rows are
    preserved rather than dropped."""
    if len(new_df) == 0:
        return
    if os.path.exists(path):
        old_df = pd.read_parquet(path)
        key_cols = [c for c in ("wfa_variant", "fold") if c in new_df.columns]
        if key_cols:
            new_keys = new_df[key_cols].drop_duplicates()
            old_df = old_df.merge(new_keys, on=key_cols, how="left", indicator=True)
            old_df = old_df[old_df["_merge"] == "left_only"].drop(columns=["_merge"])
        new_df = pd.concat([old_df, new_df], ignore_index=True)
    new_df.to_parquet(path)


if __name__ == "__main__":
    main()
