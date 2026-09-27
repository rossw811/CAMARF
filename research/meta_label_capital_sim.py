"""
research/meta_label_capital_sim.py -- audit step 3, second pre-declared primary metric (2026-09-27):
does an ML meta-labeler improve the CAPITAL-CONSTRAINED performance of the strategy's own trades?

Design (Lopez de Prado, AFML ch.3 meta-labeling; chosen because ml.py trains on |z| crossings of
Config.ML.TRAINING_ENTRY_THRESHOLD = 1.5 while the strategy enters at ENTRY_ZSCORE = 3.0, so ml.py's
events are not the trades being filtered -- Ross, 2026-09-27: "it depends how and where we apply it"):
  * primary model = the backtest's own entries (a gate's trades file; OLS rows only, B4);
  * meta-label   = 1 if the trade is profitable in DOLLARS (pnl_dollar.py; B2/B3-corrected), else 0;
                   trades without a dollar P&L (non-USD GVKEY legs, intraday) are excluded, disclosed;
  * features     = the ml.py feature set EXCEPT the lookahead TE features (R4.10), read from the
                   pair's spread file AT THE TRADE'S OWN ENTRY BAR (causal *_t columns);
  * split        = chronological by entry_time, purged on exit_time + 1% embargo
                   (ml_model_comparison_purged.purged_embargoed_split), hyper-parameters fixed;
  * PRE-DECLARED metric: capital-constrained replay ($100k, fixed sizing, portfolio_sim pnl_mode=
    "dollar") Sharpe of test-period trades the model admits (P(profitable) >= 0.5; SVM decision >= 0)
    minus the same replay on ALL test-period trades. Also reported: meta-label AUC, unconstrained
    Sharpe filtered vs all, and n admitted. Every (gate, model) run is a trial, logged.

Verified on a planted-signal synthetic first: debug/_verify_meta_label_capital_sim.py.
Usage: python research/meta_label_capital_sim.py   (CachyOS: trades files + spread files + WRDS cache)
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FEATURES = ["zscore", "zscore_velocity", "half_life_current", "hurst_exponent", "coint_fraction_rolling",
            "half_life_trend_slope", "mean_reversion_speed", "hedge_ratio_drift", "squeeze_min",
            "rsi_diff_velocity"]
_TF_DIR = {"1D": "1day"}


def features_at_entry(spread: pd.DataFrame, entry_time) -> dict:
    """ml.py's feature definitions evaluated at the entry bar of an actual trade (causal columns)."""
    if entry_time not in spread.index:
        return {}
    pos = spread.index.get_loc(entry_time)
    row = spread.iloc[pos]
    g = lambda c: float(row[c]) if c in spread.columns and pd.notna(row[c]) else np.nan
    z = spread["z_rolling"].to_numpy(float)
    ols, kal = g("hedge_ratio_ols_t"), g("hedge_ratio_kalman_t")
    sa, sb = g("squeeze_indicator_a_t"), g("squeeze_indicator_b_t")
    return {
        "zscore": z[pos],
        "zscore_velocity": z[pos] - z[max(0, pos - 5)],
        "half_life_current": g("half_life_rolling"),
        "hurst_exponent": g("hurst_rs_t"),
        "coint_fraction_rolling": g("coint_fraction_rolling_t"),
        "half_life_trend_slope": g("half_life_trend_slope_t"),
        "mean_reversion_speed": g("mean_reversion_speed_t"),
        "hedge_ratio_drift": abs(ols - kal) / abs(ols) if np.isfinite(ols) and ols != 0 and np.isfinite(kal) else np.nan,
        "squeeze_min": np.nanmin([sa, sb]) if np.isfinite(sa) or np.isfinite(sb) else np.nan,
        "rsi_diff_velocity": g("rsi_diff_velocity_t"),
    }


def build_dataset(trades: pd.DataFrame, spread_loader) -> pd.DataFrame:
    rows = []
    for t in trades.itertuples(index=False):
        sp = spread_loader(t.symbol_a, t.symbol_b, t.tf)
        f = features_at_entry(sp, pd.Timestamp(t.entry_time)) if sp is not None else {}
        rows.append(f or {k: np.nan for k in FEATURES})
    X = pd.DataFrame(rows, index=trades.index)[FEATURES]
    out = trades.copy()
    for c in FEATURES:
        out[c] = X[c]
    out["label_end_time"] = pd.to_datetime(out["exit_time"])
    out["entry_time"] = pd.to_datetime(out["entry_time"])
    out["y"] = (out["pnl_dollar_net"] > 0).astype(int)
    return out


