"""
CAMARF eg_null_calibration_montecarlo.py — exploratory diagnostic, NOT part of the
production pipeline.

Direct test of PAPER.md Section 4.2's "Strictness Paradox" Claim A: that the
Engle-Granger cointegration test used by analysis.py's CointScanner is statistically
over-conservative (empirical Type-I error well below its nominal 5% level) at long
horizons (1D, 1M), evidenced so far only by a heuristic ("raw significance rate observed
in production data is far below 5%") that assumes the candidate universe is close to
"all null" -- an assumption never independently checked.

Method: construct pairs that are NULL BY CONSTRUCTION -- real cached price series for
real symbols, randomly re-paired so any true bilateral economic relationship is
destroyed, while each individual series keeps its own real marginal statistics
(volatility clustering, fat tails, actual historical drift). This is a harder, more
realistic null than a synthetic GBM/independent-random-walk null (see
debug/_verify_eg_null_calibration.py for that easier textbook check, which this script's
harness passed before this real-data study was trusted).

Reuses the EXACT production EG-test call (statsmodels coint(a, b, trend="c",
maxlag=Config.ANALYSIS.EG_MAX_LAG, autolag="aic")) from analysis.py's
_pair_coint_worker -- not a reimplementation, so this is an apples-to-apples test of
what analysis.py's own screen actually does.

For each timeframe (15min, 1hr, 1day, 1mo -- matching PAPER.md Section 4.2's existing
raw-rate table), many random null pairs are drawn from real cached data, the EG test is
run on each at its own real overlap length, and the empirical rejection rate (fraction
with p<0.05) is compared against nominal 5% with a Clopper-Pearson 95% confidence
interval. If the interval excludes 5% (below it) at 1D/1M, that is real, quantified,
reproducible evidence the test is over-conservative at those horizons -- Claim A,
properly validated rather than asserted from a heuristic. If not, Claim A does not hold
as previously framed, and the production-data observation is better explained by the
real candidate universe not being close to "all null" already.

Output: output/research/eg_null_calibration_montecarlo.parquet
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from statsmodels.tsa.stattools import coint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

CACHE_DIR = "output/cache"
OUT_PATH = "output/research/eg_null_calibration_montecarlo.parquet"
ALPHA = 0.05
MIN_OVERLAP = 60  # matches analysis.py's own minimum (BUG-safe: same threshold, not an ad-hoc one)
SEED = 20260713

TIMEFRAMES = {
    "15m": "15min",
    "1h": "1hr",
    "1D": "1day",
    "1M": "1mo",
}

N_PAIRS_TARGET = 400  # per timeframe


def eg_pvalue(a: np.ndarray, b: np.ndarray) -> float:
    """Exact production call (analysis.py _pair_coint_worker, line ~1251)."""
    _t, p, _c = coint(a, b, trend="c", maxlag=Config.ANALYSIS.EG_MAX_LAG, autolag="aic")
    return float(p)


def symbols_for_suffix(suffix: str) -> list:
    paths = glob.glob(os.path.join(CACHE_DIR, f"*_{suffix}.parquet"))
    syms = []
    for p in paths:
        base = os.path.basename(p)
        sym = base[: -(len(suffix) + 1 + len(".parquet"))]
        syms.append(sym)
    return syms


def load_log_close(symbol: str, suffix: str) -> np.ndarray:
    df = pd.read_parquet(os.path.join(CACHE_DIR, f"{symbol}_{suffix}.parquet"))
    close = df["close"].astype(float).values
    close = close[np.isfinite(close) & (close > 0)]
    return np.log(close)


def run_timeframe(tf_label: str, suffix: str, n_pairs_target: int, rng: np.random.Generator) -> dict:
    syms = symbols_for_suffix(suffix)
    n_ok = 0
    n_rejected = 0
    n_skipped_short = 0
    n_errors = 0
    attempts = 0
    max_attempts = n_pairs_target * 4  # allow slack for skipped/errored draws

    # Pre-cache log-close arrays for symbols as they're drawn, to avoid re-reading
    cache: dict = {}

    while n_ok < n_pairs_target and attempts < max_attempts and len(syms) >= 2:
        attempts += 1
        sym_a, sym_b = rng.choice(syms, size=2, replace=False)
        if sym_a not in cache:
            try:
                cache[sym_a] = load_log_close(sym_a, suffix)
            except Exception:
                cache[sym_a] = None
        if sym_b not in cache:
            try:
                cache[sym_b] = load_log_close(sym_b, suffix)
            except Exception:
                cache[sym_b] = None
        a_full, b_full = cache[sym_a], cache[sym_b]
        if a_full is None or b_full is None:
            n_errors += 1
            continue
        # Randomly-paired series are NOT index-aligned by any real calendar
        # relationship (that's the point -- destroy the true pairing entirely,
        # not just misalign timestamps). Use the shorter series' length, take
        # the last min(len) observations from each (most recent, most liquid
        # regime for both), matching production's own "recent tail" bias.
        n = min(len(a_full), len(b_full))
        if n < MIN_OVERLAP:
            n_skipped_short += 1
            continue
        a = a_full[-n:]
        b = b_full[-n:]
        try:
            p = eg_pvalue(a, b)
        except Exception:
            n_errors += 1
            continue
        n_ok += 1
        if p < ALPHA:
            n_rejected += 1

    rate = n_rejected / n_ok if n_ok else float("nan")
    if n_ok:
        ci = binomtest(n_rejected, n_ok, ALPHA, alternative="two-sided").proportion_ci(
            confidence_level=0.95, method="exact"
        )
        ci_lo, ci_hi = float(ci.low), float(ci.high)
    else:
        ci_lo, ci_hi = float("nan"), float("nan")

    return {
        "timeframe": tf_label,
        "n_symbols_available": len(syms),
        "n_null_pairs_tested": n_ok,
        "n_rejected_p_lt_05": n_rejected,
        "empirical_rate": rate,
        "ci95_lo": ci_lo,
        "ci95_hi": ci_hi,
        "nominal_alpha": ALPHA,
        "below_nominal": bool(n_ok and ci_hi < ALPHA),
        "n_skipped_short_overlap": n_skipped_short,
        "n_errors": n_errors,
        "attempts": attempts,
    }


def main():
    rng = np.random.default_rng(SEED)
    rows = []
    for tf_label, suffix in TIMEFRAMES.items():
        print(f"[{tf_label}] running null-calibration study ({suffix})...")
        r = run_timeframe(tf_label, suffix, N_PAIRS_TARGET, rng)
        print(
            f"[{tf_label}] n_tested={r['n_null_pairs_tested']} rejected={r['n_rejected_p_lt_05']} "
            f"rate={r['empirical_rate']:.4%} 95% CI=[{r['ci95_lo']:.4%}, {r['ci95_hi']:.4%}] "
            f"vs nominal {ALPHA:.0%} -> {'BELOW NOMINAL' if r['below_nominal'] else 'not distinguishable from / above nominal'}"
        )
        rows.append(r)

    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"\nSaved: {OUT_PATH}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
