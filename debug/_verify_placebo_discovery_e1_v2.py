"""
E1 v2 (review 2026-10-25, Ross "yes to all"; docs/ERRATA.md "E1 placebo discovery v1"). Checks on
research/placebo_discovery_e1.py:
  1. own_valid_returns: a return spanning more than 5 missing business days (a genuine hole) is not a source return
  2. shared fallback: two series missing the same global-calendar days (a US holiday) take the same source returns,
     so identical real series give identical placebos (the scan's duplicate removal then works) and a correlated pair
     keeps its return correlation; no random draws (v1 drew 8.3% of returns independently)
  3. write_placebo_file: placebo USD dollar volume equals the real one; CRSP no-trade days (close NaN, total return
     present, non-GVKEY label) keep close NaN; quote_only carried over
  4. plant bases: only series that clear the ADV gate on >= PLANT_MIN_ADV_SHARE of days (US also S&P 500 member on
     >= PLANT_MIN_MEMBER_SHARE), per arm
  5. plant grid: every (half-life, spread s.d.) cell gets PLANTS_PER_CELL plants per arm; US labels PERMNO99xxxx,
     international GVKEY9xxxxx_01W
  6. install_us_plant_refs: symlinked reference files are replaced by copies (the real target is unchanged); each US
     plant resolves to its fake PERMNO, whose membership spells are its base's
  7. false_share_by_arm: placebo tail rate x real windows tested / real windows at or below the arm's BH cutoff
  8. tier1 guard: per-arm placebo / real Tier-1 candidate ratio, fails below TIER1_MIN_RATIO
Run: python debug/_verify_placebo_discovery_e1_v2.py
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


import research.placebo_discovery_e1 as e1  # noqa: E402

need = ("own_valid_returns", "choose_plant_bases", "plant_grid", "install_us_plant_refs", "false_share_by_arm",
        "tier1_arm_ratios")
missing = [f for f in need if not hasattr(e1, f)]
if missing:
    check("v2 functions exist", False, str(missing))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

# 1
idx = pd.bdate_range("2015-01-01", periods=40)
lp = pd.Series(np.linspace(0, 0.39, 40), index=idx).drop(idx[10:17])       # 7 business days missing
R = e1.own_valid_returns(lp)
check("1 return across a > 5-day hole is not a source", np.isnan(R.loc[idx[17]]) and np.isfinite(R.loc[idx[9]]),
      f"{R.loc[idx[17]]} {R.loc[idx[9]]}")

# 2
cal = pd.bdate_range("2012-01-01", "2014-12-31")                            # global calendar (foreign days)
hol = cal[::25]                                                             # "US holidays": ~10 a year
g = np.random.default_rng(2)
f = g.normal(0, 0.01, len(cal))
ra = f + g.normal(0, 0.004, len(cal))
rb = f + g.normal(0, 0.004, len(cal))
us = ~cal.isin(hol)
la = pd.Series(np.cumsum(ra), index=cal)[us]
lb = pd.Series(np.cumsum(rb), index=cal)[us]
paths = e1.year_index_paths(cal, 3.5, seed=5)
st = {}
pa = e1.placebo_series(la, cal, paths, stats=st)
pa2 = e1.placebo_series(la.copy(), cal, paths)
pb = e1.placebo_series(lb, cal, paths)
c_real = la.diff().corr(lb.diff())
c_pl = pa.diff().corr(pb.diff())
check("2 shared fallback: deterministic, identical inputs -> identical placebo, correlation kept, no random draws",
      pa.equals(pa2) and abs(c_real - c_pl) < 0.03 and st.get("random", 0) == 0,
      f"corr {c_real:.3f} -> {c_pl:.3f}; stats {st}")

# 3
with tempfile.TemporaryDirectory() as td:
    d0 = pd.bdate_range("2015-01-01", periods=60)
    close = pd.Series(np.linspace(10, 20, 60), index=d0)
    close.iloc[[5, 6]] = np.nan                                             # CRSP no-trade days
    src = pd.DataFrame({"close": close, "close_total_return": np.linspace(10, 21, 60), "volume": 1000.0,
                        "quote_only": False}, index=d0)
    src.index.name = "date"
    pl = pd.Series(np.log(np.linspace(30, 40, 60)), index=d0)
    out = os.path.join(td, "ABC_1D.parquet")
    e1.write_placebo_file(src, pl, out, label="ABC")
    d = pd.read_parquet(out)
    from dollar_volume import usd_dollar_volume
    real_dv, pl_dv = usd_dollar_volume(src), usd_dollar_volume(d)
    ok_dv = np.allclose(real_dv.dropna(), pl_dv.reindex(real_dv.dropna().index))
    check("3 dollar volume real, no-trade close NaN, quote_only kept",
          ok_dv and d["close"].iloc[[5, 6]].isna().all() and d["close_total_return"].notna().all() and "quote_only" in d,
          f"dv {ok_dv}, close NaN {d['close'].iloc[[5, 6]].isna().tolist()}, cols {list(d.columns)}")

# 4
C = pd.DataFrame({"label": ["GVKEY000001_01W", "GVKEY000002_01W", "AAA", "BBB", "CCC"],
                  "arm": ["international", "international", "us", "us", "us"],
                  "adv_share": [0.9, 0.2, 0.8, 0.9, 0.95], "member_share": [np.nan, np.nan, 0.9, 0.1, 0.7],
                  "n_days": [3000, 3000, 3000, 3000, 1000]})
B = e1.choose_plant_bases(C)
check("4 plant bases clear the gates, per arm", set(B["label"]) == {"GVKEY000001_01W", "AAA"}, str(B["label"].tolist()))

# 5
G = e1.plant_grid()
cells = G.groupby(["arm", "half_life", "spread_sd"]).size()
check("5 plant grid: PLANTS_PER_CELL per (arm, half-life, s.d.); labels by arm",
      (cells == e1.PLANTS_PER_CELL).all() and len(cells) == 2 * len(e1.HALF_LIVES) * len(e1.SPREAD_SDS)
      and G.loc[G.arm == "us", "plant"].str.match(r"^PERMNO99\d{4}$").all()
      and G.loc[G.arm == "international", "plant"].str.match(r"^GVKEY9\d{5}_01W$").all(), f"{len(G)} plants")

# 6
with tempfile.TemporaryDirectory() as td:
    real = os.path.join(td, "real"); dst = os.path.join(td, "dst")
    os.makedirs(real); os.makedirs(dst)
    m = pd.DataFrame({"permno": pd.array([10001, 10002], dtype="Int64"),
                      "mbrstartdt": pd.to_datetime(["2000-01-01", "2005-01-01"]),
                      "mbrenddt": pd.to_datetime(["2010-01-01", "2020-01-01"]), "is_current": [False, False]})
    lm = pd.DataFrame({"label": ["AAA", "BBB"], "permno": [10001.0, 10002.0], "source": ["agree", "agree"],
                       "return_scores": ["", ""]})
    m.to_parquet(os.path.join(real, "sp500_membership_history.parquet"))
    lm.to_parquet(os.path.join(real, "wrds_label_permno_final.parquet"))
    linked = True
    for fn in ("sp500_membership_history.parquet", "wrds_label_permno_final.parquet"):
        try:
            os.symlink(os.path.join(real, fn), os.path.join(dst, fn))
        except OSError:          # Windows without symlink privilege: copies (the link case runs on CI / CachyOS)
            import shutil
            shutil.copy(os.path.join(real, fn), os.path.join(dst, fn))
            linked = False
    plants = pd.DataFrame({"plant": ["PERMNO990000"], "base": ["BBB"], "arm": ["us"]})
    e1.install_us_plant_refs(dst, plants)
    M2 = pd.read_parquet(os.path.join(dst, "sp500_membership_history.parquet"))
    L2 = pd.read_parquet(os.path.join(dst, "wrds_label_permno_final.parquet"))
    real_unchanged = len(pd.read_parquet(os.path.join(real, "sp500_membership_history.parquet"))) == 2 and \
        len(pd.read_parquet(os.path.join(real, "wrds_label_permno_final.parquet"))) == 2
    sp = M2[M2["permno"] == 990000]
    check("6 US plant refs: copies not links, real unchanged, fake PERMNO has the base's spells",
          not os.path.islink(os.path.join(dst, "sp500_membership_history.parquet")) and real_unchanged
          and L2.set_index("label").loc["PERMNO990000", "permno"] == 990000
          and len(sp) == 1 and sp["mbrstartdt"].iloc[0] == pd.Timestamp("2005-01-01"),
          f"{len(M2)} {len(L2)}{'' if linked else ' (no symlink privilege here: copy case only)'}")

# 7
real_w = pd.DataFrame({"arm": ["us"] * 1000, "pvalue": np.r_[np.full(20, 1e-5), np.full(980, 0.5)],
                       "fdr_rejected": np.r_[np.ones(20, bool), np.zeros(980, bool)]})
plac_w = pd.DataFrame({"arm": ["us"] * 2000, "pvalue": np.r_[np.full(10, 1e-5), np.full(1990, 0.5)]})
F = e1.false_share_by_arm(real_w, plac_w)
r = F.set_index("arm").loc["us"]
check("7 false share = placebo tail rate x real windows / real at the cutoff",
      np.isclose(r["cutoff"], 1e-5) and np.isclose(r["est_false"], 5.0) and np.isclose(r["false_share"], 0.25), str(r.to_dict()))

# 8
real1 = pd.DataFrame({"symbol_a": ["AAA", "AAA", "GVKEY000001_01W"], "symbol_b": ["BBB", "CCC", "GVKEY000002_01W"]})
plac1 = pd.DataFrame({"symbol_a": ["AAA", "GVKEY000001_01W"], "symbol_b": ["BBB", "GVKEY000002_01W"]})
ratios, ok = e1.tier1_arm_ratios(plac1, real1)
check("8 tier-1 guard: per-arm ratios, fails below the floor",
      np.isclose(ratios["us_us_gated"], 0.5) and np.isclose(ratios["international"], 1.0) and not ok, f"{ratios} {ok}")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
