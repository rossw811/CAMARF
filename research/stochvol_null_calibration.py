"""
research/stochvol_null_calibration.py -- design A of docs/decisions/DECISIONS_2026-11-13_model_real_data.md (Ross
2026-11-13: "ill take your recommendations"). How anti-conservative is a placebo that keeps LESS volatility clustering
than real data? Unrelated pairs (no cointegration by construction) are simulated with stochastic volatility whose
clustering is MATCHED to real US series, and pushed through the discovery test and P2's yearly test; their false
rejection rates are compared with nominal and with the E1 v2c placebo's.

Real data enter only as MOMENTS of single series (mean ACF of |r| at lags 1-20, excess kurtosis) -- no pair, no test
statistic of real data is read. Descriptive input to a null generator, not a decision metric.

1. Targets: N_SERIES random US CRSP series (verified label map) with >= 2,520 valid daily log total returns; moments per
   series; series binned into deciles by ACF |r|; per decile the median (ACF, kurtosis).
2. Generators, fitted per decile on a (shape) grid by simulated moments (scale is irrelevant: the tests are invariant to
   the level of volatility):
   - Heston (full-truncation Euler, research/stochastic_vol_models.simulate_heston), daily units, rho 0, theta 1e-4:
     kappa (vol mean reversion) x xi (vol of vol).
   - SABR beta = 1 (lognormal), second shape: log-vol random walk with vol-of-vol nu (no mean reversion).
   Heston with Gaussian shocks cannot reach large kurtosis together with modest ACF; the fitted distance is reported
   per decile, never hidden.
3. Tests, exactly production's: discovery = analysis._eg_worker (statsmodels coint, trend c, maxlag 10, AIC) on 2,520
   bars, BOTH directions (each direction is one test row, as in the scan); P2 = yearly_family_test._pvalue fixed_adf /
   fixed_adf_schwert on 252-bar spreads. Pairs: two independent generator paths (corr 0) and, as a sensitivity, a
   common-factor version with return correlation 0.6 (all three components from the same fitted generator).
CPU only: the time is in the statsmodels tests (measured slower on the GPU, CLAUDE.md); the simulation share is
printed per run.
Verify: debug/_verify_stochvol_null_calibration.py
"""
import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

N_SERIES = 300
MIN_RETURNS = 2520
ACF_LAGS = 20
THETA = 1e-4                      # daily variance level (1% a day); tests are scale-invariant
BURN = 500
DISC_BARS = 2520                  # analysis / scan: EPISODIC_WINDOW_BARS
P2_BARS = 252
EG_MAX_LAG = 10                   # Config.ANALYSIS.EG_MAX_LAG (checked at import below)
KAPPAS = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)
XIS = (0.0, 0.002, 0.004, 0.006, 0.01, 0.015, 0.02, 0.03)          # vol-of-vol in variance units / sqrt(day)
NUS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12)
OUT = os.path.join(ROOT, "output", "research")


