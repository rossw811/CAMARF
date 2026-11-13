"""
research/arma_half_life_pools.py -- design B of docs/decisions/DECISIONS_2026-11-13_model_real_data.md (Ross
2026-11-13: "ill take your recommendations"). Do ARMA (BIC order, dominant-root) half-lives predict a pool spread's
next-window decay better than production's AR(1) half-life (the one behind time stops and the half-life filter)?

Inputs are production's OWN: each pair is rebuilt exactly as research/regenerate_pool_spread_series.py does
(episodic_pairs_adapter._load_aligned -> AnalysisPipeline._build_pair_result) while SpreadModel.rolling_half_life_hedged
and SpreadModel.fit_pair are wrapped to RECORD their inputs (log a, log b, hedge, window on the real rows; formation_n,
real rows). Check: the recorded call's output reproduces the A8 file's half_life_rolling at every real row.
Per refresh window t (production's schedule: every 21 bars, window = the pair's adaptive mean window) that ends in the
trading era (real row >= formation end) and has a finite prior hedge h = hedge[t - window]:
  - AR(1): SpreadModel.half_life_ar1(seg), seg = la - h * lb over the window (production's own estimate);
  - ARMA: spread_arma.fit_arma_bic(seg) dominant-root half-life (IRF half-life kept as descriptive);
  - realised (target): the next non-overlapping window's spread la - h' * lb, h' = hedge[t] (the hedge just before that
    window opens), decay = smallest h >= 0 with acf(1 + h) <= 0.5 * acf(1), log-interpolated (noise-robust; addendum).
Point-in-time: predictions use rows <= t; the target uses rows (t, t + window] only.
Decision rule (declared): ARMA counts as better only if its |log error| is lower in >= 60% of evaluable windows AND the
median ARMA / AR(1) ratio is outside [0.8, 1.25]; then a time-stop arm on ARMA half-lives is proposed as a new
pre-registered amendment. Otherwise descriptive.
Verify: debug/_verify_arma_half_life_pools.py
"""
import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

REFRESH_STEP = 21                      # SpreadModel.rolling_half_life_hedged's default step (asserted at capture)
K1_SAMPLE, K1_SEED = 80, 20261113
OUT = os.path.join(ROOT, "output", "research")


def realised_decay(seg: np.ndarray, max_lag: int = None) -> float:
    """Smallest h >= 0 with acf(1 + h) <= 0.5 * acf(1), log-interpolated between lags; NaN if acf(1) <= 0 or no
    crossing within max_lag (default len // 2). Noise-robust: white noise added to an AR(1) scales every acf(k >= 1) by
    the same constant, which cancels in the ratio."""
    s = np.asarray(seg, float)
    s = s[np.isfinite(s)]
    n = s.size
    if n < 30:
        return np.nan
    x = s - s.mean()
    den = float(np.dot(x, x))
    if den <= 0:
        return np.nan
    L = max_lag or n // 2
    acf = np.array([np.dot(x[:-k], x[k:]) / den for k in range(1, L + 2)])
    if acf[0] <= 0:
        return np.nan
    r = acf / acf[0]
    hit = np.nonzero(r[1:] <= 0.5)[0]
    if hit.size == 0:
        return np.nan
    h = int(hit[0]) + 1                                   # r[h] <= 0.5 < r[h - 1], r index = lag - 1 = h
    lo, hi = r[h - 1], r[h]
    if hi <= 0 or lo <= 0:
        return float(h - 1 + (lo - 0.5) / (lo - hi))
    return float(h - 1 + (np.log(lo) - np.log(0.5)) / (np.log(lo) - np.log(hi)))


