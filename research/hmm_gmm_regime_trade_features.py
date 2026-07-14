"""
CAMARF hmm_gmm_regime_trade_features.py -- research/comparison script, NOT part of the
production pipeline.

Extends Session 13's already-validated HMM regime work (research/hmm_regime_detection.py,
fit on daily macro series: VIX/yield-curve/COT) to TRADE-LEVEL timing features -- discovering
regime structure empirically from the actual entry-time feature vectors of CAMARF's own real
trades, rather than only using predefined macro buckets. Three unsupervised methods compared:

  1. Gaussian HMM (sequence-aware, adds a transition-persistence structure the other two lack)
  2. Gaussian Mixture Model (static, no transition structure -- same feature space, no ordering)
  3. Kalman-smoothed VIX + k-means (a third, simpler comparison point)

The research question: do these three discover something NEW in realized trade performance
beyond what the already-known VIX/yield-curve regime effect (Session 13: mean-reversion 11x
faster in VIX-crisis, 4x slower in VIX-normal) already shows, or do they just rediscover the
same pattern in different clothing?

Causality note, read before trusting any "point-in-time" claim about this module: per-trade
FEATURES (macro series ffilled to entry_time, hour-of-day, day-of-week) are genuinely causal --
each trade's feature vector only uses information available at or before its own entry_time.
The CLUSTER/STATE ASSIGNMENT step is fit once on the full historical trade sample (standard
exploratory-regime-discovery practice, not a live causal signal) -- this is a real, disclosed
limitation, not glossed over. Section further down ("expanding-window stability check") tests
directly whether this matters: are early trades' regime labels stable if the model is refit
with only the data available up to that trade, or do they shift once later trades are added?

Usage:
    python research/hmm_gmm_regime_trade_features.py
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from hmmlearn import hmm
from sklearn.mixture import GaussianMixture
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro import build as macro_build

_OUT = "output/research/hmm_gmm_regime_trade_features.parquet"
_TRADES = "output/backtest/trades_layer1.parquet"
_N_STATES = 3
_SEED = 42


def build_trade_features(trades: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    """Causal per-trade feature vector: macro series ffilled to entry_time (never using data
    dated after entry_time), plus cyclical hour-of-day / day-of-week encodings."""
    t = trades.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    t = t.sort_values("entry_time").reset_index(drop=True)

    entry_dates = t["entry_time"].dt.normalize()
    macro_causal = macro_df.reindex(
        pd.date_range(macro_df.index.min(), entry_dates.max(), freq="D")
    ).ffill()
    joined = macro_causal.reindex(entry_dates.values)
    joined.index = t.index

    t["vix_close_at_entry"] = joined["vix_close"].values
    t["t10y2y_at_entry"] = joined["t10y2y"].values
    t["hy_oas_at_entry"] = joined["hy_oas_spread_pct"].values

    hour = t["entry_time"].dt.hour + t["entry_time"].dt.minute / 60.0
    t["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    t["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    dow = t["entry_time"].dt.dayofweek
    t["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    t["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)

    return t


_FEATURE_COLS = ["vix_close_at_entry", "t10y2y_at_entry", "hy_oas_at_entry",
                  "hour_sin", "hour_cos", "dow_sin", "dow_cos"]


def _clean_feature_matrix(t: pd.DataFrame):
    X = t[_FEATURE_COLS].copy()
    ok = X.notna().all(axis=1)
    return X[ok].values, ok


def fit_hmm(X: np.ndarray, n_states: int = _N_STATES, seed: int = _SEED):
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = hmm.GaussianHMM(n_components=n_states, covariance_type="diag",
                                 n_iter=200, random_state=seed)
        model.fit(Xs)
        states = model.predict(Xs)
    return model, states, scaler


def fit_gmm(X: np.ndarray, n_states: int = _N_STATES, seed: int = _SEED):
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    gmm = GaussianMixture(n_components=n_states, covariance_type="diag",
                           random_state=seed, n_init=5)
    states = gmm.fit_predict(Xs)
    return gmm, states, scaler


def fit_kalman_kmeans(t: pd.DataFrame, ok_mask: np.ndarray, n_states: int = _N_STATES, seed: int = _SEED):
    """Simple scalar Kalman filter (local-level model) smoothing entry-time VIX, then k-means
    on [smoothed_vix, hour_sin, hour_cos, dow_sin, dow_cos]. This IS causal in the smoothing
    step itself (a forward-only Kalman filter never uses future observations to smooth past
    ones) -- only the k-means cluster-center fitting is whole-sample, same disclosed limitation
    as HMM/GMM above."""
    vix = t.loc[ok_mask, "vix_close_at_entry"].values.astype(float)
    n = len(vix)
    xhat = np.zeros(n)
    P = np.zeros(n)
    Q, R = 0.05, 1.0  # process/observation noise -- light smoothing, not heavy lag
    xhat[0], P[0] = vix[0], 1.0
    for k in range(1, n):
        x_pred, P_pred = xhat[k - 1], P[k - 1] + Q
        K = P_pred / (P_pred + R)
        xhat[k] = x_pred + K * (vix[k] - x_pred)
        P[k] = (1 - K) * P_pred

    feats = np.column_stack([
        xhat,
        t.loc[ok_mask, "hour_sin"].values,
        t.loc[ok_mask, "hour_cos"].values,
        t.loc[ok_mask, "dow_sin"].values,
        t.loc[ok_mask, "dow_cos"].values,
    ])
    scaler = StandardScaler()
    Xs = scaler.fit_transform(feats)
    km = KMeans(n_clusters=n_states, random_state=seed, n_init=10)
    states = km.fit_predict(Xs)
    return km, states, xhat


def performance_by_state(t: pd.DataFrame, ok_mask: np.ndarray, states: np.ndarray, label: str) -> pd.DataFrame:
    sub = t.loc[ok_mask].copy()
    sub["state"] = states
    rows = []
    for s in sorted(sub["state"].unique()):
        g = sub[sub["state"] == s]
        pnl = g["pnl_net"].astype(float)
        sharpe = float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 and len(pnl) > 5 else np.nan
        rows.append({
            "method": label, "state": int(s), "n_trades": len(g),
            "win_rate": float((pnl > 0).mean()), "mean_pnl": float(pnl.mean()),
            "sharpe_like": sharpe,
            "mean_vix": float(g["vix_close_at_entry"].mean()),
            "mean_hour": float((np.arctan2(g["hour_sin"].mean(), g["hour_cos"].mean())
                                 / (2 * np.pi) * 24) % 24),
        })
    return pd.DataFrame(rows)


def expanding_window_stability_check(t: pd.DataFrame, ok_mask: np.ndarray, n_checkpoints: int = 4):
    """Real causal-stability check, not a synthetic-only exercise: for the earliest N trades,
    does their HMM state label change depending on whether the model is fit only on data up to
    that point (a genuinely causal, expanding-window fit) vs. fit on the full sample (this
    module's main analysis)? If labels are stable, the whole-sample fit is a reasonable
    descriptive proxy for a live causal signal; if unstable, that must be reported as a real
    limitation, not glossed over."""
    X_full, _ = _clean_feature_matrix(t)
    n = len(X_full)
    _, full_states, _ = fit_hmm(X_full)

    checkpoints = np.linspace(int(n * 0.3), n, n_checkpoints, dtype=int)
    early_n = int(n * 0.15)
    agreement_rates = []
    for cp in checkpoints:
        X_partial = X_full[:cp]
        try:
            _, partial_states, _ = fit_hmm(X_partial)
        except Exception:
            continue
        early_labels_full = full_states[:early_n]
        early_labels_partial = partial_states[:early_n]
        # HMM state indices are arbitrary between fits -- align via majority-vote relabeling
        # on the overlapping early segment before comparing.
        from scipy.optimize import linear_sum_assignment
        conf = np.zeros((_N_STATES, _N_STATES))
        for a, b in zip(early_labels_full, early_labels_partial):
            conf[a, b] += 1
        row_ind, col_ind = linear_sum_assignment(-conf)
        remap = dict(zip(col_ind, row_ind))
        aligned_partial = np.array([remap.get(s, s) for s in early_labels_partial])
        agree = float((aligned_partial == early_labels_full).mean())
        agreement_rates.append({"checkpoint_n_trades": int(cp), "early_segment_agreement": agree})
    return pd.DataFrame(agreement_rates)


def main():
    warnings.filterwarnings("ignore")
    print("Loading trades and macro data...")
    trades = pd.read_parquet(_TRADES)
    macro_df = macro_build(force_refresh=False).data

    t = build_trade_features(trades, macro_df)
    X, ok_mask = _clean_feature_matrix(t)
    print(f"{ok_mask.sum()}/{len(t)} trades have complete causal feature vectors")

    print("\nFitting HMM...")
    hmm_model, hmm_states, _ = fit_hmm(X)
    hmm_perf = performance_by_state(t, ok_mask, hmm_states, "hmm")
    print(hmm_perf.to_string(index=False))

    print("\nFitting GMM...")
    gmm_model, gmm_states, _ = fit_gmm(X)
    gmm_perf = performance_by_state(t, ok_mask, gmm_states, "gmm")
    print(gmm_perf.to_string(index=False))

    print("\nFitting Kalman-smoothed-VIX + k-means...")
    km_model, km_states, xhat = fit_kalman_kmeans(t, ok_mask)
    km_perf = performance_by_state(t, ok_mask, km_states, "kalman_kmeans")
    print(km_perf.to_string(index=False))

    print("\nExpanding-window causal-stability check (real, not synthetic)...")
    stability = expanding_window_stability_check(t, ok_mask)
    print(stability.to_string(index=False))

    all_perf = pd.concat([hmm_perf, gmm_perf, km_perf], ignore_index=True)
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    all_perf.to_parquet(_OUT, index=False)
    stability.to_parquet(_OUT.replace(".parquet", "_stability.parquet"), index=False)
    print(f"\nWritten to {_OUT}")


if __name__ == "__main__":
    main()
