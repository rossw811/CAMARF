"""
CAMARF wfa.py — Walk-Forward Analysis (semi-WFA).

Two variants run in parallel for comparison:
  1. Expanding window  — Fold 2 trains on [0%, 50%] (accumulated)
  2. Rolling window    — Fold 2 trains on [50%, 70%] (fresh window only)

Fold structure (20/30/20/30):
  Expanding:
    Fold 1  train=[0%, 20%]   test=[20%, 50%]
    Fold 2  train=[0%, 50%]   test=[50%, 80%]
    Final holdout: [80%, 100%]  (compared to existing layer1_holdout)

  Rolling:
    Fold 1  train=[0%, 20%]   test=[20%, 50%]
    Fold 2  train=[50%, 70%]  test=[70%, 100%]

Semi-WFA definition:
  Same confirmed-pair set as analysis.py (no fold-specific pair selection).
  Per fold: OU parameters (mu_spread, sigma_spread, half-life) are re-estimated
  from the training window only. Z-score on test window uses training-window stats.
  Hedge ratio uses the causal point-in-time series (hedge_ratio_ols_t) already
  stored in the spread_series by analysis.py — this is causal by construction
  (rolling OLS without lookahead) and not re-estimated per fold.

Outputs:
  output/backtest/wfa_trades_expanding.parquet
  output/backtest/wfa_trades_rolling.parquet
  output/backtest/wfa_summary_expanding.parquet
  output/backtest/wfa_summary_rolling.parquet
  output/backtest/wfa_portfolio_expanding.parquet
  output/backtest/wfa_portfolio_rolling.parquet
  output/backtest/wfa_fold_comparison.parquet  — fold-by-fold metrics
"""
import logging
import os
import sys
import time
import warnings
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.wfa")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_OUT_DIR = os.path.join(_ROOT, "output", "backtest")

# ---------------------------------------------------------------------------
# Fold definitions
# ---------------------------------------------------------------------------
FOLD_EXPANDING = [
    # (train_start_pct, train_end_pct, test_start_pct, test_end_pct, label)
    (0.00, 0.20, 0.20, 0.50, "fold1_exp"),
    (0.00, 0.50, 0.50, 0.80, "fold2_exp"),
]
FOLD_ROLLING = [
    (0.00, 0.20, 0.20, 0.50, "fold1_roll"),
    (0.50, 0.70, 0.70, 1.00, "fold2_roll"),
]

# Backtest parameters — sourced directly from Config.BACKTEST, not duplicated.
# Previously hardcoded here with a comment claiming they matched Config.BACKTEST,
# but had silently drifted (EXIT_ZSCORE 0.5 vs. 0.0, SLIPPAGE_BPS 2.0 vs. 5,
# MAX_HOLD_MULT 3.0 vs. MAX_HOLD_MULTIPLIER's 2.0) — found 2026-07-20 Grand
# Sweep. Importing directly prevents this recurring; any config.py change now
# automatically propagates here instead of needing a manual second edit.
ENTRY_ZSCORE    = Config.BACKTEST.ENTRY_ZSCORE
EXIT_ZSCORE     = Config.BACKTEST.EXIT_ZSCORE
STOP_ZSCORE     = Config.BACKTEST.STOP_ZSCORE
MIN_HALF_LIFE   = 2  # a numerical clip floor (np.clip(half_life, MIN_HALF_LIFE, 1000.0)),
                     # NOT the same parameter as Config.BACKTEST.MIN_HALF_LIFE_BARS (an
                     # entry-filter threshold) -- distinct by design, left as a local constant
N_SHARES        = Config.BACKTEST.N_SHARES_PER_TRADE
COMMISSION      = Config.BACKTEST.COMMISSION_PER_SHARE
SLIPPAGE_BPS    = Config.BACKTEST.SLIPPAGE_BPS
MAX_HOLD_MULT   = Config.BACKTEST.MAX_HOLD_MULTIPLIER

