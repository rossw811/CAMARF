"""
research/stress_test_replication.py — honest-scope historical crisis stress
test for CAMARF's confirmed pairs.

Motivation (STORM infrastructure gap analysis, 2026-07-01): the Historian-
lens research found every "institutional" risk control (stress testing,
crowding monitors, circuit breakers) was added reactively after a specific
named crisis exposed its absence (LTCM 1998, Aug 2007 quant quake, 2010
Flash Crash, Knight Capital 2012). CAMARF had no historical-scenario stress
test at all. Building one honestly requires confronting a real data
constraint first, not glossing over it: the 17 @1h confirmed pairs only have
cached INTRADAY history back to 2023-07-24 (yfinance's 730-day 1h cap), so
this script does NOT replay the exact 1h trading strategy through 2007/2020
— that data doesn't exist. What DOES exist is deep DAILY history (yfinance
period="max") for almost every confirmed-pair symbol, reaching back decades
for most (see module-level SYMBOL_HISTORY_START below, checked directly
against real cached data, not assumed).

**What this actually tests, stated precisely so it isn't over-claimed:**
does each confirmed pair's underlying cointegration relationship — the same
Engle-Granger test analysis.py's production pipeline uses, and the same
OLS-hedge-ratio spread this project's whole strategy rests on — hold up
through known historical crisis windows, at DAILY resolution? This is a
test of relationship stability under stress, not a backtest of the intraday
strategy's crisis-period P&L (which would require data this project does
not have and should not fabricate).

Method, per pair, per crisis window:
  1. Load daily log-close prices for both legs across full available history.
  2. Skip the pair for a given crisis window if either leg's daily history
     doesn't start at least BASELINE_YEARS before the crisis window begins
     (documented per-pair, not silently dropped — mirrors era_decay_
     replication.py's honest-exclusion convention).
  3. Fit OLS hedge ratio + spread mean/std on the BASELINE window only
     (strictly before the crisis starts — no lookahead into the crisis
     itself), then compute the out-of-sample z-score of the spread during
     the crisis window using those baseline-fit parameters.
  4. Separately, run analysis.py's own _eg_worker (identical EG test,
     statsmodels.coint(), trend="c", autolag="aic") on baseline+crisis
     combined, to check whether formal cointegration still holds through
     the stress period, not just whether the OOS z-score stayed bounded.

2026-10-18 (D7/D8/D9, Ross 2026-10-12; details docs/decisions/DECISIONS_2026-10-12.md):
  D7 (R5.5): step 4's EG is dominated by the ~500 baseline days and cannot see an in-crisis break; it is kept as a
     labelled legacy column. The test used is Andrews & Kim (2006, JBES) P (R beside it) for cointegration breakdown in
     the crisis window, subsample p-values from the baseline, baseline T = max(2 years, 10 x m) rows (m/T <= .1, the
     paper's stated range; pairs without that history are INSUFFICIENT_HISTORY with t_required). Descriptive: beta
     uses the crisis window by design. Step 3's hedge ratio / z-score now use the same T-row baseline.
  D8 (R5.6): calm controls derived from VIX (every day below the 1990-2025 30th percentile, same length, same start
     month, closest in time; the GFC length has no same-month window, so its control is not season-matched).
  D9 (R5.7): crisis vs each pair's own control is paired: sign-flip randomization over shared-leg components
     (output/research/stress_test_replication_paired.parquet); replaces the 15-point rule of thumb.
2026-10-18, after adversarial review of 6226c881 (Ross: y):
  D7 precondition: ak_breakdown is defined only when the baseline alone passes production EG (no lookahead); else
     None = "no baseline relationship" (independent random walks: 19/100 flagged before, 2/100 after). Pairs enter
     D9 only if both the crisis and the calm baselines pass. baseline_spread_ar1 reported per pair.
  D8 ranking: same month, then closest start day-of-month, then closest in time, ties earlier.
  Disclosed limits: (i) P-test size is above nominal for some spread persistences (see Development.md 2026-10-18 for
     the measured table); (ii) the D9 test has a floor p of 2^(1-K) over K discordant units (min_p_achievable), and
     its result is about these six windows only, not crises in general; (iii) baselines can contain other stress
     periods (the GFC baseline includes Aug 2007); (iv) the aligned frame drops gap-masked rows (dropna), so a window
     can span a DATA_GAP as if the rows were adjacent.

Crisis windows (all well short of the confirmed pairs' full daily history
for most symbols, per the docstring's real-data check above):
  - Aug 2007 Quant Quake: 2007-08-01 to 2007-08-17 (the acute week plus
    surrounding days — Khandani & Lo NBER w14465 dates the core event to
    Aug 6-9, 2007)
  - 2008 GFC: 2008-09-01 to 2009-03-31 (Lehman collapse through the
    market bottom)
  - 2020 COVID Crash: 2020-02-19 to 2020-04-30 (S&P 500 all-time-high
    pre-crash through the initial V-shaped recovery)

Output: output/research/stress_test_replication.parquet
"""
import argparse
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _eg_worker
from config import Config
from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price

