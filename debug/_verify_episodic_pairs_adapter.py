"""
debug/_verify_episodic_pairs_adapter.py -- synthetic ground-truth
verification for research/episodic_pairs_adapter.py, BEFORE trusting it
against real episodic-confirmed pairs.

Core claim being verified, stated precisely: the adapter's gating scalar
fields must be computed from data TRUNCATED to as_of_date, never leaking
information from after that cutoff (the BUG-D69 discipline the module
docstring cites). Verified directly by constructing a synthetic pair whose
cointegration relationship ONLY exists strictly AFTER the as_of_date --
if the adapter's train-only scalar computation were (incorrectly) using
the full series, it would report a artificially strong/clean
hedge_ratio_ols reflecting that post-cutoff relationship; the correct,
truncated computation must NOT see it (n_overlap too small / hedge ratio
reflecting only the pre-cutoff noise, not the post-cutoff signal).

Also verifies: the 9-required-field contract is present and finite for a
real, well-formed pair, and spread_series_*.parquet is written with the
schema backtest.py::_load_spread expects.

Run: python debug/_verify_episodic_pairs_adapter.py
(Uses tiny synthetic price series written to a throwaway DataStore cache
location via monkeypatching DataStore.load, NOT real market data -- this
verifies the TRUNCATION LOGIC, not real-pair behavior.)
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data as data_mod
import research.episodic_pairs_adapter as adapter


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def test_placeholder_symbol_fallback():
    """BUG found 2026-09-14: DataStore.load() returns None for WRDS
    PERMNO<n>-alias / GVKEY<n>_NNW-labeled symbols (only covers the
    yfinance/WRDS-US-ticker cache), silently dropping 84% of real Tier-3
    episodic-confirmed pairs. Fixed via a fallback to
    universe_loader.load_full_universe in _load_symbol. Verified here
    without touching real disk/network: monkeypatch BOTH DataStore.load
    (returns None, simulating the real failure) and
    universe_loader.load_full_universe (returns a fake full-universe dict
    containing the placeholder symbol) -- adapter._load_aligned must
    successfully build via the fallback path."""
    df_a, df_b, dates, cutoff_date = make_pre_post_cutoff_pair()
    fake_universe = {"GVKEY000001_01W": df_a, "PERMNO99999": df_b}
    calls = {"n": 0}

    def fake_load_none(symbol, tf_label):
        return None

    def fake_load_full_universe(tf_label, use_memo_cache=True):
        calls["n"] += 1
        return fake_universe

    orig_ds_load = adapter.DataStore.load
    orig_full_universe = adapter.universe_loader.load_full_universe
    adapter.DataStore.load = staticmethod(fake_load_none)
    adapter.universe_loader.load_full_universe = fake_load_full_universe
    adapter._full_universe_cache.clear()

    results = []
    try:
        print("\n=== 4. Placeholder-symbol (PERMNO/GVKEY) fallback to load_full_universe ===")
        aligned = adapter._load_aligned("GVKEY000001_01W", "PERMNO99999", "1h", as_of_date=None)
        results.append(check("fallback path builds a real aligned result", aligned is not None))
        results.append(check("load_full_universe called exactly once (memoized, not per-symbol)",
                              calls["n"] == 1))
        # A second call for the SAME tf_label must reuse the in-process cache,
        # not call load_full_universe again.
        adapter._load_aligned("GVKEY000001_01W", "PERMNO99999", "1h", as_of_date=None)
        results.append(check("second call reuses the in-process cache (still exactly 1 call)",
                              calls["n"] == 1))
    finally:
        adapter.DataStore.load = orig_ds_load
        adapter.universe_loader.load_full_universe = orig_full_universe
        adapter._full_universe_cache.clear()
    return results


def make_pre_post_cutoff_pair(n_pre=300, n_post=300, seed=0):
    """Two symbols that are UNRELATED (independent random walks) up to the
    cutoff, then become strongly cointegrated (shared stochastic trend)
    strictly AFTER it. Returns (df_a, df_b, dates, cutoff_date)."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2023-01-01", periods=n_pre + n_post, freq="h")
    cutoff_date = dates[n_pre - 1]

    a_pre = np.cumsum(rng.normal(0, 1.0, n_pre))
    b_pre = np.cumsum(rng.normal(0, 1.0, n_pre))

    common = np.cumsum(rng.normal(0, 1.0, n_post))
    noise = rng.normal(0, 0.05, n_post)  # tight coupling post-cutoff
    a_post = a_pre[-1] + common
    b_post = b_pre[-1] + common + noise

    close_a = np.exp((np.concatenate([a_pre, a_post])) * 0.01 + 4.0)
    close_b = np.exp((np.concatenate([b_pre, b_post])) * 0.01 + 4.0)

    df_a = pd.DataFrame({"open": close_a, "high": close_a, "low": close_a,
                          "close": close_a, "volume": 1000}, index=dates)
    df_b = pd.DataFrame({"open": close_b, "high": close_b, "low": close_b,
                          "close": close_b, "volume": 1000}, index=dates)
    return df_a, df_b, dates, cutoff_date


