"""Synthetic verification for research/pair_source.py -- proves the shared
confirmed/candidate pair loader reads real output/results/*/pairs.parquet
and all_candidates.parquet correctly, skips _stale_ dirs, dedupes, and
filters by tf_label, using a throwaway synthetic results tree (never
touches the real output/results/)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import research.pair_source as ps

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


tmp = tempfile.mkdtemp(prefix="camarf_pair_source_test_")
try:
    ps._RESULTS_DIR = tmp

    os.makedirs(os.path.join(tmp, "1hr"))
    os.makedirs(os.path.join(tmp, "1day"))
    os.makedirs(os.path.join(tmp, "1hr_stale_20260101"))

    pd.DataFrame({"symbol_a": ["AAA", "CCC"], "symbol_b": ["BBB", "DDD"],
                  "tf_label": ["1h", "1h"]}).to_parquet(os.path.join(tmp, "1hr", "pairs.parquet"))
    pd.DataFrame({"symbol_a": ["AAA"], "symbol_b": ["BBB"],
                  "tf_label": ["1D"]}).to_parquet(os.path.join(tmp, "1day", "pairs.parquet"))
    pd.DataFrame({"symbol_a": ["ZZZ"], "symbol_b": ["YYY"],
                  "tf_label": ["1h"]}).to_parquet(os.path.join(tmp, "1hr_stale_20260101", "pairs.parquet"))

    pd.DataFrame({"symbol_a": ["AAA", "EEE"], "symbol_b": ["BBB", "FFF"],
                  "tf_label": ["1h", "1h"]}).to_parquet(os.path.join(tmp, "1hr", "all_candidates.parquet"))

    all_confirmed = ps.confirmed_pairs_list()
    check("confirmed pairs pooled across non-stale dirs (3 unique pairs: AAA/BBB, CCC/DDD from 1h+1D dedup)",
          set(all_confirmed) == {("AAA", "BBB"), ("CCC", "DDD")})

    check("stale dir excluded from confirmed pairs (ZZZ/YYY never appears)",
          ("ZZZ", "YYY") not in all_confirmed)

    confirmed_1h = ps.confirmed_pairs_list(tf_label="1h")
    check("tf_label filter restricts to 1h-only pairs",
          set(confirmed_1h) == {("AAA", "BBB"), ("CCC", "DDD")})

    confirmed_1d = ps.confirmed_pairs_list(tf_label="1D")
    check("tf_label filter correctly excludes a pair only confirmed at a different tf",
          confirmed_1d == [("AAA", "BBB")])

    candidates = ps.candidate_pairs_list()
    check("candidate pairs load from all_candidates.parquet, separate population from confirmed",
          set(candidates) == {("AAA", "BBB"), ("EEE", "FFF")})

    shutil.rmtree(os.path.join(tmp, "1hr"))
    shutil.rmtree(os.path.join(tmp, "1day"))
    shutil.rmtree(os.path.join(tmp, "1hr_stale_20260101"))
    empty = ps.confirmed_pairs_list()
    check("empty results tree returns empty list, not an error", empty == [])

finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
