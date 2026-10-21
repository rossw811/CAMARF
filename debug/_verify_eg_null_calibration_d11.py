"""
debug/_verify_eg_null_calibration_d11.py -- synthetic checks for D11 / R6.4 (Ross 2026-10-12: calendar-aligned nulls
from the full universe) and R6.3 (production two-direction EG call) in research/eg_null_calibration_montecarlo.py,
run BEFORE trusting it on real data.

The pre-D11 study paired each series' last n bars by POSITION: with different calendars (crypto 24/7 vs equity
sessions, different holidays/listing gaps) row i is a different date for each leg, and it sampled the ~1.5k yfinance
cache, not load_full_universe(). It also called one-direction coint() on the raw arrays.
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


def _frames(rng):
    """A (7-day calendar) and B (weekdays only) cointegrated BY DATE: b_t = a_t + stationary noise. Positional pairing
    of their last n bars puts different dates side by side; date alignment recovers the relation."""
    days = pd.date_range("2018-01-01", periods=1400, freq="D")
    a = np.cumsum(rng.normal(scale=0.02, size=len(days)))
    noise = np.zeros(len(days))
    e = rng.normal(scale=0.01, size=len(days))
    for t in range(1, len(days)):
        noise[t] = 0.5 * noise[t - 1] + e[t]
    fa = pd.DataFrame({"close": np.exp(3 + a)}, index=days)
    wk = days[days.dayofweek < 5]
    fb = pd.DataFrame({"close": np.exp(3 + a + noise)}, index=days)
    return {"A": fa, "B": fb.loc[wk]}


try:
    import eg_null_calibration_montecarlo as mod
    from analysis import eg_pvalue_pair, CointScanner
    from universe_loader import align_to_common_calendar
    from config import Config

    print("Check D11-1: pairs are matched by date, not by position")
    fr = _frames(np.random.default_rng(1))
    la, lb = np.log(fr["A"]["close"].to_numpy()), np.log(fr["B"]["close"].to_numpy())
    n = min(len(la), len(lb))
    p_positional, _ = eg_pvalue_pair(la[-n:], lb[-n:], Config.ANALYSIS.EG_MAX_LAG, "1D")
    al = align_to_common_calendar(fr, lookback_years=10)
    lp = CointScanner._build_log_price_map(al, ["A", "B"])
    p_aligned, n_al = eg_pvalue_pair(lp["A"], lp["B"], Config.ANALYSIS.EG_MAX_LAG, "1D")
    check(f"the pre-D11 positional pairing misses a by-date cointegrated pair [p {p_positional:.3g} > 0.05]",
          p_positional is not None and p_positional > 0.05)
    r = mod.pair_null_pvalue(al, "A", "B", "1D", lp_cache={})
    check(f"pair_null_pvalue aligns by date and rejects [p {r['pvalue']:.3g} < 0.01]", r["pvalue"] < 0.01)
    check(f"it IS the production two-direction call [{r['pvalue']:.6g} vs {p_aligned:.6g}]",
          np.isclose(r["pvalue"], p_aligned) and r["n_overlap"] == n_al)

    print("Check D11-2: overlap floor is production's MIN_OVERLAP_BY_TF, not 60")
    short = {k: v.iloc[-200:] for k, v in fr.items()}
    al_s = align_to_common_calendar(short, lookback_years=10)
    rs = mod.pair_null_pvalue(al_s, "A", "B", "1D", lp_cache={})
    floor = Config.STATS.MIN_OVERLAP_BY_TF["1D"]
    check(f"~140 weekday overlap < {floor} -> skipped as short [{rs['status']}, n={rs['n_overlap']}]",
          rs["status"] == "short_overlap" and rs["n_overlap"] < floor)

    print("Check D11-3: run_timeframe on independent random walks: size near nominal, counts add up")
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2010-01-01", periods=1500)
    rw = {f"S{i}": pd.DataFrame({"close": np.exp(3 + np.cumsum(rng.normal(scale=0.01, size=len(idx))))}, index=idx)
          for i in range(60)}
    rw = align_to_common_calendar(rw, lookback_years=10)
    out = mod.run_timeframe("1D", rw, n_pairs_target=300, rng=np.random.default_rng(0))
    check(f"300 null pairs tested [{out['n_null_pairs_tested']}]", out["n_null_pairs_tested"] == 300)
    check(f"empirical rate {out['empirical_rate']:.3f} in [0.01, 0.10]", 0.01 <= out["empirical_rate"] <= 0.10)
    # N16 (review finding 6, 2026-10-20): the one-direction rate is reported and asserted, not just the max-p rate.
    # max p >= forward p for every pair, so max-p rejections are a subset of forward rejections (rate_max <= rate_fwd);
    # on independent random walks one direction should sit near nominal 5% (99% binomial band for 300 pairs).
    from scipy.stats import binom
    lo, hi = binom.ppf(0.005, 300, 0.05) / 300, binom.ppf(0.995, 300, 0.05) / 300
    fwd = out["rate_forward_direction_only"]
    check(f"one-direction rate reported {fwd:.3f}, max-p rate {out['empirical_rate']:.3f} <= it",
          np.isfinite(fwd) and out["empirical_rate"] <= fwd)
    check(f"one-direction rate {fwd:.3f} inside the 99% band for nominal 5% [{lo:.3f}, {hi:.3f}]", lo <= fwd <= hi)
    check("source label recorded", out.get("source") == "load_full_universe")
    check("each unordered pair drawn at most once",
          out["n_null_pairs_tested"] + out["n_skipped_short_overlap"] + out["n_errors"] == out["attempts"]
          and out["n_duplicate_draws_skipped"] >= 0)

    print("Check D11-4: main() loads the full universe (WRDS priority, IBKR off), not the yfinance cache")
    calls = []

    def fake_load(tf, **kw):
        calls.append((tf, kw))
        return dict(rw)
    mod.load_full_universe = fake_load
    mod.OUT_PATH = os.path.join(os.environ.get("TEMP", "."), "_d11_null_test.parquet")
    mod.main(["--tf", "1D", "--n-pairs", "50"])
    check(f"load_full_universe called for 1D with columns=['close'], include_ibkr False [{calls}]",
          len(calls) == 1 and calls[0][0] == "1D" and calls[0][1].get("columns") == ["close"]
          and calls[0][1].get("include_ibkr", False) is False)
except (ImportError, AttributeError) as e:
    check(f"D11 functions exist ({type(e).__name__}: {e})", False)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
