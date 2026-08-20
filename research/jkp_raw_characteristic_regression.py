"""
research/jkp_raw_characteristic_regression.py -- Thread M Option B: simpler
raw-characteristic regression, built alongside Option A (jkp_factor_
portfolio_construction.py) per Ross's explicit request (2026-08-13):
"A stands out more to me but B is also ok, ideally we have both for
comparison."

METHODOLOGICAL CONTRAST WITH OPTION A (stated plainly, not glossed over):
Option A constructs published-methodology long-short FACTOR portfolios
(top-tercile minus bottom-tercile return spread, across the FULL market
cross-section each month) and regresses CAMARF's realized returns against
those factor RETURNS -- the standard academic approach (mirrors Fama-
French/Carhart exactly).

Option B instead uses the pair LEGS' OWN raw characteristic LEVELS
(be_me, market_equity, ret_12_1, ni_be, at_gr1, beta_60m -- as-of each
month, no cross-sectional sorting) directly as time-series regressors
against the portfolio's realized monthly returns. This asks a narrower,
less standard question: "does the portfolio's return covary with its own
time-varying exposure to these characteristics" -- NOT "does the
portfolio have loadings on the market's published risk factors." This is
explicitly the cheaper, less rigorous of the two options (see the Thread
M plan doc's own non-goals section) -- kept as a genuinely different,
independently-informative comparison, not a redundant re-run of Option A.

NO LOOKAHEAD: for a backtest holding a pair over [entry_date, exit_date],
only characteristic values dated STRICTLY BEFORE the return-realization
month are used (characteristics as of month t explain the return realized
FROM t to t+1, same forward-return convention as Option A's `ret_exc_
lead1m`, but applied here via an explicit t -> t+1 shift on raw levels
since this table's other columns are contemporaneous-as-of-date, not
pre-shifted).

Cheaper query than Option A by construction: restricted to the SPECIFIC
permnos appearing in CAMARF's own confirmed pairs (via the existing
symbol_permno_map.parquet), not the full ~16M-row market-wide panel.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from data_wrds import _connect, _OUT_DIR

_CHAR_COLS = ["be_me", "market_equity", "ret_12_1", "ni_be", "at_gr1", "beta_60m"]
_RAW_PANEL_PATH = os.path.join(_OUT_DIR, "jkp_raw_characteristics_pairlegs.parquet")


def fetch_pairleg_characteristics(db, permnos, start_date="1980-01-01"):
    cols_sql = ", ".join(["permno", "date"] + _CHAR_COLS)
    permno_list_sql = ", ".join(str(int(p)) for p in permnos)
    q = f"""
        select {cols_sql}
        from contrib_global_factor.global_factor
        where permno in ({permno_list_sql})
        and date >= '{start_date}'
    """
    df = db.raw_sql(q)
    df["date"] = pd.to_datetime(df["date"])
    os.makedirs(_OUT_DIR, exist_ok=True)
    df.to_parquet(_RAW_PANEL_PATH, index=False)
    return df


def build_portfolio_characteristic_exposure(panel: pd.DataFrame, leg_permnos: dict) -> pd.DataFrame:
    """leg_permnos: {pair_key: (permno_a, permno_b)}. For each pair and each
    month, average the two legs' raw characteristic values (equal-weighted,
    matching the equal-notional pairs-trade convention used elsewhere in
    this codebase). Returns one row per (pair_key, date)."""
    rows = []
    panel_indexed = panel.set_index(["permno", "date"])
    for pair_key, (permno_a, permno_b) in leg_permnos.items():
        dates_a = set(panel[panel["permno"] == permno_a]["date"])
        dates_b = set(panel[panel["permno"] == permno_b]["date"])
        for date in sorted(dates_a & dates_b):
            row_a = panel_indexed.loc[(permno_a, date)]
            row_b = panel_indexed.loc[(permno_b, date)]
            out = {"pair_key": pair_key, "date": date}
            for c in _CHAR_COLS:
                # Real bug hit on the actual run (2026-08-14): raw_sql() can return a
                # value as pandas nullable pd.NA (not always plain float NaN), and
                # np.nanmean()/np.isnan() choke on a RAW pd.NA inside their internal
                # `a != a` comparison (`TypeError: boolean value of NA is ambiguous`)
                # -- the SAME bug class already found and fixed 3 times elsewhere this
                # session (build_full_market_label_map, international_liquidity_
                # filter.py, here). Convert to a definite plain float FIRST via
                # pd.notna() (which DOES correctly detect pd.NA/NaN/None, unlike a raw
                # truthiness or numpy-internal check on the value itself), THEN do all
                # further math on plain floats only.
                va_raw, vb_raw = row_a[c], row_b[c]
                va = float(va_raw) if pd.notna(va_raw) else float("nan")
                vb = float(vb_raw) if pd.notna(vb_raw) else float("nan")
                out[c] = np.nanmean([va, vb]) if not (np.isnan(va) and np.isnan(vb)) else np.nan
            rows.append(out)
    return pd.DataFrame(rows)


def run_raw_characteristic_regression(monthly_portfolio_returns: pd.Series,
                                       exposure_df: pd.DataFrame) -> dict:
    """Regress monthly_portfolio_returns (indexed by month-end date) on the
    NEXT month's characteristic exposure shifted back one period -- i.e.
    exposure known at t explains the return realized t->t+1, mirroring
    Option A's ret_exc_lead1m forward-return convention without lookahead."""
    exposure_monthly = exposure_df.groupby("date")[_CHAR_COLS].mean().sort_index()
    exposure_shifted = exposure_monthly.shift(1)  # exposure as-of t explains return realized ending t+1
    exposure_shifted.index = exposure_shifted.index  # explicit no-op, documents intent
    aligned = pd.DataFrame({"portfolio_return": monthly_portfolio_returns}).join(
        exposure_shifted, how="inner"
    ).dropna()
    if len(aligned) < 12:
        return {"n_obs": len(aligned), "error": "insufficient overlapping months (<12)"}

    X = sm.add_constant(aligned[_CHAR_COLS])
    y = aligned["portfolio_return"]
    model = sm.OLS(y, X).fit()
    return {
        "n_obs": len(aligned),
        "alpha_monthly": model.params["const"],
        "alpha_annualized": model.params["const"] * 12,
        "alpha_tstat": model.tvalues["const"],
        "loadings": {c: model.params[c] for c in _CHAR_COLS},
        "loading_tstats": {c: model.tvalues[c] for c in _CHAR_COLS},
        "r_squared": model.rsquared,
    }


def main():
    p = argparse.ArgumentParser(description="Thread M Option B: raw JKP characteristic regression")
    p.add_argument("--refetch", action="store_true")
    args = p.parse_args()
    print("Option B is a library of reusable functions (fetch_pairleg_characteristics, "
          "build_portfolio_characteristic_exposure, run_raw_characteristic_regression) -- "
          "run against a real confirmed-pairs + realized-returns dataset via a driver script "
          "once the current Step 5 backtest arm results are available (see Thread M plan).")


if __name__ == "__main__":
    main()
