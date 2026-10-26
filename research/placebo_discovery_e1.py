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

v2 (review 2026-10-25, Ross "yes to all"; docs/ERRATA.md "E1 placebo discovery v1"):
  - returns are each series' own bar-to-bar returns (a return spanning > 5 missing business days is never a source),
    and a path date the series has no bar on maps to its next own bar that year -- one deterministic rule shared by
    every series with the same calendar (v1 drew 8.3% of returns independently, which cut US Tier-1 candidates by 43%
    and left identical real series non-identical, so duplicate removal never ran). Dates outside the series' own
    coverage that year map by rank (no repeated returns).
  - placebo volume is set so the placebo USD dollar volume equals the real one (the ADV gate saw placebo price x real
    volume, median +0.43 log); CRSP no-trade days (close NaN, total return present) keep close NaN (D18) and
    quote_only is carried over.
  - plants: per arm (US-gated and international), bases that clear the ADV gate on >= PLANT_MIN_ADV_SHARE of days (US
    also S&P 500 members on >= PLANT_MIN_MEMBER_SHARE), PLANTS_PER_CELL per (half-life, spread s.d.) cell on the real
    pool's scale (SPREAD_SDS; real median OLS residual s.d. 0.145). US plants are PERMNO99xxxx with their base's
    membership spells (install_us_plant_refs replaces the symlinked reference files by copies; the real files are
    never written).
  - reading: window-level tail rates by arm and false_share_by_arm (placebo tail rate x real windows tested / real
    windows at or below the arm's BH cutoff), per seed; tier1_arm_ratios guards the candidate-count gap.
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
HALF_LIVES = (5, 20, 60, 120)
SPREAD_SDS = (0.05, 0.10, 0.15, 0.20)
PLANTS_PER_CELL = 4
PLANT_MIN_DAYS = 2520
PLANT_MIN_ADV_SHARE = 0.5
PLANT_MIN_MEMBER_SHARE = 0.5
TIER1_MIN_RATIO = 0.8
US_PLANT_PERMNO0 = 990000
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


def own_valid_returns(lp: pd.Series) -> pd.Series:
    """Bar-to-bar log returns on the series' own dates; NaN where the bar follows more than data._MAX_FILL_BARS missing
    business days (a genuine hole: that multi-week move is never a source return)."""
    from data import _MAX_FILL_BARS
    lp = lp.dropna()
    d = lp.index.values.astype("datetime64[D]")
    r = np.diff(lp.to_numpy())
    gaps = np.busday_count(d[:-1], d[1:]) - 1
    r = np.where(gaps > _MAX_FILL_BARS, np.nan, r)
    return pd.Series(r, index=lp.index[1:])


def placebo_series(log_price: pd.Series, cal: pd.DatetimeIndex, paths: dict, rng=None, stats: dict = None,
                   src_pos: np.ndarray = None) -> pd.Series:
    """Placebo log price on the series' own valid dates: the return on own date t is the series' own valid return at
    the shared path's source date for t, or at its next own bar that year when it has none there (v2: one shared,
    deterministic rule -- no random draws; `rng` is unused, kept for the v1 signature). Source dates outside the
    series' own coverage that year map by rank within the year."""
    lp = log_price.dropna()
    if len(lp) < 2:
        return lp
    src_pos = source_positions(cal, paths) if src_pos is None else src_pos
    R = own_valid_returns(lp)
    ok = np.isfinite(R.to_numpy())
    vd, vv = R.index[ok], R.to_numpy()[ok]
    t = lp.index[1:]
    pos = np.clip(cal.searchsorted(t, side="right") - 1, 0, len(cal) - 1)   # calendar day at or before t
    S = cal[src_pos[pos]]
    out = np.zeros(len(t))
    cal_years = pd.DatetimeIndex(cal).year.to_numpy()
    vy, sy = vd.year.to_numpy(), S.year.to_numpy()
    n_shift = n_zero = 0
    for y in np.unique(sy):
        sel = np.flatnonzero(sy == y)
        Vy, vals = vd[vy == y], vv[vy == y]
        if len(Vy) == 0:
            n_zero += len(sel)
            continue
        Sy = S[sel]
        j = Vy.searchsorted(Sy)
        outside = (Sy < Vy[0]) | (Sy > Vy[-1])
        if outside.any():
            cy = np.flatnonzero(cal_years == y)
            rank = cal.get_indexer(Sy[outside]) - cy[0]
            j[outside] = np.minimum((rank * len(Vy)) // max(len(cy), 1), len(Vy) - 1)
        out[sel] = vals[j]
        n_shift += int((Vy[j] != Sy).sum())
    if stats is not None:
        stats["shifted"] = stats.get("shifted", 0) + n_shift
        stats["zero"] = stats.get("zero", 0) + n_zero
        stats["random"] = stats.get("random", 0)
        stats["returns"] = stats.get("returns", 0) + len(t)
    return pd.Series(np.concatenate([[lp.iloc[0]], lp.iloc[0] + np.cumsum(out)]), index=lp.index)


def plant_label(k: int) -> str:
    return f"GVKEY9{k:05d}_01W"


def plant_pair(A: pd.Series, half_life: float, rng, sd: float = SPREAD_SDS[0]):
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


def write_placebo_file(src: pd.DataFrame, placebo_log_price: pd.Series, out_path: str, label: str = None) -> None:
    """Source frame's dates, every price column replaced by exp(placebo log price). v2: CRSP no-trade days (non-GVKEY
    label, close NaN, total return present) keep close NaN (D18); quote_only is carried over; volume is set so the
    placebo USD dollar volume (dollar_volume.usd_dollar_volume) equals the real one."""
    from dollar_volume import usd_dollar_volume
    d = pd.DataFrame(index=placebo_log_price.index)
    d.index.name = src.index.name
    px = np.exp(placebo_log_price.to_numpy())
    for c in PRICE_COLS:
        if c in src.columns:
            d[c] = px
    if "close" not in d.columns:
        d["close"] = px
    if label is not None and not str(label).startswith("GVKEY") and {"close", "close_total_return"} <= set(src.columns):
        nt = (src["close"].reindex(d.index).isna() & src["close_total_return"].reindex(d.index).notna()).to_numpy()
        d.loc[nt, "close"] = np.nan
    if "quote_only" in src.columns:
        d["quote_only"] = src["quote_only"].reindex(d.index).fillna(False).astype(bool).to_numpy()
    if "volume" in src.columns:
        dv = usd_dollar_volume(src, label).reindex(d.index)
        unit = usd_dollar_volume(d.assign(volume=1.0), label)          # USD value of one unit at the placebo price
        d["volume"] = (dv / unit.replace(0, np.nan)).to_numpy()
    tmp = out_path + ".tmp"
    d.to_parquet(tmp)
    os.replace(tmp, out_path)


def _log_price(df: pd.DataFrame) -> pd.Series:
    col = next((c for c in ("close_total_return", "close_usd", "close") if c in df.columns), None)
    s = pd.to_numeric(df[col], errors="coerce") if col else pd.Series(dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s[np.isfinite(s.to_numpy()) & (s.to_numpy() > 0)]
    return np.log(s[~s.index.duplicated(keep="last")].sort_index())


def choose_plant_bases(C: pd.DataFrame) -> pd.DataFrame:
    """Plant base candidates that the pipeline can test: >= PLANT_MIN_DAYS bars, rolling ADV >= the gate on at least
    PLANT_MIN_ADV_SHARE of days, and (US arm) an S&P 500 member on at least PLANT_MIN_MEMBER_SHARE of days."""
    ok = (C["n_days"] >= PLANT_MIN_DAYS) & (C["adv_share"] >= PLANT_MIN_ADV_SHARE)
    ok &= (C["arm"] != "us") | (C["member_share"].fillna(0) >= PLANT_MIN_MEMBER_SHARE)
    return C[ok].reset_index(drop=True)


def plant_grid() -> pd.DataFrame:
    """One row per plant: arm x half-life x spread s.d. x PLANTS_PER_CELL. Labels: US PERMNO99xxxx (fake PERMNO,
    unused range), international GVKEY9xxxxx_01W."""
    rows, k = [], {"us": 0, "international": 0}
    for arm in ("us", "international"):
        for hl in HALF_LIVES:
            for sd in SPREAD_SDS:
                for _ in range(PLANTS_PER_CELL):
                    i = k[arm]
                    lab = f"PERMNO{US_PLANT_PERMNO0 + i}" if arm == "us" else plant_label(i)
                    rows.append({"plant": lab, "arm": arm, "half_life": hl, "spread_sd": sd})
                    k[arm] += 1
    return pd.DataFrame(rows)


_REF_MEMBERSHIP, _REF_LABELMAP = "sp500_membership_history.parquet", "wrds_label_permno_final.parquet"


def _replace_link_with_copy(path: str) -> pd.DataFrame:
    """Read a (possibly symlinked) reference file and turn the link into a private copy, so a later write never
    reaches the real file the link points at."""
    df = pd.read_parquet(path)
    if os.path.islink(path):
        os.remove(path)                      # removes the link only
        df.to_parquet(path, index=False)
    return df


def install_us_plant_refs(dst: str, plants: pd.DataFrame) -> None:
    """US plants resolve to their fake PERMNO (label map) and carry their base's S&P 500 membership spells, so the
    membership gate treats a planted pair exactly as its base."""
    us = plants[plants["arm"] == "us"]
    if us.empty:
        return
    lm = _replace_link_with_copy(os.path.join(dst, _REF_LABELMAP))
    mb = _replace_link_with_copy(os.path.join(dst, _REF_MEMBERSHIP))
    base_permno = lm.dropna(subset=["permno"]).set_index("label")["permno"]
    new_lm, new_mb = [], []
    for r in us.itertuples():
        fake = int(str(r.plant)[len("PERMNO"):])
        if r.base not in base_permno.index:
            raise ValueError(f"US plant base {r.base} has no PERMNO")
        new_lm.append({"label": r.plant, "permno": float(fake), "source": "agree", "return_scores": ""})
        sp = mb[mb["permno"] == int(base_permno[r.base])].copy()
        sp["permno"] = fake
        new_mb.append(sp)
    add = pd.DataFrame(new_lm)[list(lm.columns)].astype({c: lm[c].dtype for c in lm.columns})
    lm = pd.concat([lm, add], ignore_index=True)
    mb = pd.concat([mb] + new_mb, ignore_index=True).astype({"permno": mb["permno"].dtype})
    lm.to_parquet(os.path.join(dst, _REF_LABELMAP), index=False)
    mb.to_parquet(os.path.join(dst, _REF_MEMBERSHIP), index=False)


def _member_share(dates: pd.DatetimeIndex, spells: pd.DataFrame) -> float:
    if spells is None or spells.empty or len(dates) == 0:
        return 0.0
    v = dates.values
    inside = np.zeros(len(v), bool)
    for a, b in zip(spells["mbrstartdt"].values, spells["mbrenddt"].values):
        inside |= (v >= a) & (v <= b)
    return float(inside.mean())


def build(src: str, dst: str, seed: int = SEED):
    import seal
    from config import Config
    from research.rolling_adv_comparison import rolling_adv
    os.makedirs(dst, exist_ok=True)
    files = sorted(glob.glob(os.path.join(src, "*_1D.parquet")))
    rng = np.random.default_rng(seed)
    # calendar + block length from a seeded sample (memory: never all series at once)
    sample = rng.choice(files, size=min(800, len(files)), replace=False)
    rets = pd.concat({os.path.basename(f): _log_price(pd.read_parquet(f)).diff() for f in sample}, axis=1)
    cal = pd.DatetimeIndex(rets.index).sort_values()
    cal = cal[cal.dayofweek < 5]
    L = choose_block_length({c: rets[c] for c in rets.columns})
    paths = year_index_paths(cal, L, seed)
    src_pos = source_positions(cal, paths)
    print(f"{len(files)} 1D files; calendar {cal.min().date()}..{cal.max().date()} ({len(cal)} days); mean block {L:.2f}")
    thr = Config.STATS.ADV_FILTER_USD
    mb = pd.read_parquet(os.path.join(src, _REF_MEMBERSHIP))
    lmap = pd.read_parquet(os.path.join(src, _REF_LABELMAP)).dropna(subset=["permno"]).set_index("label")["permno"]
    stats, cand = {}, []
    for i, f in enumerate(files):
        lab = os.path.basename(f)[:-len("_1D.parquet")]
        src_df = pd.read_parquet(f)
        lp = _log_price(src_df)
        if len(lp) < 2:
            continue
        pl = placebo_series(lp, cal, paths, stats=stats, src_pos=src_pos)
        write_placebo_file(src_df, pl, os.path.join(dst, os.path.basename(f)), label=lab)
        if "_seg" not in lab and len(pl) >= PLANT_MIN_DAYS and "volume" in src_df.columns:
            arm = "international" if lab.startswith("GVKEY") else "us"
            adv = rolling_adv(src_df)
            share = float((adv >= thr).mean()) if len(adv) else 0.0
            msh = np.nan
            if arm == "us":
                if lab not in lmap.index:
                    continue
                msh = _member_share(pd.DatetimeIndex(lp.index), mb[mb["permno"] == int(lmap[lab])])
            cand.append({"label": lab, "arm": arm, "adv_share": share, "member_share": msh, "n_days": len(pl)})
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{len(files)}", flush=True)
    C = pd.DataFrame(cand)
    B = choose_plant_bases(C)
    G = plant_grid()
    G["base"] = ""
    for arm in ("us", "international"):
        pool = B.loc[B["arm"] == arm, "label"].to_numpy()
        need = int((G["arm"] == arm).sum())
        print(f"plant bases {arm}: {len(pool)} clear the gates (need {need})", flush=True)
        if len(pool) < need:
            raise RuntimeError(f"only {len(pool)} {arm} plant bases clear the gates; {need} needed")
        G.loc[G["arm"] == arm, "base"] = rng.choice(sorted(pool), size=need, replace=False)
    plants = []
    for k, r in enumerate(G.itertuples()):
        base_src = pd.read_parquet(os.path.join(src, f"{r.base}_1D.parquet"))
        A = _log_price(pd.read_parquet(os.path.join(dst, f"{r.base}_1D.parquet")))
        B_lp, info = plant_pair(A, r.half_life, np.random.default_rng(seed + 10_000 + k), sd=r.spread_sd)
        write_placebo_file(base_src.drop(columns=["quote_only"], errors="ignore"), B_lp,
                           os.path.join(dst, f"{r.plant}_1D.parquet"), label=r.plant)
        plants.append({"plant": r.plant, "base": r.base, "arm": r.arm, "spread_sd": r.spread_sd, **info})
    P = pd.DataFrame(plants)
    # non-price reference files (maps, links, membership), unchanged; coarse price files are NOT linked
    n_link = 0
    for f in os.listdir(src):
        p = os.path.join(src, f)
        if f.endswith(".parquet") and seal.kind_of_path(p) is None and not os.path.exists(os.path.join(dst, f)):
            os.symlink(os.path.abspath(p), os.path.join(dst, f))
            n_link += 1
    install_us_plant_refs(dst, P)
    P.to_parquet(os.path.join(dst, "_e1_plants.parquet"), index=False)
    C.to_parquet(os.path.join(dst, "_e1_plant_candidates.parquet"), index=False)
    n = max(stats.get("returns", 1), 1)
    pd.DataFrame([{"seed": seed, "mean_block": L, "n_files": len(files), "n_plants": len(P),
                   "shifted_share": stats.get("shifted", 0) / n, "zero_share": stats.get("zero", 0) / n,
                   "random_share": 0.0, "n_reference_links": n_link}]).to_parquet(os.path.join(dst, "_e1_build.parquet"))
    print(f"placebo written to {dst}: {len(P)} plants; source dates shifted to the next own bar "
          f"{stats.get('shifted', 0) / n:.2%}, zero-filled {stats.get('zero', 0) / n:.3%}; {n_link} reference files linked")


def tier1_arm_ratios(placebo_t1: pd.DataFrame, real_t1: pd.DataFrame):
    """Per-arm placebo / real Tier-1 candidate counts and whether every arm is at least TIER1_MIN_RATIO (the v1
    placebo had 57% of the real US candidates)."""
    from research.clean_pool_identity_pairs import discovery_arm
    arm = lambda D: pd.Series([discovery_arm(a, b) for a, b in zip(D["symbol_a"], D["symbol_b"])],
                              dtype=object).value_counts()
    pa, ra = arm(placebo_t1), arm(real_t1)
    ratios = {k: float(pa.get(k, 0) / ra[k]) for k in ra.index if ra[k] > 0}
    return ratios, all(v >= TIER1_MIN_RATIO for v in ratios.values())


def false_share_by_arm(real_w: pd.DataFrame, placebo_w: pd.DataFrame) -> pd.DataFrame:
    """Per arm: the real run's BH cutoff (largest p among its rejected windows), the placebo's rate at or below it,
    the expected number of null windows at or below it among the real windows tested (rate x n), and that as a share
    of the real windows at or below the cutoff. Every real window is treated as null, so est_false is conservative."""
    rows = []
    for a, g in real_w.groupby("arm"):
        rej = g.loc[g["fdr_rejected"].astype(bool), "pvalue"]
        c = float(rej.max()) if len(rej) else np.nan
        pw = placebo_w.loc[placebo_w["arm"] == a, "pvalue"]
        rate = float((pw <= c).mean()) if len(pw) and np.isfinite(c) else np.nan
        n_at = int((g["pvalue"] <= c).sum()) if np.isfinite(c) else 0
        est = rate * len(g) if np.isfinite(rate) else np.nan
        rows.append({"arm": a, "cutoff": c, "n_real_windows": len(g), "n_real_at_cutoff": n_at,
                     "placebo_rate": rate, "est_false": est, "false_share": est / n_at if n_at else np.nan})
    return pd.DataFrame(rows)


def _windows_by_arm(path: str, cols=("symbol_a", "symbol_b", "pvalue", "fdr_rejected")) -> pd.DataFrame:
    from research.clean_pool_identity_pairs import discovery_arm
    W = pd.read_parquet(path, columns=list(cols))
    keys = W["symbol_a"].astype(str) + "|" + W["symbol_b"].astype(str)
    m = {k: discovery_arm(*k.split("|")) for k in pd.unique(keys)}
    W["arm"] = keys.map(m).to_numpy()
    return W


def score(research: str, dst: str, real_research: str = None) -> dict:
    """Pool counts by arm (false positives = non-plant pairs), planted-pair recovery by arm x half-life x spread s.d.
    (tested = at least one Tier-3 window), placebo window tail rates by arm, and the real run's false share by arm."""
    plants = pd.read_parquet(os.path.join(dst, "_e1_plants.parquet"))
    pkey = [frozenset((r.plant, r.base)) for r in plants.itertuples()]
    plant_syms = set(plants["plant"])
    W = _windows_by_arm(os.path.join(research, "wrds_deep_history_episodic_scan_tier3_windows.parquet"))
    is_plant = W["symbol_a"].isin(plant_syms) | W["symbol_b"].isin(plant_syms)
    tested = {frozenset(x) for x in zip(W.loc[is_plant, "symbol_a"], W.loc[is_plant, "symbol_b"])}
    pool_rows, rec = [], []
    for k in (1, 2):
        p = os.path.join(research, f"purity_pairs_pit_k{k}_clean.parquet")
        P = pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame(columns=["symbol_a", "symbol_b", "tf_label", "arm"])
        P = P[P["tf_label"] == "1D"] if len(P) else P
        keys = [frozenset((a, b)) for a, b in zip(P["symbol_a"], P["symbol_b"])]
        arms = P["arm"].tolist() if "arm" in P.columns else [""] * len(keys)
        found = set(keys) & set(pkey)
        for a in sorted(set(arms)):
            fp = sum(1 for kk, aa in zip(keys, arms) if aa == a and not (kk & plant_syms))
            pool_rows.append({"pool": f"k{k}", "arm": a, "false_positives": fp,
                              "pool_pairs": sum(1 for aa in arms if aa == a)})
        for kk, r in zip(pkey, plants.itertuples()):
            rec.append({"pool": f"k{k}", "arm": r.arm, "half_life": r.half_life, "spread_sd": r.spread_sd,
                        "tested": kk in tested, "found": kk in found})
    out = {"pool": pd.DataFrame(pool_rows), "recovery": pd.DataFrame(rec)}
    Wn = W[~is_plant]
    rates = [{"arm": a, "n_windows": len(g), **{f"p<{t:g}": float((g["pvalue"] < t).mean()) for t in (0.05, 1e-3, 1e-4)}}
             for a, g in Wn.groupby("arm")]
    out["placebo_rates"] = pd.DataFrame(rates)
    if real_research:
        RW = _windows_by_arm(os.path.join(real_research, "wrds_deep_history_episodic_scan_tier3_windows.parquet"))
        out["false_share"] = false_share_by_arm(RW, Wn)
    for name, D in out.items():
        print(f"\n== {name}")
        if name == "recovery":
            print(D.groupby(["pool", "arm", "half_life"])[["tested", "found"]].mean().unstack("half_life").round(2).to_string())
            print(D.groupby(["pool", "arm", "spread_sd"])["found"].mean().unstack("spread_sd").round(2).to_string())
        else:
            print(D.to_string(index=False))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["build", "score", "check_tier1"])
    ap.add_argument("--src", default=os.path.join(ROOT, "output", "cache", "wrds"))
    ap.add_argument("--dst", default=None)
    ap.add_argument("--research", default=None)
    ap.add_argument("--real-research", default=None)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    if a.phase == "build":
        build(a.src, a.dst, a.seed)
    elif a.phase == "check_tier1":
        f = "wrds_deep_history_episodic_scan_tier1.parquet"
        cols = ["symbol_a", "symbol_b"]
        ratios, ok = tier1_arm_ratios(pd.read_parquet(os.path.join(a.research, f), columns=cols),
                                      pd.read_parquet(os.path.join(a.real_research, f), columns=cols))
        print(f"tier-1 placebo / real candidates by arm: {ratios} -> {'OK' if ok else 'BELOW ' + str(TIER1_MIN_RATIO)}")
        sys.exit(0 if ok else 1)
    else:
        out = score(a.research, a.dst, a.real_research)
        for name, D in out.items():
            D.to_parquet(os.path.join(a.dst, f"_e1_score_{name}.parquet"), index=False)


if __name__ == "__main__":
    main()
