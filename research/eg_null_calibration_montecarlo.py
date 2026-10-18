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

D11 / R6.4 + R6.3 (Ross 2026-10-12; fixed 2026-10-18): the pre-D11 study paired each series' last n bars BY POSITION
(row i was a different date for each leg whenever calendars differ: crypto 24/7 vs sessions, holidays, listing gaps),
sampled the ~1.5k yfinance cache instead of load_full_universe(), called one-direction coint() on raw arrays (no gap
masking, not production's both-directions max-p), and used a flat 60-bar floor. Now: load_full_universe (WRDS
priority, IBKR off), align_to_common_calendar (10-year lookback, as the screen), CointScanner._build_log_price_map
(DATA_GAP masked), analysis.eg_pvalue_pair, MIN_OVERLAP_BY_TF; each unordered pair drawn at most once. 15m has no
full-universe source and stays a labelled yfinance-cache side arm. Not excluded: same-company pairs (twins, share
classes) beyond load_full_universe's identical-series dedupe -- rare among random draws from ~44.7k; disclosed.
debug/_verify_eg_null_calibration_d11.py.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import binomtest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from config import Config
from analysis import CointScanner, eg_pvalue_pair, _eg_worker
from universe_loader import load_full_universe, align_to_common_calendar, _load_dir

OUT_PATH = os.path.join(_ROOT, "output", "research", "eg_null_calibration_montecarlo.parquet")
ALPHA = 0.05
SEED = 20260713
LOOKBACK_YEARS = 10   # same as full_universe_eg_confirmation.py's --lookback-years default (the screen it calibrates)

# D11 (R6.4): full-universe timeframes (load_full_universe: WRDS priority, IBKR off by default, architecture rule 2).
# 15m has no full-universe source (only IBKR, prior-result-dependent) -> labelled side arm on the yfinance 15min cache.
TIMEFRAMES = {"1h": "load_full_universe", "1D": "load_full_universe", "1M": "load_full_universe",
              "15m": "yfinance_cache_side_arm"}
_SIDE_ARM_SUFFIX = {"15m": "15min"}

N_PAIRS_TARGET = 400  # per timeframe


def pair_null_pvalue(aligned: dict, sym_a: str, sym_b: str, tf_label: str, lp_cache: dict) -> dict:
    """Production EG on one null pair: frames on one shared calendar (align_to_common_calendar), log closes with
    DATA_GAP masked (CointScanner._build_log_price_map), both directions, max p (eg_pvalue_pair), and production's
    MIN_OVERLAP_BY_TF floor. Row i is the same timestamp for both legs -- pairs are matched by date (D11)."""
    for s in (sym_a, sym_b):
        if s not in lp_cache:
            lp_cache[s] = CointScanner._build_log_price_map(aligned, [s]).get(s)
    la, lb = lp_cache[sym_a], lp_cache[sym_b]
    if la is None or lb is None:
        return {"status": "error", "pvalue": None, "n_overlap": 0}
    p, n = eg_pvalue_pair(la, lb, Config.ANALYSIS.EG_MAX_LAG, tf_label)
    # _eg_worker has its own fixed 60-bar floor, above 1M's MIN_OVERLAP_BY_TF (24): those are short, not errors
    if n < max(Config.STATS.MIN_OVERLAP_BY_TF.get(tf_label, 252), 60):
        return {"status": "short_overlap", "pvalue": p, "n_overlap": n}
    if p is None:
        return {"status": "error", "pvalue": None, "n_overlap": n}
    # Comparison arm (not the calibrated quantity): forward direction alone, as the pre-D11 one-direction call did,
    # to separate the effect of production's max-of-both-directions rule from the alignment/universe changes.
    fwd = _eg_worker(("A", "B", la, lb, Config.ANALYSIS.EG_MAX_LAG, tf_label))
    return {"status": "tested", "pvalue": float(p), "n_overlap": n, "pvalue_forward": float(fwd["pvalue"])}


