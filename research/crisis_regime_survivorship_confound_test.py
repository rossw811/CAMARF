"""
§5's survivorship-of-crisis-discovered-pairs confound — Tier A item #2 of
the 2026-09-08 caveat/limitation search. Real, disclosed scope limit
BEFORE running anything: this project's WRDS subscription only has a
point-in-time membership product for the S&P 500 layer (Finding #63's
already-established limit -- no equivalent exists for S&P 400/600 or the
broader merged universe), so this test can only measure the confound
among pairs where BOTH legs are trackable via
`sp500_membership_history.parquet` -- a real, honest subset of the full
638,095-pair §5 universe, not the whole thing. Reported as what it is:
a partial answer bounded by a real data-license limit, not a full
resolution of the confound.

Tests: among §5's crisis-regime-confirmed pairs (statistically-
significant reappearance), is confirmation more/less likely when at
least one leg has since been delisted from the S&P 500, vs. when both
legs are still current members? If genuinely NOT delisted pairs are
disproportionately represented among "confirmed" pairs, that's direct
evidence the diagnostic's own candidate generation (built from a
present-day symbol cache) systematically favors pairs that survived to
today -- the confound stated plainly, not glossed over.

D5 / R3.10 (Ross 2026-10-12, fixed 2026-10-17): the claim is about CRISIS-discovered pairs, but the test ran on every
regime (crisis-first pairs are ~1.8% of the universe, so an effect among them was diluted by the rest). The main row is
now first_regime == "crisis"; the all-regime row is kept as a labelled reference (the pre-D5 number). Each row also
carries Fisher's exact p and a small_count flag (min expected cell < 5), since crisis-first confirmations are few.
Still open: D6 / R3.11 (is_current = still in the S&P 500, not "survived"; exclusion survivorship invisible).
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

from pit_confirmation_vs_regime_interaction import two_proportion_test

_REGIME_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_correlation_diagnostic_pairs.parquet")
_MEMBERSHIP_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "sp500_membership_history.parquet")
_PERMNO_MAP_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "wrds_label_permno_final.parquet")  # 2026-10-12: content-verified map
_OUT_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_survivorship_confound_test.parquet")


def build_survival_lookup(membership_df: pd.DataFrame) -> dict:
    """permno -> True (currently an S&P 500 member, i.e. has at least one
    is_current=True spell) / False (every spell for this permno has
    ended -- delisted from the index, not necessarily delisted entirely
    as a company)."""
    return membership_df.groupby("permno")["is_current"].any().to_dict()


def add_survival_columns(regime_df: pd.DataFrame, permno_map: dict, survival_lookup: dict) -> pd.DataFrame:
    out = regime_df.copy()
    out["permno_a"] = out["symbol_a"].map(permno_map)
    out["permno_b"] = out["symbol_b"].map(permno_map)
    out["survived_a"] = out["permno_a"].map(survival_lookup)
    out["survived_b"] = out["permno_b"].map(survival_lookup)
    # Only pairs where BOTH legs are trackable in the S&P 500 point-in-time
    # membership history are usable -- everything else stays NaN/excluded,
    # not silently assumed "survived."
    out["both_trackable"] = out["survived_a"].notna() & out["survived_b"].notna()
    out["both_survived"] = out["survived_a"].fillna(False) & out["survived_b"].fillna(False)
    return out


def survivorship_test(joined: pd.DataFrame, regime=None) -> dict:
    """Confirmation rate, both legs survived vs at least one leg delisted, among both-trackable pairs; restricted to
    first_regime == regime (None = all regimes, the pre-D5 reference). Two-proportion z plus Fisher's exact test."""
    sub = joined[joined["both_trackable"]]
    if regime is not None:
        sub = sub[sub["first_regime"] == regime]
    r = two_proportion_test(sub.assign(pit_confirmed=sub["confirmed"]), "both_survived", True, False)
    table = np.array([[r["x_a"], r["n_a"] - r["x_a"]], [r["x_b"], r["n_b"] - r["x_b"]]])
    n = table.sum()
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / n if n else np.full((2, 2), np.nan)
    fisher_p = float(stats.fisher_exact(table)[1]) if (r["n_a"] and r["n_b"]) else float("nan")
    min_exp = float(np.nanmin(expected)) if n else float("nan")
    return {**r, "scope": regime if regime is not None else "all_regimes", "fisher_p": fisher_p,
            "min_expected": min_exp, "small_count": bool(min_exp < 5)}