# TF dirs mapping (tf_label → (tf_dir, bars_per_year))
_TF_MAP = {
    "1m":  ("1min",  390 * 252),
    "2m":  ("2min",  195 * 252),
    "3m":  ("3min",  130 * 252),
    "5m":  ("5min",   78 * 252),
    "15m": ("15min",  26 * 252),
    "30m": ("30min",  13 * 252),
    "1h":  ("1hr",   6.5 * 252),
    "4h":  ("4hr",         252),
    "1D":  ("1D",          252),
}


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------
def _load_spread(sym_a: str, sym_b: str, tf_label: str) -> Optional[pd.DataFrame]:
    tf_dir = _TF_MAP.get(tf_label, ("",))[0]
    if not tf_dir:
        return None
    stale_dir = tf_dir + "_stale"
    for d in [tf_dir, stale_dir]:
        p = os.path.join(_ROOT, "output", "results", d,
                         f"spread_series_{sym_a}_{sym_b}.parquet")
        if os.path.exists(p):
            df = pd.read_parquet(p)
            if {"spread"}.issubset(df.columns):
                return df
    return None


# ---------------------------------------------------------------------------
# OU parameter estimation from a spread slice
# ---------------------------------------------------------------------------
def _estimate_ou_params(spread: np.ndarray) -> Tuple[float, float, float]:
    """
    Returns (mu, sigma, half_life) estimated from training spread values.
    half_life = -log(2) / log(rho) where rho = lag-1 autocorrelation.
    Falls back to overall std and half_life=10 if estimation fails.
    """
    mu    = float(np.nanmean(spread))
    sigma = float(np.nanstd(spread))
    if sigma < 1e-10:
        return mu, 1e-10, 10.0
    n = len(spread)
    if n < 10:
        return mu, sigma, 10.0
    s = spread - mu
    lag1_cov = np.nanmean(s[1:] * s[:-1])
    var0     = np.nanmean(s ** 2)
    rho = lag1_cov / var0 if var0 > 0 else 0.0
    rho = float(np.clip(rho, 0.0, 0.9999))
    if rho <= 0:
        return mu, sigma, 10.0
    half_life = float(-np.log(2) / np.log(rho))
    half_life = float(np.clip(half_life, MIN_HALF_LIFE, 1000.0))
    return mu, sigma, half_life


# ---------------------------------------------------------------------------
# Trade record (minimal)
# ---------------------------------------------------------------------------
@dataclass
class WFATrade:
    symbol_a: str
    symbol_b: str
    tf_label: str
    fold: str
    variant: str           # "expanding" | "rolling"
    entry_time: object
    exit_time: object
    side: str
    entry_z: float
    exit_z: float
    entry_spread: float
    exit_spread: float
    exit_reason: str
    n_shares_a: int
    hedge_ratio: float
    pnl_gross: float
    pnl_cost: float
    pnl_net: float
    mae: float
    mfe: float
    hold_bars: int
    train_mu: float
    train_sigma: float
    train_half_life: float


