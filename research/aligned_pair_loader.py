"""
CAMARF aligned_pair_loader.py — shared utility, NOT part of the
production pipeline (but exists specifically to make exploratory/
comparison scripts match production's convention).

Built 2026-06-24 after discovering that every comparison script this
session (lead_lag_scan.py, copula_pairs.py, lead_lag_permutation_check.py,
near_miss_lag_scan.py) and two from Session 10 (eg_permutation_check.py,
tail_dependence.py) called _gap_aware_returns()/_clean_close() directly
on DataStore.load()'s raw output. Raw per-symbol cache files have NO
gap_flag column at all — it is only added by DataAligner, which
production analysis.py ALWAYS runs first (AnalysisPipeline._run_one_tf,
"Step 2: align to NYSE master calendar"). Without it, _gap_aware_returns
silently skips ALL masking and treats the return spanning the overnight/
weekend gap as an ordinary one-bar return, identical in kind to a real
intraday step. Verified directly on CATY/UCB @1h: including that single
overnight-spanning return per session pushes the correlation from 0.558
(excluded, matching production's convention) to 0.730 (included) — a
large, not a cosmetic, effect, because overnight/weekend gap-driven
moves are far more cross-sectionally correlated (market-wide news) than
intraday moves are. See Development.md Session 11 for the full account.

This does NOT change calendar alignment (raw-cache joins by real
DatetimeIndex were never miscalibrated that way) — it changes which
RETURNS get included, to match the GapFlag system's actual design
intent (align_intraday builds a dense per-symbol grid specifically so
the overnight span gets flagged and the return crossing it excluded).

REVERTED same day: briefly passed drop_data_gap_rows=True here, then
reverted after direct verification showed it silently breaks
_gap_aware_returns' OWN masking mechanism — that function identifies
"the return spanning a gap" by checking gap_flag at the CURRENT and
PREVIOUS row position; once DATA_GAP rows are removed, the first real
bar after a gap becomes positionally adjacent to the last real bar
before it with no marker between them, so the function can no longer
tell that return crosses a multi-hour gap and stops masking it.
Verified directly: CATY/UCB@1h correlation reverted from the correct
0.5577 back to the wrong 0.7304 the instant this was enabled — the
exact bug this module exists to fix, reopened through a different
mechanism. Fixing this properly needs _gap_aware_returns/_clean_close
to ALSO check the real time gap between surviving rows (not just
gap_flag at each position) before any row-dropping can be safe — a
separate, not-yet-built fix. drop_data_gap_rows stays available on
DataAligner (default False, unused by this module for now) for if/when
that fix lands.

Usage (drop-in replacement for `DataStore.load(symbol, tf_label)` when
you need a SINGLE pair's two legs on the production-matching
convention):
    from aligned_pair_loader import load_aligned_pair
    df_a, df_b = load_aligned_pair("CATY", "UCB", "1h")
    # df_a, df_b now have a gap_flag column; _gap_aware_returns/_clean_close
    # will mask DATA_GAP-spanning returns exactly as production does.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import DataAligner, DataStore

# Shared timeframe-directory constants and stale-directory fallback resolver
# (added 2026-07-05). Previously copy-pasted near-verbatim into ~9 separate
# research/*.py comparison scripts (threshold_cointegration.py,
# variance_ratio_test.py, news_impact_asymmetry.py, grid_bootstrap_ar_ci.py,
# bertram_ou_thresholds.py, reimers_trio_correction.py, kalman_slope_
# intercept.py, dd_hub_effective_bets.py, rmt_feature_denoising.py) — found
# by a 2026-07-05 code review (three independent angles flagged it
# separately) and consolidated here, the codebase's existing precedent for
# shared research/ utilities, rather than left duplicated. One copy had
# already drifted (dd_hub_effective_bets.py's local version returned a bare
# path instead of the (path, is_stale) tuple every other copy used).
TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def resolve_tf_results_dir(tf_dir):
    """output/results/{tf_dir} if it exists; otherwise the most recent
    output/results/{tf_dir}_stale_* archive directory. See
    threshold_cointegration.py's original docstring (Session 27) for the
    full account of why "_stale_" just means "superseded by a scoped
    rerun's archiving step," not "known-bad data." Returns (path, is_stale).
    """
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return live, False
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    return (candidates[-1], True) if candidates else (live, False)


def align_pair_dataframes(symbol_a, df_a, symbol_b, df_b, tf_label):
    """Run two ALREADY-LOADED dataframes through DataAligner.align_universe
    together. Factored out of load_aligned_pair so callers with a non-
    DataStore source (e.g. an IBKR-supplement-merged series, which also
    has no gap_flag column) can get the same treatment — align_intraday
    doesn't require a pre-existing gap_flag, it computes one fresh by
    reindexing onto a dense grid, so this works regardless of source.
    Returns (aligned_a, aligned_b), either may be None."""
    raw = {}
    if df_a is not None and not df_a.empty:
        raw[symbol_a] = df_a
    if df_b is not None and not df_b.empty:
        raw[symbol_b] = df_b
    if not raw:
        return None, None

    aligned = DataAligner.align_universe(
        {f"{sym}_{tf_label}": df for sym, df in raw.items()}, tf_label
    )
    return aligned.get(symbol_a), aligned.get(symbol_b)


def load_aligned_pair(symbol_a, symbol_b, tf_label):
    """Load both legs via DataStore and run them through
    DataAligner.align_universe together, exactly mirroring analysis.py's
    own Step 2. Returns (df_a, df_b), either of which may be None if that
    symbol has no cached data or fails alignment."""
    df_a = DataStore.load(symbol_a, tf_label)
    df_b = DataStore.load(symbol_b, tf_label)
    return align_pair_dataframes(symbol_a, df_a, symbol_b, df_b, tf_label)


def load_aligned_symbols(symbols, tf_label):
    """N-way generalization of load_aligned_pair, for trio/basket comparison
    scripts (added 2026-07-05 — research/reimers_trio_correction.py needed a
    3-symbol version of exactly this gap-flag-aware alignment and was instead
    calling bare DataStore.load() directly with no gap_flag masking at all,
    the same calendar-padding failure mode this module exists to prevent for
    the 2-symbol case). Returns {symbol: aligned_df}; a symbol is absent from
    the result if it has no cached data or fails alignment."""
    raw = {}
    for sym in symbols:
        df = DataStore.load(sym, tf_label)
        if df is not None and not df.empty:
            raw[sym] = df
    if not raw:
        return {}
    aligned = DataAligner.align_universe(
        {f"{sym}_{tf_label}": df for sym, df in raw.items()}, tf_label
    )
    return {sym: aligned.get(sym) for sym in raw}
