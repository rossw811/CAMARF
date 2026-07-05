"""
CAMARF bertram_ou_thresholds.py — comparison/diagnostic method, NOT part
of the production pipeline.

Bertram (2010), "Analytic Solutions for Optimal Statistical Arbitrage
Trading," Physica A 389(11) — closed-form optimal entry/exit z-thresholds
for an OU spread, maximizing expected return PER UNIT TIME (not per
trade) net of a round-trip transaction cost, via first-passage-time
analysis. Answers whether CAMARF's production entry z=2.0 (or the
empirically grid-search-optimal z=2.5, PAPER.md Section 7.8) is close to
what the OU process's own fitted parameters imply is analytically
optimal — an independent check that doesn't require more OOS data.

IMPORTANT — what's actually implemented here, and why: Bertram's own
closed-form solution requires the OU process's exact first-passage-time
distribution, expressed via a special-function integral (related to the
Dawson function). Rather than re-derive that integral from memory with no
way to independently check it, this module finds the SAME optimal
threshold Bertram's formula would by directly Monte Carlo simulating the
fitted OU process at a grid of candidate entry z-levels, exiting at the
mean (z=0), and computing the empirical expected-profit-per-unit-time for
each candidate — then reports the grid maximizer. This is the identical
economic objective Bertram (2010) defines, solved by simulation instead of
his closed form; verified via sanity checks Bertram's own theory predicts
(optimal threshold shrinks toward 0 as transaction cost -> 0, and grows as
cost increases) rather than an exact-formula-matching check, since no
independent closed-form is available here to check against.

Transaction cost is expressed as a FRACTION of the spread's own
unconditional standard deviation (a scale-free placeholder), NOT a real
dollar cost — converting to dollars would require assuming a specific
notional/share-count convention this module doesn't have a principled way
to pick. Treat the resulting optimal z* as directionally informative
(is 2.0 in the right neighborhood?), not as a literal dollar-optimal
number.

Read-only. Excludes DATA_GAP-flagged padding on both legs.

Usage:
    python research/bertram_ou_thresholds.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TF_DIRS = [
    "1min", "2min", "3min", "5min", "15min", "30min", "1hr", "4hr",
    "7day", "1mo", "3mo", "6mo",
]
_DIR_TO_LABEL = {
    "1min": "1m", "2min": "2m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1hr": "1h", "4hr": "4h", "7day": "7D", "1mo": "1M",
    "3mo": "3M", "6mo": "6M",
}


def _resolve_tf_results_dir(tf_dir):
    live = os.path.join("output", "results", tf_dir)
    if os.path.isdir(live):
        return live, False
    candidates = sorted(glob.glob(os.path.join("output", "results", f"{tf_dir}_stale_*")))
    return (candidates[-1], True) if candidates else (live, False)


def fit_discrete_ou(z):
    """z_t = rho*z_{t-1} + eps_t (demeaned, no intercept). Returns
    (rho, sigma_eps, sigma_stationary)."""
    z = z - np.mean(z)
    z_lag, z_t = z[:-1], z[1:]
    rho = float(np.dot(z_lag, z_t) / np.dot(z_lag, z_lag))
    resid = z_t - rho * z_lag
    sigma_eps = float(np.std(resid, ddof=1))
    sigma_stationary = sigma_eps / np.sqrt(max(1 - rho ** 2, 1e-8))
    return rho, sigma_eps, sigma_stationary


def simulate_profit_rate(rho, sigma_eps, sigma_stationary, entry_z, cost_frac,
                          n_paths=500, max_bars=5000, rng=None):
    """
    Monte Carlo expected profit-PER-UNIT-CALENDAR-TIME for a full repeated
    trading cycle: starting flat at z=0, WAIT until the process first
    reaches the entry level (z >= entry_z*sigma_stationary) — real elapsed
    time with no position held — THEN hold until it reverts back to z=0,
    realizing profit_per_cycle = entry_level - cost.

    The wait-to-enter leg matters and is not optional: an earlier version
    of this function only simulated the hold-to-exit leg (profit divided
    by reversion time alone), which pushed the "optimal" threshold to the
    edge of every tested grid regardless of cost, since reversion time
    from a level grows only slowly (roughly logarithmically) with that
    level while captured profit grows linearly — an unbounded-looking
    objective that never trades off against a larger threshold. Confirmed
    by running it: cost sensitivity checks failed completely (optimal z*
    stuck at the top of the grid at every cost level). Including the
    waiting time — which grows with the entry level too, since it takes
    longer for a mean-reverting process to randomly wander out further —
    is what creates a genuine interior trade-off between profit-per-trade
    and trade frequency, which is Bertram's actual economic objective.
    """
    if rng is None:
        rng = np.random.default_rng(0)
    entry_level = entry_z * sigma_stationary
    cost = cost_frac * sigma_stationary
    profit_per_cycle = entry_level - cost
    if profit_per_cycle <= 0:
        return 0.0, np.nan  # cost exceeds the move captured — never worth trading

    cycle_lengths = np.empty(n_paths)
    for p in range(n_paths):
        # Leg 1: wait for z to first reach the entry level, starting from 0.
        z = 0.0
        t_wait = 0
        for t in range(1, max_bars + 1):
            z = rho * z + rng.normal(scale=sigma_eps)
            t_wait = t
            if z >= entry_level:
                break
        # Leg 2: hold until z reverts back to 0.
        t_hold = 0
        for t in range(1, max_bars + 1):
            z = rho * z + rng.normal(scale=sigma_eps)
            t_hold = t
            if z <= 0:
                break
        cycle_lengths[p] = t_wait + t_hold
    mean_cycle = float(np.mean(cycle_lengths))
    profit_rate = profit_per_cycle / mean_cycle
    return float(profit_rate), mean_cycle


def optimal_entry_z(rho, sigma_eps, sigma_stationary, cost_frac,
                     z_grid=None, n_paths=300, rng=None):
    if z_grid is None:
        z_grid = np.arange(0.5, 3.55, 0.25)
    if rng is None:
        rng = np.random.default_rng(0)
    rates = []
    for ez in z_grid:
        rate, _cycle = simulate_profit_rate(rho, sigma_eps, sigma_stationary, ez,
                                             cost_frac, n_paths=n_paths, rng=rng)
        rates.append(rate)
    rates = np.array(rates)
    best_idx = int(np.argmax(rates))
    return float(z_grid[best_idx]), rates, z_grid


def main():
    rng = np.random.default_rng(0)
    rows = []
    for tf_dir in _TF_DIRS:
        results_dir, is_stale = _resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            print(f"NOTE {tf_dir}: using archived {results_dir}")
        tf_label = _DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)
        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            series_path = os.path.join(results_dir, f"spread_series_{sym_a}_{sym_b}.parquet")
            if not os.path.exists(series_path):
                continue
            df = pd.read_parquet(series_path)
            real_mask = (df["gap_flag_a"] != 4) & (df["gap_flag_b"] != 4)
            z = df.loc[real_mask, "spread"].to_numpy(dtype=float)
            z = z[np.isfinite(z)]
            if z.size < 200:
                continue
            rho, sigma_eps, sigma_stationary = fit_discrete_ou(z)
            if not (0 < rho < 1):
                continue  # not a mean-reverting fit on this series — skip rather than force a result
            best_z, rates, grid = optimal_entry_z(rho, sigma_eps, sigma_stationary,
                                                    cost_frac=0.10, n_paths=200, rng=rng)
            rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
                "rho": rho, "optimal_entry_z": best_z,
            })
            print(f"{sym_a}/{sym_b}@{tf_label}: rho={rho:.4f} optimal_entry_z*={best_z:.2f} "
                  f"(production uses 2.0, grid-search-best was 2.5)")

    out_df = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out_df.to_parquet("output/research/bertram_ou_thresholds.parquet")
    if len(out_df):
        print(f"\nWrote output/research/bertram_ou_thresholds.parquet: {len(out_df)} pairs, "
              f"median optimal_entry_z*={out_df['optimal_entry_z'].median():.2f}")


if __name__ == "__main__":
    main()
