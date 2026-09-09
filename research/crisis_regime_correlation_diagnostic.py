"""
research/crisis_regime_correlation_diagnostic.py -- does a candidate pair's
FIRST qualifying correlation window falling in a high-VIX regime predict
anything different about its downstream cointegration behavior?

Motivation (2026-08-25, live observation during the overnight episodic scan):
Tier 3's rolling correlation prefilter showed qualifying-pair counts holding
in the 150,000-250,000 range for windows ending 1994-2008, then jumping to
~1M-2.3M for windows spanning the 2008-2009 financial crisis and the 2020
COVID crash -- a 4-10x surge. Ross's framing, verbatim: "we have prior data
showing stocks cointegrating or moving together more often during VIX crisis
times, so if we factor in entry criteria or cointegration testing we should
note that jump."

This is deliberately NOT "pick a new correlation threshold and see if it
helps" -- that solves a hypothesized problem before confirming one exists,
and risks reading as tuning the pipeline until an inconvenient finding goes
away (the same trap this project explicitly avoids for backtest results,
per Development.md/CLAUDE.md's "question pair-selection criteria before
concluding the trading idea doesn't work, but disclose the search, don't
just report the version that worked"). This script is the diagnostic that
must come FIRST: does the crisis-era correlation surge translate into
systematically different downstream cointegration behavior at all? If not,
no fix is needed. If so, the specific mechanism (partial/market-neutral
correlation, cross-regime persistence requirement, or a straightforward
regime-adaptive threshold) is a separate, later decision -- not made here.

Related to, but a different question from, the existing Session 13 /
research/stress_test_replication.py finding (docs/HANDOFF.md): that work
asks "of pairs ALREADY past screening, does an existing cointegration
relationship survive a crisis differently than a calm period" (answer: no,
~8% vs 9%, roughly the same). This script asks a question upstream of that:
"does the raw correlation-based CANDIDATE POOL entry point itself differ
systematically by the regime a pair was FIRST discovered in."

Three sub-questions, in order (all pre-registered, reported regardless of
direction):
  1. Confirmation rate: do pairs first qualifying in a crisis-regime window
     get episodically BH-FDR-confirmed at a different rate than pairs first
     qualifying in a calm-regime window?
  2. Confirmation strength: among confirmed pairs, does episodic_fraction_fdr
     (the fraction of a pair's OWN tested windows that were FDR-rejected --
     the same continuous strength proxy Finding #28's regime segmentation
     uses) differ by first-window regime?
  3. Persistence: do crisis-first-qualified pairs disproportionately fail to
     reappear as a correlation candidate in any LATER non-crisis window
     (suggesting transient, regime-driven comovement) compared to
     calm-first-qualified pairs?

Data source, reused not re-collected: `output/research/wrds_deep_history_
episodic_scan_tier3_windows.parquet` (Tier 3's own flat (pair, window,
pvalue, window_end_date) rows -- a pair has a row for a given window only if
it was a correlation-prefilter candidate in that specific window, so the
EARLIEST window_end_date per pair is, by construction, its first qualifying
window; no need to re-derive or re-request the internal-only
first_qualified_window_end_date field rolling_correlation_candidate_pairs
computes but does not currently persist to the final output).

VIX regime classification reused from macro.py's already-existing,
already-config-driven `_classify_vix()` (calm <15 / normal [15,25) /
elevated [25,35) / crisis >=35, Config.MACRO.VIX_CALM/NORMAL_HI/ELEVATED_HI)
-- not reinvented. Point-in-time safety is automatic here: a pair's regime
label is read from VIX AS OF its own first_window_end_date only, never a
later date.

Honest scope note, carried into runtime output: as of this script's
authoring (2026-08-25), the Tier 3 windows file this reads is the
CORRECTED-scale run in progress overnight (paused mid-run at Ross's
request) -- NOT the stale 2026-08-12 file cited elsewhere as pending
correction. This script always reads whatever file currently exists at the
configured path and discloses its mtime at runtime; it does not assume any
particular vintage.

Verified against synthetic ground truth first:
debug/_verify_crisis_regime_correlation_diagnostic.py.

Usage:
    python research/crisis_regime_correlation_diagnostic.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import macro
from research.wrds_deep_history_episodic_scan import episodic_bhfdr_confirm
from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TIER3_WINDOWS_PATH = os.path.join(_ROOT, "output", "research",
                                    "wrds_deep_history_episodic_scan_tier3_windows.parquet")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

log = logging.getLogger("crisis_regime_correlation_diagnostic")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_crisis_regime_correlation_diagnostic.log"),
        mode="w", encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def load_tier3_windows(path: str = _TIER3_WINDOWS_PATH) -> pd.DataFrame:
    """Loads the flat (pair, window) rows, discloses the file's own mtime so
    a stale (pre-universe-fix) file is visible in the run log, not hidden."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} does not exist -- run research/wrds_deep_history_episodic_scan.py "
            f"first (Tier 3 writes this file)."
        )
    df = pd.read_parquet(path)
    mtime = pd.Timestamp(os.path.getmtime(path), unit="s")
    log.info(f"Loaded {len(df)} (pair, window) rows from "
             f"wrds_deep_history_episodic_scan_tier3_windows.parquet (file mtime: {mtime})")
    return df


