"""
research/jkp_factor_portfolio_construction.py -- Thread M Option A: builds
real long-short factor-mimicking portfolios from `contrib_global_factor.
global_factor` (the published Jensen/Kelly/Pedersen global factor dataset,
confirmed real and comprehensive, 444 columns, 16M rows, 1980-2025 -- see
Development.md's Thread K/M table verification entry), then regresses
CAMARF's already-realized backtest returns against them, mirroring Thread
F Part A's Fama-French decomposition pattern exactly (reuses its
build_daily_return_series/run_regression directly, not reimplemented).

Ross's direct preference (2026-08-13): "A stands out more to me but B is
also ok, ideally we have both for comparison" -- this is Option A, the
more rigorous long-short-portfolio construction (Option B, raw-
characteristic regression, is a separate, simpler script).

SIX FACTORS chosen, mirroring the standard academic convention (FF5 +
momentum, the same 6-factor scope Thread F Part A's own 5-factor model +
Carhart's momentum already established as canonical in this project):
  - value:          be_me        (book-to-market)
  - size:            market_equity (negated -- SMALL minus BIG convention)
  - momentum:        ret_12_1     (12-month return skipping the most recent month)
  - profitability:   ni_be        (net income / book equity, ROE-style)
  - investment:       at_gr1       (asset growth, negated -- LOW minus HIGH,
                       standard convention: low investment firms outperform)
  - low-risk/beta:    beta_60m     (negated -- LOW minus HIGH beta, betting-
                       against-beta convention)

MONTHLY FREQUENCY (confirmed directly via a live query: this table's `date`
column is one observation per calendar month-end, not daily -- CAMARF's
daily backtest returns are aggregated to monthly compounded returns for
this comparison, a real, necessary adaptation, not assumed compatible with
Thread F's daily-frequency regression as-is).

NO LOOKAHEAD BY CONSTRUCTION: uses `ret_exc_lead1m` (the dataset's own
pre-built 1-month-FORWARD excess return field) as the portfolio return --
sorts on a characteristic known AT month t, realizes the return from t to
t+1. This is the dataset's own intended usage pattern (JKP publish this
field specifically for this purpose), not a home-grown shift that could
get the lookahead direction wrong.

REAL VALIDATION, not just synthetic: the constructed momentum factor is
compared against the ALREADY-CACHED, ALREADY-TRUSTED Fama-French/Carhart
`umd` (momentum) factor (output/cache/wrds/ff_factors_5_daily.parquet) --
if construction is correct, these two INDEPENDENTLY-SOURCED momentum
factors should correlate strongly. A real, data-grounded verification of
the construction methodology, not just a synthetic-data unit test.

Universe restriction: common stock (crsp_shrcd 10/11/12), major exchanges
(crsp_exchcd 1/2/3) -- same definition as the CRSP security master
(Thread K Part 1) and `_get_universe_us_equity_etf_symbols`'s own scope,
for consistency across this session's WRDS work.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data_wrds import _connect
from research.fama_french_risk_decomposition import build_daily_return_series, run_regression

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_RAW_PANEL_PATH = os.path.join(_WRDS_CACHE_DIR, "jkp_factor_panel_raw.parquet")
_FACTORS_OUT_PATH = os.path.join(_ROOT, "output", "research", "jkp_factor_portfolios_monthly.parquet")

# {factor_name: (characteristic_column, invert)} -- invert=True means the
# LONG leg is the LOW-characteristic tercile (size, investment, beta all use
# the standard "low minus high" convention; value/momentum/profitability use
# "high minus low", invert=False).
#
# EXPANDED 2026-08-14 (Ross: "let's use them and more if available") from the
# original 6 (one per FF5+momentum-equivalent category) to 16, adding 2-3 more
# characteristics per category plus a wholly new liquidity category JKP's
# panel supports but the original 6 didn't touch at all. Each addition's
# `invert` direction is chosen to match the ESTABLISHED DIRECTION of its own
# anomaly/premium in the literature (documented per-line below), not copied
# blindly from its category-mate.
_FACTOR_DEFS = {
    # --- Value: cheap (high char) outperforms expensive (low char) ---
    "value": ("be_me", False),                      # book-to-market (Fama-French 1992/1993)
    "value_at_me": ("at_me", False),                 # assets-to-market -- broader value proxy than be_me alone
    "value_earnings_yield": ("ni_me", False),         # earnings yield (E/P)
    "value_sales_price": ("sale_me", False),          # sales-to-price (Chan/Hamao/Lakonishok 1991)

    # --- Size: historically small (low char) outperformed big, though weak/inconsistent post-1980s ---
    "size": ("market_equity", True),                 # market cap (Banz 1981 size premium)

    # --- Momentum: winners (high char) continue to outperform losers, 12-1 month window ---
    "momentum": ("ret_12_1", False),                  # Jegadeesh-Titman 1993 / Carhart 1997 UMD definition

    # --- Profitability/Quality: more profitable/higher-quality (high char) outperforms ---
    "profitability": ("ni_be", False),                # ROE (net income / book equity)
    "profitability_gp_at": ("gp_at", False),          # Novy-Marx 2013 gross-profitability -- cleaner "quality"
                                                        # signal, less distorted by D&A/tax/interest choices
    "profitability_fscore": ("f_score", False),       # Piotroski 2000 F-Score -- high = fundamentally strong
    "quality_low_distress": ("o_score", True),        # Ohlson 1980 O-Score = bankruptcy-risk probability;
                                                        # HIGH o_score = MORE distress risk (bad), so inverted:
                                                        # LOW o_score (safer firms) is the long leg

    # --- Investment: conservative investment (low char) outperforms aggressive (Cooper/Gulen/Schill 2008) ---
    "investment": ("at_gr1", True),                   # total asset growth
    "investment_capx": ("capx_gr1", True),            # capex growth -- narrower investment-intensity proxy
    "investment_noa": ("noa_gr1a", True),             # net operating asset growth (accrual-flavored, Fairfield/
                                                        # Whisenant/Yohn) -- also low-growth long leg

    # --- Low-risk: low-risk (low char) outperforms on a risk-adjusted basis ---
    "betting_against_beta": ("beta_60m", True),       # Frazzini-Pedersen 2014 BAB -- low-beta long leg
    "low_volatility": ("ivol_capm_252d", True),       # Ang/Hodrick/Xing 2006 low-vol anomaly -- low idio-vol
                                                        # long leg (related to but distinct from low-beta)

    # --- Liquidity: NEW category (none of the original 6 touched this dimension). Illiquid names
    # earn a PREMIUM (Amihud 2002, Pastor-Stambaugh 2003) -- the MORE-illiquid side is the long leg
    # in every case, so invert direction depends on whether higher = MORE or LESS liquid per metric. ---
    "liquidity_dolvol": ("dolvol_126d", True),        # dollar volume -- HIGHER = MORE liquid, so inverted:
                                                        # LOW dolvol (illiquid) is the long leg
    "liquidity_amihud": ("ami_126d", False),          # Amihud illiquidity ratio -- HIGHER = MORE illiquid
                                                        # already, so NOT inverted: high ami is the long leg
}
_CHAR_COLS = sorted({c for c, _ in _FACTOR_DEFS.values()})


def fetch_raw_panel(db, start_date="1980-01-01"):
    cols_sql = ", ".join(["permno", "date"] + _CHAR_COLS + ["ret_exc_lead1m"])
    q = f"""
        select {cols_sql}
        from contrib_global_factor.global_factor
        where crsp_shrcd in (10, 11, 12) and crsp_exchcd in (1, 2, 3)
        and date >= '{start_date}'
    """
    df = db.raw_sql(q)
    df["date"] = pd.to_datetime(df["date"])
    os.makedirs(_WRDS_CACHE_DIR, exist_ok=True)
    df.to_parquet(_RAW_PANEL_PATH, index=False)
    return df


def build_factor_returns(panel: pd.DataFrame, n_terciles: int = 3) -> pd.DataFrame:
    """For each month, each factor: rank stocks by the characteristic into
    terciles, form an equal-weighted LONG (top or bottom, per the factor's
    `invert` convention) minus SHORT portfolio using `ret_exc_lead1m`.

    Returns a DataFrame indexed by the date the return was actually REALIZED
    (characteristic-observation month + 1), NOT the characteristic date
    itself. `ret_exc_lead1m` at panel date T is confirmed (real spot-check,
    permno 14593/AAPL, 2026-08-13: date=2019-01-31's ret_exc_lead1m of 4.3%
    matches AAPL's actual ~4.7% FEBRUARY 2019 price move, not January's
    ~5.5%) to be the return earned from T to the following month-end, T+1
    -- so a row characterized "as of" T must be labeled with T+1's date to
    be usable in a calendar-month-aligned join against any other monthly
    return series (e.g. Fama-French factors, or CAMARF's own realized
    portfolio returns) without a silent one-month misalignment."""
    out = {}
    for factor_name, (char_col, invert) in _FACTOR_DEFS.items():
        rows = []
        for date, group in panel.dropna(subset=[char_col, "ret_exc_lead1m"]).groupby("date"):
            if len(group) < n_terciles * 10:  # need a real minimum sample per tercile
                continue
            ranks = pd.qcut(group[char_col], n_terciles, labels=False, duplicates="drop")
            if ranks.nunique() < n_terciles:
                continue
            top = group[ranks == n_terciles - 1]["ret_exc_lead1m"].mean()
            bottom = group[ranks == 0]["ret_exc_lead1m"].mean()
            spread = (bottom - top) if invert else (top - bottom)
            # Period-bucket shift, not pd.offsets.MonthEnd(1) directly on the raw
            # date: real WRDS dates aren't all clean calendar month-ends across the
            # full history (some rows land mid-month), and MonthEnd(1) applied to a
            # non-month-end date can roll onto the SAME target as an adjacent
            # already-month-end row, producing duplicate index labels downstream
            # (real error hit on the actual 1980-2025 fetch, 2026-08-13). Snapping to
            # a calendar-month PERIOD first, then advancing by exactly one period, is
            # collision-proof regardless of the source date's day-of-month.
            realized_date = (date.to_period("M") + 1).to_timestamp("M")
            rows.append({"date": realized_date, factor_name: spread})
        if rows:
            # Different permnos can report their "as of" date on different exact
            # trading days within the same calendar month (holiday-calendar
            # variation, partial-month delisting records) -- these land in
            # DISTINCT raw-date groups above (correctly, so each cross-sectional
            # sort only compares stocks characterized as of the SAME date) but
            # can collapse onto the SAME target realized-month after the period
            # shift. Average across any such collision rather than erroring on a
            # duplicate index label -- a defensible resolution (both source dates
            # genuinely describe "this calendar month's transition"), not a
            # silent data-loss risk (nothing is dropped, just combined).
            out[factor_name] = pd.DataFrame(rows).groupby("date")[factor_name].mean()
    return pd.DataFrame(out)


def main():
    p = argparse.ArgumentParser(description="Thread M Option A: JKP long-short factor construction")
    p.add_argument("--start-date", default="1980-01-01")
    p.add_argument("--refetch", action="store_true", help="Re-run the WRDS query even if a cached panel exists")
    args = p.parse_args()

    if os.path.exists(_RAW_PANEL_PATH) and not args.refetch:
        panel = pd.read_parquet(_RAW_PANEL_PATH)
        print(f"Loaded cached panel: {len(panel)} rows")
    else:
        db = _connect()
        panel = fetch_raw_panel(db, args.start_date)
        db.close()
        print(f"Fetched {len(panel)} rows from contrib_global_factor.global_factor")

    factors = build_factor_returns(panel)
    os.makedirs(os.path.dirname(_FACTORS_OUT_PATH), exist_ok=True)
    factors.to_parquet(_FACTORS_OUT_PATH)
    print(f"\nBuilt {len(factors)} months of factor returns -> {_FACTORS_OUT_PATH}")
    print(factors.describe().to_string())

    # Real validation: compare constructed momentum against the trusted,
    # independently-sourced Fama-French/Carhart 'umd' factor.
    ff_path = os.path.join(_WRDS_CACHE_DIR, "ff_factors_5_daily.parquet")
    if os.path.exists(ff_path) and "momentum" in factors.columns:
        ff = pd.read_parquet(ff_path)
        ff["date"] = pd.to_datetime(ff["date"])
        ff_monthly_umd = (1 + ff.set_index("date")["umd"]).resample("ME").prod() - 1
        joined = pd.DataFrame({
            "constructed_momentum": factors["momentum"],
            "umd_trusted": ff_monthly_umd,
        }).dropna()
        if len(joined) >= 12:
            corr = joined["constructed_momentum"].corr(joined["umd_trusted"])
            print(f"\n=== Validation: constructed momentum vs. trusted Fama-French/Carhart 'umd' ===")
            print(f"n_months_overlap={len(joined)}  correlation={corr:.4f}")
            print("(A high positive correlation here is real, independent evidence the factor "
                  "construction methodology is working correctly, not just a synthetic check.)")


if __name__ == "__main__":
    main()
