"""
research/episodic_pairs_adapter.py -- Step 3 of the PIT-safe episodic
pair-confirmation comparison-arm plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

Takes PIT-safe episodic-confirmed pair tuples (from
research/pit_pair_discovery.py's discover_pit_confirmed_pairs_with_detail,
called once for the existing WRDS/1D source and once each for the new
intraday 1h/4h sources built in Step 2) and produces:
  1. A pairs.parquet-schema-COMPATIBLE row (the 9 fields backtest.py's
     engine actually reads -- see below), suitable for backtest.py's
     `--pairs-override` mechanism.
  2. A `spread_series_{A}_{B}.parquet` file in `output/results/{tf_dir}/`
     for any pair not already present there from the standard screen --
     required because `--pairs-override` does NOT supply per-bar spread
     data; `backtest.py::_load_spread` reads that from a SEPARATE file,
     unconditionally, regardless of pair source, and silently skips
     (0 trades) any pair missing it.

PIT-SAFETY DISCIPLINE (BUG-D69, already documented in pit_wfa.py's
`backtest_pair_on_test_window`, lines 393-408): a pair's GATING scalar
fields (hedge_ratio_ols, hurst_rs, coint_fraction_rolling,
half_life_trend_slope, mean_reversion_speed) must be computed using ONLY
data available as of the pair's PIT confirmation date -- never recomputed
over the full current cache, which would leak future information into a
value meant to represent "what a real deployment would have known." This
adapter computes those 6 scalar fields from data TRUNCATED to
`as_of_date`, via a first `AnalysisPipeline._build_pair_result` call on
truncated data. The per-bar SPREAD SERIES (for actually trading the pair
going forward) is a SEPARATE, second `_build_pair_result` call on the
FULL, untruncated data -- per-bar causal companion fields inside it
(`hedge_ratio_ols_t`, `coint_fraction_rolling_t`, etc.) are themselves
point-in-time BY BAR already (computed via CointScanner.expanding_coint_
fraction inside _build_pair_result), so using the full range for the
per-bar series does not reintroduce lookahead -- this exact distinction
(frozen train-only scalar vs. per-bar-causal series) is the same one
pit_wfa.py's own comment draws.

SIMPLIFICATION vs. the original plan text: rather than using "the last
confirming window's own window_end_date" as a per-pair cutoff, this uses
the single `as_of_date` passed to discover_pit_confirmed_pairs_with_detail
for ALL pairs from that call. This is the more conservative and more
directly correct reading of what "PIT-confirmed as of date T" means for
gating-scalar computation: T is the date a real deployment would be
standing at, and everything up to T (not just up to some earlier
confirming window) is legitimately known at that point. Stated here
plainly since it's a real deviation from the plan file's literal wording,
made for a documented reason, not silently.

Emitted row fields, stated as the CONTRACT (not the full 41-column
production schema -- eigenportfolio fields are universe-entangled per the
planning-phase exploration and are explicitly out of scope here):
    symbol_a, symbol_b, tf_label,
    hedge_ratio_ols, hedge_ratio_kalman_mean,   # load-bearing
    hurst_rs, coint_fraction_rolling, half_life_trend_slope, mean_reversion_speed,
    source, as_of_date, n_windows_tested, n_windows_fdr_rejected  # metadata, nice-to-have

Synthetic verification FIRST: debug/_verify_episodic_pairs_adapter.py --
run that before trusting this script's real-data output.

Usage (as a library):
    from research.episodic_pairs_adapter import build_adapter_rows
    rows = build_adapter_rows("wrds_1D", tf_label="1D")
    rows_1h = build_adapter_rows(
        "intraday_1h", tf_label="1h",
        checkpoint_paths=(
            # Tier 3 only (BUG-D112) -- Tier 2's candidate pool is non-causal.
            "output/research/intraday_episodic_scan_1h_tier3_windows.parquet",
        ),
    )
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline, CointScanner
from config import Config
from data import DataAligner, DataStore
from research.pit_pair_discovery import (
    discover_pit_confirmed_pairs_with_detail,
    _DEFAULT_CHECKPOINT_PATHS,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")

REQUIRED_FIELDS = [
    "hedge_ratio_ols", "hedge_ratio_kalman_mean", "hurst_rs",
    "coint_fraction_rolling", "half_life_trend_slope", "mean_reversion_speed",
]


def _tf_dir(tf_label: str) -> str:
    return DataStore._TF_SAFE.get(tf_label, tf_label.lower())


def _load_aligned(sym_a: str, sym_b: str, tf_label: str, as_of_date=None):
    """Loads both symbols' cached data, optionally truncated to
    `as_of_date`, and aligns them via DataAligner.align_universe
    (drop_data_gap_rows=True -- the single-pair/real-timestamp-join
    convention pit_wfa.py::backtest_pair_on_test_window already
    established, not the cross-symbol dense-matrix default). Returns None
    if either symbol is missing or there's too little overlap to bother."""
    df_a = DataStore.load(sym_a, tf_label)
    df_b = DataStore.load(sym_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    if as_of_date is not None:
        cutoff = pd.Timestamp(as_of_date)
        df_a = df_a.loc[df_a.index <= cutoff]
        df_b = df_b.loc[df_b.index <= cutoff]
    if len(df_a) < 60 or len(df_b) < 60:
        return None
    aligned = DataAligner.align_universe(
        {f"{sym_a}_{tf_label}": df_a, f"{sym_b}_{tf_label}": df_b}, tf_label,
        drop_data_gap_rows=True,
    )
    if sym_a not in aligned or sym_b not in aligned:
        return None
    common_idx = aligned[sym_a].index.intersection(aligned[sym_b].index)
    if len(common_idx) < 60:
        return None
    return {sym_a: aligned[sym_a].loc[common_idx], sym_b: aligned[sym_b].loc[common_idx]}


def write_spread_series(sym_a: str, sym_b: str, tf_label: str, per_bar: dict) -> str:
    """Writes output/results/{tf_dir}/spread_series_{A}_{B}.parquet from
    the FULL (untruncated) per_bar series -- required by
    backtest.py::_load_spread, which is NOT supplied by --pairs-override
    (confirmed during planning: it's a separate file, read unconditionally
    regardless of pair-list provenance)."""
    tf_dir = _tf_dir(tf_label)
    out_dir = os.path.join(_RESULTS_DIR, tf_dir)
    os.makedirs(out_dir, exist_ok=True)
    spread_df = pd.DataFrame(
        {
            "spread": per_bar["spread"],
            "z_rolling": per_bar["z_rolling"],
            "z_expanding": per_bar["z_expanding"],
            "half_life_rolling": per_bar["half_life_rolling_series"],
            "gap_flag_a": per_bar["gap_flag_a"],
            "gap_flag_b": per_bar["gap_flag_b"],
            "hedge_ratio_ols_t": per_bar.get("hedge_ratio_ols_t"),
            "hedge_ratio_kalman_t": per_bar.get("hedge_ratio_kalman_t"),
            "coint_fraction_rolling_t": per_bar.get("coint_fraction_rolling_t"),
            "half_life_trend_slope_t": per_bar.get("half_life_trend_slope_t"),
            "mean_reversion_speed_t": per_bar.get("mean_reversion_speed_t"),
            "hurst_rs_t": per_bar.get("hurst_rs_t"),
        },
        index=per_bar["index"],
    )
    out_path = os.path.join(out_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
    spread_df.to_parquet(out_path)
    return out_path


def build_one_row(sym_a: str, sym_b: str, tf_label: str, as_of_date, source: str, detail: dict):
    """Returns a dict row (or None if data is insufficient) following the
    module's stated contract. `detail` is the confirmation-detail dict
    from discover_pit_confirmed_pairs_with_detail (n_windows_tested etc.)."""
    train_aligned = _load_aligned(sym_a, sym_b, tf_label, as_of_date=as_of_date)
    if train_aligned is None:
        return None
    # coint_fraction_rolling is NOT computed inside _build_pair_result --
    # it only echoes back whatever pd_meta already carries (confirmed
    # during planning). CointScanner.rolling_fraction() is the actual
    # computation; pit_wfa.py::screen_universe_at_cutoff calls it in this
    # same order (rolling_fraction BEFORE _build_pair_result) -- mirrored
    # here rather than leaving this field permanently NaN.
    pd_meta_list = CointScanner.rolling_fraction(
        [{"symbol_a": sym_a, "symbol_b": sym_b}], train_aligned, tf_label, n_workers=1
    )
    pd_meta = pd_meta_list[0] if pd_meta_list else {"symbol_a": sym_a, "symbol_b": sym_b}
    train_built = AnalysisPipeline._build_pair_result(pd_meta, train_aligned, tf_label)
    if train_built is None:
        return None
    train_result, _train_per_bar = train_built

    full_aligned = _load_aligned(sym_a, sym_b, tf_label, as_of_date=None)
    if full_aligned is None:
        return None
    full_built = AnalysisPipeline._build_pair_result(
        {"symbol_a": sym_a, "symbol_b": sym_b}, full_aligned, tf_label
    )
    if full_built is None:
        return None
    _full_result, full_per_bar = full_built

    write_spread_series(sym_a, sym_b, tf_label, full_per_bar)

    row = {
        "symbol_a": sym_a,
        "symbol_b": sym_b,
        "tf_label": tf_label,
        "source": source,
        "as_of_date": pd.Timestamp(as_of_date) if as_of_date is not None else pd.NaT,
        "n_windows_tested": detail.get("n_windows_tested"),
        "n_windows_fdr_rejected": detail.get("n_windows_fdr_rejected"),
    }
    for field in REQUIRED_FIELDS:
        row[field] = getattr(train_result, field, np.nan)
    return row


def _build_one_row_worker(args):
    sym_a, sym_b, tf_label, as_of_date, source, detail = args
    return build_one_row(sym_a, sym_b, tf_label, as_of_date, source, detail)


def _resume_checkpoint_path(source: str) -> str:
    return os.path.join(_OUT_DIR, f"episodic_pairs_adapter_progress_{source}.parquet")


def _save_progress(path: str, rows: list):
    """Atomic tmp+os.replace write, same pattern as BUG-D108's fix to
    wrds_deep_history_episodic_scan.py -- a multi-hour, per-pair sequential
    build with no incremental persistence lost 44 min of real CPU-bound work
    to a single stage-timeout kill (found live, 2026-08-11); this makes each
    kill/resume cost at most one pair, not the whole run."""
    tmp = path + ".tmp"
    pd.DataFrame(rows).to_parquet(tmp)
    os.replace(tmp, path)


def build_adapter_rows(
    source: str, tf_label: str, checkpoint_paths=_DEFAULT_CHECKPOINT_PATHS,
    as_of_date=None, alpha: float = 0.05, min_windows_confirmed: int = 1,
    n_workers: int = 1,
) -> pd.DataFrame:
    if as_of_date is None:
        as_of_date = pd.Timestamp.now().normalize()
    details = discover_pit_confirmed_pairs_with_detail(
        as_of_date=as_of_date, alpha=alpha, min_windows_confirmed=min_windows_confirmed,
        checkpoint_paths=checkpoint_paths,
    )

    progress_path = _resume_checkpoint_path(source)
    rows = []
    done_keys = set()
    if os.path.exists(progress_path):
        prior = pd.read_parquet(progress_path)
        prior_rows = prior.to_dict("records")
        # BUG (found live, 2026-08-12, while rebuilding the adapter post-
        # BUG-D112): a prior checkpoint can contain rows for pairs that are
        # NO LONGER in the current `details` (e.g. the confirmed set shrank
        # after a methodology fix, exactly BUG-D112's own situation --
        # 647->326 for WRDS/1D). Blindly trusting every checkpointed row
        # would silently reintroduce stale, no-longer-confirmed pairs into
        # supposedly-current PIT-safe output -- the same class of silent
        # contamination this whole session has been fixing. Filter to only
        # keep checkpointed rows whose key is STILL in the current
        # `details` before treating them as valid/already-done.
        current_keys = {(d["symbol_a"], d["symbol_b"]) for d in details}
        rows = [r for r in prior_rows if (r["symbol_a"], r["symbol_b"]) in current_keys]
        done_keys = {(r["symbol_a"], r["symbol_b"]) for r in rows}
        n_dropped = len(prior_rows) - len(rows)
        print(f"{source}: resuming from {len(rows)} already-built rows in {progress_path}"
              + (f" ({n_dropped} stale checkpointed rows dropped -- no longer in the current "
                 f"confirmed set)" if n_dropped else ""))
        if n_dropped:
            _save_progress(progress_path, rows)  # persist the pruned checkpoint immediately

    pending = [d for d in details if (d["symbol_a"], d["symbol_b"]) not in done_keys]

    if n_workers <= 1:
        for d in pending:
            row = build_one_row(d["symbol_a"], d["symbol_b"], tf_label, as_of_date, source, d)
            if row is not None:
                rows.append(row)
                _save_progress(progress_path, rows)
        return pd.DataFrame(rows)

    # Per-pair work (2x DataAligner.align_universe + AnalysisPipeline.
    # _build_pair_result) is independent across pairs -- embarrassingly
    # parallel, same pattern intraday_episodic_scan.py already uses for its
    # own per-pair EG tests (BUG-D110: single-threaded, this source's 647
    # WRDS/1D pairs alone took ~28s/pair, ~5 hours sequential). Each worker
    # calls CointScanner.rolling_fraction with n_workers=1 internally
    # (build_one_row's own call) to avoid nested pool spawning.
    tasks = [(d["symbol_a"], d["symbol_b"], tf_label, as_of_date, source, d) for d in pending]
    completed_since_save = 0
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_build_one_row_worker, t): t for t in tasks}
        for fut in as_completed(futures):
            row = fut.result()
            if row is not None:
                rows.append(row)
                completed_since_save += 1
                if completed_since_save >= 5:
                    _save_progress(progress_path, rows)
                    completed_since_save = 0
    if completed_since_save > 0:
        _save_progress(progress_path, rows)
    return pd.DataFrame(rows)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1,
                         help="Parallel worker processes for the per-pair build "
                              "(BUG-D110: single-threaded, ~28s/pair, hours for "
                              "647+ pairs). Each pair's build is independent.")
    args = parser.parse_args()

    # Tier 2 REMOVED from every source (BUG-D112, 2026-08-11): its candidate
    # pool is a single whole-history correlation matrix, non-causal by
    # construction -- same reason Tier 1 was already excluded. Tier 3 only.
    sources = [
        ("wrds_1D", "1D", _DEFAULT_CHECKPOINT_PATHS),
        ("intraday_1h", "1h", (
            os.path.join(_OUT_DIR, "intraday_episodic_scan_1h_tier3_windows.parquet"),
        )),
        ("intraday_4h", "4h", (
            os.path.join(_OUT_DIR, "intraday_episodic_scan_4h_tier3_windows.parquet"),
        )),
    ]
    all_rows = []
    for source, tf_label, checkpoint_paths in sources:
        existing = [p for p in checkpoint_paths if os.path.exists(p)]
        if not existing:
            print(f"SKIP {source}: no checkpoint files found at {checkpoint_paths}")
            continue
        df = build_adapter_rows(source, tf_label, checkpoint_paths=checkpoint_paths, n_workers=args.workers)
        print(f"{source}@{tf_label}: {len(df)} rows built")
        all_rows.append(df)

    if not all_rows:
        print("No adapter rows built -- nothing to write.")
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "episodic_confirmed_pairs_adapter_output.parquet")
    combined.to_parquet(out_path)
    print(f"Wrote {out_path} ({len(combined)} total rows)")
    return combined


if __name__ == "__main__":
    main()