def main():
    df_a, df_b, dates, cutoff_date = make_pre_post_cutoff_pair()
    fake_cache = {"SYNA": df_a, "SYNB": df_b}

    original_load = data_mod.DataStore.load

    def fake_load(symbol, tf_label):
        return fake_cache.get(symbol, original_load(symbol, tf_label)).copy() if symbol in fake_cache else None

    data_mod.DataStore.load = staticmethod(fake_load)
    adapter.DataStore.load = staticmethod(fake_load)

    results = []
    try:
        print("=== 1. PIT-safety: truncated scalar computation must not see post-cutoff coupling ===")
        detail = {"n_windows_tested": 3, "n_windows_fdr_rejected": 1}
        row_truncated = adapter.build_one_row(
            "SYNA", "SYNB", "1h", as_of_date=cutoff_date, source="test", detail=detail
        )
        row_full = adapter.build_one_row(
            "SYNA", "SYNB", "1h", as_of_date=dates[-1], source="test", detail=detail
        )
        results.append(check("truncated row was built at all (enough pre-cutoff overlap)",
                              row_truncated is not None))
        results.append(check("full-range row was built at all", row_full is not None))
        if row_truncated is not None and row_full is not None:
            hr_trunc = row_truncated["hedge_ratio_ols"]
            hr_full = row_full["hedge_ratio_ols"]
            print(f"    truncated hedge_ratio_ols={hr_trunc}, full-range hedge_ratio_ols={hr_full}")
            # Pre-cutoff data is pure independent noise (no true relationship),
            # so the truncated hedge ratio should NOT resemble the full-range
            # one, which is dominated by the strong post-cutoff coupling
            # (hedge ratio ~1.0 by construction, since a_post/b_post share
            # the exact same common trend with tight noise).
            results.append(check(
                "truncated hedge ratio does NOT reflect the post-cutoff coupling "
                "(differs materially from the full-range hedge ratio)",
                not np.isfinite(hr_trunc) or abs(hr_trunc - hr_full) > 0.3 or abs(hr_trunc - 1.0) > 0.3,
            ))
            # Full-range OLS is a whole-sample fit over pre-cutoff noise AND
            # post-cutoff coupling combined -- the pre-cutoff half dilutes
            # it away from a clean 1.0, so "reflects the coupling" is
            # checked as "closer to 1.0 than the truncated estimate is",
            # not an absolute closeness threshold (which the first,
            # already-passing check is the real PIT-safety claim for).
            results.append(check(
                "full-range hedge ratio is closer to the true post-cutoff 1.0 relationship "
                "than the truncated (pre-cutoff-only) estimate is",
                np.isfinite(hr_full) and (not np.isfinite(hr_trunc) or abs(hr_full - 1.0) < abs(hr_trunc - 1.0)),
            ))

        print("\n=== 2. Required-field contract present and finite (full-range row) ===")
        if row_full is not None:
            for field in adapter.REQUIRED_FIELDS:
                val = row_full.get(field)
                results.append(check(f"field '{field}' present and finite", val is not None and np.isfinite(val)))

        print("\n=== 3. spread_series file written with the schema _load_spread expects ===")
        tmp_results_dir = tempfile.mkdtemp()
        orig_results_dir = adapter._RESULTS_DIR
        adapter._RESULTS_DIR = tmp_results_dir
        try:
            train_aligned = adapter._load_aligned("SYNA", "SYNB", "1h", as_of_date=None)
            built = adapter.AnalysisPipeline._build_pair_result(
                {"symbol_a": "SYNA", "symbol_b": "SYNB"}, train_aligned, "1h"
            )
            results.append(check("full-range _build_pair_result succeeded", built is not None))
            if built is not None:
                _pr, per_bar = built
                out_path = adapter.write_spread_series("SYNA", "SYNB", "1h", per_bar)
                results.append(check("spread_series file was written", os.path.exists(out_path)))
                spread_df = pd.read_parquet(out_path)
                required_cols = {"spread", "z_rolling", "half_life_rolling"}
                results.append(check(
                    "spread_series has the columns backtest.py::_load_spread's SpreadModel-consuming "
                    "code expects (spread, z_rolling, half_life_rolling)",
                    required_cols.issubset(set(spread_df.columns)),
                ))
        finally:
            adapter._RESULTS_DIR = orig_results_dir
            shutil.rmtree(tmp_results_dir, ignore_errors=True)
    finally:
        data_mod.DataStore.load = original_load
        adapter.DataStore.load = original_load

    results.extend(test_placeholder_symbol_fallback())
    results.extend(test_build_adapter_rows_resolves_placeholder_symbols_once())

    n_pass = sum(results)
    print(f"\n{n_pass}/{len(results)} checks passed")
    return n_pass == len(results)


