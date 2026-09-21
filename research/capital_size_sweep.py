"""
research/capital_size_sweep.py -- systematic sweep of backtest.py's
--capital-account-size against a fixed pairs-override/gate combination, to
properly characterize the capital_sim headline-metric question flagged
repeatedly during the 2026-09-15/16 squeeze/momentum investigation
(docs/HANDOFF.md): a 4-point ad hoc sweep ($100k/$250k/$500k/$1M) showed a
NOISY, non-monotonic relationship between account size and headline Sharpe,
not a clean trend -- this script runs a much finer/broader grid in one
organized pass, same "run once, archive before the next point can clobber
it" discipline as research/parameter_sensitivity_screen.py, rather than
continuing ad hoc one-off runs.

Each grid point runs backtest.py once (IS only by default; --include-oos adds
a second --holdout run per point, doubling total runs), reads the resulting
portfolio_*_capsim_*.parquet's sharpe_portfolio and n_taken, and archives a
copy under output/research/capital_size_sweep/ before the next point's run
can overwrite the canonical output/backtest/ files (same _storm-suffix
collision risk documented all night for every other multi-run comparison in
this project).

Usage:
    python research/capital_size_sweep.py --pairs-override output/research/purity_pairs.parquet \\
        --storm-flag storm_momentum_gate --grid 50000 75000 100000 150000 200000 250000 \\
        350000 500000 750000 1000000 1500000 2000000
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PYTHON = sys.executable
_BACKTEST_OUT_DIR = os.path.join(_ROOT, "output", "backtest")
_ARCHIVE_DIR = os.path.join(_ROOT, "output", "research", "capital_size_sweep")

_DEFAULT_GRID = [
    50_000, 75_000, 100_000, 150_000, 200_000, 250_000, 350_000, 500_000,
    750_000, 1_000_000, 1_500_000, 2_000_000,
]

# CLI flag name -> the --storm-<flag> argument backtest.py actually accepts.
_STORM_FLAG_ARGS = {
    "storm_squeeze_gate": "--storm-squeeze-gate",
    "storm_momentum_gate": "--storm-momentum-gate",
    "storm_squeeze_momentum_gate": "--storm-squeeze-momentum-gate",
}


def build_cmd(pairs_override: str, account_size: int, storm_flag: str = None,
              holdout: bool = False) -> list:
    cmd = [
        _PYTHON, "backtest.py",
        "--pairs-override", pairs_override,
        "--capital-sim",
        "--capital-account-size", str(account_size),
    ]
    if storm_flag:
        if storm_flag not in _STORM_FLAG_ARGS:
            raise ValueError(f"unknown storm_flag {storm_flag!r}, must be one of "
                              f"{list(_STORM_FLAG_ARGS)}")
        cmd.append(_STORM_FLAG_ARGS[storm_flag])
    if holdout:
        cmd.append("--holdout")
    return cmd


def run_one(pairs_override: str, account_size: int, storm_flag: str, holdout: bool,
            timeout: int = 1800) -> tuple:
    """Runs one grid point, returns (row_dict_or_None, error_str_or_None)."""
    pre_ts = time.time()
    cmd = build_cmd(pairs_override, account_size, storm_flag, holdout)
    result = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True, timeout=timeout)
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
    row["account_size"] = account_size
    row["split"] = "oos" if holdout else "is"

    split_tag = "oos" if holdout else "is"
    archive_name = f"{storm_flag or 'nogate'}_{account_size}_{split_tag}.parquet"
    shutil.copy2(newest, os.path.join(_ARCHIVE_DIR, archive_name))
    trades_src = newest.replace("portfolio_", "trades_")
    if os.path.exists(trades_src):
        shutil.copy2(trades_src, os.path.join(
            _ARCHIVE_DIR, archive_name.replace(".parquet", "_trades.parquet")))
    return row, None


def main():
    p = argparse.ArgumentParser(description="Capital-size sweep for backtest.py --capital-sim")
    p.add_argument("--pairs-override", required=True)
    p.add_argument("--storm-flag", default=None, choices=list(_STORM_FLAG_ARGS),
                   help="Which STORM gate to hold fixed across the sweep. Omit for no gate.")
    p.add_argument("--grid", type=int, nargs="+", default=_DEFAULT_GRID)
    p.add_argument("--include-oos", action="store_true",
                   help="Also run each grid point with --holdout (doubles total runs).")
    args = p.parse_args()

    if not os.path.exists(args.pairs_override):
        print(f"FATAL: {args.pairs_override} not found")
        sys.exit(1)
    os.makedirs(_ARCHIVE_DIR, exist_ok=True)

    splits = [False, True] if args.include_oos else [False]
    rows = []
    n_total = len(args.grid) * len(splits)
    i = 0
    for account_size in args.grid:
        for holdout in splits:
            i += 1
            split_label = "OOS" if holdout else "IS"
            print(f"[{i}/{n_total}] account_size=${account_size:,} split={split_label} ...")
            t0 = time.time()
            row, err = run_one(args.pairs_override, account_size, args.storm_flag, holdout)
            if err:
                print(f"  FAILED ({time.time()-t0:.1f}s): {err[:300]}")
                continue
            print(f"  sharpe={row.get('sharpe_portfolio')} n_taken={row.get('n_taken')} "
                  f"final_equity={row.get('final_equity')} ({time.time()-t0:.1f}s)")
            rows.append(row)

    if not rows:
        print("No successful grid points -- nothing to summarize.")
        sys.exit(1)

    summary_df = pd.DataFrame(rows)
    out_path = os.path.join(_ARCHIVE_DIR, f"sweep_summary_{args.storm_flag or 'nogate'}.parquet")
    summary_df.to_parquet(out_path, index=False)
    print(f"\nSaved sweep summary -> {out_path}")
    print(summary_df[["account_size", "split", "n_taken", "sharpe_portfolio",
                       "final_equity"]].to_string(index=False))


if __name__ == "__main__":
    main()
