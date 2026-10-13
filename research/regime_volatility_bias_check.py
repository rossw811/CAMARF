"""
research/regime_volatility_bias_check.py -- endogeneity arm (b) (Ross 2026-10-13: comparison first, main pathway only
if the comparison supports it). Is the Tier-3 prefilter's crisis spike (PAPER_MAGNITUDE M-058: candidate counts jump
4-10x in the 2008-09 and 2020 windows) real co-movement, or the Forbes & Rigobon (2002) volatility bias -- measured
correlation rises with the common factor's variance even when every loading is unchanged?

Per discovery window (2520 trading days ending at each Tier-3 window end date), on a fixed random sample of CRSP
stocks with complete returns in the window:
  raw_share   -- share of pairs with |Pearson rho| >= MIN_PEARSON_CORR (the prefilter's rule)
  adj_share   -- the same with the Forbes-Rigobon adjusted rho* = rho / sqrt(1 + delta (1 - rho^2)),
                 delta = var(market in window) / var(market, full sample) - 1 (full-sample reference; FR's formula,
                 delta > -1 for calmer-than-average windows)
  rescaled_share -- exact one-factor version for PAIRS: each stock's market component rescaled to the reference
                 volatility (FR's formula is exact only for correlation WITH the factor; for two stocks it removes most,
                 not all, of the mechanical rise -- shown on synthetic data, 2026-10-13)
  null_share  -- the share in a CONSTANT-BETA world: r_i = beta_i m_t + e_i with the window's ACTUAL market path m_t,
                 and each stock's beta and idiosyncratic sd estimated once over its full history (the mechanical part)
Market: Fama-French daily mktrf + rf (output/cache/wrds/ff_factors_3_daily.parquet).
Verdict printed: crisis-window / calm-window ratios for raw, adjusted and null (crisis = windows containing 2008-09 or
2020-03; calm = the rest).
Output: output/research/regime_volatility_bias_check.parquet. Test: debug/_verify_regime_volatility_bias_check.py
Usage: python research/regime_volatility_bias_check.py [--n-symbols 2000]
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_W = os.path.join(ROOT, "output", "cache", "wrds")
OUT = os.path.join(ROOT, "output", "research", "regime_volatility_bias_check.parquet")


def fr_adjust(rho, delta):
    """Forbes-Rigobon heteroskedasticity-adjusted correlation."""
    rho = np.asarray(rho, dtype=float)
    return rho / np.sqrt(1.0 + delta * (1.0 - rho ** 2))


def window_delta(mkt_window, ref_var: float) -> float:
    """Relative increase of the window's market variance over the reference."""
    return float(np.var(mkt_window) / ref_var - 1.0)


def candidate_share(R: np.ndarray, threshold: float, delta: float = None) -> float:
    """Share of distinct pairs (rows of R = series) with |rho| >= threshold; FR-adjusted when delta is given."""
    C = np.corrcoef(R)
    iu = np.triu_indices_from(C, k=1)
    rho = C[iu]
    if delta is not None:
        rho = fr_adjust(rho, delta)
    return float(np.mean(np.abs(rho) >= threshold))


def rescaled_share(R: np.ndarray, mkt_window, ref_sd: float, threshold: float) -> float:
    """Exact one-factor de-volatilisation for PAIRS: each series' market component (window OLS beta) is rescaled to the
    reference volatility, r' = r - b m + b m (ref_sd / sd(m)); loadings and idiosyncratic parts are kept, so a genuine
    rise in loadings survives. Forbes-Rigobon's formula is exact only for a series' correlation with the factor."""
    m = np.asarray(mkt_window, dtype=float)
    mc = m - m.mean()
    Rc = R - R.mean(axis=1, keepdims=True)
    b = Rc @ mc / (mc @ mc)
    Rp = R + np.outer(b, m) * (ref_sd / m.std() - 1.0)
    return candidate_share(Rp, threshold)


def simulate_null_share(mkt_window, betas, idio_sd, threshold, rng) -> float:
    """Constant-beta world with the window's actual market path."""
    m = np.asarray(mkt_window, dtype=float)
    R = np.outer(betas, m) + rng.normal(0, 1, (len(betas), len(m))) * np.asarray(idio_sd)[:, None]
    return candidate_share(R, threshold)


