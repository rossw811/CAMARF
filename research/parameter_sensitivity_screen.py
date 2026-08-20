"""
research/parameter_sensitivity_screen.py -- Thread G Phase 1: one-at-a-time
(OAT) sensitivity screening of backtest.py-level design parameters against
the real, BUG-D112-fixed 182-pair PIT-safe Purity universe
(output/research/purity_pairs.parquet).

Scope (this pass): parameters cleanly swept via a single backtest.py CLI
flag with no cross-run state dependency -- ENTRY_ZSCORE (--entry-z), hedge
method (--hedge), and --capital-sizing method. Deliberately EXCLUDED from
this pass, not silently dropped: --risk-parity/--hrp-weight/--pit-confidence-
weight (each has a real IS-fitting state dependency on trades_layer1.parquet
per BUG-D76's fix -- needs its own careful sequencing, scoped as separate
follow-up); episodic-confirmation parameters (min_windows_confirmed, alpha,
tier3_threshold, window/step sizes) and the fundamentals reporting lag
(each requires a multi-hour re-scan per grid point, not a cheap CLI sweep --
also separate follow-up, tracked in Development.md).

For each parameter, for each grid value, runs backtest.py twice (IS, OOS via
--holdout) against the Purity pairs override with --capital-sim ($100k fixed
unless capital_sizing itself is the swept parameter), reads the resulting
portfolio_*_capsim_*.parquet's sharpe_portfolio, and archives a copy under
output/research/param_sensitivity/ (the canonical output/backtest/ files get
overwritten by the next grid point's run -- this project's established
"read immediately, archive before the next run can clobber it" discipline,
same lesson as this session's Tiered-arm _pitconf filename gotcha).

Overfitting guard: for each parameter, the grid value with the best IS Sharpe
is compared against its own OOS Sharpe, and against the value that would have
been picked by OOS Sharpe alone. A parameter whose IS-best pick is NOT also
strong OOS is flagged as an overfitting risk -- same "select on one half,
verify on the other" discipline as Finding #23 and coint_frac_window_grid.py.

Usage:
    python research/parameter_sensitivity_screen.py
    python research/parameter_sensitivity_screen.py --only entry_zscore
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
_PAIRS_OVERRIDE = os.path.join(_ROOT, "output", "research", "purity_pairs.parquet")
_BACKTEST_OUT_DIR = os.path.join(_ROOT, "output", "backtest")
_ARCHIVE_DIR = os.path.join(_ROOT, "output", "research", "param_sensitivity")


REGISTRY = [
    {
        "name": "entry_zscore",
        "param_kwarg": "entry_z",
        "grid": [1.5, 2.0, 2.5, 3.0],
        "baseline": 2.0,
    },
    {
        "name": "hedge_method",
        "param_kwarg": "hedge",
        "grid": ["both", "ols", "kalman"],
        "baseline": "both",
    },
    {
        "name": "capital_sizing_method",
        "param_kwarg": "capital_sizing",
        "grid": ["fixed", "equity_proportional", "quarter_kelly", "third_kelly",
                 "half_kelly", "full_kelly"],
        "baseline": "fixed",
    },
]

# =============================================================================
# Thread G-Full Tier 2 (2026-08-13) -- cheap, backtest.py/portfolio_sim.py-level
# Config.BACKTEST constants, swept via the generic --override mechanism (built
# same day, verified against a real extreme-value run before trusting this
# registry). Grids centered on each constant's CURRENT default, +/- a
# reasonable range for that parameter's own units -- not arbitrary, but not
# claimed optimal either, that's what this screen is FOR.
# =============================================================================
TIER2_REGISTRY = [
    {"name": "stop_zscore", "override_name": "STOP_ZSCORE",
     "grid": [3.0, 3.5, 4.0, 4.5, 5.0], "baseline": 3.5},
    {"name": "exit_zscore", "override_name": "EXIT_ZSCORE",
     "grid": [0.0, 0.25, 0.5, 0.75], "baseline": 0.0},
    {"name": "max_hold_multiplier", "override_name": "MAX_HOLD_MULTIPLIER",
     "grid": [1.0, 1.5, 2.0, 3.0, 4.0], "baseline": 2.0},
    {"name": "corr_exit_threshold", "override_name": "CORR_EXIT_THRESHOLD",
     "grid": [0.0, 0.10, 0.20, 0.30, 0.40], "baseline": 0.20},
    {"name": "corr_exit_window", "override_name": "CORR_EXIT_WINDOW",
     "grid": [20, 40, 60, 90, 120], "baseline": 60},
    {"name": "min_half_life_bars", "override_name": "MIN_HALF_LIFE_BARS",
     "grid": [1, 3, 5, 10, 20], "baseline": 5},
    {"name": "max_half_life", "override_name": "MAX_HALF_LIFE",
     "grid": [20, 35, 50, 75, 100], "baseline": 50},
    {"name": "flat_risk_pct", "override_name": "FLAT_RISK_PCT",
     "grid": [0.01, 0.02, 0.03, 0.05], "baseline": 0.02},
    {"name": "n_shares_per_trade", "override_name": "N_SHARES_PER_TRADE",
     "grid": [50, 100, 200, 500], "baseline": 100},
    {"name": "commission_per_share", "override_name": "COMMISSION_PER_SHARE",
     "grid": [0.0, 0.005, 0.01, 0.02], "baseline": 0.005},
    {"name": "slippage_bps", "override_name": "SLIPPAGE_BPS",
     "grid": [0, 5, 10, 20], "baseline": 5},
    {"name": "max_concentration_pct", "override_name": "MAX_CONCENTRATION_PCT",
     "grid": [0.10, 0.20, 0.35, 0.50], "baseline": 0.20},
]


def build_cmd(entry_z=None, hedge="both", capital_sizing="fixed",
              account=100_000, holdout=False, override=None):
    cmd = [
        _PYTHON, "backtest.py",
        "--pairs-override", _PAIRS_OVERRIDE,
        "--capital-sim",
        "--capital-sizing", capital_sizing,
        "--capital-account-size", str(account),
        "--hedge", hedge,
    ]
    if holdout:
        cmd.append("--holdout")
    if entry_z is not None:
        cmd += ["--entry-z", str(entry_z)]
    if override:
        cmd += ["--override"] + [f"{k}={v}" for k, v in override.items()]
    return cmd


def run_one(param_kwarg, value, holdout, timeout=1800, override_name=None):
    kwargs = {"entry_z": None, "hedge": "both", "capital_sizing": "fixed"}
    if override_name:
        kwargs["override"] = {override_name: value}
    else:
        kwargs[param_kwarg] = value
    kwargs["holdout"] = holdout
    pre_ts = time.time()
    cmd = build_cmd(**kwargs)
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

    split = "oos" if holdout else "is"
    archive_key = override_name or param_kwarg
    archive_name = f"{archive_key}_{str(value)}_{split}.parquet"
    shutil.copy2(newest, os.path.join(_ARCHIVE_DIR, archive_name))
    trades_src = newest.replace("portfolio_", "trades_")
    if os.path.exists(trades_src):
        trades_archive_name = archive_name.replace(".parquet", "_trades.parquet")
        shutil.copy2(trades_src, os.path.join(_ARCHIVE_DIR, trades_archive_name))
    return row, None


def main():
    p = argparse.ArgumentParser(description="Thread G: OAT parameter sensitivity screen")
    p.add_argument("--only", type=str, default=None)
    p.add_argument("--tier2", action="store_true",
                    help="Run Thread G-Full's Tier 2 registry (generic --override sweeps) "
                         "instead of the original Tier 1 (entry_z/hedge/capital_sizing) REGISTRY.")
    args = p.parse_args()

    if not os.path.exists(_PAIRS_OVERRIDE):
        print(f"FATAL: {_PAIRS_OVERRIDE} not found -- run build_comparison_arm_pairs.py first")
        sys.exit(1)
    os.makedirs(_ARCHIVE_DIR, exist_ok=True)

    active_registry = TIER2_REGISTRY if args.tier2 else REGISTRY
    entries = [e for e in active_registry if args.only is None or e["name"] == args.only]
    if not entries:
        print(f"No registry entry named {args.only!r}. Available: {[e['name'] for e in active_registry]}")
        return

    all_rows = []
    for entry in entries:
        name = entry["name"]
        kwarg = entry.get("param_kwarg")
        override_name = entry.get("override_name")
        grid, baseline = entry["grid"], entry["baseline"]
        print(f"\n=== {name} ({kwarg or override_name}) grid={grid} baseline={baseline!r} ===", flush=True)
        for value in grid:
            for holdout in (False, True):
                split = "OOS" if holdout else "IS"
                print(f"  {kwarg or override_name}={value!r} [{split}] ...", end=" ", flush=True)
                row, err = run_one(kwarg, value, holdout, override_name=override_name)
                if row is None:
                    print(f"FAILED: {err}")
                    all_rows.append({
                        "param": name, "value": str(value), "split": split,
                        "is_baseline": value == baseline, "sharpe_portfolio": float("nan"),
                        "n_taken": None, "n_total": None, "final_equity": float("nan"),
                        "error": err,
                    })
                    continue
                print(f"sharpe={row.get('sharpe_portfolio'):.4f} n_taken={row.get('n_taken')}")
                all_rows.append({
                    "param": name, "value": str(value), "split": split,
                    "is_baseline": value == baseline,
                    "sharpe_portfolio": row.get("sharpe_portfolio"),
                    "n_taken": row.get("n_taken"), "n_total": row.get("n_total"),
                    "final_equity": row.get("final_equity"), "error": None,
                })

    new_df = pd.DataFrame(all_rows)

    # Overfitting guard: per parameter, is the IS-best value also OOS-strong?
    print("\n=== Overfitting guard (IS-best value's OOS rank) ===")
    guard_rows = []
    for name in new_df["param"].unique():
        sub = new_df[new_df["param"] == name]
        is_sub = sub[sub["split"] == "IS"].dropna(subset=["sharpe_portfolio"])
        oos_sub = sub[sub["split"] == "OOS"].dropna(subset=["sharpe_portfolio"])
        if is_sub.empty or oos_sub.empty:
            continue
        is_best_value = is_sub.loc[is_sub["sharpe_portfolio"].idxmax(), "value"]
        oos_best_value = oos_sub.loc[oos_sub["sharpe_portfolio"].idxmax(), "value"]
        oos_ranked = oos_sub.sort_values("sharpe_portfolio", ascending=False).reset_index(drop=True)
        is_best_oos_rank = oos_ranked.index[oos_ranked["value"] == is_best_value].tolist()
        is_best_oos_rank = is_best_oos_rank[0] + 1 if is_best_oos_rank else None
        n_values = len(oos_ranked)
        overfit_risk = (is_best_oos_rank is not None and n_values > 1
                         and is_best_oos_rank > (n_values + 1) / 2.0)
        print(f"  {name}: IS-best={is_best_value!r}, OOS-best={oos_best_value!r}, "
              f"IS-best's OOS rank={is_best_oos_rank}/{n_values}, "
              f"overfit_risk={overfit_risk}")
        guard_rows.append({
            "param": name, "is_best_value": is_best_value, "oos_best_value": oos_best_value,
            "is_best_oos_rank": is_best_oos_rank, "n_values": n_values, "overfit_risk": overfit_risk,
        })
    guard_df = pd.DataFrame(guard_rows)
    _tier_prefix = "tier2" if args.tier2 else "phase1"
    guard_path = os.path.join(_ARCHIVE_DIR, f"{_tier_prefix}_overfitting_guard.parquet")
    guard_df.to_parquet(guard_path)
    print(f"Overfitting guard saved -> {guard_path}")

    # Effect size ranking: max IS sharpe - min IS sharpe per param, and same for OOS.
    print("\n=== Effect size ranking (range of sharpe_portfolio across grid) ===")
    effect_rows = []
    for name in new_df["param"].unique():
        sub = new_df[new_df["param"] == name]
        for split in ("IS", "OOS"):
            vals = sub[sub["split"] == split]["sharpe_portfolio"].dropna()
            if len(vals):
                effect_rows.append({"param": name, "split": split,
                                     "sharpe_range": float(vals.max() - vals.min()),
                                     "sharpe_min": float(vals.min()), "sharpe_max": float(vals.max())})
    effect_df = pd.DataFrame(effect_rows).sort_values(
        ["split", "sharpe_range"], ascending=[True, False]
    ) if effect_rows else pd.DataFrame()
    if len(effect_df):
        print(effect_df.to_string(index=False))
    effect_path = os.path.join(_ARCHIVE_DIR, f"{_tier_prefix}_effect_size_ranking.parquet")
    effect_df.to_parquet(effect_path)

    results_path = os.path.join(_ARCHIVE_DIR, f"{_tier_prefix}_oat_results.parquet")
    if os.path.exists(results_path):
        existing = pd.read_parquet(results_path)
        existing = existing[~existing["param"].isin(new_df["param"].unique())]
        out_df = pd.concat([existing, new_df], ignore_index=True)
    else:
        out_df = new_df
    out_df.to_parquet(results_path)
    print(f"\nSaved -> {results_path} ({len(out_df)} total rows)")


if __name__ == "__main__":
    main()
