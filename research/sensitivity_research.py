"""
research/sensitivity_research.py -- parameter sensitivity for CAMARF's
research/*.py comparison arms, matching the project's existing
sensitivity.py pattern (parameter grid -> headline metric, does the
finding hold or is it fragile) but applied to the research/ scripts
instead of the production backtest.

BATCH 1 (this file, 2026-08-03): the 7 Session 30 comparison arms, since
those have full context available right now (headline metric, expected
finding, and what "robust" vs "fragile" means for each was determined
while building/verifying them this session). 6 of the 7 are swept here;
research/svm_gradient_descent_classifier.py has NO CLI parameters at all
(confirmed by grep) and is currently blocked on insufficient real-world
data (19 examples, needs 30/class per Config.ML.MIN_CLASS_SAMPLES -- see
docs/FINDINGS.md #17) -- a sensitivity sweep would be meaningless until
real data exists to sweep against, not applicable, excluded rather than
faked.

REMAINING SCOPE, explicitly NOT covered by this file, tracked so it is not
silently dropped: 39 more research/*.py scripts have real CLI-tunable
parameters (out of 120 total research scripts, 46 have argparse-exposed
numeric/float/int arguments; batch 1 covers 6 of those 46). Genuinely
multi-session work -- Ross confirmed a bespoke (not generic/mechanical)
per-script sweep, which means each of the remaining 39 needs its own
headline-metric identification the same way batch 1's 6 did, not just a
parameter grid run blindly.

Each script is run as a SUBPROCESS (not imported) -- these are standalone
CLI scripts, not internal functions like sensitivity.py's backtest.py
integration, so subprocess isolation avoids cross-module global-state
collisions between running 7 different research scripts back to back in
one process.

Usage:
    python research/sensitivity_research.py
    python research/sensitivity_research.py --only cycle_detection
"""
import argparse
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PYTHON = sys.executable
_OUT_DIR = os.path.join(_ROOT, "output", "sensitivity")


def _run(script_rel_path: str, extra_args: list) -> str:
    """Run one research script as a subprocess from the project root,
    return combined stdout+stderr text. Does not raise on nonzero exit --
    callers should check for an empty/error result."""
    cmd = [_PYTHON, script_rel_path] + extra_args
    result = subprocess.run(
        cmd, cwd=_ROOT, capture_output=True, text=True, timeout=900,
    )
    return result.stdout + "\n" + result.stderr


def _extract_floats(pattern: str, text: str) -> list:
    return [float(m) for m in re.findall(pattern, text)]


# =============================================================================
# BATCH 1 REGISTRY -- one entry per Session 30 comparison arm.
# Each "extract" function takes the raw stdout+stderr text (or reads the
# script's own output parquet, for the two scripts whose headline output
# is a table rather than a clean scalar print) and returns a dict of
# {metric_name: value} for that one run.
# =============================================================================

def _extract_cycle_detection(text: str, _run_dir) -> dict:
    plv = _extract_floats(r"mean rolling PLV \(window=\d+\): ([\-\d\.]+)", text)
    return {"mean_plv": float(np.mean(plv)) if plv else float("nan"), "n_pairs_reported": len(plv)}


def _extract_levy_jump(text: str, _run_dir) -> dict:
    jump_frac = _extract_floats(r"jumps detected: \d+ \(([\d\.]+)% of bars\)", text)
    overlap = _extract_floats(r"of detected jumps, ([\d\.]+)% already had a non-NONE GapFlag", text)
    return {
        "mean_jump_frac_pct": float(np.mean(jump_frac)) if jump_frac else float("nan"),
        "mean_gapflag_overlap_pct": float(np.mean(overlap)) if overlap else float("nan"),
    }


def _extract_rough_vol(text: str, _run_dir) -> dict:
    h_rs = _extract_floats(r"H_rs=([\-\d\.]+)", text)
    h_dfa = _extract_floats(r"H_dfa=([\-\d\.]+)", text)
    h_wav = _extract_floats(r"H_wavelet=([\-\d\.]+)", text)
    return {
        "mean_H_rs": float(np.mean(h_rs)) if h_rs else float("nan"),
        "mean_H_dfa": float(np.mean(h_dfa)) if h_dfa else float("nan"),
        "mean_H_wavelet": float(np.mean(h_wav)) if h_wav else float("nan"),
    }


def _extract_options_greeks(text: str, _run_dir) -> dict:
    m = re.search(r"corr\(gamma_spread, rolling_corr\): r=([\-\d\.]+), p=([\d\.]+)", text)
    if not m:
        return {"r": float("nan"), "p": float("nan")}
    return {"r": float(m.group(1)), "p": float(m.group(2))}


