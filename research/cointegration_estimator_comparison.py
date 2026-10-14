"""
research/cointegration_estimator_comparison.py -- endogeneity arm (a) on real data (Ross 2026-10-13: comparison first;
main pathway only if supported). For every pair in the rebuilt pool (purity_pairs_pit_k1_clean.parquet, 1D pairs), on
the discovery window (EPISODIC_WINDOW_BARS, 2520 bars) of common valid days ENDING at the pair's point-in-time eligible_from:
  beta_ols / beta_dols / beta_fmols   hedge ratios (research/cointegration_estimator_arms.py)
  eg_p, eg_reject                     production Engle-Granger: analysis._eg_worker both directions, max p,
                                      Config.ANALYSIS.EG_MAX_LAG; reject at 5% (single test, as a like-for-like check)
  johansen_trace, johansen_reject     restricted-constant Johansen, simulated 5% critical value for the window length
Contrast: an equal number of (pair, window) rows drawn at random from the Tier-3 windows file (tested candidates,
confirmed or not), on their own windows -- how often the two tests agree on ordinary candidates.
Series: episodic_pairs_adapter._load_symbol (the WRDS-first total-return series with the S35 no-trade mask, as the
pools trade). Output: output/research/cointegration_estimator_comparison.parquet + printed summary.
Usage (CachyOS): python research/cointegration_estimator_comparison.py
Test: debug/_verify_cointegration_estimator_arms.py (compare_pair)
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
_R = os.path.join(ROOT, "output", "research")
OUT = os.path.join(_R, "cointegration_estimator_comparison.parquet")


def compare_pair(y, x) -> dict:
    from analysis import _eg_worker
    from config import Config
    import cointegration_estimator_arms as arms
    y, x = np.asarray(y, float), np.asarray(x, float)
    lag = Config.ANALYSIS.EG_MAX_LAG
    ab = _eg_worker(("A", "B", y, x, lag, "1D"))
    ba = _eg_worker(("B", "A", x, y, lag, "1D"))
    eg_p = max(ab["pvalue"], ba["pvalue"]) if ab.get("ok") and ba.get("ok") else np.nan
    tr = arms.johansen_trace(y, x)
    return {"n": len(y), "beta_ols": arms.ols_beta(y, x), "beta_dols": arms.dols_beta(y, x),
            "beta_fmols": arms.fmols_beta(y, x), "eg_p": float(eg_p), "eg_reject": bool(eg_p < 0.05),
            "johansen_trace": tr, "johansen_reject": bool(tr > arms.johansen_crit(len(y)))}


def _discovery_window() -> int:
    """The discovery scan's window length (EPISODIC_WINDOW_BARS) -- read, not repeated."""
    import ast
    src = open(os.path.join(ROOT, "research", "wrds_deep_history_episodic_scan.py"), encoding="utf-8").read()
    for st in ast.parse(src).body:
        if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "EPISODIC_WINDOW_BARS":
            return int(ast.literal_eval(st.value))
    raise RuntimeError("EPISODIC_WINDOW_BARS not found in the discovery scan")


def _window(sym_a, sym_b, end):
    from episodic_pairs_adapter import _load_symbol
    a, b = _load_symbol(sym_a, "1D"), _load_symbol(sym_b, "1D")
    if a is None or b is None:
        return None
    s = pd.concat([np.log(a["close"].astype(float).abs()), np.log(b["close"].astype(float).abs())], axis=1,
                  keys=["a", "b"]).dropna()
    s.index = pd.to_datetime(s.index)
    win = _discovery_window()
    s = s[s.index <= pd.Timestamp(end)].tail(win)
    return s if len(s) >= win // 2 else None


def main():
    pool = pd.read_parquet(os.path.join(_R, "purity_pairs_pit_k1_clean.parquet"))
    pool = pool[pool["tf_label"].astype(str) == "1D"]
    w = pd.read_parquet(os.path.join(_R, "wrds_deep_history_episodic_scan_tier3_windows.parquet"),
                        columns=["symbol_a", "symbol_b", "window_end_date"])
    contrast = w.sample(len(pool), random_state=20261014)
    rows = []
    for kind, frame, endcol in (("pool", pool, "eligible_from"), ("contrast", contrast, "window_end_date")):
        for r in frame.itertuples():
            s = _window(r.symbol_a, r.symbol_b, getattr(r, endcol))
            if s is None:
                rows.append({"kind": kind, "symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "status": "no_data"}); continue
            try:
                res = compare_pair(s["a"].to_numpy(), s["b"].to_numpy())
                rows.append({"kind": kind, "symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "status": "ok",
                             "window_end": s.index.max(), **res})
            except Exception as e:
                rows.append({"kind": kind, "symbol_a": r.symbol_a, "symbol_b": r.symbol_b,
                             "status": f"error: {type(e).__name__}: {str(e)[:80]}"})
    D = pd.DataFrame(rows)
    D.to_parquet(OUT)
    ok = D[D["status"] == "ok"].copy()
    print(D.groupby(["kind", "status"]).size().to_string())
    ok["rel_dols"] = (ok["beta_dols"] - ok["beta_ols"]).abs() / ok["beta_ols"].abs()
    ok["rel_fmols"] = (ok["beta_fmols"] - ok["beta_ols"]).abs() / ok["beta_ols"].abs()
    for kind, g in ok.groupby("kind"):
        print(f"\n[{kind}] n={len(g)}: median |DOLS-OLS|/|OLS| {g['rel_dols'].median():.3f} (90th pct "
              f"{g['rel_dols'].quantile(.9):.3f}); median |FMOLS-OLS|/|OLS| {g['rel_fmols'].median():.3f}; "
              f"sign flips DOLS {int((np.sign(g['beta_dols']) != np.sign(g['beta_ols'])).sum())}")
        print(pd.crosstab(g["eg_reject"], g["johansen_reject"], rownames=["EG rejects"], colnames=["Johansen rejects"]).to_string())
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
