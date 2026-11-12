"""
research/spread_arma.py -- ARMA(p, q) half-life, a comparison arm for analysis.SpreadModel.half_life_ar1
(Ross 2026-11-11: "add tests for ... ma/ar").

Why: if a spread is a mean-reverting AR(1) observed with independent noise (bid-ask bounce, non-synchronous closes
across exchanges), the observed series is ARMA(1, 1). An AR(1) fit absorbs the noise into phi, pulling it toward 0,
so the AR(1) half-life reads SHORT. The ARMA fit separates the two: the AR root carries the reversion speed.

Half-life convention (same as half_life_ar1): -ln 2 / ln(m), m = modulus of the dominant inverse AR root, valid when the
dominant root is real and in (0, 1). A complex dominant root (oscillating spread) is reported with `oscillating=True`
and the envelope half-life; a negative real dominant root gives NaN (sign-flipping, as phi <= 0 does in AR(1)).
`half_life_irf` (first bar the impulse response falls to 0.5, log-interpolated) is reported as descriptive only.

Order selection: BIC over p in 1..max_p, q in 0..max_q (p >= 1 so a reversion root always exists). Pure function of the
input window -- point-in-time when the caller passes only past bars.
Verify: debug/_verify_spread_arma.py
"""
import warnings

import numpy as np


def ar_root_half_life(ar_coefs) -> tuple:
    """(half_life, oscillating) from AR coefficients phi_1..phi_p of x_t = sum phi_i x_{t-i} + ..."""
    ar = np.asarray(ar_coefs, dtype=float)
    if ar.size == 0 or not np.all(np.isfinite(ar)):
        return np.nan, False
    # inverse roots = eigenvalues of the companion matrix
    comp = np.zeros((ar.size, ar.size))
    comp[0, :] = ar
    if ar.size > 1:
        comp[1:, :-1] = np.eye(ar.size - 1)
    lam = np.linalg.eigvals(comp)
    dom = lam[np.argmax(np.abs(lam))]
    m = float(np.abs(dom))
    oscillating = abs(dom.imag) > 1e-10
    if not (0.0 < m < 1.0):
        return np.nan, oscillating
    if not oscillating and dom.real <= 0:
        return np.nan, False
    return float(-np.log(2) / np.log(m)), oscillating


def irf_half_life(ar_coefs, ma_coefs, max_h: int = 2000) -> float:
    """First horizon where |psi_h| <= 0.5 (psi_0 = 1), interpolated linearly in log|psi|. Descriptive."""
    ar, ma = np.asarray(ar_coefs, float), np.asarray(ma_coefs, float)
    psi = np.zeros(max_h + 1)
    psi[0] = 1.0
    for h in range(1, max_h + 1):
        v = ma[h - 1] if h - 1 < ma.size else 0.0
        for i, a in enumerate(ar, start=1):
            if h - i >= 0:
                v += a * psi[h - i]
        psi[h] = v
    a = np.abs(psi)
    hit = np.nonzero(a <= 0.5)[0]
    if hit.size == 0:
        return np.nan
    h = int(hit[0])
    if a[h] <= 0:                      # crossed straight to zero: interpolate linearly in |psi|
        return float(h - 1 + (a[h - 1] - 0.5) / (a[h - 1] - a[h]))
    l0, l1 = np.log(a[h - 1]), np.log(a[h])
    return float(h - 1 + (l0 - np.log(0.5)) / (l0 - l1))


def fit_arma_bic(x, max_p: int = 2, max_q: int = 2, min_obs: int = 60) -> dict:
    """Fit ARMA(p, q) with a constant by exact Gaussian MLE (statsmodels ARIMA), choose by BIC."""
    from statsmodels.tsa.arima.model import ARIMA
    s = np.asarray(x, dtype=float)
    s = s[np.isfinite(s)]
    out = {"p": np.nan, "q": np.nan, "ar": [], "ma": [], "bic": np.nan, "half_life": np.nan,
           "oscillating": False, "half_life_irf": np.nan, "n_obs": int(s.size)}
    if s.size < min_obs:
        return out
    best = None
    for p in range(1, max_p + 1):
        for q in range(0, max_q + 1):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    r = ARIMA(s, order=(p, 0, q), trend="c").fit()
                except Exception:
                    continue
            if np.isfinite(r.bic) and (best is None or r.bic < best[0]):
                best = (r.bic, p, q, np.asarray(r.arparams), np.asarray(r.maparams))
    if best is None:
        return out
    bic, p, q, ar, ma = best
    hl, osc = ar_root_half_life(ar)
    out.update(p=p, q=q, ar=ar.tolist(), ma=ma.tolist(), bic=float(bic), half_life=hl, oscillating=osc,
               half_life_irf=irf_half_life(ar, ma))
    return out