def build_vix_regime_lookup() -> pd.Series:
    """Real production VIX regime classification (macro.py, already
    config-driven, not reinvented), indexed by NYSE trading date."""
    result = macro.build(series=["VIXCLS"])
    if "vix_regime" not in result.data.columns:
        raise RuntimeError("macro.build() did not produce a vix_regime column -- "
                            "VIXCLS fetch/classification failed, cannot proceed.")
    return result.data["vix_regime"]


def _nearest_regime(vix_regime: pd.Series, date: pd.Timestamp) -> "str | float":
    """Looks up the VIX regime as of `date`, using the most recent available
    trading-date VIX value ON OR BEFORE `date` (never a later one -- this is
    the point-in-time-safety guarantee: a pair's regime label never uses
    information from after its own first-qualifying window)."""
    eligible = vix_regime.loc[vix_regime.index <= date]
    if eligible.empty:
        return np.nan
    return eligible.iloc[-1]


def build_pair_level_table(windows_df: pd.DataFrame, vix_regime: pd.Series, alpha: float) -> pd.DataFrame:
    """One row per pair: first_window_end_date, its VIX regime, whether the
    pair was ever episodically BH-FDR-confirmed, its episodic_fraction_fdr
    (fraction of ITS OWN tested windows FDR-rejected), and whether it
    reappears as a candidate in any LATER window classified as a DIFFERENT
    (non-crisis) regime than its first window.

    VECTORIZED (2026-09-02, after a live run at Tier 3's real scale -- 5,003,637
    (pair, window) rows -- took 10+ minutes with no OOM risk but pure wasted
    wall-clock): the original version called `_nearest_regime` (a pandas
    boolean-mask filter + `.iloc[-1]`, effectively an O(len(vix_regime)) linear
    scan) once per row inside a Python-level `groupby` loop -- roughly 5M
    individual pandas calls, each with real per-call overhead, for a
    fundamentally as-of/backward-merge operation pandas already has a
    vectorized primitive for. Rewritten as ONE `pd.merge_asof` (direction=
    "backward", the same semantics as `_nearest_regime`'s "most recent value
    ON OR BEFORE date, else NaN") assigning a regime to every row in a single
    vectorized pass, then `groupby(...).transform`/`.first`/`.size`/boolean
    `.any()` for the rest -- no Python-level per-row or per-group loop
    remains. `_nearest_regime` itself is kept (still exercised directly by
    debug/_verify_crisis_regime_correlation_diagnostic.py's PIT-safety checks,
    which test it as a unit in isolation, not through this function) but is
    no longer called from here."""
    rows = windows_df.to_dict("records")
    confirmed = episodic_bhfdr_confirm(rows, alpha, min_windows_confirmed=1)
    confirmed_by_key = {frozenset((c["symbol_a"], c["symbol_b"])): c for c in confirmed}

    regime_lookup = vix_regime.sort_index().rename("regime").reset_index()
    date_col = regime_lookup.columns[0]  # whatever macro.build() named its DatetimeIndex
    merged = pd.merge_asof(
        windows_df.sort_values("window_end_date"), regime_lookup,
        left_on="window_end_date", right_on=date_col, direction="backward",
    ).sort_values(["symbol_a", "symbol_b", "window_end_date"])

    grp = merged.groupby(["symbol_a", "symbol_b"], sort=False)
    is_first_row = ~merged.duplicated(subset=["symbol_a", "symbol_b"], keep="first")
    first_regime_bc = grp["regime"].transform("first")
    diff_regime_later = (~is_first_row) & merged["regime"].notna() & (merged["regime"] != first_regime_bc)
    reappear = diff_regime_later.groupby([merged["symbol_a"], merged["symbol_b"]], sort=False).any()

    pair_table = grp.agg(
        first_window_end_date=("window_end_date", "first"),
        first_regime=("regime", "first"),
        n_windows_tested=("window_end_date", "size"),
    ).reset_index()
    pair_table = pair_table.merge(
        reappear.rename("reappears_in_different_regime").reset_index(), on=["symbol_a", "symbol_b"]
    )
    keys = list(zip(pair_table["symbol_a"], pair_table["symbol_b"]))
    confirmed_rows = [confirmed_by_key.get(frozenset(k)) for k in keys]
    pair_table["confirmed"] = [c is not None for c in confirmed_rows]
    pair_table["episodic_fraction_fdr"] = [
        c["episodic_fraction_fdr"] if c is not None else 0.0 for c in confirmed_rows
    ]
    return pair_table


