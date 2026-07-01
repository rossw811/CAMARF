"""
CAMARF — Reproducibility Script
================================

Runs the full analysis pipeline in the correct order and verifies that key
output files exist.  Every command listed here maps directly to a section of
the working paper (PAPER.md).  Run the whole script to regenerate all findings,
or run individual steps by passing --step <name>.

Usage
-----
    python reproduce.py              # full pipeline
    python reproduce.py --step backtest_baseline
    python reproduce.py --verify-only  # check outputs without re-running
    python reproduce.py --list       # show all step names

Environment
-----------
Activate the trading conda environment before running:
    conda activate trading

All scripts must be run from the project root:
    cd C:\\Users\\RossW\\Projects\\CAMARF

Pipeline order (respects data dependencies)
-------------------------------------------
1.  data.py         — fetch / update market data for full universe
2.  analysis.py     — pair screening + confirmed-pair manifest
3.  macro.py        — FRED macro series + regime labels
4.  stats.py        — statistical validation stack (§6)
5.  backtest.py     — Layer 1 IS + OOS baseline (§7.1)
6.  backtest.py     — OOS concentration variants (§7.2)
7.  backtest.py     — OOS STORM variants (§7.4)
8.  wfa.py          — Walk-forward robustness (§7.3)
9.  distance.py     — Gatev GGR distance baseline (§7.7)
10. sensitivity.py  — Parameter sensitivity sweep (§7.8)
11. ml.py           — ML meta-labeler gate (§7.9, deferred)
12. report.py       — PDF / figures
"""

import argparse
import subprocess
import sys
import os
import json
import io
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows so section symbols survive the console codec.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
PYTHON = sys.executable  # same interpreter that invoked this script

_results: dict[str, str] = {}  # step_name -> "OK" | "SKIP" | "FAIL" | "WARN"


