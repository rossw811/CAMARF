"""
research/strategy_variation_comparison.py -- Ross's direct request (2026-07-21):
does the stat-arb (cointegrated-spread) structure itself carry the edge, or
would the SAME entry/exit/risk-management engine produce comparable
risk-adjusted returns applied to single assets, using generic strategy
archetypes (breakout, trend-following DCA, single-asset mean reversion),
with everything else (position sizing, cost model, metrics) held constant? A
placebo/confound test in the spirit of Aronson's data-mining-bias framework
(dedicated_pass.md sec 11.4, not yet built) and this session's own
filter-relevance sweep.

Population: the SAME 20 (pair, timeframe) rows already used by
research/descriptive_check_concordance.py -- every row across all 12
timeframes' all_candidates.parquet (the EG+FDR+price-degeneracy survivor
population; BUG-D95's fix is what makes this visible for every TF, not just
the 2 final confirmed pairs). Reusing this exact population, rather than
picking a new universe, keeps the comparison anchored to the same underlying
names/timeframes already under investigation this session.

STAT-ARB ARM: reuses backtest.py's REAL BacktestEngine.run() UNCHANGED, on
each pair's own persisted spread_series_{A}_{B}.parquet (BUG-D95's fix is
what makes this exist for every one of the 20 rows). Same
ENTRY_ZSCORE/EXIT_ZSCORE/STOP_ZSCORE/MAX_HOLD_MULTIPLIER production
defaults, same N_SHARES_PER_TRADE flat sizing, same commission/slippage
model (_compute_cost) as every other arm here.

NO-STAT-ARB ARM: three NEW single-asset strategies (not present in
backtest.py, which is architected entirely around two-leg spreads), reusing
backtest.py's Trade dataclass (symbol_b="", hedge_ratio=1.0, n_shares_b=0.0
-- a single-asset trade is a degenerate 2-leg trade with a zero-weight
second leg), compute_metrics() (duck-types on Trade's pnl_net/mae/mfe/
hold_bars/exit_reason fields only -- symbol_b/hedge_ratio aren't read by it),
and _compute_cost() (hedge=0.0 reduces its formula to a single-leg cost
model) completely UNCHANGED -- so any Sharpe difference between arms is
attributable to the SIGNAL, not to a different cost/sizing/metrics
convention.

  - breakout: Donchian-channel style. Entry when close breaks the N-bar
    rolling high/low (N=20, a standard, non-tuned breakout window -- not
    picked to flatter this comparison). Exit: trailing stop (TRAIL_PCT=0.02,
    matching config.py's own existing COARSE_TRAIL_PCT vocabulary) or a
    MAX_HOLD_BARS cap.
  - dca_trend: scheduled entries every DCA_INTERVAL_BARS bars, gated to fire
    ONLY while a trend filter is active (close > rolling SMA, window
    TREND_SMA_WINDOW) -- Ross's own specification ("trend following for the
    DCA"). Exit: ALL open DCA trades close together the moment the trend
    filter flips (close crosses below the SMA) -- a trend-following exit,
    not a per-trade stop. Multiple overlapping open trades are expected and
    intentional (this is what makes it "DCA" rather than a single-position
    strategy).
  - mean_reversion: single-asset Bollinger-Band-style z-score, reusing
    analysis.py's SpreadModel.rolling_zscore() UNCHANGED (treating the
    asset's own log price as the "spread") with a FIXED window (MR_ZSCORE_
    WINDOW=20, matching MLConfig's own existing BBANDS_PERIOD=20) --
    deliberately NOT SpreadModel's half_life_ar1-driven adaptive window,
    since that estimator assumes the input series is itself stationary;
    individual equity log-prices generally are NOT (approximately a random
    walk), unlike a cointegrated pair spread, which is specifically
    constructed to be -- forcing the adaptive estimator onto raw
    single-asset price would silently return NaN/degenerate windows for
    most names rather than a meaningful comparison. Same ENTRY_ZSCORE/
    EXIT_ZSCORE/STOP_ZSCORE thresholds as the stat-arb arm -- the tightest
    apples-to-apples test, since it holds the risk-management RULE
    (z-score in/out/stop) constant and varies only whether z is measured on
    a spread or a single price series.

Gap-awareness: legs loaded via research/aligned_pair_loader.
load_aligned_symbols() (gap_flag-aware, matches production's DataAligner
convention); DATA_GAP bars (GapFlag.DATA_GAP=4) are masked to NaN before any
signal is computed, matching this session's established convention.

Honest scope notes, stated up front:
  - n=20 (pair, TF) rows -> up to 40 unique (symbol, TF) legs. Each arm's
    aggregate Sharpe pools trades across a THIN, already-selected-for-
    cointegration set of underlying names -- these are not a random/
    representative sample of the broader universe, they were selected
    BECAUSE their spread was correlated/cointegrated, so even the
    "no stat arb" arm is being tested on a name selection biased toward
    pairs, not a neutral universe. Reported as a limitation, not silently
    ignored.
  - Strategy parameters (breakout window, trail pct, DCA interval/trend
    window, MR z-score window) are single, reasonable, commonly-used
    values, NOT optimized/grid-searched -- this is deliberately a
    first-pass comparison, not a claim that no single-asset
    parameterization could ever match the stat-arb arm's Sharpe.
  - "DCA" here means Ross's specified trend-following-gated scheduled-entry
    variant, not classic unconditional periodic accumulation.

Verified against synthetic ground truth first:
debug/_verify_strategy_variation_comparison.py.

Usage:
    python research/strategy_variation_comparison.py
"""
import glob
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data import GapFlag
from backtest import (
    Trade, BacktestEngine, RegimeConditioner, MLConditioner,
    _load_spread, _compute_cost, compute_metrics,
)
from aligned_pair_loader import load_aligned_symbols

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

