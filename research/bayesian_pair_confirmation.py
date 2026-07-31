"""
research/bayesian_pair_confirmation.py -- Ross's direct request (2026-07-22):
"add the bayesian confirmation as comparison" (dedicated_pass.md sec 11.5).

COMPARISON ARM ONLY -- does not replace production's static EG+FDR pass/fail
confirmation. Answers a different question: instead of "did this pair clear
a one-time significance threshold," track a CONTINUOUSLY-UPDATED confidence
score for each pair as OOS trade evidence accumulates.

Model: Beta-Binomial conjugate Bayesian updating.
  PRIOR:      Beta(a0, b0) per pair, derived from the EG/FDR screen's own
              BH-adjusted p-value (coint_pvalue_adjusted). Prior mean =
              1 - coint_pvalue_adjusted (a low adjusted p-value -> high
              prior confidence the pair is genuinely cointegrated), with a
              FIXED prior strength (PRIOR_PSEUDO_N = 10 pseudo-observations)
              -- a deliberately modest, stated, NOT-tuned weight: the EG/FDR
              screen is real evidence, but it's a one-time statistical test,
              not equivalent to 10 realized trades of actual OOS evidence,
              and this prior is DESIGNED to be outweighed quickly once real
              OOS trades accumulate (the whole point of the Bayesian
              framing over a static label).
  LIKELIHOOD: each closed OOS trade (output/backtest/trades_layer1_holdout.
              parquet) is a Bernoulli trial -- "success" = pnl_net > 0 (the
              plain win/loss on realized OOS P&L, not exit_reason, since a
              trade closed via max_hold/eod that's still net profitable is
              a real win for this purpose, and a signal_exit that's still
              net negative after costs is a real loss).
  POSTERIOR:  Beta(a0 + n_wins, b0 + n_losses). Posterior mean is the
              updated confidence score; a 90% credible interval is reported
              alongside it (not just the point estimate) so a pair with few
              OOS trades shows honestly wide uncertainty rather than a
              falsely precise number.

Honest scope notes:
  - PRIOR_PSEUDO_N=10 is a stated, reasonable, NOT-optimized choice -- a
    genuinely different pseudo_n would shift how fast the posterior departs
    from the prior. Flagged, not hidden.
  - OOS trade counts per pair are currently thin (this project's own
    documented reality -- see CLAUDE.md's ML-gate training-data-
    accumulation note) -- credible intervals will legitimately be wide for
    most pairs. Reported honestly via the interval width, not smoothed over.
  - This uses output/backtest/trades_layer1_holdout.parquet (the actual
    OOS/holdout trades, not the full-series IS trades) -- the correct
    population for an "OOS evidence updates confidence" framing.

Verified against synthetic ground truth first:
debug/_verify_bayesian_pair_confirmation.py.

Usage:
    python research/bayesian_pair_confirmation.py
"""
import glob
import logging
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

PRIOR_PSEUDO_N = 10  # total prior pseudo-observations (a0 + b0); see docstring
CREDIBLE_INTERVAL = 0.90

log = logging.getLogger("bayesian_pair_confirmation")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_bayesian_pair_confirmation.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def prior_from_adjusted_pvalue(adjusted_pvalue: float, pseudo_n: float = PRIOR_PSEUDO_N):
    """Beta(a0, b0) prior from the EG/FDR screen's own evidence.
    Prior mean = 1 - adjusted_pvalue, clipped away from the exact 0/1
    boundary (a p-value of exactly 0 or 1 would otherwise produce a
    degenerate a0=0 or b0=0 Beta prior)."""
    p_genuine = np.clip(1.0 - adjusted_pvalue, 0.01, 0.99)
    a0 = p_genuine * pseudo_n
    b0 = (1.0 - p_genuine) * pseudo_n
    return a0, b0


def posterior_from_trades(a0: float, b0: float, pnl_net: np.ndarray):
    """Beta-Binomial conjugate update. pnl_net: array of realized OOS trade
    net P&L; success = pnl_net > 0."""
    n_wins = int(np.sum(pnl_net > 0))
    n_losses = int(np.sum(pnl_net <= 0))
    a_post = a0 + n_wins
    b_post = b0 + n_losses
    return a_post, b_post, n_wins, n_losses


