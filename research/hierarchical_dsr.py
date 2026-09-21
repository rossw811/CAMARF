"""
research/hierarchical_dsr.py -- Hierarchical / family-based Deflated Sharpe Ratio correction.

Motivation (Ross, 2026-09-21, responding to the pooled-N=990 DSR result in
deflated_sharpe.py showing DSR=0.0000 across every checked label, including
the squeeze/momentum gate): "i don't think the mechanistically-motivated
finding should be penalized -- but i want your thoughts... i like your ideas
let's execute them." My proposed answer (accepted, not a blanket exemption):
deflated_sharpe.py's existing correction pools ALL 990 recorded trials --
including ~250+ pure parameter-sensitivity grid points (STOP_ZSCORE,
EXIT_ZSCORE, CORR_EXIT_WINDOW, MAX_HALF_LIFE, N_SHARES_PER_TRADE, etc.) --
into ONE n_trials count for every label's DSR, including labels that were
never part of that sweep (e.g. the squeeze/momentum STORM gate, tested only
~33 times total). That's a real overcorrection: sweeping STOP_ZSCORE across
10 grid values is genuinely 10 "chances" at the STOP_ZSCORE question, not 10
chances at the squeeze/momentum question -- multiple-testing correction
should be scoped to trials that could plausibly have produced the result
being evaluated by chance, not literally every backtest.py invocation ever
logged.

This does NOT exempt any label from correction (Ross was explicit: no
family should get a free pass). It reports BOTH numbers side by side --
the existing pooled-990 DSR (unchanged, from deflated_sharpe.py) and each
family's own DSR against its own N/Var -- so a family that's genuinely
been tried many times (e.g. the entry-z-override family, ~90 trials) still
gets meaningfully deflated. Only families that are BOTH small AND distinct
in what they test end up materially different from the pooled number.

Family classification: transparent, regex-based, FIRST-MATCH-WINS, applied
to trial_registry.json's own `label` string (the only signal available --
no hidden ML classifier). Any label matching nothing lands in the explicit
"unclassified" bucket, reported not hidden, so a real gap in the pattern
list is visible rather than silently mis-bucketed.

Reuses deflated_sharpe.py's own math functions (expected_max_sharpe_null,
deflated_sharpe_ratio, deflated_sharpe_z_stat) and portfolio_math's
per-period P&L stats -- this script only changes WHICH n_trials/Var[SR]
feed into that existing, already-verified math, never reimplements it.

Usage:
    python research/hierarchical_dsr.py
    python research/hierarchical_dsr.py --registry output/backtest/trial_registry.json \\
        --registry output/backtest/trial_registry_cachyos.json
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deflated_sharpe import (
    expected_max_sharpe_null, deflated_sharpe_ratio, deflated_sharpe_z_stat,
)
import portfolio_math

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_STATS_DIR = os.path.join(_ROOT, "output", "stats")
_ANNUALIZATION = np.sqrt(252)

# Ordered, first-match-wins. Each entry: (family_name, compiled regex applied to `label`).
# Purely a naming-convention classifier over labels backtest.py itself assigns -- see each
# family's own comment for what real methodological question it represents.
_FAMILY_PATTERNS: List[Tuple[str, "re.Pattern"]] = [
    # Tier1/Tier2 parameter-sensitivity screen grid points -- one family PER swept
    # constant, since each sweep answers a different "is the result sensitive to X"
    # question and shouldn't inflate another sweep's trial count.
    ("sens_stop_zscore", re.compile(r"ovSTOP_ZSCORE")),
    ("sens_exit_zscore", re.compile(r"ovEXIT_ZSCORE")),
    ("sens_corr_exit_threshold", re.compile(r"ovCORR_EXIT_THRESHOLD")),
    ("sens_corr_exit_window", re.compile(r"ovCORR_EXIT_WINDOW")),
    ("sens_max_half_life", re.compile(r"ovMAX_HALF_LIFE")),
    ("sens_min_half_life_bars", re.compile(r"ovMIN_HALF_LIFE_BARS")),
    ("sens_max_hold_multiplier", re.compile(r"ovMAX_HOLD_MULTIPLIER")),
    ("sens_flat_risk_pct", re.compile(r"ovFLAT_RISK_PCT")),
    ("sens_n_shares_per_trade", re.compile(r"ovN_SHARES_PER_TRADE")),
    ("sens_commission", re.compile(r"ovCOMMISSION_PER_SHARE")),
    ("sens_slippage", re.compile(r"ovSLIPPAGE_BPS")),
    ("sens_max_concentration", re.compile(r"ovMAX_CONCENTRATION_PCT")),
    # Squeeze/momentum STORM gate -- the specific mechanistically-motivated finding
    # Ross asked about. Distinct question from the sensitivity sweeps above and from
    # the other STORM variants below (different economic mechanism each).
    ("squeeze_momentum_gate", re.compile(r"sqzgate|sqzmomgate|momgate")),
    # Entry-z-score override grid (ez15/ez20/ez25/ez30/ezmax35/ezmax205) -- its own
    # sweep, same reasoning as the sens_* families above.
    ("entry_zscore_override", re.compile(r"_ez\d|_ezmax\d")),
    # Other named STORM variants (cointegration-fraction gate, gap-stop, liquidity-bar
    # filter, max-half-life filter, market-maker execution model, real correlation
    # exit, sizing edge/sizing-edge-post, sqrt market-impact, "stormall" = all
    # combined) -- each a genuinely different mechanism, grouped together only
    # because no single one has enough trials to be its own family yet.
    ("storm_other", re.compile(
        r"storm_cfrac|storm_gstop|storm_liqbarfilter|storm_maxhlfilter|storm_mmexec|"
        r"storm_realcorrexit|storm_sedge|storm_sqrtimpact|stormall|"
        r"^layer1(_holdout)?_storm(_pairsoverride)?$"
    )),
    # Portfolio-construction variants: hierarchical risk parity, hub-weighting,
    # negative-hedge, risk-parity sizing, P&L cap -- a different methodological
    # question (how to size/weight an already-selected pair set) from pair selection.
    ("portfolio_construction", re.compile(r"_hrp$|_hubw$|_neghedge$|_riskparity$|_pnlcap$")),
    # Capital-sizing-scheme comparisons (fixed/kelly-variants/equity-proportional/
    # leverage-cap/concentration-cap/flat-2pct) under --capital-sim, when NOT already
    # claimed by a sens_*/squeeze/entry-z/storm family above (those combine a swept
    # parameter WITH a capsim rerun, and should stay in the swept-parameter's family).
    ("capital_sizing_scheme", re.compile(r"capsim")),
    # PIT-confirmation methodology variant (episodic vs full-history re-confirmation).
    ("pit_confirmation", re.compile(r"pitconf")),
    # Layer2 (second-stage/meta) baseline.
    ("layer2_baseline", re.compile(r"^layer2")),
    # Bare baseline runs (layer1, layer1_holdout, layer1_pairsoverride,
    # layer1_holdout_pairsoverride) -- no override, no STORM flag, no sizing variant.
    ("baseline", re.compile(r"^layer1(_holdout)?(_pairsoverride)?$")),
]


def classify_family(label: str) -> str:
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(label):
            return family
    return "unclassified"


def load_merged_trials(registry_paths: List[str]) -> List[Dict]:
    trials = []
    for path in registry_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r") as f:
            try:
                trials.extend(json.load(f))
            except json.JSONDecodeError:
                continue
    return trials


def _daily_pnl_stats(trades_path: str) -> Optional[Tuple[float, int, float, float]]:
    """Same convention as deflated_sharpe.py's own _daily_pnl_stats -- duplicated
    rather than imported because that one is module-private (leading underscore);
    kept byte-identical on purpose so results are directly comparable."""
    if not os.path.exists(trades_path):
        return None
    trades = pd.read_parquet(trades_path)
    if trades.empty or "pnl_net" not in trades.columns:
        return None
    daily = portfolio_math.daily_pnl_from_trades(trades)
    vals = daily.values.astype(float)
    if len(vals) < 3 or np.std(vals, ddof=1) == 0:
        return None
    sr_hat = float(np.mean(vals) / np.std(vals, ddof=1))
    t_obs = len(vals)
    skew = float(stats.skew(vals))
    kurt = float(stats.kurtosis(vals, fisher=False))
    return sr_hat, t_obs, skew, kurt


def family_var_sr(family_trials: List[Dict]) -> float:
    """Var[SR] across a family's own trials, in per-period (daily) units --
    same /sqrt(252) unit conversion deflated_sharpe.py uses (see its module
    docstring for why this conversion is exact, not approximate)."""
    sharpes_annualized = np.array([t["sharpe"] for t in family_trials], dtype=float)
    sharpes_daily = sharpes_annualized / _ANNUALIZATION
    if len(sharpes_daily) < 2:
        return 0.0
    return float(np.var(sharpes_daily, ddof=1))


def main():
    p = argparse.ArgumentParser(description="Hierarchical family-based DSR correction")
    p.add_argument("--registry", action="append", default=None,
                    help="Trial registry JSON path(s). Repeatable. Default: local + "
                         "CachyOS registries in output/backtest/.")
    args = p.parse_args()

    registry_paths = args.registry or [
        os.path.join(_BACKTEST_DIR, "trial_registry.json"),
        os.path.join(_BACKTEST_DIR, "trial_registry_cachyos.json"),
    ]
    trials = load_merged_trials(registry_paths)
    n_pooled = len(trials)
    print(f"Loaded {n_pooled} trials from {len(registry_paths)} registry file(s): {registry_paths}")

    by_family = defaultdict(list)
    for t in trials:
        by_family[classify_family(t["label"])].append(t)

    print(f"\n{len(by_family)} families:")
    for family in sorted(by_family, key=lambda f: -len(by_family[f])):
        members = by_family[family]
        distinct_labels = sorted(set(t["label"] for t in members))
        print(f"  {family}: n={len(members)}  ({len(distinct_labels)} distinct labels)")

    if by_family.get("unclassified"):
        unclassified_labels = sorted(set(t["label"] for t in by_family["unclassified"]))
        print(f"\nWARNING: {len(by_family['unclassified'])} trial(s) unclassified "
              f"-- pattern list may be missing a case. Labels: {unclassified_labels}")

    # Pooled Var[SR] across ALL trials -- matches deflated_sharpe.py's own n_trials/var_sr
    # exactly, reported here only for side-by-side comparison against each family's own.
    pooled_var_sr = family_var_sr(trials)

    # Evaluate every family that has >=2 trials AND at least one member label with a
    # matching trades_<label>.parquet on disk (the file backtest.py writes per run).
    # Evaluated against the family's OWN best-Sharpe member (the natural "headline"
    # candidate within that family, same principle as deflated_sharpe.py evaluating
    # the canonical layer1/layer1_holdout labels).
    results = {}
    for family, members in by_family.items():
        if family == "unclassified":
            continue
        n_family = len(members)
        var_family = family_var_sr(members)
        best = max(members, key=lambda t: t["sharpe"])
        trades_path = os.path.join(_BACKTEST_DIR, f"trades_{best['label']}.parquet")
        stats_tuple = _daily_pnl_stats(trades_path)
        if stats_tuple is None:
            reason = ("file not found" if not os.path.exists(trades_path)
                       else "found but unusable (empty, missing pnl_net, <3 distinct P&L "
                            "days, or zero-variance daily P&L)")
            print(f"\n[{family}] n={n_family}, best label='{best['label']}' "
                  f"-- {reason} at {trades_path}, skipping DSR eval")
            continue
        sr_hat, t_obs, skew, kurt = stats_tuple

        dsr_family = deflated_sharpe_ratio(sr_hat, t_obs, skew, kurt, n_family, var_family)
        z_family = deflated_sharpe_z_stat(sr_hat, t_obs, skew, kurt, n_family, var_family)
        dsr_pooled = deflated_sharpe_ratio(sr_hat, t_obs, skew, kurt, n_pooled, pooled_var_sr)
        z_pooled = deflated_sharpe_z_stat(sr_hat, t_obs, skew, kurt, n_pooled, pooled_var_sr)

        print(f"\n[{family}] n_family={n_family} best_label='{best['label']}' "
              f"SR_hat={sr_hat:.4f} (T={t_obs}, skew={skew:.3f}, kurt={kurt:.3f})")
        print(f"  Family-scoped:  DSR={dsr_family:.4f} (z={z_family:.2f}), n_trials={n_family}, "
              f"Var[SR]={var_family:.6f}")
        print(f"  Pooled (n={n_pooled}): DSR={dsr_pooled:.4f} (z={z_pooled:.2f}), "
              f"Var[SR]={pooled_var_sr:.6f}")

        results[family] = {
            "n_family": n_family, "best_label": best["label"],
            "sr_hat_per_period": sr_hat, "t_obs": t_obs, "skew": skew, "kurtosis": kurt,
            "family_var_sr": var_family, "family_dsr": dsr_family, "family_z_stat": z_family,
            "pooled_n_trials": n_pooled, "pooled_var_sr": pooled_var_sr,
            "pooled_dsr": dsr_pooled, "pooled_z_stat": z_pooled,
        }

    if results:
        out_path = os.path.join(_STATS_DIR, "hierarchical_dsr.json")
        os.makedirs(_STATS_DIR, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved => {out_path}")
    else:
        print("\nNo family had both >=2 trials and a matching trades_*.parquet -- nothing evaluated.")


if __name__ == "__main__":
    main()