def _extract_inverse_polarity_full_universe(text: str, _run_dir) -> dict:
    n_cand_m = re.search(r"(\d+) pairs with rho <=", text)
    n_real = len(re.findall(r"\(p<0\.05\)", text))
    n_looks_neg_hedge_not_real = len(re.findall(r"correlated but NOT cointegrated", text))
    return {
        "n_candidates": int(n_cand_m.group(1)) if n_cand_m else 0,
        "n_genuinely_cointegrated": n_real,
        "n_correlated_not_cointegrated": n_looks_neg_hedge_not_real,
    }


def _extract_trig_convergence(text: str, run_dir) -> dict:
    out_path = os.path.join(_ROOT, "output", "research", "trig_convergence.parquet")
    if not os.path.exists(out_path):
        return {"mean_sum_deviation": float("nan"), "mean_break_signal_z": float("nan")}
    df = pd.read_parquet(out_path)
    return {
        "mean_sum_deviation": float(df["mean_theta_sum_deviation_from_invariant"].mean()) if len(df) else float("nan"),
        "mean_break_signal_z": float(df["mean_break_signal_abs_z"].mean()) if len(df) else float("nan"),
    }


# =============================================================================
# BATCH 2 (2026-08-03, same day continuation) -- 6 more of the 46 parameterized
# research scripts, picked for centrality to the project's core cointegration/
# lead-lag methodology (closest to touching PAPER.md-level claims). 34 scripts
# remain after this batch -- still explicit backlog, not silently dropped.
# =============================================================================

def _extract_eg_permutation(text: str, _run_dir) -> dict:
    m = re.search(r"Mean null_frac_significant across ALL confirmed pairs: ([\d\.]+)", text)
    return {"mean_null_frac_significant": float(m.group(1)) if m else float("nan")}


def _extract_tail_dependence(text: str, run_dir) -> dict:
    out_path = os.path.join(_ROOT, "output", "research", "tail_dependence_summary.parquet")
    if not os.path.exists(out_path):
        return {"n_rows": 0, "mean_lambda_L": float("nan"), "mean_lambda_U": float("nan"), "gate_flagged": False}
    df = pd.read_parquet(out_path)
    gate_flagged = "GATE RESULT: at least one pair" in text
    return {
        "n_rows": len(df),
        "mean_lambda_L": float(df["lambda_L"].mean()) if len(df) and "lambda_L" in df.columns else float("nan"),
        "mean_lambda_U": float(df["lambda_U"].mean()) if len(df) and "lambda_U" in df.columns else float("nan"),
        "gate_flagged": gate_flagged,
    }


def _extract_variance_ratio(text: str, _run_dir) -> dict:
    m = re.search(r"(\d+) valid \(pair, q\) tests, (\d+) with VR<1.*?(\d+) significant at p<0\.05", text)
    if not m:
        return {"n_valid": 0, "n_vr_below_1": 0, "n_significant": 0}
    return {"n_valid": int(m.group(1)), "n_vr_below_1": int(m.group(2)), "n_significant": int(m.group(3))}


def _extract_wavelet_hurst(text: str, _run_dir) -> dict:
    m = re.search(r"Mean \|divergence\|: rs-dfa=([\-\d\.]+), rs-wavelet=([\-\d\.]+), dfa-wavelet=([\-\d\.]+)", text)
    if not m:
        return {"rs_dfa_div": float("nan"), "rs_wavelet_div": float("nan"), "dfa_wavelet_div": float("nan")}
    return {"rs_dfa_div": float(m.group(1)), "rs_wavelet_div": float(m.group(2)), "dfa_wavelet_div": float(m.group(3))}


def _extract_threshold_coint(text: str, _run_dir) -> dict:
    m = re.search(r"(\d+) pairs tested, (\d+) valid, (\d+) significant threshold effects at p<0\.05", text)
    if not m:
        return {"n_tested": 0, "n_valid": 0, "n_significant": 0}
    return {"n_tested": int(m.group(1)), "n_valid": int(m.group(2)), "n_significant": int(m.group(3))}


def _extract_regime_cluster_robustness(text: str, _run_dir) -> dict:
    m = re.search(r"cluster found in (\d+)/(\d+) draws, best-performing in (\d+)/(\d+)", text)
    if not m:
        return {"found_frac": float("nan"), "best_of_found_frac": float("nan")}
    found, n_boot, best, denom = (int(g) for g in m.groups())
    return {
        "found_frac": found / n_boot if n_boot else float("nan"),
        "best_of_found_frac": best / denom if denom else float("nan"),
    }


