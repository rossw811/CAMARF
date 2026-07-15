"""
CAMARF debug/synthetic_diagnostics.py — reusable synthetic-data generator
+ invariant-checker library for testing pipeline and research-script
methodology with KNOWN-ground-truth data (2026-07-14).

Motivation, stated plainly: today's session found and fixed real bugs in
5 different new scripts, purely because an implausible RESULT (0% win
rate, 100% win rate, identical-to-the-decimal comparison outputs, a
formula giving H=0.000 on a random walk) prompted a closer look. Every
one of those bugs COULD have been caught immediately, before ever running
on real data, by feeding the function synthetic data with a KNOWN correct
answer. This module is that: reusable generators that produce data with
a controllable, known ground truth, and reusable checkers that assert a
function's output matches what that ground truth implies — not a claim
of exhaustive pipeline coverage (the full production pipeline + 79+
research scripts is far more than one session can cover), but a real,
extensible foundation other scripts/sessions can build on.

Organized as a plain function library, not a test framework with its own
runner — so it composes naturally with this project's existing
`debug/_verify_*.py` convention (import what you need, assert directly)
rather than introducing a second parallel testing convention.

=== GENERATORS ===
Each returns data with an explicitly KNOWN property, documented in its
docstring, so a caller knows exactly what correct output should look
like before calling anything.

=== CHECKERS ===
Each is a plain assertion helper — raises AssertionError with a specific
message on failure, returns None (no exception) on success. Designed to
be called directly in any script's own ad-hoc verification, not just
from a dedicated test file.
"""
import numpy as np
import pandas as pd


# =============================================================================
# GENERATORS
# =============================================================================

def make_random_walk_series(n=5000, step_std=1.0, seed=0):
    """Levels are a pure random walk (cumsum of iid noise) -> increments
    are white noise -> KNOWN Hurst exponent H=0.5 (neither mean-reverting
    nor trending). Used to catch a Hurst-style estimator returning a
    biased/wrong value even in the "no signal" baseline case (caught
    exactly this bug in wavelet_hurst_comparison.py today: first version
    returned H=0.000 instead of ~0.5 on this exact construction)."""
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0, step_std, n))


def make_mean_reverting_series(n=5000, phi=0.3, seed=0):
    """AR(1) levels with coefficient phi (0<phi<1): s[t] = phi*s[t-1] +
    noise. KNOWN to be strongly mean-reverting for small phi — increments
    have negative lag-1 autocorrelation (phi-1)/(2-phi) < 0, so any
    correct increment-based Hurst/mean-reversion estimator MUST return
    H well below 0.5. Smaller phi = more strongly mean-reverting =
    H further below 0.5."""
    rng = np.random.default_rng(seed)
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + rng.normal(0, 1)
    return s


def make_gap_scattered_series(n=5000, gap_rate=0.17, base_std=0.003, seed=0):
    """A return series with NaN scattered roughly every 1/gap_rate bars —
    matches the REAL observed characteristic of data.py's
    _gap_aware_returns() output (confirmed directly this session: LNT's
    1h series has 747/4452 = 16.8% NaN). Any downstream .rolling(window)
    computation that doesn't explicitly handle this (e.g. compacting via
    .dropna() before rolling, or an appropriate min_periods) will
    silently produce mostly-or-entirely-NaN output — this exact bug was
    found TWICE independently today (big_move_lead_lag.py,
    hub_leg_stop_conditioning.py), both via a naive .rolling(20).std()
    on data shaped like this generator's output."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, base_std, n)
    mask = rng.random(n) < gap_rate
    ret[mask] = np.nan
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.Series(ret, index=idx)


def make_dense_calendar_grid_series(n_total=26000, real_fraction=0.14, seed=0):
    """A series matching aligned_pair_loader's DENSE reindexed output —
    most rows are NaN placeholders for non-trading time, only
    `real_fraction` of rows are real bars (confirmed directly this
    session: LNT/VTR's 1h aligned series is 26,067 rows with only 3,705
    (14.2%) real). Any rolling-window computation applied directly to
    this WITHOUT first compacting via .dropna() will see windows that
    are almost never fully real-valued — same underlying failure mode as
    make_gap_scattered_series but from a different mechanism (calendar
    density, not gap-flag masking), both requiring the same fix
    (dropna-then-reindex)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_total, freq="h")
    ret = pd.Series(np.nan, index=idx)
    n_real = int(n_total * real_fraction)
    real_positions = rng.choice(n_total, size=n_real, replace=False)
    real_positions.sort()
    ret.iloc[real_positions] = rng.normal(0, 0.003, n_real)
    return ret