log = logging.getLogger("strategy_variation_comparison")

# --- Single-asset strategy parameters (deliberately simple, not tuned) ---
N_BREAKOUT = 20
TRAIL_PCT = 0.02
BREAKOUT_MAX_HOLD_BARS = 60

DCA_INTERVAL_BARS = 10
TREND_SMA_WINDOW = 50

MR_ZSCORE_WINDOW = 20
MR_MAX_HOLD_BARS = 60

_BT = Config.BACKTEST


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_strategy_variation_comparison.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_all_candidates():
    frames = []
    for f in sorted(glob.glob(os.path.join(_RESULTS_DIR, "*", "all_candidates.parquet"))):
        if "_stale_" in f:
            continue
        df = pd.read_parquet(f)
        df["_source_dir"] = os.path.basename(os.path.dirname(f))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _clean_close(df: pd.DataFrame) -> pd.Series:
    """DATA_GAP bars DROPPED entirely (not just NaN-masked), returning a
    compact real-bars-only series. Confirmed directly (2026-07-21): the
    aligned "1h" grid from DataAligner.align_universe is DENSE, with the
    large majority of rows genuinely DATA_GAP padding (e.g. PNC@1h: 26,214
    total rows, only 4,479 real -- gap_flag==0 count matches the raw cache's
    own row count exactly, and 26,214 matches production's own persisted
    n_bars/n_overlap for this exact pair at 1h, confirming this dense-grid-
    with-mostly-padding shape is genuine production behavior, not a bug in
    this script's loading path). NaN-masking alone (leaving the dense index
    intact) starves every rolling-window computation below: a 20-row
    positional window drawn from a 26,214-row frame where ~83% of rows are
    gap-padding almost never contains 20 consecutive valid values, so
    rolling max/min/z-score would be NaN almost everywhere and no strategy
    would ever produce a trade. Dropping the gap rows first (matching how
    analysis.py's own SpreadModel functions are always called on an
    already-compacted real-bar array, never a dense gapped grid) is
    required for the rolling-window logic below to see real bars as
    positionally adjacent, exactly as production's own EG/correlation code
    does via its own real-bar compaction before any rolling computation."""
    close = df["close"].astype(float).copy()
    if "gap_flag" in df.columns:
        close = close[df["gap_flag"] != GapFlag.DATA_GAP]
    return close


