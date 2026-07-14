"""
Synthetic verification for research/hmm_gmm_regime_trade_features.py, run BEFORE trusting
real-data output, per CAMARF's standing verify-before-trusting discipline.

Case 1: causal feature construction -- a trade's feature vector must not change depending on
whether LATER trades exist in the input DataFrame (i.e. build_trade_features must not use any
future-dated macro row for an earlier trade's ffill).

Case 2: known regime separation -- construct synthetic trades with two obviously different
entry-time VIX levels (calm vs. crisis) and confirm HMM/GMM/Kalman+kmeans all separate them
into different states/clusters, not scrambled.

Case 3: expanding-window stability check sanity -- on a synthetic series with NO real regime
structure (pure noise features), confirm the stability-check machinery runs without error and
produces a well-formed DataFrame (doesn't validate the *rate* of agreement, since that's a real
finding to report on real data, not something to assert a specific value for in a synthetic case).
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from research.hmm_gmm_regime_trade_features import (
    build_trade_features, fit_hmm, fit_gmm, fit_kalman_kmeans,
    _clean_feature_matrix, expanding_window_stability_check,
)

warnings.filterwarnings("ignore")


def _synthetic_macro(n_days=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_days, freq="D")
    vix = 15 + rng.normal(0, 2, n_days)
    t10y2y = rng.normal(0.5, 0.3, n_days)
    hy_oas = rng.normal(4.0, 0.5, n_days)
    return pd.DataFrame({"vix_close": vix, "t10y2y": t10y2y, "hy_oas_spread_pct": hy_oas}, index=idx)


def case1_causal_feature_construction():
    macro_df = _synthetic_macro()
    rng = np.random.default_rng(1)
    entry_times = pd.to_datetime("2024-02-01") + pd.to_timedelta(
        rng.integers(0, 100, 50), unit="D"
    ) + pd.to_timedelta(rng.integers(9, 16, 50), unit="h")
    trades_early = pd.DataFrame({
        "entry_time": entry_times, "pnl_net": rng.normal(10, 5, 50),
    }).sort_values("entry_time").reset_index(drop=True)

    # A second version with MORE (later-dated) trades appended -- must not change the earlier
    # trades' own feature values.
    later_times = pd.to_datetime("2024-05-01") + pd.to_timedelta(rng.integers(0, 60, 30), unit="D")
    trades_extended = pd.concat([
        trades_early,
        pd.DataFrame({"entry_time": later_times, "pnl_net": rng.normal(10, 5, 30)}),
    ], ignore_index=True)

    f1 = build_trade_features(trades_early, macro_df)
    f2 = build_trade_features(trades_extended, macro_df)

    f1_sorted = f1.sort_values("entry_time").reset_index(drop=True)
    f2_early = f2[f2["entry_time"].isin(f1_sorted["entry_time"])].sort_values("entry_time").reset_index(drop=True)

    cols = ["vix_close_at_entry", "t10y2y_at_entry", "hy_oas_at_entry", "hour_sin", "hour_cos"]
    match = np.allclose(f1_sorted[cols].values, f2_early[cols].values, equal_nan=True)
    print(f"Case 1 (causal feature construction -- unaffected by later trades): match={match}")
    assert match, "FAIL: early trades' features changed when later trades were added"
    print("  PASS")


def case2_known_regime_separation():
    rng = np.random.default_rng(2)
    n_calm, n_crisis = 80, 80
    calm_times = pd.to_datetime("2024-01-01") + pd.to_timedelta(np.arange(n_calm) * 2, unit="D")
    crisis_times = pd.to_datetime("2024-06-01") + pd.to_timedelta(np.arange(n_crisis) * 2, unit="D")
    entry_times = pd.concat([pd.Series(calm_times), pd.Series(crisis_times)]).reset_index(drop=True)

    idx = pd.date_range("2023-12-01", "2024-09-01", freq="D")
    vix = pd.Series(15.0, index=idx)
    vix.loc[(idx >= "2024-05-15") & (idx < "2024-07-01")] = 45.0
    macro_df = pd.DataFrame({
        "vix_close": vix,
        "t10y2y": rng.normal(0.5, 0.05, len(idx)),
        "hy_oas_spread_pct": rng.normal(4.0, 0.1, len(idx)),
    }, index=idx)

    trades = pd.DataFrame({
        "entry_time": entry_times,
        "pnl_net": rng.normal(10, 5, n_calm + n_crisis),
    })
    t = build_trade_features(trades, macro_df)
    X, ok = _clean_feature_matrix(t)

    _, hmm_states, _ = fit_hmm(X)
    _, gmm_states, _ = fit_gmm(X)
    _, km_states, _ = fit_kalman_kmeans(t, ok)

    true_label = np.where(t.loc[ok, "vix_close_at_entry"].values > 30, 1, 0)

    def best_purity(states, true_label):
        purity = 0.0
        for s in np.unique(states):
            mask = states == s
            if mask.sum() == 0:
                continue
            majority = max((true_label[mask] == 0).mean(), (true_label[mask] == 1).mean())
            purity += majority * mask.sum()
        return purity / len(true_label)

    p_hmm = best_purity(hmm_states, true_label)
    p_gmm = best_purity(gmm_states, true_label)
    p_km = best_purity(km_states, true_label)
    print(f"Case 2 (known calm-vs-crisis separation) purity: hmm={p_hmm:.3f} gmm={p_gmm:.3f} kalman_kmeans={p_km:.3f}")
    assert p_hmm > 0.85, f"FAIL: HMM did not separate obviously distinct VIX regimes (purity={p_hmm:.3f})"
    assert p_gmm > 0.85, f"FAIL: GMM did not separate obviously distinct VIX regimes (purity={p_gmm:.3f})"
    assert p_km > 0.85, f"FAIL: Kalman+kmeans did not separate obviously distinct VIX regimes (purity={p_km:.3f})"
    print("  PASS (all three methods correctly separate an obviously bimodal VIX signal)")


def case3_stability_check_runs_cleanly():
    macro_df = _synthetic_macro(n_days=500, seed=3)
    rng = np.random.default_rng(3)
    entry_times = pd.to_datetime("2024-01-01") + pd.to_timedelta(np.sort(rng.integers(0, 400, 150)), unit="D") \
                  + pd.to_timedelta(rng.integers(9, 16, 150), unit="h")
    trades = pd.DataFrame({"entry_time": entry_times, "pnl_net": rng.normal(0, 5, 150)})
    t = build_trade_features(trades, macro_df)
    ok = t[["vix_close_at_entry", "t10y2y_at_entry", "hy_oas_at_entry"]].notna().all(axis=1)
    stability = expanding_window_stability_check(t, ok.values, n_checkpoints=3)
    print(f"Case 3 (stability-check machinery runs cleanly): shape={stability.shape}")
    assert len(stability) > 0 and "early_segment_agreement" in stability.columns
    assert stability["early_segment_agreement"].between(0, 1).all()
    print("  PASS (well-formed output, agreement rates in [0,1])")


if __name__ == "__main__":
    case1_causal_feature_construction()
    case2_known_regime_separation()
    case3_stability_check_runs_cleanly()
    print("\nALL CHECKS PASSED -- proceeding to real trade data is justified.")
