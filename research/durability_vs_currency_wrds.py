"""
research/durability_vs_currency_wrds.py -- Re-derives PAPER.md §4.2's
durability-vs-currency demonstration (NTRS/STT, SHW/UNP: full-sample EG
significance vs. last-5-years-only EG significance) on real WRDS/CRSP
data, replacing the original pre-WRDS (yfinance-era) demonstration per
Ross's 2026-09-10 instruction: nothing pre-WRDS gets considered for
writing. Same pairs, same logic, same `analysis.py._eg_worker` production
function -- only the data source changes, so this is a direct like-for-
like re-derivation, not a new claim.

D13 / R8.12 (Ross 2026-10-12; fixed 2026-10-19): a non-significant last-5-years test (n ~1,260) beside a significant
full-sample one (n ~10,000+) was read as "already failed", but the short test may lack power. Each pair now reports the
Monte Carlo power of the 5-year test (a) at the effect the full sample estimates (residual AR(1) rho and innovation
s.d., hedge ratio, regressor-leg return s.d.) and (b) at the 5-year window's own estimate -- both descriptive (they use
the whole window). Also R8.12: the EG call is now production's (analysis.eg_pvalue_pair: both directions, max p,
Config.ANALYSIS.EG_MAX_LAG; was one direction with max_lag=None) and the output directory is created.
research/rederive_durability_claims.py keeps the as-published one-direction arm. debug/_verify_durability_power_d13.py
Review of a51f926c: real innovations are fat-tailed and clustered (NTRS/STT excess kurtosis ~249), so power is also
computed from contiguous real blocks of the full-sample innovations and leg returns (power_at_blocks); each pair also
reports P(simulated 5-year p >= observed 5-year p | full-sample effect) -- the evidence the observed p carries -- and
whether the full sample detects an effect at all (power at an undetected "effect" is just the test's size).

Run: python research/durability_vs_currency_wrds.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lfilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import eg_pvalue_pair
from config import Config

_N_SIM_POWER = 500   # MC s.e. of a power estimate <= 0.022 (at power 0.5)

WRDS_CACHE = Path(__file__).resolve().parent.parent / "output" / "cache" / "wrds"
PAIRS = [("XOM", "CVX"), ("JPM", "BAC"), ("KO", "PEP"), ("NTRS", "STT"), ("SHW", "UNP")]


def load_log_close(symbol):
    df = pd.read_parquet(WRDS_CACHE / f"{symbol}_1D.parquet")
    close = df["close_total_return"].astype(float)
    return np.log(close.values), df.index


def _prod_p(a, b):
    p, n = eg_pvalue_pair(a, b, Config.ANALYSIS.EG_MAX_LAG, "1D")
    return (np.nan if p is None else float(p)), n


def estimate_effect(y, x, return_series: bool = False) -> dict:
    """Cointegrating effect on one window (descriptive): OLS hedge ratio, residual AR(1) rho (no intercept on the
    demeaned residual), innovation s.d., and the regressor leg's daily log-return s.d."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    X = np.column_stack([np.ones(len(x)), x])
    c, beta = np.linalg.lstsq(X, y, rcond=None)[0]
    u = y - c - beta * x
    rho = float(np.dot(u[1:], u[:-1]) / np.dot(u[:-1], u[:-1]))
    out = {"beta": float(beta), "rho": rho, "sigma_e": float(np.std(u[1:] - rho * u[:-1], ddof=1)),
           "sigma_x": float(np.std(np.diff(x), ddof=1))}
    if return_series:
        out["innov"] = u[1:] - rho * u[:-1]      # residual innovations
        out["dx"] = np.diff(x)                   # regressor-leg log returns, same dates
    return out


def power_at(effect: dict, n: int, n_sim: int = _N_SIM_POWER, rng=None) -> float:
    """Share of n_sim simulated n-day windows at `effect` in which the production EG test rejects at
    Config.ANALYSIS.EG_SIGNIFICANCE. Residual starts from its stationary distribution (rho < 1)."""
    rng = rng or np.random.default_rng(0)
    rho, se = float(effect["rho"]), float(effect["sigma_e"])
    rej = 0
    for _ in range(n_sim):
        x = np.cumsum(rng.normal(0, effect["sigma_x"], n))
        e = rng.normal(0, se, n)
        if rho < 1:
            e[0] = rng.normal(0, se / np.sqrt(1 - rho ** 2))
        u = lfilter([1.0], [1.0, -rho], e)
        p, _ = _prod_p(effect["beta"] * x + u, x)
        rej += bool(np.isfinite(p) and p < Config.ANALYSIS.EG_SIGNIFICANCE)
    return rej / n_sim


def _sim_p_values(effect: dict, n: int, n_sim: int, rng, blocks: bool) -> np.ndarray:
    rho = float(effect["rho"])
    out = np.empty(n_sim)
    for i in range(n_sim):
        if blocks:
            s0 = rng.integers(0, len(effect["innov"]) - n + 1)
            e, dx = effect["innov"][s0:s0 + n].copy(), effect["dx"][s0:s0 + n]
        else:
            e, dx = rng.normal(0, effect["sigma_e"], n), rng.normal(0, effect["sigma_x"], n)
        if rho < 1:
            e[0] = (rng.choice(effect["innov"]) if blocks else rng.normal(0, effect["sigma_e"])) / np.sqrt(1 - rho ** 2)
        x = np.cumsum(dx)
        p, _ = _prod_p(effect["beta"] * x + lfilter([1.0], [1.0, -rho], e), x)
        out[i] = p
    return out