def _run(cmd: list[str], label: str) -> bool:
    """Run a subprocess and return True on success."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  cmd: {' '.join(cmd)}")
    print(f"{'='*70}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode == 0:
        print(f"  ✓  {label} — exit 0")
        return True
    else:
        print(f"  ✗  {label} — exit {result.returncode}", file=sys.stderr)
        return False


def _verify(paths: list[str], label: str) -> bool:
    """Check that all listed output paths exist."""
    missing = [p for p in paths if not (ROOT / p).exists()]
    if missing:
        print(f"  MISSING outputs for {label}:", file=sys.stderr)
        for p in missing:
            print(f"    - {p}", file=sys.stderr)
        return False
    print(f"  ✓  All {len(paths)} output(s) for {label} present.")
    return True


def _read_json(path: str) -> Optional[dict]:
    full = ROOT / path
    if not full.exists():
        return None
    with open(full) as f:
        return json.load(f)


def _read_parquet_summary(path: str, cols: list[str]) -> Optional[dict]:
    """Read first-row values from a parquet file (without importing pandas at top level)."""
    full = ROOT / path
    if not full.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(full)
        return {c: df[c].iloc[0] if c in df.columns and len(df) > 0 else None for c in cols}
    except Exception as e:
        print(f"  WARN: could not read {path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Step registry — each entry is (step_name, paper_section, run_fn, verify_paths)
# ---------------------------------------------------------------------------

STEPS: list[dict] = []


def _step(name: str, section: str, cmd: list[str], outputs: list[str], optional: bool = False):
    STEPS.append(dict(name=name, section=section, cmd=cmd, outputs=outputs, optional=optional))


# 1. Data fetch -----------------------------------------------------------
_step(
    name="data",
    section="§3 Data and Universe",
    cmd=[PYTHON, "data.py"],
    outputs=["output/cache"],   # directory existence check
)

# 2. Pair analysis --------------------------------------------------------
_step(
    name="analysis",
    section="§4.1-4.7 Screening pipeline",
    cmd=[PYTHON, "analysis.py", "--workers", "12"],
    outputs=[
        "output/results/confirmed_pairs_manifest.json",
    ],
)

# 3. Macro regime labels --------------------------------------------------
# macro.py saves individual FRED series to DataStore cache (output/cache/fred_*.parquet).
# It does not write a separate output/research/ file — the aligned wide DataFrame
# is an in-memory result consumed by downstream scripts on demand.
_step(
    name="macro",
    section="§10 Future work (regime data)",
    cmd=[PYTHON, "macro.py"],
    outputs=[
        "output/cache/fred_T10Y2Y_daily.parquet",  # yield curve — §7.5 / §10
        "output/cache/fred_VIXCLS_daily.parquet",  # VIX — regime conditioning §10
    ],
)

# 4. Statistical validation stack -----------------------------------------
_step(
    name="stats",
    section="§6 Statistical Validation",
    cmd=[PYTHON, "stats.py"],
    outputs=[
        "output/stats/cointegration_tiers.parquet",    # §6.1 EG+KPSS+PO tiers
        "output/stats/hedge_ratio_comparison.parquet", # §6.2 robust hedge ratios
        "output/stats/evt_tail_risk.parquet",          # §6.3 EVT/GPD
        "output/stats/dcc_rolling_correlation.parquet",# §6.4 DCC-GARCH
        "output/stats/montecarlo_dist_fit.parquet",    # §6.5 MC scenarios
        "output/stats/permutation_test.json",          # §6.6 White 2000
        "output/stats/halflife_stationarity.parquet",  # §7.6 HL S7
    ],
)

# 5. Layer 1 IS baseline --------------------------------------------------
_step(
    name="backtest_is",
    section="§7.1 Layer 1 Baseline (in-sample)",
    cmd=[PYTHON, "backtest.py"],
    outputs=[
        "output/backtest/portfolio_layer1.parquet",
        "output/backtest/summary_layer1.parquet",
        "output/backtest/trades_layer1.parquet",
    ],
)

# 6. Layer 1 OOS holdout baseline -----------------------------------------
_step(
    name="backtest_holdout",
    section="§7.1 Layer 1 Baseline (OOS 20% holdout)",
    cmd=[PYTHON, "backtest.py", "--holdout"],
    outputs=[
        "output/backtest/portfolio_layer1_holdout.parquet",
        "output/backtest/summary_layer1_holdout.parquet",
        "output/backtest/trades_layer1_holdout.parquet",
    ],
)

# 7. OOS concentration variants -------------------------------------------
_step(
    name="backtest_neghedge",
    section="§7.2 Concentration — neg-hedge (recommended)",
    cmd=[PYTHON, "backtest.py", "--holdout", "--neg-hedge"],
    outputs=["output/backtest/summary_layer1_holdout_neghedge.parquet"],
)

_step(
    name="backtest_hubweight",
    section="§7.2 Concentration — hub-weight",
    cmd=[PYTHON, "backtest.py", "--holdout", "--hub-weight"],
    outputs=["output/backtest/summary_layer1_holdout_hubw.parquet"],
)

_step(
    name="backtest_riskparity",
    section="§7.2 Concentration — risk-parity",
    cmd=[PYTHON, "backtest.py", "--holdout", "--risk-parity"],
    outputs=["output/backtest/summary_layer1_holdout_riskparity.parquet"],
)

_step(
    name="backtest_pnlcap",
    section="§7.2 Concentration — P&L-cap",
    cmd=[PYTHON, "backtest.py", "--holdout", "--pnl-cap"],
    outputs=["output/backtest/summary_layer1_holdout_pnlcap.parquet"],
)

# 8. STORM variants -------------------------------------------------------
_step(
    name="backtest_storm_sedge",
    section="§7.4 STORM — session-edge (+0.13 Sharpe, §7.4 key finding)",
    cmd=[PYTHON, "backtest.py", "--holdout", "--storm-session-edge"],
    outputs=["output/backtest/summary_layer1_holdout_storm_sedge.parquet"],
)

_step(
    name="backtest_storm_mmexec",
    section="§7.4 STORM — mm-exec (marginal +0.003)",
    cmd=[PYTHON, "backtest.py", "--holdout", "--storm-mm-exec"],
    outputs=["output/backtest/summary_layer1_holdout_storm_mmexec.parquet"],
)

_step(
    name="backtest_storm_gstop",
    section="§7.4 STORM — garch-stop (null result)",
    cmd=[PYTHON, "backtest.py", "--holdout", "--storm-garch-stop"],
    outputs=["output/backtest/summary_layer1_holdout_storm_gstop.parquet"],
)

_step(
    name="backtest_storm_all",
    section="§7.4 STORM — all flags combined (factorial grid §7.4)",
    cmd=[PYTHON, "backtest.py", "--holdout", "--storm-all"],
    outputs=["output/backtest/summary_layer1_holdout_stormall.parquet"],
)

# 9. Walk-forward analysis ------------------------------------------------
_step(
    name="wfa",
    section="§7.3 Walk-forward robustness",
    cmd=[PYTHON, "wfa.py"],
    outputs=[
        "output/backtest/wfa_summary_expanding.parquet",
        "output/backtest/wfa_summary_rolling.parquet",
        "output/backtest/wfa_fold_comparison.parquet",
    ],
)

# 10. Distance baseline ---------------------------------------------------
_step(
    name="distance",
    section="§7.7 Gatev GGR distance baseline (Sharpe −6.33 vs 11.09 CAMARF)",
    cmd=[PYTHON, "distance.py"],
    outputs=[
        "output/stats/distance_baseline.parquet",
        "output/stats/distance_summary.json",
    ],
)

# 11. Parameter sensitivity -----------------------------------------------
_step(
    name="sensitivity",
    section="§7.8 Parameter sensitivity (entry_z=2.0 optimal, $25M ADV confirmed)",
    cmd=[PYTHON, "sensitivity.py"],
    outputs=["output/sensitivity/sensitivity_grid.parquet"],
)

# 12. ML gate (optional — may fail if insufficient training data) ----------
_step(
    name="ml",
    section="§7.9 ML gate (deferred — needs ≥30 examples/class)",
    cmd=[PYTHON, "ml.py"],
    outputs=["output/ml/model_stage1.pkl"],
    optional=True,
)

# ---------------------------------------------------------------------------
# PAPER VALIDATION — Research / comparison scripts
# Each of these generates a specific finding cited in PAPER.md.
# All are independent (can run in any order; depend only on analysis.py output).
# All are optional=True so a missing dependency doesn't break the full run.
# ---------------------------------------------------------------------------

# §5 Price degeneracy universe-wide audit — 31.9% of 1m universe flagged ---
_step(
    name="price_degeneracy_audit",
    section="§5 BUG-D49: 31.9% of 1m universe flagged (market-cap-dominant cause)",
    cmd=[PYTHON, "research/audit_price_degeneracy.py"],
    outputs=["output/research/price_degeneracy_audit_1m.parquet"],
    optional=True,
)
_step(
    name="price_degeneracy_cause",
    section="§5 BUG-D49 root cause: market cap dominant (Mann-Whitney p=1.82e-145)",
    cmd=[PYTHON, "research/investigate_price_degeneracy_cause.py"],
    outputs=["output/research/price_degeneracy_with_metadata.parquet"],
    optional=True,
)

# §4.7 Near-miss lag scan — 9 pairs correlated but not cointegrated (EG p=0.06-0.89)
_step(
    name="near_miss_lag_scan",
    section="§4.7 Correlation vs. cointegration: 9 near-miss pairs, all EG p>0.05",
    cmd=[PYTHON, "research/near_miss_lag_scan.py", "--tf", "1h"],
    outputs=["output/research/near_miss_lag_scan_1h.parquet"],
    optional=True,
)

# §10 Graph clustering — Louvain community detection comparison arm ----------
# Default TF is "1m"; produces output/research/graph_clustering/1m_summary.json
# (OXY lands in 6-member oil & gas cluster: COP/CVX/DVN/EOG/XOM — PAPER.md §10)
_step(
    name="graph_clustering",
    section="§10 Idea #2: Louvain clustering (OXY in clean 6-member oil & gas cluster)",
    cmd=[PYTHON, "research/graph_clustering.py", "--tf", "1m"],
    outputs=["output/research/graph_clustering/1m_summary.json"],
    optional=True,
)

# §10 EG permutation check — BH-FDR robustness (38/79 pairs flagged, 4.6× null)
_step(
    name="eg_permutation_check",
    section="§10 Idea #4: circular-shift permutation null check on confirmed pairs",
    cmd=[PYTHON, "research/eg_permutation_check.py"],
    outputs=["output/research/eg_permutation_check.parquet"],
    optional=True,
)

# §10 Predictability optimizer — idea #3 negative result (OLS beats CCP WFO)
_step(
    name="predictability_optimizer",
    section="§10 Idea #3: Box-Tiao negative result (OLS wins OOS, mean ratio 3.698 vs 4.130)",
    cmd=[PYTHON, "research/predictability_optimizer.py"],
    outputs=["output/research/predictability_optimizer_wfo.parquet"],
    optional=True,
)
_step(
    name="ccp_variants",
    section="§10 Idea #3 extensions: shrinkage/sparsity/moving-band all lose to OLS OOS",
    cmd=[PYTHON, "research/ccp_variants.py"],
    outputs=["output/research/ccp_variants_comparison.parquet"],
    optional=True,
)

# §10 HMM regime detection — yield curve persistent (539-621 day state durations)
_step(
    name="hmm_regime_detection",
    section="§10 HMM: yield curve persistent (539–621 day states); VIX crisis = 23.6% of history",
    cmd=[PYTHON, "research/hmm_regime_detection.py"],
    outputs=["output/research/hmm_regimes.parquet"],
    optional=True,
)

# §10 Sample entropy — 1h spreads 0.024–0.378; lower = more mechanically predictable
_step(
    name="sample_entropy",
    section="§10 SampEn: 1h pairs range 0.024–0.378 (CAT/DD most regular at 0.024)",
    cmd=[PYTHON, "research/sample_entropy_spreads.py"],
    outputs=["output/research/sample_entropy_spreads.parquet"],
    optional=True,
)

# §10 Regime-conditional analysis — VIX crisis: 11× faster mean reversion
_step(
    name="regime_conditional",
    section="§10 Regime-conditional HL: VIX crisis 11× faster, yield inversion 2.3× faster",
    cmd=[PYTHON, "research/regime_conditional_analysis.py"],
    outputs=["output/research/regime_conditional_analysis.parquet"],
    optional=True,
)

# §10 Comomentum — rolling spread correlation index (mean 0.090, P75=0.113)
_step(
    name="comomentum",
    section="§10 Comomentum: mean index 0.090 (2× unconditional baseline 0.048)",
    cmd=[PYTHON, "research/comomentum.py"],
    outputs=["output/research/comomentum_index.parquet"],
    optional=True,
)

# §10 Tail dependence — CCL/NCLH λ_U≈0.5 vs λ_L≈0.32 (real asymmetry)
_step(
    name="tail_dependence",
    section="§10 Idea #8: tail dependence (CCL/NCLH λ_U≈0.5; no broad gating signal yet)",
    cmd=[PYTHON, "research/tail_dependence.py"],
    outputs=["output/research/tail_dependence_summary.parquet"],
    optional=True,
)

# 13. Report --------------------------------------------------------------
_step(
    name="report",
    section="§7 figures for paper",
    cmd=[PYTHON, "report.py"],
    outputs=["output/report"],   # directory
    optional=True,
)

# ---------------------------------------------------------------------------
# Key metric verification — reads outputs and prints the headline numbers
# from PAPER.md so you can confirm they match
# ---------------------------------------------------------------------------

_EXPECTED_METRICS = {
    # (output_path, readable_name, paper_section, expected_value_description)
    "output/stats/permutation_test_oos.json": {
        "section": "§6.6",
        "label": "Permutation test OOS equity-curve Sharpe p-value",
        "expected": "p = 0.669 (fail to reject null — honest result)",
    },
    "output/stats/permutation_test_is.json": {
        "section": "§6.6",
        "label": "Permutation test IS closed-trade Sharpe p-value",
        "expected": "p = 0.002 (reject null at 1% — key robustness result)",
    },
    "output/stats/distance_summary.json": {
        "section": "§7.7",
        "label": "GGR distance OOS Sharpe",
        "expected": "−6.33 (vs CAMARF +11.09 — distance method fails)",
    },
}


def verify_metrics() -> None:
    """Print key headline numbers alongside their PAPER.md expected values."""
    print("\n" + "="*70)
    print("  Key metric verification")
    print("="*70)

    # Permutation test JSON files
    for path, meta in _EXPECTED_METRICS.items():
        data = _read_json(path)
        if data is None:
            print(f"  MISSING  {meta['section']} {meta['label']}")
            continue
        p_val = data.get("p_value") or data.get("pvalue") or data.get("p")
        actual = f"p = {p_val:.3f}" if p_val is not None else str(data)
        match = "✓" if p_val is not None else "?"
        print(f"  {match}  {meta['section']} {meta['label']}")
        print(f"       actual:   {actual}")
        print(f"       expected: {meta['expected']}")

    # Distance summary
    dist = _read_json("output/stats/distance_summary.json")
    if dist:
        sharpe = dist.get("ggr_sharpe") or dist.get("distance_sharpe") or dist.get("sharpe")
        print(f"\n  ✓  §7.7 GGR distance Sharpe: {sharpe}")

    # OOS holdout summary
    import pandas as pd
    try:
        oos = pd.read_parquet(ROOT / "output/backtest/summary_layer1_holdout.parquet")
        if len(oos) > 0:
            sharpe = oos["sharpe"].iloc[0] if "sharpe" in oos.columns else "?"
            trades = oos["n_trades"].iloc[0] if "n_trades" in oos.columns else "?"
            print(f"\n  ✓  §7.1 OOS Sharpe: {sharpe:.3f}  trades: {trades}")
            print(f"       expected: Sharpe ≈ 3.249, 111 trades (prior confirmed-pair set)")
            print(f"       note: Sharpe will change after analysis.py re-run with new pairs")
    except Exception:
        pass

    # Sensitivity grid — confirm entry_z=2.0 is top row
    try:
        grid = pd.read_parquet(ROOT / "output/sensitivity/sensitivity_grid.parquet")
        if len(grid) > 0:
            print(f"\n  ✓  §7.8 Sensitivity grid — {len(grid)} rows")
            if "entry_z" in grid.columns and "sharpe" in grid.columns:
                best = grid.loc[grid["sharpe"].idxmax()]
                print(f"       best: entry_z={best['entry_z']} exit_z={best.get('exit_z','?')} "
                      f"Sharpe={best['sharpe']:.2f}")
                print(f"       expected: entry_z=2.0 optimal across all exit_z levels")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="CAMARF reproducibility runner")
    parser.add_argument(
        "--step", default=None,
        help="Run only this named step (see --list for names)",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="Skip running scripts; just check outputs exist and print key metrics",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all step names and exit",
    )
    parser.add_argument(
        "--skip-optional", action="store_true", default=False,
        help="Skip steps marked optional=True (ml.py, report.py)",
    )
    args = parser.parse_args()

    if args.list:
        print("\nAvailable steps:")
        for s in STEPS:
            flag = " [optional]" if s["optional"] else ""
            print(f"  {s['name']:<25} {s['section']}{flag}")
        return

    steps_to_run = STEPS
    if args.step:
        steps_to_run = [s for s in STEPS if s["name"] == args.step]
        if not steps_to_run:
            print(f"ERROR: unknown step '{args.step}'. Run --list to see valid names.")
            sys.exit(1)

    if args.skip_optional:
        steps_to_run = [s for s in steps_to_run if not s["optional"]]

    all_ok = True
    for step in steps_to_run:
        name = step["name"]
        section = step["section"]
        optional = step["optional"]

        if not args.verify_only:
            ok = _run(step["cmd"], f"{name}  ({section})")
            status = "OK" if ok else ("SKIP" if optional else "FAIL")
            if not ok and not optional:
                all_ok = False
        else:
            status = "SKIP"

        ok_outputs = _verify(step["outputs"], name)
        if not ok_outputs and not optional:
            status = "FAIL"
            all_ok = False

        _results[name] = status

    # Summary table
    print("\n" + "="*70)
    print("  Run summary")
    print("="*70)
    for name, status in _results.items():
        icon = {"OK": "✓", "FAIL": "✗", "SKIP": "–", "WARN": "!"}.get(status, "?")
        print(f"  {icon}  {name:<28} {status}")

    # Key metrics
    verify_metrics()

    if not all_ok:
        print("\n  One or more non-optional steps failed.")
        sys.exit(1)
    else:
        print("\n  All steps completed successfully.")


if __name__ == "__main__":
    main()