def credible_interval(a: float, b: float, level: float = CREDIBLE_INTERVAL):
    lo = (1 - level) / 2
    hi = 1 - lo
    return float(stats.beta.ppf(lo, a, b)), float(stats.beta.ppf(hi, a, b))


def load_all_confirmed_pairs():
    frames = []
    for f in sorted(glob.glob(os.path.join(_RESULTS_DIR, "*", "pairs.parquet"))):
        if "_stale_" in f:
            continue
        df = pd.read_parquet(f)
        if df.empty:
            continue
        df["_source_dir"] = os.path.basename(os.path.dirname(f))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== bayesian_pair_confirmation.py: continuously-updated Bayesian confidence, "
              "COMPARISON ARM ONLY (does not replace static EG+FDR confirmation) ===")

    pairs = load_all_confirmed_pairs()
    log.info("Loaded %d confirmed pairs across all timeframes", len(pairs))
    if pairs.empty:
        log.warning("No confirmed pairs found -- aborting.")
        return

    holdout_path = os.path.join(_BACKTEST_DIR, "trades_layer1_holdout.parquet")
    if not os.path.exists(holdout_path):
        log.warning("No OOS holdout trades file found at %s -- every pair will show "
                    "prior-only (0 OOS trades). Run backtest.py first for a real update.", holdout_path)
        trades = pd.DataFrame(columns=["symbol_a", "symbol_b", "tf", "pnl_net"])
    else:
        trades = pd.read_parquet(holdout_path)
        log.info("Loaded %d OOS holdout trades across %d unique pairs",
                  len(trades), trades[["symbol_a", "symbol_b", "tf"]].drop_duplicates().shape[0])

    rows = []
    for _, row in pairs.iterrows():
        sym_a, sym_b, tf = row["symbol_a"], row["symbol_b"], row["tf_label"]
        adj_p = row.get("coint_pvalue_adjusted", np.nan)
        if pd.isna(adj_p):
            continue
        a0, b0 = prior_from_adjusted_pvalue(float(adj_p))
        prior_mean = a0 / (a0 + b0)
        prior_lo, prior_hi = credible_interval(a0, b0)

        pair_trades = trades[
            (trades["symbol_a"] == sym_a) & (trades["symbol_b"] == sym_b) & (trades["tf"] == tf)
        ]
        pnl = pair_trades["pnl_net"].to_numpy(dtype=float)
        a_post, b_post, n_wins, n_losses = posterior_from_trades(a0, b0, pnl)
        post_mean = a_post / (a_post + b_post)
        post_lo, post_hi = credible_interval(a_post, b_post)

        rows.append({
            "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf,
            "coint_pvalue_adjusted": float(adj_p),
            "prior_mean": prior_mean, "prior_ci_lo": prior_lo, "prior_ci_hi": prior_hi,
            "n_oos_trades": len(pnl), "n_wins": n_wins, "n_losses": n_losses,
            "posterior_mean": post_mean, "posterior_ci_lo": post_lo, "posterior_ci_hi": post_hi,
            "shift": post_mean - prior_mean,
        })
        log.info(
            "  %s/%s@%s: prior=%.3f [%.3f, %.3f]  n_oos=%d (%d win/%d loss)  "
            "posterior=%.3f [%.3f, %.3f]  shift=%+.3f",
            sym_a, sym_b, tf, prior_mean, prior_lo, prior_hi,
            len(pnl), n_wins, n_losses, post_mean, post_lo, post_hi, post_mean - prior_mean,
        )

    result_df = pd.DataFrame(rows)
    log.info("")
    log.info("=== Summary: %d pairs, %d with at least 1 OOS trade ===",
              len(result_df), int((result_df["n_oos_trades"] > 0).sum()))

    os.makedirs(_OUT_DIR, exist_ok=True)
    result_df.to_parquet(os.path.join(_OUT_DIR, "bayesian_pair_confirmation.parquet"), index=False)
    log.info("Saved -> output/research/bayesian_pair_confirmation.parquet")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("bayesian_pair_confirmation.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
