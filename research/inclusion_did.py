"""
research/inclusion_did.py -- endogeneity arm (c) (Ross 2026-10-13): does co-movement CAUSE / follow from common
ownership? Identification by an exogenous-ish shock: S&P 500 inclusion (Barberis, Shleifer & Wurgler 2005) raises
index-fund ownership without changing fundamentals. Difference-in-differences of a stock's co-movement with incumbent
members, added stock vs matched non-added controls, with a pre-trend test.

Pure core (tested on synthetic data):
  comovement(x, M)          mean Pearson correlation of series x with each row of M
  did_from_events(events)   per event: (treated post - pre) - mean over controls (post - pre); DiD = mean over events;
                            95% CI by bootstrapping events; pre-trend: the pre period split into PRETREND_BINS bins,
                            per-event slope of (treated - control) co-movement on bin index, one-sample t-test
Real-data driver (after WRDS job 29: CRSP SIC + size): events = S&P 500 additions 1990-2024 from the cached PIT
membership history; controls = non-members with the same 2-digit SIC, nearest size, nearest pre-period co-movement.
Disclosed caveat: additions are chosen by a committee on size/liquidity -- matching and the pre-trend test address
selection only partly. Test: debug/_verify_inclusion_did.py
"""
import numpy as np
from scipy import stats

PRETREND_BINS = 12       # one bin per calendar month of the 12-month pre-period (definition; registry)
N_BOOT = 2000            # bootstrap draws over events for the DiD CI (registry)


def comovement(x, M) -> float:
    x = np.asarray(x, float); M = np.atleast_2d(np.asarray(M, float))
    xc = (x - x.mean()) / x.std()
    Mc = (M - M.mean(axis=1, keepdims=True)) / M.std(axis=1, keepdims=True)
    return float(np.mean(Mc @ xc / len(x)))


def _event_delta(ev):
    t0, M = ev["t0"], ev["members"]
    pre, post = slice(0, t0), slice(t0, M.shape[1])
    dt = comovement(ev["treated"][post], M[:, post]) - comovement(ev["treated"][pre], M[:, pre])
    dc = np.mean([comovement(c[post], M[:, post]) - comovement(c[pre], M[:, pre]) for c in ev["controls"]])
    return dt - dc


def _event_pre_slope(ev, bins=PRETREND_BINS):
    t0, M = ev["t0"], ev["members"]
    edges = np.linspace(0, t0, bins + 1).astype(int)
    diffs = []
    for a, b in zip(edges[:-1], edges[1:]):
        s = slice(a, b)
        diffs.append(comovement(ev["treated"][s], M[:, s])
                     - np.mean([comovement(c[s], M[:, s]) for c in ev["controls"]]))
    return float(np.polyfit(np.arange(bins), diffs, 1)[0])


def did_from_events(events, n_boot: int = N_BOOT, rng=None) -> dict:
    rng = rng or np.random.default_rng(0)
    d = np.array([_event_delta(e) for e in events])
    boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)]
    slopes = np.array([_event_pre_slope(e) for e in events])
    return {"did": float(d.mean()), "ci_low": float(np.quantile(boot, 0.025)), "ci_high": float(np.quantile(boot, 0.975)),
            "n_events": len(d), "pretrend_slope": float(slopes.mean()),
            "pretrend_p": signflip_p(slopes, rng)}


SIGNFLIP_DRAWS = 5000    # sign-flip randomization draws (registry)


def signflip_p(x, rng=None, draws: int = SIGNFLIP_DRAWS) -> float:
    """Two-sided sign-flip randomization p-value for mean(x) = 0 (exact under symmetry; 2026-10-13: the one-sample
    t-test on per-event slopes was oversized, 7.7% +- 1.5% at a nominal 5% over 300 synthetic seeds)."""
    rng = rng or np.random.default_rng(0)
    x = np.asarray(x, float)
    obs = abs(x.mean())
    flips = rng.choice([-1.0, 1.0], size=(draws, len(x)))
    return float((1 + np.sum(np.abs((flips * x).mean(axis=1)) >= obs)) / (draws + 1))


PRE_BARS, BAND_BARS = 252, 21    # 12-month window; +-1 month excluded around inclusion (definition; registry)
N_MEMBERS, N_CONTROLS = 50, 3    # incumbent members sampled per event; matched controls per event (registry)


def build_event(R, d, treated, controls, members, pre: int = PRE_BARS, band: int = BAND_BARS):
    """Return segments around inclusion date d from R (dates x labels): pre = [d-pre, d-band), post = [d+band, d+pre)
    trading days. Only series complete on both segments are used. None when the treated stock is incomplete."""
    import pandas as pd
    pos = int(R.index.searchsorted(pd.Timestamp(d)))
    if pos - pre < 0 or pos + pre > len(R):
        return None
    rows = np.r_[pos - pre:pos - band, pos + band:pos + pre]
    seg = R.iloc[rows]
    ok = seg.notna().all()
    if treated not in seg or not ok.get(treated, False):
        return None
    ctrl = [seg[c].to_numpy() for c in controls if c in seg and ok.get(c, False)]
    mem = [m for m in members if m in seg and ok.get(m, False) and m != treated]
    if not ctrl or len(mem) < 2:
        return None
    return {"treated": seg[treated].to_numpy(), "controls": ctrl, "members": seg[mem].to_numpy().T,
            "t0": pre - band}


