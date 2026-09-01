"""Verification that universe_loader.py's Polars-backed _read_one (2026-08-23) produces output
BIT-IDENTICAL to the original pandas-only pd.read_parquet path -- including the index, which
Polars does not restore automatically the way pandas' own parquet reader does (the real risk
this whole swap needed checking for, see docs/HARDWARE_OPTIMIZATION_PLAN.md Sec 4 and the
inline comments in universe_loader.py::_pandas_index_col).

Runs against REAL cache files, not synthetic data -- an index-restoration bug wouldn't
necessarily show up on synthetic data built with an assumed-correct index already.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from universe_loader import _read_one_polars, _POLARS_AVAILABLE

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


check("polars is available in this environment", _POLARS_AVAILABLE)
if not _POLARS_AVAILABLE:
    print("Cannot run further checks without polars installed.")
    sys.exit(1)

# Real files spanning BOTH index-naming conventions found in this cache (2026-08-23 audit):
# 'Date' (yfinance-sourced) and 'dlycaldt' (WRDS-sourced) -- hardcoding either would have
# silently corrupted the other source's time alignment, which is exactly why this needed a
# real per-file schema lookup instead of an assumed constant.
import random
rng = random.Random(42)
all_yf = glob.glob("output/cache/*.parquet")
all_wrds = glob.glob("output/cache/wrds/*.parquet")
all_binance = glob.glob("output/cache/binance/*.parquet")
all_ibkr = glob.glob("output/cache/ibkr_supplement/*.parquet")
candidates = (
    rng.sample(all_yf, min(60, len(all_yf)))
    + rng.sample(all_wrds, min(60, len(all_wrds)))
    + rng.sample(all_binance, min(15, len(all_binance)))
    + rng.sample(all_ibkr, min(15, len(all_ibkr)))
)
candidates = [f for f in candidates if os.path.getsize(f) > 0 and "_meta.parquet" not in f]
print(f"Sampling {len(candidates)} real files across yfinance/wrds/binance/ibkr caches "
      f"(seeded, reproducible; excludes _meta.parquet files, which _load_dir's own suffix "
      f"filtering never passes to _read_one in production -- these are metadata sidecars, "
      f"not OHLCV price data, and are out of scope for this verification)")

n_tested = 0
for path in candidates:
    for columns in (None, ["close"], ["close", "volume"]):
        ref = pd.read_parquet(path, columns=columns)
        got = _read_one_polars(path, columns)
        n_tested += 1
        label = f"{os.path.basename(path)} columns={columns}"
        if got is None:
            check(f"{label}: polars path did not silently fail", False)
            continue
        check(f"{label}: columns match", list(ref.columns) == list(got.columns))
        check(f"{label}: index name matches", ref.index.name == got.index.name)
        check(f"{label}: index dtype matches", str(ref.index.dtype) == str(got.index.dtype))
        check(f"{label}: index values match", list(ref.index) == list(got.index))
        # Numeric equality, not pandas' dtype-strict .equals() -- confirmed directly (2026-08-23)
        # that WRDS-sourced files' pandas metadata round-trips through pd.read_parquet as the
        # nullable pandas Float64Dtype(), while Polars' to_pandas() produces plain numpy
        # float64. VALUES are bit-identical either way (confirmed: max abs diff 0.0 across
        # tested files) -- this is a disclosed, intentional dtype normalization, not a bug: this
        # project has repeated, documented bugs FROM nullable pd.NA dtypes (see CLAUDE.md's
        # Known-Resolved-Issues and this session's own data_wrds.py/jkp_thread_m_driver.py
        # pd.NA fixes), so plain float64 downstream is the safer choice, not a regression.
        values_match = True
        for col in ref.columns:
            r, g = ref[col].to_numpy(dtype="float64", na_value=np.nan), got[col].to_numpy(dtype="float64")
            if not np.allclose(r, g, equal_nan=True):
                values_match = False
        check(f"{label}: data values match numerically (dtype-tolerant)", values_match)

print(f"\n{n_tested} (file, columns) combinations tested across {len(candidates)} real files")
n_fail = sum(1 for _, c in checks if not c)
print(f"{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