def survivorship_test_stratified(joined: pd.DataFrame, regime=None) -> dict:
    """Comparison arm (review of N7, 2026-10-22): the pooled test is confounded by discovery year -- pairs first found
    recently are mostly both-current AND right-censored (few windows, no time to confirm). Mantel-Haenszel common odds
    ratio (survived vs delisted) stratified by the year of the pair's first window; strata without both groups or
    without any variation in the outcome carry no information and are dropped (counted). OR > 1 = survivors confirm
    more often within a year, the direction survivorship bias predicts."""
    from statsmodels.stats.contingency_tables import StratifiedTable
    sub = joined[joined["both_trackable"]]
    if regime is not None:
        sub = sub[sub["first_regime"] == regime]
    tabs, dropped = [], 0
    for _, g in sub.groupby(pd.to_datetime(sub["first_window_end_date"]).dt.year):
        s_ = g[g["both_survived"]]["confirmed"]
        d_ = g[~g["both_survived"]]["confirmed"]
        t = np.array([[s_.sum(), len(s_) - s_.sum()], [d_.sum(), len(d_) - d_.sum()]], dtype=float)
        if len(s_) == 0 or len(d_) == 0 or t[:, 0].sum() == 0 or t[:, 1].sum() == 0:
            dropped += 1
            continue
        tabs.append(t)
    out = {"scope": regime if regime is not None else "all_regimes", "n_strata": len(tabs), "n_strata_dropped": dropped,
           "mh_or": np.nan, "mh_ci_lo": np.nan, "mh_ci_hi": np.nan, "mh_p": np.nan,
           "n_events": int(sum(t[:, 0].sum() for t in tabs))}
    if tabs:
        st_ = StratifiedTable(tabs)
        lo, hi = st_.oddsratio_pooled_confint()
        out.update(mh_or=float(st_.oddsratio_pooled), mh_ci_lo=float(lo), mh_ci_hi=float(hi),
                   mh_p=float(st_.test_null_odds().pvalue))
    return out


def main():
    if not (os.path.exists(_REGIME_PATH) and os.path.exists(_MEMBERSHIP_PATH) and os.path.exists(_PERMNO_MAP_PATH)):
        print("ERROR: missing input(s).")
        return

    regime_df = pd.read_parquet(_REGIME_PATH)
    membership_df = pd.read_parquet(_MEMBERSHIP_PATH)
    from data_wrds import label_permno_map
    _m = label_permno_map(_PERMNO_MAP_PATH)
    permno_map_df = pd.DataFrame({"symbol": list(_m), "permno": list(_m.values())})
    permno_map = dict(zip(permno_map_df["symbol"], permno_map_df["permno"]))
    survival_lookup = build_survival_lookup(membership_df)

    joined = add_survival_columns(regime_df, permno_map, survival_lookup)
    n_trackable = int(joined["both_trackable"].sum())
    print(f"§5 universe: {len(joined)} pairs. Both legs S&P-500-trackable: {n_trackable} "
          f"({n_trackable/len(joined):.2%}) -- the real, disclosed scope limit this test can "
          f"measure within.")

    rows = []
    for regime, label in (("crisis", "MAIN (crisis-first pairs, the claim's population)"),
                          (None, "reference (all regimes, the pre-D5 number)")):
        r = survivorship_test(joined, regime=regime)
        rows.append(r)
        print(f"\n{label}: n = {r['n_a'] + r['n_b']}")
        if r["n_a"] == 0 or r["n_b"] == 0:
            print("  one group empty -- no test")
            continue
        print(f"  P(confirmed | both legs survived to present): {r['x_a']}/{r['n_a']} = {r['p_a']:.4%}")
        print(f"  P(confirmed | at least one leg delisted):      {r['x_b']}/{r['n_b']} = {r['p_b']:.4%}")
        print(f"  z={r['z']:.4f}, p={r['p_value']:.4f}; Fisher exact p={r['fisher_p']:.4f}; "
              f"min expected cell {r['min_expected']:.2f}" + ("  [SMALL COUNTS: read the exact p]" if r["small_count"] else ""))

    for regime in ("crisis", None):
        m = survivorship_test_stratified(joined, regime=regime)
        rows[0 if regime == "crisis" else 1].update({k: v for k, v in m.items() if k != "scope"})
        print(f"\nyear-stratified MH ({m['scope']}): OR {m['mh_or']:.3f} [{m['mh_ci_lo']:.3f}, {m['mh_ci_hi']:.3f}], "
              f"p {m['mh_p']:.2e}; {m['n_strata']} year strata ({m['n_strata_dropped']} uninformative dropped), "
              f"{m['n_events']} confirmations")
    pd.DataFrame([{**r, "n_total_universe": len(joined), "n_trackable": n_trackable} for r in rows]).to_parquet(_OUT_PATH)
    print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