def _make_trade(symbol, tf_label, strategy, side, entry_i, entry_price,
                 exit_i, exit_price, index, exit_reason, excursions):
    n_shares = _BT.N_SHARES_PER_TRADE
    sign = 1.0 if side == "long" else -1.0
    pnl_gross = sign * (exit_price - entry_price) * n_shares
    cost = _compute_cost(entry_price, 0.0, n_shares, _BT.COMMISSION_PER_SHARE, _BT.SLIPPAGE_BPS)
    pnl_net = pnl_gross - cost
    mae = float(min(excursions)) if excursions else 0.0
    mfe = float(max(excursions)) if excursions else 0.0
    return Trade(
        tf=tf_label, symbol_a=symbol, symbol_b="", hedge_method=strategy, hedge_ratio=1.0,
        entry_time=index[entry_i], entry_z=np.nan, entry_spread=float(entry_price), side=side,
        n_shares_a=n_shares, n_shares_b=0.0,
        half_life_at_entry=np.nan, hurst_at_entry=np.nan,
        exit_time=index[exit_i], exit_z=np.nan, exit_spread=float(exit_price), exit_reason=exit_reason,
        pnl_gross=pnl_gross, pnl_cost=cost, pnl_net=pnl_net,
        mae=mae, mfe=mfe, hold_bars=exit_i - entry_i,
    )


def run_breakout(symbol: str, tf_label: str, df: pd.DataFrame) -> list:
    close = _clean_close(df)
    n = len(close)
    if n < N_BREAKOUT + 10:
        return []
    roll_max = close.shift(1).rolling(N_BREAKOUT).max()
    roll_min = close.shift(1).rolling(N_BREAKOUT).min()

    trades = []
    in_pos = False
    side = entry_i = entry_price = peak = None
    excursions = []
    for i in range(N_BREAKOUT, n):
        c = close.iloc[i]
        if pd.isna(c):
            continue
        if not in_pos:
            if pd.isna(roll_max.iloc[i]) or pd.isna(roll_min.iloc[i]):
                continue
            if c > roll_max.iloc[i]:
                in_pos, side, entry_i, entry_price, peak, excursions = True, "long", i, c, c, [0.0]
            elif c < roll_min.iloc[i]:
                in_pos, side, entry_i, entry_price, peak, excursions = True, "short", i, c, c, [0.0]
        else:
            if side == "long":
                peak = max(peak, c)
                hit_stop = c <= peak * (1 - TRAIL_PCT)
                excursions.append(c - entry_price)
            else:
                peak = min(peak, c)
                hit_stop = c >= peak * (1 + TRAIL_PCT)
                excursions.append(entry_price - c)
            hold_bars = i - entry_i
            hit_max_hold = hold_bars >= BREAKOUT_MAX_HOLD_BARS
            is_last = i == n - 1
            if hit_stop or hit_max_hold or is_last:
                reason = "stop" if hit_stop else ("max_hold" if hit_max_hold else "eod")
                trades.append(_make_trade(symbol, tf_label, "breakout", side, entry_i,
                                           entry_price, i, c, close.index, reason, excursions))
                in_pos = False
    return trades


def run_dca_trend(symbol: str, tf_label: str, df: pd.DataFrame) -> list:
    close = _clean_close(df)
    n = len(close)
    if n < TREND_SMA_WINDOW + 10:
        return []
    sma = close.rolling(TREND_SMA_WINDOW).mean()
    above = close > sma

    trades = []
    open_entries = []  # list of (entry_i, entry_price)
    last_entry_i = -DCA_INTERVAL_BARS
    for i in range(TREND_SMA_WINDOW, n):
        c = close.iloc[i]
        if pd.isna(c) or pd.isna(sma.iloc[i]):
            continue
        trend_on = bool(above.iloc[i])
        trend_prev_on = bool(above.iloc[i - 1]) if i > 0 and not pd.isna(above.iloc[i - 1]) else trend_on

        # Scheduled entry, gated on trend filter being active
        if trend_on and (i - last_entry_i) >= DCA_INTERVAL_BARS:
            open_entries.append((i, c))
            last_entry_i = i

        # Trend-following exit: close ALL open entries the moment trend flips off
        exiting_now = trend_prev_on and not trend_on
        is_last = i == n - 1
        if (exiting_now or is_last) and open_entries:
            reason = "trend_exit" if exiting_now else "eod"
            for entry_i, entry_price in open_entries:
                seg = close.iloc[entry_i:i + 1]
                excursions = [0.0] + list((seg - entry_price).dropna().to_numpy())
                trades.append(_make_trade(symbol, tf_label, "dca_trend", "long", entry_i,
                                           entry_price, i, c, close.index, reason, excursions))
            open_entries = []
    return trades


