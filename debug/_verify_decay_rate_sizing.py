"""Synthetic verification for backtest.py::compute_decay_rate_weights /
compose_regime_age_and_decay_rate_weights / _parse_decay_rate_spec --
Thread Q decay-rate path (scoped 2026-08-24)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import (
    compute_decay_rate_weights, compose_regime_age_and_decay_rate_weights,
    _parse_decay_rate_spec,
)

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


def _trades(rows, col="decay_rate_coint_fraction_sma"):
    return pd.DataFrame(rows, columns=["symbol_a", "symbol_b", col])

COL = "decay_rate_coint_fraction_sma"

# Case 1: a pair with clearly positive (strengthening) decay_rate gets a LARGER multiplier
# than a pair with clearly negative (weakening) decay_rate, under every decay_fn.
strengthening = [("AAA", "BBB", 5.0)] * 10
weakening = [("CCC", "DDD", -5.0)] * 10
for fn in ("step", "linear", "exponential"):
    w = compute_decay_rate_weights(trades_df=_trades(strengthening + weakening), decay_fn=fn, min_obs=5)
    check(f"decay_fn={fn}: strengthening pair gets larger multiplier than weakening pair",
          w["AAA/BBB"] > w["CCC/DDD"])

# Case 2: unknown (NaN) decay_rate gets flat 1.0 multiplier
unknown = [("EEE", "FFF", np.nan)] * 10
w = compute_decay_rate_weights(trades_df=_trades(strengthening + weakening + unknown), decay_fn="step", min_obs=5)
check("unknown decay_rate gets flat 1.0 multiplier (not treated as directional)",
      abs(w["EEE/FFF"] - 1.0) < 1e-9)

# Case 3: thin pairs (below min_obs) excluded
thin = [("GGG", "HHH", 3.0)] * 3
w = compute_decay_rate_weights(trades_df=_trades(strengthening + thin), decay_fn="step", min_obs=5)
check("thin pair (below min_obs) excluded from weights", "GGG/HHH" not in w)

# Case 4: weights stay within [0.1, 5.0]
extreme = [("III", "JJJ", 1000.0)] * 10
w = compute_decay_rate_weights(trades_df=_trades(strengthening + weakening + extreme), decay_fn="exponential", min_obs=5)
check("weights stay within [0.1, 5.0] clip range", all(0.1 <= v <= 5.0 for v in w.values()))

# Case 5: unknown decay_fn raises (needs real population variance to reach the decay_fn
# branch at all -- an all-identical population returns early via the zero-variance guard)
try:
    compute_decay_rate_weights(trades_df=_trades(strengthening + weakening), decay_fn="bogus", min_obs=5)
    check("unknown decay_fn raises ValueError", False)
except ValueError:
    check("unknown decay_fn raises ValueError", True)

# Case 6: missing column -> empty dict, not a crash
w = compute_decay_rate_weights(trades_df=_trades(strengthening, col="some_other_col"),
                                signal="half_life", smoothing="kalman", decay_fn="step", min_obs=5)
check("missing signal/smoothing column -> empty dict, not a crash", w == {})

# Case 7: no variance in population -> empty dict, not a divide-by-zero
flat_pop = [("KKK", "LLL", 2.0)] * 10
w = compute_decay_rate_weights(trades_df=_trades(flat_pop), decay_fn="step", min_obs=5)
check("zero-variance population -> empty dict (no divide-by-zero crash)", w == {})

# --- compose_regime_age_and_decay_rate_weights ---
age_w = {"AAA/BBB": 1.5, "CCC/DDD": 0.7}
rate_w = {"AAA/BBB": 1.2, "EEE/FFF": 0.8}
composed = compose_regime_age_and_decay_rate_weights(age_w, rate_w)
check("compose: pair in both dicts multiplies both multipliers",
      abs(composed["AAA/BBB"] - min(1.5 * 1.2, 5.0)) < 1e-9)
check("compose: pair only in age dict gets rate's neutral 1.0 (age unchanged)",
      abs(composed["CCC/DDD"] - 0.7) < 1e-9)
check("compose: pair only in rate dict gets age's neutral 1.0 (rate unchanged)",
      abs(composed["EEE/FFF"] - 0.8) < 1e-9)
check("compose: result clipped to [0.1, 5.0]",
      all(0.1 <= v <= 5.0 for v in composed.values()))

# --- _parse_decay_rate_spec ---
check("_parse_decay_rate_spec: valid spec parses correctly",
      _parse_decay_rate_spec("coint_fraction:sma:step") == ("coint_fraction", "sma", "step"))
for bad_spec in ("coint_fraction:sma", "bogus:sma:step", "coint_fraction:bogus:step",
                 "coint_fraction:sma:bogus"):
    try:
        _parse_decay_rate_spec(bad_spec)
        check(f"_parse_decay_rate_spec: rejects {bad_spec!r}", False)
    except ValueError:
        check(f"_parse_decay_rate_spec: rejects {bad_spec!r}", True)

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
