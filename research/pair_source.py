"""
research/pair_source.py -- single source of truth for "which pairs should a
research/diagnostic script run against," replacing per-script hardcoded
ticker lists (Ross's direction 2026-08-24: "we shouldn't be hardcoding
anything... everything should be using either the full universe or the
confirmed pairs" -- a codebase-wide grep found ~20 research/*.py scripts
carrying a hand-picked pair list, 12 of them the exact same copy-pasted
9-pair set, none of them re-derived when the confirmed-pair population
changes).

Two real populations, both read from analysis.py's own production output,
never invented here:
  - load_confirmed_pairs(): output/results/*/pairs.parquet -- the EG+FDR
    (+ price-degeneracy) survivors, i.e. CAMARF's actual current confirmed
    pair set. Use for any script whose question is "does X hold for pairs
    CAMARF has actually confirmed."
  - load_candidate_pairs(): output/results/*/all_candidates.parquet -- the
    broader EG+FDR+price-degeneracy candidate population (BUG-D95's fix is
    what makes this populated for every timeframe, not just final
    survivors). Use for a script that wants a larger population than the
    (often thin) confirmed set.

Both skip any "_stale_" results dir (a superseded run), matching the
convention already used by bayesian_pair_confirmation.py and
strategy_variation_comparison.py -- this module replaces those scripts'
private duplicate copies of the same glob/concat logic, not just the
pair-list callers.

Out of scope: the FULL asset universe (every symbol CAMARF tracks, not just
paired-up candidates) is universe_loader.py's job, not this module's --
this module is specifically about PAIR selection.
"""
import glob
import os

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")


def _load_glob(pattern: str) -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(os.path.join(_RESULTS_DIR, "*", pattern))):
        if "_stale_" in f:
            continue
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if df.empty:
            continue
        df["_source_dir"] = os.path.basename(os.path.dirname(f))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_confirmed_pairs() -> pd.DataFrame:
    """All rows from every non-stale output/results/*/pairs.parquet -- CAMARF's
    actual current confirmed-pair population, across every timeframe."""
    return _load_glob("pairs.parquet")


def load_candidate_pairs() -> pd.DataFrame:
    """All rows from every non-stale output/results/*/all_candidates.parquet --
    the broader EG+FDR+price-degeneracy survivor population (BUG-D95)."""
    return _load_glob("all_candidates.parquet")


def confirmed_pairs_list(tf_label: str = None) -> list:
    """[(symbol_a, symbol_b), ...] deduped, sorted -- for scripts that only
    need the pair identity, not the full confirmed-pairs metadata. Pass
    tf_label to restrict to pairs confirmed at that specific timeframe (a
    pair confirmed at 1h is not necessarily confirmed at 1D -- filtering by
    tf is causally correct behavior a flat hardcoded list could never do)."""
    df = load_confirmed_pairs()
    if df.empty:
        return []
    if tf_label is not None and "tf_label" in df.columns:
        df = df[df["tf_label"] == tf_label]
    if "symbol_a" not in df.columns or "symbol_b" not in df.columns:
        return []
    return sorted(set(zip(df["symbol_a"], df["symbol_b"])))


def candidate_pairs_list(tf_label: str = None) -> list:
    """Same as confirmed_pairs_list() but drawn from the broader candidate
    population (all_candidates.parquet) instead of final confirmed pairs."""
    df = load_candidate_pairs()
    if df.empty:
        return []
    if tf_label is not None and "tf_label" in df.columns:
        df = df[df["tf_label"] == tf_label]
    if "symbol_a" not in df.columns or "symbol_b" not in df.columns:
        return []
    return sorted(set(zip(df["symbol_a"], df["symbol_b"])))