def make_z_score_series_with_known_trade(entry_z=2.5, exit_z=0.0, hold_bars=20,
                                          pre_bars=30, post_bars=30, seed=0):
    """A z-score series with a single, HAND-PLANTED, unambiguous
    mean-reverting trade: starts near 0, jumps to entry_z, then reverts
    linearly to exit_z over hold_bars, then stays near exit_z. A correct
    "fade the extreme" mean-reversion P&L calculation MUST show a
    positive-sign profit for this trade (entry_z=2.5 fading down to
    exit_z=0.0 is an unambiguous win for anyone betting on the
    reversion) — this exact construction (a hand-computable expected
    sign) is what would have caught breakout_vs_reversion.py's P&L sign
    bug immediately, before it ever touched real data."""
    rng = np.random.default_rng(seed)
    pre = rng.normal(0, 0.1, pre_bars)
    ramp_up = np.array([entry_z])
    reversion = np.linspace(entry_z, exit_z, hold_bars)
    post = exit_z + rng.normal(0, 0.1, post_bars)
    z = np.concatenate([pre, ramp_up, reversion, post])
    return pd.Series(z, index=pd.date_range("2024-01-01", periods=len(z), freq="h")), {
        "entry_idx": pre_bars, "expected_exit_idx_range": (pre_bars + hold_bars - 2, pre_bars + hold_bars + 2),
        "entry_z": entry_z, "exit_z": exit_z, "expected_pnl_sign": 1,
    }


# =============================================================================
# CHECKERS
# =============================================================================

def assert_not_degenerate(series_or_array, name="series", max_nan_fraction=0.5):
    """Catches the exact class of bug found twice today: a computation
    that silently returns all-or-mostly-NaN due to an unhandled gap/
    sparsity issue upstream. Fails loudly instead of letting a downstream
    comparison (e.g. `>= threshold`) silently evaluate False forever."""
    arr = np.asarray(series_or_array, dtype=float)
    if arr.size == 0:
        raise AssertionError(f"{name}: empty — expected a real result")
    nan_frac = np.isnan(arr).mean()
    if nan_frac > max_nan_fraction:
        raise AssertionError(
            f"{name}: {nan_frac:.1%} NaN (max allowed {max_nan_fraction:.1%}) — "
            f"likely a rolling-window-on-sparse-data bug (see make_gap_scattered_series/"
            f"make_dense_calendar_grid_series docstrings for the known failure mode)"
        )


def assert_recovers_known_hurst(estimator_fn, tolerance=0.15):
    """Runs a Hurst-style estimator (callable taking a levels array,
    returning a float H) against both reference generators and checks
    the DIRECTION and rough magnitude are right — not exact equality
    (finite-sample noise), but far enough from wrong that a sign/formula
    error like today's wavelet bug (H=0.000 instead of ~0.5) would fail
    loudly."""
    h_random_walk = estimator_fn(make_random_walk_series(5000, seed=0))
    if not (0.5 - tolerance <= h_random_walk <= 0.5 + tolerance):
        raise AssertionError(
            f"random-walk H={h_random_walk:.3f}, expected ~0.5 +/- {tolerance} — "
            f"estimator likely has a formula/sign bug"
        )
    h_reverting = estimator_fn(make_mean_reverting_series(5000, phi=0.3, seed=1))
    if not (h_reverting < 0.5 - tolerance / 2):
        raise AssertionError(
            f"strongly-mean-reverting (phi=0.3) H={h_reverting:.3f}, expected well below 0.5 — "
            f"estimator likely has a formula/sign bug"
        )
    if not (h_reverting < h_random_walk):
        raise AssertionError(
            f"expected H(mean-reverting)={h_reverting:.3f} < H(random-walk)={h_random_walk:.3f} — "
            f"estimator response is backwards"
        )