def series_moments(r: np.ndarray) -> tuple:
    """(mean ACF of |r - mean| at lags 1..ACF_LAGS, excess kurtosis) of one return series (NaNs dropped)."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if len(r) < ACF_LAGS + 2 or not r.std() > 0:     # e.g. a Heston path truncated to zero variance
        return float("nan"), float("nan")
    a = np.abs(r - r.mean())
    a = a - a.mean()
    den = float(np.dot(a, a))
    acf = np.mean([np.dot(a[:-k], a[k:]) / den for k in range(1, ACF_LAGS + 1)]) if den > 0 else 0.0
    z = (r - r.mean()) / r.std()
    return float(acf), float(np.mean(z ** 4) - 3.0)


def heston_returns(n_paths: int, n: int, kappa: float, xi: float, rng) -> np.ndarray:
    """(n, n_paths) daily log returns from Heston (rho 0, theta THETA, v0 THETA), after BURN steps."""
    from stochastic_vol_models import simulate_heston
    X, _ = simulate_heston(n_paths, n + BURN, 1.0, 1.0, 0.0, THETA, kappa, THETA, xi, 0.0, rng, return_paths=True)
    return np.diff(X, axis=0)[BURN:]


def sabr_returns(n_paths: int, n: int, nu: float, rng) -> np.ndarray:
    """(n, n_paths) daily log returns, SABR beta = 1: r_t = a_t z_t - a_t^2 / 2, log a a random walk with step nu,
    a_0 = sqrt(THETA). Written on log returns (no absorption)."""
    a0 = np.sqrt(THETA)
    la = np.log(a0) + np.cumsum(nu * rng.standard_normal((n + BURN, n_paths)) - 0.5 * nu * nu, axis=0)
    a = np.exp(la)[BURN:]
    return a * rng.standard_normal((n, n_paths)) - 0.5 * a * a


def generator(kind: str, params: dict):
    if kind == "heston":
        return lambda n_paths, n, rng: heston_returns(n_paths, n, params["kappa"], params["xi"], rng)
    if kind == "sabr":
        return lambda n_paths, n, rng: sabr_returns(n_paths, n, params["nu"], rng)
    if kind == "iid":
        return lambda n_paths, n, rng: np.sqrt(THETA) * rng.standard_normal((n, n_paths))
    raise ValueError(kind)


def sim_moments(gen, rng, n_paths: int = 40, n: int = 3000) -> tuple:
    R = gen(n_paths, n, rng)
    m = np.array([series_moments(R[:, j]) for j in range(R.shape[1])])
    if np.isnan(m[:, 0]).mean() > 0.5:                  # mostly degenerate paths: this grid point is unusable
        return float("nan"), float("nan")
    return float(np.nanmedian(m[:, 0])), float(np.nanmedian(m[:, 1]))


def fit(kind: str, target: tuple, rng) -> dict:
    """Grid fit by simulated moments: minimise relative squared distance in (ACF, kurtosis), ACF weighted 2:1 (it is
    the clustering being matched; kurtosis is a secondary shape)."""
    grid = ([{"kappa": k, "xi": x} for k in KAPPAS for x in XIS] if kind == "heston" else [{"nu": v} for v in NUS])
    best = None
    for p in grid:
        acf, kurt = sim_moments(generator(kind, p), rng)
        if not np.isfinite(acf):
            continue
        d =2 * ((acf - target[0]) / max(target[0], 1e-3)) ** 2 + ((kurt - target[1]) / max(abs(target[1]), 1.0)) ** 2
        if best is None or d < best["dist"]:
            best = {**p, "acf": acf, "kurt": kurt, "dist": float(d)}
    return best


def make_pairs(gen, n_pairs: int, n: int, corr: float, rng) -> tuple:
    """Two (n, n_pairs) log-price panels with no cointegration: independent generator paths, or with a common factor
    of return correlation `corr` (all components from the same generator)."""
    if corr == 0:
        ra, rb = gen(n_pairs, n, rng), gen(n_pairs, n, rng)
    else:
        f, ea, eb = gen(n_pairs, n, rng), gen(n_pairs, n, rng), gen(n_pairs, n, rng)
        w = np.sqrt(corr)
        ra, rb = w * f + np.sqrt(1 - corr) * ea, w * f + np.sqrt(1 - corr) * eb
    return np.cumsum(ra, axis=0), np.cumsum(rb, axis=0)


def _eg_both(args) -> list:
    """Production's EG worker, both directions (one row each, as the scan)."""
    from analysis import _eg_worker
    a, b = args
    out = []
    for x, y in ((a, b), (b, a)):
        r = _eg_worker(("A", "B", x, y, EG_MAX_LAG, "1D"))
        # the scan's rule (_window_row): ok -> p; insufficient overlap -> not a test; any other error -> p = 1.0
        out.append(float(r["pvalue"]) if r.get("ok") else
                   (np.nan if r.get("error") == "insufficient_overlap" else 1.0))
    return out