def summarize(pair_table: pd.DataFrame) -> dict:
    """The three pre-registered comparisons, crisis vs. calm specifically
    (the two extremes) plus the full 4-way regime breakdown for completeness."""
    summary = {}

    by_regime = pair_table.groupby("first_regime").agg(
        n_pairs=("confirmed", "size"),
        n_confirmed=("confirmed", "sum"),
        confirmation_rate=("confirmed", "mean"),
        mean_episodic_fraction_fdr=("episodic_fraction_fdr", "mean"),
        reappearance_rate=("reappears_in_different_regime", "mean"),
    ).reset_index()
    summary["by_regime_table"] = by_regime

    crisis = pair_table[pair_table["first_regime"] == "crisis"]
    calm = pair_table[pair_table["first_regime"] == "calm"]
    if len(crisis) > 0 and len(calm) > 0:
        # Two-proportion z-test, confirmation rate: crisis-first vs calm-first.
        n1, n2 = len(crisis), len(calm)
        x1, x2 = crisis["confirmed"].sum(), calm["confirmed"].sum()
        p_pool = (x1 + x2) / (n1 + n2)
        se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if p_pool not in (0, 1) else np.nan
        z = (x1 / n1 - x2 / n2) / se if se and np.isfinite(se) and se > 0 else np.nan
        p_value = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else np.nan
        summary["crisis_vs_calm_confirmation_rate"] = {
            "crisis_n": int(n1), "crisis_confirmed": int(x1), "crisis_rate": float(x1 / n1),
            "calm_n": int(n2), "calm_confirmed": int(x2), "calm_rate": float(x2 / n2),
            "z_stat": float(z) if np.isfinite(z) else None,
            "p_value": float(p_value) if np.isfinite(p_value) else None,
        }
        # Two-proportion z-test, reappearance rate: crisis-first vs calm-first (2026-09-02,
        # added alongside the episodic_fraction_fdr test below -- both were previously
        # descriptive-only, means with no test statistic, while the confirmation-rate
        # comparison above already had one. Same test as confirmation rate, same formula,
        # just a different binary outcome column.
        xr1 = int(crisis["reappears_in_different_regime"].sum())
        xr2 = int(calm["reappears_in_different_regime"].sum())
        pr_pool = (xr1 + xr2) / (n1 + n2)
        se_r = np.sqrt(pr_pool * (1 - pr_pool) * (1 / n1 + 1 / n2)) if pr_pool not in (0, 1) else np.nan
        z_r = (xr1 / n1 - xr2 / n2) / se_r if se_r and np.isfinite(se_r) and se_r > 0 else np.nan
        p_r = 2 * (1 - stats.norm.cdf(abs(z_r))) if np.isfinite(z_r) else np.nan
        summary["crisis_vs_calm_reappearance_rate"] = {
            "crisis_reappearance_rate": float(xr1 / n1), "calm_reappearance_rate": float(xr2 / n2),
            "z_stat": float(z_r) if np.isfinite(z_r) else None,
            "p_value": float(p_r) if np.isfinite(p_r) else None,
        }

        # Mann-Whitney U, episodic_fraction_fdr among CONFIRMED pairs only: a bounded [0,1]
        # fraction, not obviously normal (especially with min_windows_confirmed=1 meaning many
        # confirmed pairs sit near the low end), so a rank-based test is the right default over
        # Welch's t. Small-n caveat carried into the output directly, not hidden: crisis has far
        # fewer confirmed pairs than calm (29 vs 412 in the 2026-09-02 corrected-scale run).
        crisis_efd = crisis.loc[crisis["confirmed"], "episodic_fraction_fdr"]
        calm_efd = calm.loc[calm["confirmed"], "episodic_fraction_fdr"]
        if len(crisis_efd) >= 2 and len(calm_efd) >= 2:
            u_stat, u_p = stats.mannwhitneyu(crisis_efd, calm_efd, alternative="two-sided")
        else:
            u_stat, u_p = None, None
        summary["crisis_vs_calm_episodic_fraction_fdr"] = {
            "crisis_mean": float(crisis_efd.mean()) if len(crisis_efd) else None,
            "calm_mean": float(calm_efd.mean()) if len(calm_efd) else None,
            "crisis_n_confirmed": int(len(crisis_efd)), "calm_n_confirmed": int(len(calm_efd)),
            "mannwhitney_u": float(u_stat) if u_stat is not None else None,
            "p_value": float(u_p) if u_p is not None else None,
        }
    else:
        summary["crisis_vs_calm_confirmation_rate"] = None
        summary["crisis_vs_calm_reappearance_rate"] = None
        summary["crisis_vs_calm_episodic_fraction_fdr"] = None
        log.warning("Insufficient crisis or calm pairs for a direct comparison -- "
                    "reporting the full by-regime table only.")

    # Non-monotonicity disclosure (2026-09-02): the 4-way by-regime table does NOT show a clean
    # calm->normal->elevated->crisis dose-response gradient in confirmation_rate -- reported
    # directly here rather than left for a reader to notice only by inspecting the raw table,
    # so a "more VIX = more confirmation" overclaim never gets a chance to stand unchallenged.
    ordered = ["calm", "normal", "elevated", "crisis"]
    rates = by_regime.set_index("first_regime")["confirmation_rate"].reindex(ordered)
    is_monotonic = bool(rates.dropna().is_monotonic_increasing)
    summary["confirmation_rate_monotonic_across_regime_severity"] = is_monotonic
    if not is_monotonic:
        log.warning("Confirmation rate is NOT monotonically increasing across calm->normal->"
                    "elevated->crisis (%s) -- this is a crisis-extreme effect specifically, "
                    "not a general 'more stress = more confirmation' gradient. Do not report "
                    "it as a dose-response relationship.", rates.to_dict())

    return summary


