"""
research/placebo_discovery_e1.py -- E1: end-to-end placebo discovery and pipeline power (Ross 2026-10-24: "build, yes
to all"). How many pairs does the WHOLE discovery pipeline (prefilter, windowed tiers, point-in-time BH, pool cleaning)
put in the pool when no pair is cointegrated, and how many truly cointegrated pairs does it find?

Placebo universe (`build`): for each calendar year one stationary-bootstrap index path over that year's trading days,
SHARED by every series, so returns keep their cross-sectional (and crisis-year) correlation; resampling breaks every
long-run relation. Each series keeps its own dates (listing span, real holes) and its real volume (the liquidity
gates see real liquidity); its placebo log price starts at its real first value. Where the shared path lands on a date
the series has no return (e.g. it listed mid-year), one of its own returns from the same year is drawn instead
(counted: `fallback_share`). Mean block length: the median of per-series Politis & White (2004) / Patton, Politis &
White (2009) estimates over a seeded sample (not one estimate on an index: 68 days, 2026-10-24 -- see
choose_block_length). Pre-seal data only (the caches hold no sealed rows).
Plants: N_PLANTS Compustat Global series (>= 10 years) get a partner B = mu + beta * A + AR(1) spread with half-life
in HALF_LIVES (trading days), spread s.d. PLANT_SD in log price, labelled GVKEY9xxxxx_01W (an unused GVKEY range; no
CCM/Capital IQ link, so the same-company rule never removes them; Compustat-style legs are not S&P-gated, so they are
tested -- power is measured for the international / mixed arm).
Isolation: the placebo cache is a separate directory; the pipeline runs in a separate checkout whose output/cache/wrds
is that directory (debug/_tmp_chain_e1.sh), so no real cache or output is touched. Non-price reference files (maps,
links, membership) are symlinked unchanged; coarse price files are not linked.
Score (`score`): pool pairs (k1/k2) -> false positives (no plant) and recovered plants by half-life.
Usage: python research/placebo_discovery_e1.py build --dst <dir> [--seed 20261024]
       python research/placebo_discovery_e1.py score --research <checkout>/output/research --dst <dir>
Check: debug/_verify_placebo_discovery_e1.py
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SEED = 20261024
N_PLANTS = 48
HALF_LIVES = (5, 20, 60, 120)
PLANT_SD = 0.05
PLANT_MIN_DAYS = 2520
PRICE_COLS = ("open", "high", "low", "close", "close_usd", "close_total_return")


def choose_block_length(returns_by_series: dict) -> float:
    """Median of the per-series Politis-White stationary-bootstrap block lengths (as N14 uses per pair). 2026-10-24: one
    estimate on an equal-weight index gave 68 days (stale prices make the index autocorrelated) -- blocks that long keep
    a real pair's error correction inside each block, so the placebo was not a null."""
    from arch.bootstrap import optimal_block_length
    Ls = []
    for r in returns_by_series.values():
        x = pd.Series(r).dropna().to_numpy()
        if len(x) >= 250:
            Ls.append(float(optimal_block_length(x)["stationary"].iloc[0]))
    return float(max(1.0, np.median(Ls))) if Ls else 1.0


def year_index_paths(cal: pd.DatetimeIndex, mean_block: float, seed: int = SEED) -> dict:
    """{year: positions into `cal`} -- a stationary-bootstrap path over that year's dates, one per year."""
    from research.eg_null_correlation_matched_n14 import stationary_indices
    rng = np.random.default_rng(seed)
    out = {}
    years = pd.DatetimeIndex(cal).year
    for y in np.unique(years):
        pos = np.flatnonzero(years == y)
        out[int(y)] = pos[stationary_indices(len(pos), mean_block, rng)]
    return out


def source_positions(cal: pd.DatetimeIndex, paths: dict) -> np.ndarray:
    """map[p] = calendar position whose return calendar day p borrows (the shared path of p's year)."""
    years = pd.DatetimeIndex(cal).year
    m = np.empty(len(cal), dtype=int)
    for y, path in paths.items():
        pos = np.flatnonzero(years == y)
        m[pos] = path
    return m


