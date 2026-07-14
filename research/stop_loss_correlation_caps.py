"""
stop_loss_correlation_caps.py — two portfolio risk-management comparison arms:

1. Stop-loss sweep: COARSE_STOP_ZSCORE = [3.0, 3.5, 4.0, 4.5] (config.py already
   defines this grid; it was never actually run before this module). Patches
   Config.BACKTEST.STOP_ZSCORE and re-runs the real BacktestEngine, matching
   sensitivity.py's established run_variant() pattern exactly.

2. Correlation-aware exposure caps: extends the DD-hub/portfolio-wide
   effective-bets diagnostic (dd_hub_effective_bets.py / portfolio_effective_bets.py
   — real correlation matrix already computed there, ENB=9.78 of 21 nominal
   pairs) from a DIAGNOSTIC into an actual SIZING RULE — group pairs into
   discrete correlation clusters (scipy hierarchical clustering, the same
   linkage machinery backtest.py's HRP implementation already uses) and cap
   each cluster's TOTAL position-size weight, not just each pair's own weight.

Comparison arm only, per CAMARF's current research/paper policy — writes to
docs/FINDINGS.md and Development.md, not PAPER.md directly. Not promoted to
production defaults unless a result is genuinely exceptional and says so
explicitly.
"""
import os
import sys
import warnings
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from sensitivity import load_pairs_and_spreads  # noqa: E402


def _correct_portfolio_sharpe(trades: list) -> float:
    """Daily-bucketed equity-curve Sharpe using resample("1D") (zero-fills
    every calendar day between first and last exit), matching
    aggregate_portfolio()'s established convention -- NOT sensitivity.py's
    own _portfolio_sharpe(), which still uses the groupby(date).sum() form
    BUG-D62 already found and fixed in portfolio_sim.py but which was never
    applied to sensitivity.py itself. Flagged as a real, separate finding
    (see FINDINGS.md/Development.md write-up) rather than silently worked
    around without disclosure."""
    if not trades:
        return float("nan")
    exit_times = [t.exit_time for t in trades if t.exit_time is not None]
    if not exit_times:
        return float("nan")
    pnl = [t.pnl_net for t in trades if t.exit_time is not None]
    s = pd.Series(pnl, index=pd.DatetimeIndex(exit_times)).sort_index()
    daily = s.resample("1D").sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))

_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "output", "research")


# =============================================================================
# 1. STOP-LOSS SWEEP
# =============================================================================

def run_stop_variant(pairs: pd.DataFrame, spreads: dict, stop_z: float) -> Dict:
    """Run the full confirmed-pair OOS holdout at one STOP_ZSCORE value,
    baseline entry/exit z otherwise. Mirrors sensitivity.py's run_variant()
    config-patch pattern exactly."""
    from backtest import BacktestEngine, RegimeConditioner, MLConditioner

    cfg = Config.BACKTEST
    original_stop = cfg.STOP_ZSCORE
    cfg.STOP_ZSCORE = stop_z
    try:
        engine = BacktestEngine(cfg=cfg, regime_cond=RegimeConditioner(enabled=False),
                                 ml_cond=MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={})
        all_trades = []
        stop_exits = 0
        for _, row in pairs.iterrows():
            key = f"{row['symbol_a']}_{row['symbol_b']}"
            spread_df = spreads.get(key)
            if spread_df is None:
                continue
            trades = engine.run(row, spread_df, hedge_method="ols", holdout_only=True)
            all_trades.extend(trades)
            stop_exits += sum(1 for t in trades if "stop" in str(getattr(t, "exit_reason", "")).lower())
    finally:
        cfg.STOP_ZSCORE = original_stop

    sh = _correct_portfolio_sharpe(all_trades)
    total_pnl = sum(getattr(t, "pnl_net", 0.0) for t in all_trades)
    dd = _max_drawdown(all_trades)
    return {
        "stop_zscore": stop_z, "sharpe": round(sh, 4) if np.isfinite(sh) else float("nan"),
        "n_trades": len(all_trades), "n_stop_exits": stop_exits,
        "total_pnl": round(total_pnl, 2), "max_drawdown": round(dd, 2),
    }