def _p2_years(args) -> list:
    """P2 fixed ADF (AIC, Schwert) on each 252-bar year of one pair's log-price spread."""
    from yearly_family_test import _pvalue
    a, b = args
    out = []
    for s in range(0, len(a) - P2_BARS + 1, P2_BARS):
        x, y = pd.Series(a[s:s + P2_BARS]), pd.Series(b[s:s + P2_BARS])
        out.append((_pvalue(x, y, "fixed_adf"), _pvalue(x, y, "fixed_adf_schwert")))
    return out


def _init_worker():
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[v] = "1"


def run_cell(gen, n_pairs: int, corr: float, seed: int, workers: int, p2_pairs: int) -> dict:
    rng = np.random.default_rng(seed)
    t0 = time.time()
    A, B = make_pairs(gen, n_pairs, DISC_BARS, corr, rng)
    t_sim = time.time() - t0
    with ProcessPoolExecutor(workers, initializer=_init_worker) as ex:
        eg = np.array([p for pr in ex.map(_eg_both, [(A[:, j], B[:, j]) for j in range(n_pairs)], chunksize=64)
                       for p in pr])
        p2 = np.array([p for pr in ex.map(_p2_years, [(A[:, j], B[:, j]) for j in range(min(p2_pairs, n_pairs))],
                                         chunksize=16) for p in pr])
    t_all = time.time() - t0
    eg = eg[np.isfinite(eg)]
    row = {"eg_tests": len(eg), "p2_tests": len(p2), "sim_share": round(t_sim / t_all, 4)}
    for t in (0.05, 1e-3, 1e-4, 2e-5):
        row[f"eg_p<{t:g}"] = float((eg < t).mean())
    for j, nm in enumerate(("aic", "schwert")):
        for t in (0.05, 0.01):
            row[f"p2_{nm}_p<{t:g}"] = float((p2[:, j] < t).mean())
    return row


def real_targets(src: str, n: int = N_SERIES, seed: int = 20261113) -> pd.DataFrame:
    import parquet_io
    from data_wrds import label_permno_map
    from placebo_discovery_e1 import _log_price
    labs = sorted(l for l in label_permno_map() if os.path.exists(os.path.join(src, f"{l}_1D.parquet")))
    np.random.default_rng(seed).shuffle(labs)
    rows = []
    for l in labs:
        lp = _log_price(parquet_io.read_parquet(os.path.join(src, f"{l}_1D.parquet")))
        r = lp.diff().dropna().to_numpy()
        if len(r) >= MIN_RETURNS:
            acf, kurt = series_moments(r)
            rows.append({"label": l, "n": len(r), "acf": acf, "kurt": kurt})
        if len(rows) >= n:
            break
    T = pd.DataFrame(rows)
    T["decile"] = pd.qcut(T["acf"].rank(method="first"), 10, labels=False)
    return T


# =====================================================================================================================
# A2 (Ross 2026-11-15 "go for it", after the review WITHDREW the Heston reading: every fitted Heston point violated
# Feller and 27-53% of its returns were exactly 0). Log-volatility AR(1) with Student-t shocks -- volatility is always
# positive -- fitted to the ACF of |r| at SHORT (1-20) and LONG (240-260) lags plus kurtosis; the two legs of a pair
# share a volatility factor (loading c) and have correlated shocks (rho), both fitted to REAL candidate pairs' median
# return and |r| correlation inside the windows they were tested in (pair moments only). Rates reported down to 2e-5.
# =====================================================================================================================
LONG_LAGS = (240, 261)
CHUNK = 5000
PHIS = (0.95, 0.98, 0.99, 0.995, 0.998, 0.999)
ETAS = (0.03, 0.06, 0.1, 0.15, 0.2, 0.3)
DOFS = (4.5, 5.0, 6.0, 8.0, 12.0, 30.0)
LOADINGS = (0.0, 0.2, 0.4, 0.6, 0.8, 0.9)
RHOS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)


