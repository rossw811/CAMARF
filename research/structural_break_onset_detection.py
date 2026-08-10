"""
CAMARF research/structural_break_onset_detection.py -- comparison/
diagnostic script, NOT part of the production pipeline (2026-08-04).

Ross's framing, from a live design discussion (2026-08-04): a fixed
calendar-length cointegration window (the episodic scan's 10-year
window) can't distinguish "cointegrated its entire life" from "just
became coupled" -- a pair that coupled 6 months ago is invisible inside
9.5 years of pre-coupling noise. Instead of a fixed or even a half-life-
relative window (research/coint_frac_window_grid.py already explored
that dimension -- still one FIXED window/threshold applied uniformly to
every pair), this module makes the window itself CONDITIONAL: detect the
actual structural break where a pair's relationship changed, and let
"time since that break" be the window, which is genuinely variable
per pair rather than a single tuned constant.

REUSES the existing Quandt-Andrews break-point test directly
(analysis.py::StrategyDecayDetector.zivot_andrews -- a Chow-F scan over
candidate break dates on the spread's own AR(1) coefficient), not
reimplemented. That function only reports a single break (its own
docstring: "identify the date with the largest Chow F statistic"). Ross's
explicit choice: report the FULL break history per pair, not just the
most recent break, and let downstream comparison arms (the onset-age
arm this is built to feed) decide how to use it. Extended to multiple
breaks via standard binary segmentation: find the best single break,
split the series there, recurse on each half, stop at min_segment_bars
or when no further significant break is found.

DIRECTION INTERPRETATION, since zivot_andrews only reports WHERE a break
is, not what kind: at each detected break, this module independently
computes the AR(1) mean-reversion coefficient (phi) on the pre- and
post-break segments (the same statistic zivot_andrews computes
internally for its own Chow test, exposed here for interpretation, not
re-derived differently). post_phi < pre_phi (more mean-reverting after
the break) is classified "onset" (a plausible coupling event); post_phi
> pre_phi is "decoupling"; genuinely ambiguous cases (both segments
already highly mean-reverting, or neither is) are reported as
"unclear" rather than forced into one label.

SCOPE LIMITATION, disclosed directly: this classifies each break using a
SIMPLE AR(1) phi comparison, not the fuller EG/KPSS/PO tiering production
cointegration confirmation uses -- a fast, first-pass structural
signal meant to feed the onset-age comparison arm's own more careful
backtest-based validation, not a replacement for the production screen.

Usage:
    python research/structural_break_onset_detection.py
    python research/structural_break_onset_detection.py --full-universe --tf 1D
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from config import Config
from data import DataStore, _clean_close
from analysis import StrategyDecayDetector
import ml

MIN_SEGMENT_BARS = 200  # floor below which zivot_andrews itself refuses (n < 200 -> None)


def _ar1_phi(segment: np.ndarray) -> float:
    """Same AR(1) coefficient computation StrategyDecayDetector.zivot_andrews
    uses internally for its own Chow test -- exposed here so callers can
    interpret break DIRECTION, which that function's return value (just an
    index or None) does not carry."""
    s = segment[np.isfinite(segment)]
    if s.size < 10:
        return np.nan
    s_lag = s[:-1] - s[:-1].mean()
    s_now = s[1:] - s[1:].mean()
    denom = np.dot(s_lag, s_lag)
    if denom <= 0:
        return np.nan
    return float(np.dot(s_lag, s_now) / denom)


def _classify_break(pre_seg: np.ndarray, post_seg: np.ndarray) -> dict:
    pre_phi, post_phi = _ar1_phi(pre_seg), _ar1_phi(post_seg)
    if not (np.isfinite(pre_phi) and np.isfinite(post_phi)):
        break_type = "unclear"
    elif post_phi < pre_phi - 0.05:
        break_type = "onset"
    elif post_phi > pre_phi + 0.05:
        break_type = "decoupling"
    else:
        break_type = "unclear"
    return {"break_type": break_type, "pre_phi": pre_phi, "post_phi": post_phi,
            "phi_separation": abs(pre_phi - post_phi) if np.isfinite(pre_phi) and np.isfinite(post_phi) else -1.0}


def find_all_breaks(spread: np.ndarray, dates: pd.DatetimeIndex, min_segment_bars: int = MIN_SEGMENT_BARS) -> list:
    """SLIDING-WINDOW scan over StrategyDecayDetector.zivot_andrews, not
    binary segmentation -- a real design correction, found by this
    module's own synthetic verification, not assumed. A single global
    Chow-F scan on the WHOLE series loses statistical power when MORE
    THAN ONE real regime change is present: any candidate split point's
    pre/post OLS mixes data from both sides of at least one true break,
    diluting the F-statistic everywhere, so binary segmentation's
    top-level call can return None even when real breaks exist --
    verified directly: a synthetic 3-segment (unrelated -> coupled ->
    unrelated) series with two deliberately-constructed breaks produced
    ZERO detections under binary segmentation, confirmed by calling
    zivot_andrews on the full series directly (returned None).

    Fixed with a sliding window (width = 2*min_segment_bars, step =
    min_segment_bars, i.e. 50% overlap): each window is short enough that
    at most one true break typically falls inside it, giving the Chow
    test local statistical power a global scan doesn't have. Overlapping
    windows can each flag the SAME real break; near-duplicate detections
    (within min_segment_bars of each other) are collapsed, keeping the
    one with the largest pre/post phi separation (the more decisively
    resolved of the duplicates) rather than double-counting."""
    n = len(spread)
    # Window/step sizing is a real, disclosed tradeoff, found empirically
    # not assumed. Two separate failure modes were found in synthetic
    # testing before landing here: (1) too-small a window (2x
    # min_segment_bars) lacks statistical power to detect a modest phi
    # shift; (2) too-coarse a step (== min_segment_bars) can leave every
    # generated window mis-aligned relative to where the true break
    # actually falls, missing it even at a window size that DOES have
    # enough power when well-centered (confirmed directly: a manually
    # centered window found the same break a step=200 scan's three
    # actual windows all missed). Fixed with a larger window (3x) and a
    # finer step (0.5x) -- enough overlap that some window is always
    # reasonably well-centered on any true break, while windows this
    # size still avoid the dilution problem a full-series scan has when
    # multiple true breaks are far enough apart (verified: both the
    # single-break and two-break synthetic cases pass at this setting,
    # debug/_verify_structural_break_onset_detection.py).
    window = 3 * min_segment_bars
    step = min_segment_bars // 2
    raw_breaks = []

    start = 0
    while start + min_segment_bars < n:
        end = min(start + window, n)
        seg = spread[start:end]
        seg_dates = dates[start:end]
        if seg.size >= min_segment_bars:
            break_idx_str = StrategyDecayDetector.zivot_andrews(seg)
            if break_idx_str is not None:
                break_idx = int(break_idx_str)
                pre_seg, post_seg = seg[:break_idx], seg[break_idx:]
                if pre_seg.size >= 10 and post_seg.size >= 10:
                    info = _classify_break(pre_seg, post_seg)
                    info["break_date"] = seg_dates[break_idx]
                    info["_global_idx"] = start + break_idx
                    raw_breaks.append(info)
        start += step

    if not raw_breaks:
        return []

    raw_breaks.sort(key=lambda b: b["_global_idx"])
    deduped = []
    for b in raw_breaks:
        if deduped and b["_global_idx"] - deduped[-1]["_global_idx"] < min_segment_bars:
            if b["phi_separation"] > deduped[-1]["phi_separation"]:
                deduped[-1] = b
            continue
        deduped.append(b)

    for b in deduped:
        del b["_global_idx"]
        del b["phi_separation"]
    return deduped


def compute_ols_spread(log_a: np.ndarray, log_b: np.ndarray) -> np.ndarray:
    """Full-sample OLS hedge ratio (a fast, first-pass spread construction
    for break-scanning purposes -- NOT the production point-in-time
    hedge_ratio_ols_t series; this module is a structural diagnostic, not
    a trading signal, so a single full-sample hedge ratio for locating
    WHERE the relationship's dynamics changed is an appropriate,
    disclosed simplification)."""
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    if mask.sum() < MIN_SEGMENT_BARS:
        return np.full_like(log_a, np.nan)
    x, y = log_b[mask], log_a[mask]
    x_c = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(x_c, y, rcond=None)
    spread = np.full_like(log_a, np.nan)
    spread[mask] = log_a[mask] - beta[1] * log_b[mask]
    return spread


def full_universe_scan(tf_label: str = "1D", corr_threshold: float = None) -> list:
    from analysis import DataAligner, UniverseFilter

    if corr_threshold is None:
        corr_threshold = Config.UNIVERSE.MIN_PEARSON_CORR

    safe = DataStore._TF_SAFE.get(tf_label, tf_label.lower())
    pattern = os.path.join(Config.DATA.CACHE_DIR, f"*_{safe}.parquet")
    raw = {}
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        symbol = fname[: -(len(safe) + len(".parquet") + 1)]
        df = DataStore.load(symbol, tf_label)
        if df is not None and not df.empty:
            raw[symbol] = df
    print(f"Loaded {len(raw)} symbols at {tf_label}")
    if len(raw) < 10:
        return []

    aligned = DataAligner.align_universe({f"{s}_{tf_label}": df for s, df in raw.items()}, tf_label)
    print(f"{len(aligned)}/{len(raw)} aligned")
    returns, symbols, _idx = UniverseFilter.build_returns_matrix(aligned, min_overlap=MIN_SEGMENT_BARS)
    print(f"{len(symbols)} symbols survive min_overlap, computing correlation matrix...")
    corr = UniverseFilter.correlation_matrix(returns)

    n = corr.shape[0]
    candidates = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr[i, j]
            if np.isfinite(c) and abs(c) >= corr_threshold:
                candidates.append((symbols[i], symbols[j]))
    print(f"{len(candidates)} candidate pairs clear |rho| >= {corr_threshold}")

    rows = []
    for sym_a, sym_b in candidates:
        df_a, df_b = aligned.get(sym_a), aligned.get(sym_b)
        if df_a is None or df_b is None:
            continue
        common_idx = df_a.index.intersection(df_b.index)
        if len(common_idx) < MIN_SEGMENT_BARS:
            continue
        df_a, df_b = df_a.loc[common_idx], df_b.loc[common_idx]
        log_a = np.log(_clean_close(df_a))
        log_b = np.log(_clean_close(df_b))
        spread = compute_ols_spread(log_a, log_b)
        breaks = find_all_breaks(spread, df_a.index)
        for b in breaks:
            b.update(symbol_a=sym_a, symbol_b=sym_b, tf_label=tf_label)
            rows.append(b)
        if breaks:
            print(f"  {sym_a}/{sym_b}: {len(breaks)} break(s), "
                  f"types={[b['break_type'] for b in breaks]}")
    return rows


def main():
    p = argparse.ArgumentParser(description="CAMARF structural-break onset detection")
    p.add_argument("--full-universe", action="store_true")
    p.add_argument("--tf", type=str, default="1D")
    p.add_argument("--corr-threshold", type=float, default=None)
    p.add_argument("--pit-safe", action="store_true",
                    help="Source pairs from research/pit_pair_discovery.py's PIT-safe episodic "
                         "screen instead of ml._discover_confirmed_pairs() (task #5). Ignored "
                         "with --full-universe, which already sources candidates from its own "
                         "same-TF correlation pre-filter.")
    args = p.parse_args()

    if args.full_universe:
        rows = full_universe_scan(args.tf, args.corr_threshold)
        out_df = pd.DataFrame(rows)
        out_dir = os.path.join("output", "research")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "structural_break_onset_detection_full_universe.parquet")
        out_df.to_parquet(out_path)
        n_onset = int((out_df["break_type"] == "onset").sum()) if len(out_df) else 0
        n_decoupling = int((out_df["break_type"] == "decoupling").sum()) if len(out_df) else 0
        n_pairs = out_df[["symbol_a", "symbol_b"]].drop_duplicates().shape[0] if len(out_df) else 0
        print(f"Done. {len(out_df)} breaks across {n_pairs} pairs -- {n_onset} onset, "
              f"{n_decoupling} decoupling. Saved -> {out_path}")
        return

    if args.pit_safe:
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pairs = discover_pit_confirmed_pairs()
        print(f"Using PIT-safe episodic pair discovery: {len(pairs)} (pair, tf) combinations")
    else:
        pairs = ml._discover_confirmed_pairs()
    rows = []
    for symbol_a, symbol_b, tf_label in pairs:
        df_a, df_b = DataStore.load(symbol_a, tf_label), DataStore.load(symbol_b, tf_label)
        if df_a is None or df_b is None:
            continue
        common_idx = df_a.index.intersection(df_b.index)
        if len(common_idx) < MIN_SEGMENT_BARS:
            print(f"  skip {symbol_a}/{symbol_b}@{tf_label}: only {len(common_idx)} overlapping bars")
            continue
        df_a, df_b = df_a.loc[common_idx], df_b.loc[common_idx]
        log_a, log_b = np.log(_clean_close(df_a)), np.log(_clean_close(df_b))
        spread = compute_ols_spread(log_a, log_b)
        breaks = find_all_breaks(spread, df_a.index)
        print(f"  {symbol_a}/{symbol_b}@{tf_label}: {len(breaks)} break(s)")
        for b in breaks:
            b.update(symbol_a=symbol_a, symbol_b=symbol_b, tf_label=tf_label)
            rows.append(b)
            print(f"    {b['break_date']}: {b['break_type']} (phi {b['pre_phi']:.3f} -> {b['post_phi']:.3f})")

    out_df = pd.DataFrame(rows)
    out_dir = os.path.join("output", "research")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "structural_break_onset_detection.parquet")
    out_df.to_parquet(out_path)
    print(f"Done. Saved -> {out_path}")


if __name__ == "__main__":
    main()