def _max_drawdown(trades) -> float:
    if not trades:
        return 0.0
    pnls = sorted(((getattr(t, "exit_time", None), getattr(t, "pnl_net", 0.0)) for t in trades),
                   key=lambda x: (x[0] is None, x[0]))
    cum = np.cumsum([p for _, p in pnls])
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return float(dd.max()) if len(dd) else 0.0


# =============================================================================
# 2. CORRELATION-AWARE EXPOSURE CAPS
# =============================================================================

def identify_correlation_clusters(corr_df: pd.DataFrame, corr_threshold: float = 0.5) -> Dict[str, int]:
    """Hierarchical clustering on a correlation-derived distance matrix
    (distance = sqrt(0.5*(1-corr)), same transform backtest.py's HRP code
    already uses), cut at a distance corresponding to corr_threshold.
    Returns {symbol_key: cluster_id}."""
    symbols = list(corr_df.columns)
    n = len(symbols)
    if n < 2:
        return {s: i for i, s in enumerate(symbols)}
    corr = corr_df.to_numpy()
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="average")
    dist_threshold = np.sqrt(0.5 * (1 - corr_threshold))
    labels = fcluster(link, t=dist_threshold, criterion="distance")
    return {sym: int(lbl) for sym, lbl in zip(symbols, labels)}


def apply_cluster_exposure_cap(base_weights: Dict[str, float], clusters: Dict[str, int],
                                max_cluster_exposure: float) -> Dict[str, float]:
    """Scale down every pair in a cluster proportionally, if the cluster's
    combined weight exceeds max_cluster_exposure. Pairs in clusters under
    the cap are returned unchanged."""
    by_cluster: Dict[int, List[str]] = {}
    for sym, cid in clusters.items():
        by_cluster.setdefault(cid, []).append(sym)

    out = dict(base_weights)
    for cid, members in by_cluster.items():
        cluster_total = sum(base_weights.get(m, 0.0) for m in members)
        if cluster_total > max_cluster_exposure and cluster_total > 0:
            scale = max_cluster_exposure / cluster_total
            for m in members:
                out[m] = base_weights.get(m, 0.0) * scale
    return out


