"""
CAMARF research/cycle_detection.py — comparison/diagnostic script, NOT
part of the production pipeline (2026-08-02).

Ross's own framing: test cycle detection along three axes at once, for
research/comparison purposes first — no production (ml.py/backtest.py)
wiring yet, that's a separate, later decision once this shows real signal.

  1. WITHIN-ASSET dominant cycle: time-varying dominant period via a
     continuous Morlet wavelet transform (Torrence & Compo, 1998),
     implemented directly in numpy/FFT rather than adding a PyWavelets
     dependency — same "no new dependency" convention already established
     by wavelet_hurst_comparison.py's hand-rolled Haar estimator, for the
     same documented reason (this project's history of environment/
     dependency pain: pyarrow version mismatches, base-vs-trading-env
     confusion).
  2. CROSS-ASSET phase synchronization: a rolling, CAUSAL phase-locking
     value (PLV) between a pair's two legs via Hilbert-transform
     instantaneous phase (scipy.signal.hilbert — already an existing
     scipy dependency, not new). Each PLV value uses only the trailing
     `window` bars ending at that point.
  3. CROSS-TIMEFRAME cycle consistency: does the same pair's dominant
     cycle (converted to a common calendar-day unit via bars-per-day)
     show up consistently across timeframes. Reuses
     cross_timeframe_divergence.py's own _BARS_PER_DAY table rather than
     duplicating it (this project's established shared-utility precedent).

DISCLOSED LIMITATION (bias-documentation rule, CLAUDE.md rules #6/#7): the
dominant-cycle wavelet transform (#1) is NOT point-in-time-safe as
implemented — it is computed via one whole-series FFT, so
"dominant period at time t" uses information from both before AND after
t. This is fine for a first-pass research diagnostic ("does a stable
cycle exist in this pair's history at all") but MUST NOT be used as an
ml.py feature or a live signal without a causal retrofit (e.g. a
trailing-window-only CWT recomputed forward, at real computational cost)
first. The rolling PLV (#2) does not have this problem — it is already
windowed/causal by construction (verified directly, see
debug/_verify_cycle_detection.py's causality check). Also disclosed: PLV
here is computed on RAW (unfiltered) returns, not band-pass-filtered to a
specific frequency of interest first — a standard refinement if this
proves promising, deliberately not applied in this v1 diagnostic.

Usage:
    python research/cycle_detection.py
    python research/cycle_detection.py --plv-window 30
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.signal import hilbert

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price
from cross_timeframe_divergence import _BARS_PER_DAY as _BASE_BARS_PER_DAY
import ml

# cross_timeframe_divergence._BARS_PER_DAY has no 2min/3min entries (that
# module's own default TF groups never needed them) -- extend locally (390
# trading minutes/day, same convention as every other entry in the base
# table) rather than editing that module's dict.
_BARS_PER_DAY = dict(_BASE_BARS_PER_DAY, **{"2min": 195.0, "3min": 130.0})


def morlet_period_for_scale(scale, w0: float = 6.0):
    """Torrence & Compo (1998) eq. 10: Fourier period corresponding to a
    Morlet wavelet scale, for the standard w0=6 (~5.3-cycle) Morlet."""
    return 4 * np.pi * scale / (w0 + np.sqrt(2 + w0 ** 2))


def morlet_cwt(x: np.ndarray, periods: np.ndarray, w0: float = 6.0) -> np.ndarray:
    """
    Continuous Morlet wavelet transform via FFT convolution (Torrence &
    Compo 1998, eq. 6), evaluated at the given target periods (in bars).
    Returns a (len(periods), len(x)) complex array. x must be finite (no
    NaNs) — caller's responsibility to mask/interpolate first.

    NOT causal: the FFT convolution uses the entire series at every t.
    See module docstring's disclosed limitation.
    """
    n = len(x)
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    fx = np.fft.fft(x)
    omega = 2 * np.pi * np.fft.fftfreq(n)
    scales = np.asarray(periods) * (w0 + np.sqrt(2 + w0 ** 2)) / (4 * np.pi)
    heaviside = (omega > 0).astype(float)
    W = np.empty((len(scales), n), dtype=complex)
    for i, s in enumerate(scales):
        norm = np.sqrt(2 * np.pi * s) * (np.pi ** -0.25)
        daughter = norm * heaviside * np.exp(-0.5 * (s * omega - w0) ** 2)
        W[i] = np.fft.ifft(fx * daughter)
    return W


def dominant_cycle(x: np.ndarray, min_period: int = 4, max_period_frac: float = 0.25,
                    n_periods: int = 40) -> dict:
    """
    Within-asset dominant cycle via the Morlet CWT's global wavelet
    spectrum (time-averaged power at each scanned period).
    """
    x = x[np.isfinite(x)]
    n = len(x)
    max_period = max(min_period + 1, int(n * max_period_frac))
    periods = np.geomspace(min_period, max_period, n_periods)
    W = morlet_cwt(x, periods)
    power = np.abs(W) ** 2
    global_power = power.mean(axis=1)
    dominant_period_global = float(periods[np.argmax(global_power)])
    dominant_period_t = periods[np.argmax(power, axis=0)]
    return {
        "periods": periods,
        "global_power": global_power,
        "dominant_period_global": dominant_period_global,
        "dominant_period_t": dominant_period_t,
    }


def rolling_plv(x_a: np.ndarray, x_b: np.ndarray, window: int) -> np.ndarray:
    """
    CAUSAL rolling phase-locking value between two return series, via
    Hilbert-transform instantaneous phase. plv[t] uses ONLY
    x_a[t-window+1:t+1] and x_b[...] — the trailing window, never future
    bars. First (window-1) entries are NaN (insufficient history),
    matching this project's existing rolling-estimator convention (e.g.
    rolling_half_life).

    PLV = |mean_t(exp(i * (phase_a(t) - phase_b(t))))| over the window —
    1.0 means perfectly phase-locked throughout the window, 0.0 means
    phases drift independently. Standard definition (Lachaux et al. 1999).
    """
    n = len(x_a)
    plv = np.full(n, np.nan)
    for t in range(window - 1, n):
        wa = x_a[t - window + 1:t + 1]
        wb = x_b[t - window + 1:t + 1]
        if not (np.all(np.isfinite(wa)) and np.all(np.isfinite(wb))):
            continue
        phase_a = np.angle(hilbert(wa))
        phase_b = np.angle(hilbert(wb))
        plv[t] = np.abs(np.mean(np.exp(1j * (phase_a - phase_b))))
    return plv


def cross_timeframe_consistency(period_a_bars: float, tf_a: str,
                                 period_b_bars: float, tf_b: str) -> dict:
    """
    Converts each TF's dominant period (in bars) to calendar days using
    the shared bars/day table, then compares. A genuinely shared
    underlying cycle should show up as roughly the SAME calendar-day
    period regardless of sampling rate.
    """
    bpd_a = _BARS_PER_DAY.get(tf_a)
    bpd_b = _BARS_PER_DAY.get(tf_b)
    if not bpd_a or not bpd_b:
        return {"consistent_within_2x": None, "reason": f"no bars/day entry for {tf_a} or {tf_b}"}
    days_a = period_a_bars / bpd_a
    days_b = period_b_bars / bpd_b
    ratio = days_a / days_b if days_b else np.nan
    return {
        "period_days_a": days_a,
        "period_days_b": days_b,
        "ratio": ratio,
        "consistent_within_2x": bool(0.5 <= ratio <= 2.0) if np.isfinite(ratio) else None,
    }


def _returns(log_price: np.ndarray) -> np.ndarray:
    return np.diff(log_price)


def main():
    ap = argparse.ArgumentParser(description="Cycle detection research diagnostic (2026-08-02)")
    ap.add_argument("--plv-window", type=int, default=60)
    args = ap.parse_args()

    from data import DataStore

    pairs = ml._discover_confirmed_pairs()  # (symbol_a, symbol_b, tf_label) for EVERY confirmed pair, all TFs
    if not pairs:
        print("No confirmed pairs found (no persisted spread_series_*.parquet) — nothing to run.")
        return
    print(f"Running cycle detection on {len(pairs)} confirmed (pair, TF) combinations...")

    rows = []
    for sym_a, sym_b, tf_label_short in pairs:
        # ml.py's discovery returns production's short-form tf_label ("2m"/"1h"/...);
        # load_aligned_pair/DataStore expect the long "safe" form ("2min"/"1hr"/...) --
        # DataStore._TF_SAFE is the authoritative mapping, reused directly rather than
        # guessed at.
        tf = DataStore._TF_SAFE.get(tf_label_short, tf_label_short.lower())
        df_a, df_b = load_aligned_pair(sym_a, sym_b, tf)
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            print(f"skip {sym_a}/{sym_b}@{tf}: no aligned data")
            continue
        log_a = _gap_masked_log_price(df_a)
        log_b = _gap_masked_log_price(df_b)
        common_idx = df_a.index.intersection(df_b.index)
        la = pd.Series(log_a, index=df_a.index).reindex(common_idx).values
        lb = pd.Series(log_b, index=df_b.index).reindex(common_idx).values
        ra, rb = _returns(la), _returns(lb)
        mask = np.isfinite(ra) & np.isfinite(rb)
        ra_f, rb_f = ra[mask], rb[mask]
        if len(ra_f) < args.plv_window * 3:
            print(f"skip {sym_a}/{sym_b}@{tf}: only {len(ra_f)} clean bars, need >= {args.plv_window * 3}")
            continue

        dom_a = dominant_cycle(ra_f)
        dom_b = dominant_cycle(rb_f)
        plv = rolling_plv(ra_f, rb_f, args.plv_window)

        print(f"\n{sym_a}/{sym_b}@{tf}: n={len(ra_f)}")
        print(f"  dominant period ({sym_a}): {dom_a['dominant_period_global']:.1f} bars")
        print(f"  dominant period ({sym_b}): {dom_b['dominant_period_global']:.1f} bars")
        print(f"  mean rolling PLV (window={args.plv_window}): {np.nanmean(plv):.3f}")

        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "tf": tf, "n_bars": len(ra_f),
            "dominant_period_a": dom_a["dominant_period_global"],
            "dominant_period_b": dom_b["dominant_period_global"],
            "mean_plv": float(np.nanmean(plv)),
        })

    cross_tf_rows = []
    if rows:
        by_pair = {}
        for r in rows:
            by_pair.setdefault((r["symbol_a"], r["symbol_b"]), []).append(r)
        for pair, entries in by_pair.items():
            if len(entries) < 2:
                continue
            # Every pairwise TF combination this pair is confirmed at, not
            # just the first two (dynamic pair discovery can surface a pair
            # confirmed at 3+ TFs).
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    e0, e1 = entries[i], entries[j]
                    cons = cross_timeframe_consistency(
                        e0["dominant_period_a"], e0["tf"], e1["dominant_period_a"], e1["tf"]
                    )
                    print(f"\nCross-TF consistency, {pair[0]} dominant cycle, {e0['tf']} vs {e1['tf']}: {cons}")
                    cross_tf_rows.append({"symbol_a": pair[0], "symbol_b": pair[1],
                                           "tf_a": e0["tf"], "tf_b": e1["tf"], **cons})

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
    os.makedirs(out_dir, exist_ok=True)
    if rows:
        pd.DataFrame(rows).to_parquet(os.path.join(out_dir, "cycle_detection.parquet"))
        print(f"\nResults written to output/research/cycle_detection.parquet")
        if cross_tf_rows:
            pd.DataFrame(cross_tf_rows).to_parquet(os.path.join(out_dir, "cycle_detection_cross_tf.parquet"))
            print(f"Cross-TF consistency written to output/research/cycle_detection_cross_tf.parquet")
    else:
        print("\nNo pairs produced usable output — nothing written.")


if __name__ == "__main__":
    main()