_TF_LABEL = "1D"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_MANIFEST_PATH = os.path.join(_ROOT, "output", "results", "confirmed_pairs_manifest.json")

log = logging.getLogger("stress_test_replication")

_BASELINE_YEARS = 2  # years of pre-crisis history required to fit hedge ratio + spread stats

_CRISES = [
    ("aug_2007_quant_quake", "2007-08-01", "2007-08-17"),
    ("2008_gfc", "2008-09-01", "2009-03-31"),
    ("2020_covid_crash", "2020-02-19", "2020-04-30"),
]

# Calm-period controls, same window length/season as the crisis they pair
# with, but no documented crisis in the window — added after the first real
# run showed 0/13-1/21 cointegration-holds rates across every crisis, which
# is ambiguous on its own: it could mean crisis-specific fragility, or it
# could just mean a single-shot EG test on an arbitrary old daily window
# rarely finds cointegration for these pairs regardless of market
# conditions (most were discovered on 2023-2026 1h data, not historical
# daily data). Without this control, "0/13 cointegrated during the crisis"
# is not interpretable as a crisis finding at all.
#
# D8 (R5.6, 2026-10-18): the hand-picked controls (2015-08-01..17, 2016-09-01..2017-03-31, 2018-02-19..04-30) were
# chosen after the first run and were not calm (2018 follows the Feb-2018 VIX spike). Controls are now derived from
# VIX by the pre-registered rule in select_calm_window(); see derive_calm_controls().


def derive_calm_controls(vix: pd.Series, crises=None) -> list:
    """D8: one calm control per crisis, same length in VIX trading days. Returns
    [(control_name, start, end, crisis_name, season_matched)]."""
    crises = crises or _CRISES
    out = []
    for name, start, end in crises:
        n_days = int(((vix.dropna().index >= pd.Timestamp(start)) & (vix.dropna().index <= pd.Timestamp(end))).sum())
        w = select_calm_window(vix, start, n_days, crises)
        out.append((f"calm_control_for_{name}", str(w["start"].date()), str(w["end"].date()), name, w["season_matched"]))
    return out

# Same stop-loss convention backtest.py's Layer 1 baseline uses (Config.BACKTEST
# stop at 3.5 sigma) — used here as the honest yardstick for "extreme" rather
# than an arbitrary new threshold invented for this script.
_EXTREME_Z_THRESHOLD = getattr(Config.BACKTEST, "STOP_ZSCORE", 3.5)


# --- D7 (Ross 2026-10-12, details 2026-10-17/18): Andrews & Kim (2006), "Tests for Cointegration Breakdown Over a
# Short Time Period", JBES 24(4) 379-394, verified against the author-hosted PDF. Descriptive: beta uses all T+m obs.
_AK_MAX_M_OVER_T = 0.1   # the paper: "The P test works well for values [of m/T] as high as .1"
_AK_ALPHA = 0.05         # P-test level; its own constant, not borrowed from EG_SIGNIFICANCE (the screen's level)


def baseline_length(n_rows_two_years: int, m: int) -> int:
    """D7: baseline rows T = max(2 years of rows, m / 0.1), so m/T stays within the paper's stated range."""
    return int(max(n_rows_two_years, int(np.ceil(m / _AK_MAX_M_OVER_T))))


