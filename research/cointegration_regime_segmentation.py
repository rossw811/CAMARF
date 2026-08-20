"""
research/cointegration_regime_segmentation.py -- Thread J Test 2 (regime
segmentation), the piece explicitly flagged in the master plan file as
needing a concrete design pass before implementation, per Ross's own "if
something hasn't been scoped, scope it first then build it" instruction
(2026-08-13). Design decisions made here, stated explicitly so they can be
challenged rather than silently assumed:

REUSES existing, already-verified machinery rather than rebuilding a rolling
EG-test loop from scratch: `wrds_deep_history_episodic_scan_tier3_windows.
parquet` (1,197,576 real rows) already has a per-(pair, window_end_date) EG
p-value from the existing rolling scan -- Tier 3's own candidate-generation
windows ARE the raw regime signal this needs, just never segmented into
contiguous spans before. No new statistical test is introduced.

THE REGIME-BOUNDARY DESIGN QUESTION (the actual novel piece): a pair's raw
per-window state (pvalue < alpha -> "coint", else "not_coint") flips noisily
window-to-window near a genuine transition and even during a stable regime
(a single borderline p-value shouldn't end a 10-year cointegrated stretch).
Fixed via HYSTERESIS, not a naive per-window flip: a state change only
"confirms" once the NEW raw state persists for >= MIN_REGIME_WINDOWS
consecutive windows (default 3 -- reusing Finding #23's own already-
validated `min_windows_confirmed=3` convention rather than inventing a new
number). The regime's recorded START is the ONSET of that persistent run
(the point the state genuinely started shifting), not the later
confirmation point -- a real design choice: it means a very recent
transition (fewer than MIN_REGIME_WINDOWS windows old) at a pair's most
current data doesn't get confirmed yet, correctly reflected as "still the
prior regime, insufficient evidence for a new one" rather than silently
extrapolated.

STRENGTH METRIC (Test 3, additive on Test 2's spans): uses the EG p-value
itself (continuous, already present, well-understood) rather than `coint_
fraction_rolling` (mentioned as an option in the original scoping note, but
that field lives in a different pipeline stage -- the adapter's per-pair
output, not this per-window file -- and pulling it in would mean another
join this pass doesn't need). Within each "coint" regime span, buckets by
TERCILES of that regime's own observed p-value distribution (empirical,
data-driven cutoffs -- not an arbitrary fixed threshold, consistent with
this session's broader "figure out what static numbers make sense, don't
assume arbitrary ones" theme) into strong/moderate/weak.

NOT YET RUN against the real 1.2M-row file (that's the next step, cheap --
this is a pandas groupby, not a re-scan) -- verified synthetically first,
per this project's standing discipline, given the regime-boundary logic is
genuinely new code, not a parameter tweak.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

_WINDOWS_PATH = os.path.join("output", "research", "wrds_deep_history_episodic_scan_tier3_windows.parquet")
_OUT_PATH = os.path.join("output", "research", "cointegration_regime_segments.parquet")

MIN_REGIME_WINDOWS = 3  # reuses Finding #23's own validated min_windows_confirmed convention
ALPHA = 0.05            # matches Config.STATS.FDR_ALPHA / EG_SIGNIFICANCE convention elsewhere


def segment_regimes(window_df: pd.DataFrame, alpha: float = ALPHA,
                     min_regime_windows: int = MIN_REGIME_WINDOWS,
                     pvalue_col: str = "pvalue") -> list:
    """
    window_df: one pair's rows, columns [window_end_date, pvalue_col], NOT
    necessarily pre-sorted (sorted here). Returns a list of dicts, one per
    detected regime span: {state, start_date, end_date, n_windows,
    mean_pvalue, strength} (strength only set for "coint" spans, via
    terciles of THAT span's own p-value distribution -- see module
    docstring). Consecutive spans of the SAME state never occur in the
    output (they'd have been merged by construction).
    """
    df = window_df.sort_values("window_end_date").reset_index(drop=True)
    raw_states = np.where(df[pvalue_col] < alpha, "coint", "not_coint")

    # Hysteresis: walk the raw sequence, only flip the CONFIRMED state once
    # min_regime_windows consecutive raw observations agree. confirmed[i] is
    # the confirmed state as of window i; the run's recorded start is the
    # onset of the persistent raw run, not the confirmation point.
    n = len(df)
    confirmed = [None] * n
    if n == 0:
        return []
    current_state = raw_states[0]
    run_start_idx = 0
    pending_state = None
    pending_start_idx = None
    pending_count = 0
    confirmed[0] = current_state if min_regime_windows <= 1 else None

    # Simpler two-pass approach: first pass finds confirmed transition points,
    # second pass fills in confirmed state per window given those transitions.
    transitions = []  # list of (onset_idx, new_state)
    i = 0
    active_state = raw_states[0]
    # Bootstrap: the very first min_regime_windows rows are only "confirmed"
    # once they themselves persist -- find the first confirmed state.
    boot_idx = 0
    while boot_idx < n:
        run_state = raw_states[boot_idx]
        run_len = 1
        j = boot_idx + 1
        while j < n and raw_states[j] == run_state:
            run_len += 1
            j += 1
        if run_len >= min_regime_windows or boot_idx == 0:
            active_state = run_state
            transitions.append((boot_idx, run_state))
            break
        boot_idx = j
    else:
        active_state = raw_states[0]
        transitions.append((0, active_state))

    i = transitions[0][0] + 1
    while i < n:
        if raw_states[i] != active_state:
            run_state = raw_states[i]
            run_len = 1
            j = i + 1
            while j < n and raw_states[j] == run_state:
                run_len += 1
                j += 1
            if run_len >= min_regime_windows:
                transitions.append((i, run_state))
                active_state = run_state
                i = j
                continue
        i += 1

    # Build confirmed-state array from transition onset points.
    confirmed_state = np.empty(n, dtype=object)
    for k, (onset_idx, state) in enumerate(transitions):
        end_idx = transitions[k + 1][0] if k + 1 < len(transitions) else n
        confirmed_state[onset_idx:end_idx] = state
    if transitions[0][0] > 0:
        confirmed_state[:transitions[0][0]] = transitions[0][1]

    # Collapse into contiguous spans. Strength gradation (Test 3) is NOT done
    # here -- a single pair typically has only 0-1 "coint" spans in its whole
    # history (confirmed against the real data: 16,064 coint spans across
    # 158,849 pairs, ~0.1/pair), so PER-PAIR terciles are meaningless (a
    # real bug caught by running against real data, not just the synthetic
    # test -- see debug/_verify_cointegration_regime_segmentation.py's
    # check 5, which passed because it specifically constructed one pair
    # with 3 spans, not representative of real pair-level span counts).
    # Strength is assigned in main() as a GLOBAL post-processing step across
    # every pair's spans instead -- see assign_strength_terciles().
    spans = []
    span_start = 0
    for i in range(1, n + 1):
        if i == n or confirmed_state[i] != confirmed_state[span_start]:
            seg = df.iloc[span_start:i]
            state = confirmed_state[span_start]
            mean_p = float(seg[pvalue_col].mean())
            spans.append({
                "state": state, "start_date": seg["window_end_date"].iloc[0],
                "end_date": seg["window_end_date"].iloc[-1], "n_windows": len(seg),
                "mean_pvalue": mean_p,
            })
            span_start = i

    return spans


def assign_strength_terciles(spans_df: pd.DataFrame) -> pd.DataFrame:
    """
    GLOBAL strength gradation across every pair's 'coint' spans -- terciles
    of the mean_pvalue distribution across ALL coint spans in the dataset,
    not per-pair (per-pair terciles are meaningless at real-world span
    counts, see segment_regimes' docstring note above). Empirical cutoffs,
    not an arbitrary fixed threshold.
    """
    out = spans_df.copy()
    out["strength"] = None
    coint_mask = out["state"] == "coint"
    coint_means = out.loc[coint_mask, "mean_pvalue"]
    if len(coint_means) >= 3:
        t1, t2 = np.percentile(coint_means, [33.3, 66.7])
        out.loc[coint_mask, "strength"] = np.where(
            coint_means <= t1, "strong", np.where(coint_means > t2, "weak", "moderate")
        )
    return out


def main():
    if not os.path.exists(_WINDOWS_PATH):
        print(f"FATAL: {_WINDOWS_PATH} not found")
        sys.exit(1)
    df = pd.read_parquet(_WINDOWS_PATH)
    print(f"Loaded {len(df)} real per-window rows across "
          f"{df[['symbol_a', 'symbol_b']].drop_duplicates().shape[0]} pairs")

    all_spans = []
    for (sym_a, sym_b), pair_df in df.groupby(["symbol_a", "symbol_b"]):
        spans = segment_regimes(pair_df)
        for s in spans:
            s["symbol_a"] = sym_a
            s["symbol_b"] = sym_b
            all_spans.append(s)

    out_df = pd.DataFrame(all_spans)
    out_df = assign_strength_terciles(out_df)
    os.makedirs(os.path.dirname(_OUT_PATH), exist_ok=True)
    out_df.to_parquet(_OUT_PATH, index=False)
    print(f"Saved {len(out_df)} regime spans across "
          f"{out_df[['symbol_a', 'symbol_b']].drop_duplicates().shape[0]} pairs -> {_OUT_PATH}")
    print(out_df["state"].value_counts())
    print(out_df[out_df["state"] == "coint"]["strength"].value_counts())


if __name__ == "__main__":
    main()
