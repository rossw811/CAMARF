"""
debug/_verify_bayesian_pair_confirmation.py -- synthetic ground-truth
verification for research/bayesian_pair_confirmation.py's Beta-Binomial
conjugate update, BEFORE trusting real-data results.

Checks:
  1. prior_from_adjusted_pvalue: hand-computed a0/b0 for a known adjusted
     p-value and PRIOR_PSEUDO_N.
  2. posterior_from_trades: hand-computed Beta-Binomial update for a known
     win/loss sequence.
  3. Zero OOS trades -> posterior == prior exactly (no phantom update).
  4. All-wins and all-losses sequences move the posterior mean in the
     correct direction, converging toward 1.0 / 0.0 as n grows.
  5. credible_interval brackets the point estimate and narrows as evidence
     accumulates (more trades -> tighter interval, all else equal).
  6. Degenerate p-value inputs (adjusted_pvalue exactly 0.0 or 1.0) don't
     produce a degenerate (zero-parameter) Beta distribution.

Run: python debug/_verify_bayesian_pair_confirmation.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

import bayesian_pair_confirmation as bpc


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def verify_prior_construction():
    print("\n=== 1. prior_from_adjusted_pvalue ===")
    a0, b0 = bpc.prior_from_adjusted_pvalue(0.02, pseudo_n=10)
    # p_genuine = 1 - 0.02 = 0.98 -> a0 = 9.8, b0 = 0.2
    ok = check("a0 = 9.8 for adjusted_pvalue=0.02, pseudo_n=10", abs(a0 - 9.8) < 1e-9)
    ok &= check("b0 = 0.2 for adjusted_pvalue=0.02, pseudo_n=10", abs(b0 - 0.2) < 1e-9)
    ok &= check("a0 + b0 == pseudo_n exactly", abs((a0 + b0) - 10) < 1e-9)
    return ok


def verify_posterior_update():
    print("\n=== 2. posterior_from_trades: hand-computed Beta-Binomial update ===")
    a0, b0 = 5.0, 5.0
    pnl = np.array([10.0, 5.0, -3.0, 8.0, -1.0, 2.0, -4.0])  # 4 wins, 3 losses
    a_post, b_post, n_wins, n_losses = bpc.posterior_from_trades(a0, b0, pnl)
    ok = check("n_wins == 4", n_wins == 4)
    ok &= check("n_losses == 3", n_losses == 3)
    ok &= check("a_post == a0 + n_wins == 9.0", abs(a_post - 9.0) < 1e-9)
    ok &= check("b_post == b0 + n_losses == 8.0", abs(b_post - 8.0) < 1e-9)
    return ok


def verify_zero_trades_no_phantom_update():
    print("\n=== 3. Zero OOS trades -> posterior == prior exactly ===")
    a0, b0 = bpc.prior_from_adjusted_pvalue(0.01)
    a_post, b_post, n_wins, n_losses = bpc.posterior_from_trades(a0, b0, np.array([]))
    ok = check("n_wins == 0 and n_losses == 0", n_wins == 0 and n_losses == 0)
    ok &= check("a_post == a0 exactly (no phantom update)", a_post == a0)
    ok &= check("b_post == b0 exactly (no phantom update)", b_post == b0)
    return ok


def verify_direction_and_convergence():
    print("\n=== 4. All-wins / all-losses move the posterior in the correct direction ===")
    a0, b0 = bpc.prior_from_adjusted_pvalue(0.5)  # neutral-ish prior, mean=0.5
    prior_mean = a0 / (a0 + b0)

    all_wins = np.full(50, 1.0)
    a_w, b_w, _, _ = bpc.posterior_from_trades(a0, b0, all_wins)
    post_mean_wins = a_w / (a_w + b_w)
    ok = check("50 wins pushes posterior mean UP from the prior", post_mean_wins > prior_mean)
    ok &= check("50 wins pushes posterior mean close to 1.0", post_mean_wins > 0.9)

    all_losses = np.full(50, -1.0)
    a_l, b_l, _, _ = bpc.posterior_from_trades(a0, b0, all_losses)
    post_mean_losses = a_l / (a_l + b_l)
    ok &= check("50 losses pushes posterior mean DOWN from the prior", post_mean_losses < prior_mean)
    ok &= check("50 losses pushes posterior mean close to 0.0", post_mean_losses < 0.1)
    return ok


def verify_credible_interval_narrows():
    print("\n=== 5. Credible interval brackets the mean and narrows with more evidence ===")
    a0, b0 = bpc.prior_from_adjusted_pvalue(0.5)
    few = np.array([1.0, -1.0, 1.0])
    many = np.tile(few, 20)  # same win rate, 20x the evidence

    a_few, b_few, _, _ = bpc.posterior_from_trades(a0, b0, few)
    a_many, b_many, _, _ = bpc.posterior_from_trades(a0, b0, many)

    lo_few, hi_few = bpc.credible_interval(a_few, b_few)
    lo_many, hi_many = bpc.credible_interval(a_many, b_many)
    mean_few = a_few / (a_few + b_few)
    mean_many = a_many / (a_many + b_many)

    ok = check("interval brackets the mean (few evidence)", lo_few <= mean_few <= hi_few)
    ok &= check("interval brackets the mean (more evidence)", lo_many <= mean_many <= hi_many)
    ok &= check("more evidence at the same win rate -> narrower credible interval",
                (hi_many - lo_many) < (hi_few - lo_few))
    return ok


def verify_no_degenerate_beta_at_extremes():
    print("\n=== 6. Degenerate p-value inputs don't produce a zero-parameter Beta ===")
    a0_zero, b0_zero = bpc.prior_from_adjusted_pvalue(0.0)
    a0_one, b0_one = bpc.prior_from_adjusted_pvalue(1.0)
    ok = check("adjusted_pvalue=0.0 -> a0 > 0 and b0 > 0", a0_zero > 0 and b0_zero > 0)
    ok &= check("adjusted_pvalue=1.0 -> a0 > 0 and b0 > 0", a0_one > 0 and b0_one > 0)
    return ok


def main():
    results = [
        verify_prior_construction(),
        verify_posterior_update(),
        verify_zero_trades_no_phantom_update(),
        verify_direction_and_convergence(),
        verify_credible_interval_narrows(),
        verify_no_degenerate_beta_at_extremes(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
