"""
Regression test for the A2 comparison arm (Ross, 2026-10-03: "causal expanding OLS", "break at outages"), built with
A3 (DATA_GAP rows masked before hedge estimation).
A2 (code review 2026-09-26): where the rolling OLS hedge has no value, SpreadModel.compute_spread used the FULL-SAMPLE
hedge ratio (and 1.0 if even that was missing) -- lookahead. Arm `Config.ANALYSIS.HEDGE_FALLBACK = "causal_expanding"`:
OLS on real rows up to each bar only (same minimum as the rolling window: half of it), and no spread before that.
Arm `Config.ANALYSIS.DAILY_GAP_BREAKS = True`: for daily-or-coarser data a run of > data._MAX_FILL_BARS missing bars
is a genuine gap (segment break) in longest_gap_respecting_segment, as DATA_GAP is everywhere else.
Checks:
  1. HedgeRatioEstimator.ols_expanding equals a hand OLS on each prefix of real rows (NaNs skipped), NaN before min_obs;
  2. NO LOOKAHEAD under the arm: changing prices AFTER bar t0 leaves the spread up to t0 unchanged;
  3. the current method (full_sample) DOES change it -- proves check 2 can detect lookahead;
  4. under the arm, compute_spread never uses the 1.0 fallback (NaN hedge -> NaN spread);
  5. daily gap breaks: a 10-bar outage splits the "1D" segment only when DAILY_GAP_BREAKS is on; a 3-bar one never;
  6. defaults unchanged: both settings default to the current behaviour.
Run: python debug/_verify_a2_causal_hedge_arm.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import AnalysisPipeline, HedgeRatioEstimator, SpreadModel
from config import Config
from data import longest_gap_respecting_segment

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def pair_frames(la, lb, idx):
    mk = lambda l: pd.DataFrame({"open": np.exp(l), "high": np.exp(l), "low": np.exp(l), "close": np.exp(l),
                                 "volume": 1e6, "gap_flag": 0}, index=idx)
    return {"AA": mk(la), "BB": mk(lb)}


def spread_of(la, lb, idx):
    """Per-bar spread exactly as _build_pair_result builds it (via its persisted per-bar output)."""
    out = AnalysisPipeline._build_pair_result({"symbol_a": "AA", "symbol_b": "BB"}, pair_frames(la, lb, idx), "1D")
    if out is None:
        return None
    pb = out[1] if isinstance(out, tuple) else None
    return np.asarray(pb["spread"], dtype=float) if pb is not None else None


def main():
    cfg = Config.ANALYSIS
    check("6.defaults_unchanged", getattr(cfg, "HEDGE_FALLBACK", None) == "full_sample"
          and getattr(cfg, "DAILY_GAP_BREAKS", None) is False,
          f"HEDGE_FALLBACK={getattr(cfg, 'HEDGE_FALLBACK', None)!r} DAILY_GAP_BREAKS={getattr(cfg, 'DAILY_GAP_BREAKS', None)!r}")
    if not hasattr(HedgeRatioEstimator, "ols_expanding"):
        check("1.ols_expanding_exists", False); return finish()

    rng = np.random.default_rng(5)
    n = 400
    lb = np.cumsum(rng.normal(0, 0.01, n)) + 4.0
    la = 0.8 * lb + 1.0 + rng.normal(0, 0.003, n)
    la_n, lb_n = la.copy(), lb.copy()
    la_n[[10, 11, 50]] = np.nan
    beta = HedgeRatioEstimator.ols_expanding(la_n, lb_n, min_obs=30)
    ok, bad = True, []
    for t in (29, 40, 120, 399):
        m = np.isfinite(la_n[:t + 1]) & np.isfinite(lb_n[:t + 1])
        a, b = la_n[:t + 1][m], lb_n[:t + 1][m]
        exp = np.nan if m.sum() < 30 else float(((a - a.mean()) @ (b - b.mean())) / ((b - b.mean()) @ (b - b.mean())))
        same = (np.isnan(exp) and np.isnan(beta[t])) or np.isclose(exp, beta[t])
        ok &= bool(same)
        if not same:
            bad.append((t, exp, beta[t]))
    check("1.ols_expanding_matches_hand_prefix_ols", ok, str(bad))

    idx = pd.bdate_range("2015-01-02", periods=n)
    t0 = 250
    la2 = la.copy()
    la2[t0 + 1:] += np.linspace(0, 0.8, n - t0 - 1)      # change only the FUTURE (after t0)
    orig = (cfg.HEDGE_FALLBACK, cfg.DAILY_GAP_BREAKS)
    try:
        cfg.HEDGE_FALLBACK = "causal_expanding"
        s1, s2 = spread_of(la, lb, idx), spread_of(la2, lb, idx)
        ok2 = s1 is not None and s2 is not None and np.allclose(s1[:t0 + 1], s2[:t0 + 1], equal_nan=True)
        check("2.no_lookahead_under_arm", ok2, "" if ok2 else "spread before t0 changed when only the future changed")
        cfg.HEDGE_FALLBACK = "full_sample"
        f1, f2 = spread_of(la, lb, idx), spread_of(la2, lb, idx)
        check("3.current_method_has_lookahead", f1 is not None and f2 is not None
              and not np.allclose(f1[:t0 + 1], f2[:t0 + 1], equal_nan=True))
        cfg.HEDGE_FALLBACK = "causal_expanding"
        sp = SpreadModel.compute_spread(la, lb, np.full(n, np.nan), np.nan, static_fallback=False)
        check("4.no_1.0_fallback_under_arm", bool(np.isnan(sp).all()))

        m10 = np.ones(60, bool); m10[20:30] = False
        m3 = np.ones(60, bool); m3[20:23] = False
        cfg.DAILY_GAP_BREAKS = False
        off10 = longest_gap_respecting_segment(m10, "1D").sum()
        cfg.DAILY_GAP_BREAKS = True
        on10, on3 = longest_gap_respecting_segment(m10, "1D").sum(), longest_gap_respecting_segment(m3, "1D").sum()
        check("5.daily_gap_breaks", off10 == 50 and on10 == 30 and on3 == 57, f"off10={off10} on10={on10} on3={on3}")
    finally:
        cfg.HEDGE_FALLBACK, cfg.DAILY_GAP_BREAKS = orig
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
