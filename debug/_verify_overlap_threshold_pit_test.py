# =============================================================================
# Synthetic verification of research/overlap_threshold_pit_test.py's OWN new
# logic (fold-date spacing, lead-lag detection, bucket/aggregate summary).
#
# Does NOT re-test screen_universe_at_cutoff/backtest_pair_on_test_window
# themselves -- those are pit_wfa_wrds_daily.py's own functions, already
# covered by debug/_verify_pit_wfa_wrds_daily.py. Re-verifying them here
# would duplicate coverage without proving anything about the NEW code this
# file actually adds.
# =============================================================================
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.overlap_threshold_pit_test import (
    _fold_start_dates, _mechanical_lead_lag, summarize, _BARS_TO_CALENDAR_DAYS,
)

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# --- _fold_start_dates ---

# 1. A universe window with plenty of room for the largest L + OOS produces
#    n_folds distinct, ordered start dates strictly within [start, end).
u_start = pd.Timestamp("2000-01-01")
u_end = pd.Timestamp("2026-01-01")
folds = _fold_start_dates(u_start, u_end, n_folds=3, max_l_bars=1260)
check("folds.count", len(folds) == 3, f"got {len(folds)}")
check("folds.ordered", folds == sorted(folds), f"{folds}")
check("folds.within_window", all(u_start <= f < u_end for f in folds))

# 2. Every fold must leave enough room for max_l_bars + the OOS window --
#    the whole point of this function is to prevent the silent-partial-
#    coverage bug class this project keeps finding elsewhere.
max_days_needed = int(1260 * _BARS_TO_CALENDAR_DAYS) + 1 + 365
check("folds.leave_room_for_largest_L",
      all((u_end - f).days >= max_days_needed for f in folds),
      f"max_days_needed={max_days_needed}")

# 2b. A single-fold request (n_folds=1) over a LONG window must anchor at
#    the LATEST usable start (recent, data-rich history), not the earliest
#    (real bug caught live 2026-09-12 running the actual pilot: it defaulted
#    to 1926, a near-empty era of the real WRDS universe, wasting the whole
#    pilot's compute on an uninformative result before this was fixed).
folds_single = _fold_start_dates(u_start, u_end, n_folds=1, max_l_bars=1260)
check("folds.single_fold_anchors_at_latest_not_earliest",
      folds_single != [u_start] and (u_end - folds_single[0]).days >= max_days_needed,
      f"got {folds_single}")

# 3. A too-short universe window collapses to a single fold at the start,
#    not an out-of-range or negative-spacing result.
short_end = u_start + pd.Timedelta(days=100)
folds_short = _fold_start_dates(u_start, short_end, n_folds=3, max_l_bars=1260)
check("folds.short_window_collapses_to_one", folds_short == [u_start], f"{folds_short}")

# --- _mechanical_lead_lag ---


class _FakePairResult:
    def __init__(self, a, b):
        self.symbol_a, self.symbol_b = a, b


def _synthetic_ohlc(close: np.ndarray, index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "open": close, "high": close, "low": close, "close": close,
        "gap_flag": 0,
    }, index=index)


rng = np.random.default_rng(0)
idx = pd.bdate_range("2010-01-01", periods=2500)
noise_a = rng.normal(0, 1, len(idx))
# B is A's return shifted forward by 3 bars (A leads B by 3) plus its own
# independent noise -- a clean, known lead-lag ground truth.
lag_true = 3
shifted = np.roll(noise_a, lag_true)
shifted[:lag_true] = 0
noise_b = 0.9 * shifted + 0.1 * rng.normal(0, 1, len(idx))
close_a = 100 * np.exp(np.cumsum(noise_a * 0.01))
close_b = 100 * np.exp(np.cumsum(noise_b * 0.01))

universe = {
    "LEADER": _synthetic_ohlc(close_a, idx),
    "FOLLOWER": _synthetic_ohlc(close_b, idx),
    "INDEPENDENT": _synthetic_ohlc(100 * np.exp(np.cumsum(rng.normal(0, 1, len(idx)) * 0.01)), idx),
}

lag_pair = _FakePairResult("LEADER", "FOLLOWER")
mech = _mechanical_lead_lag(lag_pair, universe, idx[0], idx[-1])
check("lead_lag.known_lag_pair_flagged_mechanical", mech is True, f"got {mech}")

indep_pair = _FakePairResult("LEADER", "INDEPENDENT")
mech_indep = _mechanical_lead_lag(indep_pair, universe, idx[0], idx[-1])
check("lead_lag.independent_pair_not_flagged", mech_indep is False, f"got {mech_indep}")

# Too little data -> None (unknown), not a crash and not a False.
short_idx = idx[:30]
short_universe = {k: v.loc[short_idx] for k, v in universe.items()}
mech_short = _mechanical_lead_lag(lag_pair, short_universe, short_idx[0], short_idx[-1])
check("lead_lag.insufficient_data_returns_none", mech_short is None, f"got {mech_short}")

# Missing symbol -> None, not a KeyError.
missing_pair = _FakePairResult("LEADER", "DOES_NOT_EXIST")
mech_missing = _mechanical_lead_lag(missing_pair, universe, idx[0], idx[-1])
check("lead_lag.missing_symbol_returns_none_not_crash", mech_missing is None, f"got {mech_missing}")

# --- summarize ---

df = pd.DataFrame([
    {"actual_n_overlap": 100, "mechanical_lead_lag": False, "held_up": True},
    {"actual_n_overlap": 110, "mechanical_lead_lag": False, "held_up": False},
    {"actual_n_overlap": 300, "mechanical_lead_lag": False, "held_up": True},
    {"actual_n_overlap": 310, "mechanical_lead_lag": False, "held_up": True},
    {"actual_n_overlap": 300, "mechanical_lead_lag": True, "held_up": True},
    {"actual_n_overlap": 300, "mechanical_lead_lag": None, "held_up": False},
])
summary = summarize(df)
check("summarize.produces_rows", len(summary) > 0, f"{len(summary)} rows")
check("summarize.has_false_confirmation_rate_col",
      "false_confirmation_rate" in summary.columns)
check("summarize.rates_in_unit_interval",
      summary["false_confirmation_rate"].between(0, 1).all())
check("summarize.total_pairs_conserved",
      summary["n_pairs"].sum() == len(df),
      f"got {summary['n_pairs'].sum()} want {len(df)}")
check("summarize.unknown_cohort_present",
      "unknown" in set(summary["lead_lag_cohort"]),
      f"cohorts={sorted(set(summary['lead_lag_cohort']))}")
# pyarrow can't serialize pandas' native Interval dtype (pd.cut's default
# output) -- crashed the real pilot after 32 min of real compute, 2026-09-12.
# overlap_bucket must come back as plain str so to_parquet doesn't repeat this.
check("summarize.overlap_bucket_is_parquet_safe_str",
      summary["overlap_bucket"].map(type).eq(str).all(),
      f"dtypes={summary['overlap_bucket'].map(type).unique()}")

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
sys.exit(0 if n_pass == len(checks) else 1)
