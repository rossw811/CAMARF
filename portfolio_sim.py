"""
portfolio_sim.py — capital-constrained, chronologically-interleaved portfolio replay,
mark-to-market equity.

Addresses BUG-D60 (Development.md, 2026-07-12): `backtest.py`'s BacktestEngine processes each
pair in complete isolation, so the reported portfolio Sharpe implicitly assumes unlimited
capital — every signal gets taken at full size regardless of how many other positions are
already open. Confirmed directly: peak 27 concurrent positions, $421,252 real notional required
at the single worst moment, never checked against any account size.

This module does NOT touch BacktestEngine's entry/exit signal-generation logic at all — that
logic is already validated (synthetic tests, real-data runs throughout this project's history)
and duplicating/modifying it here would risk drift and lookahead bugs. Instead, it takes the
trades BacktestEngine ALREADY produced (the full, capital-unconstrained trade list already in
`output/backtest/trades_layer1*.parquet`) and replays them chronologically as a genuine
event-driven simulation.

Equity is tracked MARK-TO-MARKET (Ross's direction, 2026-07-12: "unrealized P&L rather than
realized - only if it's logically sensible" — it is: real margin accounts size new positions off
current marked equity, not just realized-to-date P&L). At every entry-candidate timestamp:
  1. Settle (realize) any positions that have actually closed by this timestamp.
  2. Mark every STILL-open position to market using the SAME P&L formula BacktestEngine's own
     `_close_trade()` uses (`direction * (current_spread - entry_spread) * n_shares_a`, pulled
     from real spread_series data at this timestamp, gross/pre-cost since exit costs aren't
     paid until actually closed) -- current_equity = realized_equity + sum(unrealized P&L).
  3. Committed capital (margin held) for each open position stays at its ORIGINAL sizing basis
     (unrealized gains don't free up margin; unrealized losses don't add HELD margin -- both do
     flow through current_equity in step 2, which is what actually gates new entries).
  4. available = current_equity - committed_capital. A signal that can't be fully funded is
     downsized (scaled to whatever's available) or skipped entirely if nothing remains.

Two sizing methods:
  - "fixed": try to take every trade at its ORIGINAL size (matches BacktestEngine's fixed
    N_SHARES_PER_TRADE) — isolates the pure capital-constraint effect.
  - "equity_proportional": target size scales linearly with CURRENT mark-to-market equity
    relative to starting capital (Ross's day-1-$10k/day-10-$15k example).

NOT implemented this pass, flagged rather than rushed: flat_2pct/half_kelly/full_kelly
(`Config.BACKTEST.SIZING_METHODS`, long-defined in config.py, never implemented anywhere) need a
real stop-distance-in-dollars risk model — estimating that without lookahead requires rolling
spread volatility AT ENTRY TIME, not yet built. See Development.md for the phasing decision.

Usage:
    python portfolio_sim.py --account-size 100000 --sizing fixed
    python portfolio_sim.py --account-size 1000000 --sizing equity_proportional
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

log = logging.getLogger("portfolio_sim")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_ROOT, "output", "cache")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")

# Mirrors ml.py's _TF_SAFE -- duplicated rather than imported, same rationale (avoid pulling in
# unrelated import chains for a small, stable lookup table).
_TF_SAFE = {
    "1m": "1min", "2m": "2min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1hr", "4h": "4hr", "1D": "1day", "7D": "7day", "1M": "1mo", "3M": "3mo", "6M": "6mo",
}

_price_cache = {}
_spread_cache = {}


def get_price_at(symbol: str, ts: pd.Timestamp) -> float:
    """Last available 1h close price for symbol AT OR BEFORE ts (method="pad", not "nearest" --
    "nearest" could pick a bar slightly AFTER ts, a lookahead crack for a sizing/risk decision
    made at ts. Fixed 2026-07-12 while building the causal volatility model below, which made
    this matter more directly than it did for the simpler original notional-at-entry use.)."""
    if symbol not in _price_cache:
        path = os.path.join(_CACHE_DIR, f"{symbol}_1hr.parquet")
        try:
            _price_cache[symbol] = pd.read_parquet(path)
        except Exception:
            _price_cache[symbol] = None
    df = _price_cache[symbol]
    if df is None or len(df) == 0 or "close" not in df.columns:
        return float("nan")
    idx = df.index.get_indexer([ts], method="pad")[0]
    if idx < 0:
        return float("nan")
    return float(df.iloc[idx]["close"])


def _load_spread_series(symbol_a: str, symbol_b: str, tf_label: str) -> "pd.DataFrame | None":
    key = (symbol_a, symbol_b, tf_label)
    if key not in _spread_cache:
        tf_dir = _TF_SAFE.get(tf_label, tf_label.lower())
        path = os.path.join(_RESULTS_DIR, tf_dir, f"spread_series_{symbol_a}_{symbol_b}.parquet")
        try:
            _spread_cache[key] = pd.read_parquet(path)[["spread"]]
        except Exception:
            _spread_cache[key] = None
    return _spread_cache[key]


def get_spread_at(symbol_a: str, symbol_b: str, tf_label: str, ts: pd.Timestamp) -> float:
    """Last available spread value for this pair AT OR BEFORE ts (method="pad" -- see
    get_price_at's docstring for why "nearest" is a lookahead risk here)."""
    df = _load_spread_series(symbol_a, symbol_b, tf_label)
    if df is None or len(df) == 0:
        return float("nan")
    idx = df.index.get_indexer([ts], method="pad")[0]
    if idx < 0:
        return float("nan")
    return float(df.iloc[idx]["spread"])


# ---------------------------------------------------------------------------
# Causal rolling spread volatility -- for stop-distance risk-based sizing
# (flat_2pct / half_kelly / full_kelly). Config.BACKTEST.SIZING_METHODS has
# existed since the project's original design phase, never implemented
# anywhere until this build (2026-07-12).
# ---------------------------------------------------------------------------
_ADAPTIVE_WINDOW_MULT = 8      # matches analysis.py's OU_WINDOW_HALFLIFE_MULT_MEAN
_ADAPTIVE_WINDOW_MIN = 30      # matches analysis.py's OU_WINDOW_MIN_BARS
_ADAPTIVE_WINDOW_MAX = 252     # matches analysis.py's OU_LOOKBACK_DAYS
STOP_ZSCORE = 3.5              # matches Config.BACKTEST.STOP_ZSCORE

_rolling_std_cache = {}


def _adaptive_window(half_life: float) -> int:
    """Exact replica of analysis.py's SpreadModel._adaptive_window, same constants — the window
    a stop-distance estimate uses must match the SAME window z_rolling itself was computed with,
    or "how far to the stop in z-units" and "current spread volatility" would be measuring two
    different things."""
    if not np.isfinite(half_life) or half_life <= 0:
        return _ADAPTIVE_WINDOW_MAX
    return int(np.clip(round(_ADAPTIVE_WINDOW_MULT * half_life), _ADAPTIVE_WINDOW_MIN, _ADAPTIVE_WINDOW_MAX))


def causal_rolling_std_at_entry(symbol_a: str, symbol_b: str, tf_label: str,
                                 entry_time: pd.Timestamp, half_life: float) -> float:
    """Causal (trailing-window, no lookahead) spread standard deviation AT entry_time, using
    ONLY bars up to and including entry_time -- pandas' own `.rolling()` is causal by
    construction, and indexing with method="pad" guarantees the bar used is at or before
    entry_time, never after."""
    df = _load_spread_series(symbol_a, symbol_b, tf_label)
    if df is None or len(df) == 0:
        return float("nan")
    window = _adaptive_window(half_life)
    cache_key = (symbol_a, symbol_b, tf_label, window)
    if cache_key not in _rolling_std_cache:
        _rolling_std_cache[cache_key] = df["spread"].rolling(
            window, min_periods=max(2, window // 2)
        ).std(ddof=1)
    rolling_std = _rolling_std_cache[cache_key]
    idx = df.index.get_indexer([entry_time], method="pad")[0]
    if idx < 0:
        return float("nan")
    return float(rolling_std.iloc[idx])


def stop_distance_dollars_per_share(entry_z: float, entry_spread: float, symbol_a: str,
                                     symbol_b: str, tf_label: str, entry_time: pd.Timestamp,
                                     half_life: float) -> float:
    """Estimated dollar P&L, per share of leg A, if this trade were stopped out at
    Config.BACKTEST.STOP_ZSCORE -- entirely from information available AT entry_time (causal).
    Uses the SAME (current_spread - entry_spread) formula BacktestEngine._close_trade() uses
    for real P&L, just evaluated at the STOP z-level instead of the actual exit, via the
    causal rolling std to convert z-distance into spread-price distance. Returns NaN if
    volatility can't be estimated (insufficient history) -- callers must handle this (fall back
    to a default sizing method, per Development.md's documented "60+ trades" / early-period
    bias convention, never silently treat NaN as zero risk)."""
    sigma = causal_rolling_std_at_entry(symbol_a, symbol_b, tf_label, entry_time, half_life)
    if not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(entry_z):
        return float("nan")
    z_distance_to_stop = STOP_ZSCORE - abs(entry_z)
    if z_distance_to_stop <= 0:
        return float("nan")  # already past the stop level -- shouldn't happen for a real entry
    return z_distance_to_stop * sigma


def notional_at_entry(trade: dict) -> float:
    """Real dollar notional (both legs) at this trade's entry — pulled from real cached
    prices, not estimated."""
    pa = get_price_at(trade["symbol_a"], trade["entry_time"])
    pb = get_price_at(trade["symbol_b"], trade["entry_time"])
    na = trade["n_shares_a"] * pa if np.isfinite(pa) else 0.0
    nb = trade["n_shares_b"] * pb if np.isfinite(pb) else 0.0
    return na + nb


def unrealized_pnl(pos: dict, ts: pd.Timestamp) -> float:
    """Mark-to-market P&L for a still-open position at ts, using the SAME formula
    BacktestEngine._close_trade() uses for the real (final) P&L: direction * (current_spread -
    entry_spread) * n_shares_a. Gross (pre-cost) -- exit costs aren't incurred until actually
    closed, so charging them into an interim mark would understate available margin."""
    current_spread = get_spread_at(pos["symbol_a"], pos["symbol_b"], pos["tf"], ts)
    if not np.isfinite(current_spread) or not np.isfinite(pos["entry_spread"]):
        return 0.0  # no data at this point -- treat as flat rather than crash/skew sizing
    direction = 1 if pos["side"] == "long" else -1
    return direction * (current_spread - pos["entry_spread"]) * pos["n_shares_a"] * pos["size_scale"]


_KELLY_MIN_TRADES = 60  # Development.md's own documented convention: Kelly estimate unreliable
                        # below 60 realized trades -- a bias, not silently corrected away
                        # (CLAUDE.md rule 6). Below this, Kelly methods fall back to flat_2pct.
_FLAT_RISK_PCT = 0.02   # "Fixed 2% risk" per the original Development.md sizing spec

# Kelly fraction multipliers. half_kelly/full_kelly were the original Development.md spec;
# quarter_kelly/third_kelly added 2026-07-12 per Ross's request. IMPORTANT, stated explicitly
# per Ross's own caveat: scanning across MORE Kelly fractions is itself another instance of the
# same multiple-comparison problem this whole session's DSR/holdout-exposure work is about --
# each additional fraction tested is one more "trial," and picking whichever fraction happens to
# look best after the fact would be exactly the Garden-of-Forking-Paths risk already flagged
# elsewhere. These are reported side by side as a comparison, not as a search for the best one.
_KELLY_MULTS = {"quarter_kelly": 0.25, "third_kelly": 1.0 / 3.0, "half_kelly": 0.5, "full_kelly": 1.0}


def _kelly_fraction(closed_pnls: list) -> float:
    """f* = win_rate - (1 - win_rate) / payoff_ratio (standard Kelly for a binary win/lose bet).
    Computed CAUSALLY from closed_pnls (only trades closed before the current entry candidate).
    Clipped at 0 -- a negative Kelly fraction means no edge, take no position, not a short."""
    if len(closed_pnls) < _KELLY_MIN_TRADES:
        return float("nan")
    pnls = np.array(closed_pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    if len(wins) == 0 or len(losses) == 0:
        return 0.0  # all-win or all-loss history -- no meaningful payoff ratio, don't extrapolate
    win_rate = len(wins) / len(pnls)
    payoff_ratio = wins.mean() / abs(losses.mean())
    if payoff_ratio <= 0:
        return 0.0
    f_star = win_rate - (1 - win_rate) / payoff_ratio
    return max(0.0, f_star)


def replay_portfolio(
    trades_df: pd.DataFrame,
    starting_capital: float,
    sizing_method: str = "fixed",
    min_size_scale: float = 0.05,
) -> dict:
    """
    Event-driven, capital-constrained, mark-to-market replay of an already-generated trade list.

    trades_df must have: symbol_a, symbol_b, tf, entry_time, exit_time, entry_spread, entry_z,
    half_life_at_entry, side, n_shares_a, n_shares_b, pnl_net (the ORIGINAL, capital-
    unconstrained P&L at original size).

    sizing_method: "fixed" | "equity_proportional" | "flat_2pct" | "half_kelly" | "full_kelly".
    The three risk-based methods size off the causal stop-distance estimate (see
    stop_distance_dollars_per_share) rather than scaling the original backtest.py share count.
    """
    trades = trades_df.sort_values("entry_time").copy()
    trades["notional_at_entry"] = trades.apply(lambda t: notional_at_entry(t), axis=1)
    records = trades.to_dict("records")

    realized_equity = starting_capital
    open_positions = []  # list of dicts: exit_time, actual_pnl (final), committed, + MTM fields
    taken = []
    skipped = 0
    n_kelly_fallback = 0  # count of trades that fell back to flat_2pct pending 60+ trade history
    n_skipped_no_risk_estimate = 0  # count skipped because entry_z already >= STOP_ZSCORE at
    # entry (real property of backtest.py's entry logic, confirmed 2026-07-12: 45% of real
    # trades enter with |entry_z| >= STOP_ZSCORE=3.5, since entry has no upper z-bound) --
    # tracked separately from capital-constrained skips, a different cause entirely.
    closed_pnls = []  # causal history of REALIZED pnl_net (original-size basis) for Kelly estimation
    equity_curve = [(trades["entry_time"].min() if len(trades) else pd.Timestamp.now(), realized_equity)]
    peak_concurrent_notional = 0.0
    peak_mtm_equity = realized_equity
    trough_mtm_equity = realized_equity

    for t in records:
        entry_time = t["entry_time"]

        # 1. Settle positions that have actually closed by this timestamp -- realize their
        # final P&L (already fixed at open-time via size_scale) into realized_equity, and
        # record the trade's ORIGINAL-size pnl_net into the causal Kelly history (using the
        # original-size basis, not the capital-scaled actual_pnl, so Kelly's win-rate/payoff
        # estimate reflects the strategy's own edge, not an artifact of past capital constraints).
        still_open = []
        for pos in open_positions:
            if pos["exit_time"] <= entry_time:
                realized_equity += pos["actual_pnl"]
                equity_curve.append((pos["exit_time"], realized_equity))
                closed_pnls.append(pos["original_pnl_net"])
            else:
                still_open.append(pos)
        open_positions = still_open

        # 2. Mark remaining open positions to market at this timestamp.
        mtm_unrealized = sum(unrealized_pnl(pos, entry_time) for pos in open_positions)
        current_equity = realized_equity + mtm_unrealized
        peak_mtm_equity = max(peak_mtm_equity, current_equity)
        trough_mtm_equity = min(trough_mtm_equity, current_equity)

        # 3. Committed capital stays at each open position's ORIGINAL sizing basis.
        committed_now = sum(pos["committed"] for pos in open_positions)
        available = max(0.0, current_equity - committed_now)

        original_notional = t["notional_at_entry"]
        if not np.isfinite(original_notional) or original_notional <= 0:
            skipped += 1
            continue

        used_kelly_fallback = False
        if sizing_method == "fixed":
            target_notional = original_notional
        elif sizing_method == "equity_proportional":
            target_notional = original_notional * (current_equity / starting_capital)
        elif sizing_method == "flat_2pct" or sizing_method in _KELLY_MULTS:
            risk_per_share = stop_distance_dollars_per_share(
                t.get("entry_z", float("nan")), t["entry_spread"], t["symbol_a"], t["symbol_b"],
                t["tf"], entry_time, t.get("half_life_at_entry", float("nan")),
            )
            if not np.isfinite(risk_per_share) or risk_per_share <= 0:
                skipped += 1
                n_skipped_no_risk_estimate += 1
                continue  # can't estimate risk causally -- skip rather than guess
            if sizing_method == "flat_2pct":
                risk_fraction = _FLAT_RISK_PCT
            else:
                f_star = _kelly_fraction(closed_pnls)
                if not np.isfinite(f_star):
                    risk_fraction = _FLAT_RISK_PCT  # fallback: <60 trades, per Development.md convention
                    used_kelly_fallback = True
                else:
                    risk_fraction = f_star * _KELLY_MULTS[sizing_method]
            if risk_fraction <= 0:
                skipped += 1
                continue  # zero/negative edge estimate -- Kelly says don't trade
            target_shares_a = (risk_fraction * current_equity) / risk_per_share
            price_a = get_price_at(t["symbol_a"], entry_time)
            price_b = get_price_at(t["symbol_b"], entry_time)
            hedge_ratio = t["n_shares_b"] / t["n_shares_a"] if t["n_shares_a"] else 1.0
            target_notional = (target_shares_a * price_a if np.isfinite(price_a) else 0.0) + \
                               (target_shares_a * hedge_ratio * price_b if np.isfinite(price_b) else 0.0)
            if target_notional <= 0:
                skipped += 1
                continue
        else:
            raise ValueError(f"unknown sizing_method: {sizing_method}")

        if used_kelly_fallback:
            n_kelly_fallback += 1

        size_scale = min(1.0, available / target_notional) if target_notional > 0 else 0.0
        if size_scale < min_size_scale:
            skipped += 1
            continue

        actual_notional = target_notional * size_scale
        actual_pnl = t["pnl_net"] * (actual_notional / original_notional)

        open_positions.append({
            "exit_time": t["exit_time"], "actual_pnl": actual_pnl, "committed": actual_notional,
            "symbol_a": t["symbol_a"], "symbol_b": t["symbol_b"], "tf": t["tf"],
            "entry_spread": t["entry_spread"], "side": t["side"], "n_shares_a": t["n_shares_a"],
            "size_scale": size_scale, "original_pnl_net": t["pnl_net"],
        })
        peak_concurrent_notional = max(peak_concurrent_notional, committed_now + actual_notional)
        taken.append({**t, "actual_notional": actual_notional, "actual_pnl": actual_pnl,
                       "size_scale": size_scale})

    # Drain remaining open positions at the end.
    for pos in sorted(open_positions, key=lambda p: p["exit_time"]):
        realized_equity += pos["actual_pnl"]
        equity_curve.append((pos["exit_time"], realized_equity))

    taken_df = pd.DataFrame(taken)
    equity_curve_df = pd.DataFrame(equity_curve, columns=["time", "equity"]).drop_duplicates("time")

    return {
        "taken": taken_df,
        "skipped_count": skipped,
        "n_taken": len(taken_df),
        "n_kelly_fallback": n_kelly_fallback,
        "n_skipped_no_risk_estimate": n_skipped_no_risk_estimate,
        "final_equity": realized_equity,
        "equity_curve": equity_curve_df,
        "peak_concurrent_notional": peak_concurrent_notional,
        "peak_mtm_equity": peak_mtm_equity,
        "trough_mtm_equity": trough_mtm_equity,
        "starting_capital": starting_capital,
        "sizing_method": sizing_method,
    }


def portfolio_sharpe_from_replay(result: dict) -> float:
    """Sharpe from the ACTUAL realized daily P&L this replay produced, pooled daily using the
    SAME convention as backtest.py's aggregate_portfolio() -- resample("1D").sum() on the P&L
    series indexed by exit_time, which fills every calendar day between the first and last exit
    with 0 P&L. This does NOT match a plain groupby(exit_date) over only the days that happen to
    have a realized exit (BUG-D62, Development.md 2026-07-13): the groupby-only convention this
    function originally used silently drops every zero-P&L calendar day, which understates N and
    materially overstates Sharpe. Confirmed directly: computing the FULL unconstrained trade set's
    Sharpe under groupby-only gives ~9.79, comparable to every "capital constraints raise Sharpe"
    figure previously reported for this function -- i.e. the entire effect was this convention
    mismatch, not a property of capital-constrained trading. Must match aggregate_portfolio() or
    any comparison against the unconstrained headline Sharpe is not apples-to-apples."""
    taken = result["taken"]
    if len(taken) == 0:
        return float("nan")
    exit_time = pd.to_datetime(taken["exit_time"])
    s = pd.Series(taken["actual_pnl"].values, index=pd.DatetimeIndex(exit_time)).sort_index()
    daily = s.resample("1D").sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def max_drawdown_pct(equity_curve_df: pd.DataFrame) -> float:
    """Max drawdown as a fraction of the running peak equity (standard convention: (peak-trough)/
    peak at the point of the deepest subsequent decline, not a single global min/max pair -- a
    global-min-vs-global-max reading would understate a real drawdown that happened before the
    series' eventual high). Computed from replay_portfolio()'s realized equity_curve (settled at
    each trade's exit_time), matching the same realized-P&L basis portfolio_sharpe_from_replay()
    and the Calmar/PDR functions below use -- not a continuous intra-trade MTM curve."""
    eq = equity_curve_df.sort_values("time")["equity"].values
    if len(eq) < 2:
        return float("nan")
    running_max = np.maximum.accumulate(eq)
    dd_pct = np.where(running_max > 0, (running_max - eq) / running_max, 0.0)
    return float(dd_pct.max())


def profit_factor_from_replay(result: dict) -> float:
    """Gross profit / |gross loss| on the ACTUAL (capital-scaled) realized P&L this replay
    produced -- same basis as portfolio_sharpe_from_replay(), not the original unconstrained size."""
    taken = result["taken"]
    if len(taken) == 0:
        return float("nan")
    pnl = taken["actual_pnl"].to_numpy()
    wins = pnl[pnl > 0].sum()
    losses = pnl[pnl <= 0].sum()
    return float(wins / abs(losses)) if losses != 0 else float("inf")


def pdr_from_replay(result: dict) -> float:
    """Profit-to-Drawdown Ratio = Profit Factor / Max Drawdown (%), per Ross's own framing
    ("a ratio between profit factor and dd"), 2026-07-13/14. Unitless, larger is better; a high
    profit factor with a small drawdown gives a large PDR, either a weak profit factor or a deep
    drawdown shrinks it. Comparison-metric only -- not the same construction as backtest.py's
    compute_metrics() 'calmar' field (total_pnl/max_dd in raw dollars, not this ratio)."""
    pf = profit_factor_from_replay(result)
    dd = max_drawdown_pct(result["equity_curve"])
    if not np.isfinite(pf) or not np.isfinite(dd) or dd <= 0:
        return float("nan")
    return pf / dd


def calmar_from_replay(result: dict) -> float:
    """Standard Calmar Ratio = Annualized Return / Max Drawdown (%). Uses the SAME resample("1D")
    daily-P&L annualization basis as portfolio_sharpe_from_replay()/aggregate_portfolio() (BUG-D62/
    D64 convention), not backtest.py compute_metrics()'s non-standard total_pnl/max_dd 'calmar'
    field, which is neither annualized nor drawdown-normalized the same way -- deliberately not
    reusing that name's existing computation, this is the textbook definition."""
    taken = result["taken"]
    if len(taken) == 0:
        return float("nan")
    exit_time = pd.to_datetime(taken["exit_time"])
    s = pd.Series(taken["actual_pnl"].to_numpy(), index=pd.DatetimeIndex(exit_time)).sort_index()
    daily = s.resample("1D").sum()
    if len(daily) < 5:
        return float("nan")
    starting_capital = result["starting_capital"]
    if starting_capital <= 0:
        return float("nan")
    total_return = result["final_equity"] / starting_capital - 1.0
    n_years = len(daily) / 252.0
    if n_years <= 0:
        return float("nan")
    base = 1.0 + total_return
    annualized_return = (base ** (1.0 / n_years) - 1.0) if base > 0 else float("nan")
    dd = max_drawdown_pct(result["equity_curve"])
    if not np.isfinite(annualized_return) or not np.isfinite(dd) or dd <= 0:
        return float("nan")
    return annualized_return / dd


def main():
    p = argparse.ArgumentParser(description="Capital-constrained, mark-to-market portfolio replay (BUG-D60)")
    p.add_argument("--account-size", type=float, default=100_000)
    p.add_argument("--sizing", choices=["fixed", "equity_proportional", "flat_2pct",
                                         "quarter_kelly", "third_kelly", "half_kelly", "full_kelly"],
                   default="fixed")
    p.add_argument("--trades-path", default="output/backtest/trades_layer1.parquet")
    args = p.parse_args()

    trades_df = pd.read_parquet(args.trades_path)
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])

    log.info("Replaying %d trades, starting capital $%.0f, sizing=%s",
              len(trades_df), args.account_size, args.sizing)
    result = replay_portfolio(trades_df, args.account_size, args.sizing)
    sharpe = portfolio_sharpe_from_replay(result)

    original_total_pnl = float(trades_df["pnl_net"].sum())
    actual_total_pnl = float(result["taken"]["actual_pnl"].sum()) if len(result["taken"]) else 0.0

    log.info("=== Result: account=$%.0f sizing=%s ===", args.account_size, args.sizing)
    log.info("  Trades taken: %d / %d (%d skipped, capital-constrained)",
              result["n_taken"], len(trades_df), result["skipped_count"])
    if result["n_kelly_fallback"] > 0:
        log.info("  Kelly fallback to flat_2pct (< 60 trade history): %d trades", result["n_kelly_fallback"])
    if result["n_skipped_no_risk_estimate"] > 0:
        log.info("  Skipped, no causal risk estimate (entry_z already >= STOP_ZSCORE): %d trades",
                  result["n_skipped_no_risk_estimate"])
    log.info("  Peak concurrent notional (committed): $%.0f", result["peak_concurrent_notional"])
    log.info("  Peak mark-to-market equity: $%.2f  |  Trough: $%.2f",
              result["peak_mtm_equity"], result["trough_mtm_equity"])
    log.info("  Original (unconstrained) total P&L: $%.2f", original_total_pnl)
    log.info("  Actual (capital-constrained) total P&L: $%.2f", actual_total_pnl)
    log.info("  Final REALIZED equity: $%.2f (started $%.0f)", result["final_equity"], args.account_size)
    log.info("  Portfolio Sharpe (actual, realized): %.4f", sharpe)


if __name__ == "__main__":
    main()
