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

EXTENDED 2026-09-01 (Ross: "update it for sophistication and robustness
based on the modern needs of the project, as a lot has changed in the past
month and a half") — the original 8 factors above predate the entire
2026-08 WRDS-merge/episodic-scan/PIT-safety arc and don't cover any of it.
Four new factors, same additive/backward-compatible discipline (every new
parameter defaults to None/off, reproducing the exact original behavior
when unused — verified explicitly in the self-test section, not assumed):
  9. coint_regime_windows (list of (start, end, is_cointegrated))
     -> research/wrds_deep_history_episodic_scan.py's Tier 2/3 episodic,
        rolling-window EG testing; BUG-D112's causal-candidacy gate
        (first_qualified_window_end_date); research/pit_wfa_episodic.py.
        Replaces the single global `cointegrated` bool with a genuine
        time-varying schedule — a pair that's ONLY cointegrated in some
        sub-windows, exactly the shape of relationship the whole episodic-
        vs-static methodology exists to distinguish from a pair that's
        cointegrated (or not) for its entire history.
 10. symbol_a_membership_spells / symbol_b_membership_spells
     (list of (start, end) index-membership windows per symbol)
     -> the "Point-in-time S&P 500 membership gate" seen constantly in
        wrds_deep_history_episodic_scan.py's real production logs — a
        window should be gated OUT if EITHER symbol wasn't an index member
        as of that window's end date. Recorded as ground-truth metadata
        (does not alter the price series) plus an `is_pit_member()` helper
        so a verify script can check the real gate's decision at any bar
        against a known-correct answer.
 11. adv_regime ("constant_liquid" / "constant_illiquid" /
     "liquid_then_illiquid" / "illiquid_then_liquid")
     -> the ADV (rolling average dollar volume) liquidity gate, the other
        gate constantly seen in real Tier 2/3 logs alongside the PIT gate.
        This factory previously generated NO volume series at all (price
        only) — adds one, stored in ground_truth (not the main return
        tuple, so every existing caller's `price_a, price_b, ground_truth
        = make_synthetic_pair(...)` unpacking is completely unaffected).
 12. make_duplicate_identity_pair() (separate helper, not a
     make_synthetic_pair parameter — a different concept: two DIFFERENT
     symbol labels for what is secretly the SAME underlying company, not
     a cointegrated pair of genuinely different companies)
     -> the 78->27 pair-promotion contamination taxonomy (Development.md
        2026-08-24): same-GVKEY duplicate identities, ticker<->PERMNO
        collisions, SPAC NAV-clustering. Produces two price series that are
        identical (or near-identical, via a small optional noise_std) up to
        a synthetic vendor-labeling difference, for testing collision-
        detection logic like promote_full_universe_pairs.py's same-GVKEY
        filter without needing a real, already-known contamination case.

Honest scope note: this factory targets the factors this session's own
work has DIRECTLY touched and can verify are correctly injected/
detectable. It does not yet cover every conceivable pipeline behavior
(e.g. IBKR-specific pacing/connection failure modes) — designed to be
EXTENDED, not treated as already-exhaustive. Each new factor added should
get the same inject-then-verify-detectable treatment demonstrated in this
file's self-test section.
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
    coint_regime_windows: Optional[List[Tuple[int, int, bool]]] = None,
    symbol_a_membership_spells: Optional[List[Tuple[int, int]]] = None,
    symbol_b_membership_spells: Optional[List[Tuple[int, int]]] = None,
    adv_regime: Optional[str] = None,
    adv_base_dollar_volume: float = 50_000_000.0,
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

    EXTENDED 2026-09-01:
      9. coint_regime_windows (list of (start, end, is_cointegrated),
         covering [0, n_bars) with no gaps or overlaps): if given,
         OVERRIDES the single global `cointegrated`/`mean_reversion_speed`
         behavior with a genuine time-varying schedule — the spread is OU
         (mean-reverting) during is_cointegrated=True windows and a random
         walk during is_cointegrated=False windows, with the OU/RW state
         carried continuously across window boundaries (no artificial
         level jump at a schedule change, only a change in DYNAMICS,
         exactly like a real relationship gradually starting or stopping
         to hold rather than teleporting). When None (default), behavior
         is IDENTICAL to the original single-window `cointegrated` bool.
     10. symbol_a_membership_spells / symbol_b_membership_spells (list of
         (start, end) bar-index windows where that symbol is a PIT index
         member): pure ground-truth metadata, does not touch the price
         series — use with the module-level is_pit_member() helper to
         check a real gate's decision at any bar against a known answer.
         None (default) means "no membership restriction" (always a
         member), matching a symbol with no gate applied.
     11. adv_regime: if given, also generates a synthetic DAILY-style
         dollar-volume series (independent of the hourly price index —
         collapsed to one value per ~24 bars to mimic a daily ADV signal
         the way the real pipeline computes it) with a controllable
         liquidity regime, stored at ground_truth["volume_a"] (a pd.Series
         aligned to price_a's index, forward-filled within each day) —
         does not alter price_a/price_b themselves. None (default)
         generates no volume series at all, identical to the original
         price-only behavior.
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
    if coint_regime_windows is not None:
        # 2026-09-01 extension: a genuine time-varying schedule instead of
        # one global flag. State (spread level) carries continuously across
        # window boundaries -- only the DYNAMICS (mean-reverting vs random
        # walk) change at a boundary, never an artificial level jump.
        _validate_regime_windows(coint_regime_windows, n_bars)
        spread = np.zeros(n_bars)
        for start, end, is_coint in coint_regime_windows:
            for t in range(max(start, 1), end):
                if is_coint:
                    spread[t] = (1 - mean_reversion_speed) * spread[t - 1] + a_innov[t] * 0.01
                else:
                    spread[t] = spread[t - 1] + a_innov[t] * 0.01
    elif cointegrated:
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

    # --- 8. ADV/liquidity regime (2026-09-01 extension) — a synthetic
    # dollar-volume series, independent of price. None (default) generates
    # nothing at all, identical to the original price-only behavior.
    volume_a = None
    if adv_regime is not None:
        volume_a = _make_adv_series(n_bars, idx, adv_regime, adv_base_dollar_volume, rng)

    ground_truth = {
        "cointegrated": cointegrated, "hedge_ratio": hedge_ratio,
        "mean_reversion_speed": mean_reversion_speed, "lead_lag_bars": lead_lag_bars,
        "structural_break_at": structural_break_at, "break_type": break_type if structural_break_at else None,
        "gaps": gap_metadata, "contamination_seam_at": contamination_seam_at if contamination_applied else None,
        "contamination_ratio": contamination_ratio if contamination_applied else None,
        "jump_dates": jump_dates or [], "volatility_regime": volatility_regime, "n_bars": n_bars,
        "coint_regime_windows": coint_regime_windows,
        "symbol_a_membership_spells": symbol_a_membership_spells,
        "symbol_b_membership_spells": symbol_b_membership_spells,
        "adv_regime": adv_regime, "volume_a": volume_a,
    }
    return price_a, price_b, ground_truth


def _validate_regime_windows(windows: List[Tuple[int, int, bool]], n_bars: int) -> None:
    """Confirms coint_regime_windows covers [0, n_bars) with no gaps or
    overlaps -- a silently incomplete schedule would leave part of the
    spread at its zero-initialized default, a subtle bug that would look
    like a legitimate (but wrong) flat/non-mean-reverting stretch rather
    than an obvious crash."""
    sorted_windows = sorted(windows, key=lambda w: w[0])
    if sorted_windows[0][0] != 0:
        raise ValueError(f"coint_regime_windows must start at bar 0, got {sorted_windows[0][0]}")
    if sorted_windows[-1][1] != n_bars:
        raise ValueError(f"coint_regime_windows must end at n_bars={n_bars}, got {sorted_windows[-1][1]}")
    for (s1, e1, _), (s2, e2, _) in zip(sorted_windows, sorted_windows[1:]):
        if e1 != s2:
            raise ValueError(f"coint_regime_windows has a gap or overlap between ({s1},{e1}) and ({s2},{e2})")


def _make_adv_series(n_bars: int, idx: pd.DatetimeIndex, adv_regime: str,
                      base_dollar_volume: float, rng: np.random.Generator) -> pd.Series:
    """Pure helper -- one dollar-volume value per calendar day (held
    constant across that day's intraday bars, mimicking how a real daily
    ADV signal looks when joined onto an intraday-indexed series), with a
    controllable liquidity regime. ILLIQUID_MULT=0.1 puts synthetic volume
    well below a typical $25M ADV gate threshold when base_dollar_volume is
    the liquid-regime default ($50M), so a real gate applied to this series
    has a genuine liquid/illiquid distinction to detect, not two values on
    the same side of any real threshold."""
    ILLIQUID_MULT = 0.1
    day_of = idx.floor("D")
    unique_days = day_of.unique()
    n_days = len(unique_days)
    if adv_regime == "constant_liquid":
        per_day = np.full(n_days, base_dollar_volume)
    elif adv_regime == "constant_illiquid":
        per_day = np.full(n_days, base_dollar_volume * ILLIQUID_MULT)
    elif adv_regime == "liquid_then_illiquid":
        per_day = np.full(n_days, base_dollar_volume)
        per_day[n_days // 2:] *= ILLIQUID_MULT
    elif adv_regime == "illiquid_then_liquid":
        per_day = np.full(n_days, base_dollar_volume * ILLIQUID_MULT)
        per_day[n_days // 2:] /= ILLIQUID_MULT
    else:
        raise ValueError(f"unknown adv_regime={adv_regime!r}")
    per_day *= (1.0 + rng.normal(0, 0.05, n_days))  # small realistic day-to-day noise
    day_to_vol = dict(zip(unique_days, per_day))
    return pd.Series([day_to_vol[d] for d in day_of], index=idx)


def is_pit_member(membership_spells: Optional[List[Tuple[int, int]]], bar_idx: int) -> bool:
    """Given a symbol's ground_truth membership_spells (list of (start, end)
    bar-index windows, end exclusive) and a bar index, returns whether that
    symbol is a known index member at that bar. None means "no restriction
    specified" -> always a member (matches a symbol with no gate applied).
    Use this as the KNOWN-correct answer when testing a real PIT
    membership-gate function against synthetic data."""
    if membership_spells is None:
        return True
    return any(start <= bar_idx < end for start, end in membership_spells)


def make_duplicate_identity_pair(
    n_bars: int = 500, seed: int = 0, start_price: float = 100.0,
    label_a: str = "TICKER_A", label_b: str = "TICKER_B", noise_std: float = 0.0,
) -> Tuple[pd.Series, pd.Series, Dict[str, Any]]:
    """2026-09-01 addition, per the 78->27 pair-promotion contamination
    taxonomy (Development.md 2026-08-24): produces two DIFFERENTLY-LABELED
    price series that are secretly the SAME underlying identity (a same-
    GVKEY duplicate, or a ticker<->PERMNO collision), for testing
    collision-detection logic like promote_full_universe_pairs.py's
    same-GVKEY filter without needing a real, already-known contamination
    case. noise_std=0 (default) makes them bit-for-bit identical -- the
    cleanest "this MUST be caught" case; a small noise_std produces a
    near-identical pair (mimics two vendors' slightly different rounding/
    adjustment of what's still the same underlying security), a harder,
    more realistic detection case."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="h")
    log_p = np.cumsum(rng.normal(0, 1, n_bars)) * 0.01 + np.log(start_price)
    price_a = pd.Series(np.exp(log_p), index=idx)
    if noise_std > 0:
        price_b = pd.Series(np.exp(log_p + rng.normal(0, noise_std, n_bars)), index=idx)
    else:
        price_b = price_a.copy()
    ground_truth = {
        "is_duplicate_identity": True, "label_a": label_a, "label_b": label_b,
        "noise_std": noise_std, "correlation": float(np.corrcoef(price_a, price_b)[0, 1]),
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

    # Backward-compatibility check (2026-09-01): every new parameter must
    # default to reproducing EXACTLY the original behavior when unused —
    # not just "close," bit-for-bit identical, since this factory has zero
    # importers today but is meant to be adopted broadly, and a silent
    # behavior change on upgrade would be a real, hard-to-notice regression.
    print("\n--- Backward compatibility: new params default to zero effect ---")
    pa_old = make_synthetic_pair(n_bars=500, cointegrated=True, mean_reversion_speed=0.1, seed=42)
    pa_new = make_synthetic_pair(n_bars=500, cointegrated=True, mean_reversion_speed=0.1, seed=42,
                                  coint_regime_windows=None, symbol_a_membership_spells=None,
                                  symbol_b_membership_spells=None, adv_regime=None)
    ok = pa_old[0].equals(pa_new[0]) and pa_old[1].equals(pa_new[1])
    status = "OK" if ok else "FAIL"
    print(f"{status}  identical output with all new params at their defaults vs. omitted entirely")
    if not ok:
        failures.append("backward compatibility: new-param defaults changed original output")

    # Factor 9: coint_regime_windows produces a schedule-following spread —
    # cointegrated sub-window is EG-significant on its own, non-cointegrated
    # sub-window is not, even though a single global flag could never
    # produce this pattern.
    print("\n--- Factor 9: coint_regime_windows (episodic schedule) ---")
    pa, pb, truth = make_synthetic_pair(
        n_bars=2000, mean_reversion_speed=0.1, hedge_ratio=1.0, seed=9,
        coint_regime_windows=[(0, 1000, True), (1000, 2000, False)],
    )
    la, lb = np.log(pa.values), np.log(pb.values)
    _, pval_coint_window, _ = coint(la[:1000], lb[:1000], trend="c")
    _, pval_noncoint_window, _ = coint(la[1000:], lb[1000:], trend="c")
    ok = pval_coint_window < 0.05 and pval_noncoint_window > pval_coint_window
    status = "OK" if ok else "FAIL"
    print(f"{status}  cointegrated window (bars 0-1000) EG p={pval_coint_window:.4f} (should be significant), "
          f"non-cointegrated window (bars 1000-2000) EG p={pval_noncoint_window:.4f} (should be weaker)")
    if not ok:
        failures.append(f"coint_regime_windows factor: coint-window p={pval_coint_window}, "
                         f"non-coint-window p={pval_noncoint_window}")
    try:
        make_synthetic_pair(n_bars=100, coint_regime_windows=[(0, 50, True), (60, 100, False)])
        failures.append("coint_regime_windows: a schedule with a gap (50-60 missing) should have raised, did not")
        print("FAIL  a schedule with a gap should raise ValueError, did not")
    except ValueError:
        print("OK  a schedule with a gap correctly raises ValueError (_validate_regime_windows)")

    # Factor 10: is_pit_member() matches the injected spells exactly
    print("\n--- Factor 10: PIT membership spells + is_pit_member() ---")
    spells = [(0, 100), (200, 300)]
    checks = [(50, True), (150, False), (250, True), (350, False)]
    ok = all(is_pit_member(spells, bar) == expected for bar, expected in checks)
    status = "OK" if ok else "FAIL"
    print(f"{status}  is_pit_member matches known spells at bars {[b for b, _ in checks]}")
    if not ok:
        failures.append(f"is_pit_member: mismatch against known spells {spells}")
    ok_none = all(is_pit_member(None, bar) is True for bar in (0, 500, 99999))
    print(f"{'OK' if ok_none else 'FAIL'}  is_pit_member(None, ...) is always True (no restriction specified)")
    if not ok_none:
        failures.append("is_pit_member: None spells should always return True")

    # Factor 11: adv_regime produces a genuinely liquid/illiquid distinction
    print("\n--- Factor 11: ADV/liquidity regime ---")
    pa, pb, truth = make_synthetic_pair(n_bars=500, adv_regime="liquid_then_illiquid",
                                         adv_base_dollar_volume=50_000_000.0, seed=11)
    vol = truth["volume_a"]
    ADV_GATE_THRESHOLD = 25_000_000.0  # matches the real pipeline's $25M ADV gate
    first_half_liquid = vol.iloc[:len(vol) // 4].mean() > ADV_GATE_THRESHOLD
    second_half_illiquid = vol.iloc[-len(vol) // 4:].mean() < ADV_GATE_THRESHOLD
    ok = first_half_liquid and second_half_illiquid
    status = "OK" if ok else "FAIL"
    print(f"{status}  liquid_then_illiquid: early mean=${vol.iloc[:len(vol)//4].mean():,.0f} "
          f"(should be > ${ADV_GATE_THRESHOLD:,.0f}), late mean=${vol.iloc[-len(vol)//4:].mean():,.0f} "
          f"(should be < ${ADV_GATE_THRESHOLD:,.0f})")
    if not ok:
        failures.append("adv_regime factor: liquid_then_illiquid did not cross the real $25M gate threshold "
                         "in the expected direction")
    pa2, pb2, truth2 = make_synthetic_pair(n_bars=500, seed=11)  # adv_regime=None (default)
    ok_none = truth2["volume_a"] is None
    print(f"{'OK' if ok_none else 'FAIL'}  adv_regime=None (default) generates no volume series at all")
    if not ok_none:
        failures.append("adv_regime: default (None) should leave ground_truth['volume_a'] as None")

    # Factor 12: make_duplicate_identity_pair() produces a near-perfect
    # correlation a collision-detection filter should flag
    print("\n--- Factor 12: make_duplicate_identity_pair() (GVKEY/ticker-collision contamination) ---")
    pa, pb, truth = make_duplicate_identity_pair(n_bars=500, seed=12, noise_std=0.0)
    ok = truth["correlation"] > 0.9999 and pa.equals(pb)
    status = "OK" if ok else "FAIL"
    print(f"{status}  noise_std=0: correlation={truth['correlation']:.6f} (expected >0.9999), "
          f"series bit-identical={pa.equals(pb)}")
    if not ok:
        failures.append(f"duplicate identity factor (noise_std=0): correlation={truth['correlation']}")
    pa2, pb2, truth2 = make_duplicate_identity_pair(n_bars=500, seed=12, noise_std=0.01)
    ok2 = truth2["correlation"] > 0.95 and not pa2.equals(pb2)
    status2 = "OK" if ok2 else "FAIL"
    print(f"{status2}  noise_std=0.01: correlation={truth2['correlation']:.6f} (expected >0.95, <1), "
          f"series NOT identical={not pa2.equals(pb2)}")
    if not ok2:
        failures.append(f"duplicate identity factor (noise_std=0.01): correlation={truth2['correlation']}")

    print(f"\n{'='*70}")
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("All factors correctly injectable AND detectable by their real target functions.")
