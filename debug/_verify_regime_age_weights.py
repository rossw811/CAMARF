"""Synthetic verification for backtest.py::compute_regime_age_weights -- Thread Q Idea 1 Path A."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from backtest import compute_regime_age_weights

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


def _trades(rows):
    return pd.DataFrame(rows, columns=["symbol_a", "symbol_b", "regime_age_days"])


# Case 1: fresh pair gets a LARGER multiplier than a long-running pair, under every decay_fn
fresh = [("AAA", "BBB", 10.0)] * 10
long_running = [("CCC", "DDD", 900.0)] * 10
for fn in ("step", "linear", "exponential"):
    w = compute_regime_age_weights(trades_df=_trades(fresh + long_running), decay_fn=fn, min_obs=5)
    check(f"decay_fn={fn}: fresh pair gets larger multiplier than long-running",
          w["AAA/BBB"] > w["CCC/DDD"])

# Case 2: unknown (NaN) regime age gets flat 1.0 multiplier, not silently treated as old
unknown = [("EEE", "FFF", np.nan)] * 10
w = compute_regime_age_weights(trades_df=_trades(unknown), decay_fn="step", min_obs=5)
check("unknown regime age gets flat 1.0 multiplier (not treated as old)",
      abs(w["EEE/FFF"] - 1.0) < 1e-9)

# Case 3: thin pairs (below min_obs) excluded, not silently weighted from too little data
thin = [("GGG", "HHH", 10.0)] * 3
w = compute_regime_age_weights(trades_df=_trades(thin), decay_fn="step", min_obs=5)
check("thin pair (below min_obs) excluded from weights", "GGG/HHH" not in w)

# Case 4: weights clipped to [0.1, 5.0] range
extreme = [("III", "JJJ", 0.0)] * 10
w = compute_regime_age_weights(trades_df=_trades(extreme), decay_fn="step", min_obs=5)
check("weights stay within [0.1, 5.0] clip range", all(0.1 <= v <= 5.0 for v in w.values()))

# Case 5: unknown decay_fn raises, doesn't silently fall through to a default
try:
    compute_regime_age_weights(trades_df=_trades(fresh), decay_fn="bogus", min_obs=5)
    check("unknown decay_fn raises ValueError", False)
except ValueError:
    check("unknown decay_fn raises ValueError", True)

n_fail = sum(1 for _, c in checks if not c)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed")
sys.exit(1 if n_fail else 0)