def acf_abs(r: np.ndarray, lags) -> np.ndarray:
    """ACF of |r - mean| at the given lags (FFT; NaNs dropped)."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    a = np.abs(r - r.mean())
    a = a - a.mean()
    n = a.size
    f = np.fft.rfft(a, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    return ac[np.asarray(lags)] / ac[0] if ac[0] > 0 else np.full(len(lags), np.nan)


def moments2(r: np.ndarray) -> tuple:
    """(mean ACF |r| lags 1-20, mean ACF |r| lags 240-260, excess kurtosis)."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if r.size < LONG_LAGS[1] + 50 or not r.std() > 0:
        return (np.nan,) * 3
    z = (r - r.mean()) / r.std()
    return (float(np.mean(acf_abs(r, range(1, ACF_LAGS + 1)))), float(np.mean(acf_abs(r, range(*LONG_LAGS)))),
            float(np.mean(z ** 4) - 3.0))


def logvol_paths(n_paths: int, n: int, phi: float, eta: float, rng) -> np.ndarray:
    """(n, n_paths) stationary AR(1) log-vol deviations h_t = phi h_(t-1) + eta u_t, started from the stationary law."""
    sd = eta / np.sqrt(1 - phi * phi)
    h = np.empty((n, n_paths))
    h[0] = sd * rng.standard_normal(n_paths)
    u = eta * rng.standard_normal((n, n_paths))
    for t in range(1, n):
        h[t] = phi * h[t - 1] + u[t]
    return h


def t_shocks(z: np.ndarray, dof: float, rng) -> np.ndarray:
    """Unit-variance Student-t from standard normals z (own chi-square per element)."""
    w = rng.chisquare(dof, z.shape) / dof
    return z / np.sqrt(w) * np.sqrt((dof - 2) / dof)


def logsv_pairs(n_pairs: int, n: int, p: dict, c: float, rho: float, rng) -> tuple:
    """Two (n, n_pairs) LOG-PRICE panels, no cointegration: r_i = sigma_i,t * eps_i,t, log sigma_i = scale + h_i with
    h_i = c f + sqrt(1 - c^2) g_i (f, g_i independent AR(1)s with the same phi, eta: each leg's marginal law is the
    fitted one), eps correlated rho before the t transform. Mean daily variance = THETA."""
    f = logvol_paths(n_pairs, n, p["phi"], p["eta"], rng)
    ga, gb = logvol_paths(n_pairs, n, p["phi"], p["eta"], rng), logvol_paths(n_pairs, n, p["phi"], p["eta"], rng)
    w = np.sqrt(1 - c * c)
    ha, hb = c * f + w * ga, c * f + w * gb
    sd = p["eta"] / np.sqrt(1 - p["phi"] ** 2)
    scale = np.sqrt(THETA) * np.exp(-sd * sd)              # E[exp(2h)] = exp(2 sd^2) -> mean variance THETA
    z1 = rng.standard_normal((n, n_pairs))
    z2 = rho * z1 + np.sqrt(1 - rho * rho) * rng.standard_normal((n, n_pairs))
    ra = scale * np.exp(ha) * t_shocks(z1, p["dof"], rng)
    rb = scale * np.exp(hb) * t_shocks(z2, p["dof"], rng)
    return np.cumsum(ra, axis=0), np.cumsum(rb, axis=0)


def grid_moments2(rng, n_paths: int = 30, n: int = 4000) -> pd.DataFrame:
    rows = []
    for phi in PHIS:
        for eta in ETAS:
            for dof in DOFS:
                A, _ = logsv_pairs(n_paths, n, {"phi": phi, "eta": eta, "dof": dof}, 0.0, 0.0, rng)
                m = np.array([moments2(np.diff(A[:, j])) for j in range(n_paths)])
                rows.append({"phi": phi, "eta": eta, "dof": dof, "acf_s": float(np.nanmedian(m[:, 0])),
                             "acf_l": float(np.nanmedian(m[:, 1])), "kurt": float(np.nanmedian(m[:, 2]))})
    return pd.DataFrame(rows)