def andrews_kim_test(y, x, T: int, m: int) -> dict:
    """P (eq. 8) and R (eqs. 25-26) for a breakdown in obs T..T+m-1 of y = c + beta*x + u, with subsample p-values
    (eqs. 10-15): P_j uses the leave-ceil(m/2)-out estimator on obs 0..T-1; pv = mean(stat <= stat_j)."""
    y = np.asarray(y, dtype=float)[:T + m]
    X = np.column_stack([np.ones(T + m), np.asarray(x, dtype=float)[:T + m]])
    b_all = np.linalg.lstsq(X, y, rcond=None)[0]
    u_post = y[T:] - X[T:] @ b_all
    P = float(u_post @ u_post)
    R = float(np.sum(np.cumsum(u_post[::-1]) ** 2))
    h = int(np.ceil(m / 2))
    n_sub = T - m + 1
    XT, yT = X[:T], y[:T]
    cxx = np.concatenate([np.zeros((1, 2, 2)), np.cumsum(np.einsum("ti,tj->tij", XT, XT), axis=0)])
    cxy = np.concatenate([np.zeros((1, 2)), np.cumsum(XT * yT[:, None], axis=0)])
    j = np.arange(n_sub)
    A = cxx[T] - (cxx[j + h] - cxx[j])                               # X'X over obs 0..T-1 minus j..j+h-1
    rhs = cxy[T] - (cxy[j + h] - cxy[j])
    B = np.linalg.solve(A, rhs[..., None])[..., 0]                   # (n_sub, 2): leave-ceil(m/2)-out betas
    win = np.lib.stride_tricks.sliding_window_view(np.arange(T), m)[:n_sub]
    resid = yT[win] - (B[:, None, 0] + B[:, None, 1] * XT[win, 1])
    Pj = np.sum(resid ** 2, axis=1)
    # Eq. 25 prints R_j = P_{T+1}(beta_2(j), A_m); the subsample statistic is evaluated on window j..j+m-1 (as P_j in
    # eq. 11 and as eq. 26's "replace beta_1:(T+m) by beta_2(j)" implies) -- the T+1 subscript is a typo.
    Rj = np.sum(np.cumsum(resid[:, ::-1], axis=1) ** 2, axis=1)
    return {"P": P, "R": R, "pv_P": float(np.mean(P <= Pj)), "pv_R": float(np.mean(R <= Rj)),
            "n_subsamples": int(n_sub), "m_over_T": m / T, "beta_full": float(b_all[1])}


# --- D8 (Ross 2026-10-12, details 2026-10-18): calm controls derived from VIX, not hand-picked.
_CALM_VIX_QUANTILE = 0.30
_CALM_VIX_PERIOD = ("1990-01-01", "2025-12-31")


def select_calm_window(vix: pd.Series, crisis_start: str, n_days: int, crises,
                       q: float = _CALM_VIX_QUANTILE, period=_CALM_VIX_PERIOD) -> dict:
    """Every VIX day below its `period` q-quantile (descriptive), n_days long, starting in the crisis's month, not
    overlapping any crisis window; the qualifying window whose start is closest to the crisis start (ties: earlier).
    No same-month window -> any month, season_matched=False. None at all -> ValueError (never relaxed silently).
    Ranking (Ross 2026-10-18): same month, then closest start day-of-month, then closest in time, then earlier --
    "closest in time" alone picked month-end starts (2006-08-31, 2006-02-28), i.e. September/March windows."""
    v = vix.dropna().loc[period[0]:period[1]]
    thr = float(v.quantile(q))
    n = len(v)
    if n_days > n:
        raise ValueError(f"window of {n_days} days longer than the VIX history")
    run = np.lib.stride_tricks.sliding_window_view((v < thr).to_numpy(), n_days).all(axis=1)
    starts, ends = v.index[:n - n_days + 1], v.index[n_days - 1:]
    ok = run.copy()
    for _, cs, ce in crises:
        ok &= ~((starts <= pd.Timestamp(ce)) & (ends >= pd.Timestamp(cs)))
    c0 = pd.Timestamp(crisis_start)
    for season in (True, False):
        cand = (ok & (starts.month == c0.month)) if season else ok
        if cand.any():
            pos = np.flatnonzero(cand)
            dist = np.abs((starts[pos] - c0).days)
            day_dist = np.abs(starts[pos].day - c0.day) if season else np.zeros(len(pos), dtype=int)
            best = pos[np.lexsort((starts[pos].asi8, dist, day_dist))[0]]
            return {"start": starts[best], "end": ends[best], "n_days": int(n_days), "threshold": thr,
                    "season_matched": season}
    raise ValueError(f"no {n_days}-day window with every VIX day below {thr:.2f} in {period}")