def capture_pair(a: str, b: str, eligible_from) -> dict:
    """Rebuild one pool pair through production's path, recording the rolling half-life's inputs and fit_pair's
    formation rows. Returns {la, lb, h, window, form_real, hl_out, file_hl} or raises."""
    from analysis import AnalysisPipeline
    from research import episodic_pairs_adapter as ad
    rec = {}
    restore = install_recorders(rec)
    try:
        al = ad._load_aligned(a, b, "1D", as_of_date=None, preloaded=None)
        if al is None:
            raise RuntimeError("alignment failed")
        built = AnalysisPipeline._build_pair_result({"symbol_a": a, "symbol_b": b, "eligible_from": eligible_from}, al, "1D")
        if built is None:
            raise RuntimeError("_build_pair_result returned None")
    finally:
        restore()
    if "la" not in rec:
        raise RuntimeError("rolling half-life was not called")
    rec["built_hl"] = np.asarray(built[1].get("half_life_rolling", []), float)
    disk = os.path.join(ad._RESULTS_DIR, ad._tf_dir("1D"), f"spread_series_{a}_{b}.parquet")
    rec["disk_hl"] = (pd.read_parquet(disk, columns=["half_life_rolling"])["half_life_rolling"].to_numpy(float)
                      if os.path.exists(disk) else None)
    return rec


def install_recorders(rec: dict):
    """Wrap SpreadModel.rolling_half_life_hedged (primary call, bias_correct False) and SpreadModel.fit_pair so they
    record their inputs into `rec`; behaviour unchanged (each wrapper returns the original's result). Returns restore()."""
    from analysis import SpreadModel
    orig_roll, orig_fit = SpreadModel.rolling_half_life_hedged, SpreadModel.fit_pair

    def roll(log_a, log_b, hedge, window=252, step=21, bias_correct=False):
        out = orig_roll(log_a, log_b, hedge, window=window, step=step, bias_correct=bias_correct)
        if not bias_correct:
            rec.update(la=np.array(log_a), lb=np.array(log_b), h=np.array(hedge), window=int(window), step=int(step),
                       hl_out=out)
        return out

    def fit(log_a, log_b, hedge_series, hedge_static, clean_mask=None, static_fallback=True, formation_n=None, **kw):
        spread = SpreadModel.compute_spread(log_a, log_b, hedge_series, hedge_static, static_fallback=static_fallback)
        cm = np.ones(spread.size, bool) if clean_mask is None else clean_mask
        real_pos = np.flatnonzero(cm & np.isfinite(spread))
        rec.update(form_real=int((real_pos < formation_n).sum()) if formation_n is not None else 0, real_pos=real_pos)
        return orig_fit(log_a, log_b, hedge_series, hedge_static, clean_mask=clean_mask,
                        static_fallback=static_fallback, formation_n=formation_n, **kw)

    SpreadModel.rolling_half_life_hedged, SpreadModel.fit_pair = staticmethod(roll), staticmethod(fit)

    def restore():
        SpreadModel.rolling_half_life_hedged, SpreadModel.fit_pair = orig_roll, orig_fit
    return restore


def _same(x, y) -> bool:
    return x is not None and y is not None and len(x) == len(y) and bool(
        np.allclose(np.nan_to_num(x, nan=-1.0), np.nan_to_num(y, nan=-1.0)))


def evaluate_windows(rec: dict) -> pd.DataFrame:
    """One row per trading-era refresh window: AR(1), ARMA, realised next-window decay."""
    from analysis import SpreadModel
    from spread_arma import fit_arma_bic
    la, lb, h, w, step = rec["la"], rec["lb"], rec["h"], rec["window"], rec["step"]
    n = la.size
    rows = []
    for t in range(w - 1, n, step):
        if t < rec["form_real"] or t - w < 0 or not np.isfinite(h[t - w]) or t + w >= n or not np.isfinite(h[t]):
            continue
        seg = la[t - w + 1: t + 1] - h[t - w] * lb[t - w + 1: t + 1]
        nxt = la[t + 1: t + w + 1] - h[t] * lb[t + 1: t + w + 1]
        ar1 = SpreadModel.half_life_ar1(seg)
        am = fit_arma_bic(seg)
        rows.append({"t": t, "window": w, "hl_ar1": ar1, "hl_arma": am["half_life"], "hl_arma_irf": am["half_life_irf"],
                     "arma_p": am["p"], "arma_q": am["q"], "oscillating": am["oscillating"],
                     "realised": realised_decay(nxt)})
    return pd.DataFrame(rows)


