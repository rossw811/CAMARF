"""
STORM factor grid: all 2^4 combinations of session_edge, garch_stop, mm_exec,
and coint_frac_threshold (0.0 = off, 0.10 = filter pairs with coint_frac < 0.10).

Runs on the OOS holdout slice. Outputs wfa/backtest-style comparison table.
"""
import os, sys, itertools, warnings
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

from backtest import BacktestEngine, RegimeConditioner, MLConditioner, load_mm_hedge_map
from config import Config
import portfolio_math

_ROOT = os.path.dirname(os.path.abspath(__file__))
_OUT_DIR = os.path.join(_ROOT, "output", "backtest")
os.makedirs(_OUT_DIR, exist_ok=True)

_TF_DIRS = [
    ("1min", "1m"), ("2min", "2m"), ("3min", "3m"), ("5min", "5m"),
    ("15min", "15m"), ("30min", "30m"), ("1hr", "1h"), ("4hr", "4h"),
]


def load_all_pairs():
    """Load pairs from each tf_dir results folder, same as backtest.py main()."""
    tiers = pd.read_parquet(os.path.join(_ROOT, "output", "stats", "cointegration_tiers.parquet"))
    cf_map = {(r.symbol_a, r.symbol_b, r.tf_label): r.coint_fraction_rolling
              for _, r in tiers.iterrows()}
    all_pairs = []
    for tf_dir, tf_label in _TF_DIRS:
        ppath = os.path.join(_ROOT, "output", "results", tf_dir, "pairs.parquet")
        if not os.path.exists(ppath):
            continue
        pairs = pd.read_parquet(ppath)
        if "tf_label" not in pairs.columns:
            pairs["tf_label"] = tf_label
        pairs["_tf_dir"] = tf_dir
        # attach coint_fraction_rolling from tiers
        pairs["coint_fraction_rolling"] = pairs.apply(
            lambda r: cf_map.get((r.symbol_a, r.symbol_b, tf_label), np.nan), axis=1)
        all_pairs.append(pairs)
    return pd.concat(all_pairs, ignore_index=True) if all_pairs else pd.DataFrame()


def load_spread(tf_dir, sym_a, sym_b):
    path = os.path.join(_ROOT, "output", "results", tf_dir,
                        f"spread_series_{sym_a}_{sym_b}.parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def portfolio_sharpe(trades):
    if not trades:
        return float("nan"), 0.0, 0, 0.0
    pnl = np.array([t.pnl_net for t in trades])
    total = float(pnl.sum())
    n = len(trades)
    wr = float((pnl > 0).mean())
    # Equity-curve Sharpe using daily P&L, zero-filled via portfolio_math (matches
    # aggregate_portfolio()'s convention) -- NOT groupby("date"), which silently
    # drops zero-P&L calendar days and inflates Sharpe (BUG-D62/D64/D70/D71 class,
    # found here 2026-07-20 Grand Sweep as a previously-missed 7th recurrence).
    exit_times = [t.exit_time for t in trades if t.exit_time is not None]
    if exit_times:
        df = pd.DataFrame({"exit_time": exit_times, "pnl_net": pnl})
        sharpe = portfolio_math.sharpe_from_trades(df)
    else:
        sharpe = float("nan")
    return sharpe, total, n, wr


def run_variant(pairs_df, storm_flags, mm_map, label):
    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
        storm_flags=storm_flags,
        mm_hedge_map=mm_map,
    )
    all_trades = []
    for _, pair_row in pairs_df.iterrows():
        sym_a = pair_row["symbol_a"]
        sym_b = pair_row["symbol_b"]
        tf_dir = pair_row["_tf_dir"]
        spread_df = load_spread(tf_dir, sym_a, sym_b)
        if spread_df is None:
            continue
        trades = engine.run(pair_row, spread_df, hedge_method="ols", holdout_only=True)
        all_trades.extend(trades)
    sh, tot, n, wr = portfolio_sharpe(all_trades)
    return {"label": label, "sharpe": round(sh, 3), "total_pnl": round(tot, 2),
            "n_trades": n, "win_rate": round(wr, 3)}


def main():
    pairs_df = load_all_pairs()
    print(f"Loaded {len(pairs_df)} confirmed pairs across all TF dirs")

    mm_map = load_mm_hedge_map()
    print(f"MM hedge map: {len(mm_map)} pairs")

    # Factor levels
    SE_LEVELS = [False, True]       # session_edge
    GS_LEVELS = [False, True]       # garch_stop
    ME_LEVELS = [False, True]       # mm_exec
    CF_LEVELS = [0.0, 0.10]         # coint_frac_threshold (0=off, 0.10=filter weak-coint)

    rows = []
    combos = list(itertools.product(SE_LEVELS, GS_LEVELS, ME_LEVELS, CF_LEVELS))
    print(f"\nRunning {len(combos)} grid combinations...\n")

    for se, gs, me, cf in combos:
        sf = {
            "session_edge": se,
            "garch_stop": gs,
            "mm_exec": me,
            "coint_frac_threshold": cf,
        }
        mm = mm_map if me else {}
        label = (
            f"SE={'1' if se else '0'} "
            f"GS={'1' if gs else '0'} "
            f"MM={'1' if me else '0'} "
            f"CF={cf:.2f}"
        )
        result = run_variant(pairs_df, sf, mm, label)
        rows.append(result)
        print(f"  {label}  =>  Sharpe={result['sharpe']:.3f}  PnL=${result['total_pnl']:,.0f}  "
              f"n={result['n_trades']}  WR={result['win_rate']:.1%}")

    grid_df = pd.DataFrame(rows)
    grid_df.to_parquet(os.path.join(_OUT_DIR, "storm_grid.parquet"), index=False)

    print("\n=== STORM GRID — RANKED BY SHARPE ===")
    print(grid_df.sort_values("sharpe", ascending=False).to_string(index=False))

    # Factor marginal effects
    print("\n=== MARGINAL EFFECT OF EACH FACTOR (avg Sharpe delta) ===")
    grid_df["SE"] = grid_df["label"].str.contains("SE=1")
    grid_df["GS"] = grid_df["label"].str.contains("GS=1")
    grid_df["MM"] = grid_df["label"].str.contains("MM=1")
    grid_df["CF"] = grid_df["label"].str.contains("CF=0.10")
    for factor, col in [("session_edge", "SE"), ("garch_stop", "GS"),
                        ("mm_exec", "MM"), ("coint_frac_thr=0.10", "CF")]:
        on = grid_df[grid_df[col]]["sharpe"].mean()
        off = grid_df[~grid_df[col]]["sharpe"].mean()
        print(f"  {factor:25s}  on={on:.3f}  off={off:.3f}  delta={on-off:+.3f}")


if __name__ == "__main__":
    main()