def placebo_series(log_price: pd.Series, cal: pd.DatetimeIndex, paths: dict, rng=None, stats: dict = None,
                   src_pos: np.ndarray = None) -> pd.Series:
    """Placebo log price on the series' own valid dates: the return on date t is the series' real return on the shared
    path's date for t (same-year fallback, counted, when it has none there)."""
    rng = rng or np.random.default_rng(0)
    lp = log_price.dropna()
    if len(lp) < 2:
        return lp
    src_pos = source_positions(cal, paths) if src_pos is None else src_pos
    rc = lp.reindex(cal).diff().to_numpy()                # real returns on consecutive calendar days
    p = cal.get_indexer(lp.index[1:])                     # -1 for dates off the calendar (weekend stamps)
    r = np.full(len(p), np.nan)
    ok = p >= 0
    r[ok] = rc[src_pos[p[ok]]]
    bad = ~np.isfinite(r)
    if bad.any():                                         # same-year fallback from the series' own returns
        own = lp.diff().iloc[1:]
        yrs = own.index.year.to_numpy()
        vals = own.to_numpy()
        for y in np.unique(yrs[bad]):
            pool = vals[(yrs == y) & np.isfinite(vals)]
            sel = bad & (yrs == y)
            r[sel] = rng.choice(pool, size=int(sel.sum())) if len(pool) else 0.0
    if stats is not None:
        stats["fallback"] = stats.get("fallback", 0) + int(bad.sum())
        stats["returns"] = stats.get("returns", 0) + len(r)
    out = np.concatenate([[lp.iloc[0]], lp.iloc[0] + np.cumsum(r)])
    return pd.Series(out, index=lp.index)


def plant_label(k: int) -> str:
    return f"GVKEY9{k:05d}_01W"


def plant_pair(A: pd.Series, half_life: float, rng, sd: float = PLANT_SD):
    """B = mu + beta * A + u on A's dates, u AR(1) with the given half-life and stationary s.d. `sd`."""
    beta = float(rng.uniform(0.5, 1.5))
    mu = float(rng.normal(0, 0.5))
    phi = 0.5 ** (1.0 / half_life)
    u = np.empty(len(A))
    u[0] = rng.normal() * sd
    eps = rng.normal(size=len(A)) * sd * np.sqrt(1 - phi ** 2)
    for t in range(1, len(A)):
        u[t] = phi * u[t - 1] + eps[t]
    return pd.Series(mu + beta * A.to_numpy() + u, index=A.index), {"beta": beta, "mu": mu, "half_life": half_life}


def write_placebo_file(src: pd.DataFrame, placebo_log_price: pd.Series, out_path: str) -> None:
    """Source frame's dates/volume, every price column replaced by exp(placebo log price)."""
    d = pd.DataFrame(index=placebo_log_price.index)
    d.index.name = src.index.name
    px = np.exp(placebo_log_price.to_numpy())
    for c in PRICE_COLS:
        if c in src.columns:
            d[c] = px
    if "close" not in d.columns:
        d["close"] = px
    if "volume" in src.columns:
        d["volume"] = src["volume"].reindex(d.index).to_numpy()
    tmp = out_path + ".tmp"
    d.to_parquet(tmp)
    os.replace(tmp, out_path)