def run_timeframe(tf_label: str, aligned: dict, n_pairs_target: int, rng: np.random.Generator,
                  source: str = "load_full_universe") -> dict:
    syms = sorted(aligned)
    n_ok = n_rejected = n_rej_fwd = n_skipped_short = n_errors = n_dup = attempts = 0
    max_attempts = n_pairs_target * 20  # slack: thin/young listings often miss the overlap floor
    seen, lp_cache, overlaps = set(), {}, []
    while n_ok < n_pairs_target and attempts < max_attempts and len(syms) >= 2:
        sym_a, sym_b = rng.choice(syms, size=2, replace=False)
        key = frozenset((sym_a, sym_b))
        if key in seen:
            n_dup += 1
            if n_dup > 50 * max_attempts:
                break
            continue
        seen.add(key)
        attempts += 1
        r = pair_null_pvalue(aligned, sym_a, sym_b, tf_label, lp_cache)
        if r["status"] == "short_overlap":
            n_skipped_short += 1
        elif r["status"] == "error":
            n_errors += 1
        else:
            n_ok += 1
            n_rejected += r["pvalue"] < ALPHA
            n_rej_fwd += r["pvalue_forward"] < ALPHA
            overlaps.append(r["n_overlap"])

    rate = n_rejected / n_ok if n_ok else float("nan")
    if n_ok:
        ci = binomtest(int(n_rejected), n_ok, ALPHA, alternative="two-sided").proportion_ci(
            confidence_level=0.95, method="exact")
        ci_lo, ci_hi = float(ci.low), float(ci.high)
    else:
        ci_lo, ci_hi = float("nan"), float("nan")
    return {
        "timeframe": tf_label,
        "source": source,
        "n_symbols_available": len(syms),
        "n_null_pairs_tested": n_ok,
        "n_rejected_p_lt_05": int(n_rejected),
        "empirical_rate": rate,
        "ci95_lo": ci_lo,
        "ci95_hi": ci_hi,
        "nominal_alpha": ALPHA,
        "rate_forward_direction_only": n_rej_fwd / n_ok if n_ok else float("nan"),
        "below_nominal": bool(n_ok and ci_hi < ALPHA),
        "above_nominal": bool(n_ok and ci_lo > ALPHA),
        "min_overlap": Config.STATS.MIN_OVERLAP_BY_TF.get(tf_label, 252),
        "median_overlap": float(np.median(overlaps)) if overlaps else float("nan"),
        "n_skipped_short_overlap": n_skipped_short,
        "n_errors": n_errors,
        "n_duplicate_draws_skipped": n_dup,
        "attempts": attempts,
    }


def load_aligned(tf_label: str) -> dict:
    if TIMEFRAMES[tf_label] == "load_full_universe":
        frames = load_full_universe(tf_label, columns=["close"])
    else:
        frames = _load_dir(Config.DATA.CACHE_DIR, _SIDE_ARM_SUFFIX[tf_label], columns=["close"])
    return align_to_common_calendar(frames, lookback_years=LOOKBACK_YEARS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="EG null calibration on calendar-aligned random full-universe pairs")
    ap.add_argument("--tf", nargs="+", default=list(TIMEFRAMES), choices=list(TIMEFRAMES),
                    help="1D loads ~44.7k daily series -- RAM-heavy, run it on CachyOS")
    ap.add_argument("--n-pairs", type=int, default=N_PAIRS_TARGET)
    args = ap.parse_args(argv)
    rng = np.random.default_rng(SEED)
    rows = []
    for tf_label in args.tf:
        print(f"[{tf_label}] loading ({TIMEFRAMES[tf_label]}) and aligning to one calendar...")
        aligned = load_aligned(tf_label)
        r = run_timeframe(tf_label, aligned, args.n_pairs, rng, source=TIMEFRAMES[tf_label])
        print(f"[{tf_label}] n_tested={r['n_null_pairs_tested']} rejected={r['n_rejected_p_lt_05']} "
              f"rate={r['empirical_rate']:.4%} 95% CI=[{r['ci95_lo']:.4%}, {r['ci95_hi']:.4%}] vs nominal "
              f"{ALPHA:.0%}; forward direction alone {r['rate_forward_direction_only']:.2%} (median overlap {r['median_overlap']:.0f}, {r['n_skipped_short_overlap']} short-overlap "
              f"draws skipped)")
        rows.append(r)
        del aligned
    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"\nSaved: {OUT_PATH}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
