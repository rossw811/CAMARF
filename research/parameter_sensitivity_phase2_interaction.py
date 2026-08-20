"""
research/parameter_sensitivity_phase2_interaction.py -- Thread G Phase 2:
interaction study on Phase 1's real survivors (entry_zscore, hedge_method;
capital_sizing_method excluded -- Phase 1 found it untestable at this
universe's trade volume, see docs/FINDINGS.md #25).

Reduced factorial: entry_z grid (4) x hedge grid (3) = 12 combinations,
IS + OOS each, against the real 182-pair Purity universe, --capital-sim.
Answers "does entry_z's effect on Sharpe depend on hedge method" -- a real
interaction, not just two independent marginal effects (Phase 1's OAT
screen could not distinguish these).

Usage:
    python research/parameter_sensitivity_phase2_interaction.py
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from research.parameter_sensitivity_screen import _ARCHIVE_DIR

ENTRY_Z_GRID = [1.5, 2.0, 2.5, 3.0]
HEDGE_GRID = ["both", "ols", "kalman"]
RESULTS_PATH = os.path.join(_ARCHIVE_DIR, "phase2_interaction_results.parquet")


def run_combo(entry_z, hedge, holdout):
    kwargs = {"entry_z": None, "hedge": "both", "capital_sizing": "fixed"}
    kwargs["entry_z"] = entry_z
    kwargs["hedge"] = hedge
    kwargs["holdout"] = holdout
    # run_one is written for single-parameter sweeps (param_kwarg, value) --
    # call the underlying builder directly instead via a thin local re-impl
    # of its body, since we need two varying kwargs at once.
    from research.parameter_sensitivity_screen import build_cmd, _ROOT, _BACKTEST_OUT_DIR
    import glob, shutil, subprocess, sys, time

    pre_ts = time.time()
    cmd = build_cmd(entry_z=entry_z, hedge=hedge, capital_sizing="fixed", holdout=holdout)
    result = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        return None, (result.stdout[-2000:] + "\n" + result.stderr[-2000:])
    candidates = glob.glob(os.path.join(_BACKTEST_OUT_DIR, "portfolio_layer1*capsim*.parquet"))
    fresh = [f for f in candidates if os.path.getmtime(f) >= pre_ts - 1]
    if not fresh:
        return None, "no fresh portfolio_*_capsim_*.parquet found after run"
    newest = max(fresh, key=os.path.getmtime)
    df = pd.read_parquet(newest)
    if df.empty:
        return None, f"{newest} is empty (0 trades taken)"
    row = df.iloc[0].to_dict()
    split = "oos" if holdout else "is"
    archive_name = f"interaction_ez{str(entry_z).replace('.', '')}_{hedge}_{split}.parquet"
    shutil.copy2(newest, os.path.join(_ARCHIVE_DIR, archive_name))
    return row, None


def main():
    os.makedirs(_ARCHIVE_DIR, exist_ok=True)
    all_rows = []
    for entry_z, hedge in itertools.product(ENTRY_Z_GRID, HEDGE_GRID):
        for holdout in (False, True):
            split = "OOS" if holdout else "IS"
            print(f"entry_z={entry_z} hedge={hedge!r} [{split}] ...", end=" ", flush=True)
            row, err = run_combo(entry_z, hedge, holdout)
            if row is None:
                print(f"FAILED: {err}")
                all_rows.append({"entry_z": entry_z, "hedge": hedge, "split": split,
                                  "sharpe_portfolio": float("nan"), "n_taken": None, "error": err})
                continue
            print(f"sharpe={row.get('sharpe_portfolio'):.4f} n_taken={row.get('n_taken')}")
            all_rows.append({"entry_z": entry_z, "hedge": hedge, "split": split,
                              "sharpe_portfolio": row.get("sharpe_portfolio"),
                              "n_taken": row.get("n_taken"), "n_total": row.get("n_total"),
                              "final_equity": row.get("final_equity"), "error": None})

    df = pd.DataFrame(all_rows)
    df.to_parquet(RESULTS_PATH)
    print(f"\nSaved -> {RESULTS_PATH} ({len(df)} rows)")

    print("\n=== IS pivot (rows=entry_z, cols=hedge) ===")
    is_pivot = df[df["split"] == "IS"].pivot(index="entry_z", columns="hedge", values="sharpe_portfolio")
    print(is_pivot.to_string())
    print("\n=== OOS pivot (rows=entry_z, cols=hedge) ===")
    oos_pivot = df[df["split"] == "OOS"].pivot(index="entry_z", columns="hedge", values="sharpe_portfolio")
    print(oos_pivot.to_string())

    # Interaction check: is hedge's BEST choice consistent across entry_z levels?
    # If the best hedge method flips depending on entry_z, that's a real interaction,
    # not just two independent marginal effects.
    print("\n=== Best hedge method per entry_z level (interaction check) ===")
    for split_name, pivot in (("IS", is_pivot), ("OOS", oos_pivot)):
        best_hedge_per_z = pivot.idxmax(axis=1)
        print(f"  {split_name}: {dict(best_hedge_per_z)}")
        consistent = best_hedge_per_z.nunique() == 1
        print(f"  {split_name} best hedge consistent across all entry_z levels: {consistent}")


if __name__ == "__main__":
    main()
