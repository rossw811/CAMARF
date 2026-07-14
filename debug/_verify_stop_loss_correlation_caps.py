"""
_verify_stop_loss_correlation_caps.py — synthetic ground-truth checks for
research/stop_loss_correlation_caps.py, BEFORE trusting it on real data.

Case 1: stop-loss sweep sanity. A synthetic spread that blows through 3.0
but not 4.5 must be stopped out under STOP_ZSCORE=3.0 and NOT stopped out
under STOP_ZSCORE=4.5 -- confirms the sweep mechanism actually changes exit
behavior in the expected direction, not just relabeling the same trades.

Case 2: correlation-cluster exposure cap. A synthetic 4-pair correlation
matrix with 2 pairs highly correlated (0.9) and 2 pairs uncorrelated with
everything must (a) group the 2 correlated pairs into one cluster via the
same eigendecomposition machinery dd_hub_effective_bets.py already uses,
and (b) cap their COMBINED exposure to the same total the cap allows for
ANY single uncorrelated pair -- i.e. the two clustered pairs should not,
combined, get more capital than the cap permits for the whole cluster.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from research.stop_loss_correlation_caps import (
    run_stop_variant,
    identify_correlation_clusters,
    apply_cluster_exposure_cap,
)


def case1_stop_sweep():
    from backtest import BacktestEngine, RegimeConditioner, MLConditioner

    n = 100
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    z = np.full(n, 0.05)
    # Ramp from ~0 to 4.0 then back down -- crosses 3.0 at bar ~35, crosses
    # 4.5 never (peaks at 4.0), so STOP_ZSCORE=3.0 should stop it out and
    # STOP_ZSCORE=4.5 should let it exit normally via mean reversion.
    # n=100 (not 60) so the != 0.0 warm-up filter (drops any exact-zero bar,
    # backtest.py:445) can never shrink the real series below its own
    # len(df) < 60 minimum-bars guard (backtest.py:446).
    ramp_up = np.linspace(0.05, 4.0, 40)
    ramp_down = np.linspace(4.0, 0.05, 60)
    z[:40] = ramp_up
    z[40:] = ramp_down
    spread_df = pd.DataFrame({
        "timestamp": idx,
        "z_rolling": z,
        "spread": z * 0.5,
        "half_life_rolling": np.full(n, 10.0),
    }).set_index("timestamp")

    row = pd.Series({
        "symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": "1h",
        "hedge_ratio_ols": 1.0, "hedge_ratio_kalman_mean": 1.0,
        "half_life_rolling": 10.0, "hurst_rs": 0.5,
    })

    cfg = Config.BACKTEST
    original_stop = cfg.STOP_ZSCORE
    try:
        cfg.STOP_ZSCORE = 3.0
        engine_tight = BacktestEngine(cfg=cfg, regime_cond=RegimeConditioner(enabled=False),
                                       ml_cond=MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={})
        trades_tight = engine_tight.run(row, spread_df, hedge_method="ols", holdout_only=False)

        cfg.STOP_ZSCORE = 4.5
        engine_loose = BacktestEngine(cfg=cfg, regime_cond=RegimeConditioner(enabled=False),
                                       ml_cond=MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={})
        trades_loose = engine_loose.run(row, spread_df, hedge_method="ols", holdout_only=False)
    finally:
        cfg.STOP_ZSCORE = original_stop

    tight_exits = [t.exit_reason for t in trades_tight] if trades_tight else []
    loose_exits = [t.exit_reason for t in trades_loose] if trades_loose else []
    stopped_tight = any("stop" in str(r).lower() for r in tight_exits)
    stopped_loose = any("stop" in str(r).lower() for r in loose_exits)

    ok = stopped_tight and not stopped_loose
    print(f"Case 1 (stop-loss sweep direction): tight(3.0) exits={tight_exits} "
          f"loose(4.5) exits={loose_exits}")
    print(f"  tight stopped_out={stopped_tight} (expect True), "
          f"loose stopped_out={stopped_loose} (expect False) -> {'PASS' if ok else 'FAIL'}")
    return ok


def case2_correlation_cap():
    # 4 synthetic pairs: A,B highly correlated (0.9), C,D uncorrelated with everything.
    symbols = ["A_B", "C_D", "E_F", "G_H"]
    corr = np.array([
        [1.0, 0.9, 0.02, -0.01],
        [0.9, 1.0, 0.03,  0.01],
        [0.02, 0.03, 1.0, 0.01],
        [-0.01, 0.01, 0.01, 1.0],
    ])
    corr_df = pd.DataFrame(corr, index=symbols, columns=symbols)

    clusters = identify_correlation_clusters(corr_df, corr_threshold=0.5)
    same_cluster = clusters.get("A_B") == clusters.get("C_D")
    diff_cluster_ef = clusters.get("A_B") != clusters.get("E_F")
    diff_cluster_gh = clusters.get("A_B") != clusters.get("G_H")
    ok_grouping = same_cluster and diff_cluster_ef and diff_cluster_gh
    print(f"Case 2a (cluster grouping): A_B/C_D same cluster={same_cluster} (expect True), "
          f"A_B vs E_F different={diff_cluster_ef} (expect True), "
          f"A_B vs G_H different={diff_cluster_gh} (expect True) -> {'PASS' if ok_grouping else 'FAIL'}")

    base_weights = {s: 1.0 for s in symbols}
    capped = apply_cluster_exposure_cap(base_weights, clusters, max_cluster_exposure=1.0)
    cluster_ab_total = capped["A_B"] + capped["C_D"]
    single_pair_cap = capped["E_F"]
    ok_cap = cluster_ab_total <= 1.0 + 1e-9 and abs(single_pair_cap - base_weights["E_F"]) < 1e-9
    print(f"Case 2b (exposure cap): A_B+C_D combined weight={cluster_ab_total:.4f} "
          f"(expect <= 1.0, the cap), uncorrelated E_F weight unchanged={single_pair_cap:.4f} "
          f"(expect {base_weights['E_F']:.4f}) -> {'PASS' if ok_cap else 'FAIL'}")

    return ok_grouping and ok_cap


if __name__ == "__main__":
    r1 = case1_stop_sweep()
    r2 = case2_correlation_cap()
    if r1 and r2:
        print("\nALL CHECKS PASSED -- proceeding to real data is justified.")
        sys.exit(0)
    else:
        print("\nFAILED -- do not trust real-data results until this passes.")
        sys.exit(1)
