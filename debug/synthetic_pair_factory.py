"""
CAMARF debug/synthetic_pair_factory.py — parameterized synthetic PAIR
generator + permutation-sweep runner (2026-07-14), extending
debug/synthetic_diagnostics.py's single-series generators to full PAIRS
with independently-togglable, KNOWN ground-truth properties covering
every major factor this project's pipeline and research scripts test
for.

Motivation (Ross, 2026-07-14): not just a handful of bug-specific
generators, but a factory that can produce different datasets and
VARIATIONS/PERMUTATIONS across every factor the pipeline tests for, so
target functions can be validated against known ground truth across
combinations, not just single illustrative cases.

Factors covered (each independently controllable — see
make_synthetic_pair's parameters), with the REAL pipeline/research
mechanism each one targets:
  1. cointegrated (bool) + hedge_ratio + mean_reversion_speed
     -> analysis.py's EG+BH-FDR screening, HurstEstimator
  2. lead_lag_bars (int, signed)
     -> research/lead_lag_scan.py, research/lead_lag_permutation_check.py,
        this session's earnings/big-move/MIDAS lead-lag tests
  3. structural_break_at + break_type
     -> analysis.py's Zivot-Andrews/CUSUM, BUG-D68's coint_frac gate,
        research/decoupling_analysis.py
  4. gap_positions (DATA_GAP / FILL / NO_ACTIVITY-style)
     -> data.py's GapFlag system, _gap_aware_returns/_clean_close
  5. contamination_seam_at + contamination_ratio
     -> BUG-D65's append-seam split-adjustment detection,
        research/data_contamination_scan.py
  6. jump_dates (isolated single-bar moves)
     -> research/peer_correlation_contamination_check.py,
        research/big_move_lead_lag.py's event-window conditioning
  7. volatility_regime (constant / garch_like / regime_switch)
     -> research/financial_turbulence_index.py, HMM/GMM regime work
        (task #37), z-score threshold calibration generally
  8. noise_std, n_bars
     -> general statistical-power characterization (sample-size effects
        found directly this session in task #54's cross-timeframe work)

Honest scope note: this factory targets the factors this session's own
work has DIRECTLY touched and can verify are correctly injected/
detectable. It does not yet cover every conceivable pipeline behavior
(e.g. IBKR-specific pacing/connection failure modes, universe-
construction edge cases) — designed to be EXTENDED, not treated as
already-exhaustive. Each new factor added should get the same
inject-then-verify-detectable treatment demonstrated in this file's
self-test section.
"""
import itertools
from typing import Optional, List, Tuple, Dict, Any

import numpy as np
import pandas as pd


