"""Re-run stats.py Section 6 (permutation test) against the CURRENT trades_layer1.parquet /
trades_layer1_holdout.parquet (post BUG-D58/D59/D62 fixes, 2026-07-12), to get a fresh,
traceable p-value replacing PAPER.md's untraceable Abstract figure and the stale 2026-07-05
figure cited elsewhere in the paper. Reuses stats.py's own run_permutation_test unmodified —
no reimplementation."""
import json
import os

from stats import _load_trades, run_permutation_test

_STATS_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "stats")
os.makedirs(_STATS_DIR, exist_ok=True)

trades_is = _load_trades("layer1")
trades_oos = _load_trades("layer1_holdout")
print(f"IS trades: {len(trades_is)}  OOS trades: {len(trades_oos)}")

perm_oos = run_permutation_test(trades_oos, "layer1_holdout")
perm_is = run_permutation_test(trades_is, "layer1")

print("\n=== OOS ===")
print(json.dumps(perm_oos, indent=2))
print("\n=== IS ===")
print(json.dumps(perm_is, indent=2))

with open(os.path.join(_STATS_DIR, "permutation_test_oos.json"), "w") as fh:
    json.dump(perm_oos, fh, indent=2)
with open(os.path.join(_STATS_DIR, "permutation_test_is.json"), "w") as fh:
    json.dump(perm_is, fh, indent=2)
print("\nWrote output/stats/permutation_test_oos.json and permutation_test_is.json")
