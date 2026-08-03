"""
Integration-style verification of the WRDS-primary wiring added to
data.py::UniverseBuilder.build() (docs/HANDOFF.md's WRDS-replacement plan,
Phase C). Unlike the causality-fix verify scripts, this deliberately runs
against REAL cached WRDS data already on disk (output/cache/wrds/, ~20k
files) rather than synthetic data -- the thing actually being verified here
is I/O + real-schema compatibility (does data.py's read/rename/clean logic
work against files data_wrds.py actually produced), which a synthetic mock
would not meaningfully exercise.

Does NOT require a live WRDS connection -- reads only the already-fetched
parquet cache.

Checks, per real symbol/TF combination (AAPL across all 5 WRDS_PRIMARY_TFS):
  1. The read+rename logic (duplicated here to match data.py's nested
     _load_wrds_symbol_tf exactly, since it's a closure and not importable)
     produces a DataFrame with a 'close' column whose values match the raw
     file's close_total_return column, NOT its split-only close column --
     the exact BUG-D101-adjacent correctness requirement (docs/HANDOFF.md:
     "swapping WRDS's close_total_return into data.py's close column is the
     correct like-for-like replacement").
  2. DataCleaner.clean() (the real production function, imported directly)
     accepts the resulting DataFrame without crashing and returns a passing
     QualityReport for at least one real symbol/TF -- confirms MIN_BARS_
     REQUIRED / _standardize / _fill_gaps don't reject real WRDS-sourced
     data structurally.
  3. Config.DATA.WRDS_PRIMARY_TFS/WRDS_PRIMARY_ASSET_CLASSES are non-empty
     and contain only timeframes CRSP can actually provide (sanity check
     against the intraday-exclusion constraint documented in
     docs/HANDOFF.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from data import DataCleaner

_WRDS_CACHE_DIR = os.path.join(Config.DATA.CACHE_DIR, "wrds")
_TEST_SYMBOL = "AAPL"


def _load_wrds_symbol_tf(symbol: str, tf_label: str):
    """Mirrors data.py::build()'s nested _load_wrds_symbol_tf exactly."""
    path = os.path.join(_WRDS_CACHE_DIR, f"{symbol}_{tf_label}.parquet")
    if not os.path.exists(path):
        return None
    raw = pd.read_parquet(path)
    if raw.empty or "close_total_return" not in raw.columns:
        return None
    out = raw.drop(columns=["close"], errors="ignore").rename(
        columns={"close_total_return": "close"}
    )
    if not {"open", "high", "low"}.issubset(out.columns):
        for c in ("open", "high", "low"):
            out[c] = out["close"]
    return out


def main():
    failures = []

    if not os.path.isdir(_WRDS_CACHE_DIR):
        print(f"SKIPPED: {_WRDS_CACHE_DIR} does not exist on this machine — nothing to verify against.")
        return

    if not Config.DATA.WRDS_PRIMARY_TFS:
        failures.append("Config.DATA.WRDS_PRIMARY_TFS is empty")
    _INTRADAY = {"1m", "2m", "3m", "5m", "15m", "30m", "1h", "4h"}
    bad_tfs = Config.DATA.WRDS_PRIMARY_TFS & _INTRADAY
    if bad_tfs:
        failures.append(f"WRDS_PRIMARY_TFS contains intraday TFs CRSP cannot provide: {bad_tfs}")
    if not Config.DATA.WRDS_PRIMARY_ASSET_CLASSES:
        failures.append("Config.DATA.WRDS_PRIMARY_ASSET_CLASSES is empty")

    any_passed = False
    for tf_label in sorted(Config.DATA.WRDS_PRIMARY_TFS):
        raw_path = os.path.join(_WRDS_CACHE_DIR, f"{_TEST_SYMBOL}_{tf_label}.parquet")
        if not os.path.exists(raw_path):
            print(f"  {_TEST_SYMBOL}_{tf_label}: no cache file present, skipping (not a failure — machine-dependent)")
            continue

        raw_original = pd.read_parquet(raw_path)
        cleaned_input = _load_wrds_symbol_tf(_TEST_SYMBOL, tf_label)
        if cleaned_input is None:
            failures.append(f"{tf_label}: _load_wrds_symbol_tf returned None despite file existing")
            continue

        # Check 1: close column is the TOTAL-RETURN series, not split-only.
        if "close" not in cleaned_input.columns:
            failures.append(f"{tf_label}: no 'close' column after rename")
        else:
            common_idx = cleaned_input.index.intersection(raw_original.index)
            if len(common_idx) == 0:
                failures.append(f"{tf_label}: no overlapping index between raw and renamed frames")
            else:
                got = cleaned_input.loc[common_idx, "close"]
                expected_tr = raw_original.loc[common_idx, "close_total_return"]
                expected_split_only = raw_original.loc[common_idx, "close"] if "close" in raw_original.columns else None
                tr_match = np.allclose(got.values, expected_tr.values, equal_nan=True)
                if not tr_match:
                    failures.append(f"{tf_label}: renamed 'close' does not match original 'close_total_return' values")
                if expected_split_only is not None:
                    split_match = np.allclose(got.values, expected_split_only.values, equal_nan=True)
                    # A stock with zero dividends over the whole window would make
                    # tr==split_only trivially -- AAPL has paid dividends since
                    # 2012, so on a long enough history these MUST differ, or the
                    # rename silently kept the wrong column.
                    if split_match and len(common_idx) > 500:
                        failures.append(f"{tf_label}: renamed 'close' equals split-only close over {len(common_idx)} bars — rename likely picked the wrong column")

        # Check 2: DataCleaner.clean() accepts it.
        try:
            cleaned, report = DataCleaner.clean(
                cleaned_input, _TEST_SYMBOL, "equity", tf_label, tf_label, source="wrds"
            )
        except Exception as e:
            failures.append(f"{tf_label}: DataCleaner.clean() raised {type(e).__name__}: {e}")
            continue

        if report.passed:
            any_passed = True
            print(f"  {tf_label}: OK — {len(cleaned)} bars, close range [{cleaned['close'].min():.2f}, {cleaned['close'].max():.2f}]")
        else:
            print(f"  {tf_label}: DataCleaner rejected — {report.fail_reason} (not necessarily a bug, e.g. insufficient bars for a short-history TF)")

    if not any_passed:
        failures.append(f"DataCleaner.clean() never passed for any {_TEST_SYMBOL} TF — nothing usable would ever be wired in")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nWRDS-primary wiring verification passed (against real cached data).")


if __name__ == "__main__":
    main()
