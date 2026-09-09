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
"""
import os
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "research"))

from pit_confirmation_vs_regime_interaction import two_proportion_test

_REGIME_PATH = os.path.join(_ROOT, "output", "research", "crisis_regime_correlation_diagnostic_pairs.parquet")
_MEMBERSHIP_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "sp500_membership_history.parquet")
_PERMNO_MAP_PATH = os.path.join(_ROOT, "output", "cache", "wrds", "symbol_permno_map.parquet")
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


def main():
    if not (os.path.exists(_REGIME_PATH) and os.path.exists(_MEMBERSHIP_PATH) and os.path.exists(_PERMNO_MAP_PATH)):
        print("ERROR: missing input(s).")
        return

    regime_df = pd.read_parquet(_REGIME_PATH)
    membership_df = pd.read_parquet(_MEMBERSHIP_PATH)
    permno_map_df = pd.read_parquet(_PERMNO_MAP_PATH)
    permno_map = dict(zip(permno_map_df["symbol"], permno_map_df["permno"]))
    survival_lookup = build_survival_lookup(membership_df)

    joined = add_survival_columns(regime_df, permno_map, survival_lookup)
    n_trackable = int(joined["both_trackable"].sum())
    print(f"§5 universe: {len(joined)} pairs. Both legs S&P-500-trackable: {n_trackable} "
          f"({n_trackable/len(joined):.2%}) -- the real, disclosed scope limit this test can "
          f"measure within.")

    trackable = joined[joined["both_trackable"]]
    if len(trackable) < 50:
        print(f"Only {len(trackable)} trackable pairs -- too few for a meaningful test. "
              f"Reporting raw counts only, no z-test.")
        print(trackable.groupby("both_survived")["confirmed"].agg(["sum", "count"]))
        return

    r = two_proportion_test(
        trackable.assign(pit_confirmed=trackable["confirmed"]),
        "both_survived", True, False,
    )
    print(f"\nP(§5-confirmed | both legs survived to present): {r['x_a']}/{r['n_a']} = {r['p_a']:.4%}")
    print(f"P(§5-confirmed | at least one leg delisted):      {r['x_b']}/{r['n_b']} = {r['p_b']:.4%}")
    print(f"z={r['z']:.4f}, p={r['p_value']:.4f}")

    pd.DataFrame([{**r, "n_total_universe": len(joined), "n_trackable": n_trackable}]).to_parquet(_OUT_PATH)
    print(f"\nSaved to {_OUT_PATH}")


if __name__ == "__main__":
    main()
