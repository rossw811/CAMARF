"""
capital_sim_selection_mechanism.py — root-causes why capital-constrained backtests
(portfolio_sim.py's replay_portfolio(), "fixed" sizing) report a HIGHER Sharpe than the
unconstrained headline (5.80 IS), across every account tier tested (7.19-10.44).

Standalone diagnostic, NOT part of the production pipeline. Tests one claim: is the
higher constrained Sharpe (a) a real structural effect of FIFO trade admission implicitly
filtering out worse trades / crowded-signal periods, or (b) a mechanical variance artifact
of shrinking the sample size (any random subset of the same size would score similarly)?

replay_portfolio() is pure FIFO by entry_time -- no edge-based ranking (portfolio_sim.py,
"fixed" sizing_method: target_notional = original_notional, size_scale = min(1, available/
target_notional), skip if size_scale < min_size_scale). So admission is entirely a function
of arrival order + how much capital already-open positions are consuming, not signal quality.

Decisive test: bootstrap a null by drawing random same-size subsets from the full
unconstrained trade list and computing pooled-daily Sharpe on each (SAME convention as
backtest.py's aggregate_portfolio() -- pnl indexed by exit_time [fallback entry_time],
resample("1D").sum(), mean/std*sqrt(252) -- confirmed by reading that function directly,
not approximated). If the real FIFO-admitted subset's Sharpe (using ORIGINAL, unconstrained
pnl_net, restricted to admitted trades -- isolates the SELECTION question from the sizing
question) falls inside this null's typical range, that's a variance artifact. If it sits
above the 95th percentile, FIFO ordering is doing something structurally meaningful.

Usage: python research/capital_sim_selection_mechanism.py
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from portfolio_sim import replay_portfolio  # noqa: E402

_N_BOOTSTRAP = 5000
_SEED = 20260713  # fixed seed for reproducibility -- Date.now()/random() sourcing not available
# hedge_method is REQUIRED in the key: trades_layer1.parquet stores both an OLS-hedge and a
# Kalman-hedge variant of the same underlying signal as separate rows for 23/24 confirmed pairs
# (only EG/WRB has kalman alone) -- confirmed directly, not assumed, after an initial run of this
# script without hedge_method in the key silently double-counted admitted trades (1598 vs the
# correct, session-verified 1313 for $100k/fixed).
_KEY_COLS = ["symbol_a", "symbol_b", "tf", "entry_time", "hedge_method"]


def pooled_daily_sharpe(pnl: pd.Series, exit_times: pd.Series, entry_times: pd.Series) -> float:
    """Exact replica of backtest.py's aggregate_portfolio() pooling convention: index by
    exit_time (falling back to entry_time when exit_time is null), resample("1D").sum()
    (fills non-trading days with 0, unlike a plain groupby(date)), then mean/std*sqrt(252)."""
    idx = exit_times.where(exit_times.notna(), entry_times)
    s = pd.Series(pnl.values, index=pd.DatetimeIndex(idx)).sort_index()
    daily = s.resample("1D").sum()
    if daily.std() == 0 or len(daily) == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


def admitted_skipped(trades_df: pd.DataFrame, account_size: float, sizing: str = "fixed"):
    result = replay_portfolio(trades_df, account_size, sizing)
    taken = result["taken"]
    if len(taken) == 0:
        return result, trades_df.iloc[0:0], trades_df
    taken_keys = set(map(tuple, taken[_KEY_COLS].astype(str).values))
    all_keys_arr = trades_df[_KEY_COLS].astype(str).values
    admitted_mask = np.array([tuple(row) in taken_keys for row in all_keys_arr])
    return result, trades_df[admitted_mask].copy(), trades_df[~admitted_mask].copy()


def bootstrap_null_percentile(trades_df: pd.DataFrame, n_taken: int, real_sharpe: float,
                               rng: np.random.Generator) -> tuple:
    n_total = len(trades_df)
    null_sharpes = np.empty(_N_BOOTSTRAP)
    for i in range(_N_BOOTSTRAP):
        idx = rng.choice(n_total, size=n_taken, replace=False)
        sub = trades_df.iloc[idx]
        null_sharpes[i] = pooled_daily_sharpe(sub["pnl_net"], sub["exit_time"], sub["entry_time"])
    null_sharpes = null_sharpes[np.isfinite(null_sharpes)]
    percentile = float((null_sharpes < real_sharpe).mean() * 100)
    return percentile, null_sharpes


def run_tier(trades_df: pd.DataFrame, account_size: float, rng: np.random.Generator) -> dict:
    result, admitted, skipped = admitted_skipped(trades_df, account_size, "fixed")
    n_taken = len(admitted)

    admitted_pnl = admitted["pnl_net"]
    skipped_pnl = skipped["pnl_net"]
    ks_stat, ks_p = stats.ks_2samp(admitted_pnl, skipped_pnl) if len(skipped_pnl) > 1 else (float("nan"), float("nan"))

    real_sharpe_selection_only = pooled_daily_sharpe(
        admitted["pnl_net"], admitted["exit_time"], admitted["entry_time"]
    )
    unconstrained_sharpe = pooled_daily_sharpe(
        trades_df["pnl_net"], trades_df["exit_time"], trades_df["entry_time"]
    )

    percentile, null_dist = bootstrap_null_percentile(trades_df, n_taken, real_sharpe_selection_only, rng)

    is_dd_hub = (trades_df["symbol_a"] == "DD") | (trades_df["symbol_b"] == "DD")
    admitted_dd_frac = float(is_dd_hub[admitted.index].mean()) if len(admitted) else float("nan")
    skipped_dd_frac = float(is_dd_hub[skipped.index].mean()) if len(skipped) else float("nan")

    return {
        "account_size": account_size,
        "n_total": len(trades_df),
        "n_taken": n_taken,
        "n_skipped": len(skipped),
        "unconstrained_sharpe_full": unconstrained_sharpe,
        "admitted_sharpe_selection_only": real_sharpe_selection_only,
        "admitted_mean_pnl": float(admitted_pnl.mean()),
        "skipped_mean_pnl": float(skipped_pnl.mean()) if len(skipped_pnl) else float("nan"),
        "admitted_std_pnl": float(admitted_pnl.std()),
        "skipped_std_pnl": float(skipped_pnl.std()) if len(skipped_pnl) else float("nan"),
        "admitted_win_rate": float((admitted_pnl > 0).mean()),
        "skipped_win_rate": float((skipped_pnl > 0).mean()) if len(skipped_pnl) else float("nan"),
        "ks_stat": ks_stat,
        "ks_p": ks_p,
        "null_percentile": percentile,
        "null_mean": float(null_dist.mean()),
        "null_std": float(null_dist.std()),
        "null_p5": float(np.percentile(null_dist, 5)),
        "null_p95": float(np.percentile(null_dist, 95)),
        "admitted_dd_hub_frac": admitted_dd_frac,
        "skipped_dd_hub_frac": skipped_dd_frac,
    }


def main():
    trades_df = pd.read_parquet(os.path.join(_ROOT, "output", "backtest", "trades_layer1.parquet"))
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])

    rng = np.random.default_rng(_SEED)

    print(f"Full unconstrained trade set: {len(trades_df)} trades, "
          f"pooled-daily Sharpe = {pooled_daily_sharpe(trades_df['pnl_net'], trades_df['exit_time'], trades_df['entry_time']):.4f}")
    print(f"DD-hub trades: {int(((trades_df['symbol_a']=='DD')|(trades_df['symbol_b']=='DD')).sum())} / {len(trades_df)} "
          f"({((trades_df['symbol_a']=='DD')|(trades_df['symbol_b']=='DD')).mean()*100:.1f}%)")
    print()

    for account_size in (100_000, 500_000):
        r = run_tier(trades_df, account_size, rng)
        print(f"=== account_size=${account_size:,.0f} (fixed sizing) ===")
        print(f"  taken={r['n_taken']}/{r['n_total']}  skipped={r['n_skipped']}")
        print(f"  admitted mean/std/win_rate pnl_net: {r['admitted_mean_pnl']:.2f} / {r['admitted_std_pnl']:.2f} / {r['admitted_win_rate']*100:.1f}%")
        print(f"  skipped  mean/std/win_rate pnl_net: {r['skipped_mean_pnl']:.2f} / {r['skipped_std_pnl']:.2f} / {r['skipped_win_rate']*100:.1f}%")
        print(f"  KS test admitted-vs-skipped pnl_net distribution: stat={r['ks_stat']:.4f} p={r['ks_p']:.4f}")
        print(f"  DD-hub fraction: admitted={r['admitted_dd_hub_frac']*100:.1f}%  skipped={r['skipped_dd_hub_frac']*100:.1f}%")
        print(f"  Sharpe (selection-only, original pnl_net): admitted={r['admitted_sharpe_selection_only']:.4f}  full-unconstrained={r['unconstrained_sharpe_full']:.4f}")
        print(f"  Bootstrap null (n={_N_BOOTSTRAP} random same-size subsets): mean={r['null_mean']:.4f} std={r['null_std']:.4f} "
              f"[5th,95th]=[{r['null_p5']:.4f},{r['null_p95']:.4f}]")
        print(f"  Real admitted-subset Sharpe falls at the {r['null_percentile']:.1f}th percentile of the null distribution")
        print()


if __name__ == "__main__":
    main()
