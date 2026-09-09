"""
debug/_verify_coint_decay_rate_signal_test.py -- synthetic ground-truth checks for
research/coint_decay_rate_signal_test.py, BEFORE trusting it against the real 5M-row
coint_strength_series.parquet.

Run: python debug/_verify_coint_decay_rate_signal_test.py
(Fully synthetic/offline -- no real data needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.coint_decay_rate_signal_test as sig

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


print("Check 1: add_next_window_persists -- correct per-pair shift(-1), last window per pair "
      "gets NaN (no next observation), not treated as a negative outcome")
df1 = pd.DataFrame({
    "symbol_a": ["A", "A", "A", "B", "B"],
    "symbol_b": ["X", "X", "X", "Y", "Y"],
    "window_start": [0, 1, 2, 0, 1],
    "pvalue": [0.01, 0.02, 0.90, 0.03, 0.80],  # A: coint, coint, NOT coint. B: coint, NOT coint.
})
r1 = sig.add_next_window_persists(df1)
check("A's window 0 (next=window1, pvalue 0.02<0.05) persists_next=True",
      r1.loc[(r1.symbol_a == "A") & (r1.window_start == 0), "persists_next"].iloc[0] == True)
check("A's window 1 (next=window2, pvalue 0.90>=0.05) persists_next=False",
      r1.loc[(r1.symbol_a == "A") & (r1.window_start == 1), "persists_next"].iloc[0] == False)
check("A's window 2 (LAST window, no next) persists_next is NaN, not False",
      pd.isna(r1.loc[(r1.symbol_a == "A") & (r1.window_start == 2), "persists_next"].iloc[0]))
check("B's window 1 (LAST window for B) persists_next is NaN",
      pd.isna(r1.loc[(r1.symbol_a == "B") & (r1.window_start == 1), "persists_next"].iloc[0]))
check("cross-pair isolation: A's last window's NaN doesn't leak into B's rows",
      r1.loc[(r1.symbol_a == "B") & (r1.window_start == 0), "persists_next"].iloc[0] == False)

print("Check 2: add_rolling_z -- matches a manual per-pair rolling z-score computation")
rng = np.random.default_rng(0)
n = 30
df2 = pd.DataFrame({
    "symbol_a": ["A"] * n, "symbol_b": ["X"] * n,
    "window_start": range(n), "coint_strength": rng.normal(0.5, 0.1, n),
})
z_computed = sig.add_rolling_z(df2, z_window=10)
manual_mean = df2["coint_strength"].rolling(10, min_periods=5).mean()
manual_std = df2["coint_strength"].rolling(10, min_periods=5).std(ddof=1)
manual_z = (df2["coint_strength"] - manual_mean) / manual_std
check("rolling z-score matches a direct pandas .rolling() computation on the same series "
      "(within floating-point tolerance)",
      np.allclose(z_computed.values, manual_z.values, equal_nan=True))

print("Check 3: add_rolling_z -- causal (warm-up bars before min_periods are NaN, not a "
      "fabricated early z-score)")
check("first 4 bars (below min_periods=5 at z_window=10) are NaN", z_computed.iloc[:4].isna().all())
check("bar 5 onward (min_periods reached) has a real value", z_computed.iloc[4:].notna().all())

print("Check 4: evaluate_z_signal -- detects a KNOWN, deliberately injected signal (high "
      "coint_strength_z predicts elevated next-window persistence at a known rate)")
n_pairs = 200
rows = []
rng2 = np.random.default_rng(1)
for i in range(n_pairs):
    # Build each pair as a short, 12-window series. Half the pairs get a strong z-score signal
    # (coint_strength trending sharply UP at window 8, engineered so z_window=5 clearly detects
    # it) paired with a HIGH probability (0.9) of persisting; the other half get a flat series
    # (no real signal) paired with a LOW baseline persistence probability (0.3) -- injected
    # directly via the actual outcome (pvalue), not just the predictor, so the z-test has a real
    # ground-truth effect to recover.
    strong_signal = i % 2 == 0
    base = rng2.normal(0.5, 0.02, 12)
    if strong_signal:
        base[8] = 0.9  # sharp jump -> high rolling z-score at window 8
        persist_prob_at_8 = 0.9
    else:
        persist_prob_at_8 = 0.3
    pvals = rng2.uniform(0.5, 0.9, 12)  # mostly "not coint" filler elsewhere, irrelevant to the test
    pvals[9] = 0.01 if rng2.random() < persist_prob_at_8 else 0.90  # window 8's NEXT window (9)
    for w in range(12):
        rows.append({"symbol_a": f"P{i}", "symbol_b": "Q", "window_start": w,
                      "coint_strength": base[w], "pvalue": pvals[w],
                      "coint_decay_rate": np.nan})
df4 = pd.DataFrame(rows)
df4 = sig.add_next_window_persists(df4)
result4 = sig.evaluate_z_signal(df4, z_window=5, z_threshold=1.5)
check(f"the injected high-z signal group shows a materially higher persist rate "
      f"({result4['signal_persist_rate']:.2f}) than the baseline ({result4['baseline_persist_rate']:.2f})",
      result4["signal_persist_rate"] > result4["baseline_persist_rate"] + 0.15)
check(f"the z-test correctly flags this as statistically significant (p={result4['p_value']})",
      result4["p_value"] is not None and result4["p_value"] < 0.05)

print("Check 5: evaluate_z_signal -- a genuinely NULL predictor (random coint_strength, no "
      "relationship to the outcome) does NOT get flagged as a false positive at a normal alpha")
rng3 = np.random.default_rng(2)
rows5 = []
for i in range(150):
    strength = rng3.normal(0.5, 0.1, 12)
    pvals = rng3.choice([0.01, 0.90], size=12, p=[0.5, 0.5])  # persistence independent of strength
    for w in range(12):
        rows5.append({"symbol_a": f"N{i}", "symbol_b": "M", "window_start": w,
                       "coint_strength": strength[w], "pvalue": pvals[w]})
df5 = pd.DataFrame(rows5)
df5 = sig.add_next_window_persists(df5)
result5 = sig.evaluate_z_signal(df5, z_window=5, z_threshold=1.5)
check(f"a null predictor is NOT flagged as significant at p<0.05 "
      f"(p={result5['p_value']}) -- no false-positive inflation",
      result5["p_value"] is None or result5["p_value"] >= 0.05)

print("Check 6: evaluate_decay_signal -- detects a KNOWN injected decay-rate/persistence "
      "relationship the same way evaluate_z_signal does")
rows6 = []
for i in range(200):
    weakening = i % 2 == 0
    decay = -0.05 if weakening else 0.05
    persist_prob = 0.85 if weakening else 0.30
    persists = rng2.random() < persist_prob
    rows6.append({"symbol_a": f"D{i}", "symbol_b": "E", "coint_decay_rate": decay,
                  "persists_next": persists})
df6 = pd.DataFrame(rows6)
result6 = sig.evaluate_decay_signal(df6)
check(f"weakening-trend group shows a materially different persist rate "
      f"({result6['signal_persist_rate']:.2f} vs baseline {result6['baseline_persist_rate']:.2f})",
      abs(result6["signal_persist_rate"] - result6["baseline_persist_rate"]) > 0.15)
check(f"correctly flagged significant (p={result6['p_value']})",
      result6["p_value"] is not None and result6["p_value"] < 0.05)

print(f"\n{passed}/{passed + failed} checks passed")
sys.exit(0 if failed == 0 else 1)
