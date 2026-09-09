"""
Pooled-across-folds headline Sharpe for pit_wfa_wrds_daily.py's corrected-
scale PIT result -- PAPER_MAGNITUDE.md §4/§10's last open item on this
finding. Ross approved the splicing design 2026-09-08 after an explicit
methodology discussion (three real choices, each with a genuine bias
tradeoff -- see PAPER_MAGNITUDE.md §4 for the full disclosure):

1. Capital continuity across the fold boundary: ARITHMETIC-POOLED, not
   compounded. Each fold keeps its own $100,000 capital base, consistent
   with how each fold's Sharpe is already reported standalone in the
   existing per-fold table -- compounding would let an early lucky/unlucky
   fold mechanically amplify or shrink everything downstream, which is
   not what a fold's own capital-constrained result currently measures.
2. The calendar gap between folds (untested time no PIT screen covers):
   DROPPED, not zero-filled. `portfolio_math.daily_pnl_from_trades`
   already zero-fills only WITHIN a given trade set's own [min exit,
   max exit] span (see its `resample("1D").sum()` convention) -- calling
   it separately per fold and concatenating the results means the
   inter-fold gap is never inserted, while each fold's own genuine
   no-trade days stay correctly zero-filled. Zero-filling the gap
   instead would dilute volatility with days this project has zero
   evidence about, artificially inflating the pooled Sharpe.
3. Annualization: `ann_factor=252` (portfolio_math's existing default),
   applied to the SPLICED series -- keyed to the actual number of daily
   observations present after splicing, not calendar span, since the
   gap was dropped rather than zero-filled.

Pools WITHIN each wfa_variant separately (rolling: fold1_roll+fold2_roll;
expanding: fold1_exp+fold2_exp) rather than mixing variants -- fold1_exp
and fold1_roll are identical by construction, but fold2_exp and
fold2_roll are genuinely different trade sets, and pooling across
variants would require an arbitrary choice of which fold2 to use.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_math

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TRADES_PATH = os.path.join(_ROOT, "output", "backtest", "pit_wfa_wrds_daily_taken_trades.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "backtest", "pit_wfa_wrds_daily_pooled_sharpe.parquet")


def pool_variant(trades_df: pd.DataFrame, wfa_variant: str, fold_order: list) -> dict:
    """Splices the named folds' daily P&L (in `fold_order`) end to end,
    dropping the inter-fold calendar gap (see module docstring), and
    computes the pooled Sharpe on the resulting series."""
    per_fold_daily = []
    per_fold_stats = []
    for fold in fold_order:
        fold_trades = trades_df[(trades_df["wfa_variant"] == wfa_variant) & (trades_df["fold"] == fold)]
        daily = portfolio_math.daily_pnl_from_trades(fold_trades, pnl_col="actual_pnl")
        per_fold_daily.append(daily)
        per_fold_stats.append({
            "fold": fold, "n_trades": len(fold_trades),
            "n_daily_obs": len(daily), "fold_sharpe": sharpe_from_daily_pnl_local(daily),
            "date_range": (str(daily.index.min().date()), str(daily.index.max().date())) if len(daily) else None,
        })

    # Concatenate VALUES only (reset_index) -- the pooled Sharpe calc
    # doesn't need real dates, only the ordered sequence of daily P&L
    # observations with the inter-fold gap absent, per the agreed design.
    pooled_values = pd.concat([d.reset_index(drop=True) for d in per_fold_daily], ignore_index=True)
    pooled_sharpe = sharpe_from_daily_pnl_local(pooled_values)

    return {
        "wfa_variant": wfa_variant,
        "fold_order": fold_order,
        "per_fold": per_fold_stats,
        "n_pooled_daily_obs": len(pooled_values),
        "pooled_total_pnl": float(pooled_values.sum()),
        "pooled_sharpe": pooled_sharpe,
        "pooled_mean_daily_pnl": float(pooled_values.mean()) if len(pooled_values) else float("nan"),
        "pooled_std_daily_pnl": float(pooled_values.std()) if len(pooled_values) else float("nan"),
    }


def sharpe_from_daily_pnl_local(daily_pnl: pd.Series) -> float:
    return portfolio_math.sharpe_from_daily_pnl(daily_pnl, ann_factor=252.0)


def pool_variant_equal_weighted(trades_df: pd.DataFrame, wfa_variant: str, fold_order: list) -> dict:
    """Tier C item #17 (2026-09-08 caveat/limitation search): an
    ALTERNATIVE, equally-defensible pooling construction to pool_variant's
    calendar-day-weighted splice -- not a correction to it (that method's
    own docstring already discloses the weighting property as a real,
    disclosed feature, not a bug). Here, each fold's OWN Sharpe is
    computed independently, then the folds are averaged with EQUAL
    weight regardless of how many calendar days each one spans. This
    answers a different question than pool_variant: "if each fold's
    result counted equally regardless of its length, what would the
    average look like" vs. pool_variant's "what does the full spliced
    daily P&L sequence say." Genuinely different tradeoffs: equal-
    weighting avoids letting a long, thin-trading fold dominate purely by
    calendar span, but it also throws away real information about how
    much evidence each fold actually contains (a fold's own Sharpe
    computed on very few observations is noisier, and equal-weighting
    treats that noisy estimate the same as a well-supported one)."""
    fold_sharpes = []
    for fold in fold_order:
        fold_trades = trades_df[(trades_df["wfa_variant"] == wfa_variant) & (trades_df["fold"] == fold)]
        daily = portfolio_math.daily_pnl_from_trades(fold_trades, pnl_col="actual_pnl")
        s = sharpe_from_daily_pnl_local(daily)
        fold_sharpes.append({"fold": fold, "n_trades": len(fold_trades), "n_daily_obs": len(daily), "sharpe": s})

    valid = [f["sharpe"] for f in fold_sharpes if np.isfinite(f["sharpe"])]
    equal_weighted_mean_sharpe = float(np.mean(valid)) if valid else float("nan")

    return {
        "wfa_variant": wfa_variant, "fold_order": fold_order, "per_fold": fold_sharpes,
        "n_folds_valid": len(valid),
        "equal_weighted_mean_sharpe": equal_weighted_mean_sharpe,
    }


def main():
    if not os.path.exists(_TRADES_PATH):
        print(f"ERROR: {_TRADES_PATH} not found -- run pit_wfa_wrds_daily.py "
              f"(with the taken-trades persistence, 2026-09-08+) first.")
        return

    trades_df = pd.read_parquet(_TRADES_PATH)
    print(f"Loaded {len(trades_df)} taken trades: "
          f"{trades_df.groupby(['wfa_variant', 'fold']).size().to_dict()}")

    results = []
    for wfa_variant, fold_order in [
        ("rolling", ["fold1_roll", "fold2_roll"]),
        ("expanding", ["fold1_exp", "fold2_exp"]),
    ]:
        present = set(trades_df[trades_df["wfa_variant"] == wfa_variant]["fold"].unique())
        if not set(fold_order).issubset(present):
            print(f"Skipping {wfa_variant}: expected folds {fold_order}, found {present}")
            continue
        r = pool_variant(trades_df, wfa_variant, fold_order)
        results.append(r)
        print(f"\n=== {wfa_variant} pooled ({' -> '.join(fold_order)}) ===")
        for f in r["per_fold"]:
            print(f"  {f['fold']}: {f['n_trades']} trades, {f['n_daily_obs']} daily obs, "
                  f"fold Sharpe={f['fold_sharpe']:.4f}, range={f['date_range']}")
        print(f"  POOLED (calendar-day-weighted): {r['n_pooled_daily_obs']} daily obs, "
              f"total P&L=${r['pooled_total_pnl']:,.2f}, Sharpe={r['pooled_sharpe']:.4f}")

        r_eq = pool_variant_equal_weighted(trades_df, wfa_variant, fold_order)
        print(f"  POOLED (equal-weighted-per-fold, alternative construction): "
              f"mean Sharpe={r_eq['equal_weighted_mean_sharpe']:.4f} "
              f"(fold Sharpes: {[round(f['sharpe'], 4) for f in r_eq['per_fold']]})")
        r["equal_weighted_mean_sharpe"] = r_eq["equal_weighted_mean_sharpe"]

    if results:
        flat_rows = [{k: v for k, v in r.items() if k != "per_fold"} for r in results]
        pd.DataFrame(flat_rows).to_parquet(_OUT_PATH)
        print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