def fit2(G: pd.DataFrame, target: tuple) -> dict:
    """Nearest grid point: relative squared distance, short and long ACF weighted 2, kurtosis 1."""
    s, l, k = target
    d = (2 * ((G.acf_s - s) / max(abs(s), 1e-3)) ** 2 + 2 * ((G.acf_l - l) / max(abs(l), 1e-2)) ** 2
         + ((G.kurt - k) / max(abs(k), 1.0)) ** 2)
    r = G.loc[d.idxmin()]
    return {"phi": float(r.phi), "eta": float(r.eta), "dof": float(r.dof), "fit_acf_s": float(r.acf_s),
            "fit_acf_l": float(r.acf_l), "fit_kurt": float(r.kurt), "fit_dist": float(d.min()),
            "on_grid_edge": bool(r.phi in (PHIS[0], PHIS[-1]) or r.eta in (ETAS[0], ETAS[-1]) or r.dof in (DOFS[0], DOFS[-1]))}


def pair_corrs(A: np.ndarray, B: np.ndarray) -> tuple:
    """Median over pairs of corr(r_a, r_b) and corr(|r_a - mean|, |r_b - mean|)."""
    ra, rb = np.diff(A, axis=0), np.diff(B, axis=0)
    c_r = [np.corrcoef(ra[:, j], rb[:, j])[0, 1] for j in range(ra.shape[1])]
    c_a = [np.corrcoef(np.abs(ra[:, j] - ra[:, j].mean()), np.abs(rb[:, j] - rb[:, j].mean()))[0, 1] for j in range(ra.shape[1])]
    return float(np.median(c_r)), float(np.median(c_a))


def fit_pair_dependence(p: dict, target: tuple, rng) -> dict:
    """(c, rho) on a grid so the simulated median (corr r, corr |r|) matches the real candidate pairs'."""
    best = None
    for c in LOADINGS:
        for rho in RHOS:
            A, B = logsv_pairs(60, DISC_BARS, p, c, rho, rng)
            cr, ca = pair_corrs(A, B)
            d = ((cr - target[0]) / target[0]) ** 2 + ((ca - target[1]) / max(target[1], 0.02)) ** 2
            if best is None or d < best["dep_dist"]:
                best = {"c": c, "rho": rho, "sim_corr_r": cr, "sim_corr_abs": ca, "dep_dist": float(d)}
    return best


def real_targets2(src: str, n: int = N_SERIES, seed: int = 20261113) -> pd.DataFrame:
    import parquet_io
    from data_wrds import label_permno_map
    from placebo_discovery_e1 import _log_price
    labs = sorted(l for l in label_permno_map() if os.path.exists(os.path.join(src, f"{l}_1D.parquet")))
    np.random.default_rng(seed).shuffle(labs)
    rows = []
    for l in labs:
        r = _log_price(parquet_io.read_parquet(os.path.join(src, f"{l}_1D.parquet"))).diff().dropna().to_numpy()
        if len(r) >= MIN_RETURNS:
            s, lg, k = moments2(r)
            rows.append({"label": l, "n": len(r), "acf_s": s, "acf_l": lg, "kurt": k})
        if len(rows) >= n:
            break
    T = pd.DataFrame(rows)
    T["decile"] = pd.qcut(T["acf_s"].rank(method="first"), 10, labels=False)
    return T


def real_pair_targets(src: str, research: str, n: int = 500, seed: int = 20261115) -> pd.DataFrame:
    """US-gated candidate pairs (real Tier-3 windows): per sampled window, corr of returns and of |r| over the window's
    2,520 common bars ending at window_end_date. Pair moments only -- the window's p-value is not read."""
    import parquet_io
    from placebo_discovery_e1 import _log_price, _windows_by_arm
    W = _windows_by_arm(os.path.join(research, "wrds_deep_history_episodic_scan_tier3_windows.parquet"),
                        cols=("symbol_a", "symbol_b", "window_end_date"))
    W = W[W.arm == "us_us_gated"].sample(n=n, random_state=seed)
    cache, rows = {}, []
    for r in W.itertuples():
        for s in (r.symbol_a, r.symbol_b):
            if s not in cache:
                cache[s] = _log_price(parquet_io.read_parquet(os.path.join(src, f"{s}_1D.parquet")))
        j = pd.concat([cache[r.symbol_a], cache[r.symbol_b]], axis=1, join="inner").dropna()
        j = j[j.index <= r.window_end_date].tail(DISC_BARS + 1).diff().dropna()
        if len(j) < DISC_BARS // 2:
            continue
        a, b = j.iloc[:, 0].to_numpy(), j.iloc[:, 1].to_numpy()
        rows.append({"corr_r": float(np.corrcoef(a, b)[0, 1]),
                     "corr_abs": float(np.corrcoef(np.abs(a - a.mean()), np.abs(b - b.mean()))[0, 1])})
    return pd.DataFrame(rows)


