"""
CAMARF trend_dominance_diagnostic.py -- exploratory diagnostic, NOT part of the
production pipeline (candidate for promotion into analysis.py's CointScanner
pre-filter stage; not wired in yet, pending Ross's review of these results).

Root-causes and remedies the DD-hub concentration finding (Development.md,
2026-07-13): DD is one leg in 259/353 (73.4%) of the entire 1h candidate pool,
not just the 5 already-confirmed pairs PAPER.md Section 7.2 documents. DD's
correlation against these partners is unremarkable (median 0.457, matching the
non-DD population's 0.455) but its EG p-values are four orders of magnitude
more extreme (median 2.89e-9 vs 6.65e-5) -- the classic spurious-regression
signature (Granger & Newbold 1974): DD's own price rose ~4.3x over the cached
window, and a strong, low-noise, sustained trend in one leg makes almost any
partner with its own positive drift show a spuriously "significant" EG
residual, without a genuine equilibrium relationship underneath.

This is a real, direct instance of the mechanism eg_null_calibration_montecarlo.py
already demonstrated in aggregate (randomly-paired real symbols show elevated
false-positive EG rates from shared market drift) -- this module operationalizes
that finding into a per-symbol diagnostic and a concrete remedy.

Two-stage design (mirrors CAMARF's own existing cheap-prefilter -> expensive-
confirmatory-test architecture: Pearson corr -> EG):

  Stage 1 (cheap, universe-wide): trend_r_squared() -- fit a log-linear trend to
  each symbol's own price series, measure the fraction of variance it explains.
  A high R^2 with a strong, consistent slope indicates a dominant, low-noise
  trend -- the spurious-regression precondition. This is a single OLS fit per
  symbol, cheap enough to run on the whole universe.

  Stage 2 (expensive, only on Stage-1-flagged symbols): spurious_regression_risk_score()
  -- directly measure the mechanism by pairing the flagged symbol against many
  genuinely-random OTHER symbols (same exact production EG call as
  eg_null_calibration_montecarlo.py reuses) and reporting the empirical rate
  of spuriously "significant" (p<0.05) results. This is the ground-truth risk
  measure Stage 1's R^2 only proxies for -- confirms an R^2 flag actually
  translates to elevated spurious-cointegration risk before trusting it.

  Remedy: leg_corrected_pvalue() -- for a real candidate pair involving a
  Stage-2-confirmed high-risk leg, replace the raw asymptotic EG p-value with
  an empirical p-value computed against that SPECIFIC leg's own random-partner
  null distribution (a trend-preserving bootstrap null, per Ross's directive)
  rather than the generic asymptotic critical value already known (via the
  Monte Carlo study) to be too liberal for high-drift symbols. This is chosen
  over outright exclusion because it does not discard genuinely tradable pairs
  involving an otherwise-legitimate symbol that happens to have trended --
  a pair only survives if it clears a bar calibrated to that specific leg's
  own elevated baseline risk, not a blanket ban.

HONEST LIMITATION, found during verification, not glossed over (see
debug/_verify_trend_dominance_diagnostic.py): Stage 1 (trend R^2) does NOT
reliably predict Stage-2 spurious-regression risk among ORDINARY real
stocks. WMT (R^2=0.9445) vs. PG (R^2=0.0656), tested at n=150 real random
partners each, gave risk rates of 6.67% and 9.33% respectively -- the WRONG
direction, both close to the ~5-13% ordinary-stock baseline
eg_null_calibration_montecarlo.py already established. DD's own extreme
rate (68% at n=150, vs. ~5-10% for ordinary stocks) is therefore NOT
explained by "high trend R^2" as a general, transferable screening
heuristic -- DD is evidently an outlier for some more specific or more
extreme reason than trend-R^2 alone captures, not yet identified. PRACTICAL
CONSEQUENCE: this module's two-stage design as originally conceived (cheap
R^2 pre-filter -> expensive Stage-2 confirmation) is NOT validated for
universe-wide use as intended -- Stage 1 cannot be trusted to correctly
triage which symbols need Stage 2 checked. Stage 2 (direct measurement) is
independently validated and reliable (confirms DD's already-known anomaly
unambiguously), but is too expensive to run on the FULL candidate universe
without a working cheap pre-filter. The remedy below is applied to DD
specifically, where Stage 2 has already run; extending trend-dominance
detection to other, not-yet-known high-risk legs universe-wide is NOT yet
solved by this module and needs further work (a better Stage-1 proxy, or
accepting Stage 2's real cost applied broadly) before this is production-ready
beyond the DD case itself.

Output: output/research/trend_dominance_diagnostic.parquet
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

CACHE_DIR = "output/cache"
OUT_PATH = "output/research/trend_dominance_diagnostic.parquet"
SEED = 20260713


def eg_pvalue(a: np.ndarray, b: np.ndarray) -> float:
    """Exact production call (analysis.py _pair_coint_worker)."""
    _t, p, _c = coint(a, b, trend="c", maxlag=Config.ANALYSIS.EG_MAX_LAG, autolag="aic")
    return float(p)


def load_log_close(symbol: str, suffix: str) -> np.ndarray:
    df = pd.read_parquet(os.path.join(CACHE_DIR, f"{symbol}_{suffix}.parquet"))
    close = df["close"].astype(float).values
    close = close[np.isfinite(close) & (close > 0)]
    return np.log(close)


def symbols_for_suffix(suffix: str) -> list:
    paths = glob.glob(os.path.join(CACHE_DIR, f"*_{suffix}.parquet"))
    syms = []
    for p in paths:
        base = os.path.basename(p)
        sym = base[: -(len(suffix) + 1 + len(".parquet"))]
        syms.append(sym)
    return syms


def trend_r_squared(log_close: np.ndarray) -> dict:
    """
    Stage 1: fit log_close ~ a + b*t via OLS, report R^2 and the fitted slope.
    Operates on log-price directly (not returns) so a high R^2 captures a
    dominant, low-noise DIRECTIONAL trend -- exactly the spurious-regression
    precondition -- not merely "the series moved a lot."
    """
    n = len(log_close)
    if n < 30:
        return {"r_squared": float("nan"), "slope": float("nan"), "n": n}
    t = np.arange(n, dtype=float)
    t_c = t - t.mean()
    y_c = log_close - log_close.mean()
    b = float((t_c * y_c).sum() / (t_c * t_c).sum())
    fitted = b * t_c
    ss_res = float(((y_c - fitted) ** 2).sum())
    ss_tot = float((y_c ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"r_squared": r2, "slope": b, "n": n}


def spurious_regression_risk_score(
    symbol: str,
    suffix: str,
    all_symbols: list,
    n_partners: int,
    rng: np.random.Generator,
    cache: dict,
) -> dict:
    """
    Stage 2: pair `symbol` against n_partners genuinely-random OTHER symbols
    (destroying any true bilateral relationship by construction, same logic as
    eg_null_calibration_montecarlo.py) and report the empirical rate of
    spuriously significant (p<0.05) EG results -- and the raw test-statistic
    distribution, needed later for leg_corrected_pvalue()'s empirical p-value.
    """
    if symbol not in cache:
        try:
            cache[symbol] = load_log_close(symbol, suffix)
        except Exception:
            cache[symbol] = None
    a_full = cache[symbol]
    if a_full is None:
        return {"n_ok": 0, "n_rejected": 0, "risk_rate": float("nan"), "pvalues": []}

    others = [s for s in all_symbols if s != symbol]
    partners = rng.choice(others, size=min(n_partners, len(others)), replace=False)

    n_ok = 0
    n_rejected = 0
    pvalues = []
    for partner in partners:
        if partner not in cache:
            try:
                cache[partner] = load_log_close(partner, suffix)
            except Exception:
                cache[partner] = None
        b_full = cache[partner]
        if b_full is None:
            continue
        n = min(len(a_full), len(b_full))
        if n < 60:
            continue
        try:
            p = eg_pvalue(a_full[-n:], b_full[-n:])
        except Exception:
            continue
        n_ok += 1
        pvalues.append(p)
        if p < 0.05:
            n_rejected += 1

    rate = n_rejected / n_ok if n_ok else float("nan")
    return {"n_ok": n_ok, "n_rejected": n_rejected, "risk_rate": rate, "pvalues": pvalues}


def leg_corrected_pvalue(real_pvalue: float, leg_null_pvalues: list) -> float:
    """
    The remedy. Empirical p-value for a real candidate pair involving a
    high-risk leg: the fraction of that leg's OWN random-partner null p-values
    that are AT LEAST AS EXTREME (<=) as the real pair's p-value. This
    re-calibrates significance against the leg's actual, elevated baseline
    false-positive rate instead of the generic asymptotic EG critical value.

    If the leg's null distribution is itself uniform(0,1)-like (low risk),
    this returns approximately the same value as the raw p-value (no-op).
    If the leg's null distribution is skewed toward small p-values (high risk,
    like DD), this correctly inflates the corrected p-value, making it harder
    for a pair involving that leg to look spuriously significant.
    """
    if not leg_null_pvalues:
        return real_pvalue
    arr = np.asarray(leg_null_pvalues)
    return float(np.mean(arr <= real_pvalue))


def main():
    rng = np.random.default_rng(SEED)
    suffix = "1hr"
    all_symbols = symbols_for_suffix(suffix)
    cache: dict = {}

    # --- Stage 1: trend-R^2 for DD + a comparison sample ---
    comparison_sample = list(
        rng.choice([s for s in all_symbols if s != "DD"], size=30, replace=False)
    )
    stage1_symbols = ["DD"] + comparison_sample
    rows = []
    for sym in stage1_symbols:
        if sym not in cache:
            try:
                cache[sym] = load_log_close(sym, suffix)
            except Exception:
                cache[sym] = None
        lc = cache[sym]
        if lc is None:
            continue
        r1 = trend_r_squared(lc)
        rows.append({"symbol": sym, **r1})
    stage1 = pd.DataFrame(rows).sort_values("r_squared", ascending=False)
    print("=== Stage 1: trend R^2 (DD vs. 30-symbol random comparison sample) ===")
    print(stage1.to_string(index=False))
    dd_r2 = float(stage1.loc[stage1.symbol == "DD", "r_squared"].iloc[0])
    other_r2 = stage1.loc[stage1.symbol != "DD", "r_squared"]
    print(
        f"\nDD trend R^2 = {dd_r2:.4f} | comparison sample: "
        f"median={other_r2.median():.4f}, 90th pct={other_r2.quantile(0.9):.4f}, "
        f"max={other_r2.max():.4f}"
    )
    dd_percentile = float((other_r2 < dd_r2).mean())
    print(f"DD sits at/above the {dd_percentile:.0%} percentile of the comparison sample.\n")

    # --- Stage 2: spurious-regression risk score, DD vs. 3 comparison symbols ---
    # n_partners=150 for DD specifically -- debug/_verify_trend_dominance_diagnostic.py
    # found n=40 too noisy to distinguish an ordinary stock's baseline rate
    # cleanly (WMT vs PG gave inconsistent, sometimes-inverted directional
    # reads at n=40; n=150 settled to a stable ~5-10% ordinary-stock band).
    # DD's true rate is large enough (see below) that this matters less for
    # DD itself, but 150 is used throughout here for a fair, consistent
    # comparison against that now-validated ordinary-stock baseline.
    print("=== Stage 2: spurious-regression risk score (EG vs. 150 random partners for DD; "
          "40 for comparison symbols, matching the verify script's cheaper baseline check) ===")
    risk_rows = []
    dd_risk = spurious_regression_risk_score("DD", suffix, all_symbols, 150, rng, cache)
    risk_rows.append({"symbol": "DD", **{k: v for k, v in dd_risk.items() if k != "pvalues"}})
    print(f"DD: n_ok={dd_risk['n_ok']} n_rejected={dd_risk['n_rejected']} "
          f"risk_rate={dd_risk['risk_rate']:.2%}")

    comparison_risk_symbols = list(rng.choice(comparison_sample, size=3, replace=False))
    comparison_risks = {}
    for sym in comparison_risk_symbols:
        r2 = spurious_regression_risk_score(sym, suffix, all_symbols, 40, rng, cache)
        comparison_risks[sym] = r2
        risk_rows.append({"symbol": sym, **{k: v for k, v in r2.items() if k != "pvalues"}})
        print(f"{sym}: n_ok={r2['n_ok']} n_rejected={r2['n_rejected']} "
              f"risk_rate={r2['risk_rate']:.2%}")

    # --- Remedy test: apply leg_corrected_pvalue() to DD's real candidate pairs ---
    print("\n=== Remedy: leg_corrected_pvalue() applied to DD's real 1h candidates ===")
    cand_path = "output/results/1hr/all_candidates.parquet"
    before_after = None
    if os.path.exists(cand_path):
        cand = pd.read_parquet(cand_path)
        dd_mask = (cand["symbol_a"] == "DD") | (cand["symbol_b"] == "DD")
        dd_cand = cand.loc[dd_mask].copy()
        raw_p = dd_cand["coint_pvalue_raw"].values
        corrected_p = np.array([leg_corrected_pvalue(p, dd_risk["pvalues"]) for p in raw_p])
        n_before = int((raw_p < 0.05).sum())
        n_after = int((corrected_p < 0.05).sum())
        before_after = {
            "n_dd_candidates": len(dd_cand),
            "n_significant_before": n_before,
            "n_significant_after": n_after,
            "pct_reduction": 1.0 - (n_after / n_before if n_before else 1.0),
        }
        print(
            f"DD candidates: {len(dd_cand)} | significant before correction "
            f"(raw p<0.05): {n_before} | after leg-corrected p<0.05: {n_after} "
            f"({before_after['pct_reduction']:.1%} reduction)"
        )
    else:
        print(f"WARNING: {cand_path} not found -- skipping real before/after test.")

    out_rows = pd.DataFrame(risk_rows)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out_rows.to_parquet(OUT_PATH, index=False)
    print(f"\nSaved: {OUT_PATH}")

    return {
        "dd_r2": dd_r2,
        "dd_r2_percentile": dd_percentile,
        "dd_risk_rate": dd_risk["risk_rate"],
        "comparison_risk_rates": {k: v["risk_rate"] for k, v in comparison_risks.items()},
        "before_after": before_after,
    }


if __name__ == "__main__":
    main()