def main(n_controls: int = None):
    """S&P 500 additions 1990-2023 -> events; controls = non-members at the date, same 2-digit SIC, common stock
    (shrcd 10/11), nearest log market cap (|prc| x shrout, month-end before the date), complete data."""
    import os
    import sys
    import pandas as pd
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    from data_wrds import label_permno_map, sp500_members_asof, crsp_no_trade_mask
    W = os.path.join(root, "output", "cache", "wrds")
    mem = pd.read_parquet(os.path.join(W, "sp500_membership_history.parquet"))
    names = pd.read_parquet(os.path.join(W, "crsp_msenames_sic.parquet"))
    size = pd.read_parquet(os.path.join(W, "crsp_msf_size.parquet"))
    size["date"] = pd.to_datetime(size["date"]); size["mcap"] = size["prc"].abs() * size["shrout"]
    lab = {}
    for l, p in label_permno_map().items():
        if p not in lab or lab[p].startswith("PERMNO"):
            lab[p] = l
    cache = {}

    def ret(p):
        if p not in cache:
            l = lab.get(int(p))
            f = os.path.join(W, f"{l}_1D.parquet") if l else None
            if not f or not os.path.exists(f):
                cache[p] = None
            else:
                df = pd.read_parquet(f)
                px = crsp_no_trade_mask(df, l, df["close_total_return"].astype(float)).abs()
                r = np.log(px).diff(); r.index = pd.to_datetime(r.index)
                cache[p] = r[~r.index.duplicated(keep="last")]
        return cache[p]

    adds = mem[(pd.to_datetime(mem["mbrstartdt"]) >= "1990-01-01") & (pd.to_datetime(mem["mbrstartdt"]) <= "2023-12-31")]
    rng = np.random.default_rng(20261014)
    events, meta = [], []
    for a in adds.itertuples():
        d = pd.Timestamp(a.mbrstartdt)
        nm = names[(pd.to_datetime(names["namedt"]) <= d) & (pd.to_datetime(names["nameendt"]) >= d)]
        sic = nm.loc[nm["permno"] == a.permno, "siccd"]
        if sic.empty or ret(a.permno) is None:
            continue
        sic2 = int(sic.iloc[0]) // 100
        members_now = sp500_members_asof(mem, d - pd.Timedelta(days=1)) - {a.permno}
        pool = nm[(nm["siccd"] // 100 == sic2) & nm["shrcd"].isin([10, 11]) & ~nm["permno"].isin(members_now | {a.permno})]
        sz = size[(size["date"] < d) & (size["date"] >= d - pd.Timedelta(days=40))].drop_duplicates("permno", keep="last")
        sz = pd.to_numeric(sz.set_index("permno")["mcap"], errors="coerce").astype(float)
        sz = sz[np.isfinite(sz) & (sz > 0)]          # no size -> cannot be size-matched (CRSP prc/shrout missing)
        if a.permno not in sz.index:
            continue
        cand = pool[pool["permno"].isin(sz.index)]["permno"].unique()
        cand = sorted(cand, key=lambda p: abs(np.log(sz[p]) - np.log(sz[a.permno])))
        ctrl = [p for p in cand if ret(p) is not None][:N_CONTROLS * 3]
        mlist = [p for p in rng.permutation(sorted(members_now)) if ret(p) is not None][:N_MEMBERS * 2]
        ids = [a.permno] + ctrl + mlist
        R = pd.concat({p: ret(p) for p in ids}, axis=1).sort_index()
        ev = build_event(R, d, a.permno, ctrl, mlist)
        if ev is None:
            continue
        ev["controls"] = ev["controls"][:n_controls or N_CONTROLS]; ev["members"] = ev["members"][:N_MEMBERS]
        events.append(ev); meta.append({"permno": a.permno, "date": d, "sic2": sic2})
    res = did_from_events(events, rng=np.random.default_rng(1))
    print(f"events {len(events)} of {len(adds)} additions 1990-2023: {res}")
    M = pd.DataFrame(meta); M["delta"] = [_event_delta(e) for e in events]; M["decade"] = (M["date"].dt.year // 10) * 10
    print(M.groupby("decade")["delta"].agg(["count", "mean"]).to_string())
    suffix = "" if not n_controls or n_controls == N_CONTROLS else f"_c{n_controls}"
    M.to_parquet(os.path.join(root, "output", "research", f"inclusion_did_events{suffix}.parquet"))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-controls", type=int, default=None, help="sensitivity: matched controls per event")
    main(ap.parse_args().n_controls)