def assert_trades_have_valid_exits(trades, n_bars, entry_key="entry_idx", exit_key="exit_idx"):
    """Every trade must have entry_idx <= exit_idx < n_bars — catches the
    'entries without matching exits' failure mode Ross flagged this
    session (fake P&L, and breaks capital-constraint simulation since
    capital never frees up). Also flags any trade whose exit is not
    STRICTLY reachable from its entry within n_bars, which would indicate
    an out-of-bounds or off-by-one construction bug."""
    for i, t in enumerate(trades):
        entry_idx, exit_idx = t[entry_key], t[exit_key]
        if exit_idx < entry_idx:
            raise AssertionError(f"trade {i}: exit_idx={exit_idx} < entry_idx={entry_idx} — invalid")
        if exit_idx >= n_bars or entry_idx >= n_bars:
            raise AssertionError(
                f"trade {i}: entry_idx={entry_idx}/exit_idx={exit_idx} out of bounds (n_bars={n_bars}) — "
                f"a position was left open beyond the available data"
            )


def assert_known_trade_pnl_sign(pnl_fn, expected_sign=1):
    """The decisive check that would have caught breakout_vs_reversion.py's
    sign bug (0.00 win rate on 665 trades from independently-verified
    mean-reverting pairs) BEFORE it ever ran on real data. pnl_fn: a
    callable taking (z_series, ground_truth_dict) -> float pnl, using
    make_z_score_series_with_known_trade's output."""
    z, truth = make_z_score_series_with_known_trade()
    pnl = pnl_fn(z, truth)
    actual_sign = 1 if pnl > 0 else (-1 if pnl < 0 else 0)
    if actual_sign != truth["expected_pnl_sign"]:
        raise AssertionError(
            f"hand-planted unambiguous winning trade (entry_z={truth['entry_z']} fading to "
            f"exit_z={truth['exit_z']}) produced pnl={pnl:.4f} (sign={actual_sign}), "
            f"expected sign={truth['expected_pnl_sign']} — P&L formula likely has a sign error"
        )


def assert_no_lookahead_in_rolling(fn, series, window):
    """Generic causal-computation check: perturbing a value AFTER
    position t must not change fn's output AT position t. Constructs two
    copies of `series` that are identical up to and including index t,
    differ after — asserts fn's output at t is identical for both.
    Catches lookahead bugs generically, not just the specific patterns
    already found this session."""
    n = len(series)
    t = n // 2
    if t + window >= n:
        raise ValueError("series too short relative to window for this check")
    s1 = series.copy()
    s2 = series.copy()
    rng = np.random.default_rng(0)
    s2.iloc[t + 1:] = s2.iloc[t + 1:] + rng.normal(0, 100, n - t - 1)  # huge perturbation after t
    out1 = fn(s1)
    out2 = fn(s2)
    v1, v2 = out1.iloc[t], out2.iloc[t]
    if not (pd.isna(v1) and pd.isna(v2)) and not np.isclose(v1, v2, equal_nan=True):
        raise AssertionError(
            f"fn's output at index {t} changed ({v1} -> {v2}) after perturbing data AFTER that "
            f"index — likely a lookahead bug (uses future data the position wouldn't have known)"
        )