def _log_price(df: pd.DataFrame) -> pd.Series:
    col = next((c for c in ("close_total_return", "close_usd", "close") if c in df.columns), None)
    s = pd.to_numeric(df[col], errors="coerce") if col else pd.Series(dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s[np.isfinite(s.to_numpy()) & (s.to_numpy() > 0)]
    return np.log(s[~s.index.duplicated(keep="last")].sort_index())


def build(src: str, dst: str, seed: int = SEED):
    import seal
    os.makedirs(dst, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src, "*_1D.parquet")))
    rng = np.random.default_rng(seed)
    # calendar + block length from an equal-weight index of a seeded sample (memory: never all series at once)
    sample = rng.choice(files, size=min(800, len(files)), replace=False)
    rets = pd.concat({os.path.basename(f): _log_price(pd.read_parquet(f)).diff() for f in sample}, axis=1)
    cal = pd.DatetimeIndex(rets.index).sort_values()
    cal = cal[cal.dayofweek < 5]
    L = choose_block_length({c: rets[c] for c in rets.columns})
    paths = year_index_paths(cal, L, seed)
    src_pos = source_positions(cal, paths)
    print(f"{len(files)} 1D files; calendar {cal.min().date()}..{cal.max().date()} ({len(cal)} days); mean block {L:.2f}")
    stats, long_gvkey = {}, []
    for i, f in enumerate(files):
        src_df = pd.read_parquet(f)
        lp = _log_price(src_df)
        if len(lp) < 2:
            continue
        pl = placebo_series(lp, cal, paths, np.random.default_rng(seed + i), stats, src_pos)
        write_placebo_file(src_df, pl, os.path.join(dst, os.path.basename(f)))
        lab = os.path.basename(f)[:-len("_1D.parquet")]
        if lab.startswith("GVKEY") and "_seg" not in lab and len(pl) >= PLANT_MIN_DAYS:
            long_gvkey.append(lab)
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{len(files)}", flush=True)
    plants = []
    for k, base in enumerate(sorted(rng.choice(long_gvkey, size=min(N_PLANTS, len(long_gvkey)), replace=False))):
        hl = HALF_LIVES[k % len(HALF_LIVES)]
        A_df = pd.read_parquet(os.path.join(dst, f"{base}_1D.parquet"))
        A = np.log(A_df["close"])
        B, info = plant_pair(A, hl, np.random.default_rng(seed + 10_000 + k))
        write_placebo_file(A_df, B, os.path.join(dst, f"{plant_label(k)}_1D.parquet"))
        plants.append({"plant": plant_label(k), "base": base, **info})
    pd.DataFrame(plants).to_parquet(os.path.join(dst, "_e1_plants.parquet"), index=False)
    # non-price reference files (maps, links, membership), unchanged; coarse price files are NOT linked
    n_link = 0
    for f in os.listdir(src):
        p = os.path.join(src, f)
        if f.endswith(".parquet") and seal.kind_of_path(p) is None and not os.path.exists(os.path.join(dst, f)):
            os.symlink(os.path.abspath(p), os.path.join(dst, f))
            n_link += 1
    fb = stats.get("fallback", 0) / max(stats.get("returns", 1), 1)
    pd.DataFrame([{"seed": seed, "mean_block": L, "n_files": len(files), "n_plants": len(plants),
                   "fallback_share": fb, "n_reference_links": n_link}]).to_parquet(os.path.join(dst, "_e1_build.parquet"))
    print(f"placebo written to {dst}: {len(plants)} plants, same-year fallback share {fb:.2%}, {n_link} reference files linked")


def score(research: str, dst: str) -> pd.DataFrame:
    plants = pd.read_parquet(os.path.join(dst, "_e1_plants.parquet"))
    truth = {frozenset((r.plant, r.base)): r.half_life for r in plants.itertuples()}
    rows = []
    for k in (1, 2):
        p = os.path.join(research, f"purity_pairs_pit_k{k}_clean.parquet")
        P = pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame(columns=["symbol_a", "symbol_b", "tf_label"])
        P = P[P["tf_label"] == "1D"] if len(P) else P
        keys = [frozenset((a, b)) for a, b in zip(P["symbol_a"], P["symbol_b"])]
        hit = [kk for kk in keys if kk in truth]
        plant_syms = set(plants["plant"])
        fp = [kk for kk in keys if kk not in truth and not (kk & plant_syms)]
        row = {"pool": f"k{k}", "pool_pairs": len(keys), "false_positives": len(fp),
               "plant_pairs_found": len(hit), "plants_total": len(truth),
               "plant_side_pairs_other": len([kk for kk in keys if kk not in truth and (kk & plant_syms)])}
        for hl in HALF_LIVES:
            n = sum(1 for v in truth.values() if v == hl)
            row[f"recovered_hl{hl}"] = f"{sum(1 for kk in hit if truth[kk] == hl)}/{n}"
        rows.append(row)
    R = pd.DataFrame(rows)
    print(R.to_string(index=False))
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["build", "score"])
    ap.add_argument("--src", default=os.path.join(ROOT, "output", "cache", "wrds"))
    ap.add_argument("--dst", required=True)
    ap.add_argument("--research", default=None)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    if a.phase == "build":
        build(a.src, a.dst, a.seed)
    else:
        R = score(a.research, a.dst)
        R.to_parquet(os.path.join(a.dst, "_e1_score.parquet"), index=False)


if __name__ == "__main__":
    main()