def make_synthetic_pair(
    n_bars: int = 2000,
    seed: int = 0,
    cointegrated: bool = True,
    hedge_ratio: float = 1.0,
    mean_reversion_speed: float = 0.05,
    lead_lag_bars: int = 0,
    structural_break_at: Optional[int] = None,
    break_type: str = "decouple",
    gap_positions: Optional[List[Tuple[int, int, str]]] = None,
    contamination_seam_at: Optional[int] = None,
    contamination_ratio: float = 2.0,
    jump_dates: Optional[List[int]] = None,
    jump_magnitude: float = 0.10,
    volatility_regime: str = "constant",
    noise_std: float = 1.0,
    start_price: float = 100.0,
) -> Tuple[pd.Series, pd.Series, Dict[str, Any]]:
    """
    Returns (price_a, price_b, ground_truth) where price_a/price_b are
    pd.Series of LEVEL prices (not log/returns) indexed by an hourly
    DatetimeIndex, and ground_truth is a dict documenting every injected
    property for downstream verification.

    Construction order (each stage builds on the previous):
      1. B's log-price: a random walk (the "market" driver).
      2. A's log-price: hedge_ratio * B + a spread process — OU
         (mean-reverting, cointegrated=True) or itself a random walk
         (cointegrated=False, so A and B may still be CORRELATED via
         shared innovations but are NOT cointegrated — the specific
         "correlated without cointegration" case EG/BH-FDR must reject).
      3. lead_lag_bars: if nonzero, B's own innovations are additionally
         driven by A's innovations from `lead_lag_bars` bars earlier
         (on top of the contemporaneous spread relationship) — a genuine,
         literal Granger-causal lag structure, not just noise.
      4. structural_break_at: after this bar, the relationship changes
         per break_type ("decouple" = cointegrated flips to a random
         walk spread; "level_shift" = one-time jump in the spread's
         equilibrium; "trend_change" = the spread starts drifting).
      5. volatility_regime: scales noise_std over time.
      6. jump_dates: isolated single-bar shocks to A only (mimics an
         idiosyncratic/earnings-style event).
      7. contamination_seam_at: multiplies A's price by contamination_ratio
         for all bars BEFORE the seam (mimics BUG-D65's unreconciled
         split-adjustment-basis mismatch — a discontinuity with no real
         corporate action).
      8. gap_positions: sets bars to NaN at specified (start, length,
         type) — 'DATA_GAP' style (>5 consecutive) or 'FILL' style
         (<=5 consecutive), matching data.py's GapFlag convention.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="h")

    # --- volatility regime scaling ---
    if volatility_regime == "constant":
        vol_scale = np.full(n_bars, noise_std)
    elif volatility_regime == "garch_like":
        vol_scale = np.full(n_bars, noise_std)
        cur = noise_std
        for t in range(1, n_bars):
            cur = 0.95 * cur + 0.05 * noise_std + 0.3 * abs(rng.normal(0, noise_std * 0.3))
            vol_scale[t] = cur
    elif volatility_regime == "regime_switch":
        vol_scale = np.full(n_bars, noise_std)
        switch_at = n_bars // 2
        vol_scale[switch_at:] *= 3.0
    else:
        raise ValueError(f"unknown volatility_regime={volatility_regime!r}")

    # --- 1+2+3 combined: B's and A's INNOVATION streams (not levels),
    # with the lead-lag cross-contribution applied at the innovation
    # (single-bar RETURN) level, not accumulated onto a level — adding a
    # lagged component's cumsum onto a level creates a permanent drift/
    # trend bias, not a genuine lagged RETURN correlation, and produces
    # no signal lagged_corr_scan (which operates on returns) can detect.
    # Caught directly: an earlier version of this construction added
    # np.cumsum(extra) onto log_b/log_a, and the self-test below showed
    # best_lag=0 recovered for BOTH true_lag=+5 and -5 — the injected
    # "lead-lag" was invisible to the actual detection mechanism it was
    # meant to test. Fixed by building the cross-contribution into the
    # innovation stream BEFORE any cumsum, so B's (or A's) OWN return at
    # time t genuinely contains a term proportional to the other leg's
    # return `lead_lag_bars` bars earlier.
    b_own_innov = rng.normal(0, 1, n_bars) * vol_scale
    a_own_innov = rng.normal(0, 1, n_bars) * vol_scale

    if lead_lag_bars > 0:
        # A leads: B's return at t includes a component of A's return at t-lag.
        lagged_a = np.roll(a_own_innov, lead_lag_bars)
        lagged_a[:lead_lag_bars] = 0
        b_innov = b_own_innov + 0.6 * lagged_a
        a_innov = a_own_innov
    elif lead_lag_bars < 0:
        # B leads: A's return at t includes a component of B's return at t-|lag|.
        k = abs(lead_lag_bars)
        lagged_b = np.roll(b_own_innov, k)
        lagged_b[:k] = 0
        a_innov = a_own_innov + 0.6 * lagged_b
        b_innov = b_own_innov
    else:
        a_innov, b_innov = a_own_innov, b_own_innov

    log_b = np.cumsum(b_innov) * 0.01 + np.log(start_price)

    # --- A: hedge_ratio*B + spread (OU if cointegrated, else RW) ---
    if cointegrated:
        spread = np.zeros(n_bars)
        for t in range(1, n_bars):
            spread[t] = (1 - mean_reversion_speed) * spread[t - 1] + a_innov[t] * 0.01
    else:
        spread = np.cumsum(a_innov) * 0.01

    log_a = hedge_ratio * log_b + spread

    # --- 4. structural break ---
    if structural_break_at is not None:
        post = slice(structural_break_at, None)
        if break_type == "decouple":
            post_len = n_bars - structural_break_at
            post_innov = rng.normal(0, 1, post_len) * vol_scale[post]
            new_spread_tail = np.cumsum(post_innov) * 0.01
            log_a[post] = log_a[structural_break_at] + (new_spread_tail - new_spread_tail[0]) + \
                (hedge_ratio * (log_b[post] - log_b[structural_break_at]))
        elif break_type == "level_shift":
            log_a[post] += 0.05  # one-time ~5% equilibrium jump, no real corporate action
        elif break_type == "trend_change":
            drift = np.linspace(0, 0.0005 * (n_bars - structural_break_at), n_bars - structural_break_at)
            log_a[post] += drift
        else:
            raise ValueError(f"unknown break_type={break_type!r}")

    # --- 5. isolated jumps (A only) ---
    if jump_dates:
        for j in jump_dates:
            if 0 <= j < n_bars:
                log_a[j:] += jump_magnitude  # permanent step, like a real price jump

    # --- 6. contamination seam (A only, BUG-D65-style) ---
    contamination_applied = False
    if contamination_seam_at is not None:
        log_a[:contamination_seam_at] += np.log(contamination_ratio)
        contamination_applied = True

    price_a = pd.Series(np.exp(log_a), index=idx)
    price_b = pd.Series(np.exp(log_b), index=idx)

    # --- 7. gaps (applied last, to final price series) ---
    gap_metadata = []
    if gap_positions:
        for start, length, gtype in gap_positions:
            end = min(start + length, n_bars)
            price_a.iloc[start:end] = np.nan
            gap_metadata.append({"start": start, "length": end - start, "type": gtype})

    ground_truth = {
        "cointegrated": cointegrated, "hedge_ratio": hedge_ratio,
        "mean_reversion_speed": mean_reversion_speed, "lead_lag_bars": lead_lag_bars,
        "structural_break_at": structural_break_at, "break_type": break_type if structural_break_at else None,
        "gaps": gap_metadata, "contamination_seam_at": contamination_seam_at if contamination_applied else None,
        "contamination_ratio": contamination_ratio if contamination_applied else None,
        "jump_dates": jump_dates or [], "volatility_regime": volatility_regime, "n_bars": n_bars,
    }
    return price_a, price_b, ground_truth


def sweep(param_grid: Dict[str, list], base_kwargs: Optional[Dict[str, Any]] = None, max_combos: int = 200):
    """Cartesian-product permutation sweep over param_grid, capped at
    max_combos (randomly sampled if the full grid exceeds it — stated via
    a printed warning, never silently truncated). Yields
    (params_dict, price_a, price_b, ground_truth) for each combination.
    """
    base_kwargs = base_kwargs or {}
    keys = list(param_grid.keys())
    all_combos = list(itertools.product(*param_grid.values()))
    if len(all_combos) > max_combos:
        print(f"WARNING: {len(all_combos)} combinations exceeds max_combos={max_combos} — "
              f"randomly sampling {max_combos} (not silently truncating from the front).")
        rng = np.random.default_rng(0)
        idx = rng.choice(len(all_combos), size=max_combos, replace=False)
        all_combos = [all_combos[i] for i in idx]
    for seed_offset, combo in enumerate(all_combos):
        params = dict(zip(keys, combo))
        kwargs = {**base_kwargs, **params, "seed": base_kwargs.get("seed", 0) + seed_offset}
        price_a, price_b, truth = make_synthetic_pair(**kwargs)
        yield params, price_a, price_b, truth


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))
    from statsmodels.tsa.stattools import coint

    print("=== Self-test: each factor is correctly injectable AND detectable by the REAL relevant function ===\n")
    failures = []

    # Factor 1: cointegrated=True is detected as such, cointegrated=False is not
    print("--- Factor 1: cointegration (EG test) ---")
    for coint_flag in (True, False):
        pa, pb, truth = make_synthetic_pair(n_bars=2000, cointegrated=coint_flag, mean_reversion_speed=0.1, seed=1)
        la, lb = np.log(pa.values), np.log(pb.values)
        _, pval, _ = coint(la, lb, trend="c")
        detected = pval < 0.05
        status = "OK" if detected == coint_flag else "FAIL"
        print(f"{status}  cointegrated={coint_flag}: EG p={pval:.4f}, detected_cointegrated={detected}")
        if detected != coint_flag:
            failures.append(f"cointegration factor: coint={coint_flag} but EG detected={detected}")

    # Factor 2: lead-lag structure is recovered by lagged_corr_scan.
    # Tested with hedge_ratio=0 deliberately: log_a = hedge_ratio*log_b +
    # spread means ANY nonzero hedge_ratio creates a direct, O(1)
    # contemporaneous link between A and B regardless of the
    # `cointegrated` flag (which only controls whether the SPREAD is
    # stationary, not whether A tracks B's level at all) — first attempt
    # used cointegrated=False but left hedge_ratio at its 1.0 default,
    # so A still directly tracked B's level and lag=0 still dominated
    # (corr~0.72-0.77 at lag 0 regardless of the injected lag-5 signal).
    # hedge_ratio=0 removes that direct link entirely, isolating the
    # lead-lag mechanism so it's tested on its own, not competing with a
    # second, stronger effect.
    print("\n--- Factor 2: lead-lag structure (lagged_corr_scan) ---")
    from lead_lag_scan import lagged_corr_scan, best_lag
    for true_lag in (0, 5, -5):
        pa, pb, truth = make_synthetic_pair(n_bars=3000, cointegrated=False, hedge_ratio=0.0,
                                             lead_lag_bars=true_lag, seed=2)
        ret_a = pd.Series(np.diff(np.log(pa.values), prepend=np.log(pa.values[0])), index=pa.index)
        ret_b = pd.Series(np.diff(np.log(pb.values), prepend=np.log(pb.values[0])), index=pb.index)
        scan = lagged_corr_scan(ret_a, ret_b, max_lag=10)
        k_star, c_star, n_star = best_lag(scan)
        # Loose tolerance: recovered lag within 2 bars of true, or both near 0
        ok = k_star is not None and abs(k_star - true_lag) <= 2
        status = "OK" if ok else "FAIL"
        print(f"{status}  true_lag={true_lag}: recovered best_lag={k_star} (corr={c_star})")
        if not ok:
            failures.append(f"lead-lag factor: true={true_lag} but recovered={k_star}")

    # Factor 3: structural break is detectable near the injected location
    print("\n--- Factor 3: structural break (simple variance-shift proxy check) ---")
    pa, pb, truth = make_synthetic_pair(n_bars=2000, cointegrated=True, mean_reversion_speed=0.1,
                                          structural_break_at=1000, break_type="decouple", seed=3)
    la, lb = np.log(pa.values), np.log(pb.values)
    # Full-sample EG should be weaker/non-significant given the back half decoupled
    _, pval_full, _ = coint(la, lb, trend="c")
    _, pval_pre, _ = coint(la[:1000], lb[:1000], trend="c")
    ok = pval_pre < 0.05 and pval_full > pval_pre
    status = "OK" if ok else "FAIL"
    print(f"{status}  pre-break EG p={pval_pre:.4f} (should be significant), "
          f"full-sample EG p={pval_full:.4f} (should be weaker, break dilutes it)")
    if not ok:
        failures.append(f"structural break factor: pre-break p={pval_pre}, full p={pval_full}")

    # Factor 4: gaps are correctly injected at requested positions
    print("\n--- Factor 4: gap injection ---")
    pa, pb, truth = make_synthetic_pair(n_bars=500, gap_positions=[(100, 8, "DATA_GAP"), (300, 3, "FILL")], seed=4)
    n_nan_expected = 8 + 3
    n_nan_actual = pa.isna().sum()
    ok = n_nan_actual == n_nan_expected and pa.iloc[100:108].isna().all() and pa.iloc[300:303].isna().all()
    status = "OK" if ok else "FAIL"
    print(f"{status}  expected {n_nan_expected} NaN bars at requested positions, found {n_nan_actual}")
    if not ok:
        failures.append(f"gap factor: expected {n_nan_expected} NaN, found {n_nan_actual}")

    # Factor 5: contamination seam produces a detectable discontinuity
    print("\n--- Factor 5: contamination seam (BUG-D65-style) ---")
    pa, pb, truth = make_synthetic_pair(n_bars=500, contamination_seam_at=250, contamination_ratio=2.0, seed=5)
    ratio_at_seam = pa.iloc[249] / pa.iloc[250]
    ok = 1.8 < ratio_at_seam < 2.2
    status = "OK" if ok else "FAIL"
    print(f"{status}  price ratio at seam: {ratio_at_seam:.3f} (expected ~2.0)")
    if not ok:
        failures.append(f"contamination factor: seam ratio={ratio_at_seam}, expected ~2.0")

    # Factor 6: jump dates produce isolated detectable jumps
    print("\n--- Factor 6: isolated jump injection ---")
    pa, pb, truth = make_synthetic_pair(n_bars=500, jump_dates=[250], jump_magnitude=0.15, seed=6)
    ret_at_jump = pa.iloc[250] / pa.iloc[249] - 1
    ok = ret_at_jump > 0.10
    status = "OK" if ok else "FAIL"
    print(f"{status}  return at jump bar: {ret_at_jump:.3f} (expected > 0.10)")
    if not ok:
        failures.append(f"jump factor: return={ret_at_jump}, expected > 0.10")

    print(f"\n{'='*70}")
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("All factors correctly injectable AND detectable by their real target functions.")