def run_cell_panels(A: np.ndarray, B: np.ndarray, workers: int, p2_pairs: int) -> dict:
    n_pairs = A.shape[1]
    with ProcessPoolExecutor(workers, initializer=_init_worker) as ex:
        eg = np.array([p for pr in ex.map(_eg_both, [(A[:, j], B[:, j]) for j in range(n_pairs)], chunksize=64)
                       for p in pr])
        p2 = np.array([p for pr in ex.map(_p2_years, [(A[:, j], B[:, j]) for j in range(min(p2_pairs, n_pairs))],
                                         chunksize=16) for p in pr])
    eg = eg[np.isfinite(eg)]
    p2 = p2.reshape(-1, 2)
    row = {"eg_tests": len(eg), "p2_tests": len(p2)}
    for t in (0.05, 1e-3, 1e-4, 2e-5):
        row[f"eg_p<{t:g}"] = float((eg < t).mean())
        row[f"eg_n<{t:g}"] = int((eg < t).sum())
    for j, nm in enumerate(("aic", "schwert")):
        row[f"p2_{nm}_p<0.05"] = float((p2[:, j] < 0.05).mean()) if len(p2) else np.nan
    return row


def main_a2(a):
    rng = np.random.default_rng(20261115)
    T = real_targets2(a.src)
    tg = T.groupby("decile")[["acf_s", "acf_l", "kurt"]].median()
    print(f"{len(T)} real US series; targets:\n{tg.round(4).to_string()}", flush=True)
    T.to_parquet(os.path.join(OUT, "stochvol_a2_targets.parquet"))
    PT = real_pair_targets(a.src, OUT)
    ptg = (float(PT.corr_r.median()), float(PT.corr_abs.median()))
    print(f"real US candidate pairs ({len(PT)} windows): median corr r {ptg[0]:.3f}, corr |r| {ptg[1]:.3f}", flush=True)
    G = grid_moments2(rng)
    G.to_parquet(os.path.join(OUT, "stochvol_a2_grid.parquet"))
    out_path = os.path.join(OUT, "stochvol_null_rates_a2.parquet")
    rows = []
    for d in a.deciles:
        p = fit2(G, tuple(tg.loc[d]))
        dep = fit_pair_dependence(p, ptg, rng)
        zero = float((np.diff(logsv_pairs(10, 3000, p, 0.0, 0.0, rng)[0], axis=0) == 0).mean())
        for arm, c in (("shared_vol", dep["c"]), ("independent_vol", 0.0)):
            crng = np.random.default_rng(100 * d + (0 if c else 1))
            acc, p2_left = {}, a.p2_pairs
            for _ in range(int(np.ceil(a.pairs / CHUNK))):          # chunks: memory ~ 9 panels x 2,520 x CHUNK floats
                A, B = logsv_pairs(CHUNK, DISC_BARS, p, c, dep["rho"], crng)
                part = run_cell_panels(A, B, a.workers, p2_left)
                p2_left = max(0, p2_left - CHUNK)
                del A, B
                for k, v in part.items():
                    if k.startswith(("eg_n", "eg_tests", "p2_tests")):
                        acc[k] = acc.get(k, 0) + v
                    elif k.startswith("p2_") and part["p2_tests"]:
                        acc[k + "_sum"] = acc.get(k + "_sum", 0.0) + v * part["p2_tests"]
            r = {"eg_tests": acc["eg_tests"], "p2_tests": acc["p2_tests"]}
            for t in (0.05, 1e-3, 1e-4, 2e-5):
                r[f"eg_n<{t:g}"] = acc[f"eg_n<{t:g}"]
                r[f"eg_p<{t:g}"] = acc[f"eg_n<{t:g}"] / acc["eg_tests"]
            for nm in ("aic", "schwert"):
                r[f"p2_{nm}_p<0.05"] = acc.get(f"p2_{nm}_p<0.05_sum", np.nan) / max(acc["p2_tests"], 1)
            rows.append({"decile": d, "arm": arm, "c": c, **{k: v for k, v in dep.items() if k != "c"},
                         **{f"target_{k}": v for k, v in tg.loc[d].items()}, **p, "zero_return_share": zero, **r})
            print(rows[-1], flush=True)
            pd.DataFrame(rows).to_parquet(out_path)
    D = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(D[["decile", "arm", "phi", "eta", "dof", "on_grid_edge", "fit_dist", "c", "rho", "eg_p<0.05", "eg_p<0.0001",
             "eg_p<2e-05", "eg_n<2e-05", "p2_aic_p<0.05"]].round(5).to_string(index=False))
    for arm, g in D.groupby("arm"):
        n = g["eg_tests"].sum()
        print(arm, {t: round(float(g[f"eg_n<{t:g}"].sum()) / n / t, 2) for t in (1e-3, 1e-4, 2e-5)}, "x nominal (pooled)")


