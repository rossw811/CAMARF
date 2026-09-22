"""
Synthetic verification for research/fdr_threshold_sensitivity.py -- confirms tightening alpha
never INCREASES the confirmed-pair count (BH-FDR is monotonic in alpha by construction) and that
a genuinely tiny alpha can drive the count to 0, using a synthetic mix of strong-signal and
null-noise p-values (no real data, no 25-hour dependency).

Run: python debug/_verify_fdr_threshold_sensitivity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from research.wrds_deep_history_episodic_scan import episodic_bhfdr_confirm

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _build_rows(rng, n_strong_pairs=20, n_null_pairs=200, n_windows=8):
    rows = []
    for i in range(n_strong_pairs):
        for w in range(n_windows):
            rows.append({"symbol_a": f"STRONG{i}", "symbol_b": "X",
                         "pvalue": float(rng.uniform(0.0, 0.001))})
    for i in range(n_null_pairs):
        for w in range(n_windows):
            rows.append({"symbol_a": f"NULL{i}", "symbol_b": "X",
                         "pvalue": float(rng.uniform(0.0, 1.0))})
    return rows


def main():
    rng = np.random.default_rng(7)
    base_rows = _build_rows(rng)

    alphas = [0.05, 0.01, 0.001, 1e-6]
    counts = []
    for alpha in alphas:
        rows = [dict(r) for r in base_rows]
        confirmed = episodic_bhfdr_confirm(rows, alpha)
        counts.append(len(confirmed))
        print(f"  alpha={alpha}: {len(confirmed)} confirmed pairs")

    check("monotonic.non_increasing_as_alpha_tightens",
          all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)), counts)
    check("strong_signal.survives_at_baseline_alpha", counts[0] >= 15, counts[0])
    check("tiny_alpha.drives_toward_zero_or_near_zero", counts[-1] <= 5, counts[-1])

    # episodic_bhfdr_confirm mutates its input rows in place (adds fdr_rejected/
    # fdr_adjusted_pvalue) -- confirms that documented behavior directly, since
    # fdr_threshold_sensitivity.py's own main() depends on passing a FRESH copy per
    # alpha (reusing the same list across alphas would silently reuse stale flags).
    rows_a = [dict(r) for r in base_rows]
    episodic_bhfdr_confirm(rows_a, 0.05)
    check("mutates_input_rows_in_place", "fdr_rejected" in rows_a[0] and "fdr_adjusted_pvalue" in rows_a[0])

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
