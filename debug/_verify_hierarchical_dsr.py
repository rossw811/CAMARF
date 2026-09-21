"""
Synthetic verification for research/hierarchical_dsr.py -- no live data,
fabricated trial registries and a fabricated trades file with a KNOWN
family structure and a known directional property (family-scoped DSR must
be >= pooled DSR when the family's own N is smaller than the pooled N,
holding SR_hat/T/skew/kurt fixed -- fewer "chances" means a smaller
expected-max-Sharpe-by-chance subtracted off).

Run: python debug/_verify_hierarchical_dsr.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.hierarchical_dsr import (
    classify_family, load_merged_trials, family_var_sr, _daily_pnl_stats,
)
from deflated_sharpe import deflated_sharpe_ratio, deflated_sharpe_z_stat

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_classify_family_known_labels():
    cases = [
        ("layer1", "baseline"),
        ("layer1_holdout", "baseline"),
        ("layer1_pairsoverride_ovSTOP_ZSCORE3p0", "sens_stop_zscore"),
        ("layer1_holdout_pairsoverride_ovSTOP_ZSCORE3p0_capsim_fixed_100000", "sens_stop_zscore"),
        ("layer1_storm_sqzmomgate_pairsoverride", "squeeze_momentum_gate"),
        ("layer1_holdout_storm_momgate_pairsoverride", "squeeze_momentum_gate"),
        ("layer1_ez20_pairsoverride", "entry_zscore_override"),
        ("layer1_ez20_ezmax205_pairsoverride", "entry_zscore_override"),
        ("layer1_holdout_hrp", "portfolio_construction"),
        ("layer1_holdout_pnlcap", "portfolio_construction"),
        ("layer1_pairsoverride_capsim_full_kelly_100000", "capital_sizing_scheme"),
        ("layer1_holdout_pitconf_pairsoverride", "pit_confirmation"),
        ("layer2", "layer2_baseline"),
        ("layer2_holdout", "layer2_baseline"),
        ("layer1_storm", "storm_other"),
        ("layer1_holdout_storm_cfrac", "storm_other"),
        ("totally_unrecognized_experimental_label_xyz", "unclassified"),
    ]
    all_ok = True
    for label, expected in cases:
        actual = classify_family(label)
        ok = actual == expected
        all_ok = all_ok and ok
        if not ok:
            print(f"    MISMATCH: '{label}' -> got '{actual}', expected '{expected}'")
    check("classify_family.matches_known_labels", all_ok)


def test_load_merged_trials_no_dedup():
    with tempfile.TemporaryDirectory() as d:
        p1 = os.path.join(d, "reg1.json")
        p2 = os.path.join(d, "reg2.json")
        t1 = [{"label": "layer1", "sharpe": 1.0, "n_trades": 10, "timestamp_run": None}]
        t2 = [{"label": "layer1", "sharpe": 1.0, "n_trades": 10, "timestamp_run": None},
              {"label": "layer1_holdout", "sharpe": 0.5, "n_trades": 5, "timestamp_run": None}]
        with open(p1, "w") as f:
            json.dump(t1, f)
        with open(p2, "w") as f:
            json.dump(t2, f)
        merged = load_merged_trials([p1, p2])
        check("load_merged_trials.no_dedup_sums_counts", len(merged) == 3, len(merged))


def test_family_var_sr_matches_manual_computation():
    trials = [
        {"label": "x", "sharpe": 1.0}, {"label": "x", "sharpe": 2.0},
        {"label": "x", "sharpe": 3.0}, {"label": "x", "sharpe": 4.0},
    ]
    annualization = np.sqrt(252)
    manual = float(np.var(np.array([1.0, 2.0, 3.0, 4.0]) / annualization, ddof=1))
    got = family_var_sr(trials)
    check("family_var_sr.matches_manual_var", abs(got - manual) < 1e-12, f"got={got} manual={manual}")

    check("family_var_sr.single_trial_returns_zero", family_var_sr([{"label": "x", "sharpe": 1.0}]) == 0.0)


def test_daily_pnl_stats_synthetic_trades():
    with tempfile.TemporaryDirectory() as d:
        n = 60
        rng = np.random.default_rng(3)
        dates = pd.date_range("2023-01-01", periods=n, freq="1D")
        trades = pd.DataFrame({
            "entry_time": dates, "exit_time": dates,
            "pnl_net": rng.normal(5.0, 20.0, n),
        })
        path = os.path.join(d, "trades_test.parquet")
        trades.to_parquet(path)
        result = _daily_pnl_stats(path)
        check("daily_pnl_stats.returns_tuple_for_valid_trades", result is not None)
        if result is not None:
            sr_hat, t_obs, skew, kurt = result
            check("daily_pnl_stats.t_obs_matches_n_days", t_obs == n, t_obs)
            check("daily_pnl_stats.sr_hat_is_finite", np.isfinite(sr_hat))

        check("daily_pnl_stats.missing_file_returns_none",
              _daily_pnl_stats(os.path.join(d, "does_not_exist.parquet")) is None)


def test_family_scoped_dsr_less_penalized_than_pooled():
    # Fixed SR_hat/T/skew/kurt (as if from one real trades file). Family has a SMALL
    # n_trials (5) with LOW variance; pooled pool has the SAME 5 plus 500 unrelated
    # high-variance dummy trials appended (simulating the real registry's hundreds of
    # unrelated parameter-sensitivity grid points). Family-scoped DSR must be >=
    # pooled DSR -- fewer independent "chances" means a smaller expected-max-Sharpe-
    # under-the-null subtracted off, so the SAME observed result looks LESS like a
    # lucky draw once scoped to its own family.
    sr_hat, t_obs, skew, kurt = 0.15, 200, 0.5, 4.0

    rng = np.random.default_rng(7)
    family_sharpes = rng.normal(0.5, 0.3, 5)
    pooled_sharpes = np.concatenate([family_sharpes, rng.normal(0.0, 3.0, 500)])

    n_family, n_pooled = len(family_sharpes), len(pooled_sharpes)
    var_family = float(np.var(family_sharpes, ddof=1))
    var_pooled = float(np.var(pooled_sharpes, ddof=1))

    dsr_family = deflated_sharpe_ratio(sr_hat, t_obs, skew, kurt, n_family, var_family)
    dsr_pooled = deflated_sharpe_ratio(sr_hat, t_obs, skew, kurt, n_pooled, var_pooled)

    check("family_dsr.less_or_equally_penalized_than_pooled", dsr_family >= dsr_pooled,
          f"family_dsr={dsr_family:.4f} pooled_dsr={dsr_pooled:.4f} "
          f"(n_family={n_family} n_pooled={n_pooled})")
    check("family_dsr.pooled_still_a_valid_probability", 0.0 <= dsr_pooled <= 1.0)
    check("family_dsr.family_still_a_valid_probability", 0.0 <= dsr_family <= 1.0)


if __name__ == "__main__":
    test_classify_family_known_labels()
    test_load_merged_trials_no_dedup()
    test_family_var_sr_matches_manual_computation()
    test_daily_pnl_stats_synthetic_trades()
    test_family_scoped_dsr_less_penalized_than_pooled()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
