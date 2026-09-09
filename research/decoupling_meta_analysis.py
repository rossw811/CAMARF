"""
research/decoupling_meta_analysis.py -- Phase 3 of the discovery-event research program (Ross:
"run a properly-scoped meta-analysis of related null results"). Targets the existing decoupling
chain (decoupling_analysis.py -> decoupling_requalification.py -> decoupling_backtest.py), whose
own individual results are each too underpowered to be conclusive alone: 5/142 (3.5%) broken
pairs formally re-qualify cointegration post-break, and of the 4 that reach a real backtest, only
1/4 shows positive total P&L (Ross's 2026-07-01 decision: "keep the entire decoupling line of
work as research-only" -- a real, useful negative result, not a dead end).

This is the "genuinely related hypothesis" family this meta-analysis combines -- not an arbitrary
grab-bag of unrelated nulls (per Ross's own "auditing which nulls test a genuinely related
hypothesis before combining them" scoping): every input here tests the SAME underlying question
("does a pair's post-break cointegration re-formation represent something real and tradeable?"),
just at different stages of the same pipeline.

Two formal small-n combinations, both explicitly disclosed as underpowered at n=4-5 rather than
oversold:
  1. Fisher's combined p-value on the requalification stage's own 4 EG p-values -- tests whether
     the SET of requalifications shows combined evidence beyond what any one p-value implies.
  2. A one-sample t-test (and, given n=4, a sign test too, since a t-test's normality assumption
     is a stretch at this sample size) on the 4 backtested pairs' total P&L -- tests whether the
     requalified-and-backtested set shows a real aggregate trading edge.

Real finding this session, before this script was built (Finding #51): decoupling_backtest.py's
per-pair Sharpe values are NOT combined here even though they're available -- 3 of the 4 pairs
have only 2-3 CALENDAR DAYS of post-break history at 1m/2m resolution, making any annualized
Sharpe for them statistically unstable regardless of annualization-formula correctness (a
small-sample-window limitation, not the bug already fixed in backtest.py:compute_metrics). Total
P&L (not annualized, immune to this instability) is the metric combined here instead.

Verified against synthetic ground truth first: debug/_verify_decoupling_meta_analysis.py.

Usage:
    python research/decoupling_meta_analysis.py
"""
import logging
import os

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger("decoupling_meta_analysis")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_REQUAL_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "decoupling_requalification.parquet")
_BACKTEST_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "decoupling_backtest.parquet")


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def fisher_combined_pvalue(pvalues: list) -> dict:
    """Fisher's method: X^2 = -2 * sum(ln(p_i)) ~ chi2(df=2k) under the null that ALL k tests are
    individually null. Standard meta-analytic combination for independent p-values testing
    related hypotheses -- NOT valid for non-independent tests, which these 4 pairs plausibly are
    not (fully) since 3 of the 4 share SPY/VOO, a real caveat disclosed in main()."""
    pvalues = [p for p in pvalues if np.isfinite(p) and 0 < p <= 1]
    k = len(pvalues)
    if k == 0:
        return {"chi2_stat": None, "combined_pvalue": None, "k": 0}
    chi2_stat = -2 * sum(np.log(p) for p in pvalues)
    combined_p = float(stats.chi2.sf(chi2_stat, df=2 * k))
    return {"chi2_stat": float(chi2_stat), "combined_pvalue": combined_p, "k": k}


def combine_total_pnl(total_pnls: list) -> dict:
    """One-sample t-test AND sign test on total P&L across the backtested set, testing H0: the
    requalified-and-backtested set has zero mean aggregate edge. Both reported since n=4 is too
    small for the t-test's normality assumption to be trusted alone."""
    arr = np.array([p for p in total_pnls if np.isfinite(p)])
    n = len(arr)
    if n < 2:
        return {"n": n, "mean_pnl": float(arr.mean()) if n else None, "t_stat": None, "t_pvalue": None,
                "n_positive": None, "sign_pvalue": None}
    t_stat, t_p = stats.ttest_1samp(arr, popmean=0.0)
    n_positive = int((arr > 0).sum())
    sign_p = float(stats.binomtest(n_positive, n, p=0.5).pvalue)
    return {"n": n, "mean_pnl": float(arr.mean()), "t_stat": float(t_stat), "t_pvalue": float(t_p),
            "n_positive": n_positive, "sign_pvalue": sign_p}


def main():
    _setup_logging()
    log.info("=== decoupling_meta_analysis.py: Phase 3 -- combining the decoupling_"
              "requalification.py/decoupling_backtest.py chain's own underpowered results ===")
    requal = pd.read_parquet(_REQUAL_PATH)
    backtest = pd.read_parquet(_BACKTEST_PATH)
    log.info(f"Requalification stage: {len(requal)} pairs, {int(requal['requalifies'].sum())} "
             f"pass EG at 0.05. Backtest stage: {len(backtest)} pairs backtested.")

    fisher = fisher_combined_pvalue(requal["requalify_pvalue"].tolist())
    log.info(f"Fisher's combined p-value across {fisher['k']} requalification p-values: "
              f"chi2={fisher['chi2_stat']:.2f}, combined_p={fisher['combined_pvalue']:.2e}")
    log.info("  CAVEAT: 3 of 4 pairs share SPY/VOO -- Fisher's independence assumption is not "
              "fully met; combined significance is a soft upper bound on the true joint evidence, "
              "not a strict formal guarantee.")

    pnl_result = combine_total_pnl(backtest["total_pnl"].tolist())
    log.info(f"Total P&L across {pnl_result['n']} backtested pairs: mean={pnl_result['mean_pnl']:.2f}, "
              f"t={pnl_result['t_stat']:.3f}, p={pnl_result['t_pvalue']:.3f}; "
              f"{pnl_result['n_positive']}/{pnl_result['n']} positive, sign-test p={pnl_result['sign_pvalue']:.3f}")

    out = pd.DataFrame([{
        "n_requalified": fisher["k"], "fisher_chi2": fisher["chi2_stat"],
        "fisher_combined_pvalue": fisher["combined_pvalue"],
        "n_backtested": pnl_result["n"], "mean_total_pnl": pnl_result["mean_pnl"],
        "pnl_t_stat": pnl_result["t_stat"], "pnl_t_pvalue": pnl_result["t_pvalue"],
        "n_positive_pnl": pnl_result["n_positive"], "pnl_sign_test_pvalue": pnl_result["sign_pvalue"],
    }])
    out_path = os.path.join(os.path.dirname(_ROOT), "output", "research", "decoupling_meta_analysis.parquet")
    out.to_parquet(out_path)
    log.info(f"Saved -> {out_path}")
    log.info("decoupling_meta_analysis.py complete")


if __name__ == "__main__":
    main()
