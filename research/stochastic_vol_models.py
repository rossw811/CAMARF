"""
research/stochastic_vol_models.py -- Bachelier, Heston and SABR (Ross 2026-11-11: "add tests for bachelier, heston/sabr").

CAMARF has no option quotes (free-data rule), so none of these is calibrated to a market here. Their roles:
  * Bachelier (arithmetic Brownian motion): the right model for a SPREAD, which can be negative. Used as the
    no-mean-reversion baseline: the chance a driftless spread reaches a band within T (first passage), against which
    an OU (mean-reverting) exit probability is compared. Closed-form option price included for completeness/tests.
  * Heston (stochastic variance, CIR, correlated with price): a stochastic-volatility NULL generator for the
    Engle-Granger calibration (V3 compared GARCH-t; Heston adds continuous-time SV with leverage).
  * SABR: Hagan et al. (2002) lognormal implied-vol approximation and a simulator. Without option quotes its only
    valid use here is as a second SV null generator (beta controls level-dependence of volatility).
All functions are pure; simulators take an explicit numpy Generator.
Verify: debug/_verify_stochastic_vol_models.py
"""
import numpy as np
from scipy import integrate
from scipy.stats import norm


# --------------------------------------------------------------------------------------------------- Black / Bachelier
def black_price(F, K, T, sigma, df=1.0, kind="call"):
    """Black (1976) lognormal forward price."""
    s = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * s * s) / s
    call = df * (F * norm.cdf(d1) - K * norm.cdf(d1 - s))
    return call if kind == "call" else call - df * (F - K)


def bachelier_price(F, K, T, sigma, df=1.0, kind="call"):
    """Bachelier (1900) normal-model forward price; sigma in price units per sqrt(year)."""
    s = sigma * np.sqrt(T)
    if s <= 0:
        intrinsic = max(F - K, 0.0) if kind == "call" else max(K - F, 0.0)
        return df * intrinsic
    d = (F - K) / s
    call = df * ((F - K) * norm.cdf(d) + s * norm.pdf(d))
    return call if kind == "call" else call - df * (F - K)


def bachelier_hit_prob(distance, sigma, T):
    """P(driftless arithmetic BM reaches ONE level `distance` away (above or below, sign ignored) by T)
    = 2 Phi(-|b| / (sigma sqrt T)) (reflection principle). The no-mean-reversion baseline for a spread reaching its
    exit band (one level: the mean it should revert to)."""
    s = sigma * np.sqrt(T)
    return float(2.0 * norm.cdf(-abs(distance) / s)) if s > 0 else float(distance == 0)


# ------------------------------------------------------------------------------------------------------------- Heston
def heston_cf(u, S0, T, r, v0, kappa, theta, xi, rho):
    """Characteristic function of ln S_T, Albrecher et al. (2007) 'little trap' form (no branch-cut jumps)."""
    iu = 1j * u
    a = kappa - rho * xi * iu
    d = np.sqrt(a * a + xi * xi * (iu + u * u))
    g = (a - d) / (a + d)
    e = np.exp(-d * T)
    C = r * iu * T + kappa * theta / xi ** 2 * ((a - d) * T - 2.0 * np.log((1 - g * e) / (1 - g)))
    D = (a - d) / xi ** 2 * (1 - e) / (1 - g * e)
    return np.exp(C + D * v0 + iu * np.log(S0))


def heston_call(S0, K, T, r, v0, kappa, theta, xi, rho, upper=200.0):
    """European call by Gil-Pelaez inversion of the Heston characteristic function."""
    lnK = np.log(K)
    f = lambda u: heston_cf(u, S0, T, r, v0, kappa, theta, xi, rho)
    fm = f(-1j)                                            # = S0 e^{rT}
    p1 = lambda u: (np.exp(-1j * u * lnK) * f(u - 1j) / (1j * u * fm)).real
    p2 = lambda u: (np.exp(-1j * u * lnK) * f(u) / (1j * u)).real
    P1 = 0.5 + integrate.quad(p1, 1e-10, upper, limit=500)[0] / np.pi
    P2 = 0.5 + integrate.quad(p2, 1e-10, upper, limit=500)[0] / np.pi
    return float(S0 * P1 - K * np.exp(-r * T) * P2)