def main():
    _setup_logging()
    log.info("=== crisis_regime_correlation_diagnostic.py: does a pair's first-qualifying-window "
             "VIX regime predict downstream cointegration confirmation? Pre-registered, "
             "reported regardless of direction. ===")

    windows_df = load_tier3_windows()
    vix_regime = build_vix_regime_lookup()
    log.info(f"VIX regime series loaded: {vix_regime.notna().sum()} labeled trading days, "
             f"range [{vix_regime.index.min().date()}, {vix_regime.index.max().date()}]")

    pair_table = build_pair_level_table(windows_df, vix_regime, Config.STATS.FDR_ALPHA)
    log.info(f"Built pair-level table: {len(pair_table)} unique pairs")

    summary = summarize(pair_table)
    log.info("\n" + summary["by_regime_table"].to_string(index=False))
    if summary["crisis_vs_calm_confirmation_rate"] is not None:
        log.info(f"Crisis vs. calm confirmation rate: {summary['crisis_vs_calm_confirmation_rate']}")
        log.info(f"Crisis vs. calm reappearance rate: {summary['crisis_vs_calm_reappearance_rate']}")
        log.info(f"Crisis vs. calm episodic_fraction_fdr: {summary['crisis_vs_calm_episodic_fraction_fdr']}")

    os.makedirs(_OUT_DIR, exist_ok=True)
    pair_table.to_parquet(os.path.join(_OUT_DIR, "crisis_regime_correlation_diagnostic_pairs.parquet"), index=False)
    summary["by_regime_table"].to_parquet(
        os.path.join(_OUT_DIR, "crisis_regime_correlation_diagnostic_summary.parquet"), index=False
    )
    log.info("Saved -> output/research/crisis_regime_correlation_diagnostic_{pairs,summary}.parquet")


if __name__ == "__main__":
    main()