# --- D9 (Ross 2026-10-12, details 2026-10-17): each pair's crisis outcome vs its own calm-control outcome is paired.
def paired_component_signflip_test(df: pd.DataFrame, n_sim: int = 100_000, rng=None, exact_max_units: int = 20) -> dict:
    """df: one row per (pair, crisis) with bool crisis_outcome / calm_outcome; d = crisis - calm. Null: within each
    connected component of pairs sharing a leg (the D2 unit, over all crises) crisis/calm labels are exchangeable ->
    flip the sign of each component's summed d. Exact when <= exact_max_units components are non-zero. Classical
    exact McNemar (pairs as independent) reported beside it for reference. min_p_achievable = 2^(1-K) for K non-zero
    units (the all-same-sign outcome): with K < 6 the test cannot reach 0.05 whatever the data."""
    from scipy import stats
    from crisis_regime_concentration_significance_test import pair_component_labels
    rng = rng or np.random.default_rng(0)
    d = df["crisis_outcome"].astype(int).to_numpy() - df["calm_outcome"].astype(int).to_numpy()
    lab = pair_component_labels(df["symbol_a"], df["symbol_b"])
    D = pd.Series(d).groupby(lab).sum().to_numpy()
    D = D[D != 0]
    S = int(d.sum())
    if len(D) == 0:
        p = 1.0
    elif len(D) <= exact_max_units:
        signs = 1 - 2 * ((np.arange(2 ** len(D))[:, None] >> np.arange(len(D))) & 1)
        p = float(np.mean(np.abs(signs @ D) >= abs(S)))
    else:
        sims = (1 - 2 * rng.integers(0, 2, size=(n_sim, len(D)))) @ D
        p = float((1 + np.sum(np.abs(sims) >= abs(S))) / (n_sim + 1))
    b, c = int(np.sum(d == 1)), int(np.sum(d == -1))
    mc = float(stats.binomtest(b, b + c, 0.5).pvalue) if b + c else 1.0
    return {"n": int(len(d)), "crisis_rate": float(df["crisis_outcome"].mean()),
            "calm_rate": float(df["calm_outcome"].mean()), "rate_diff": S / len(d),
            "discordant_crisis_only": b, "discordant_calm_only": c, "n_units_discordant": int(len(D)),
            "p_value": p, "min_p_achievable": float(2.0 ** (1 - len(D))) if len(D) else 1.0, "mcnemar_exact_p": mc}


