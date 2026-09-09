"""
Synthetic verification for a real, systemic bug found live (2026-09-03) in
research/pit_wfa_wrds_daily.py's capital-constrained measurement:
`portfolio_sim.get_price_at()`/`_load_spread_series()` hardcode reads from
`output/cache/{symbol}_1hr.parquet` and
`output/results/{tf}/spread_series_{a}_{b}.parquet` -- files pit_wfa.py's own
1h pipeline writes, but which pit_wfa_wrds_daily.py's WRDS-daily pairs NEVER
produce (it works entirely in-memory). Real, deterministic effect observed
live: 0/21 trades taken under flat_2pct sizing on fold1_exp, reproduced
identically across two full relaunches -- not a fold-specific data artifact.

Fixed via an injectable in-memory override (register_price_series /
register_spread_series), checked BEFORE the file-based cache in both lookup
functions, so pit_wfa.py's own file-based behavior (which never registers
anything) stays byte-identical.

Run: python debug/_verify_portfolio_sim_external_series_fix.py
(No WRDS connection needed -- fully synthetic/offline.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_sim as ps

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


print("Check 1: get_price_at -- an unregistered symbol with no on-disk cache file returns NaN "
      "(reproduces the real bug: a WRDS-daily-only symbol, before the fix)")
ps.clear_external_series()
price_before = ps.get_price_at("ZZZ_NONEXISTENT_SYMBOL", pd.Timestamp("2020-01-01"))
check("unregistered symbol with no cache file -> NaN (the real crash precondition)",
      np.isnan(price_before))

print("Check 2: register_price_series -- once registered, get_price_at finds the in-memory "
      "series instead of falling through to the (nonexistent) file cache")
idx = pd.date_range("2020-01-01", periods=10, freq="D")
price_df = pd.DataFrame({"close": np.linspace(100, 109, 10)}, index=idx)
ps.register_price_series("ZZZ_NONEXISTENT_SYMBOL", price_df)
price_after = ps.get_price_at("ZZZ_NONEXISTENT_SYMBOL", pd.Timestamp("2020-01-05"))
check(f"registered symbol resolves to the real in-memory price ({price_after}), not NaN",
      not np.isnan(price_after) and price_after == price_df.loc["2020-01-05", "close"])

print("Check 3: get_price_at -- 'pad' (as-of, no lookahead) semantics preserved for the "
      "in-memory path, matching the existing file-based path's own causal guarantee")
price_padded = ps.get_price_at("ZZZ_NONEXISTENT_SYMBOL", pd.Timestamp("2020-01-05 12:00:00"))
check("a timestamp between two bars resolves to the LAST bar at-or-before it, not a lookahead "
      "peek at the next one", price_padded == price_df.loc["2020-01-05", "close"])

print("Check 4: register_spread_series / _load_spread_series -- same override behavior for the "
      "spread series feeding causal_rolling_std_at_entry / stop_distance_dollars_per_share")
ps.clear_external_series()
spread_before = ps._load_spread_series("AAA", "BBB", "1D")
check("unregistered pair with no spread_series file -> None (the real crash precondition)",
      spread_before is None)
spread_df = pd.DataFrame({"spread": np.sin(np.linspace(0, 10, 300)) * 2}, index=pd.date_range("2015-01-01", periods=300, freq="D"))
ps.register_spread_series("AAA", "BBB", "1D", spread_df)
spread_after = ps._load_spread_series("AAA", "BBB", "1D")
check("registered pair resolves to the real in-memory spread series, not None",
      spread_after is not None and len(spread_after) == 300)

print("Check 5: end-to-end -- stop_distance_dollars_per_share (the function whose NaN return "
      "was the direct cause of every capital-constrained trade being skipped) now returns a "
      "real, finite value once the pair's spread series is registered")
entry_ts = spread_df.index[250]
half_life = 20.0
dist_before_registration_cleared = ps.stop_distance_dollars_per_share(
    entry_z=2.0, entry_spread=0.5, symbol_a="CCC", symbol_b="DDD", tf_label="1D",
    entry_time=entry_ts, half_life=half_life,
)
check("an UNregistered pair (CCC/DDD) still correctly returns NaN (no accidental global "
      "leakage from AAA/BBB's registration)", np.isnan(dist_before_registration_cleared))
dist_after = ps.stop_distance_dollars_per_share(
    entry_z=2.0, entry_spread=0.5, symbol_a="AAA", symbol_b="BBB", tf_label="1D",
    entry_time=entry_ts, half_life=half_life,
)
check(f"a REGISTERED pair (AAA/BBB) now returns a finite risk-per-share estimate ({dist_after}), "
      f"not NaN -- this is the exact value that was silently NaN for every WRDS-daily trade "
      f"before the fix, causing every trade to be skipped under flat_2pct/Kelly sizing",
      np.isfinite(dist_after) and dist_after > 0)

ps.clear_external_series()
print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
