"""
research/build_comparison_arm_pairs.py -- Thread A Step 4 of the PIT-safe
episodic pair-confirmation comparison-arm plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

Builds three --pairs-override-compatible pairs files from the standard
full-history screen's output (output/results/{tf_dir}/pairs.parquet,
currently 3 confirmed pairs: IQV/Q@1D, KVUE/KMB@3m, PNC/ZION@4h) and Step
3's PIT-safe episodic adapter output
(output/research/episodic_confirmed_pairs_adapter_output.parquet, 454
pairs):

  1. **Hybrid** (hybrid_pairs.parquet): union of the episodic adapter
     output (all 454 rows, as-is) + any standard-screen pair NOT already
     present in the episodic set, tagged source="full_history_fallback".
     A real, documented data necessity, not a silent gap-fill: as of this
     build, ALL 3 standard-confirmed pairs are absent from the episodic
     set (see DISCLOSURE below), so Hybrid = 454 + 3 = 457 rows.
  2. **Purity** (purity_pairs.parquet): the episodic adapter output only,
     no fallback -- 454 rows, none of which are the current production
     pair set.
  3. **Tiered** (tiered_pairs.parquet): the full standard pairs.parquet
     (3 rows, no rows dropped), left-joined against the episodic output
     by (symbol_a, symbol_b, tf_label) to attach a pit_confidence_tier
     column consumed by backtest.py's compute_pit_confidence_weights()
     (--pit-confidence-weight): full_episodic (>=1 episodic match this
     exact tf), partial_episodic (reserved -- see DISCLOSURE), or
     full_history_only (no episodic match at all).

DISCLOSURE, found live during this build (2026-08-11), not hidden: querying
the episodic adapter output for all 3 standard-confirmed pairs returns ZERO
matches -- the full-history screen's currently-confirmed pairs and the
PIT-safe episodic screen's confirmed pairs are COMPLETELY DISJOINT sets at
this snapshot. This means Tiered's tier assignment for this run is
uniformly "full_history_only" for all 3 rows (a flat 0.3x N_SHARES
scale-down vs baseline, not a differentiated per-pair test) -- a real,
disclosed limitation of what Tiered can show at the CURRENT confirmed-pair
snapshot, not a bug in this script. "partial_episodic" (a pair confirmed
episodically at SOME but not ALL of its standard-screen timeframes) cannot
occur here either, since none of the 3 standard pairs have ANY episodic
match. Both facts belong in Step 6's writeup verbatim, not smoothed over.

Synthetic verification FIRST: debug/_verify_build_comparison_arm_pairs.py
-- run that before trusting this script's real-data output.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")

_ADAPTER_OUTPUT_PATH = os.path.join(_OUT_DIR, "episodic_confirmed_pairs_adapter_output.parquet")

# The 6 fields both the standard pairs.parquet schema and the episodic
# adapter output carry under the same names (adapter's own stated
# REQUIRED_FIELDS contract) -- the minimal shared schema Hybrid's
# full_history_fallback rows use, since the two sources otherwise have
# very different column sets (standard pairs.parquet has 41 columns;
# the adapter output has the 6 gating scalars + metadata only).
_SHARED_SCALAR_FIELDS = [
    "hedge_ratio_ols", "hedge_ratio_kalman_mean", "hurst_rs",
    "coint_fraction_rolling", "half_life_trend_slope", "mean_reversion_speed",
]

_TF_DIRS = [
    ("1min", "1min"), ("2min", "2min"), ("3min", "3min"), ("5min", "5min"),
    ("15min", "15min"), ("30min", "30min"), ("1hr", "1h"), ("4hr", "4h"),
    ("1day", "1D"), ("7day", "7D"), ("1mo", "1M"), ("3mo", "3m"), ("6mo", "6m"),
]


def load_standard_pairs() -> pd.DataFrame:
    """Loads and concatenates every TF's output/results/{tf_dir}/pairs.parquet
    (the standard, non-PIT-safe full-history screen's currently-confirmed
    pairs), with a tf_label column guaranteed present."""
    frames = []
    for tf_dir, tf_label in _TF_DIRS:
        path = os.path.join(_RESULTS_DIR, tf_dir, "pairs.parquet")
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path)
        if df.empty:
            continue
        if "tf_label" not in df.columns:
            df["tf_label"] = tf_label
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["symbol_a", "symbol_b", "tf_label"] + _SHARED_SCALAR_FIELDS)
    return pd.concat(frames, ignore_index=True)


def load_episodic_pairs() -> pd.DataFrame:
    if not os.path.exists(_ADAPTER_OUTPUT_PATH):
        raise FileNotFoundError(
            f"{_ADAPTER_OUTPUT_PATH} not found -- run research/episodic_pairs_adapter.py first "
            "(Thread A Step 3)."
        )
    return pd.read_parquet(_ADAPTER_OUTPUT_PATH)


def _pair_key_set(df: pd.DataFrame) -> set:
    return set(zip(df["symbol_a"], df["symbol_b"], df["tf_label"]))


def build_hybrid(standard_df: pd.DataFrame, episodic_df: pd.DataFrame) -> pd.DataFrame:
    episodic_keys = _pair_key_set(episodic_df)
    fallback_mask = ~standard_df.apply(
        lambda r: (r["symbol_a"], r["symbol_b"], r["tf_label"]) in episodic_keys, axis=1
    )
    fallback_rows = standard_df.loc[fallback_mask, ["symbol_a", "symbol_b", "tf_label"] + _SHARED_SCALAR_FIELDS].copy()
    fallback_rows["source"] = "full_history_fallback"
    fallback_rows["as_of_date"] = pd.NaT
    fallback_rows["n_windows_tested"] = np.nan
    fallback_rows["n_windows_fdr_rejected"] = np.nan
    shared_cols = ["symbol_a", "symbol_b", "tf_label", "source", "as_of_date",
                   "n_windows_tested", "n_windows_fdr_rejected"] + _SHARED_SCALAR_FIELDS
    return pd.concat(
        [episodic_df[shared_cols], fallback_rows[shared_cols]], ignore_index=True
    )


def build_purity(episodic_df: pd.DataFrame) -> pd.DataFrame:
    return episodic_df.copy()


def build_tiered(standard_df: pd.DataFrame, episodic_df: pd.DataFrame) -> pd.DataFrame:
    """Full standard pairs.parquet, no rows dropped, with pit_confidence_tier
    attached per pair based on how many of its OWN timeframe's episodic
    confirmations exist (a pair only ever has one tf_label row in
    standard_df per TF, so "how many" collapses to "any/none" here --
    partial_episodic is reserved for a future run where a pair is
    standard-confirmed at multiple TFs with mixed episodic-match status,
    which cannot occur in the current 1-row-per-pair standard_df shape)."""
    episodic_keys = _pair_key_set(episodic_df)

    def _tier(row):
        return "full_episodic" if (row["symbol_a"], row["symbol_b"], row["tf_label"]) in episodic_keys \
            else "full_history_only"

    tiered = standard_df.copy()
    tiered["pit_confidence_tier"] = tiered.apply(_tier, axis=1)
    return tiered


def main():
    standard_df = load_standard_pairs()
    episodic_df = load_episodic_pairs()
    print(f"Standard (full-history) confirmed pairs: {len(standard_df)}")
    print(f"Episodic (PIT-safe) confirmed pairs: {len(episodic_df)}")

    overlap = _pair_key_set(standard_df) & _pair_key_set(episodic_df)
    print(f"Overlap between the two sets: {len(overlap)} pair(s) -- {sorted(overlap)}")

    hybrid = build_hybrid(standard_df, episodic_df)
    purity = build_purity(episodic_df)
    tiered = build_tiered(standard_df, episodic_df)

    os.makedirs(_OUT_DIR, exist_ok=True)
    hybrid_path = os.path.join(_OUT_DIR, "hybrid_pairs.parquet")
    purity_path = os.path.join(_OUT_DIR, "purity_pairs.parquet")
    tiered_path = os.path.join(_OUT_DIR, "tiered_pairs.parquet")
    hybrid.to_parquet(hybrid_path)
    purity.to_parquet(purity_path)
    tiered.to_parquet(tiered_path)

    print(f"Hybrid: {len(hybrid)} rows -> {hybrid_path} "
          f"({(hybrid['source'] == 'full_history_fallback').sum()} full_history_fallback)")
    print(f"Purity: {len(purity)} rows -> {purity_path}")
    print(f"Tiered: {len(tiered)} rows -> {tiered_path} "
          f"(tier counts: {tiered['pit_confidence_tier'].value_counts().to_dict()})")
    return hybrid, purity, tiered


if __name__ == "__main__":
    main()