def build_paired_table(tested: pd.DataFrame, calm_controls: list, outcome: str, crisis=None) -> pd.DataFrame:
    """D9: one row per (pair, crisis) where the pair was TESTED in both the crisis and that crisis's own calm control:
    symbol_a, symbol_b, crisis, crisis_outcome, calm_outcome. Pairs missing either side, or with a missing outcome on
    either side (ak_breakdown is missing when that window's baseline fails the D7 precondition), are dropped."""
    # D7 precondition applies to EVERY D9 outcome (Ross 2026-10-18: a pair enters only if both baselines pass); the gate
    # covered ak_breakdown alone until the review of 64d9e9f5. Per-window extreme_dislocation stays ungated (descriptive).
    if "baseline_cointegrated" in tested.columns:
        tested = tested[tested["baseline_cointegrated"] == True]  # noqa: E712
    out = []
    for c_name, _, _, for_crisis, _ in calm_controls:
        if crisis is not None and for_crisis != crisis:
            continue
        cr = tested[tested["crisis"] == for_crisis].set_index(["symbol_a", "symbol_b"])[outcome].dropna()
        ca = tested[tested["crisis"] == c_name].set_index(["symbol_a", "symbol_b"])[outcome].dropna()
        both = cr.index.intersection(ca.index)
        out.append(pd.DataFrame({"symbol_a": [k[0] for k in both], "symbol_b": [k[1] for k in both],
                                 "crisis": for_crisis, "crisis_outcome": cr.loc[both].astype(bool).to_numpy(),
                                 "calm_outcome": ca.loc[both].astype(bool).to_numpy()}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_stress_test_replication.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def stress_test_pair(sym_a: str, sym_b: str, crisis_name: str, crisis_start: str, crisis_end: str) -> "dict | None":
    """Returns None (with the caller expected to log why) if either leg's
    history doesn't reach far enough back to build a real baseline.

    Tier 6 fix (Grand Sweep 2026-07-20): previously loaded each leg via bare
    DataStore.load() with no gap-flag masking at all before the EG test —
    low risk for a level-based test at daily resolution (this file's own
    _eg_worker fix's is_genuine_data_gap treats 1D as a no-op, since the
    dense-calendar-padding artifact only affects intraday timeframes), but
    aligned here for consistency with sibling scripts."""
    df_a, df_b = load_aligned_pair(sym_a, sym_b, _TF_LABEL)
    if df_a is None or df_b is None:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)

    crisis_start_ts = pd.Timestamp(crisis_start)
    crisis_end_ts = pd.Timestamp(crisis_end)
    baseline_start_ts = crisis_start_ts - pd.DateOffset(years=_BASELINE_YEARS)

    aligned = pd.DataFrame({"a": log_a, "b": log_b}).dropna()
    if aligned.empty or aligned.index.min() > baseline_start_ts:
        return {"status": "INSUFFICIENT_HISTORY", "data_start": None if aligned.empty else aligned.index.min()}

    crisis = aligned[(aligned.index >= crisis_start_ts) & (aligned.index <= crisis_end_ts)]
    pre = aligned[aligned.index < crisis_start_ts]
    n_two_years = int((pre.index >= baseline_start_ts).sum())
    if n_two_years < 60 or len(crisis) < 3:
        return {"status": "INSUFFICIENT_HISTORY", "data_start": aligned.index.min()}
    # D7: T = max(2 years, 10 x m) rows so m/T <= .1 (Andrews-Kim's stated range); too little history -> excluded, listed.
    t_required = baseline_length(n_two_years, len(crisis))
    if len(pre) < t_required:
        return {"status": "INSUFFICIENT_HISTORY", "data_start": aligned.index.min(), "t_required": t_required}
    baseline = pre.iloc[-t_required:]

    # OLS hedge ratio fit on baseline only (no lookahead into the crisis window).
    b_centered = baseline["b"] - baseline["b"].mean()
    a_centered = baseline["a"] - baseline["a"].mean()
    var_b = float(np.dot(b_centered, b_centered))
    if var_b <= 0:
        return {"status": "DEGENERATE_BASELINE"}
    hedge_ratio = float(np.dot(a_centered, b_centered) / var_b)

    baseline_spread = baseline["a"] - hedge_ratio * baseline["b"]
    spread_mean, spread_std = float(baseline_spread.mean()), float(baseline_spread.std())
    if spread_std <= 0:
        return {"status": "DEGENERATE_BASELINE"}

    # D7 precondition (Ross 2026-10-18): "breakdown" needs a relationship to break. Production EG on the baseline rows
    # only (no lookahead); a failing pair is "no baseline relationship" and ak_breakdown is None. Without it 22-24% of
    # independent random walks were flagged as breakdowns (adversarial review of 6226c881, reproduced).
    eg_base = _eg_worker((sym_a, sym_b, baseline["a"].values, baseline["b"].values,
                          Config.ANALYSIS.EG_MAX_LAG, _TF_LABEL))
    baseline_cointegrated = bool(eg_base.get("ok") and eg_base.get("pvalue", 1.0) < Config.ANALYSIS.EG_SIGNIFICANCE)
    # Baseline spread persistence: the P test over-rejects for persistent spreads (measured size ~10-11% at rho .97,
    # m = 13-50), so each pair's rho is reported beside its result.
    s_dm = (baseline_spread - spread_mean).to_numpy()
    baseline_spread_ar1 = float(np.dot(s_dm[1:], s_dm[:-1]) / np.dot(s_dm[:-1], s_dm[:-1]))

    crisis_spread = crisis["a"] - hedge_ratio * crisis["b"]
    crisis_z = (crisis_spread - spread_mean) / spread_std
    max_abs_z = float(crisis_z.abs().max())

    # Legacy (R5.5): EG on baseline+crisis combined -- dominated by the baseline days, cannot see an in-crisis break.
    # Kept as a labelled column for continuity with earlier reports; the D7 breakdown test below is the one used.
    combined = pd.concat([baseline, crisis])
    eg_result = _eg_worker((sym_a, sym_b, combined["a"].values, combined["b"].values,
                             Config.ANALYSIS.EG_MAX_LAG, _TF_LABEL))
    ak = andrews_kim_test(combined["a"].values, combined["b"].values, T=len(baseline), m=len(crisis))

    return {
        "status": "TESTED",
        "crisis": crisis_name,
        "n_baseline_days": len(baseline),
        "n_crisis_days": len(crisis),
        "hedge_ratio": hedge_ratio,
        "max_abs_z_during_crisis": max_abs_z,
        "extreme_dislocation": max_abs_z > _EXTREME_Z_THRESHOLD,
        "eg_pvalue_baseline_plus_crisis": eg_result.get("pvalue"),
        "cointegration_holds": bool(
            eg_result.get("ok") and eg_result.get("pvalue", 1.0) < Config.ANALYSIS.EG_SIGNIFICANCE
        ),
        "ak_P": ak["P"], "ak_pv_P": ak["pv_P"], "ak_R": ak["R"], "ak_pv_R": ak["pv_R"],
        "ak_m_over_T": ak["m_over_T"],
        "eg_pvalue_baseline_only": eg_base.get("pvalue"),
        "baseline_cointegrated": baseline_cointegrated,
        "baseline_spread_ar1": baseline_spread_ar1,
        # descriptive (beta uses the crisis window); None = no baseline relationship, not a breakdown
        "ak_breakdown": bool(ak["pv_P"] < _AK_ALPHA) if baseline_cointegrated else None,
    }


def main():
    ap = argparse.ArgumentParser(description="Historical crisis stress test on confirmed pairs (2026-07-01)")
    ap.add_argument("--pit-safe", action="store_true",
                     help="Source pairs from research/pit_pair_discovery.py's PIT-safe episodic "
                          "screen instead of the production confirmed_pairs_manifest.json (task #5). "
                          "NOTE: this is a real compute-scale jump (~700 pairs vs. a handful) since "
                          "every pair is tested across 3 crisis windows + 3 calm controls — hold "
                          "this for a time when it won't contend with other running jobs.")
    args = ap.parse_args()

    _setup_logging()
    t0 = time.time()
    log.info("=== stress_test_replication.py: historical crisis stress test on confirmed pairs (1D resolution) ===")
    log.info("SCOPE: tests cointegration-relationship stability at DAILY resolution during known "
             "historical crisis windows — does NOT replay the intraday strategy (no cached 1h data "
             "reaches back to 2007/2020; see module docstring).")

    if args.pit_safe:
        sys.path.insert(0, os.path.join(_ROOT, "research"))
        from pit_pair_discovery import discover_pit_confirmed_pairs
        pit_pairs = discover_pit_confirmed_pairs()
        pairs = sorted(set((a, b) for a, b, _tf in pit_pairs))
        log.info("Using PIT-safe episodic pair discovery: %d unique pairs", len(pairs))
    else:
        if not os.path.exists(_MANIFEST_PATH):
            log.warning("No confirmed_pairs_manifest.json found — run analysis.py first.")
            return
        # Reconstruct confirmed pairs from per-TF pairs.parquet (manifest only
        # tracks symbols, not pairings) — same source decoupling_requalification.py uses.
        import glob
        pairs = []
        for pairs_path in sorted(glob.glob(os.path.join(_ROOT, "output", "results", "*", "pairs.parquet"))):
            df = pd.read_parquet(pairs_path)
            for _, row in df.iterrows():
                pairs.append((row["symbol_a"], row["symbol_b"]))
        pairs = sorted(set(pairs))

    import macro
    vix = macro.build(series=["VIXCLS"]).data["vix_close"]
    calm_controls = derive_calm_controls(vix)
    for c_name, c_start, c_end, for_crisis, season in calm_controls:
        log.info("D8 calm control for %s: %s..%s (every VIX day below its 1990-2025 30th pct)%s",
                 for_crisis, c_start, c_end, "" if season else " -- NOT season-matched (no same-month window qualifies)")
    all_windows = _CRISES + [(c[0], c[1], c[2]) for c in calm_controls]
    log.info("%d pairs to test across %d crisis windows + %d calm controls",
              len(pairs), len(_CRISES), len(calm_controls))

    rows = []
    for sym_a, sym_b in pairs:
        for crisis_name, start, end in all_windows:
            result = stress_test_pair(sym_a, sym_b, crisis_name, start, end)
            if result is None:
                continue
            row = {"symbol_a": sym_a, "symbol_b": sym_b, "crisis": crisis_name, **result}
            rows.append(row)
            if result["status"] == "TESTED":
                log.info(
                    "  %s/%s @ %s: max|z|=%.2f%s, Andrews-Kim P p=%.4f (m/T %.3f)%s; legacy EG p=%.4f",
                    sym_a, sym_b, crisis_name, result["max_abs_z_during_crisis"],
                    " [EXTREME]" if result["extreme_dislocation"] else "",
                    result["ak_pv_P"], result["ak_m_over_T"], (" [NO BASELINE RELATIONSHIP]" if result["ak_breakdown"] is None
                     else " [BREAKDOWN]" if result["ak_breakdown"] else ""),
                    result["eg_pvalue_baseline_plus_crisis"],
                )
            else:
                log.info("  %s/%s @ %s: %s", sym_a, sym_b, crisis_name, result["status"])

    if not rows:
        log.warning("No pairs produced a result.")
        return

    result_df = pd.DataFrame(rows)
    tested = result_df[result_df["status"] == "TESTED"]
    log.info(
        "\n--- Result: %d/%d pair-crisis combinations testable (rest lack sufficient pre-crisis "
        "daily history) ---", len(tested), len(result_df)
    )
    if not tested.empty:
        for crisis_name, _, _ in all_windows:
            sub = tested[tested["crisis"] == crisis_name]
            if sub.empty:
                continue
            log.info(
                "  [%s] %d pairs tested, %d cointegrated on their baseline: %d Andrews-Kim breakdown (P test, 5%%), "
                "%d extreme dislocation (|z|>%.1f); legacy EG 'holds' %d", crisis_name, len(sub),
                int(sub["baseline_cointegrated"].sum()), int((sub["ak_breakdown"] == True).sum()),  # noqa: E712
                int(sub["extreme_dislocation"].sum()), _EXTREME_Z_THRESHOLD, int(sub["cointegration_holds"].sum()),
            )

    # D9 (R5.7): each pair's crisis outcome against ITS OWN calm control -- paired, significance by sign flips over
    # connected components of pairs sharing a leg. Replaces the 15-point rule of thumb.
    os.makedirs(_OUT_DIR, exist_ok=True)
    paired_rows = []
    for outcome in ("ak_breakdown", "extreme_dislocation"):
        for scope in [None] + [c[0] for c in _CRISES]:
            paired = build_paired_table(tested, calm_controls, outcome, crisis=scope)
            if paired.empty:
                continue
            r = paired_component_signflip_test(paired, rng=np.random.default_rng(0))
            paired_rows.append({"outcome": outcome, "scope": scope or "all_crises", **r})
            log.info("D9 paired [%s, %s]: n=%d, crisis %.1f%% vs calm %.1f%%, discordant %d/%d over %d units, "
                     "component sign-flip p=%.4f (min achievable %.4f) (classical McNemar p=%.4f, pairs as independent -- reference only)",
                     outcome, scope or "all crises", r["n"], 100 * r["crisis_rate"], 100 * r["calm_rate"],
                     r["discordant_crisis_only"], r["discordant_calm_only"], r["n_units_discordant"],
                     r["p_value"], r["min_p_achievable"], r["mcnemar_exact_p"])
    # Always rewritten: an empty result must replace an earlier file, never leave it standing as if current.
    if not paired_rows:
        log.info("D9 paired: no pair has a cointegrated baseline in both a crisis and its calm control -- no test")
    pd.DataFrame(paired_rows, columns=None if paired_rows else ["outcome", "scope", "n", "p_value"]).to_parquet(
        os.path.join(_OUT_DIR, "stress_test_replication_paired.parquet"), index=False)

    out_path = os.path.join(_OUT_DIR, "stress_test_replication.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info("Saved -> %s", out_path)
    log.info("Reported honestly regardless of outcome direction: extreme z excursions during a "
             "crisis window are a finding about this pair's stress-period fragility, not a defect "
             "in this script, and the reverse (no dislocation) is not evidence the pair is immune "
             "to future stress, only that it survived these particular historical windows.")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("stress_test_replication.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
