"""
Verifies the data.py save()->append() switch using the REAL DataStore.append()
and IBKRFeed._resample() functions against a throwaway test symbol (ZZTEST*),
never touching any real cached symbol. Cleans up after itself.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data import DataStore, IBKRFeed

SYM = "ZZTEST"


def make_bars(start, n, freq="1min"):
    idx = pd.date_range(start, periods=n, freq=freq)
    rng = np.random.default_rng(0)
    close = 100 + rng.normal(0, 0.1, n).cumsum()
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": rng.integers(100, 1000, n),
        },
        index=idx,
    )


def cleanup():
    for tf in ["1m", "2m", "3m", "1h", "4h"]:
        path = DataStore._path(SYM, tf)
        if os.path.exists(path):
            os.remove(path)


cleanup()
checks = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    checks.append(status)
    print(f"[{status}] {name}  {detail}")


# --- Day 1: first "run" fetches a fresh window, saved via append() (degrades
# to save() when nothing exists yet) ---
day1 = make_bars("2026-06-12 09:30", 390)  # one trading day of 1m bars
DataStore.append(SYM, "1m", day1)
loaded = DataStore.load(SYM, "1m")
check("Day 1: append() with no prior cache behaves like save()", len(loaded) == 390)

# --- Day 2: next "run" fetches a window that OVERLAPS day 1 (as a real
# yfinance/IBKR re-fetch would: same recent days + 1 new day) ---
day2_window = make_bars("2026-06-12 09:30", 390 * 2, "1min")  # 2 days, overlapping day1
DataStore.append(SYM, "1m", day2_window)
loaded2 = DataStore.load(SYM, "1m")
check(
    "Day 2: append() grows the archive (not wholesale-replaced)",
    len(loaded2) == 780,
    f"got {len(loaded2)} bars",
)
check(
    "Day 2: no duplicate timestamps after dedup",
    not loaded2.index.duplicated().any(),
)
check(
    "Day 2: overlapping bars keep the LATEST fetch's values (keep='last')",
    np.isclose(loaded2.loc[day2_window.index[0], "close"], day2_window.iloc[0]["close"]),
)

# --- Simulate a 3rd run that's a pure subset of what's already cached
# (e.g. yfinance gave a shorter window than what we already have).
# Use day1's exact start (guaranteed inside the cached range — day2_window's
# continuous 1-min calendar range doesn't respect trading-session breaks,
# so anchoring relative to "calendar days" elsewhere isn't reliable here). ---
day3_window = make_bars("2026-06-12 09:30", 100, "1min")
DataStore.append(SYM, "1m", day3_window)
loaded3 = DataStore.load(SYM, "1m")
check(
    "Day 3: appending a strict subset doesn't shrink the archive",
    len(loaded3) == 780,
    f"got {len(loaded3)} bars",
)

# --- Now replicate the edited 2m/3m-from-1m derivation block exactly ---
for tf_label, rule in IBKRFeed.RESAMPLED_FROM_1M:
    resampled = IBKRFeed._resample(loaded3, rule)
    if resampled is not None:
        DataStore.append(SYM, tf_label, resampled)

df_3m = DataStore.load(SYM, "3m")
check(
    "3m derivation covers the FULL accumulated 1m range, not just the latest fetch",
    df_3m.index.min() == loaded3.index.min() and df_3m.index.max() >= loaded3.index.max() - pd.Timedelta(minutes=3),
    f"3m range: {df_3m.index.min()} to {df_3m.index.max()} (1m range: {loaded3.index.min()} to {loaded3.index.max()})",
)

# --- Re-derive again (simulating the NEXT run) after 1m grows further ---
day4_window = make_bars("2026-06-12 09:30", 390 * 3, "1min")  # now 3 days
DataStore.append(SYM, "1m", day4_window)
loaded4 = DataStore.load(SYM, "1m")
for tf_label, rule in IBKRFeed.RESAMPLED_FROM_1M:
    resampled = IBKRFeed._resample(loaded4, rule)
    if resampled is not None:
        DataStore.append(SYM, tf_label, resampled)
df_3m_v2 = DataStore.load(SYM, "3m")
check(
    "3m grows further on the next run as 1m grows further (no is_fresh skip)",
    len(df_3m_v2) > len(df_3m),
    f"3m bars: {len(df_3m)} -> {len(df_3m_v2)}",
)

cleanup()
n_fail = checks.count("FAIL")
print()
print(f"{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