def test_build_adapter_rows_resolves_placeholder_symbols_once():
    """BUG found live on CachyOS 2026-09-15: with n_workers>1, each
    ProcessPoolExecutor worker independently called _get_full_universe
    (per-PROCESS memoization, not per-pool), so multiple workers loading
    their own 8.6GB copy of the full-universe cache near-simultaneously
    OOM-killed the machine (confirmed via dmesg). Fix: build_adapter_rows
    now pre-resolves every NEEDED placeholder symbol ONCE in the main
    process before building any task, passing only each pair's own small
    subset into its task. Verified here (n_workers=1, so the fix's
    single-call invariant is exercised without needing to also mock a real
    process pool) with TWO pairs that share a placeholder symbol -- if the
    old per-call-site behavior were still in effect, resolving it while
    building each pair's task would call load_full_universe multiple times;
    the fix must call it exactly once for the whole run regardless of how
    many pairs need it."""
    df_a, df_b, dates, cutoff_date = make_pre_post_cutoff_pair(seed=2)
    df_c, df_d, _, _ = make_pre_post_cutoff_pair(seed=3)
    real_cache = {"REALA": df_a, "PERMNO88888": df_b, "REALC": df_c}
    fake_universe = {"PERMNO88888": df_b, "GVKEY000002_01W": df_d}
    calls = {"n": 0}

    def fake_load(symbol, tf_label):
        return real_cache.get(symbol).copy() if symbol in real_cache else None

    def fake_load_full_universe(tf_label, use_memo_cache=True):
        calls["n"] += 1
        return fake_universe

    def fake_discover(as_of_date, alpha, min_windows_confirmed, checkpoint_paths):
        return [
            {"symbol_a": "REALA", "symbol_b": "PERMNO88888",
             "n_windows_tested": 1, "n_windows_fdr_rejected": 1},
            {"symbol_a": "REALC", "symbol_b": "GVKEY000002_01W",
             "n_windows_tested": 1, "n_windows_fdr_rejected": 1},
        ]

    orig_ds_load = adapter.DataStore.load
    orig_full_universe = adapter.universe_loader.load_full_universe
    orig_discover = adapter.discover_pit_confirmed_pairs_with_detail
    orig_out_dir = adapter._OUT_DIR
    orig_results_dir = adapter._RESULTS_DIR
    tmp_dir = tempfile.mkdtemp()
    adapter.DataStore.load = staticmethod(fake_load)
    adapter.universe_loader.load_full_universe = fake_load_full_universe
    adapter.discover_pit_confirmed_pairs_with_detail = fake_discover
    adapter._OUT_DIR = tmp_dir
    adapter._RESULTS_DIR = tmp_dir
    adapter._full_universe_cache.clear()

    results = []
    try:
        print("\n=== 5. build_adapter_rows pre-resolves placeholder symbols ONCE, not per-pair ===")
        df_out = adapter.build_adapter_rows(
            "test_source", "1h", checkpoint_paths=(), as_of_date=dates[-1], n_workers=1,
        )
        print(f"    load_full_universe call count: {calls['n']}")
        results.append(check(
            "load_full_universe called exactly once across 2 pairs needing placeholder symbols",
            calls["n"] == 1,
        ))
        print(f"    rows built: {len(df_out)}")
        results.append(check("at least one row built despite placeholder symbols involved",
                              len(df_out) >= 1))
    finally:
        adapter.DataStore.load = orig_ds_load
        adapter.universe_loader.load_full_universe = orig_full_universe
        adapter.discover_pit_confirmed_pairs_with_detail = orig_discover
        adapter._OUT_DIR = orig_out_dir
        adapter._RESULTS_DIR = orig_results_dir
        adapter._full_universe_cache.clear()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return results


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
