"""
research/residual_correlation_factor_test.py -- does the crisis-regime
persistence effect (Finding #41/#44, PAPER_MAGNITUDE.md §5) survive once
market-wide factor co-movement is regressed out of the correlation
prefilter, or is it explained away once idiosyncratic (residual)
correlation is used instead of raw Pearson?

Motivation: §5 names crisis-era factor co-movement (Forbes & Rigobon,
2002; Longin & Solnik, 2001) as a named, untested confound -- crisis
periods are exactly when idiosyncratic correlation structure collapses
toward a single dominant systemic-risk factor, which alone could explain
both the correlation-prefilter surge motivating §5 and the downstream
persistence pattern, independent of any genuine pairwise relationship.
The same-sector/cross-sector test (Finding #44) found a pattern CONSISTENT
with this confound (real effect in cross-sector pairs, none in same-
sector) but that's a coarse proxy -- this test is the direct one.

Scope, stated explicitly (a deliberately CHEAPER design than re-running
Tier 3's full rolling-window discovery pipeline on residualized data,
which would cost the same multi-hour-plus, multi-crash-restart-prone
budget the original Tier 3 run needed): rather than re-deriving the
candidate pool and re-running the expensive rolling-window EG discovery
from scratch, this REUSES the already-discovered candidate pairs
(crisis_regime_correlation_diagnostic_pairs.parquet, 638,095 pairs,
already regime-tagged and already has real persistence-test machinery)
and asks a narrower, still-decisive question: of THOSE pairs, which ones
would ALSO have cleared a residual (factor-adjusted) correlation
threshold, vs. which were only correlated because of a shared market
factor? The market factor is regressed out ONCE, over each symbol's full
available history (a full-history regression, not causal/rolling -- a
disclosed choice, defensible for a structural CONFOUND CHECK rather than
a live trading signal, where causality would matter). Then the SAME
persistence test (crisis-vs-calm reappearance rate) is re-run separately
on the "survives residual correlation" and "explained by factor alone"
subsets.

Market factor: SPY daily close (WRDS-primary per this project's standing
priority, `output/cache/wrds/SPY_1D.parquet`), log returns.

Verified against synthetic ground truth first:
debug/_verify_residual_correlation_factor_test.py.

Usage:
    python research/residual_correlation_factor_test.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAIRS_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_correlation_diagnostic_pairs.parquet")
_SPY_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "SPY_1D.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "residual_correlation_factor_test.parquet")

log = logging.getLogger("residual_correlation_factor_test")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)


def safe_log_returns(close: pd.Series) -> pd.Series:
    """Log returns from a close-price series, masking non-positive prices
    to NaN BEFORE taking the log -- guards against a genuine non-positive
    price (bad tick, placeholder row, corrupted history) silently becoming
    -inf and propagating into a downstream regression/correlation,
    matching this project's own standing GapFlag discipline of masking a
    known-bad value to NaN rather than smoothing over it.

    Real, live investigation (2026-09-03): the naive version of this
    function hit "divide by zero encountered in log" 2,092 times across
    the real full universe. Traced directly, not assumed: checked whether
    real symbols actually carry close<=0 prices (they do not -- 0 found
    across a 5,000-symbol sample) and found the true cause is a pandas
    quirk, not a data-quality issue -- WRDS's `close` column loads as the
    nullable `Float64` extension dtype (capital F), and pandas' masked-
    array ufunc dispatch computes `log()` over the RAW underlying buffer
    (including NA positions, which are internally 0.0 placeholders) before
    applying the NA mask to the result -- producing a real, if ultimately
    discarded, divide-by-zero at the raw-buffer level for every masked
    row. The final NaN-masked VALUES were already correct even before this
    fix (confirmed: no -inf ever leaked into a `dropna()`'d result), but
    relying on that as a permanent guarantee of pandas' internal nullable-
    dtype behavior is fragile. Converting to a plain numpy float64 array
    up front (where NaN truly is NaN, not a masked sentinel over a live
    buffer) sidesteps the whole class of issue rather than depending on
    it resolving correctly by accident.

    A masked bar's return AND the following bar's return (which would
    diff against a NaN) both correctly become NaN, not a fabricated
    number -- `.dropna()` downstream removes both, same as any other real
    data gap this project's pipeline already handles this way."""
    plain_close = close.astype("float64")  # drops the nullable-Float64 wrapper; NaN stays NaN
    safe_close = plain_close.where(plain_close > 0)
    return np.log(safe_close).diff().dropna()


def compute_residual_returns(returns: pd.Series, factor_returns: pd.Series) -> pd.Series:
    """OLS-regresses `returns` on `factor_returns` (full-history, aligned
    on shared dates) and returns the residual (idiosyncratic) return
    series -- the part of a symbol's return NOT explained by the market
    factor. Returns an empty Series if fewer than 60 overlapping
    observations exist (not enough to estimate a stable beta)."""
    aligned = pd.DataFrame({"y": returns, "x": factor_returns}).dropna()
    if len(aligned) < 60:
        return pd.Series(dtype=float)
    beta, alpha = np.polyfit(aligned["x"], aligned["y"], deg=1)
    residual = aligned["y"] - (alpha + beta * aligned["x"])
    return residual


def residual_correlation_from_precomputed(resid_a: pd.Series, resid_b: pd.Series) -> float:
    """Correlation between two ALREADY-RESIDUALIZED return series. Split
    from the regression step deliberately: a symbol appears in many pairs
    (638,095 pairs, far fewer unique symbols -- every candidate pair
    sharing a symbol would otherwise redundantly re-run the SAME OLS
    regression against the market factor once per pair it's part of).
    Precomputing each symbol's residual series ONCE (main()) and reusing
    it across every pair avoids that redundant work entirely."""
    aligned = pd.DataFrame({"a": resid_a, "b": resid_b}).dropna()
    if len(aligned) < 60:
        return np.nan
    return float(aligned["a"].corr(aligned["b"]))


def two_proportion_z_test(x1: int, n1: int, x2: int, n2: int) -> dict:
    """Standard two-proportion z-test, the same formula used throughout
    this project's discovery-event work (crisis_regime_correlation_
    diagnostic.py), reused here rather than reimplemented differently."""
    if n1 == 0 or n2 == 0:
        return {"z_stat": None, "p_value": None}
    p_pool = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if p_pool not in (0, 1) else np.nan
    z = (x1 / n1 - x2 / n2) / se if se and np.isfinite(se) and se > 0 else np.nan
    p = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else np.nan
    return {"z_stat": float(z) if np.isfinite(z) else None, "p_value": float(p) if np.isfinite(p) else None}


def main():
    _setup_logging()
    log.info("=== residual_correlation_factor_test.py: does the crisis-regime persistence "
             "effect survive once market-factor co-movement is regressed out? ===")

    if not os.path.exists(_PAIRS_PATH):
        log.error(f"{_PAIRS_PATH} does not exist -- run crisis_regime_correlation_diagnostic.py first.")
        sys.exit(1)
    if not os.path.exists(_SPY_PATH):
        log.error(f"{_SPY_PATH} does not exist -- SPY daily data required as the market factor.")
        sys.exit(1)

    pairs = pd.read_parquet(_PAIRS_PATH)
    spy = pd.read_parquet(_SPY_PATH)
    spy_returns = safe_log_returns(spy["close"])
    log.info(f"Loaded {len(pairs)} candidate pairs, SPY factor series "
             f"({len(spy_returns)} daily returns, {spy_returns.index.min().date()} to "
             f"{spy_returns.index.max().date()}).")

    unique_symbols = pd.unique(pairs[["symbol_a", "symbol_b"]].values.ravel())
    log.info(f"{len(unique_symbols)} unique symbols across all candidate pairs -- loading "
             f"each once, not once per pair.")

    returns_by_symbol = {}
    n_loaded, n_failed = 0, 0
    for sym in unique_symbols:
        path = os.path.join(_ROOT, "output", "cache", "wrds", f"{sym}_1D.parquet")
        if not os.path.exists(path):
            n_failed += 1
            continue
        try:
            df = pd.read_parquet(path)
            returns_by_symbol[sym] = safe_log_returns(df["close"])
            n_loaded += 1
        except Exception:
            n_failed += 1
    log.info(f"Loaded return series for {n_loaded} symbols ({n_failed} missing/unreadable).")

    log.info(f"Regressing each of {len(returns_by_symbol)} UNIQUE symbols against the market "
             f"factor ONCE (not once per pair -- a symbol appears in many candidate pairs; "
             f"638,095 pairs share far fewer unique symbols, so precomputing avoids redundant "
             f"OLS work per pair it's part of)...")
    residual_by_symbol = {
        sym: compute_residual_returns(ret, spy_returns) for sym, ret in returns_by_symbol.items()
    }
    log.info(f"Residualized {sum(1 for r in residual_by_symbol.values() if len(r) > 0)} symbols "
             f"successfully (rest had <60 overlapping observations with the factor).")

    log.info("Computing residual correlation for each candidate pair (cheap now -- a plain "
             "correlation between two already-residualized series, no per-pair regression)...")
    residual_survives = []
    for i, row in enumerate(pairs.itertuples(index=False)):
        sym_a, sym_b = row.symbol_a, row.symbol_b
        if sym_a not in residual_by_symbol or sym_b not in residual_by_symbol:
            residual_survives.append(np.nan)
            continue
        rc = residual_correlation_from_precomputed(residual_by_symbol[sym_a], residual_by_symbol[sym_b])
        residual_survives.append(rc)
        if (i + 1) % 50_000 == 0:
            log.info(f"  {i+1}/{len(pairs)} pairs processed...")

    pairs = pairs.copy()
    pairs["residual_correlation"] = residual_survives
    from config import Config
    threshold = Config.UNIVERSE.MIN_PEARSON_CORR
    pairs["survives_residual_corr"] = pairs["residual_correlation"].abs() >= threshold
    n_valid = pairs["residual_correlation"].notna().sum()
    n_survives = pairs["survives_residual_corr"].sum()
    log.info(f"{n_valid} of {len(pairs)} pairs had computable residual correlation "
             f"(rest missing return data); of those, {n_survives} ({n_survives/max(n_valid,1):.1%}) "
             f"still clear the |correlation| >= {threshold} threshold after factor-adjustment.")

    results = {}
    for label, subset_mask in [
        ("survives_residual_corr", pairs["survives_residual_corr"] == True),
        ("factor_explained_only", (pairs["survives_residual_corr"] == False) & pairs["residual_correlation"].notna()),
    ]:
        subset = pairs[subset_mask]
        crisis = subset[subset["first_regime"] == "crisis"]
        calm = subset[subset["first_regime"] == "calm"]
        if len(crisis) < 5 or len(calm) < 5:
            results[label] = {"n_crisis": len(crisis), "n_calm": len(calm), "insufficient_n": True}
            continue
        test = two_proportion_z_test(
            int(crisis["reappears_in_different_regime"].sum()), len(crisis),
            int(calm["reappears_in_different_regime"].sum()), len(calm),
        )
        results[label] = {
            "n_crisis": len(crisis), "n_calm": len(calm),
            "crisis_reappear_rate": crisis["reappears_in_different_regime"].mean(),
            "calm_reappear_rate": calm["reappears_in_different_regime"].mean(),
            **test, "insufficient_n": False,
        }
        log.info(f"[{label}] n_crisis={len(crisis)}, n_calm={len(calm)}, "
                 f"crisis_reappear={results[label]['crisis_reappear_rate']:.2%}, "
                 f"calm_reappear={results[label]['calm_reappear_rate']:.2%}, "
                 f"z={test['z_stat']}, p={test['p_value']}")

    pairs.to_parquet(_OUT_PATH, index=False)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("residual_correlation_factor_test.py complete")


if __name__ == "__main__":
    main()