# ---------------------------------------------------------------------------
# Backtest event loop on a slice (uses pre-computed train params)
# ---------------------------------------------------------------------------
def _run_fold_backtest(
    sym_a: str, sym_b: str, tf_label: str,
    test_df: pd.DataFrame,
    train_mu: float, train_sigma: float, train_half_life: float,
    fold_label: str, variant: str,
    storm_flags: Optional[Dict] = None,
    mm_hedge_map: Optional[Dict] = None,
    coint_frac: float = 1.0,
) -> List[WFATrade]:
    """
    Event-driven backtest on test_df using training-window OU params.
    Z-score = (spread - train_mu) / train_sigma (no lookahead).
    storm_flags: dict with keys coint_frac_sizing, garch_stop, session_edge, mm_exec.
    """
    sf = storm_flags or {}
    mm_map = mm_hedge_map or {}

    df = test_df.copy().dropna(subset=["spread"])
    df = df[df["spread"].notna()]
    if len(df) < 30 or train_sigma < 1e-10:
        return []

    spread_arr  = df["spread"].values
    hedge_col   = "hedge_ratio_ols_t"
    hedge_arr   = df[hedge_col].values if hedge_col in df.columns else np.full(len(df), np.nan)
    ts_arr      = df.index

    # STORM: garch_stop pre-compute
    _garch_stop = sf.get("garch_stop", False)
    _hist_z_std = 1.0
    _rolling_z_std = None
    _session_edge = sf.get("session_edge", False)
    _is_intraday = any(c in tf_label for c in ["m", "h"]) and "D" not in tf_label
    _mm_exec = sf.get("mm_exec", False)
    _beta_mm = mm_map.get(f"{sym_a}/{sym_b}") if _mm_exec else None
    _coint_frac_sizing = sf.get("coint_frac_sizing", False)
    n           = len(df)

    # Compute z-score using training-window parameters (no lookahead)
    z_arr = (spread_arr - train_mu) / train_sigma

    if _garch_stop:
        _hist_z_std = float(np.nanstd(z_arr)) or 1.0
        _rolling_z_std = (pd.Series(z_arr)
                          .rolling(100, min_periods=10)
                          .std()
                          .fillna(_hist_z_std)
                          .values)

    trades: List[WFATrade] = []
    in_position = False
    current: Optional[WFATrade] = None
    mae_val = mfe_val = 0.0

    max_hold = int(MAX_HOLD_MULT * train_half_life)

    for i in range(n):
        z      = z_arr[i]
        spread = spread_arr[i]
        ts     = ts_arr[i]

        if not np.isfinite(z) or not np.isfinite(spread):
            continue

        # Hedge ratio (causal point-in-time, with optional MM override)
        hedge_raw = float(hedge_arr[i]) if i < len(hedge_arr) else np.nan
        hedge = hedge_raw if np.isfinite(hedge_raw) else np.nan
        if _mm_exec and _beta_mm is not None and np.isfinite(_beta_mm) and _beta_mm > 0:
            hedge = _beta_mm
        if not np.isfinite(hedge) or hedge <= 0:
            continue

        if not in_position:
            # STORM: session_edge filter
            if _session_edge and _is_intraday:
                _hr, _mn = getattr(ts, "hour", -1), getattr(ts, "minute", 0)
                if (_hr == 9 and _mn < 30) or _hr >= 15:
                    continue

            if abs(z) < ENTRY_ZSCORE:
                continue

            # STORM: coint_frac_sizing — scale down by rolling confirmation fraction
            eff_shares = N_SHARES
            if _coint_frac_sizing and np.isfinite(coint_frac) and coint_frac > 0:
                eff_shares = max(1, int(N_SHARES * coint_frac))

            side = "short" if z > 0 else "long"
            current = WFATrade(
                symbol_a=sym_a, symbol_b=sym_b, tf_label=tf_label,
                fold=fold_label, variant=variant,
                entry_time=ts, exit_time=None, side=side,
                entry_z=z, exit_z=np.nan,
                entry_spread=spread, exit_spread=np.nan,
                exit_reason="",
                n_shares_a=eff_shares, hedge_ratio=hedge,
                pnl_gross=np.nan, pnl_cost=np.nan, pnl_net=np.nan,
                mae=np.nan, mfe=np.nan, hold_bars=0,
                train_mu=train_mu, train_sigma=train_sigma,
                train_half_life=train_half_life,
            )
            in_position = True
            mae_val = mfe_val = 0.0

        else:
            pnl_raw = (spread - current.entry_spread)
            if current.side == "short":
                pnl_raw = -pnl_raw
            mae_val = min(mae_val, pnl_raw)
            mfe_val = max(mfe_val, pnl_raw)
            current.hold_bars += 1

            exit_reason = ""
            # STORM: garch_stop
            _eff_stop = STOP_ZSCORE
            if _garch_stop and _rolling_z_std is not None:
                if _rolling_z_std[i] > 2.0 * _hist_z_std:
                    _eff_stop = min(_eff_stop, 3.0)
            if abs(z) >= _eff_stop:
                exit_reason = "stop"
            elif (current.side == "short" and z <= EXIT_ZSCORE) or \
                 (current.side == "long" and z >= -EXIT_ZSCORE):
                exit_reason = "signal_exit"
            elif current.hold_bars >= max_hold:
                exit_reason = "max_hold"

            if exit_reason:
                current.exit_time   = ts
                current.exit_z      = z
                current.exit_spread = spread
                current.exit_reason = exit_reason
                n = current.n_shares_a
                direction = 1 if current.side == "long" else -1
                gross = direction * (spread - current.entry_spread) * n
                cost  = (COMMISSION * (n + n * current.hedge_ratio) * 2
                         + SLIPPAGE_BPS / 10_000 * abs(current.entry_spread) * n * 2)
                current.pnl_gross = round(gross, 4)
                current.pnl_cost  = round(cost, 4)
                current.pnl_net   = round(gross - cost, 4)
                current.mae       = round(mae_val * n, 4)
                current.mfe       = round(mfe_val * n, 4)
                trades.append(current)
                in_position = False
                current = None

    # Close any open at end
    if in_position and current is not None:
        current.exit_time   = ts_arr[-1]
        current.exit_z      = z_arr[-1]
        current.exit_spread = spread_arr[-1]
        current.exit_reason = "eod"
        n = current.n_shares_a
        direction = 1 if current.side == "long" else -1
        gross = direction * (spread_arr[-1] - current.entry_spread) * n
        cost  = (COMMISSION * (n + n * current.hedge_ratio) * 2
                 + SLIPPAGE_BPS / 10_000 * abs(current.entry_spread) * n * 2)
        current.pnl_gross = round(gross, 4)
        current.pnl_cost  = round(cost, 4)
        current.pnl_net   = round(gross - cost, 4)
        current.mae       = round(mae_val * n, 4)
        current.mfe       = round(mfe_val * n, 4)
        trades.append(current)

    return trades