def main():
    from config import Config
    assert Config.ANALYSIS.EG_MAX_LAG == EG_MAX_LAG, "discovery EG max lag changed -- update EG_MAX_LAG"
    ap = argparse.ArgumentParser()
    ap.add_argument("--a2", action="store_true", help="A2: log-vol AR(1)-t with a shared vol factor (2026-11-15)")
    ap.add_argument("--src", default=os.path.join(ROOT, "output", "cache", "wrds"))
    ap.add_argument("--pairs", type=int, default=10000, help="pairs per decile x generator x corr (2 EG rows each)")
    ap.add_argument("--p2-pairs", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 4),
                    help="default a quarter of the cores: runs beside E1 at low priority")
    ap.add_argument("--deciles", type=int, nargs="*", default=list(range(10)))
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if a.a2:
        return main_a2(a)
    T = real_targets(a.src)
    tg = T.groupby("decile")[["acf", "kurt"]].median()
    print(f"{len(T)} real US series; per-decile targets:\n{tg.round(3).to_string()}", flush=True)
    T.to_parquet(os.path.join(OUT, "stochvol_null_targets.parquet"))
    rng = np.random.default_rng(1113)
    rows = []
    out_path = os.path.join(OUT, "stochvol_null_rates.parquet")
    base = run_cell(generator("iid", {}), a.pairs, 0.0, 7, a.workers, a.p2_pairs)
    rows.append({"generator": "iid", "decile": -1, "corr": 0.0, **base})
    print("iid control:", base, flush=True)
    for d in a.deciles:
        for kind in ("heston", "sabr"):
            p = fit(kind, tuple(tg.loc[d]), rng)
            for corr in (0.0, 0.6):
                r = run_cell(generator(kind, p), a.pairs, corr, 1000 * d + (0 if kind == "heston" else 500) + int(corr * 10),
                             a.workers, a.p2_pairs)
                rows.append({"generator": kind, "decile": d, "corr": corr, "target_acf": tg.loc[d, "acf"],
                             "target_kurt": tg.loc[d, "kurt"], **{f"fit_{k}": v for k, v in p.items()}, **r})
                print(rows[-1], flush=True)
                pd.DataFrame(rows).to_parquet(out_path)
    D = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    cols = ["generator", "decile", "corr", "target_acf", "fit_acf", "target_kurt", "fit_kurt", "eg_p<0.05", "eg_p<0.001",
            "eg_p<0.0001", "p2_aic_p<0.05", "p2_schwert_p<0.05"]
    print(D[[c for c in cols if c in D.columns]].round(5).to_string(index=False))


if __name__ == "__main__":
    main()
