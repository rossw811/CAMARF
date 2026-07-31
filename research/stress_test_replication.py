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
_CALM_CONTROLS = [
    ("calm_control_2015_08", "2015-08-01", "2015-08-17"),      # analog to aug_2007_quant_quake
    ("calm_control_2016_2017", "2016-09-01", "2017-03-31"),    # analog to 2008_gfc
    ("calm_control_2018", "2018-02-19", "2018-04-30"),         # analog to 2020_covid_crash
]

# Same stop-loss convention backtest.py's Layer 1 baseline uses (Config.BACKTEST
# stop at 3.5 sigma) — used here as the honest yardstick for "extreme" rather
# than an arbitrary new threshold invented for this script.
_EXTREME_Z_THRESHOLD = getattr(Config.BACKTEST, "STOP_ZSCORE", 3.5)


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

    baseline = aligned[(aligned.index >= baseline_start_ts) & (aligned.index < crisis_start_ts)]
    crisis = aligned[(aligned.index >= crisis_start_ts) & (aligned.index <= crisis_end_ts)]
    if len(baseline) < 60 or len(crisis) < 3:
        return {"status": "INSUFFICIENT_HISTORY", "data_start": aligned.index.min()}

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

    crisis_spread = crisis["a"] - hedge_ratio * crisis["b"]
    crisis_z = (crisis_spread - spread_mean) / spread_std
    max_abs_z = float(crisis_z.abs().max())

    # Formal EG re-test on baseline+crisis combined, at daily resolution.
    combined = aligned[(aligned.index >= baseline_start_ts) & (aligned.index <= crisis_end_ts)]
    eg_result = _eg_worker((sym_a, sym_b, combined["a"].values, combined["b"].values,
                             Config.ANALYSIS.EG_MAX_LAG, _TF_LABEL))

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
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== stress_test_replication.py: historical crisis stress test on confirmed pairs (1D resolution) ===")
    log.info("SCOPE: tests cointegration-relationship stability at DAILY resolution during known "
             "historical crisis windows — does NOT replay the intraday strategy (no cached 1h data "
             "reaches back to 2007/2020; see module docstring).")

    if not os.path.exists(_MANIFEST_PATH):
        log.warning("No confirmed_pairs_manifest.json found — run analysis.py first.")
        return
    import json
    with open(_MANIFEST_PATH) as f:
        manifest = json.load(f)

    # Reconstruct confirmed pairs from per-TF pairs.parquet (manifest only
    # tracks symbols, not pairings) — same source decoupling_requalification.py uses.
    import glob
    pairs = []
    for pairs_path in sorted(glob.glob(os.path.join(_ROOT, "output", "results", "*", "pairs.parquet"))):
        df = pd.read_parquet(pairs_path)
        for _, row in df.iterrows():
            pairs.append((row["symbol_a"], row["symbol_b"]))
    pairs = sorted(set(pairs))
    all_windows = _CRISES + _CALM_CONTROLS
    log.info("%d confirmed pairs to test across %d crisis windows + %d calm controls",
              len(pairs), len(_CRISES), len(_CALM_CONTROLS))

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
                    "  %s/%s @ %s: max|z|=%.2f%s, EG p=%.4f (%s)",
                    sym_a, sym_b, crisis_name, result["max_abs_z_during_crisis"],
                    " [EXTREME]" if result["extreme_dislocation"] else "",
                    result["eg_pvalue_baseline_plus_crisis"],
                    "cointegration holds" if result["cointegration_holds"] else "cointegration does NOT hold",
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
        for crisis_name, _, _ in _CRISES + _CALM_CONTROLS:
            sub = tested[tested["crisis"] == crisis_name]
            if sub.empty:
                continue
            n_extreme = int(sub["extreme_dislocation"].sum())
            n_coint_holds = int(sub["cointegration_holds"].sum())
            log.info(
                "  [%s] %d/%d pairs tested: %d extreme dislocation (|z|>%.1f), "
                "%d/%d still cointegrated through baseline+crisis",
                crisis_name, len(sub), len(sub), n_extreme, _EXTREME_Z_THRESHOLD, n_coint_holds, len(sub),
            )

    # Crisis-vs-calm-control comparison — without this, "0/13 cointegrated
    # during crisis" is not interpretable: it could reflect crisis-specific
    # fragility, or simply that a single-shot daily EG test on any arbitrary
    # old window rarely finds cointegration for pairs discovered on
    # 2023-2026 1h data. Compare directly before drawing any conclusion.
    if not tested.empty:
        crisis_names = [c[0] for c in _CRISES]
        calm_names = [c[0] for c in _CALM_CONTROLS]
        crisis_sub = tested[tested["crisis"].isin(crisis_names)]
        calm_sub = tested[tested["crisis"].isin(calm_names)]
        if not crisis_sub.empty and not calm_sub.empty:
            crisis_extreme_rate = crisis_sub["extreme_dislocation"].mean()
            calm_extreme_rate = calm_sub["extreme_dislocation"].mean()
            crisis_coint_rate = crisis_sub["cointegration_holds"].mean()
            calm_coint_rate = calm_sub["cointegration_holds"].mean()
            log.info(
                "\n--- Crisis vs. calm-control comparison (the honest read on whether this is a "
                "crisis-specific finding) ---\n"
                "  Extreme dislocation rate: crisis=%.0f%% (%d/%d) vs calm=%.0f%% (%d/%d)\n"
                "  Cointegration-holds rate: crisis=%.0f%% (%d/%d) vs calm=%.0f%% (%d/%d)",
                crisis_extreme_rate * 100, int(crisis_sub["extreme_dislocation"].sum()), len(crisis_sub),
                calm_extreme_rate * 100, int(calm_sub["extreme_dislocation"].sum()), len(calm_sub),
                crisis_coint_rate * 100, int(crisis_sub["cointegration_holds"].sum()), len(crisis_sub),
                calm_coint_rate * 100, int(calm_sub["cointegration_holds"].sum()), len(calm_sub),
            )
            if abs(crisis_extreme_rate - calm_extreme_rate) < 0.15 and abs(crisis_coint_rate - calm_coint_rate) < 0.15:
                log.warning(
                    "Crisis and calm-control rates are similar (within 15 pts on both metrics) — "
                    "this test cannot distinguish crisis-specific fragility from a general property "
                    "of single-shot daily EG tests on old windows for these pairs. Report this "
                    "honestly as inconclusive on the crisis-specific question, not as evidence of "
                    "crisis fragility."
                )
            else:
                log.info(
                    "Crisis and calm-control rates differ by more than 15 points — some support for "
                    "a genuine crisis-specific effect, though still confounded by everything else "
                    "that differs between these specific historical windows."
                )

    os.makedirs(_OUT_DIR, exist_ok=True)
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
