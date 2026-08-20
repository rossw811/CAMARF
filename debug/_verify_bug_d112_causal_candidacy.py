"""
Synthetic verification of BUG-D112's fix (causal candidate-generation
gating for Tier 3's rolling correlation prefilter) BEFORE trusting it on
the real, multi-hour episodic re-scan.

Checks:
  1. A pair correlated ONLY in LATE windows must NOT get EG-tested on an
     EARLY window that predates its first correlation evidence -- the
     exact BUG-D112 mechanism, reproduced synthetically and confirmed
     fixed. Checked SELF-CONSISTENTLY (every EG-task window_end_date >=
     the pair's own recorded first_qualified_window_end_date), not via
     hardcoded window-index arithmetic.
  2. A pair correlated from the FIRST window onward must still get
     EG-tested on (approximately) every window (the fix must not become
     overly conservative and drop legitimately-eligible later windows).
  3. first_qualified_window_end_date is the TRUE MINIMUM window_end_date
     across all windows where a pair qualifies, not the best-correlation
     window's date -- constructed so a pair's best-correlation window is
     LATE while its (weaker but still threshold-clearing) first-qualifying
     window is EARLY, and confirmed the two are correctly distinguished.
  4. Tier 2 is no longer referenced anywhere in the PIT-safe pair-discovery
     path (pit_pair_discovery.py's _DEFAULT_CHECKPOINT_PATHS,
     episodic_pairs_adapter.py's main() sources).
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.wrds_deep_history_episodic_scan import (
    rolling_correlation_candidate_pairs, build_rolling_eg_tasks,
)


def main():
    failures = []
    rng = np.random.default_rng(11)

    # window must clear UniverseFilter._pairwise_corr's min_overlap=30 floor
    # (found live: window=20 silently produced an all-NaN correlation matrix
    # -- a real constraint of the production code this test must respect).
    window, step = 40, 20
    n_bars = 200  # windows: [0:40],[20:60],[40:80],...,[160:200] (9 windows)
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="24h")
    symbols = ["A", "B", "C", "D", "E"]

    # A/B: independent noise for bars [0:100), strongly correlated for
    # bars [100:200) -- only windows fully inside the late region should
    # qualify (window covering [100:140] onward).
    shared_late = rng.normal(size=n_bars) * 0.02
    ret_a = rng.normal(size=n_bars) * 0.02
    ret_a[100:] = shared_late[100:] * 0.95 + rng.normal(size=n_bars - 100) * 0.001
    ret_b = rng.normal(size=n_bars) * 0.02
    ret_b[100:] = shared_late[100:] * 0.95 + rng.normal(size=n_bars - 100) * 0.001

    # C/D: strongly correlated throughout [0:200) -- should qualify at the
    # very first window and get tested on (nearly) all windows.
    shared_early = rng.normal(size=n_bars) * 0.02
    ret_c = shared_early * 0.95 + rng.normal(size=n_bars) * 0.001
    ret_d = shared_early * 0.95 + rng.normal(size=n_bars) * 0.001

    # C/E: WEAKLY correlated throughout (clears threshold but not by much),
    # with a much STRONGER correlated stretch only in the late region --
    # best-correlation window should be late, first-qualifying window early.
    ret_e = shared_early * 0.75 + rng.normal(size=n_bars) * 0.012
    ret_e[140:] = shared_early[140:] * 0.99 + rng.normal(size=n_bars - 140) * 0.0003

    returns_df = pd.DataFrame(
        {"A": ret_a, "B": ret_b, "C": ret_c, "D": ret_d, "E": ret_e}, index=dates
    )
    log_price_df = returns_df.cumsum() + 100
    asset_class_map = {s: "equity" for s in symbols}

    candidates = rolling_correlation_candidate_pairs(
        returns_df, symbols, threshold=0.5, asset_class_map=asset_class_map,
        window=window, step=step,
    )
    by_key = {frozenset((p["symbol_a"], p["symbol_b"])): p for p in candidates}

    ab_key, cd_key, ce_key = frozenset(("A", "B")), frozenset(("C", "D")), frozenset(("C", "E"))
    for key, name in [(ab_key, "A/B"), (cd_key, "C/D"), (ce_key, "C/E")]:
        if key not in by_key:
            failures.append(f"{name} should qualify as a candidate")

    # --- Check 3: first_qualified != best-correlation window ---
    if ce_key in by_key:
        ce = by_key[ce_key]
        # best correlation must come from the late, near-1.0 window; first-
        # qualifying window must be earlier than that.
        if ce["pearson_corr"] < 0.9:
            failures.append(f"C/E best pearson_corr should reflect the late strong-correlation "
                             f"window (>=0.9), got {ce['pearson_corr']}")
        if ce["first_qualified_window_end_date"] >= dates[139]:
            failures.append(f"C/E first_qualified_window_end_date ({ce['first_qualified_window_end_date']}) "
                             f"should be well before the late strong-correlation region (dates[139]="
                             f"{dates[139]}) -- best-corr and first-qualified windows may have been "
                             f"conflated (the original BUG-D112 mechanism)")

    if ab_key in by_key:
        if by_key[ab_key]["first_qualified_window_end_date"] < dates[99]:
            failures.append(f"A/B first_qualified_window_end_date should not be before the late "
                             f"correlated region starts (dates[99]={dates[99]}), got "
                             f"{by_key[ab_key]['first_qualified_window_end_date']}")

    # --- Checks 1 & 2: build_rolling_eg_tasks gating, self-consistent ---
    array_cache = {s: log_price_df[s].to_numpy() for s in log_price_df.columns}
    tasks, task_meta = build_rolling_eg_tasks(
        candidates, log_price_df, max_lag=1, window=window, step=step, array_cache=array_cache,
    )

    for key, name in [(ab_key, "A/B"), (cd_key, "C/D")]:
        if key not in by_key:
            continue
        first_q = by_key[key]["first_qualified_window_end_date"]
        pair_meta = [m for m in task_meta if frozenset((m[0], m[1])) == key]
        too_early = [m for m in pair_meta if m[5] < first_q]
        if too_early:
            failures.append(f"BUG-D112 NOT fixed: {name} got EG-tested on {len(too_early)} window(s) "
                             f"dated before its own first_qualified_window_end_date ({first_q}): "
                             f"{too_early}")

    if cd_key in by_key:
        cd_meta = [m for m in task_meta if frozenset((m[0], m[1])) == cd_key]
        n_cd_windows = len(set(m[2] for m in cd_meta))
        total_windows = (n_bars - window) // step + 1
        if n_cd_windows < total_windows - 1:  # allow off-by-one at the boundary
            failures.append(f"C/D (qualifies at the first window) should be tested on ~{total_windows} "
                             f"windows, got {n_cd_windows} -- fix may be overly conservative")

    # --- Check 4: Tier 2 no longer referenced ---
    from research.pit_pair_discovery import _DEFAULT_CHECKPOINT_PATHS
    if any("tier2" in p for p in _DEFAULT_CHECKPOINT_PATHS):
        failures.append(f"pit_pair_discovery._DEFAULT_CHECKPOINT_PATHS still references Tier 2: "
                         f"{_DEFAULT_CHECKPOINT_PATHS}")
    from research import episodic_pairs_adapter
    adapter_src = inspect.getsource(episodic_pairs_adapter.main)
    if "tier2" in adapter_src:
        failures.append("episodic_pairs_adapter.main()'s sources list still references Tier 2")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All BUG-D112 causal-candidacy checks passed.")
    print(f"  A/B first_qualified_window_end_date: {by_key.get(ab_key, {}).get('first_qualified_window_end_date')}")
    print(f"  C/D first_qualified_window_end_date: {by_key.get(cd_key, {}).get('first_qualified_window_end_date')}")
    print(f"  C/E best corr={by_key.get(ce_key, {}).get('pearson_corr')}, "
          f"first_qualified={by_key.get(ce_key, {}).get('first_qualified_window_end_date')}")


if __name__ == "__main__":
    main()
