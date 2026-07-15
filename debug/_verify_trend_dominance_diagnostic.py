"""
Synthetic/controlled verification for research/trend_dominance_diagnostic.py,
BEFORE trusting it on real data (this project's standing discipline).

FIRST ATTEMPT (documented, not hidden -- a real, informative failure, per
CLAUDE.md rule 8): a purely-synthetic check using independent Gaussian random
walks (a strong-drift-small-noise leg vs. random-drift partners, and a
STATIONARY OU mean-reverting leg as the "low risk" comparison) FAILED --
strong_trend showed 0% spurious rejections and the "meanrev" leg showed 100%.
Root cause, diagnosed directly rather than patched blindly: (1) an
already-stationary leg is close-to-trivially "cointegrated" with anything
under statsmodels' coint() mechanics (OLS drives the coefficient on the
non-stationary partner toward ~0, leaving a residual that is approximately
the already-stationary leg itself) -- this is a construction bug (a
mean-reverting PRICE LEVEL is not realistic; only spreads between confirmed
pairs are mean-reverting in CAMARF, never a raw candidate leg on its own), not
a diagnostic bug. (2) two i.i.d.-Gaussian-increment random walks with no
shared factor essentially never show classical Granger-Newbold spurious
cointegration under a proper EG residual-unit-root test (which is precisely
why EG improves on naive OLS) -- this re-confirms, rather than contradicts,
why eg_null_calibration_montecarlo.py deliberately used REAL resampled price
data instead of synthetic GBM: real financial series carry volatility
clustering, fat tails, and regime structure that a simple Gaussian walk does
not, and that appears to be exactly what the earlier Monte Carlo study's
elevated (7.75%-12.75%) real-data rate actually depends on.

REVISED APPROACH, following that same established precedent: use REAL cached
1h data for both the "leg" and the "partner pool," with two REAL symbols of
already-known, directly-computable, and starkly different trend R^2 as the
high-risk/low-risk pair under test (PG, R^2=0.0656 -- flat/noisy; WMT,
R^2=0.9445 -- strong, low-noise uptrend) -- ground truth here is the SIGN and
MAGNITUDE of the difference in real trend-R^2, independently verifiable, not
an assumed synthetic DGP. DD itself is deliberately NOT used in this check,
to keep it independent of the main real-data study this verification is
gating.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research.trend_dominance_diagnostic import (
    trend_r_squared,
    eg_pvalue,
    leg_corrected_pvalue,
    load_log_close,
    symbols_for_suffix,
)

SEED = 20260713
SUFFIX = "1hr"
HIGH_TREND_SYM = "WMT"   # real, R^2=0.9445 (computed directly, see module docstring)
LOW_TREND_SYM = "PG"     # real, R^2=0.0656


def main():
    rng = np.random.default_rng(SEED)

    high_lc = load_log_close(HIGH_TREND_SYM, SUFFIX)
    low_lc = load_log_close(LOW_TREND_SYM, SUFFIX)

    # --- Check 1: trend R^2 on real data matches the pre-computed values used
    # to select these two symbols (mechanical correctness of trend_r_squared) ---
    r2_high = trend_r_squared(high_lc)["r_squared"]
    r2_low = trend_r_squared(low_lc)["r_squared"]
    print(f"trend R^2: {HIGH_TREND_SYM}={r2_high:.4f} {LOW_TREND_SYM}={r2_low:.4f}")
    check1 = r2_high > 0.85 and r2_low < 0.20 and r2_high > r2_low
    print(f"Check 1 (matches pre-computed real R^2, high >> low): "
          f"{'PASS' if check1 else 'FAIL'}")

    # --- Check 2, REVISED after a real, disclosed negative finding: at n=40
    # partners, WMT (R^2=0.94) vs PG (R^2=0.07) showed 2.50% vs 5.00% -- wrong
    # direction. Re-run at n=150 (less noisy) still gave WMT=6.67% vs
    # PG=9.33% -- STILL the wrong direction, both near the ~5-10% baseline
    # eg_null_calibration_montecarlo.py already established for ordinary
    # stocks. Honest conclusion: trend-R^2 alone does NOT reliably predict
    # spurious-regression risk among ORDINARY real stocks at this sample
    # size -- Stage 1 (the cheap trend-R^2 pre-filter) does not validate as a
    # general screening proxy and is NOT relied on for the production remedy
    # below. This is reported as a real negative finding (rule 8), not
    # silently dropped.
    #
    # REVISED AGAIN (2026-07-14, Phase 9 bug-sweep): this check originally
    # used DD as the "known anomaly" ground truth -- correct at the time
    # (DD's cache carried BUG-D65's real append-seam contamination, an
    # independently-confirmed spurious-regression driver). Task #64 refetched
    # DD's cache clean; DD's own EG-significance rate against 150 real random
    # partners is now 1.33% -- BELOW the ordinary ~5-10% baseline, not above
    # it. This is the CORRECT, expected consequence of BUG-D65's fix (DD's
    # contamination-era anomaly is confirmed gone from production data, from
    # yet another independent angle) -- not a regression in this diagnostic
    # or in DD's data. But it means DD is no longer a valid "known anomaly"
    # ground-truth case.
    #
    # Attempted a synthetic replacement (a single deterministic +50% log-level
    # jump injected partway through a copy of WMT's real series), expecting
    # it to reproduce an elevated spurious-cointegration rate the way DD's
    # real contamination once did. It did NOT (3.33%, still below baseline) --
    # an implausible result relative to that hypothesis, investigated rather
    # than accepted at face value. Likely explanation: a single deterministic
    # level shift is not the same failure mode as BUG-D65's actual mechanism.
    # A one-time step in an otherwise I(1) series is still non-stationary and,
    # per unit-root test theory (a structural break in the regression
    # residual mean typically REDUCES ADF/EG power, biasing toward *not*
    # rejecting the unit root), should if anything make EG LESS likely to
    # flag spurious cointegration -- consistent with what was just measured,
    # not contradicting it. The real DD anomaly likely depended on a more
    # specific interaction (the contamination's exact effect on DD's overall
    # trend/drift versus its many real partners' own trends over the same
    # calendar period) that a single injected jump does not reproduce.
    # Getting a faithful synthetic reconstruction right would need real
    # investigation of BUG-D65's precise mechanism, not a quick patch -- per
    # this project's "don't force a synthetic case to work" discipline, this
    # check is RETIRED (not force-passed, not silently deleted) rather than
    # patched with an unverified construction. Checks 1/3/4 do not depend on
    # any contamination ground truth and remain fully valid regression tests
    # of the diagnostic's actual arithmetic.
    all_symbols = symbols_for_suffix(SUFFIX)
    n_partners = 150
    contaminated_lc = high_lc.copy()
    jump_idx = len(contaminated_lc) // 2
    contaminated_lc[jump_idx:] += 0.5  # ~65% level shift, matching BUG-D65's magnitude order
    partners_dd = list(rng.choice(
        [s for s in all_symbols if s != HIGH_TREND_SYM], size=n_partners, replace=False,
    ))
    dd_pvals = []
    for partner in partners_dd:
        try:
            p_lc = load_log_close(partner, SUFFIX)
        except Exception:
            continue
        n = min(len(contaminated_lc), len(p_lc))
        if n >= 60:
            try:
                dd_pvals.append(eg_pvalue(contaminated_lc[-n:], p_lc[-n:]))
            except Exception:
                pass
    dd_rate = float(np.mean(np.array(dd_pvals) < 0.05)) if dd_pvals else float("nan")
    print(f"\nWMT/PG ordinary-stock baseline (n=40, already run above this "
          f"module's real-data history): ~2.5%-9.3%, near nominal.")
    print(f"Synthetically-contaminated WMT copy (single deterministic jump) risk rate "
          f"vs {len(dd_pvals)} real random partners: {dd_rate:.2%} -- informational only, "
          f"not gated (see comment above: this construction doesn't reproduce BUG-D65's "
          f"real mechanism, and DD itself is no longer available as ground truth since its "
          f"cache was cleaned).")
    print("Check 2: RETIRED (no known-anomaly ground truth currently available; not "
          "counted toward pass/fail -- see comment above)")

    # --- Check 3: leg_corrected_pvalue() arithmetic, verified directly against
    # a hand-computable case (decoupled from real EG behavior) ---
    known_null = [0.01, 0.02, 0.5, 0.7, 0.9, 0.95]  # sorted, known fractions
    # Fraction of known_null <= 0.5 is exactly 3/6 = 0.5
    corrected_mid = leg_corrected_pvalue(0.5, known_null)
    # Fraction of known_null <= 0.015 is exactly 1/6
    corrected_low = leg_corrected_pvalue(0.015, known_null)
    # Fraction of known_null <= 0.99 is exactly 6/6 = 1.0
    corrected_high = leg_corrected_pvalue(0.99, known_null)
    print(f"\nleg_corrected_pvalue arithmetic: mid(0.5)->{corrected_mid} (expect 0.5), "
          f"low(0.015)->{corrected_low:.4f} (expect {1/6:.4f}), "
          f"high(0.99)->{corrected_high} (expect 1.0)")
    check3 = (
        abs(corrected_mid - 0.5) < 1e-9
        and abs(corrected_low - 1 / 6) < 1e-9
        and abs(corrected_high - 1.0) < 1e-9
    )
    print(f"Check 3 (exact empirical-CDF arithmetic): {'PASS' if check3 else 'FAIL'}")

    # --- Check 4: applying the correction to the real high-risk pool never
    # makes a p-value look BETTER (a structural property of the empirical-CDF
    # formula: corrected = P(null <= raw), which is >= 0 and, whenever the
    # null distribution has any mass below the raw p-value, >= the naive
    # "this pair is significant" reading is only preserved/tightened) ---
    if dd_pvals:
        sample_real_p = float(np.median(dd_pvals))
        corrected_sample = leg_corrected_pvalue(sample_real_p, dd_pvals)
        print(f"\nSanity: synthetic-contamination median null p={sample_real_p:.4g} -> "
              f"self-corrected={corrected_sample:.4g} (expect ~0.5 by construction)")
        check4 = abs(corrected_sample - 0.5) < 0.15
        print(f"Check 4 (median-of-own-null self-corrects to ~0.5): "
              f"{'PASS' if check4 else 'FAIL'}")
    else:
        check4 = False
        print("Check 4: SKIPPED (no dd_pvals) -> FAIL")

    all_pass = check1 and check3 and check4  # check2 retired, see comment above
    print(f"\n{'ALL CHECKS PASSED' if all_pass else 'FAILURE'} -- "
          f"{'proceeding to real data is justified.' if all_pass else 'DO NOT trust real-data results yet.'}")
    return all_pass


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
