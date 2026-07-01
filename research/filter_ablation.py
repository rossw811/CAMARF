"""
CAMARF filter_ablation.py — exploratory diagnostic, NOT part of the
production pipeline.

Motivated by a 2026-06-30 discussion with Ross: when a pipeline has several
sequential filters, it's easy to end up with a filter (or combination of
filters) that quietly discards pairs that would actually have traded well —
the filter's existence isn't itself evidence it's net-positive. This script
answers that directly for the two filters where a genuine counterfactual is
actually possible with data this project persists:

  - the coint_fraction_rolling threshold + secondary-evidence override
    (analysis.py's Config.UNIVERSE.MIN_COINT_FRAC gate)
  - the structural-pair exclusion (forex triangles, same-company share
    classes)

Scope limit, stated explicitly rather than silently: the Pearson pre-filter,
Engle-Granger+BH-FDR, and price-degeneracy filters are NOT covered here.
Pairs cut by Pearson or EG+FDR never get a hedge ratio/spread model built at
all (no PairResult object exists for them), so there is nothing to
counterfactually backtest. Price-degeneracy-excluded pairs are dropped one
step earlier in analysis.py's _run_one_tf(), before all_candidates.parquet
is even written, so their spread_series was never persisted either — and
arguably a spread built on a price-degenerate series (2-7 distinct closes)
isn't a meaningful counterfactual to test in the first place.

Data dependency: requires analysis.py to have been (re-)run with the
Phase-1 filter-ablation persistence change (all_candidates.parquet +
spread_series for the full pre-coint_frac/pre-structural pair set, not just
the final confirmed set) — see analysis.py's _save_tf_results() docstring
comments dated 2026-06-30 for the exact mechanism.

Method: for each timeframe with an all_candidates.parquet, split the
candidates into (a) structural exclusions, recomputed via the same
CrossAssetTagger classifiers analysis.py itself uses (not re-derived
independently — this must match production exactly), and (b) coint_frac
exclusions (whatever's left in all_candidates that isn't in the final
pairs.parquet). Write each excluded group to a --pairs-override file and
invoke backtest.py as a subprocess (IS and OOS holdout) to get the real
counterfactual Sharpe/P&L, then report it next to the actual confirmed-pair
baseline for the same TF.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from analysis import CrossAssetTagger
from backtest import _TF_DIRS

_PYTHON = sys.executable
_RESULTS_DIR = "output/results"
_OUT_DIR = "output/research"


def _run_backtest_override(pairs_df: pd.DataFrame, tf_label: str, holdout: bool) -> dict:
    """Write pairs_df to a temp override file, invoke backtest.py, read back
    the portfolio-level stats parquet it writes. Returns {} if backtest.py
    produced no trades for this subset (a legitimate, reportable outcome,
    not an error)."""
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = f.name
    try:
        pairs_df.to_parquet(tmp_path, index=False)
        label = "layer1"
        if holdout:
            label += "_holdout"
        label += "_pairsoverride"
        cmd = [
            _PYTHON, "backtest.py",
            "--tf", tf_label,
            "--pairs-override", tmp_path,
        ]
        if holdout:
            cmd.append("--holdout")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"    backtest.py failed (rc={result.returncode}): {result.stderr[-500:]}")
            return {}
        portfolio_path = os.path.join("output", "backtest", f"portfolio_{label}.parquet")
        if not os.path.exists(portfolio_path):
            return {}
        stats = pd.read_parquet(portfolio_path).iloc[0].to_dict()
        os.remove(portfolio_path)  # don't let counterfactual runs pollute real output dir
        return stats
    finally:
        os.remove(tmp_path)


def main():
    os.makedirs(_OUT_DIR, exist_ok=True)
    rows = []

    for tf_dir, tf_label in _TF_DIRS:
        cand_path = os.path.join(_RESULTS_DIR, tf_dir, "all_candidates.parquet")
        pairs_path = os.path.join(_RESULTS_DIR, tf_dir, "pairs.parquet")
        if not os.path.exists(cand_path) or not os.path.exists(pairs_path):
            print(f"[{tf_label}] SKIP: missing all_candidates.parquet or pairs.parquet "
                  f"(rerun analysis.py with the Phase-1 persistence change)")
            continue

        all_candidates = pd.read_parquet(cand_path)
        confirmed = pd.read_parquet(pairs_path)
        confirmed_keys = set(zip(confirmed["symbol_a"], confirmed["symbol_b"]))

        is_structural = all_candidates.apply(
            lambda r: CrossAssetTagger._shared_currency(r["symbol_a"], r["symbol_b"])
            or CrossAssetTagger._is_share_class_pair(r["symbol_a"], r["symbol_b"]),
            axis=1,
        )
        structural_excluded = all_candidates[is_structural]
        non_structural = all_candidates[~is_structural]
        coint_frac_excluded = non_structural[
            ~non_structural.apply(
                lambda r: (r["symbol_a"], r["symbol_b"]) in confirmed_keys, axis=1
            )
        ]

        print(f"[{tf_label}] {len(all_candidates)} candidates, {len(confirmed)} confirmed, "
              f"{len(structural_excluded)} structural-excluded, "
              f"{len(coint_frac_excluded)} coint_frac-excluded")

        for filter_name, excluded_df in [
            ("structural_exclusion", structural_excluded),
            ("coint_frac_threshold", coint_frac_excluded),
        ]:
            if excluded_df.empty:
                continue
            is_stats = _run_backtest_override(excluded_df, tf_label, holdout=False)
            oos_stats = _run_backtest_override(excluded_df, tf_label, holdout=True)
            rows.append({
                "tf_label": tf_label,
                "filter": filter_name,
                "n_excluded": len(excluded_df),
                "is_sharpe": is_stats.get("sharpe_portfolio"),
                "is_trades": is_stats.get("n_trades_total"),
                "is_pnl": is_stats.get("total_pnl_portfolio"),
                "oos_sharpe": oos_stats.get("sharpe_portfolio"),
                "oos_trades": oos_stats.get("n_trades_total"),
                "oos_pnl": oos_stats.get("total_pnl_portfolio"),
            })

    if not rows:
        print("No filter-ablation results produced — see SKIP messages above.")
        return

    report = pd.DataFrame(rows)
    out_path = os.path.join(_OUT_DIR, "filter_ablation.parquet")
    report.to_parquet(out_path, index=False)
    print(f"\nSaved {len(report)} rows -> {out_path}\n")
    print(report.to_string(index=False))
    print(
        "\nInterpretation: a filter is net-positive if the pairs it excludes "
        "would have produced a WORSE OOS Sharpe than the confirmed baseline "
        "(see the confirmed set's own OOS Sharpe in PAPER.md §7.1). A filter "
        "that excludes pairs with a comparable or better counterfactual OOS "
        "Sharpe is a candidate for loosening, not evidence the filter is "
        "wrong outright — small-n counterfactual subsets are noisy."
    )


if __name__ == "__main__":
    main()