def run_mean_reversion(symbol: str, tf_label: str, df: pd.DataFrame) -> list:
    from analysis import SpreadModel

    close = _clean_close(df)
    n = len(close)
    if n < MR_ZSCORE_WINDOW * 2:
        return []
    log_price = np.log(close.to_numpy(dtype=float))
    z = SpreadModel.rolling_zscore(log_price, MR_ZSCORE_WINDOW)

    trades = []
    in_pos = False
    side = entry_i = entry_price = None
    excursions = []
    for i in range(n):
        c = close.iloc[i]
        zi = z[i]
        if pd.isna(c) or not np.isfinite(zi):
            continue
        if not in_pos:
            if zi >= _BT.ENTRY_ZSCORE:
                in_pos, side, entry_i, entry_price, excursions = True, "short", i, c, [0.0]
            elif zi <= -_BT.ENTRY_ZSCORE:
                in_pos, side, entry_i, entry_price, excursions = True, "long", i, c, [0.0]
        else:
            if side == "long":
                excursions.append(c - entry_price)
            else:
                excursions.append(entry_price - c)
            hold_bars = i - entry_i
            signal_exit = (side == "long" and zi >= -_BT.EXIT_ZSCORE) or \
                          (side == "short" and zi <= _BT.EXIT_ZSCORE)
            stop_hit = abs(zi) >= _BT.STOP_ZSCORE and (
                (side == "long" and zi < 0) or (side == "short" and zi > 0)
            )
            max_hold = hold_bars >= MR_MAX_HOLD_BARS
            is_last = i == n - 1
            if signal_exit or stop_hit or max_hold or is_last:
                reason = "signal_exit" if signal_exit else (
                    "stop" if stop_hit else ("max_hold" if max_hold else "eod")
                )
                trades.append(_make_trade(symbol, tf_label, "mean_reversion", side, entry_i,
                                           entry_price, i, c, close.index, reason, excursions))
                in_pos = False
    return trades


