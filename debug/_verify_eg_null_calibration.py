"""
_verify_eg_null_calibration.py — synthetic ground-truth check for the EG null-calibration
Monte Carlo study (research/eg_null_calibration_montecarlo.py).

Confirms the test harness (a thin wrapper around analysis.py's actual production EG-test
call, coint(a, b, trend="c", maxlag=EG_MAX_LAG, autolag="aic")) recovers approximately the
nominal 5% empirical Type-I error rate on a textbook case: short, low-n, genuinely
independent simulated random walks, where the correct answer is unambiguous by construction.

Known caveat, stated up front rather than discovered as a surprise: Engle-Granger's
asymptotic critical values (MacKinnon response-surface) are known in the econometrics
literature to have real finite-sample size distortions, particularly at small n — so an
exact 5.00% recovery is not expected. This check uses a generous tolerance band (2%-10%)
rather than a tight one, and reports the exact observed rate either way.
"""
import numpy as np
from statsmodels.tsa.stattools import coint

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

N_REPLICATES = 500
N_OBS = 500  # short/low-n textbook case
ALPHA = 0.05
SEED = 20260713


def eg_pvalue(a: np.ndarray, b: np.ndarray) -> float:
    """Exact production call signature (analysis.py _pair_coint_worker, line ~1251)."""
    _t, p, _c = coint(a, b, trend="c", maxlag=Config.ANALYSIS.EG_MAX_LAG, autolag="aic")
    return float(p)


def run_textbook_null(n_replicates: int, n_obs: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    rejections = 0
    n_ok = 0
    for i in range(n_replicates):
        # Two genuinely independent random walks -- no shared innovations, no true
        # cointegrating relationship by construction.
        a = np.cumsum(rng.normal(0, 1, n_obs)) + 100.0
        b = np.cumsum(rng.normal(0, 1, n_obs)) + 100.0
        try:
            p = eg_pvalue(a, b)
            n_ok += 1
            if p < ALPHA:
                rejections += 1
        except Exception:
            continue
    rate = rejections / n_ok if n_ok else float("nan")
    return {"n_replicates": n_replicates, "n_ok": n_ok, "n_rejected": rejections, "rate": rate}


if __name__ == "__main__":
    result = run_textbook_null(N_REPLICATES, N_OBS, SEED)
    print(f"Textbook null check: n_obs={N_OBS}, n_replicates={result['n_replicates']}, "
          f"n_ok={result['n_ok']}, rejected={result['n_rejected']}, "
          f"empirical_rate={result['rate']:.4f} (nominal alpha={ALPHA})")

    lo, hi = 0.02, 0.10
    passed = lo <= result["rate"] <= hi
    print(f"Tolerance band: [{lo}, {hi}] -> {'PASS' if passed else 'FAIL'}")

    if not passed:
        raise SystemExit(
            f"FAIL: harness did not recover a plausible Type-I rate near nominal "
            f"{ALPHA} on the textbook independent-random-walk case (got {result['rate']:.4f}). "
            f"Do not trust the real-data null-calibration study until this is resolved."
        )
    print("PASS: harness recovers a plausible empirical Type-I rate on the textbook case. "
          "Proceeding to the real-data-derived null study is now justified.")
