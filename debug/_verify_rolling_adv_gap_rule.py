"""
debug/_verify_rolling_adv_gap_rule.py -- BUG-D122 reproducing test.

rolling_adv used min_periods == window, so one missing volume day voided a whole trailing year and the discovery
liquidity gate's Series.asof() fell back to an ADV years old. The fix (GapFlag rule, data._MAX_FILL_BARS = 5): the mean
runs over the days that HAVE volume, and the value is NaN only when the trailing window contains a DATA_GAP (more than
_MAX_FILL_BARS consecutive missing days) or lacks a full window of history.

Checks (all synthetic):
  1. a single missing day does not void the window; value = mean of the present days
  2. 5 consecutive missing days still valid; 6 consecutive missing days void exactly the windows containing them
  3. the window slides past a gap: value valid again once the gap has left the window
  4. first window-1 rows stay NaN (history requirement unchanged)
  5. causality: mutating data strictly after T never changes the value at T
  6. no gaps -> identical to the old plain rolling mean
Run: python debug/_verify_rolling_adv_gap_rule.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data
import research.rolling_adv_comparison as rac

W = 20


def mk(vol):
    idx = pd.bdate_range("2020-01-01", periods=len(vol))
    return pd.DataFrame({"close": 10.0, "volume": np.asarray(vol, float)}, index=idx)


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    return bool(cond)


ok = True
base = np.full(60, 100.0)

v = base.copy(); v[30] = np.nan
a = rac.rolling_adv(mk(v), window=W)
ok &= check("1. one missing day: window still valid, mean of present days", a.iloc[30:50].notna().all() and np.allclose(a.dropna(), 1000.0))

v = base.copy(); v[30:35] = np.nan                       # 5 consecutive = at the limit
a5 = rac.rolling_adv(mk(v), window=W)
ok &= check("2a. 5 consecutive missing days still valid", a5.iloc[30:50].notna().all())

v = base.copy(); v[30:36] = np.nan                       # 6 consecutive = DATA_GAP
a6 = rac.rolling_adv(mk(v), window=W)
bad = a6.isna().to_numpy()
exp_bad = np.zeros(60, bool); exp_bad[:W - 1] = True; exp_bad[35:30 + W] = True   # windows ending t in [s+5, e-5+W-1] = [35, 49]
ok &= check("2b. 6 consecutive missing days void exactly the windows holding them", (bad == exp_bad).all())
ok &= check("3. valid again once the gap leaves the window", a6.iloc[30 + W:].notna().all())
ok &= check("4. first window-1 rows NaN", a6.iloc[:W - 1].isna().all())

v = base.copy(); v[30:36] = np.nan
v2 = v.copy(); v2[45:] = 7e6
b1 = rac.rolling_adv(mk(v), window=W); b2 = rac.rolling_adv(mk(v2), window=W)
ok &= check("5. causal: changes after T leave value at T alone", b1.iloc[:45].equals(b2.iloc[:45]) or np.allclose(b1.iloc[:45], b2.iloc[:45], equal_nan=True))

rng = np.random.default_rng(0); v = rng.uniform(50, 150, 60)
old = (pd.Series(v * 10.0)).rolling(W, min_periods=W).mean().to_numpy()
ok &= check("6. no gaps: identical to the plain rolling mean", np.allclose(rac.rolling_adv(mk(v), window=W).to_numpy(), old, equal_nan=True))
# 7. review finding (2026-10-27): Series.asof skips NaN, so across a genuine gap the gate read a pre-gap ADV
v = np.full(80, 100.0); v[40:50] = np.nan                  # 10-day DATA_GAP
d = mk(v); r = rac.rolling_adv(d, window=W)
t_in = d.index[55]                                         # window holding the gap -> rolling_adv NaN here
ok &= check("7a. precondition: rolling_adv is NaN inside the gap-holding window", np.isnan(r.loc[t_in]))
ok &= check("7b. adv_at returns NaN there (asof would return the stale pre-gap value)", np.isnan(rac.adv_at(r, t_in)) and not np.isnan(r.asof(t_in)))
t_ok = d.index[79]
ok &= check("7c. adv_at equals the value at the exact row when valid", rac.adv_at(r, t_ok) == r.loc[t_ok])
ok &= check("7d. adv_at on a non-trading day uses the last row at or before it", rac.adv_at(r, t_ok + pd.Timedelta(days=1)) == r.loc[t_ok])
ok &= check("7e. adv_at before the first row is NaN", np.isnan(rac.adv_at(r, d.index[0] - pd.Timedelta(days=5))))
# 8. --adv-missing zero comparison arm (Ross 2026-10-28): a priced day without volume counts as 0
v = base.copy(); v[30] = np.nan
z = rac.rolling_adv(mk(v), window=W, missing_volume="zero")
ok &= check("8a. zero arm: one priced no-volume day enters as 0", np.isclose(z.iloc[30], 1000.0 * (W - 1) / W))
v = base.copy(); v[30:36] = np.nan
d8 = mk(v); z6 = rac.rolling_adv(d8, window=W, missing_volume="zero")
ok &= check("8b. zero arm: 6 priced no-volume days are zeros, not a DATA_GAP", z6.iloc[W - 1:].notna().all())
d8.loc[d8.index[30:36], "close"] = np.nan
ok &= check("8c. zero arm: 6 days with no price still void the window (DATA_GAP)", rac.rolling_adv(d8, window=W, missing_volume="zero").iloc[35:50].isna().all())
try:
    rac.rolling_adv(mk(base), window=W, missing_volume="bogus"); ok &= check("8d. unknown mode raises", False)
except ValueError:
    ok &= check("8d. unknown mode raises", True)
ok &= check("0. gap limit is the project's rule", data._MAX_FILL_BARS == 5)

print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
