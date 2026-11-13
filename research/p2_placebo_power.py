"""
research/p2_placebo_power.py -- P2 placebo check (Ross 2026-11-13, "go for it"): false positives and power of the yearly
fixed-hedge share-class test on the E1 v2c placebo, BEFORE any real P2 result is read. No real test statistic is
computed here: real prices enter only through the placebo rebuild (their returns, reshuffled by build()'s day paths).

1. Null. For each v2c seed, the share-class family's legs are rebuilt exactly as placebo_discovery_e1.build() writes them
   (same seeded sample -> calendar / block / lambda / vol state / paths; sample_paths). Legs keep their same-day
   co-movement but lose any long-run tie, so every rejection is false. P2's own procedure is run unchanged
   (yearly_family_tests, test="fixed_adf", BH per year at ALPHA), on the KEPT (same-claim) family and the full UNGATED
   family, each with its own BH.
2. Power. In each pair-year, leg b is replaced by b* = a - c - u, where u is mean-reverting with the pair's OWN placebo
   spread noise: u_t = phi_t u_(t-1) + e_t, e_t = d(log a - log b)_t on the pair's common dates (scale, fat tails and
   volatility clustering from the data; no chosen spread s.d.). phi = 0.5 ** (1 / half-life) where the relation holds,
   1 (random walk) where it does not. The recursion runs over the pair's whole history from its first common date,
   so year y's segment starts from a state built by earlier noise only (nothing after year y enters year y).
   Variants: "full" (holds throughout), "starts_mid" (random walk until the middle common date of year y, then holds),
   "ends_mid" (holds until the middle of year y, then random walk; holds before year y).
   BH bounds: "one_true" = the planted pair's p joined with the OTHER pairs' null p-values of that year and seed;
   "all_true" = every pair of the year planted (same half-life, variant).
Outputs (output/research/): p2_placebo_power_null.parquet, p2_placebo_power_planted.parquet, p2_placebo_power_summary.parquet
Verify: debug/_verify_p2_placebo_power.py
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

import parquet_io  # noqa: E402
from p2_share_class_family import (CLASSIFICATION_CSV, adv_gated, apply_classification, family_by_year,  # noqa: E402
                                   leg_label, permno_labels)
from placebo_discovery_e1 import _log_price, placebo_series, sample_paths  # noqa: E402
from yearly_family_test import _pvalue, bh_reject, yearly_family_tests  # noqa: E402

SEEDS = (20261024, 20261025, 20261026, 20261027, 20261028)   # the E1 v2c chain's seeds
VERSION = "v2c"
YEARS = range(1990, 2025)
ALPHA = 0.05
HALF_LIVES = (5, 20, 60, 120)
# 2026-11-13: the AIC-lag ADF over-rejected on this null (7.5-8.1% at 5%); the two long-lag arms run beside it, same draws
TESTS = ("fixed_adf", "fixed_adf_schwert", "fixed_adf_tstat")                                 # E1's plant grid
VARIANTS = ("full", "starts_mid", "ends_mid")
OUT = os.path.join(ROOT, "output", "research")


def planted_spread(e: np.ndarray, phi_t: np.ndarray) -> np.ndarray:
    """u_t = phi_t * u_(t-1) + e_t, u_0 = e_0 (e: spread noise on the pair's common dates; NaN noise -> 0)."""
    from scipy.signal import lfilter
    e = np.nan_to_num(np.asarray(e, float))
    phi_t = np.asarray(phi_t, float)
    u = np.empty(len(e))
    if len(e) == 0:
        return u
    u[0] = e[0]
    # constant-phi runs from t = 1 on, each filtered with the previous value as its initial state
    cut = np.flatnonzero(np.diff(phi_t[1:]) != 0) + 2
    for s, t in zip(np.r_[1, cut], np.r_[cut, len(e)]):
        if t > s:
            ph = phi_t[s]
            u[s:t] = lfilter([1.0], [1.0, -ph], e[s:t], zi=[ph * u[s - 1]])[0]
    return u


def phi_path(dates: pd.DatetimeIndex, year: int, half_life: float, variant: str) -> np.ndarray:
    """Per common date: phi where the planted relation holds, 1 where it does not (see module doc)."""
    phi = 0.5 ** (1.0 / half_life)
    yr = dates.year == year
    pos = np.flatnonzero(yr)
    out = np.full(len(dates), phi)
    if variant == "full" or len(pos) == 0:
        return out
    mid = pos[len(pos) // 2]
    if variant == "starts_mid":
        out[: mid] = 1.0
    elif variant == "ends_mid":
        out[mid:] = 1.0
    else:
        raise ValueError(variant)
    return out


def planted_leg(la: pd.Series, lb: pd.Series, year: int, half_life: float, variant: str) -> tuple:
    """(a, b*) on the pair's common dates up to the end of `year`: a - b* = mean(a - b) + u."""
    j = pd.concat([la, lb], axis=1, join="inner").dropna()
    j = j[j.index.year <= year]
    a, b = j.iloc[:, 0], j.iloc[:, 1]
    s = (a - b).to_numpy()
    e = np.concatenate([[0.0], np.diff(s)])
    u = planted_spread(e, phi_path(j.index, year, half_life, variant))
    return a, pd.Series(a.to_numpy() - np.nanmean(s) - u, index=j.index)


def one_true_rejected(p_plant: float, p_null_others: np.ndarray, alpha: float = ALPHA) -> bool:
    """BH over [planted p] + the other pairs' null p-values of that year: is the planted pair rejected?"""
    if not np.isfinite(p_plant):
        return False
    return bool(bh_reject(np.concatenate([[p_plant], np.asarray(p_null_others, float)]), alpha)[0])


# The rebuild is exact only for the file list E1 v2c sampled from: build() draws its 800-file sample from the sorted list
# of *_1D.parquet, so ONE added file changes every seed's calendar / block / paths (review 2026-11-13, finding 4). The
# list is pinned (CachyOS cache, 2026-11-13, = E1 v2c seed 1's n_files 46,218) and checked by hash; each seed's mean
# block is checked against E1's own _e1_build.parquet where that seed has been built.
FILE_MANIFEST = os.path.join(ROOT, "research", "p2_placebo_file_manifest_v2c.txt")
MANIFEST_SHA256 = "b9c260332504fed306947d32a367c13d780575aa492203c1a36e2db9534f3366"   # sha256("\n".join(names))
E1_MEAN_BLOCK = {20261024: 3.499627, 20261025: 3.752784}                                 # from E1 v2c _e1_build


def manifest_files(src: str) -> list:
    import hashlib
    names = [l.strip() for l in open(FILE_MANIFEST, encoding="utf-8") if l.strip()]
    if hashlib.sha256("\n".join(names).encode()).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError(f"{FILE_MANIFEST} does not match its pinned hash")
    files = [os.path.join(src, n) for n in names]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise RuntimeError(f"{len(missing)} pinned files missing from {src}, e.g. {missing[:3]}")
    return files


def rebuild_legs(src: str, labels: dict, seed: int, version: str = VERSION) -> dict:
    """{permno: placebo log price} exactly as build() writes them for `seed` (labels: permno -> file label), sampled from
    the pinned E1 v2c file list (not whatever is in `src` now)."""
    files = manifest_files(src)
    rng = np.random.default_rng(seed)
    cal, L, lam, vol_lam, paths, src_pos = sample_paths(files, rng, seed, version)
    if seed in E1_MEAN_BLOCK and abs(L - E1_MEAN_BLOCK[seed]) > 5e-7:
        raise RuntimeError(f"seed {seed}: mean block {L:.6f} != E1's {E1_MEAN_BLOCK[seed]} -- rebuild is not E1's placebo")
    print(f"  seed {seed}: block {L:.4f}, lambda {lam}, calendar {len(cal)} days", flush=True)
    out = {}
    for p, lab in labels.items():
        lp = _log_price(parquet_io.read_parquet(os.path.join(src, f"{lab}_1D.parquet")))
        out[p] = placebo_series(lp, cal, paths, src_pos=src_pos, vol_lambda=vol_lam) if len(lp) >= 2 else lp
    return out


def families(src: str):
    n = parquet_io.read_parquet(os.path.join(src, "crsp_stocknames_all.parquet"))
    by_p = permno_labels(src)                         # BUG-D117 verified map (not full_us_market_label_map)
    ung = family_by_year(n, set(by_p), YEARS)
    kept, unc = apply_classification(ung, pd.read_csv(os.path.join(ROOT, CLASSIFICATION_CSV)))
    if any(unc.values()):
        raise RuntimeError(f"unclassified pairs in the family: {sum(map(len, unc.values()))}")
    legs = {x for v in ung.values() for pr in v for x in pr}
    labels = {p: leg_label(src, by_p[p]) for p in legs}
    # headline family (review 2026-11-13, finding 1): ADV-gated on REAL volume (the gate is part of the family
    # definition, point-in-time), then classified -- benchmarked on the placebo like the others
    from config import Config
    from rolling_adv_comparison import rolling_adv
    adv = {p: rolling_adv(parquet_io.read_parquet(os.path.join(src, f"{labels[p]}_1D.parquet"))) for p in legs}
    gated, _ = apply_classification(adv_gated(ung, adv, Config.STATS.ADV_FILTER_USD),
                                    pd.read_csv(os.path.join(ROOT, CLASSIFICATION_CSV)))
    return {"gated": gated, "kept": kept, "ungated": ung}, labels


def run_seed(LP: dict, fams: dict, seed: int, tests=TESTS):
    null_rows, plant_rows = [], []
    for test in tests:
        for fname, F in fams.items():
            N = yearly_family_tests(LP, F, alpha=ALPHA, years=list(YEARS), test=test)
            N["family"], N["seed"], N["test"] = fname, seed, test
            null_rows.append(N)
    # planted p-values once per testable pair-year of the widest family (kept is a subset of ungated; both families are
    # tested on the same LP dict, so the coverage rule -- and the testable set -- is identical)
    N = pd.concat(null_rows, ignore_index=True)
    U = N[np.isfinite(N["pvalue"])].drop_duplicates(["symbol_a", "symbol_b", "year"])
    for r in U.itertuples():
        for hl in HALF_LIVES:
            for v in VARIANTS:
                a, b = planted_leg(LP[r.symbol_a], LP[r.symbol_b], r.year, hl, v)
                ya, yb = a[a.index.year == r.year], b[b.index.year == r.year]
                for test in tests:
                    plant_rows.append({"symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "year": r.year, "seed": seed,
                                       "half_life": hl, "variant": v, "n_bars": len(ya), "test": test,
                                       "pvalue": _pvalue(ya, yb, test)})
    return N, pd.DataFrame(plant_rows)


def bh_bounds(N: pd.DataFrame, P: pd.DataFrame, alpha: float = ALPHA) -> pd.DataFrame:
    """Per planted row and family: one_true / all_true BH rejection (family = kept or ungated, its own year's m)."""
    out = []
    for (fname, test), Nf in N.groupby(["family", "test"]):
        Nf = Nf[np.isfinite(Nf["pvalue"])]
        keys = Nf.set_index(["seed", "year", "symbol_a", "symbol_b"])["pvalue"]
        Pf = P[P["test"] == test].merge(Nf[["seed", "year", "symbol_a", "symbol_b"]],
                                        on=["seed", "year", "symbol_a", "symbol_b"])
        for (seed, year, hl, v), g in Pf.groupby(["seed", "year", "half_life", "variant"]):
            nulls = keys.loc[(seed, year)]
            if not np.isfinite(g["pvalue"].to_numpy()).all():      # a NaN would silently shrink all_true's m
                raise RuntimeError(f"NaN planted p-value: {fname} {test} seed {seed} year {year} hl {hl} {v}")
            allrej = bh_reject(g["pvalue"].to_numpy(), alpha)
            for (r, ar) in zip(g.itertuples(), allrej):
                others = nulls.drop(index=(r.symbol_a, r.symbol_b)).to_numpy()
                out.append({"family": fname, "test": test, "seed": seed, "year": year, "half_life": hl, "variant": v,
                            "symbol_a": r.symbol_a, "symbol_b": r.symbol_b, "pvalue": r.pvalue, "m": len(nulls),
                            "one_true": one_true_rejected(r.pvalue, others, alpha), "all_true": bool(ar)})
    return pd.DataFrame(out)


def summarize(N: pd.DataFrame, B: pd.DataFrame) -> dict:
    Nt = N[np.isfinite(N["pvalue"])]
    size = Nt.groupby(["family", "test"]).agg(tests=("pvalue", "size"), **{f"p<{t:g}": ("pvalue", lambda x, t=t: float((x < t).mean()))
                                                               for t in (0.05, 0.01, 0.001)},
                                    bh_false=("rejected", "sum"))
    yrs = Nt.groupby(["family", "test", "seed", "year"])["rejected"].any().groupby(["family", "test"])
    size["family_years"] = yrs.size()
    size["years_with_false_bh"] = yrs.sum()
    power = B.groupby(["family", "test", "variant", "half_life"]).agg(n=("pvalue", "size"), one_true=("one_true", "mean"),
                                                              all_true=("all_true", "mean"),
                                                              p_lt_005=("pvalue", lambda x: float((x < 0.05).mean())))
    return {"size": size, "power": power}


def null_distribution(src: str, n_draws: int, tests=TESTS, fam_names=("gated", "kept")) -> pd.DataFrame:
    """Pre-registration's Monte Carlo null (draft 2026-11-13): the identical procedure on n_draws placebo rebuilds
    (seeds SEEDS[0] + k), per family x test: C = number of BH-confirmed pair-years, plus the testable count. Each draw
    keeps the whole structure (pairs repeating across years, same-year clustering). Checkpointed per draw; resumes."""
    out_path = os.path.join(OUT, "p2_placebo_null_distribution.parquet")
    fams, labels = families(src)
    fams = {k: fams[k] for k in fam_names}
    legs = {x for F in fams.values() for v in F.values() for pr in v for x in pr}
    labels = {p: labels[p] for p in legs}
    done = parquet_io.read_parquet(out_path) if os.path.exists(out_path) else pd.DataFrame()
    rows = done.to_dict("records")
    have = set(done["seed"]) if len(done) else set()
    for k in range(n_draws):
        seed = SEEDS[0] + k
        if seed in have:
            continue
        LP = rebuild_legs(src, labels, seed)
        for test in tests:
            for fname, F in fams.items():
                R = yearly_family_tests(LP, F, alpha=ALPHA, years=list(YEARS), test=test)
                rows.append({"seed": seed, "family": fname, "test": test, "confirmed": int(R["rejected"].sum()),
                             "testable": int(np.isfinite(R["pvalue"]).sum())})
        os.makedirs(OUT, exist_ok=True)
        pd.DataFrame(rows).to_parquet(out_path)
        print(f"  draw {k + 1}/{n_draws} (seed {seed}) saved", flush=True)
    D = pd.DataFrame(rows)
    print(D.groupby(["family", "test"])["confirmed"].describe(percentiles=[.5, .9, .95, .99]).round(2).to_string())
    return D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "output", "cache", "wrds"))
    ap.add_argument("--seeds", type=int, nargs="*", default=list(SEEDS))
    ap.add_argument("--tests", nargs="*", default=list(TESTS))
    ap.add_argument("--null-draws", type=int, default=0,
                    help="null-only Monte Carlo: seeds SEEDS[0] + k, k < N; gated + kept families; C = confirmed count")
    a = ap.parse_args()
    if a.null_draws:
        return null_distribution(a.src, a.null_draws, a.tests)
    fams, labels = families(a.src)
    print(f"family legs {len(labels)}; kept pair-years {sum(map(len, fams['kept'].values()))}, "
          f"ungated {sum(map(len, fams['ungated'].values()))}", flush=True)
    Ns, Ps = [], []
    for seed in a.seeds:
        LP = rebuild_legs(a.src, labels, seed)
        N, P = run_seed(LP, fams, seed, a.tests)
        Ns.append(N); Ps.append(P)
        print(f"  seed {seed}: null tests {int(np.isfinite(N['pvalue']).sum())}, planted {len(P)}", flush=True)
    N, P = pd.concat(Ns, ignore_index=True), pd.concat(Ps, ignore_index=True)
    B = bh_bounds(N, P)
    S = summarize(N, B)
    os.makedirs(OUT, exist_ok=True)
    N.to_parquet(os.path.join(OUT, "p2_placebo_power_null.parquet"))
    B.to_parquet(os.path.join(OUT, "p2_placebo_power_planted.parquet"))
    S["power"].reset_index().to_parquet(os.path.join(OUT, "p2_placebo_power_summary.parquet"))
    pd.set_option("display.width", 200)
    print("\n== null (every rejection false)\n" + S["size"].round(4).to_string())
    print("\n== power\n" + S["power"].round(3).to_string())
    print("\n== power by seed (full, one_true)\n" + B[B.variant == "full"].groupby(["family", "test", "half_life", "seed"])
          ["one_true"].mean().unstack("seed").round(3).to_string())


if __name__ == "__main__":
    main()
