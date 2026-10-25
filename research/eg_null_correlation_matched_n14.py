"""
research/eg_null_correlation_matched_n14.py -- N14: size (and power) of the production EG screen on its OWN candidate
population (Ross, DECISIONS_2026-10-21 #5). C-008 (D11) measured size on RANDOM pairs; the screen only tests pairs
whose returns correlate at |corr| >= threshold (0.6 in research/full_universe_correlation_prefilter.py, the 10-year
screen C-008 calibrates; Config.UNIVERSE.MIN_PEARSON_CORR = 0.40 in the discovery scan), and cross-sectional
dependence or non-synchronous closes could inflate rejection there.

Null: for each sampled candidate pair, a stationary block bootstrap (Politis & Romano 1994) of the pair's JOINT
returns -- one index path for both legs, so contemporaneous and short-lag cross-correlation and each leg's volatility
clustering are kept -- re-integrated to log prices from the real first values. Resampling blocks breaks any long-run
relation, so a rejection is a false positive. Mean block length: Politis & White (2004) as corrected by Patton,
Politis & White (2009) (arch.bootstrap.optimal_block_length, 'stationary'), the larger of the two legs'. Within a
block the pair's short-run error correction survives, so long blocks bias the null toward rejection: block lengths
are reported, and the size is also given for pairs with L <= the median.
Power: the same bootstrapped leg A with B rebuilt as mu + beta * A + u, u an AR(1) with half-life h (10/40/120 bars)
whose stationary s.d. is the real pair's OLS residual s.d. -- a cointegrated pair with the candidate's own scale.

Candidates: on the screen's calendar (eg_null_calibration_montecarlo.load_aligned: load_full_universe, WRDS priority,
align_to_common_calendar 10 years; sealed rows never present), returns from CointScanner._build_log_price_map. A
random anchor's return correlation with every symbol (pairwise-complete, >= min_obs overlap) gives its candidates;
one is drawn per anchor; exact duplicates (|corr| >= 0.999999) and structural pairs (filter_structural_pairs) are
dropped as the screen does. Test: production eg_pvalue_pair (both directions, max p), MIN_OVERLAP_BY_TF floor.
Size CI: pair-cluster bootstrap over pairs (draws within a pair are not independent).
Output: output/research/eg_null_correlation_matched_n14_{tf}.parquet (per draw) + _summary.parquet.
Usage: python research/eg_null_correlation_matched_n14.py --tf 1h [--threshold 0.6 0.4] [--n-pairs 300] [--draws 5]
       (1D loads ~44.7k daily series: CachyOS only). Check: debug/_verify_eg_null_correlation_matched_n14.py
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config  # noqa: E402

SEED = 20261021
HALF_LIVES = (10, 40, 120)
DUP_CORR = 0.999999


def stationary_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap index path of length n (geometric block lengths, wrap-around)."""
    p = 1.0 / max(float(mean_block), 1.0)
    idx = np.empty(n, dtype=int)
    idx[0] = rng.integers(n)
    new = rng.random(n) < p
    starts = rng.integers(n, size=n)
    for t in range(1, n):
        idx[t] = starts[t] if new[t] else (idx[t - 1] + 1) % n
    return idx


def block_length(la: np.ndarray, lb: np.ndarray) -> float:
    from arch.bootstrap import optimal_block_length
    r = np.column_stack([np.diff(la), np.diff(lb)])
    return float(max(1.0, optimal_block_length(r)["stationary"].max()))


def joint_bootstrap(la: np.ndarray, lb: np.ndarray, mean_block: float, rng: np.random.Generator):
    """Both legs' returns resampled on ONE index path, re-integrated from the real first log prices."""
    r = np.column_stack([np.diff(la), np.diff(lb)])
    rs = r[stationary_indices(len(r), mean_block, rng)]
    return (np.concatenate([[la[0]], la[0] + np.cumsum(rs[:, 0])]),
            np.concatenate([[lb[0]], lb[0] + np.cumsum(rs[:, 1])]))


