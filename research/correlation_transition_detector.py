"""
research/correlation_transition_detector.py -- Phase 1 of the discovery-
event/no-correlation-signal research program (2026-09-03, scoped with Ross:
"combine no-correlations for a signal" / "combine with correlated for
signals", both selected as "extend the decoupling pipeline" + "correlation-
regime TRANSITIONS as the signal", to be tested via with/without comparison
arms to find optimal parameters -- this script builds the foundational
transition table those comparisons need; it is NOT itself a signal or a
backtest).

A correlation-regime TRANSITION is simply the boundary between two
consecutive spans for the same pair in `cointegration_regime_segments.
parquet` (§7.2's output, already-verified hysteresis-based span
segmentation -- reused directly, no new statistical test): a
"coint" -> "not_coint" boundary is DECOUPLING (the existing decoupling_
analysis.py/decoupling_requalification.py/decoupling_backtest.py chain
already studies exactly this direction, treating it purely as an exclusion
event); a "not_coint" -> "coint" boundary is RECOUPLING (the reverse
direction, not previously catalogued anywhere in this project). This
script generalizes to BOTH directions and, new relative to the existing
decoupling chain, tags every transition with the point-in-time-safe VIX
regime prevailing at that transition -- reusing crisis_regime_correlation_
diagnostic.py's `_nearest_regime`/`build_vix_regime_lookup` directly, not
reimplemented, so a transition's regime label is computed identically to
every other regime label in this project's discovery-event work.

Design choice, stated explicitly: the recorded transition DATE is the new
span's start_date (the ONSET of the persistent run that confirmed the
regime change, per §7.2's own hysteresis design), not the confirmation
point later in that run and not the old span's end_date -- consistent
with how §7.2 itself already defines a regime's "start."

Verified against synthetic ground truth first:
debug/_verify_correlation_transition_detector.py.

Usage:
    python research/correlation_transition_detector.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEGMENTS_PATH = os.path.join(_ROOT, "output", "research", "cointegration_regime_segments.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "correlation_transitions.parquet")

log = logging.getLogger("correlation_transition_detector")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def detect_transitions(segments: pd.DataFrame) -> pd.DataFrame:
    """For every pair with 2+ regime spans (sorted by start_date), finds
    every consecutive-span boundary where state changes and records it as a
    transition row: {symbol_a, symbol_b, transition_date, transition_type
    (decoupling|recoupling), old_state, new_state, old_strength,
    new_strength, old_span_n_windows, new_span_n_windows}. Pairs with only
    1 span (never transitioned, or only one state observed across the
    whole available history) produce zero transition rows -- correctly
    excluded, not padded with a fabricated event.

    VECTORIZED (2026-09-03, caught live before it ran to completion --
    same anti-pattern class as this session's earlier merge_asof fixes): a
    first version of this function used `groupby(...)` with a Python-level
    loop and `.to_dict("records")` per group, one iteration per PAIR
    (638,095 groups at real Tier 3 scale) -- killed after 2+ minutes with
    no sign of finishing, the same "Python-level loop over hundreds of
    thousands of small groups" shape already fixed twice earlier this
    session. Rewritten as a single vectorized pass: sort once, then use
    `groupby(...).shift(1)` to pull each row's PREVIOUS span's fields into
    the same row (one C-level pass, not a Python loop), and boolean-filter
    for `prev_state is not null AND prev_state != state` -- the first row
    of each pair's group has no previous span (shift produces NaN there),
    correctly excluding single-span pairs without a separate branch."""
    sorted_segments = segments.sort_values(["symbol_a", "symbol_b", "start_date"]).reset_index(drop=True)
    grp = sorted_segments.groupby(["symbol_a", "symbol_b"], sort=False)
    prev_state = grp["state"].shift(1)
    prev_strength = grp["strength"].shift(1)
    prev_n_windows = grp["n_windows"].shift(1)

    is_transition = prev_state.notna() & (prev_state != sorted_segments["state"])
    out = sorted_segments.loc[is_transition, ["symbol_a", "symbol_b", "start_date", "state",
                                               "strength", "n_windows"]].copy()
    out["old_state"] = prev_state[is_transition]
    out["old_strength"] = prev_strength[is_transition]
    out["old_span_n_windows"] = prev_n_windows[is_transition]
    out = out.rename(columns={
        "start_date": "transition_date", "state": "new_state",
        "strength": "new_strength", "n_windows": "new_span_n_windows",
    })
    out["transition_type"] = np.where(out["new_state"] == "coint", "recoupling", "decoupling")

    cols = ["symbol_a", "symbol_b", "transition_date", "transition_type",
            "old_state", "new_state", "old_strength", "new_strength",
            "old_span_n_windows", "new_span_n_windows"]
    return out[cols].reset_index(drop=True)


def tag_transition_regime(transitions: pd.DataFrame, vix_regime: pd.Series) -> pd.DataFrame:
    """Adds a point-in-time-safe `regime` column via merge_asof (the same
    vectorized primitive crisis_regime_correlation_diagnostic.py's fix
    uses, not the old per-row _nearest_regime loop it replaced)."""
    if transitions.empty:
        return transitions.assign(regime=pd.Series(dtype=object))
    regime_lookup = vix_regime.sort_index().rename("regime").reset_index()
    date_col = regime_lookup.columns[0]
    out = pd.merge_asof(
        transitions.sort_values("transition_date"), regime_lookup,
        left_on="transition_date", right_on=date_col, direction="backward",
    )
    return out.drop(columns=[date_col])


def main():
    _setup_logging()
    log.info("=== correlation_transition_detector.py: cataloguing every decoupling AND "
             "recoupling event across the full Tier 3 universe, regime-tagged ===")

    if not os.path.exists(_SEGMENTS_PATH):
        log.error(f"{_SEGMENTS_PATH} does not exist -- run "
                  f"research/cointegration_regime_segmentation.py first.")
        sys.exit(1)

    segments = pd.read_parquet(_SEGMENTS_PATH)
    log.info(f"Loaded {len(segments)} regime spans across "
             f"{segments[['symbol_a','symbol_b']].drop_duplicates().shape[0]} pairs.")

    transitions = detect_transitions(segments)
    log.info(f"Detected {len(transitions)} transitions "
             f"({(transitions['transition_type']=='decoupling').sum()} decoupling, "
             f"{(transitions['transition_type']=='recoupling').sum()} recoupling).")

    import macro
    result = macro.build(series=["VIXCLS"])
    vix_regime = result.data["vix_regime"]
    tagged = tag_transition_regime(transitions, vix_regime)

    tagged.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info(f"\nBy regime and type:\n{tagged.groupby(['regime', 'transition_type']).size()}")
    log.info("correlation_transition_detector.py complete")


if __name__ == "__main__":
    main()
