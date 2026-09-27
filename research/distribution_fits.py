"""
research/distribution_fits.py -- audit step 3 (2026-09-26, Ross-approved plan): which standard
distribution family best describes each of CAMARF's core random quantities.

Each family is fitted only to the kind of variable it can actually model (the agreed mapping --
fitting every family to one series would be meaningless and a multiple-testing trap):

| Variable (source)                                   | Families                                   |
|-----------------------------------------------------|--------------------------------------------|
| Entries per business day, zero-filled (trades, OLS) | Poisson vs negative binomial (overdispersion)|
| Hold time in bars (trades, OLS)                     | geometric (discrete); expon/gamma/Weibull/lognormal (continuous view) |
| Half-life at entry (trades, OLS)                    | expon / gamma / Weibull / lognormal         |
| Label-horizon z change z_future - z_entry (ml events)| normal / Cauchy / Student-t (tail weight)   |
| Per-pair convergence count out of events (ml events)| binomial vs beta-binomial (heterogeneity)   |

DEFERRED, stated rather than substituted: fits of trade P&L / spread returns, and the exact
hypergeometric version of the capital-constraint luck check, both depend on backtest.py's P&L,
which is confirmed broken (code review B2 beta drift, B3 unit mixing, B4 OLS/Kalman double count).

Method: maximum likelihood per family (loc fixed at 0 for positive families), AIC and BIC for
selection, and a parametric-bootstrap goodness-of-fit p-value (Anderson-Darling statistic for
continuous families, max |ECDF - CDF| for discrete; parameters re-estimated on every bootstrap
sample, so the test is valid with estimated parameters). GOF runs on a random subsample of at most
--gof-max-n points (disclosed in the output): at n in the tens of thousands every parametric family
is rejected for trivial deviations, so AIC/BIC ranking plus the effect-size statistic is the
informative part, not the p-value alone.

Trades are filtered to hedge_method == "ols" (B4: OLS/Kalman copies are near-duplicates) and to
1D bars. hold_bars / exits depend on the spread's z-score path, which itself uses the rolling
hedge ratio -- disclosed; they do not depend on the broken P&L accounting.

Verified against synthetic ground truth first: debug/_verify_distribution_fits.py.

Usage (project root; CachyOS holds the current 1,375-pair trades files):
    python research/distribution_fits.py [--trades PATH] [--gof-reps 200] [--gof-max-n 5000]
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import optimize, stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_DEFAULT_TRADES = os.path.join("output", "backtest", "trades_layer1_storm_momgate_pairsoverride.parquet")


# ---------------------------------------------------------------------------
# Continuous families
# ---------------------------------------------------------------------------

def _cont_fit(name, x, positive):
    d = getattr(stats, name)
    theta = d.fit(x, floc=0) if positive else d.fit(x)
    names = (d.shapes.split(", ") if d.shapes else []) + ["loc", "scale"]
    params = dict(zip(names, map(float, theta)))
    k = len(theta) - (1 if positive else 0)
    return d(*theta), params, k


def _ad_stat(u):
    u = np.clip(np.sort(u), 1e-12, 1 - 1e-12)
    n = len(u)
    i = np.arange(1, n + 1)
    return float(-n - np.mean((2 * i - 1) * (np.log(u) + np.log(1 - u[::-1]))))


def fit_continuous(x, families, positive, gof_reps=200, gof_max_n=5000, rng=None):
    rng = rng or np.random.default_rng(42)
    x = np.asarray(x, float)
    x = x[np.isfinite(x) & ((x > 0) if positive else True)]
    xg = x if len(x) <= gof_max_n else rng.choice(x, gof_max_n, replace=False)
    rows = []
    for name in families:
        try:
            frozen, params, k = _cont_fit(name, x, positive)
        except Exception as e:
            rows.append({"family": name, "error": f"{type(e).__name__}: {e}"})
            continue
        ll = float(np.sum(frozen.logpdf(x)))
        row = {"family": name, "params": params, "k": k, "n": len(x), "loglik": ll,
               "aic": 2 * k - 2 * ll, "bic": k * np.log(len(x)) - 2 * ll,
               "ks_D": float(stats.kstest(x, frozen.cdf).statistic), "gof_p": np.nan, "gof_n": len(xg)}
        if gof_reps:
            fg, _, _ = _cont_fit(name, xg, positive)
            a_obs = _ad_stat(fg.cdf(xg))
            null = []
            for _ in range(gof_reps):
                xb = fg.rvs(len(xg), random_state=rng)
                try:
                    fb, _, _ = _cont_fit(name, xb, positive)
                    null.append(_ad_stat(fb.cdf(xb)))
                except Exception:
                    continue
            row["gof_stat_ad"] = a_obs
            row["gof_p"] = (1 + sum(a >= a_obs for a in null)) / (1 + len(null))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Discrete families
# ---------------------------------------------------------------------------

def _count_fit(name, k):
    m = float(np.mean(k))
    if name == "poisson":
        return stats.poisson(m), {"mu": m}, 1
    if name == "geom":  # support 1, 2, ...
        p = 1.0 / m
        return stats.geom(p), {"p": p}, 1
    if name == "nbinom":
        v = float(np.var(k))
        r0 = m * m / (v - m) if v > m else 50.0

        def nll(th):
            r, p = np.exp(th[0]), 1 / (1 + np.exp(-th[1]))
            return -np.sum(stats.nbinom.logpmf(k, r, p))
        th0 = [np.log(r0), np.log((r0 / (r0 + m)) / (1 - r0 / (r0 + m)))]
        res = optimize.minimize(nll, th0, method="Nelder-Mead", options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 4000})
        r, p = float(np.exp(res.x[0])), float(1 / (1 + np.exp(-res.x[1])))
        return stats.nbinom(r, p), {"n": r, "p": p}, 2
    raise ValueError(name)


def fit_counts(k, families, gof_reps=200, gof_max_n=5000, rng=None):
    rng = rng or np.random.default_rng(42)
    k = np.asarray(k).astype(int)
    kg = k if len(k) <= gof_max_n else rng.choice(k, gof_max_n, replace=False)
    rows = []
    for name in families:
        if name == "geom" and k.min() < 1:
            rows.append({"family": name, "error": "geom support starts at 1"})
            continue
        frozen, params, npar = _count_fit(name, k)
        ll = float(np.sum(frozen.logpmf(k)))
        row = {"family": name, "params": params, "k": npar, "n": len(k), "loglik": ll,
               "aic": 2 * npar - 2 * ll, "bic": npar * np.log(len(k)) - 2 * ll,
               "gof_p": np.nan, "gof_n": len(kg)}
        if gof_reps:
            def dstat(sample, fz):
                grid = np.arange(sample.min(), sample.max() + 1)
                ecdf = np.searchsorted(np.sort(sample), grid, side="right") / len(sample)
                return float(np.max(np.abs(ecdf - fz.cdf(grid))))
            fg, _, _ = _count_fit(name, kg)
            d_obs = dstat(kg, fg)
            null = []
            for _ in range(gof_reps):
                kb = fg.rvs(len(kg), random_state=rng)
                if name == "geom" and kb.min() < 1:
                    continue
                fb, _, _ = _count_fit(name, kb)
                null.append(dstat(kb, fb))
            row["gof_stat_D"] = d_obs
            row["gof_p"] = (1 + sum(d >= d_obs for d in null)) / (1 + len(null))
        rows.append(row)
    return pd.DataFrame(rows)


def fit_binomial_family(successes, trials):
    """Binomial (one common rate) vs beta-binomial (unit-level rate heterogeneity) for per-unit
    success counts out of known trial counts."""
    s = np.asarray(successes).astype(int)
    n = np.asarray(trials).astype(int)
    p = s.sum() / n.sum()
    ll_b = float(np.sum(stats.binom.logpmf(s, n, p)))

    # Parametrized by mean mu and overdispersion rho = 1/(a+b+1), rho bounded to [1e-6, 1-1e-6].
    # Found by the synthetic check (2026-09-26): unbounded (a, b) drifts to ~1e12 on homogeneous
    # data (the binomial limit), where scipy's betabinom.logpmf loses precision to gammaln
    # cancellation and reported a log-likelihood 27 units ABOVE the binomial's -- a numerical
    # artifact that made BIC pick beta-binomial on data with no heterogeneity at all.
    def _ab(th):
        mu = 1 / (1 + np.exp(-th[0]))
        rho = 1e-6 + (1 - 2e-6) / (1 + np.exp(-th[1]))
        c = (1 - rho) / rho
        return mu * c, (1 - mu) * c

    def nll(th):
        a_, b_ = _ab(th)
        return -np.sum(stats.betabinom.logpmf(s, n, a_, b_))
    res = optimize.minimize(nll, [np.log(p / (1 - p)), 0.0], method="Nelder-Mead",
                            options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 4000})
    a, b = (float(v) for v in _ab(res.x))
    # The binomial is the rho -> 0 limit of the beta-binomial, so the beta-binomial MLE can never
    # have a lower likelihood; taking the max guards the boundary case exactly.
    ll_bb = max(-float(res.fun), ll_b)
    N = len(s)
    rows = [
        {"family": "binomial", "params": {"p": float(p)}, "k": 1, "n": N, "loglik": ll_b,
         "aic": 2 - 2 * ll_b, "bic": np.log(N) - 2 * ll_b},
        {"family": "betabinom", "params": {"a": a, "b": b, "mean": a / (a + b),
                                            "overdispersion_rho": 1 / (a + b + 1)},
         "k": 2, "n": N, "loglik": ll_bb, "aic": 4 - 2 * ll_bb, "bic": 2 * np.log(N) - 2 * ll_bb},
    ]
    # Likelihood-ratio test binomial (rho=0, boundary) vs beta-binomial: chi-bar-square 50:50 mixture.
    lr = max(0.0, 2 * (ll_bb - ll_b))
    for r in rows:
        r["lr_stat_vs_binomial"] = lr
        r["lr_p_boundary"] = 0.5 * stats.chi2.sf(lr, 1) if lr > 0 else 1.0
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", default=_DEFAULT_TRADES)
    ap.add_argument("--gof-reps", type=int, default=200)
    ap.add_argument("--gof-max-n", type=int, default=5000)
    args = ap.parse_args()
    rng = np.random.default_rng(42)
    results = {}

    T = pd.read_parquet(args.trades)
    n_all = len(T)
    T = T[(T["hedge_method"] == "ols") & (T["tf"] == "1D")].copy()
    T["entry_time"] = pd.to_datetime(T["entry_time"])
    print(f"Trades: {args.trades} -> {len(T)} of {n_all} rows (OLS, 1D)")

    days = pd.bdate_range(T["entry_time"].min().normalize(), T["entry_time"].max().normalize())
    per_day = T.groupby(T["entry_time"].dt.normalize()).size().reindex(days, fill_value=0).to_numpy()
    print(f"\n[entries per business day] n_days={len(per_day)} mean={per_day.mean():.3f} var={per_day.var():.3f}")
    results["entries_per_bday"] = fit_counts(per_day, ["poisson", "nbinom"], args.gof_reps, args.gof_max_n, rng)

    hb = T["hold_bars"].dropna().astype(int)
    hb = hb[hb >= 1].to_numpy()
    print(f"[hold_bars] n={len(hb)} mean={hb.mean():.2f} median={np.median(hb):.0f}")
    results["hold_bars_discrete"] = fit_counts(hb, ["geom", "nbinom", "poisson"], args.gof_reps, args.gof_max_n, rng)
    results["hold_bars_continuous"] = fit_continuous(hb, ["expon", "gamma", "weibull_min", "lognorm"], True,
                                                     args.gof_reps, args.gof_max_n, rng)

    hl = T["half_life_at_entry"].to_numpy(float)
    print(f"[half_life_at_entry] n={np.isfinite(hl).sum()}")
    results["half_life_at_entry"] = fit_continuous(hl, ["expon", "gamma", "weibull_min", "lognorm"], True,
                                                   args.gof_reps, args.gof_max_n, rng)

    import ml
    ex = ml.build(min_class_samples=0, pit_safe=True).examples
    dz = (ex["z_future"] - ex["z_entry"]).to_numpy(float)
    print(f"[z_future - z_entry] n={np.isfinite(dz).sum()}")
    results["z_change_at_horizon"] = fit_continuous(dz, ["norm", "cauchy", "t"], False,
                                                    args.gof_reps, args.gof_max_n, rng)
    pos = sorted(ex["label_for_training"].unique())
    conv_label = "converged" if "converged" in pos else pos[-1]
    g = ex.groupby(["symbol_a", "symbol_b", "tf_label"])["label_for_training"]
    succ = g.apply(lambda s: int((s == conv_label).sum())).to_numpy()
    tot = g.size().to_numpy()
    print(f"[per-pair convergence] pairs={len(tot)} events={tot.sum()} success label='{conv_label}'")
    results["per_pair_convergence"] = fit_binomial_family(succ, tot)

    os.makedirs(_OUT_DIR, exist_ok=True)
    frames = []
    for var, df in results.items():
        df = df.copy()
        df.insert(0, "variable", var)
        df["params"] = df["params"].apply(lambda p: json.dumps(p) if isinstance(p, dict) else p)
        frames.append(df)
        best_aic = df.sort_values("aic").iloc[0]["family"]
        best_bic = df.sort_values("bic").iloc[0]["family"]
        print(f"\n== {var}: best AIC={best_aic}, best BIC={best_bic}")
        cols = [c for c in ("family", "k", "n", "loglik", "aic", "bic", "ks_D", "gof_p", "gof_n",
                            "lr_stat_vs_binomial", "lr_p_boundary", "params") if c in df.columns]
        print(df[cols].to_string(index=False))
    out = pd.concat(frames, ignore_index=True)
    out["deferred"] = "trade P&L / spread-return fits and hypergeometric luck-check: depend on broken P&L (B2-B4)"
    out.to_parquet(os.path.join(_OUT_DIR, "distribution_fits.parquet"))
    print(f"\nSaved {len(out)} rows -> output/research/distribution_fits.parquet")


if __name__ == "__main__":
    main()
