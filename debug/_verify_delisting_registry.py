"""
Synthetic verification for task #68 (survivorship bias fix, 2026-07-14):
UniverseBuilder.flag_or_exclude() must classify a persistently-failing
symbol as "likely_delisted" (with a delisted_symbols.json registry entry
recording its last-known-good date) only when it already has substantial
cached daily history — and must fall back to the prior plain-exclusion
behavior (no registry entry) when it doesn't.

Verifies without touching the real production exclusion/registry files by
redirecting Config.DATA.CACHE_DIR and the UniverseBuilder path constants
into a temp directory for the duration of each case.
"""
import os
import sys
import json
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import Config, DataStore, UniverseBuilder


def _write_daily_cache(symbol: str, n_bars: int):
    dates = pd.bdate_range("2024-01-02", periods=n_bars, tz=None)
    closes = 100.0 + np.cumsum(np.random.default_rng(0).normal(0, 0.5, n_bars))
    df = pd.DataFrame(
        {
            "open": closes, "high": closes * 1.001, "low": closes * 0.999,
            "close": closes, "volume": 1_000_000,
        },
        index=dates,
    )
    DataStore.save(symbol, "1D", df)
    return df


def _run_case(n_bars: int, label: str):
    with tempfile.TemporaryDirectory() as d:
        orig_cache_dir = Config.DATA.CACHE_DIR
        orig_excl = UniverseBuilder._EXCLUSION_CACHE
        orig_reg = UniverseBuilder._DELISTED_REGISTRY
        Config.DATA.CACHE_DIR = d
        UniverseBuilder._EXCLUSION_CACHE = os.path.join(d, "excluded_assets.json")
        UniverseBuilder._DELISTED_REGISTRY = os.path.join(d, "delisted_symbols.json")
        try:
            symbol = "TESTSYM"
            df = _write_daily_cache(symbol, n_bars) if n_bars > 0 else None
            was_delisted = UniverseBuilder.flag_or_exclude(
                symbol, "Auto-excluded: 3 run failures", run_failures=3
            )

            registry = UniverseBuilder.load_delisted_registry()
            in_exclusions = symbol in UniverseBuilder.load_exclusions()

            print(f"[{label}] n_bars={n_bars} -> was_delisted={was_delisted}, "
                  f"in_exclusions={in_exclusions}, in_registry={symbol in registry}")

            assert in_exclusions, f"[{label}] symbol should always end up excluded"
            if n_bars >= UniverseBuilder._DELISTING_MIN_PRIOR_BARS:
                assert was_delisted, f"[{label}] expected likely_delisted classification"
                assert symbol in registry, f"[{label}] expected a registry entry"
                entry = registry[symbol]
                expected_last = str(df.index.max().date())
                assert entry["last_good_date"] == expected_last, (
                    f"[{label}] last_good_date mismatch: {entry['last_good_date']} "
                    f"!= {expected_last}"
                )
                assert entry["n_bars_1D"] == n_bars, f"[{label}] n_bars mismatch"
                print(f"  registry entry: {entry}")
            else:
                assert not was_delisted, f"[{label}] should NOT be classified delisted"
                assert symbol not in registry, f"[{label}] should have no registry entry"
            print(f"[{label}] PASS")
        finally:
            Config.DATA.CACHE_DIR = orig_cache_dir
            UniverseBuilder._EXCLUSION_CACHE = orig_excl
            UniverseBuilder._DELISTED_REGISTRY = orig_reg


if __name__ == "__main__":
    _run_case(n_bars=250, label="genuinely-tracked, now failing (250 daily bars)")
    _run_case(n_bars=59, label="just below threshold (59 bars)")
    _run_case(n_bars=60, label="exactly at threshold (60 bars)")
    _run_case(n_bars=5, label="thin/never-really-tracked (5 bars)")
    _run_case(n_bars=0, label="no cache at all (0 bars)")
    print("\nAll cases passed.")