def run_stat_arb(row: pd.Series) -> list:
    # Use the exact directory this candidate was actually loaded from
    # (row["_source_dir"], set by load_all_candidates()) rather than
    # re-deriving a tf_label -> tf_dir mapping -- avoids any risk of
    # mismatching a "_stale_"-suffixed archive naming quirk.
    sym_a, sym_b, tf_label = row["symbol_a"], row["symbol_b"], row["tf_label"]
    tf_dir = row["_source_dir"]
    spread_df = _load_spread(tf_dir, sym_a, sym_b)
    if spread_df is None:
        return []
    pair_row = pd.Series({
        "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
        "hedge_ratio_ols": row.get("hedge_ratio_ols", 1.0),
        "hedge_ratio_kalman_mean": row.get("hedge_ratio_kalman_mean", row.get("hedge_ratio_ols", 1.0)),
        "hurst_rs": row.get("hurst_rs", np.nan),
        "coint_fraction_rolling": row.get("coint_fraction_rolling", 1.0),
    })
    engine = BacktestEngine(_BT, RegimeConditioner(enabled=False), MLConditioner(enabled=False))
    return engine.run(pair_row, spread_df, hedge_method="ols")


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== strategy_variation_comparison.py: does the stat-arb structure carry the "
              "edge, or would generic single-asset strategies do as well on the same names? ===")

    candidates = load_all_candidates()
    log.info("Loaded %d (pair, tf) rows from all_candidates.parquet across all timeframes", len(candidates))
    if candidates.empty:
        log.warning("No candidates found -- aborting.")
        return

    # --- Arm 1: stat-arb (real BacktestEngine, unchanged) ---
    stat_arb_trades = []
    stat_arb_rows = []
    for _, row in candidates.iterrows():
        trades = run_stat_arb(row)
        stat_arb_trades.extend(trades)
        m = compute_metrics(trades, row["tf_label"], row["symbol_a"], row["symbol_b"], "ols")
        if m:
            m["arm"] = "stat_arb"
            stat_arb_rows.append(m)
        log.info("  [stat_arb] %s/%s@%s: %d trades", row["symbol_a"], row["symbol_b"], row["tf_label"], len(trades))

    # --- Arm 2: single-asset strategies, on every unique (symbol, tf) leg ---
    legs_by_tf = {}
    for _, row in candidates.iterrows():
        legs_by_tf.setdefault(row["tf_label"], set()).add(row["symbol_a"])
        legs_by_tf.setdefault(row["tf_label"], set()).add(row["symbol_b"])

    single_asset_trades = {"breakout": [], "dca_trend": [], "mean_reversion": []}
    single_asset_rows = []
    for tf_label, symbols in legs_by_tf.items():
        symbols = sorted(symbols)
        log.info("  Loading %d unique legs at %s via load_aligned_symbols (gap-flag-aware)...",
                  len(symbols), tf_label)
        aligned = load_aligned_symbols(symbols, tf_label)
        for sym in symbols:
            df = aligned.get(sym)
            if df is None or df.empty:
                log.warning("  [%s@%s] no aligned data -- skipping", sym, tf_label)
                continue
            for strat_name, strat_fn in [
                ("breakout", run_breakout), ("dca_trend", run_dca_trend), ("mean_reversion", run_mean_reversion),
            ]:
                trades = strat_fn(sym, tf_label, df)
                single_asset_trades[strat_name].extend(trades)
                m = compute_metrics(trades, tf_label, sym, "", strat_name)
                if m:
                    m["arm"] = strat_name
                    single_asset_rows.append(m)
                log.info("  [%s] %s@%s: %d trades", strat_name, sym, tf_label, len(trades))

    # --- Pooled (portfolio-level) comparison: pool ALL trades per arm, one Sharpe each ---
    # (pools trades across pairs/legs before computing Sharpe -- matches this
    # project's own established convention, BUG-D59/D90's fix, rather than
    # averaging per-pair/per-leg Sharpe-like ratios.)
    log.info("")
    log.info("=== Pooled comparison (all trades per arm pooled before computing one Sharpe each) ===")
    pooled_summary = []
    for arm_name, trades in [("stat_arb", stat_arb_trades), *single_asset_trades.items()]:
        if not trades:
            log.info("  %-16s: 0 trades", arm_name)
            continue
        # compute_metrics needs one tf_label; pooled across TFs is a real
        # limitation (bars-per-year annualization differs by TF) -- report
        # honestly using each trade's own tf via a per-TF pooled pass instead.
        by_tf = {}
        for t in trades:
            by_tf.setdefault(t.tf, []).append(t)
        for tf_label, tf_trades in by_tf.items():
            m = compute_metrics(tf_trades, tf_label, arm_name, "", "pooled")
            if m:
                m["arm"] = arm_name
                pooled_summary.append(m)
                log.info("  %-16s @ %-4s: n=%-4d sharpe=%-8s profit_factor=%-8s win_rate=%s",
                          arm_name, tf_label, m["n_trades"], m.get("sharpe"), m.get("profit_factor"), m.get("win_rate"))

    os.makedirs(_OUT_DIR, exist_ok=True)
    pd.DataFrame(stat_arb_rows + single_asset_rows).to_parquet(
        os.path.join(_OUT_DIR, "strategy_variation_comparison_per_pair.parquet"), index=False
    )
    pd.DataFrame(pooled_summary).to_parquet(
        os.path.join(_OUT_DIR, "strategy_variation_comparison_pooled.parquet"), index=False
    )
    log.info("Saved -> output/research/strategy_variation_comparison_{per_pair,pooled}.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("strategy_variation_comparison.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