def cointegrated_version(la, lb, half_life: float, rng: np.random.Generator, mean_block: float = None,
                         spread_sd: float = None):
    """Power arm: bootstrapped A, and B = mu + beta * A + AR(1) spread with the given half-life whose stationary s.d.
    is `spread_sd` (v2: a fixed grid -- review 2026-10-24: at the pair's own levels-residual s.d., power was mostly a
    signal-to-noise artefact) or, when None, the real pair's OLS residual s.d. (v1)."""
    L = block_length(la, lb) if mean_block is None else mean_block
    A, _ = joint_bootstrap(la, lb, L, rng)
    X = np.column_stack([np.ones(len(la)), la])
    (mu, beta), *_ = np.linalg.lstsq(X, lb, rcond=None)
    s = float(np.std(lb - X @ np.array([mu, beta]))) if spread_sd is None else float(spread_sd)
    phi = 0.5 ** (1.0 / half_life)
    u = np.zeros(len(la))
    eps = rng.normal(size=len(la)) * s * np.sqrt(1 - phi ** 2)
    u[0] = rng.normal() * s
    for t in range(1, len(u)):
        u[t] = phi * u[t - 1] + eps[t]
    return A, mu + beta * A + u


def sample_candidates(rets: pd.DataFrame, threshold: float, n_pairs: int, rng: np.random.Generator,
                      min_obs: int = 252, max_anchors: int = None):
    """Anchor sampling: each random anchor's pairwise-complete return correlation with every symbol; one candidate
    with threshold <= |corr| < DUP_CORR drawn per anchor; each unordered pair at most once."""
    R = rets.to_numpy(dtype=float)
    M = np.isfinite(R)
    Z = np.where(M, R, 0.0)
    syms = list(rets.columns)
    order = rng.permutation(len(syms))[: (max_anchors or len(syms))]
    out, seen = [], set()
    for a in order:
        if len(out) >= n_pairs:
            break
        m = M & M[:, [a]]
        n = m.sum(0)
        ra = np.where(m, Z[:, [a]], 0.0)
        rb = np.where(m, Z, 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            ma, mb = ra.sum(0) / n, rb.sum(0) / n
            cov = (ra * rb).sum(0) / n - ma * mb
            va = (ra ** 2).sum(0) / n - ma ** 2
            vb = (rb ** 2).sum(0) / n - mb ** 2
            c = np.abs(cov / np.sqrt(va * vb))
        c[a] = np.nan
        ok = np.flatnonzero((n >= min_obs) & (c >= threshold) & (c < DUP_CORR))
        ok = [b for b in ok if frozenset((syms[a], syms[b])) not in seen]
        if not ok:
            continue
        b = int(rng.choice(ok))
        seen.add(frozenset((syms[a], syms[b])))
        out.append((syms[a], syms[b]))
    return out


def candidate_returns(aligned: dict, min_obs: int) -> pd.DataFrame:
    """Returns for candidate correlations: each symbol's log returns between ITS OWN consecutive valid prices, placed
    on the union of timestamps (pairwise-complete correlation then uses bars both legs have). This equals the intraday
    discovery scan's returns for US listings sharing session timestamps (research/intraday_episodic_scan.py).
    2026-10-22: differencing adjacent rows of the common calendar -- which is also what gap_aware_returns /
    UniverseFilter.build_returns_matrix do -- gave almost no returns at 1h, where the union of timestamps includes
    crypto's 24/7 hours and non-US sessions (42 finite returns per symbol on CachyOS). Symbols with fewer than min_obs
    returns are dropped."""
    cols = {}
    for s_, df in aligned.items():
        if df is None or "close" not in df.columns:
            continue
        c = pd.to_numeric(df["close"], errors="coerce")
        c = c[np.isfinite(c.to_numpy()) & (c.to_numpy() > 0)]
        r = np.log(c).diff().iloc[1:]
        r = r[~r.index.duplicated(keep="last")]
        if len(r) >= min_obs:
            cols[s_] = r
    return pd.DataFrame(cols)


SPREAD_SDS = (0.02, 0.05, 0.10)   # v2 power grid, log-price units


def screen_sample(cands: pd.DataFrame, n: int, rng: np.random.Generator, ids: dict = None) -> pd.DataFrame:
    """v2 (review 2026-10-24): n pairs drawn UNIFORMLY from the screen's own candidate list after the screen's filters
    (exact duplicates |corr| >= DUP_CORR, filter_structural_pairs with the correlations, the same-company rule) -- the
    anchor sampler weighted pairs by ~1/degree."""
    from universe_loader import filter_structural_pairs
    sys.path.insert(0, os.path.join(ROOT, "research"))
    from full_universe_eg_confirmation import drop_same_company
    c = cands[cands["pearson_corr"].abs() < DUP_CORR] if "pearson_corr" in cands.columns else cands
    recs = c.to_dict("records")
    recs, _ = filter_structural_pairs(recs)
    if ids is not None:
        recs, _ = drop_same_company(recs, ids)
    k = min(n, len(recs))
    pick = rng.choice(len(recs), size=k, replace=False)
    return pd.DataFrame([recs[i] for i in sorted(pick)])


def _cluster_ci(rej: pd.Series, groups: pd.Series, rng: np.random.Generator, reps: int = 2000):
    g = pd.DataFrame({"r": rej.astype(float).to_numpy(), "g": groups.to_numpy()}).groupby("g")["r"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    k = rng.integers(len(g), size=(reps, len(g)))
    est = s[k].sum(1) / c[k].sum(1)
    return float(np.quantile(est, 0.025)), float(np.quantile(est, 0.975))


def run(tf: str, thresholds, n_pairs: int, draws: int, candidates_dir: str = None):
    from analysis import CointScanner, eg_pvalue_pair
    from data import longest_gap_respecting_segment
    from research.eg_null_calibration_montecarlo import load_aligned
    from universe_loader import filter_structural_pairs
    rng = np.random.default_rng(SEED)
    aligned = load_aligned(tf)
    lp = CointScanner._build_log_price_map(aligned, sorted(aligned))
    floor = max(Config.STATS.MIN_OVERLAP_BY_TF.get(tf, 252), 60)
    if candidates_dir is None:
        rets = candidate_returns(aligned, floor)
    del aligned
    rows = []
    sample_sets = []
    if candidates_dir is not None:   # v2: the screen's own candidates, uniformly; the screen's 60-bar EG floor
        import glob as _g
        sys.path.insert(0, os.path.join(ROOT, "research"))
        from clean_pool_identity_pairs import build_company_ids
        C = pd.concat([pd.read_parquet(f) for f in sorted(_g.glob(os.path.join(candidates_dir, "*.parquet")))],
                      ignore_index=True)
        ids = build_company_ids(sorted(set(C["symbol_a"]) | set(C["symbol_b"])))
        S_ = screen_sample(C, n_pairs, rng, ids=ids)
        floor = 60
        thr_label = float(round(C["pearson_corr"].abs().min(), 2)) if "pearson_corr" in C.columns else -1.0
        print(f"[{tf}] v2: {len(C)} screen candidates in {candidates_dir}; testing {len(S_)} uniform pairs")
        sample_sets.append((thr_label, list(zip(S_["symbol_a"], S_["symbol_b"]))))
    else:
        for thr in thresholds:
            cand = sample_candidates(rets, thr, n_pairs * 2, rng, min_obs=floor)
            kept, dropped = filter_structural_pairs([{"symbol_a": a, "symbol_b": b} for a, b in cand])
            print(f"[{tf} thr {thr}] {len(cand)} candidates sampled (anchor sampler), {len(dropped)} structural dropped")
            sample_sets.append((thr, [(p["symbol_a"], p["symbol_b"]) for p in kept][:n_pairs]))
    for thr, pairs in sample_sets:
        for a, b in pairs:
            keep = longest_gap_respecting_segment(np.isfinite(lp[a]) & np.isfinite(lp[b]), tf)
            la, lb = lp[a][keep], lp[b][keep]
            if len(la) < floor:
                continue
            p_real, _ = eg_pvalue_pair(la, lb, Config.ANALYSIS.EG_MAX_LAG, tf)
            L = block_length(la, lb)
            base = {"tf": tf, "threshold": thr, "symbol_a": a, "symbol_b": b, "n_bars": len(la), "block_length": L,
                    "corr": float(np.corrcoef(np.diff(la), np.diff(lb))[0, 1]), "p_real": p_real}
            for d in range(draws):
                A, B = joint_bootstrap(la, lb, L, rng)
                p0, _ = eg_pvalue_pair(A, B, Config.ANALYSIS.EG_MAX_LAG, tf)
                row = {**base, "draw": d, "p_null": p0}
                for h in HALF_LIVES:
                    for sd in ((None,) + SPREAD_SDS if candidates_dir is not None else (None,)):
                        A1, B1 = cointegrated_version(la, lb, h, rng, L, spread_sd=sd)
                        key = f"p_power_hl{h}" if sd is None else f"p_power_hl{h}_sd{sd}"
                        row[key] = eg_pvalue_pair(A1, B1, Config.ANALYSIS.EG_MAX_LAG, tf)[0]
                rows.append(row)
    D = pd.DataFrame(rows)
    v2 = "_v2" if candidates_dir is not None else ""
    out = os.path.join(ROOT, "output", "research", f"eg_null_correlation_matched_n14_{tf}{v2}.parquet")
    D.to_parquet(out)
    S = []
    for thr, g in D.groupby("threshold"):
        key = g["symbol_a"] + "|" + g["symbol_b"]
        rej = g["p_null"] < 0.05
        lo, hi = _cluster_ci(rej, key, rng)
        short = g[g["block_length"] <= g["block_length"].median()]
        s = {"tf": tf, "threshold": thr, "n_pairs": key.nunique(), "n_draws": len(g), "size": float(rej.mean()),
             "size_ci_lo": lo, "size_ci_hi": hi, "size_short_blocks": float((short["p_null"] < 0.05).mean()),
             "block_length_median": float(g["block_length"].median()),
             "real_rejection_rate": float((g.drop_duplicates(["symbol_a", "symbol_b"])["p_real"] < 0.05).mean())}
        for h in HALF_LIVES:
            s[f"power_hl{h}"] = float((g[f"p_power_hl{h}"] < 0.05).mean())
            for sd in SPREAD_SDS:
                c = f"p_power_hl{h}_sd{sd}"
                if c in g.columns:
                    s[f"power_hl{h}_sd{sd}"] = float((g[c] < 0.05).mean())
        q = pd.qcut(g["block_length"].rank(method="first"), 4, labels=False)   # review D2: size by block length
        for i in range(4):
            gi = g[q == i]
            s[f"size_block_q{i + 1}"] = float((gi["p_null"] < 0.05).mean())
            s[f"block_q{i + 1}_median"] = float(gi["block_length"].median())
        long_ = g[g["n_bars"] >= 252]
        s["size_nbars_ge252"] = float((long_["p_null"] < 0.05).mean()) if len(long_) else float("nan")
        s["sampling"] = "uniform over screen candidates" if candidates_dir is not None else "anchor (one per anchor)"
        S.append(s)
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()})
    pd.DataFrame(S).to_parquet(out.replace(".parquet", "_summary.parquet"))
    print(f"-> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h", choices=["15m", "1h", "1D", "1M"])
    ap.add_argument("--threshold", type=float, nargs="+", default=[0.6, Config.UNIVERSE.MIN_PEARSON_CORR])
    ap.add_argument("--n-pairs", type=int, default=300)
    ap.add_argument("--draws", type=int, default=5)
    ap.add_argument("--candidates-dir", default=None,
                    help="v2: sample uniformly from this screen candidate chunk dir (the screen's own population)")
    a = ap.parse_args()
    run(a.tf, a.threshold, a.n_pairs, a.draws, a.candidates_dir)


if __name__ == "__main__":
    main()