def main():
    os.makedirs(_OUT_DIR, exist_ok=True)
    print("=" * 70)
    print("Portfolio risk-management comparison arms: stop-loss sweep + "
          "correlation-aware exposure caps")
    print("=" * 70)

    # --- Part 1: stop-loss sweep ---
    print("\n--- Part 1: Stop-loss sweep (config.py's COARSE_STOP_ZSCORE grid) ---")
    result_tuple = load_pairs_and_spreads("1hr", "1h")
    if not result_tuple or len(result_tuple) < 3:
        print("No pairs/spreads found for 1h — aborting stop-loss sweep.")
        stop_results = []
    else:
        pairs, spreads, _adv_map = result_tuple
        print(f"Loaded {len(pairs)} confirmed pairs, {len(spreads)} spread files.")
        stop_grid = getattr(Config.BACKTEST, "COARSE_STOP_ZSCORE", [3.0, 3.5, 4.0, 4.5])
        stop_results = []
        for sz in stop_grid:
            r = run_stop_variant(pairs, spreads, sz)
            stop_results.append(r)
            print(f"  STOP_ZSCORE={sz:.1f}  Sharpe={r['sharpe']:.4f}  "
                  f"n_trades={r['n_trades']}  stop_exits={r['n_stop_exits']}  "
                  f"total_pnl=${r['total_pnl']:,.2f}  max_dd=${r['max_drawdown']:,.2f}")
        pd.DataFrame(stop_results).to_parquet(
            os.path.join(_OUT_DIR, "stop_loss_sweep.parquet"))

    # --- Part 2: correlation-aware exposure caps ---
    print("\n--- Part 2: Correlation-aware exposure caps ---")
    corr_matrix_path = os.path.join(_OUT_DIR, "portfolio_effective_bets_corr_matrix.parquet")
    if not os.path.exists(corr_matrix_path):
        print(f"Real correlation matrix not found at {corr_matrix_path} — "
              "run research/portfolio_effective_bets.py first. Aborting Part 2.")
        cluster_results = None
    else:
        corr_df = pd.read_parquet(corr_matrix_path)
        clusters = identify_correlation_clusters(corr_df, corr_threshold=0.5)
        n_clusters = len(set(clusters.values()))
        print(f"Loaded real {corr_df.shape[0]}-pair correlation matrix. "
              f"{n_clusters} clusters found at corr_threshold=0.5 (from {corr_df.shape[0]} pairs).")
        cluster_sizes = pd.Series(clusters).value_counts()
        multi_member = cluster_sizes[cluster_sizes > 1]
        print(f"Clusters with >1 member: {len(multi_member)} "
              f"(sizes: {multi_member.to_dict()})")

        # Real OOS comparison: baseline equal weight vs. cluster-capped weight,
        # applied as a post-hoc reweight of realized trade P&L (same convention
        # risk-parity/HRP sizing comparisons already use elsewhere this session).
        trades_path = os.path.join(
            os.path.dirname(_OUT_DIR), "backtest", "trades_layer1_holdout.parquet")
        if not os.path.exists(trades_path):
            print(f"OOS holdout trades not found at {trades_path} — cannot compute "
                  "real Sharpe comparison for Part 2.")
            cluster_results = {"n_clusters": n_clusters, "cluster_sizes": cluster_sizes.to_dict()}
        else:
            trades = pd.read_parquet(trades_path)
            trades["pair_key"] = trades["symbol_a"] + "_" + trades["symbol_b"]
            base_weights = {k: 1.0 for k in trades["pair_key"].unique()}
            capped_weights = apply_cluster_exposure_cap(base_weights, clusters, max_cluster_exposure=1.0)

            base_sharpe = _reweighted_sharpe(trades, base_weights)
            capped_sharpe = _reweighted_sharpe(trades, capped_weights)
            print(f"  Baseline (equal weight, no cap): Sharpe={base_sharpe:.4f}")
            print(f"  Correlation-cluster-capped:      Sharpe={capped_sharpe:.4f}")
            cluster_results = {
                "n_clusters": n_clusters, "cluster_sizes": cluster_sizes.to_dict(),
                "base_sharpe": base_sharpe, "capped_sharpe": capped_sharpe,
            }
            pd.DataFrame([{"symbol": k, "cluster": v} for k, v in clusters.items()]).to_parquet(
                os.path.join(_OUT_DIR, "correlation_clusters.parquet"))

    print("\nDone.")
    return stop_results, cluster_results


def _reweighted_sharpe(trades: pd.DataFrame, weights: Dict[str, float]) -> float:
    """Scale each trade's pnl_net by its pair's weight, pool by exit date
    (resample convention, matching aggregate_portfolio()'s BUG-D62-fixed
    convention, not the buggy groupby-only one)."""
    t = trades.copy()
    t["w"] = t["pair_key"].map(weights).fillna(1.0)
    t["weighted_pnl"] = t["pnl_net"] * t["w"]
    t["exit_time"] = pd.to_datetime(t["exit_time"])
    s = pd.Series(t["weighted_pnl"].values, index=pd.DatetimeIndex(t["exit_time"])).sort_index()
    daily = s.resample("1D").sum()
    if len(daily) < 5 or daily.std() == 0:
        return float("nan")
    return float(daily.mean() / daily.std() * np.sqrt(252))


if __name__ == "__main__":
    main()