# ---------------------------------------------------------------------------
# Per-fold metrics
# ---------------------------------------------------------------------------
def _fold_metrics(trades: List[WFATrade], tf_label: str) -> Dict:
    if not trades:
        return {}
    pnl = np.array([t.pnl_net for t in trades])
    n = len(pnl)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    bpy = _TF_MAP.get(tf_label, ("", 252))[1]
    sharpe = (pnl.mean() / pnl.std() * np.sqrt(bpy)) if pnl.std() > 0 and n > 1 else np.nan
    cum = np.cumsum(pnl)
    max_dd = float((np.maximum.accumulate(cum) - cum).max()) if n > 0 else 0.0
    return {
        "n_trades": n,
        "win_rate": round(len(wins) / n, 4) if n > 0 else np.nan,
        "sharpe": round(sharpe, 4) if np.isfinite(sharpe) else np.nan,
        "total_pnl": round(float(pnl.sum()), 2),
        "max_drawdown": round(max_dd, 2),
    }


# ---------------------------------------------------------------------------
# Portfolio aggregation
# ---------------------------------------------------------------------------
def _portfolio_stats(all_trades: List[WFATrade]) -> Dict:
    if not all_trades:
        return {}
    pnl_s = pd.Series(
        [t.pnl_net for t in all_trades],
        index=[t.exit_time for t in all_trades],
    ).sort_index()
    daily = pnl_s.resample("1D").sum()
    sharpe = float((daily.mean() / daily.std() * np.sqrt(252))
                   if daily.std() > 0 else np.nan)
    cum = daily.cumsum()
    max_dd = float((cum.cummax() - cum).max()) if len(cum) > 0 else 0.0
    total = float(pnl_s.sum())
    return {
        "n_pairs": len(set(f"{t.symbol_a}/{t.symbol_b}" for t in all_trades)),
        "n_trades_total": len(all_trades),
        "total_pnl_portfolio": round(total, 2),
        "sharpe_portfolio": round(sharpe, 4) if np.isfinite(sharpe) else np.nan,
        "max_drawdown_portfolio": round(max_dd, 2),
    }