def evaluate(ds: pd.DataFrame, models: dict, capital: float = 100_000.0, embargo_pct: float = 0.01,
             replay=None) -> pd.DataFrame:
    """Train each model on the purged train split, score the test split, and compare capital-sim
    Sharpe (admitted vs all test trades). `replay(df) -> sharpe` is injectable for tests."""
    from research.ml_model_comparison_purged import metric_panel, purged_embargoed_split
    import portfolio_math as pm
    import portfolio_sim
    if replay is None:
        def replay(df):
            if len(df) == 0:
                return float("nan"), 0
            r = portfolio_sim.replay_portfolio(df, capital, "fixed", pnl_mode="dollar")
            return portfolio_sim.portfolio_sharpe_from_replay(r), r["n_taken"]
    span = ds["entry_time"].max() - ds["entry_time"].min()
    sp = purged_embargoed_split(ds, purge=True, embargo=span * embargo_pct)
    tr, te = ds.loc[sp["train"]], ds.loc[sp["test"]]
    med = tr[FEATURES].median()
    Xtr, Xte = tr[FEATURES].fillna(med).to_numpy(), te[FEATURES].fillna(med).to_numpy()
    base_sh, base_taken = replay(te)
    base_unc = pm.sharpe_from_trades(te, "pnl_dollar_net")
    rows = []
    for name, (model, has_proba, bal) in models.items():
        kw = {}
        if bal:
            from sklearn.utils.class_weight import compute_sample_weight
            kw["sample_weight"] = compute_sample_weight("balanced", tr["y"].to_numpy())
        try:
            model.fit(Xtr, tr["y"].to_numpy(), **kw)
            s = model.predict_proba(Xte)[:, 1] if has_proba else model.decision_function(Xte)
        except Exception as e:
            rows.append({"model": name, "error": f"{type(e).__name__}: {e}"})
            continue
        admit = s >= (0.5 if has_proba else 0.0)
        sub = te[admit]
        f_sh, f_taken = replay(sub)
        auc = metric_panel(te["y"].to_numpy(), s, has_proba)["auc_roc"] if te["y"].nunique() == 2 else float("nan")
        rows.append({"model": name, "n_train": len(tr), "n_test": len(te), "n_admitted": int(admit.sum()),
                     "meta_auc": auc, "capsim_sharpe_all": base_sh, "capsim_sharpe_filtered": f_sh,
                     "capsim_sharpe_diff": f_sh - base_sh, "capsim_taken_all": base_taken,
                     "capsim_taken_filtered": f_taken,
                     "unconstrained_sharpe_all": base_unc,
                     "unconstrained_sharpe_filtered": pm.sharpe_from_trades(sub, "pnl_dollar_net") if len(sub) else float("nan"),
                     "test_start": str(te["entry_time"].min().date()), "test_end": str(te["entry_time"].max().date())})
    return pd.DataFrame(rows)


def main():
    import pnl_dollar
    from research.ml_model_comparison_purged import _models
    cache = {}

    def spread_loader(a, b, tf):
        k = (a, b, tf)
        if k not in cache:
            p = os.path.join("output", "results", _TF_DIR.get(tf, "x"), f"spread_series_{a}_{b}.parquet")
            cache[k] = pd.read_parquet(p) if os.path.exists(p) else None
        return cache[k]

    out, trials = [], []
    for f in sorted(glob.glob("output/backtest/trades_layer1_storm_*gate_pairsoverride.parquet")):
        gate = os.path.basename(f).replace("trades_layer1_storm_", "").replace("_pairsoverride.parquet", "")
        T = pd.read_parquet(f)
        T = T[(T["hedge_method"] == "ols") & (T["tf"] == "1D")]
        D = pnl_dollar.add_dollar_pnl(T)
        st = D["pnl_dollar_status"].value_counts().to_dict()
        D = D[D["pnl_dollar_status"] == "ok"]
        ds = build_dataset(D, spread_loader)
        print(f"\n== {gate}: {len(ds)} USD 1D OLS trades (status {st}); profitable rate {ds['y'].mean():.3f}")
        res = evaluate(ds, _models())
        res.insert(0, "gate", gate)
        print(res.drop(columns=[c for c in ("test_start", "test_end") if c in res]).round(4).to_string(index=False))
        out.append(res)
        trials += [{"gate": gate, "model": m} for m in res["model"]]
    R = pd.concat(out, ignore_index=True)
    os.makedirs("output/research", exist_ok=True)
    R.to_parquet("output/research/meta_label_capital_sim.parquet")
    with open("output/research/meta_label_capital_sim_trials.json", "w") as fh:
        json.dump({"n_trials": len(trials), "trials": trials,
                   "primary_metric": "capsim_sharpe_filtered - capsim_sharpe_all (test split, $100k fixed, dollar P&L)"}, fh, indent=1)
    print(f"\nSaved {len(R)} rows ({len(trials)} trials) -> output/research/meta_label_capital_sim.parquet")


if __name__ == "__main__":
    main()