def _one(task):
    a, b, ef, pool = task
    try:
        rec = capture_pair(a, b, ef)
        internal = _same(rec["built_hl"][rec["real_pos"]], rec["hl_out"])     # recorded call = what the result holds
        on_disk = _same(rec["built_hl"], rec["disk_hl"])                       # = the A8 spread file
        W = evaluate_windows(rec)
        W["symbol_a"], W["symbol_b"], W["pool"] = a, b, pool
        W["recorded_is_used"], W["reproduces_a8_file"] = internal, on_disk
        return W, None
    except Exception as e:
        return None, f"{a}/{b}: {e}"


def summarize(W: pd.DataFrame) -> pd.DataFrame:
    ok = W[np.isfinite(W.hl_ar1) & np.isfinite(W.hl_arma) & np.isfinite(W.realised) & (W.realised > 0)]
    e1 = np.abs(np.log(ok.hl_ar1 / ok.realised)); e2 = np.abs(np.log(ok.hl_arma / ok.realised))
    rows = []
    for pool, g in ok.assign(e1=e1, e2=e2).groupby("pool"):
        ratio = float(np.median(g.hl_arma / g.hl_ar1))
        better = float((g.e2 < g.e1).mean())
        rows.append({"pool": pool, "windows": int((W.pool == pool).sum()), "evaluable": len(g), "pairs": g.symbol_a.str.cat(g.symbol_b).nunique(),
                     "median_ar1": float(g.hl_ar1.median()), "median_arma": float(g.hl_arma.median()),
                     "median_realised": float(g.realised.median()), "median_ratio_arma_ar1": ratio,
                     "arma_better_share": better, "median_abs_log_err_ar1": float(g.e1.median()),
                     "median_abs_log_err_arma": float(g.e2.median()),
                     "decision_arma_better": bool(better >= 0.6 and not (0.8 <= ratio <= 1.25))})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 4))
    a = ap.parse_args()
    import parquet_io
    tasks = []
    for k in (2, 1):
        P = parquet_io.read_parquet(os.path.join(OUT, f"purity_pairs_pit_k{k}_clean.parquet"))
        P = P[P["tf_label"] == "1D"]
        if k == 1:
            k2 = {(r.symbol_a, r.symbol_b) for r in tasks_k2}
            P = P[[(x, y) not in k2 for x, y in zip(P.symbol_a, P.symbol_b)]]
            P = P.sample(n=min(K1_SAMPLE, len(P)), random_state=K1_SEED)
        else:
            tasks_k2 = list(P.itertuples())
        tasks += [(r.symbol_a, r.symbol_b, r.eligible_from, f"k{k}") for r in P.itertuples()]
    print(f"{len(tasks)} pairs (k2 all, k1 sample {K1_SAMPLE} not in k2)", flush=True)
    Ws, errs = [], []
    with ProcessPoolExecutor(a.workers) as ex:
        for i, (W, err) in enumerate(ex.map(_one, tasks)):
            if err:
                errs.append(err)
            elif W is not None and len(W):
                Ws.append(W)
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(tasks)} pairs", flush=True)
    W = pd.concat(Ws, ignore_index=True)
    W.to_parquet(os.path.join(OUT, "arma_half_life_pools_windows.parquet"))
    print(f"errors {len(errs)}: {errs[:5]}")
    g = W.groupby(["symbol_a", "symbol_b"])[["recorded_is_used", "reproduces_a8_file"]].first()
    print("pairs: recorded inputs are the ones used", g.recorded_is_used.value_counts().to_dict(),
          "| rebuild reproduces the A8 file's half_life_rolling", g.reproduces_a8_file.value_counts().to_dict())
    S = summarize(W)
    S.to_parquet(os.path.join(OUT, "arma_half_life_pools_summary.parquet"))
    pd.set_option("display.width", 250)
    print(S.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