BATCH2_REGISTRY = [
    {
        "name": "eg_permutation_check",
        "script": "research/eg_permutation_check.py",
        "flag": "--n-perm",
        "grid": [100, 200, 500, 1000],
        "baseline": 500,
        "extract": _extract_eg_permutation,
        "expected": "mean_null_frac_significant should stay near its baseline value (expected ~0.05 under a well-behaved null) as n_perm increases -- more permutations should tighten the estimate, not shift its central tendency. A value that DRIFTS with n_perm (not just gets less noisy) would mean the baseline n_perm=500 estimate itself was unreliable.",
    },
    {
        "name": "tail_dependence",
        "script": "research/tail_dependence.py",
        "flag": "--asymmetry-threshold",
        "grid": [0.10, 0.15, 0.20, 0.25],
        "baseline": 0.15,
        "extract": _extract_tail_dependence,
        "expected": "Does the GATE RESULT (material tail asymmetry found or not) flip depending on where the asymmetry-threshold gate is set? A gate result that's only reached right at the default threshold is a fragile finding.",
    },
    {
        "name": "variance_ratio_test",
        "script": "research/variance_ratio_test.py",
        "flag": "--q-values",
        "grid": ["2 4 8", "2 4 8 16", "4 8 16 32"],
        "baseline": "2 4 8 16",
        "extract": _extract_variance_ratio,
        "expected": "Does the mean-reversion-direction finding (VR<1) and significance count hold across different holding-period grids, or is it an artifact of the specific q-values chosen? --q-values takes multiple ints so grid values are space-separated strings, split before passing to subprocess.",
    },
    {
        "name": "wavelet_hurst_comparison",
        "script": "research/wavelet_hurst_comparison.py",
        "flag": "--tf",
        "grid": ["1h", "4h", "1D"],
        "baseline": "1h",
        "extract": _extract_wavelet_hurst,
        "expected": "Does the RS/DFA/wavelet estimator divergence pattern hold across timeframes, or is it specific to 1h? A --tf sweep is this project's own established robustness-check convention (does a finding replicate across timeframes), not a generic parameter grid.",
    },
    {
        "name": "threshold_cointegration",
        "script": "research/threshold_cointegration.py",
        "flag": "--n-boot",
        "grid": [100, 250, 500, 1000],
        "baseline": 500,
        "extract": _extract_threshold_coint,
        "expected": "Does the count of pairs with significant threshold effects (p<0.05) stay stable as bootstrap draws increase, or was the baseline n_boot=500 count noisy?",
    },
    {
        "name": "regime_cluster_robustness_check",
        "script": "research/regime_cluster_robustness_check.py",
        "flag": "--n-boot",
        "grid": [50, 100, 200, 400],
        "baseline": 200,
        "extract": _extract_regime_cluster_robustness,
        "expected": "This script's OWN name is 'robustness check' -- testing whether ITS bootstrap-count choice is itself robust is a direct meta-check. found_frac/best_of_found_frac should stabilize (not keep changing) as n_boot grows.",
    },
]


REGISTRY = [
    {
        "name": "cycle_detection",
        "script": "research/cycle_detection.py",
        "flag": "--plv-window",
        "grid": [30, 45, 60, 90, 120],
        "baseline": 60,
        "extract": _extract_cycle_detection,
        "expected": "Finding #13's honest null on KVUE/KMB -- mean_plv should stay low/unremarkable across the grid, not swing to a high value at some window that would flip the conclusion.",
    },
    {
        "name": "levy_jump_diffusion",
        "script": "research/levy_jump_diffusion.py",
        "flag": "--alpha",
        "grid": [0.001, 0.005, 0.01, 0.05, 0.10],
        "baseline": 0.01,
        "extract": _extract_levy_jump,
        "expected": "Finding #14's headline claim is mean_gapflag_overlap_pct ~= 0 (jumps and GapFlag detect different things) -- should hold at every alpha, though jump_frac itself will rise as alpha loosens (more bars cross a looser significance bar) -- that's expected and not a fragility.",
    },
    {
        "name": "rough_volatility",
        "script": "research/rough_volatility.py",
        "flag": "--rv-window",
        "grid": [15, 20, 30, 45, 60],
        "baseline": 30,
        "extract": _extract_rough_vol,
        "expected": "Finding #15's mixed-signal result (DFA/wavelet show roughness, R/S doesn't clearly agree) -- checking whether that DISAGREEMENT between estimators is itself robust across windows, or an artifact of the one window tested.",
    },
    {
        "name": "options_greeks_features",
        "script": "research/options_greeks_features.py",
        "flag": "--window",
        "grid": [15, 20, 30, 45, 60],
        "baseline": 30,
        "extract": _extract_options_greeks,
        "expected": "Finding #16's significant-but-confounded correlation (r, p) -- checking whether statistical significance survives across window choices, i.e. whether it's a robust (if confounded) pattern or a single-window fluke.",
    },
    {
        "name": "inverse_polarity_full_universe",
        "script": "research/inverse_polarity.py",
        "flag": "--corr-threshold",
        "grid": [-0.30, -0.35, -0.40, -0.50, -0.60],
        "baseline": -0.40,
        "extra_args": ["--full-universe"],
        "extract": _extract_inverse_polarity_full_universe,
        "expected": "Finding #18's real full-universe null (2 candidates at -0.40, neither cointegrated) -- checking whether loosening the threshold reveals any genuine equilibrium candidate, or whether the null is robust across a reasonable threshold range. EXPENSIVE: full 1697-symbol correlation matrix recomputed per grid point, ~1-3 min each.",
    },
    {
        "name": "trig_convergence",
        "script": "research/trig_convergence.py",
        "flag": "--window",
        "grid": [30, 45, 60, 90, 120],
        "baseline": 60,
        "extract": _extract_trig_convergence,
        "expected": "Finding #19's honest null (all 3 confirmed pairs positively correlated, large deviation from the polar-opposite invariant) -- checking whether the deviation-from-invariant ranking across pairs (KVUE/KMB smallest, PNC/ZION largest) is stable across window choices.",
    },
]

