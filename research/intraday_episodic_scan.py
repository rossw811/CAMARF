"""
research/intraday_episodic_scan.py -- Step 2 of the PIT-safe episodic
pair-confirmation comparison-arm plan
(C:\\Users\\RossW\\.claude\\plans\\ancient-mixing-feather.md).

Intraday (1h/4h) analogue of research/wrds_deep_history_episodic_scan.py's
Tier 2/3 episodic-discovery pipeline. WRDS/CRSP has no intraday data at
all, so that script's approach can't extend to 1h/4h directly -- but Step
0 (debug/_check_intraday_cache_coverage.py) found this isn't a niche
case: 1,535/1,576 cached symbols (97%) have >=2 years of 1h history
(median ~3yr), so a real intraday episodic scan is worth building
universe-wide, not just for PNC/ZION (the one pair this whole thread
started from).

REUSED DIRECTLY (imported, not copy-pasted) from
research/wrds_deep_history_episodic_scan.py -- all of these are already
TF-agnostic (operate on generic window/step bar counts and price arrays,
no WRDS-specific logic inside): `episodic_bhfdr_confirm`,
`episodic_bhfdr_confirm_asof`, `build_rolling_eg_tasks`,
`run_rolling_eg_pool`, `rolling_correlation_candidate_pairs`, and the
checkpoint helpers (`_checkpoint_paths`/`_load_checkpoint`/
`_save_checkpoint`/`clear_checkpoint` -- same order-dependent-on-`pairs`-
list resume gotcha as the WRDS script: if you resume a killed run, pass
the SAME pairs list in the SAME order, or the checkpoint's positional
`n_pairs_done` marker will skip/repeat the wrong pairs).

REWRITTEN for intraday:
- Data loading -- DataStore.load(symbol, tf_label) per Step 0's coverage
  list, following research/structural_break_onset_detection.py's own
  intraday-aware loading pattern (full_universe_scan), NOT WRDS's
  *_1D.parquet-only loader.
- Tier 1 (full-sample EG) is dropped entirely -- ~3yr of 1h data adds
  little beyond what the standard intraday screen (analysis.py) already
  covers at full-sample scale; the whole point here is rolling/episodic
  discovery, so this goes straight to Tier 2/3-equivalent logic.
- Window/step sizing -- NOT a new hardcoded constant. Uses
  research/intraday_episodic_window_sensitivity.py's (Step 1) empirically
  tested `fixed_min_overlap_2x` config as the default: window = 2x
  Config.STATS.MIN_OVERLAP_BY_TF[tf], step = window/4 -- the one config
  that showed PERFECT stability (CV=0.0) in Step 1's real PNC/ZION/KVUE-
  KMB/IQV-Q test, alongside `fixed_min_overlap_1x`'s equally real showing.
  `--window-config` lets a caller pick `fixed_min_overlap_1x` too, if
  Step 6's write-up (docs/FINDINGS.md) later favors it once the full
  real-data comparison is in. `adaptive_halflife_8x` and `onset_anchored`
  (Step 1's other two configs) are deliberately NOT wired in here: both
  are inherently PER-PAIR window choices, and `build_rolling_eg_tasks`/
  `run_rolling_eg_pool` (reused above) take one GLOBAL window/step for
  the whole batch -- making them per-pair-adaptive at full-universe scale
  would mean abandoning the existing batched-pool machinery for a
  per-pair loop, a real efficiency cost not justified without first
  seeing whether it changes the confirmed set materially. Noted as a
  disclosed scope limit, not silently dropped.

Output schema matches the WRDS script's Tier 2/3 windows file exactly
(`symbol_a, symbol_b, window_start, pvalue, window_end_date, fdr_rejected,
fdr_adjusted_pvalue`) so research/pit_pair_discovery.py's
`discover_pit_confirmed_pairs(checkpoint_paths=..., tf_label=...)` can
consume it with ZERO code changes -- verified during planning that both
`checkpoint_paths` and `tf_label` are already keyword args there, not
hardcoded internally.

Synthetic verification FIRST: debug/_verify_intraday_episodic_scan.py --
run that before trusting this script's real-data output.

Usage:
    python research/intraday_episodic_scan.py --tf 1h
    python research/intraday_episodic_scan.py --tf 4h --window-config fixed_min_overlap_1x
"""
import argparse
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from data import DataStore
from analysis import UniverseFilter
from research.wrds_deep_history_episodic_scan import (
    build_rolling_eg_tasks,
    run_rolling_eg_pool,
    rolling_correlation_candidate_pairs,
    episodic_bhfdr_confirm,
    clear_checkpoint,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_COVERAGE_PATH = os.path.join(_OUT_DIR, "intraday_cache_coverage.parquet")

log = logging.getLogger("intraday_episodic_scan")


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def window_config(name: str, tf_label: str) -> tuple:
    """Global (window, step) bar counts for the requested config, per
    Step 1's registry (research/intraday_episodic_window_sensitivity.py).
    Only the two GLOBAL (non-per-pair) configs are valid here -- see the
    module docstring's "REWRITTEN for intraday" section for why."""
    base = Config.STATS.MIN_OVERLAP_BY_TF.get(tf_label, 252)
    if name == "fixed_min_overlap_1x":
        window = base
    elif name == "fixed_min_overlap_2x":
        window = 2 * base
    else:
        raise ValueError(
            f"window-config {name!r} is not valid for the full-universe scanner "
            f"(only fixed_min_overlap_1x/2x are global; adaptive_halflife_8x and "
            f"onset_anchored are per-pair -- see module docstring)"
        )
    step = max(1, window // 4)
    return window, step


def load_universe(tf_label: str, min_bars: int) -> dict:
    """Loads {symbol: close_series} for every symbol in Step 0's coverage
    inventory with enough bars for the requested window, via
    DataStore.load (the same intraday-aware loader
    structural_break_onset_detection.py's full_universe_scan uses), NOT
    the WRDS script's *_1D.parquet-only loader."""
    if not os.path.exists(_COVERAGE_PATH):
        raise FileNotFoundError(
            f"{_COVERAGE_PATH} not found -- run debug/_check_intraday_cache_coverage.py first."
        )
    coverage = pd.read_parquet(_COVERAGE_PATH)
    eligible = coverage[(coverage["tf"] == tf_label) & (coverage["n_bars"] >= min_bars)]
    out = {}
    for symbol in eligible["symbol"]:
        df = DataStore.load(symbol, tf_label)
        if df is not None and not df.empty and "close" in df.columns:
            out[symbol] = df["close"]
    return out


def build_log_prices_and_returns(close_by_symbol: dict, min_overlap: int):
    """Intraday analogue of the WRDS script's function of the same name --
    reimplemented (not imported) because that version's `>= 756` inclusion
    floor is a hardcoded daily-ish-data assumption; here the floor is
    `min_overlap` (the requested config's own window size), so a symbol
    with fewer bars than the window it would need to be tested against is
    correctly excluded rather than silently kept with all-NaN windows."""
    close_df = pd.DataFrame(close_by_symbol).sort_index()
    log_price_df = np.log(close_df.astype(float))
    returns = log_price_df.diff().iloc[1:]
    valid_cols = returns.columns[returns.notna().sum() >= min_overlap]
    return log_price_df[valid_cols], returns[valid_cols]


def run_scan(tf_label: str, window_config_name: str, workers: int = 6, tier3_threshold: float = 0.80) -> dict:
    window, step = window_config(window_config_name, tf_label)
    log.info(f"[{tf_label}] window={window} step={step} (config={window_config_name})")

    close_by_symbol = load_universe(tf_label, min_bars=window)
    log.info(f"[{tf_label}] {len(close_by_symbol)} symbols with >= {window} bars")
    if len(close_by_symbol) < 10:
        log.warning(f"[{tf_label}] fewer than 10 eligible symbols -- aborting this TF.")
        return {}

    log_price_df, returns = build_log_prices_and_returns(close_by_symbol, min_overlap=window)
    symbols = list(returns.columns)
    log.info(f"[{tf_label}] {len(symbols)} symbols survive the {window}-bar overlap floor")
    if len(symbols) < 10:
        log.warning(f"[{tf_label}] fewer than 10 symbols after overlap floor -- aborting.")
        return {}

    asset_class_map = {s: "equity" for s in symbols}  # same disclosed simplification the
    # WRDS script uses (research/wrds_deep_history_episodic_scan.py:666) -- non-gating,
    # descriptive-only field; the intraday cache also holds non-equity symbols, so this
    # tag is known-inaccurate for those, disclosed rather than silently assumed correct.
    threshold = Config.UNIVERSE.MIN_PEARSON_CORR
    corr = UniverseFilter.correlation_matrix(returns.to_numpy().T)
    static_pairs = UniverseFilter.candidate_pairs(corr, symbols, threshold, asset_class_map)
    log.info(f"[{tf_label}] Tier-2-equivalent (static corr prefilter): {len(static_pairs)} candidate pairs")

    results = {}
    max_lag = Config.ANALYSIS.EG_MAX_LAG

    # Save each tier's output IMMEDIATELY after it completes, not batched at
    # the very end of this function -- found the hard way (2026-08-10):
    # Tier 2 alone takes ~55 min at full universe-1h scale, but the original
    # version only wrote results to disk after BOTH tiers finished, so a kill
    # during Tier 3 (which happens routinely, see the repeated-kill
    # investigation in Development.md's Session 31 entry) silently discarded
    # Tier 2's already-completed work, forcing a full from-scratch Tier 2
    # redo on every such kill. Also SKIP a tier entirely if its final output
    # already exists on disk from a prior run -- makes re-invoking this
    # script after a Tier-3 kill genuinely resume from "Tier 2 already done",
    # not just resume Tier 2's own internal batch checkpoint from 0 again.
    os.makedirs(_OUT_DIR, exist_ok=True)

    def _tier_paths(key):
        return {k: os.path.join(_OUT_DIR, f"intraday_episodic_scan_{tf_label}_{k}.parquet")
                for k in (f"{key}_windows", f"{key}_confirmed")}

    tier2_paths = _tier_paths("tier2")
    if all(os.path.exists(p) for p in tier2_paths.values()):
        log.info(f"[{tf_label}][TIER 2] already complete on disk, loading rather than re-running")
        results["tier2_windows"] = pd.read_parquet(tier2_paths["tier2_windows"])
        results["tier2_confirmed"] = pd.read_parquet(tier2_paths["tier2_confirmed"])
    elif static_pairs:
        tier2_flat = run_rolling_eg_pool(
            static_pairs, log_price_df, max_lag, window=window, step=step,
            workers=workers, checkpoint_id=f"intraday_{tf_label}_tier2", checkpoint_every=3,
        )
        clear_checkpoint(f"intraday_{tf_label}_tier2")
        tier2_confirmed = episodic_bhfdr_confirm(tier2_flat, Config.STATS.FDR_ALPHA)
        log.info(f"[{tf_label}][TIER 2] {len(tier2_flat)} (pair,window) tests -> "
                 f"{len(tier2_confirmed)} episodically confirmed")
        results["tier2_windows"] = pd.DataFrame(tier2_flat)
        results["tier2_confirmed"] = pd.DataFrame(tier2_confirmed)
        for key in ("tier2_windows", "tier2_confirmed"):
            results[key].to_parquet(tier2_paths[key], index=False)
            log.info(f"[{tf_label}] Saved -> {tier2_paths[key]} ({len(results[key])} rows)")

    # TIER 3 uses a STRICTER threshold than Tier 2's static prefilter, not the
    # same Config.UNIVERSE.MIN_PEARSON_CORR=0.40 -- found empirically to matter,
    # not assumed. rolling_correlation_candidate_pairs's "correlated in >=1
    # window, not the whole history" relaxation is a real combinatorial
    # explosion at this universe's scale: checked directly at 0.40, it produced
    # 931,731 candidates (12.6x Tier 2's 73,825, which itself took 55 minutes
    # to complete) -- an impractical scope, the same class of problem this
    # project already hit once with cross_timeframe_cointegration.py's
    # full-universe scan (133,993 candidates at a loose threshold, tightened to
    # 1,301 at a stricter one). Swept 0.60/0.70/0.80/0.85 directly (not
    # guessed): 507,460 / 251,285 / 53,972 / 13,376. 0.80 lands closest to
    # Tier 2's own scale (53,972 vs 73,825) without tightening so hard Tier 3
    # loses most of its point (finding pairs the whole-history static filter
    # misses) -- the chosen default, overridable via --tier3-threshold.
    tier3_paths = _tier_paths("tier3")
    if all(os.path.exists(p) for p in tier3_paths.values()):
        log.info(f"[{tf_label}][TIER 3] already complete on disk, loading rather than re-running")
        results["tier3_windows"] = pd.read_parquet(tier3_paths["tier3_windows"])
        results["tier3_confirmed"] = pd.read_parquet(tier3_paths["tier3_confirmed"])
    else:
        log.info(f"[{tf_label}][TIER 3] Rolling correlation prefilter (threshold={tier3_threshold})...")
        tier3_pairs = rolling_correlation_candidate_pairs(
            returns, symbols, tier3_threshold, asset_class_map, window=window, step=step,
        )
        log.info(f"[{tf_label}][TIER 3] {len(tier3_pairs)} candidate pairs "
                 f"(vs Tier 2's {len(static_pairs)} static-corr-prefiltered)")
        if tier3_pairs:
            tier3_flat = run_rolling_eg_pool(
                tier3_pairs, log_price_df, max_lag, window=window, step=step,
                workers=workers, checkpoint_id=f"intraday_{tf_label}_tier3", checkpoint_every=3,
            )
            clear_checkpoint(f"intraday_{tf_label}_tier3")
            tier3_confirmed = episodic_bhfdr_confirm(tier3_flat, Config.STATS.FDR_ALPHA)
            log.info(f"[{tf_label}][TIER 3] {len(tier3_flat)} (pair,window) tests -> "
                     f"{len(tier3_confirmed)} episodically confirmed")
            results["tier3_windows"] = pd.DataFrame(tier3_flat)
            results["tier3_confirmed"] = pd.DataFrame(tier3_confirmed)
            for key in ("tier3_windows", "tier3_confirmed"):
                results[key].to_parquet(tier3_paths[key], index=False)
                log.info(f"[{tf_label}] Saved -> {tier3_paths[key]} ({len(results[key])} rows)")

    return results


def main():
    _setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf", choices=["1h", "4h", "both"], default="1h")
    parser.add_argument("--window-config", choices=["fixed_min_overlap_1x", "fixed_min_overlap_2x"],
                         default="fixed_min_overlap_2x",
                         help="Default is Step 1's empirically most stable config (CV=0.0 on real data).")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--tier3-threshold", type=float, default=0.80,
                         help="Rolling correlation prefilter threshold for Tier 3, stricter than "
                              "Tier 2's static Config.UNIVERSE.MIN_PEARSON_CORR=0.40 by design -- "
                              "swept empirically (0.60/0.70/0.80/0.85 -> 507k/251k/54k/13k "
                              "candidates at 1h), 0.80 is the default because it lands closest to "
                              "Tier 2's own scale (73,825) without over-tightening.")
    args = parser.parse_args()

    tfs = ["1h", "4h"] if args.tf == "both" else [args.tf]
    t0 = time.time()
    for tf_label in tfs:
        run_scan(tf_label, args.window_config, workers=args.workers, tier3_threshold=args.tier3_threshold)
    log.info(f"intraday_episodic_scan.py complete ({(time.time() - t0) / 60:.1f} min)")


if __name__ == "__main__":
    main()
