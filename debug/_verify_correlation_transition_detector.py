"""
debug/_verify_correlation_transition_detector.py -- synthetic checks for
research/correlation_transition_detector.py, run BEFORE trusting it against
real cointegration_regime_segments.parquet data.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.correlation_transition_detector import detect_transitions, tag_transition_regime

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name}")
        failed += 1


print("Check 1: detect_transitions -- a pair with 3 alternating spans produces exactly 2 "
      "transitions, correctly typed")
segments = pd.DataFrame([
    {"symbol_a": "A", "symbol_b": "B", "state": "coint",
     "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.Timestamp("2012-01-01"),
     "n_windows": 8, "strength": "strong"},
    {"symbol_a": "A", "symbol_b": "B", "state": "not_coint",
     "start_date": pd.Timestamp("2012-01-01"), "end_date": pd.Timestamp("2015-01-01"),
     "n_windows": 12, "strength": None},
    {"symbol_a": "A", "symbol_b": "B", "state": "coint",
     "start_date": pd.Timestamp("2015-01-01"), "end_date": pd.Timestamp("2018-01-01"),
     "n_windows": 10, "strength": "moderate"},
])
transitions = detect_transitions(segments)
check("exactly 2 transitions detected for A/B (3 spans -> 2 boundaries)", len(transitions) == 2)
check("first transition (coint->not_coint) correctly typed DECOUPLING",
      transitions.iloc[0]["transition_type"] == "decoupling")
check("first transition date is the SECOND span's start_date (2012-01-01), not the first "
      "span's end_date (same value here, but the principle -- new span's onset -- matters)",
      transitions.iloc[0]["transition_date"] == pd.Timestamp("2012-01-01"))
check("second transition (not_coint->coint) correctly typed RECOUPLING",
      transitions.iloc[1]["transition_type"] == "recoupling")
check("decoupling transition's old_strength carries the OLD (coint) span's strength ('strong')",
      transitions.iloc[0]["old_strength"] == "strong")
check("recoupling transition's new_strength carries the NEW (coint) span's strength ('moderate')",
      transitions.iloc[1]["new_strength"] == "moderate")

print("Check 2: detect_transitions -- a pair with only 1 span (never transitioned) produces "
      "ZERO transitions, not a fabricated one")
single_span = pd.DataFrame([
    {"symbol_a": "C", "symbol_b": "D", "state": "coint",
     "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.Timestamp("2020-01-01"),
     "n_windows": 20, "strength": "weak"},
])
check("a single-span pair produces no transitions", len(detect_transitions(single_span)) == 0)

print("Check 3: detect_transitions -- multiple independent pairs are handled separately, "
      "no cross-pair contamination")
multi_pair = pd.concat([segments, pd.DataFrame([
    {"symbol_a": "X", "symbol_b": "Y", "state": "not_coint",
     "start_date": pd.Timestamp("2011-01-01"), "end_date": pd.Timestamp("2013-01-01"),
     "n_windows": 5, "strength": None},
    {"symbol_a": "X", "symbol_b": "Y", "state": "coint",
     "start_date": pd.Timestamp("2013-01-01"), "end_date": pd.Timestamp("2016-01-01"),
     "n_windows": 9, "strength": "strong"},
])], ignore_index=True)
multi_transitions = detect_transitions(multi_pair)
check("A/B contributes 2 transitions, X/Y contributes 1 -- exactly 3 total, no cross-pair mixing",
      len(multi_transitions) == 3
      and (multi_transitions[["symbol_a", "symbol_b"]] == ["A", "B"]).all(axis=1).sum() == 2
      and (multi_transitions[["symbol_a", "symbol_b"]] == ["X", "Y"]).all(axis=1).sum() == 1)

print("Check 4: tag_transition_regime -- point-in-time-safe regime lookup, never a future value")
vix_regime = pd.Series(
    ["calm", "crisis", "normal"],
    index=pd.DatetimeIndex(["2011-01-01", "2012-06-01", "2014-01-01"]),
)
tagged = tag_transition_regime(transitions, vix_regime)
check("the 2012-01-01 decoupling transition gets 'calm' (most recent value ON OR BEFORE, "
      "the 2011-01-01 label, NOT the 2012-06-01 'crisis' label which is AFTER)",
      tagged[tagged["transition_date"] == pd.Timestamp("2012-01-01")].iloc[0]["regime"] == "calm")
check("the 2015-01-01 recoupling transition gets 'normal' (most recent value on or before)",
      tagged[tagged["transition_date"] == pd.Timestamp("2015-01-01")].iloc[0]["regime"] == "normal")

print("Check 5: tag_transition_regime -- empty input does not crash")
empty = pd.DataFrame(columns=["symbol_a", "symbol_b", "transition_date", "transition_type"])
empty_tagged = tag_transition_regime(empty, vix_regime)
check("empty transitions input produces an empty (not crashed) output", len(empty_tagged) == 0)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
