"""
Synthetic verification for research/rough_volatility.py, before trusting it
on real pair data. Reuses the SAME AR(1)-direction-check convention already
established by debug/_verify_wavelet_hurst.py (this project's precedent for
verifying Hurst-estimator behavior without needing a full fBm generator) --
the estimators themselves (HurstEstimator.hurst_rs/hurst_dfa, wavelet_hurst)
are already independently verified elsewhere; what's new and needs checking
here is realized_vol_series() + the log-RV composition.

Construction: simulate returns r_t = sigma_t * z_t where log(sigma_t)
follows an AR(1) process with coefficient phi. A ROUGH (strongly mean-
reverting, low phi) vol process should give realized_vol_series() output
with LOW Hurst; a SMOOTH/PERSISTENT (phi near 1) vol process should give
Hurst nearer 0.5 -- checks direction, matching this project's existing
convention for validating estimator behavior.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from rough_volatility import realized_vol_series, vol_roughness


def _simulate_returns_with_ar1_vol(n, phi, seed):
    rng = np.random.default_rng(seed)
    log_sigma = np.zeros(n)
    for t in range(1, n):
        log_sigma[t] = phi * log_sigma[t - 1] + rng.normal(0, 0.3)
    sigma = np.exp(log_sigma - log_sigma.mean())  # center so sigma stays O(1)
    z = rng.normal(0, 1, n)
    return sigma * z


def test_rough_vol_gives_low_hurst():
    r = _simulate_returns_with_ar1_vol(6000, phi=0.3, seed=0)  # strongly mean-reverting vol
    log_rv = realized_vol_series(r, window=30)
    result = vol_roughness(log_rv)
    print(f"rough vol (phi=0.3): H_rs={result['h_rs']:.3f} H_dfa={result['h_dfa']:.3f} "
          f"H_wavelet={result['h_wavelet']:.3f} (expect well below 0.5)")
    assert result["h_rs"] < 0.45, f"expected low H_rs for rough vol, got {result['h_rs']}"
    assert result["h_dfa"] < 0.45, f"expected low H_dfa for rough vol, got {result['h_dfa']}"


def test_persistent_vol_gives_higher_hurst_than_rough():
    r_rough = _simulate_returns_with_ar1_vol(6000, phi=0.2, seed=1)
    r_persistent = _simulate_returns_with_ar1_vol(6000, phi=0.95, seed=1)
    h_rough = vol_roughness(realized_vol_series(r_rough, window=30))["h_rs"]
    h_persistent = vol_roughness(realized_vol_series(r_persistent, window=30))["h_rs"]
    print(f"H_rs rough(phi=0.2)={h_rough:.3f} vs persistent(phi=0.95)={h_persistent:.3f} "
          f"(expect persistent strictly higher)")
    assert h_persistent > h_rough, "more persistent vol process should give a higher Hurst than a rougher one"


def test_insufficient_data_returns_nan_not_crash():
    result = vol_roughness(np.array([np.nan] * 50))
    print(f"insufficient-data case: {result}")
    assert np.isnan(result["h_rs"]) and np.isnan(result["h_dfa"]) and np.isnan(result["h_wavelet"])


if __name__ == "__main__":
    test_rough_vol_gives_low_hurst()
    test_persistent_vol_gives_higher_hurst_than_rough()
    test_insufficient_data_returns_nan_not_crash()
    print("\nAll rough_volatility.py synthetic checks passed.")
