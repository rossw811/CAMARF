"""
research/intraday_episodic_window_sensitivity.py -- Step 1 of the PIT-safe
episodic pair-confirmation comparison-arm plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

Directly answers Ross's "we should change the 200 bars and run an actual
test to see what value makes a valid relationship... that goes for any and
all hardcoded values" request. Rather than picking a new intraday episodic
window/step size by guessing, this registers 4 candidate configs, each
derived from an EXISTING production convention (not a new guessed
constant), and evaluates them against real intraday data with two metrics
stated up front, not chosen post-hoc.

Candidate configs:
  fixed_min_overlap_1x -- window = Config.STATS.MIN_OVERLAP_BY_TF[tf], step = window/4
  fixed_min_overlap_2x -- window = 2x that floor, step = window/4
  adaptive_halflife_8x -- per-pair window via SpreadModel._adaptive_window
                          (mult=8, same convention production already uses
                          for z-score/half-life estimation), step = window/4
  onset_anchored        -- window(s) anchored at
                          structural_break_onset_detection.find_all_breaks's
                          detected onset date(s), window length = config 1's

Evaluation metrics, stated up front (not picked post-hoc):
  (a) confirmed-pair-count stability -- coefficient of variation of
      n_confirmed (via episodic_bhfdr_confirm, imported unchanged from
      research/wrds_deep_history_episodic_scan.py) across 3 small (+/-15%)
      perturbations of the config's window/step, over a small candidate
      pair set (the 3 currently standard-confirmed pairs' symbols, at 1h
      and 4h). A config is "fragile" if small perturbations swing the
      confirmed count a lot.
  (b) contiguity -- for PNC/ZION specifically (the one pair with
      unambiguous standard-screen confirmation to sanity-check against),
      the fraction of significant (p<0.05) windows that fall in a run of
      length >= 2 (ordered by window_start). This is the direct analogue
      of the already-diagnosed MIN_SEGMENT_BARS=200 bug in
      structural_break_onset_detection.py (KVUE/KMB@3m showed 9 "breaks"
      in a couple months -- noise, not real regime change, because 200
      bars at 3m is only a few days). A config picking up mostly ISOLATED
      significant windows (low contiguity) is behaving like that bug; a
      config finding long contiguous stretches is finding real regime
      structure, not noise.

This script does NOT pick a winner -- it prints/writes both metrics per
config in a table. Step 6's write-up (docs/FINDINGS.md) states the choice
from these real numbers, per this project's own comparison-arm discipline.

Synthetic verification FIRST: debug/_verify_intraday_episodic_window_sensitivity.py
-- run that before trusting this script's real-data output.

Usage:
    python research/intraday_episodic_window_sensitivity.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore
from analysis import _eg_worker, SpreadModel
from research.wrds_deep_history_episodic_scan import episodic_bhfdr_confirm
from research.structural_break_onset_detection import find_all_breaks, compute_ols_spread

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

# The 3 currently standard-confirmed pairs' symbols -- a small, fast,
# already-relevant candidate set for this sensitivity test (Step 2's real
# scanner is the full-universe job; this is a config-selection tool, kept
# deliberately small and fast).
CANDIDATE_PAIRS = [("PNC", "ZION"), ("KVUE", "KMB"), ("IQV", "Q")]
CANDIDATE_TFS = ["1h", "4h"]
MAX_LAG = 1
ALPHA = 0.05
PNC_ZION = ("PNC", "ZION")  # the contiguity sanity-check pair


def load_aligned_log_prices(sym_a: str, sym_b: str, tf_label: str):
    """Returns (dates, log_a, log_b) aligned on the union of both symbols'
    cached index, NaN where either is missing (_eg_worker's own gap-
    respecting segment logic handles that, same as production)."""
    df_a = DataStore.load(sym_a, tf_label)
    df_b = DataStore.load(sym_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None, None, None
    idx = df_a.index.union(df_b.index).sort_values()
    close_a = df_a["close"].reindex(idx)
    close_b = df_b["close"].reindex(idx)
    with np.errstate(invalid="ignore", divide="ignore"):
        log_a = np.log(close_a.to_numpy(dtype=float))
        log_b = np.log(close_b.to_numpy(dtype=float))
    return idx, log_a, log_b


def rolling_pvalue_rows(sym_a, sym_b, log_a, log_b, dates, window, step, starts=None, min_bars=60):
    """Serial rolling EG-both-directions scan (small candidate set, no
    process pool needed here -- Step 2's real scanner uses the pooled
    version for full-universe scale). Mirrors
    wrds_deep_history_episodic_scan.episodic_fraction's serial-loop
    pattern, but keeps per-window dates/pvalues (not just the fraction),
    and accepts an explicit `starts` list for the onset_anchored config.

    For explicit `starts` (onset_anchored): a window anchored at a REAL
    detected break near the end of available data won't have `window`
    full bars remaining -- clip to what's actually available (mirroring
    structural_break_onset_detection.find_all_breaks's own
    `end = min(start + window, n)` pattern) rather than silently
    dropping every onset near the series end. Only accept if the clipped
    segment still clears `min_bars` (_eg_worker's own floor below which
    it refuses, n_overlap < 60) -- a 5-bar clipped window would be
    statistically meaningless, not just short.
    For the regular grid (`starts=None`), the fixed-length range already
    guarantees every window fits, so this clipping never triggers there."""
    n = len(log_a)
    if starts is None:
        if n < window:
            return []
        starts = list(range(0, n - window + 1, step))
    rows = []
    for start in starts:
        end = min(start + window, n)
        if end - start < min_bars:
            continue
        seg_a, seg_b = log_a[start:end], log_b[start:end]
        r_ab = _eg_worker((sym_a, sym_b, seg_a, seg_b, MAX_LAG, "1D"))
        r_ba = _eg_worker((sym_b, sym_a, seg_b, seg_a, MAX_LAG, "1D"))
        if not (r_ab.get("ok") and r_ba.get("ok")):
            continue
        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b,
            "window_start": start,
            "pvalue": max(r_ab["pvalue"], r_ba["pvalue"]),
            "window_end_date": dates[end - 1],
        })
    return rows


def config_fixed_min_overlap(tf_label, mult, **_):
    base = Config.STATS.MIN_OVERLAP_BY_TF.get(tf_label, 252)
    window = int(mult * base)
    step = max(1, window // 4)
    return window, step


def config_adaptive_halflife(tf_label, log_a, log_b, **_):
    base = Config.STATS.MIN_OVERLAP_BY_TF.get(tf_label, 252)
    spread = compute_ols_spread(log_a, log_b)
    valid = spread[np.isfinite(spread)]
    # Rough half-life proxy from AR(1) on the full-sample spread -- this
    # config's whole point is per-pair adaptivity, but the sensitivity
    # test only needs a representative window LENGTH, not a full causal
    # per-bar half-life series (that's SpreadModel.fit_pair's job in
    # production; here we just need one number to feed
    # SpreadModel._adaptive_window, the actual reused convention).
    if valid.size >= 10:
        lag = valid[:-1] - valid[:-1].mean()
        now = valid[1:] - valid[1:].mean()
        denom = np.dot(lag, lag)
        phi = np.dot(lag, now) / denom if denom > 0 else np.nan
        half_life = -np.log(2) / np.log(abs(phi)) if 0 < abs(phi) < 1 else np.nan
    else:
        half_life = np.nan
    window = SpreadModel._adaptive_window(half_life, mult=8, min_bars=base, max_bars=2 * base)
    step = max(1, window // 4)
    return window, step


def config_onset_anchored(tf_label, log_a, log_b, dates, **_):
    window, _step = config_fixed_min_overlap(tf_label, mult=1.0)
    spread = compute_ols_spread(log_a, log_b)
    min_segment = max(200, min(window, Config.STATS.MIN_OVERLAP_BY_TF.get(tf_label, 252) // 4))
    breaks = find_all_breaks(spread, dates, min_segment_bars=min_segment)
    if not breaks:
        return window, None  # signal: no onset detected, caller falls back to fixed starts
    onset_positions = []
    valid = np.isfinite(spread)
    valid_dates = dates[valid]
    for b in breaks:
        pos = valid_dates.get_indexer([b["break_date"]])[0]
        if pos >= 0:
            onset_positions.append(int(pos))
    return window, onset_positions


REGISTRY = {
    "fixed_min_overlap_1x": lambda tf, log_a, log_b, dates: config_fixed_min_overlap(tf, mult=1.0),
    "fixed_min_overlap_2x": lambda tf, log_a, log_b, dates: config_fixed_min_overlap(tf, mult=2.0),
    "adaptive_halflife_8x": lambda tf, log_a, log_b, dates: config_adaptive_halflife(tf, log_a, log_b),
    "onset_anchored": lambda tf, log_a, log_b, dates: config_onset_anchored(tf, log_a, log_b, dates),
}


def run_config_on_pair(config_name, sym_a, sym_b, tf_label, dates, log_a, log_b, window_override=None):
    fn = REGISTRY[config_name]
    window, step_or_starts = fn(tf_label, log_a, log_b, dates)
    if window_override is not None:
        window = window_override
    n = len(log_a)
    if config_name == "onset_anchored":
        starts = step_or_starts if step_or_starts else list(range(0, max(1, n - window), max(1, window // 4)))
        return rolling_pvalue_rows(sym_a, sym_b, log_a, log_b, dates, window, None, starts=starts)
    step = step_or_starts if not window_override else max(1, window // 4)
    return rolling_pvalue_rows(sym_a, sym_b, log_a, log_b, dates, window, step)


def contiguity_fraction(rows):
    """Fraction of significant (p<0.05) windows, ordered by window_start,
    that fall in a run of length >= 2. NaN if no significant windows."""
    if not rows:
        return float("nan")
    ordered = sorted(rows, key=lambda r: r["window_start"])
    sig = [r["pvalue"] < ALPHA for r in ordered]
    n_sig = sum(sig)
    if n_sig == 0:
        return float("nan")
    in_run = 0
    for i, s in enumerate(sig):
        if not s:
            continue
        prev_sig = i > 0 and sig[i - 1]
        next_sig = i < len(sig) - 1 and sig[i + 1]
        if prev_sig or next_sig:
            in_run += 1
    return in_run / n_sig


def evaluate_config(config_name, pairs_data):
    """pairs_data: {(sym_a, sym_b): (dates, log_a, log_b)}. Returns dict of
    metrics for this config across the candidate set."""
    base_rows_all = []
    per_pair_base_window = {}
    for (sym_a, sym_b), (dates, log_a, log_b) in pairs_data.items():
        rows = run_config_on_pair(config_name, sym_a, sym_b, "1h", dates, log_a, log_b)
        base_rows_all.extend(rows)
        fn = REGISTRY[config_name]
        w, _ = fn("1h", log_a, log_b, dates)
        per_pair_base_window[(sym_a, sym_b)] = w

    base_confirmed = episodic_bhfdr_confirm(base_rows_all, ALPHA, min_windows_confirmed=1)
    n_base_confirmed = len(base_confirmed)

    perturbation_counts = [n_base_confirmed]
    for factor in (0.85, 1.15):
        pert_rows_all = []
        for (sym_a, sym_b), (dates, log_a, log_b) in pairs_data.items():
            w_base = per_pair_base_window[(sym_a, sym_b)]
            w_pert = max(30, int(round(w_base * factor)))
            rows = run_config_on_pair(config_name, sym_a, sym_b, "1h", dates, log_a, log_b, window_override=w_pert)
            pert_rows_all.extend(rows)
        confirmed = episodic_bhfdr_confirm(pert_rows_all, ALPHA, min_windows_confirmed=1)
        perturbation_counts.append(len(confirmed))

    counts = np.array(perturbation_counts, dtype=float)
    cv = float(np.std(counts) / counts.mean()) if counts.mean() > 0 else float("nan")

    pnc_zion_rows = [r for r in base_rows_all if (r["symbol_a"], r["symbol_b"]) == PNC_ZION
                     or (r["symbol_b"], r["symbol_a"]) == PNC_ZION]
    contiguity = contiguity_fraction(pnc_zion_rows)

    return {
        "config": config_name,
        "n_base_confirmed": n_base_confirmed,
        "perturbation_counts": perturbation_counts,
        "cv_confirmed_count": cv,
        "pnc_zion_n_windows": len(pnc_zion_rows),
        "pnc_zion_contiguity": contiguity,
    }


def main():
    pairs_data = {}
    for sym_a, sym_b in CANDIDATE_PAIRS:
        dates, log_a, log_b = load_aligned_log_prices(sym_a, sym_b, "1h")
        if dates is None:
            print(f"SKIP {sym_a}/{sym_b}@1h: missing cache")
            continue
        pairs_data[(sym_a, sym_b)] = (dates, log_a, log_b)

    if not pairs_data:
        print("No candidate pairs have cached 1h data -- aborting.")
        return pd.DataFrame()

    results = [evaluate_config(name, pairs_data) for name in REGISTRY]
    result_df = pd.DataFrame(results)

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "intraday_episodic_window_sensitivity.parquet")
    result_df.to_parquet(out_path)

    print(result_df.to_string(index=False))
    print(f"Wrote {out_path}")
    return result_df


if __name__ == "__main__":
    main()