# ---------------------------------------------------------------------------
# Main WFA runner
# ---------------------------------------------------------------------------
def run_wfa(folds: List[Tuple], variant_name: str, tiers: pd.DataFrame,
            storm_flags: Optional[Dict] = None,
            mm_hedge_map: Optional[Dict] = None) -> List[WFATrade]:
    all_trades: List[WFATrade] = []
    fold_records = []

    for _, pair_row in tiers.iterrows():
        sym_a    = pair_row["symbol_a"]
        sym_b    = pair_row["symbol_b"]
        tf_label = pair_row["tf_label"]

        spread_df = _load_spread(sym_a, sym_b, tf_label)
        if spread_df is None:
            log.debug("WFA SKIP %s/%s@%s: no spread series", sym_a, sym_b, tf_label)
            continue

        spread_df = spread_df.dropna(subset=["spread"])
        if len(spread_df) < 200:
            log.debug("WFA SKIP %s/%s@%s: too few bars (%d)", sym_a, sym_b, tf_label, len(spread_df))
            continue

        n = len(spread_df)
        pair_trades_this_variant = []

        for (train_s, train_e, test_s, test_e, fold_label) in folds:
            ti_s = int(n * train_s)
            ti_e = int(n * train_e)
            te_s = int(n * test_s)
            te_e = int(n * test_e)

            train_df = spread_df.iloc[ti_s:ti_e]
            test_df  = spread_df.iloc[te_s:te_e]

            if len(train_df) < 50 or len(test_df) < 30:
                log.debug("WFA %s/%s@%s fold=%s: insufficient bars train=%d test=%d",
                          sym_a, sym_b, tf_label, fold_label, len(train_df), len(test_df))
                continue

            mu, sigma, half_life = _estimate_ou_params(train_df["spread"].values)
            _cfrac = float(pair_row.get("coint_fraction_rolling", 1.0))
            fold_trades = _run_fold_backtest(
                sym_a, sym_b, tf_label, test_df,
                mu, sigma, half_life, fold_label, variant_name,
                storm_flags=storm_flags, mm_hedge_map=mm_hedge_map,
                coint_frac=_cfrac,
            )
            pair_trades_this_variant.extend(fold_trades)

            fm = _fold_metrics(fold_trades, tf_label)
            fold_records.append({
                "variant": variant_name, "fold": fold_label,
                "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
                "train_bars": len(train_df), "test_bars": len(test_df),
                "train_mu": round(mu, 6), "train_sigma": round(sigma, 6),
                "train_half_life": round(half_life, 2),
                **fm,
            })

            log.info("WFA [%s] %s/%s@%s fold=%s  train=%d test=%d  n_trades=%d  "
                     "sharpe=%.2f  pnl=%.2f",
                     variant_name, sym_a, sym_b, tf_label, fold_label,
                     len(train_df), len(test_df), fm.get("n_trades", 0),
                     fm.get("sharpe", float("nan")), fm.get("total_pnl", 0.0))

        all_trades.extend(pair_trades_this_variant)

    return all_trades, fold_records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    t0 = time.time()
    log.info("=" * 70)
    log.info("CAMARF  —  wfa.py  —  Walk-Forward Analysis (semi-WFA)")
    log.info("=" * 70)

    tiers_path = os.path.join(_ROOT, "output", "stats", "cointegration_tiers.parquet")
    if not os.path.exists(tiers_path):
        log.error("cointegration_tiers.parquet not found — run stats.py first")
        sys.exit(1)
    tiers = pd.read_parquet(tiers_path)
    log.info("Loaded %d confirmed pairs", len(tiers))

    os.makedirs(_OUT_DIR, exist_ok=True)

    # Load MM hedge map once for mm_exec variants
    mm_hedge_map: Dict[str, float] = {}
    mm_path = os.path.join(_ROOT, "output", "stats", "hedge_ratio_comparison.parquet")
    if os.path.exists(mm_path):
        mm_df = pd.read_parquet(mm_path)
        for _, row in mm_df.iterrows():
            key = f"{row['symbol_a']}/{row['symbol_b']}"
            beta_mm = float(row.get("beta_mm", np.nan))
            if np.isfinite(beta_mm) and beta_mm > 0:
                mm_hedge_map[key] = beta_mm
        log.info("MM hedge map: %d pairs", len(mm_hedge_map))

    # Strategy variants: (strategy_suffix, storm_flags_dict)
    STRATEGY_VARIANTS = [
        ("baseline",     {}),
        ("cfrac_sizing", {"coint_frac_sizing": True}),
        ("garch_stop",   {"garch_stop": True}),
        ("session_edge", {"session_edge": True}),
        ("mm_exec",      {"mm_exec": True}),
        ("storm_all",    {"coint_frac_sizing": True, "garch_stop": True,
                          "session_edge": True, "mm_exec": True}),
    ]

    fold_comparison_rows = []
    portfolio_summary_rows = []

    for wfa_variant, folds in [("expanding", FOLD_EXPANDING), ("rolling", FOLD_ROLLING)]:
        for strategy_suffix, sf in STRATEGY_VARIANTS:
            run_label = f"{wfa_variant}_{strategy_suffix}"
            log.info("\n--- WFA [%s] strategy=%s ---", wfa_variant, strategy_suffix)
            trades, fold_records = run_wfa(
                folds, run_label, tiers,
                storm_flags=sf,
                mm_hedge_map=mm_hedge_map if sf.get("mm_exec") else {},
            )
            for r in fold_records:
                r["wfa_variant"] = wfa_variant
                r["strategy"] = strategy_suffix
            fold_comparison_rows.extend(fold_records)

            if trades:
                trade_rows = [asdict(t) for t in trades]
                pd.DataFrame(trade_rows).to_parquet(
                    os.path.join(_OUT_DIR, f"wfa_trades_{run_label}.parquet"), index=False)

                port = _portfolio_stats(trades)
                port.update({"wfa_variant": wfa_variant, "strategy": strategy_suffix,
                             "run_label": run_label})
                portfolio_summary_rows.append(port)
                pd.DataFrame([port]).to_parquet(
                    os.path.join(_OUT_DIR, f"wfa_portfolio_{run_label}.parquet"), index=False)

                log.info("WFA [%s/%s] %d trades | Sharpe=%.4f | PnL=%.2f",
                         wfa_variant, strategy_suffix, len(trades),
                         port.get("sharpe_portfolio", float("nan")),
                         port.get("total_pnl_portfolio", 0.0))
            else:
                log.warning("WFA [%s/%s] no trades generated", wfa_variant, strategy_suffix)

    # Save consolidated outputs
    if fold_comparison_rows:
        pd.DataFrame(fold_comparison_rows).to_parquet(
            os.path.join(_OUT_DIR, "wfa_fold_comparison.parquet"), index=False)
    if portfolio_summary_rows:
        pd.DataFrame(portfolio_summary_rows).to_parquet(
            os.path.join(_OUT_DIR, "wfa_portfolio_all.parquet"), index=False)

    # Print master comparison table
    if portfolio_summary_rows:
        print("\n=== WFA × STRATEGY COMPARISON ===")
        cmp_df = pd.DataFrame(portfolio_summary_rows)
        pivot = cmp_df.pivot_table(
            index="strategy",
            columns="wfa_variant",
            values=["sharpe_portfolio", "total_pnl_portfolio", "n_trades_total"],
            aggfunc="first",
        )
        print(pivot.round(3).to_string())

    try:
        cmp = pd.read_parquet(os.path.join(_OUT_DIR, "wfa_fold_comparison.parquet"))
        print("\n=== FOLD-LEVEL AVERAGES (baseline only) ===")
        for wfav in ["expanding", "rolling"]:
            sub = cmp[(cmp["wfa_variant"] == wfav) & (cmp["strategy"] == "baseline")]
            if sub.empty:
                continue
            g = sub.groupby("fold")[["n_trades", "sharpe", "total_pnl", "win_rate"]].mean()
            print(f"\n{wfav}:")
            print(g.round(3).to_string())
    except Exception as e:
        log.warning("Could not print fold comparison: %s", e)

    runtime = (time.time() - t0) / 60
    log.info("\nWFA complete in %.1f min. Outputs in %s", runtime, _OUT_DIR)

    # Write log
    log_lines = [
        "=== CAMARF wfa.py ===",
        f"date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"runtime_min: {runtime:.1f}",
        f"pairs: {len(tiers)}",
        "Fold structures: expanding=[0-20%/20-50%, 0-50%/50-80%]  rolling=[0-20%/20-50%, 50-70%/70-100%]",
        "=== end ===",
    ]
    with open(os.path.join(_ROOT, "latest_run_wfa.log"), "w") as f:
        f.write("\n".join(log_lines))


if __name__ == "__main__":
    main()