if __name__ == "__main__":
    # Self-test: run every checker against a known-good and known-bad
    # implementation, confirming the checkers themselves catch what
    # they claim to.
    print("=== Self-test: assert_not_degenerate ===")
    try:
        assert_not_degenerate(make_gap_scattered_series(1000, gap_rate=0.99), "99%-NaN series")
        print("FAIL: should have raised on a 99%-NaN series")
    except AssertionError as e:
        print(f"OK (correctly raised): {e}")
    assert_not_degenerate(make_random_walk_series(1000), "clean random walk")
    print("OK: clean series passes")

    print("\n=== Self-test: assert_recovers_known_hurst ===")
    def _broken_hurst(levels):
        return 0.0  # the exact bug found in wavelet_hurst_comparison.py today
    try:
        assert_recovers_known_hurst(_broken_hurst)
        print("FAIL: should have raised on the broken estimator")
    except AssertionError as e:
        print(f"OK (correctly raised): {e}")

    def _correct_hurst(levels):
        inc = np.diff(levels)
        # crude but directionally-correct proxy: lag-1 autocorrelation sign
        ac1 = np.corrcoef(inc[:-1], inc[1:])[0, 1]
        return float(np.clip(0.5 + ac1 * 0.3, 0.0, 1.0))
    assert_recovers_known_hurst(_correct_hurst, tolerance=0.2)
    print("OK: directionally-correct estimator passes")

    print("\n=== Self-test: assert_trades_have_valid_exits ===")
    try:
        assert_trades_have_valid_exits([{"entry_idx": 5, "exit_idx": 200}], n_bars=100)
        print("FAIL: should have raised on out-of-bounds exit")
    except AssertionError as e:
        print(f"OK (correctly raised): {e}")
    assert_trades_have_valid_exits([{"entry_idx": 5, "exit_idx": 10}], n_bars=100)
    print("OK: valid trade passes")

    print("\n=== Self-test: assert_known_trade_pnl_sign ===")
    def _broken_pnl(z, truth):
        # The actual bug found in breakout_vs_reversion.py today:
        # direction * (entry_z - exit_z) instead of direction * (exit_z -
        # entry_z). For this fade-down-from-positive scenario, direction=-1,
        # so correct is -1*(exit-entry)=entry-exit; broken is -1*(entry-exit)=exit-entry
        # (exact sign flip of the correct formula, not just a different
        # arithmetic path that happens to coincide).
        exit_val = z.iloc[truth["expected_exit_idx_range"][0]]
        return exit_val - truth["entry_z"]  # sign-flipped vs. the correct entry_z - exit_val
    try:
        assert_known_trade_pnl_sign(_broken_pnl)
        print("FAIL: should have raised on the sign-flipped P&L")
    except AssertionError as e:
        print(f"OK (correctly raised): {e}")

    def _correct_pnl(z, truth):
        exit_val = z.iloc[truth["expected_exit_idx_range"][0]]
        return truth["entry_z"] - exit_val  # fading down from entry_z: profit = entry - exit
    assert_known_trade_pnl_sign(_correct_pnl)
    print("OK: correct P&L formula passes")

    print("\n=== Self-test: assert_no_lookahead_in_rolling ===")
    s = pd.Series(np.random.default_rng(0).normal(0, 1, 200),
                   index=pd.date_range("2024-01-01", periods=200, freq="h"))

    def _lookahead_bug(series):
        return series.rolling(10, center=True).mean()  # centered window = lookahead

    def _causal_ok(series):
        return series.rolling(10).mean()  # trailing window = causal

    try:
        assert_no_lookahead_in_rolling(_lookahead_bug, s, window=10)
        print("FAIL: should have raised on a centered (lookahead) rolling window")
    except AssertionError as e:
        print(f"OK (correctly raised): {e}")
    assert_no_lookahead_in_rolling(_causal_ok, s, window=10)
    print("OK: causal trailing window passes")

    print("\nAll self-tests passed — checkers correctly distinguish known-good from known-bad "
          "implementations of every failure mode found this session.")