def _market():
    f = pd.read_parquet(os.path.join(_W, "ff_factors_3_daily.parquet"))
    f["date"] = pd.to_datetime(f["date"])
    return (f.set_index("date")["mktrf"] + f.set_index("date")["rf"]).astype(float).sort_index()


def main():
    from config import Config
    from data_wrds import label_permno_map
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-symbols", type=int, default=2000)
    a = ap.parse_args()
    thr = Config.UNIVERSE.MIN_PEARSON_CORR
    win = 2520
    mkt = _market()
    ref_var = float(mkt.var())
    rng = np.random.default_rng(20261013)
    labels = sorted(label_permno_map())
    labels = [l for l in labels if os.path.exists(os.path.join(_W, f"{l}_1D.parquet"))]
    pick = rng.choice(labels, size=min(a.n_symbols, len(labels)), replace=False)
    rets = {}
    for l in pick:
        d = pd.read_parquet(os.path.join(_W, f"{l}_1D.parquet"), columns=["close_total_return"])
        d.index = pd.to_datetime(d.index)
        r = np.log(d["close_total_return"].astype(float).abs()).diff()
        rets[l] = r[~r.index.duplicated(keep="last")]
    R = pd.DataFrame(rets).reindex(mkt.index)
    # constant betas / idiosyncratic sd over each stock's full history
    beta, idio = {}, {}
    for l in R.columns:
        ok = R[l].notna()
        if ok.sum() < 500:
            continue
        x, y = mkt[ok].to_numpy(), R.loc[ok, l].to_numpy()
        b = np.cov(x, y)[0, 1] / np.var(x)
        beta[l], idio[l] = b, float(np.std(y - b * x))
    ends = sorted(pd.to_datetime(pd.read_parquet(
        os.path.join(ROOT, "output", "research", "wrds_deep_history_episodic_scan_tier3_windows.parquet"),
        columns=["window_end_date"])["window_end_date"]).unique())
    rows = []
    for e in ends:
        idx = mkt.index[mkt.index <= e][-win:]
        if len(idx) < win:
            continue
        Rw = R.loc[idx, [c for c in R.columns if c in beta]]
        Rw = Rw.loc[:, Rw.notna().all()]
        if Rw.shape[1] < 100:
            continue
        mw = mkt.loc[idx].to_numpy()
        dlt = window_delta(mw, ref_var)
        cols = list(Rw.columns)
        rows.append({"window_end": e, "n_symbols": len(cols), "delta": dlt,
                     "raw_share": candidate_share(Rw.to_numpy().T, thr),
                     "adj_share": candidate_share(Rw.to_numpy().T, thr, delta=dlt),
                     "rescaled_share": rescaled_share(Rw.to_numpy().T, mw, float(np.sqrt(ref_var)), thr),
                     "null_share": simulate_null_share(mw, [beta[c] for c in cols], [idio[c] for c in cols], thr, rng),
                     "crisis": bool(((idx >= "2008-01-01") & (idx <= "2009-12-31")).any()
                                    or ((idx >= "2020-02-15") & (idx <= "2020-04-30")).any())})
        print(f"{e.date()} n={len(cols)} delta={dlt:+.2f} raw={rows[-1]['raw_share']:.4f} "
              f"adj={rows[-1]['adj_share']:.4f} resc={rows[-1]['rescaled_share']:.4f} null={rows[-1]['null_share']:.4f} crisis={rows[-1]['crisis']}", flush=True)
    D = pd.DataFrame(rows)
    D.to_parquet(OUT)
    g = D.groupby("crisis")[["raw_share", "adj_share", "rescaled_share", "null_share"]].mean()
    print(g.to_string())
    if True in g.index and False in g.index:
        r = g.loc[True] / g.loc[False]
        print(f"crisis/calm ratio: raw {r['raw_share']:.2f}x, FR-adjusted {r['adj_share']:.2f}x, factor-rescaled "
              f"{r['rescaled_share']:.2f}x, constant-beta null {r['null_share']:.2f}x")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
