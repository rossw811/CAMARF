"""
research/nelson_siegel.py -- Nelson-Siegel yield-curve factors (Ross 2026-11-11: "add tests for ... nelson-siegel").

Diebold-Li (2006) form with a FIXED decay lambda (0.0609 per month: curvature loading peaks at ~30 months), so each
date's fit is ordinary least squares on that date's yields only -- point-in-time by construction, no estimation
across dates:
    y(tau) = beta1 + beta2 * (1 - e^{-lam tau}) / (lam tau) + beta3 * [(1 - e^{-lam tau}) / (lam tau) - e^{-lam tau}]
beta1 = level, beta2 = slope (short minus long, sign as in Diebold-Li: y(0) - y(inf) = beta2), beta3 = curvature.
Role in CAMARF: candidate macro regime features (level / slope / curvature) as a comparison arm to the raw T10Y2Y
spread macro.py carries today. The fixed lambda is a convention, not tuned on CAMARF outcomes.
Verify: debug/_verify_nelson_siegel.py
"""
import numpy as np
import pandas as pd

DIEBOLD_LI_LAMBDA = 0.0609          # per month
MIN_MATURITIES = 4                  # 3 parameters + at least one degree of freedom
FRED_TREASURY_MONTHS = {"DGS1MO": 1, "DGS3MO": 3, "DGS6MO": 6, "DGS1": 12, "DGS2": 24, "DGS3": 36, "DGS5": 60,
                        "DGS7": 84, "DGS10": 120, "DGS20": 240, "DGS30": 360}


def ns_loadings(tau_months, lam: float = DIEBOLD_LI_LAMBDA) -> np.ndarray:
    tau = np.asarray(tau_months, dtype=float)
    x = lam * tau
    l2 = (1 - np.exp(-x)) / x
    return np.column_stack([np.ones_like(tau), l2, l2 - np.exp(-x)])


def fit_ns(yields: pd.DataFrame, tau_months, lam: float = DIEBOLD_LI_LAMBDA) -> pd.DataFrame:
    """Row-by-row OLS. `yields` columns align with `tau_months`; NaN maturities are dropped per row; rows with fewer
    than MIN_MATURITIES yields get NaN factors. Returns level, slope, curvature, rmse, n_maturities."""
    L = ns_loadings(tau_months, lam)
    Y = yields.to_numpy(dtype=float)
    out = np.full((Y.shape[0], 5), np.nan)
    for i, y in enumerate(Y):
        ok = np.isfinite(y)
        out[i, 4] = ok.sum()
        if ok.sum() < MIN_MATURITIES:
            continue
        b, *_ = np.linalg.lstsq(L[ok], y[ok], rcond=None)
        out[i, :3] = b
        out[i, 3] = np.sqrt(np.mean((y[ok] - L[ok] @ b) ** 2))
    return pd.DataFrame(out, index=yields.index, columns=["level", "slope", "curvature", "rmse", "n_maturities"])
