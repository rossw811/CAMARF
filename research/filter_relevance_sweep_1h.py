"""
research/filter_relevance_sweep_1h.py — comparison/diagnostic script, NOT
part of the production pipeline.

Companion to research/filter_ablation.py, built specifically to close a
gap that script cannot close: analysis.py's own persistence of
all_candidates.parquet/spread_series_*.parquet/pairs.parquet is entirely
gated behind `if discovered_pairs:` (the FINAL post-coint_frac/
post-structural set) — see analysis.py ~line 5468-5591. When a timeframe's
funnel collapses to ZERO final confirmed pairs (as 1h did in the
2026-07-21 06:14 run: 2 pairs survived EG+FDR, then coint_frac cut 1,
structural exclusion cut the last 1), NOTHING is persisted, including the
candidate-level detail filter_ablation.py needs to build a counterfactual.
This is itself a real finding (documented in Development.md), not just an
inconvenience — the pipeline's persistence design makes exactly the most
diagnostically-interesting case (a timeframe going from some candidates to
zero) invisible after the fact.

This script rebuilds that missing detail for 1h specifically (the single
most decision-relevant timeframe) by reusing PRODUCTION functions directly
for fidelity — no reimplementation of EG, hedge-ratio estimation, or the
spread model:
  - aligned_pair_loader.load_aligned_pair (same DataAligner path production uses)
  - analysis.py's _eg_worker, _rolling_coint_worker (same EG/rolling-coint tests)
  - analysis.py's AnalysisPipeline._build_pair_result (same hedge-ratio/
    spread-model/half-life/Hurst/decay-test construction)
  - backtest.py's BacktestEngine.run() + compute_metrics (same event-driven
    backtest engine, IS and holdout)

Identifies the 2 pairs that survived 1h's EG+FDR step from the features_*
files analysis.py DID persist before the discovered_pairs gate
(features_PNC.parquet, features_SPY.parquet, features_VOO.parquet,
features_ZION.parquet) -- these 4 assets across exactly 2 pairs, consistent
with PNC/ZION and SPY/VOO (SPY/VOO already known from CrossAssetTagger as a
structural index-tracking exclusion; PNC/ZION is the natural remaining
candidate).

Usage:
    python research/filter_relevance_sweep_1h.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from analysis import (
    AnalysisPipeline, CrossAssetTagger, Config, _eg_worker, _rolling_coint_worker,
)
from backtest import BacktestEngine, RegimeConditioner, MLConditioner, compute_metrics

_TF_LABEL = "1h"
_CANDIDATE_PAIRS = [("PNC", "ZION"), ("SPY", "VOO")]


def analyze_pair(sym_a, sym_b):
    df_a, df_b = load_aligned_pair(sym_a, sym_b, _TF_LABEL)
    if df_a is None or df_b is None:
        return {"symbol_a": sym_a, "symbol_b": sym_b, "status": "no_data"}

    log_a = np.log(df_a["close"].values.astype(float))
    log_b = np.log(df_b["close"].values.astype(float))

    max_lag = Config.ANALYSIS.EG_MAX_LAG
    eg_result = _eg_worker((sym_a, sym_b, log_a, log_b, max_lag, _TF_LABEL))
    if not eg_result.get("ok"):
        return {"symbol_a": sym_a, "symbol_b": sym_b, "status": "eg_failed",
                "eg_error": eg_result.get("error")}

    rc_result = _rolling_coint_worker((sym_a, sym_b, log_a, log_b, 252, 21, _TF_LABEL))
    coint_frac = rc_result.get("fraction", np.nan)

    is_structural = (
        CrossAssetTagger._shared_currency(sym_a, sym_b)
        or CrossAssetTagger._is_share_class_pair(sym_a, sym_b)
        or CrossAssetTagger._is_index_tracking_pair(sym_a, sym_b)
    )

    pd_meta = {
        "symbol_a": sym_a, "symbol_b": sym_b,
        "asset_class_a": "unknown", "asset_class_b": "unknown",
        "is_cross_asset": False,
        "pearson_corr": np.nan,  # not needed downstream for this counterfactual
        "coint_pvalue_raw": eg_result["pvalue"],
        "coint_pvalue_adjusted": eg_result["pvalue"],  # single-pair test, no FDR pool here
        "coint_fraction_rolling": coint_frac,
    }
    aligned_data = {sym_a: df_a, sym_b: df_b}
    built = AnalysisPipeline._build_pair_result(pd_meta, aligned_data, _TF_LABEL)
    if built is None:
        return {"symbol_a": sym_a, "symbol_b": sym_b, "status": "build_pair_result_failed"}
    pair_result, per_bar = built

    min_coint_frac = getattr(Config.UNIVERSE, "MIN_COINT_FRAC", 0.70)
    passes_coint_frac = (not np.isfinite(coint_frac)) or coint_frac >= min_coint_frac
    passes_secondary = AnalysisPipeline.passes_coint_frac_secondary_evidence(pair_result)

    spread_df = pd.DataFrame({
        "spread": per_bar["spread"],
        "z_rolling": per_bar["z_rolling"],
        "z_expanding": per_bar["z_expanding"],
        "half_life_rolling": per_bar["half_life_rolling_series"],
        "gap_flag_a": per_bar["gap_flag_a"],
        "gap_flag_b": per_bar["gap_flag_b"],
        "hedge_ratio_ols_t": per_bar.get("hedge_ratio_ols_t"),
        "hedge_ratio_kalman_t": per_bar.get("hedge_ratio_kalman_t"),
    }, index=per_bar["index"])

    pair_row = pd.Series({
        "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": _TF_LABEL,
        "hedge_ratio_ols": pair_result.hedge_ratio_ols,
        "hedge_ratio_kalman_mean": pair_result.hedge_ratio_kalman_mean,
        "half_life_rolling": pair_result.half_life_rolling,
        "hurst_rs": pair_result.hurst_rs,
    })

    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
    )
    trades_is = engine.run(pair_row, spread_df, "ols")
    trades_holdout = engine.run(pair_row, spread_df, "ols", holdout_only=True)
    m_is = compute_metrics(trades_is, _TF_LABEL, sym_a, sym_b, "ols") if trades_is else {}
    m_holdout = compute_metrics(trades_holdout, _TF_LABEL, sym_a, sym_b, "ols") if trades_holdout else {}

    return {
        "symbol_a": sym_a, "symbol_b": sym_b, "status": "ok",
        "eg_pvalue": eg_result["pvalue"], "n_overlap": eg_result["n_overlap"],
        "coint_fraction_rolling": coint_frac,
        "passes_coint_frac_threshold": bool(passes_coint_frac),
        "passes_secondary_evidence_override": bool(passes_secondary),
        "half_life_trend_slope": pair_result.half_life_trend_slope,
        "zivot_andrews_break": pair_result.zivot_andrews_break,
        "cusum_first_excursion": pair_result.cusum_first_excursion,
        "is_structural_exclusion": bool(is_structural),
        "is_trades": m_is.get("n_trades", 0), "is_sharpe": m_is.get("sharpe"),
        "is_pnl": m_is.get("total_pnl"),
        "holdout_trades": m_holdout.get("n_trades", 0), "holdout_sharpe": m_holdout.get("sharpe"),
        "holdout_pnl": m_holdout.get("total_pnl"),
    }


def main():
    print(f"=== Filter-relevance reconstruction for {_TF_LABEL} "
          f"(analysis.py's own persistence never ran for this TF: 0 final confirmed pairs) ===\n")
    rows = []
    for sym_a, sym_b in _CANDIDATE_PAIRS:
        r = analyze_pair(sym_a, sym_b)
        rows.append(r)
        if r.get("status") == "ok":
            print(f"{sym_a}/{sym_b}: EG p={r['eg_pvalue']:.4g}  coint_frac={r['coint_fraction_rolling']:.3f} "
                  f"(passes {Config.UNIVERSE.MIN_COINT_FRAC:.2f} threshold: {r['passes_coint_frac_threshold']})  "
                  f"secondary_evidence_override={r['passes_secondary_evidence_override']}  "
                  f"structural_exclusion={r['is_structural_exclusion']}")
            print(f"    half_life_trend_slope={r['half_life_trend_slope']}  "
                  f"zivot_andrews_break={r['zivot_andrews_break']}  cusum_first_excursion={r['cusum_first_excursion']}")
            print(f"    IS: n={r['is_trades']} sharpe={r['is_sharpe']} pnl={r['is_pnl']}  |  "
                  f"Holdout: n={r['holdout_trades']} sharpe={r['holdout_sharpe']} pnl={r['holdout_pnl']}")
        else:
            print(f"{sym_a}/{sym_b}: {r.get('status')} {r.get('eg_error', '')}")

    out_dir = "output/research"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"filter_relevance_sweep_{_TF_LABEL}.parquet")
    pd.DataFrame(rows).to_parquet(out_path)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