def power_at_blocks(effect: dict, n: int, n_sim: int = _N_SIM_POWER, rng=None) -> float:
    """Power of the production EG test at `effect` with the residual innovations and regressor returns taken as one
    contiguous block of the real full-sample series (fat tails, volatility clustering and their co-movement kept).
    effect from estimate_effect(..., return_series=True)."""
    p = _sim_p_values(effect, n, n_sim, rng or np.random.default_rng(0), blocks=True)
    return float(np.mean(np.isfinite(p) & (p < Config.ANALYSIS.EG_SIGNIFICANCE)))


def run_pair(sym_a, sym_b, n_sim: int = _N_SIM_POWER, rng=None):
    a_log, a_idx = load_log_close(sym_a)
    b_log, b_idx = load_log_close(sym_b)
    a_series = pd.Series(a_log, index=a_idx)
    b_series = pd.Series(b_log, index=b_idx)
    common = a_series.index.intersection(b_series.index)
    a_aligned = a_series.loc[common]
    b_aligned = b_series.loc[common]

    # 2026-10-02 (claims registry re-derivation): n and the start date used to count CALENDAR ROWS, including the
    # years before either leg has a price (NaN) -- NTRS/STT reported "13,373 obs since 1972" when the legs only
    # overlap from 1985-12-03 (~10,100 obs). Report the days on which BOTH legs have a value; EG itself (via
    # _eg_worker) already used only valid data, so the p-values were unaffected.
    both = a_aligned.notna() & b_aligned.notna() & np.isfinite(a_aligned) & np.isfinite(b_aligned)
    full_start, full_end = common[both.to_numpy()].min(), common[both.to_numpy()].max()
    n_full = int(both.sum())

    p_full, _ = _prod_p(a_aligned.values, b_aligned.values)

    cutoff = full_end - pd.DateOffset(years=5)
    recent_mask = common >= cutoff
    a_recent = a_aligned.values[recent_mask]
    b_recent = b_aligned.values[recent_mask]
    p_recent, _ = _prod_p(a_recent, b_recent)
    n_recent = int(recent_mask.sum())
    rng = rng or np.random.default_rng(20261019)
    eff_full = estimate_effect(a_aligned.values, b_aligned.values, return_series=True)
    eff_recent = estimate_effect(a_recent, b_recent)
    pow_full = power_at(eff_full, n_recent, n_sim, rng)
    pow_recent = power_at(eff_recent, n_recent, n_sim, rng)
    p_g = _sim_p_values(eff_full, n_recent, n_sim, rng, blocks=False)
    p_b = _sim_p_values(eff_full, n_recent, n_sim, rng, blocks=True)
    pow_full_blocks = float(np.mean(np.isfinite(p_b) & (p_b < Config.ANALYSIS.EG_SIGNIFICANCE)))
    p_ge_g = float(np.mean(p_g[np.isfinite(p_g)] >= p_recent)) if np.isfinite(p_recent) else np.nan
    p_ge_b = float(np.mean(p_b[np.isfinite(p_b)] >= p_recent)) if np.isfinite(p_recent) else np.nan
    detected = bool(np.isfinite(p_full) and p_full < Config.ANALYSIS.EG_SIGNIFICANCE)

    print(f"\n{sym_a}/{sym_b}:")
    print(f"  Full-sample ({full_start.date()} to {full_end.date()}, n={n_full}): "
          f"EG p={p_full:.4f} (production: both directions, max p)")
    print(f"  Last 5 years ({cutoff.date()} to {full_end.date()}, n={recent_mask.sum()}): "
          f"EG p={p_recent:.4f}; power of this test at the full-sample effect (rho {eff_full['rho']:.4f}) "
          f"{pow_full:.2f} (real blocks {pow_full_blocks:.2f}), at the window's own (rho {eff_recent['rho']:.4f}) "
          f"{pow_recent:.2f}; P(p >= observed | full-sample effect) {p_ge_g:.2f} gaussian / {p_ge_b:.2f} blocks"
          + ("" if detected else "  [full sample detects no effect: power here is about the test's size]"))
    return {
        "pair": f"{sym_a}/{sym_b}",
        "full_start": str(full_start.date()),
        "full_end": str(full_end.date()),
        "n_full": n_full,
        "p_full": p_full,
        "n_recent": n_recent,
        "p_recent": p_recent,
        "rho_full": eff_full["rho"], "rho_recent": eff_recent["rho"],
        "power_recent_at_full_effect": pow_full,      # descriptive (whole-window estimates)
        "power_recent_at_recent_effect": pow_recent,
        "power_recent_at_full_effect_blocks": pow_full_blocks,
        "p_ge_observed_gaussian": p_ge_g, "p_ge_observed_blocks": p_ge_b,
        "full_sample_effect_detected": detected,
        "power_n_sim": n_sim,
    }


if __name__ == "__main__":
    results = [run_pair(a, b) for a, b in PAIRS]
    out_df = pd.DataFrame(results)
    out_path = Path(__file__).resolve().parent.parent / "output" / "research" / "durability_vs_currency_wrds.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)   # R8.12: was never created
    out_df.to_parquet(out_path)
    print(f"\nSaved to {out_path}")
    print(out_df.to_string())