def simulate_heston(n_paths, n_steps, dt, S0, r, v0, kappa, theta, xi, rho, rng, return_paths=False):
    """Full-truncation Euler (Lord et al. 2010) on ln S. Returns (lnS_T, v_T) or full (n_steps+1, n_paths) paths."""
    x = np.full(n_paths, np.log(S0))
    v = np.full(n_paths, float(v0))
    if return_paths:
        X, V = [x.copy()], [v.copy()]
    c = np.sqrt(1 - rho * rho)
    for _ in range(n_steps):
        z1 = rng.standard_normal(n_paths)
        z2 = rho * z1 + c * rng.standard_normal(n_paths)
        vp = np.maximum(v, 0.0)
        x = x + (r - 0.5 * vp) * dt + np.sqrt(vp * dt) * z1
        v = v + kappa * (theta - vp) * dt + xi * np.sqrt(vp * dt) * z2
        if return_paths:
            X.append(x.copy()); V.append(np.maximum(v, 0.0))
    if return_paths:
        return np.array(X), np.array(V)
    return x, np.maximum(v, 0.0)


def feller_ok(kappa, theta, xi):
    """2 kappa theta >= xi^2: variance stays strictly positive."""
    return 2 * kappa * theta >= xi * xi


# --------------------------------------------------------------------------------------------------------------- SABR
def sabr_vol(F, K, T, alpha, beta, rho, nu):
    """Hagan et al. (2002) lognormal (Black) implied volatility, eq. (2.17a); ATM limit (2.18) when K == F."""
    one_b = 1.0 - beta
    fk = F * K
    logfk = np.log(F / K)
    corr = 1.0 + (one_b ** 2 / 24 * alpha ** 2 / fk ** one_b
                  + rho * beta * nu * alpha / (4 * fk ** (one_b / 2))
                  + (2 - 3 * rho ** 2) / 24 * nu ** 2) * T
    denom = fk ** (one_b / 2) * (1 + one_b ** 2 / 24 * logfk ** 2 + one_b ** 4 / 1920 * logfk ** 4)
    z = nu / alpha * fk ** (one_b / 2) * logfk
    return float(alpha / denom * z_over_x(z, rho) * corr)


ZX_SERIES_BELOW = 1e-6


def z_over_x(z: float, rho: float) -> float:
    """z / x(z), x(z) = ln[(sqrt(1 - 2 rho z + z^2) + z - rho) / (1 - rho)]; series 1 - rho z / 2 near 0 (the closed
    form loses precision there)."""
    if abs(z) < ZX_SERIES_BELOW:
        return 1.0 - 0.5 * rho * z
    return z / np.log((np.sqrt(1 - 2 * rho * z + z * z) + z - rho) / (1 - rho))


def simulate_sabr(n_paths, n_steps, dt, F0, alpha, beta, rho, nu, rng, return_paths=False):
    """Euler on F (absorbed at 0), exact lognormal step on alpha. Returns F_T or full (n_steps+1, n_paths) paths."""
    F = np.full(n_paths, float(F0))
    a = np.full(n_paths, float(alpha))
    if return_paths:
        P = [F.copy()]
    c = np.sqrt(1 - rho * rho)
    for _ in range(n_steps):
        z1 = rng.standard_normal(n_paths)
        z2 = rho * z1 + c * rng.standard_normal(n_paths)
        F = np.maximum(F + a * np.power(np.maximum(F, 0.0), beta) * np.sqrt(dt) * z1, 0.0)
        a = a * np.exp(nu * np.sqrt(dt) * z2 - 0.5 * nu * nu * dt)
        if return_paths:
            P.append(F.copy())
    return np.array(P) if return_paths else F