# svm_gradient_descent_classifier.py deliberately excluded -- see module
# docstring. No CLI params exist, and it's data-blocked (19/30 examples),
# not parameter-blocked, so a sweep would be meaningless right now.

REGISTRY = REGISTRY + BATCH2_REGISTRY
# 34 of the 46 parameterized research scripts remain after batch 2 --
# explicit backlog (tracked in Development.md/docs/FINDINGS.md), not
# silently dropped.


def main():
    p = argparse.ArgumentParser(description="Parameter sensitivity for CAMARF research scripts")
    p.add_argument("--only", type=str, default=None, help="Run only the named registry entry")
    args = p.parse_args()

    os.makedirs(_OUT_DIR, exist_ok=True)
    entries = [e for e in REGISTRY if args.only is None or e["name"] == args.only]
    if not entries:
        print(f"No registry entry named {args.only!r}. Available: {[e['name'] for e in REGISTRY]}")
        return

    all_rows = []
    for entry in entries:
        print(f"\n=== {entry['name']} ({entry['script']} {entry['flag']}) ===")
        print(f"    Expected: {entry['expected']}")
        for value in entry["grid"]:
            # A grid value containing spaces (e.g. variance_ratio_test's
            # "--q-values 2 4 8", a multi-value nargs="+" flag) must be
            # split into separate argv tokens, not passed as one string --
            # argparse would otherwise see a single unparseable token.
            value_tokens = str(value).split(" ") if isinstance(value, str) and " " in value else [str(value)]
            extra = entry.get("extra_args", []) + [entry["flag"]] + value_tokens
            print(f"  running {entry['flag']}={value} ...", end=" ", flush=True)
            text = _run(entry["script"], extra)
            metrics = entry["extract"](text, _OUT_DIR)
            # value stored as str always -- a mixed float/str "value" column
            # (e.g. -0.30 alongside "2 4 8" for variance_ratio_test's
            # multi-value grid) makes pyarrow raise ArrowInvalid on write.
            # Found running this exact sweep; parse back to float at read
            # time for the numeric-grid arms if needed.
            row = {"comparison_arm": entry["name"], "param": entry["flag"], "value": str(value),
                   "is_baseline": value == entry["baseline"], **metrics}
            all_rows.append(row)
            print({k: v for k, v in metrics.items()})

    new_df = pd.DataFrame(all_rows)
    out_path = os.path.join(_OUT_DIR, "research_scripts_sensitivity_batch1.parquet")
    # MERGE with any existing file rather than overwrite -- a --only run
    # used to silently discard every other comparison_arm's previously
    # saved rows (found running this exact sequence: 5 separate --only
    # invocations left only the LAST one's rows on disk). Replace rows for
    # comparison_arm(s) just re-run, keep everything else untouched.
    if os.path.exists(out_path):
        existing = pd.read_parquet(out_path)
        existing = existing[~existing["comparison_arm"].isin(new_df["comparison_arm"].unique())]
        out_df = pd.concat([existing, new_df], ignore_index=True)
    else:
        out_df = new_df
    out_df.to_parquet(out_path)
    print(f"\nSaved -> {out_path} ({len(out_df)} total rows across {out_df['comparison_arm'].nunique()} arms)")
    print(new_df.to_string(index=False))


if __name__ == "__main__":
    main()
