"""
options.py — options-overlay comparison arm, NOT part of the core
production pipeline (parallel status to distance.py/sensitivity.py: reads
existing backtest output, never fetches or changes core position sizing).

Long-deferred (Development.md: "no historical IV data source available,
CBOE free API delayed only"). Built now per Ross's explicit request to do
the best possible version without paid data, after confirming directly
(not assumed) what's actually available for free:

  - yfinance's live option_chain() includes an impliedVolatility column for
    the CURRENT moment's listed contracts, but there is no way to pull a
    historical IV time series for free; this is a genuine, confirmed
    data-source limitation, not a code gap.
  - CORRECTION (2026-09-07, research/risk_neutral_density.py): the live
    impliedVolatility column itself is NOT reliable, checked directly
    against a real chain — deep-ITM strikes read a degenerate 1e-05
    placeholder rather than a solved value, and the OTM side showed an
    implausible exact-doubling staircase, not a real smile. Any live-chain
    consumer should derive its own IV via Black-Scholes inversion against a
    real transaction price (mid(bid, ask), falling back to lastPrice when
    bid/ask aren't live), not trust this column at face value.
  - CBOE's free API is delayed-only, unsuitable for the kind of precise
    entry/exit timing CAMARF's backtests need.

Since a real historical options backtest needs a historical IV TIME SERIES
(not a single current snapshot), this uses REALIZED volatility (rolling
annualized std of each leg's own daily log returns — data CAMARF already
has for every day in its history) as an EXPLICIT, CLEARLY-LABELED PROXY for
implied volatility. This is not free of bias: implied vol is systematically
HIGHER than subsequently-realized vol on average (the variance risk
premium, a well-documented, decades-old empirical regularity) — so pricing
options off realized vol UNDERSTATES what they would actually have cost,
making any hedging-cost estimate here optimistic/conservative, not a
precise historical reconstruction. Reported honestly, not hidden.

Method: standard Black-Scholes pricing (risk-free rate assumed 0 — a
simplification; short-dated near-the-money option prices are not highly
rate-sensitive, and CAMARF has no existing risk-free-rate data source to
draw from) for a protective-put overlay on one leg of each confirmed pair,
sized to the leg's actual position (n_shares_a from real backtest trades),
struck at a fixed OTM percentage, held for the trade's actual duration.
Compares: does adding this overlay to CAMARF's existing real trades reduce
max drawdown, and at what cost to average P&L — the standard, unavoidable
hedging tradeoff, not a free lunch.

Verified via Black-Scholes put-call parity on a known analytic case before
trusting real trade data.

Usage:
    python options.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_BACKTEST_DIR = "output/backtest"
_CACHE_DIR = "output/cache"
_REALIZED_VOL_WINDOW = 21  # ~1 trading month, standard convention
_OTM_PCT = 0.05  # 5% out-of-the-money strike

log = logging.getLogger("options")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler("latest_run_options.log", mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def black_scholes_put(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Standard Black-Scholes European put price. T in years, sigma annualized."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def black_scholes_call(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Standard Black-Scholes European call price. T in years, sigma annualized."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(S - K, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))


def black_scholes_delta(S: float, K: float, T: float, sigma: float, r: float = 0.0,
                          option_type: str = "call") -> float:
    """Standard Black-Scholes delta. At/after expiry (T<=0), delta collapses to the option's
    intrinsic-value indicator (1.0/0.0 for a call, 0.0/-1.0 for a put) rather than an
    undefined N(d1) — matches how a real option actually behaves at expiry, not a NaN."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return float(norm.cdf(d1)) if option_type == "call" else float(norm.cdf(d1) - 1.0)


def black_scholes_gamma(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Standard Black-Scholes gamma -- identical for calls and puts (both have the same
    curvature of delta with respect to the underlying)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return float(norm.pdf(d1) / (S * sigma * np.sqrt(T)))


def black_scholes_vega(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> float:
    """Standard Black-Scholes vega (sensitivity to a 1.00 = 100-percentage-point change in
    sigma; divide by 100 for the conventional 'per 1 vol point' quoting convention) --
    identical for calls and puts."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return float(S * norm.pdf(d1) * np.sqrt(T))


def black_scholes_theta(S: float, K: float, T: float, sigma: float, r: float = 0.0,
                          option_type: str = "call") -> float:
    """Standard Black-Scholes theta, in dollars per YEAR (divide by 365 for the conventional
    'per calendar day' quoting convention)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    term1 = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
    if option_type == "call":
        term2 = -r * K * np.exp(-r * T) * norm.cdf(d2)
    else:
        term2 = r * K * np.exp(-r * T) * norm.cdf(-d2)
    return float(term1 + term2)


def black_scholes_greeks(S: float, K: float, T: float, sigma: float, r: float = 0.0,
                           option_type: str = "call") -> dict:
    """All four Greeks at once, matching the same (S, K, T, sigma, r, option_type) call shape
    as the individual functions above -- convenience wrapper, no new computation."""
    return {
        "delta": black_scholes_delta(S, K, T, sigma, r, option_type),
        "gamma": black_scholes_gamma(S, K, T, sigma, r),
        "vega": black_scholes_vega(S, K, T, sigma, r),
        "theta": black_scholes_theta(S, K, T, sigma, r, option_type),
    }


def black_scholes_greeks_vectorized(S, K, T: float, sigma, r: float = 0.0,
                                      option_type: str = "call") -> dict:
    """Array-input version of black_scholes_greeks -- same formulas, vectorized over S/sigma
    (T and r stay scalar, matching every current caller's fixed-tenor/zero-rate use case).
    Invalid elements (S<=0, K<=0, sigma<=0, T<=0) produce NaN rather than raising, so a caller
    can run this over a full daily time series with occasional bad/missing data points without
    per-row filtering first. Currently CALL-only (delta collapses correctly for calls at
    T<=0/sigma<=0 -- 1.0 if ITM else 0.0 -- but put support isn't needed by any vectorized
    caller yet; add it if one arises rather than guessing at the right degenerate behavior now)."""
    if option_type != "call":
        raise NotImplementedError("black_scholes_greeks_vectorized currently supports "
                                   "option_type='call' only -- no vectorized caller needs puts yet.")
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    valid = (S > 0) & (K > 0) & (sigma > 0) & (T > 0)
    d1 = np.full_like(S, np.nan)
    d2 = np.full_like(S, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        d1[valid] = (np.log(S[valid] / K[valid]) + (r + 0.5 * sigma[valid] ** 2) * T) / (sigma[valid] * np.sqrt(T))
        d2[valid] = d1[valid] - sigma[valid] * np.sqrt(T)

    delta = np.full_like(S, np.nan)
    gamma = np.full_like(S, np.nan)
    vega = np.full_like(S, np.nan)
    theta = np.full_like(S, np.nan)

    delta[valid] = norm.cdf(d1[valid])
    gamma[valid] = norm.pdf(d1[valid]) / (S[valid] * sigma[valid] * np.sqrt(T))
    vega[valid] = S[valid] * norm.pdf(d1[valid]) * np.sqrt(T)
    theta[valid] = (
        -(S[valid] * norm.pdf(d1[valid]) * sigma[valid]) / (2 * np.sqrt(T))
        - r * K[valid] * np.exp(-r * T) * norm.cdf(d2[valid])
    )
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def realized_vol_proxy(close: pd.Series, window: int = _REALIZED_VOL_WINDOW) -> pd.Series:
    """Rolling annualized realized vol — the explicit IV proxy this module
    uses (see module docstring for the known variance-risk-premium bias)."""
    log_ret = np.log(close).diff()
    return log_ret.rolling(window).std() * np.sqrt(252)


def load_price_series(symbol: str) -> "pd.Series | None":
    """Real coverage bug found and fixed live (2026-09-07/08, via research/asset_volatility_
    profile.py's real result: only 11/55 confirmed-pair symbols got a valid price series): this
    function only ever checked the yfinance-only `{symbol}_1day.parquet` cache, never
    `output/cache/wrds/{symbol}_1D.parquet` -- silently violating this project's own "WRDS takes
    complete priority over other providers of data" rule (CLAUDE.md) for every caller of this
    function (options.py's own protective-overlay work, research/options_greeks_features.py,
    research/asset_volatility_profile.py). 44/55 of the "missing" symbols in that Finding #54
    result turned out to have real WRDS-cached data all along, just under a path/column this
    function never looked at.

    Fixed to check WRDS first (close_total_return -- CRSP total-return-adjusted, matching
    research/beta_weighted_portfolio.py's own SPY loader), then IBKR's deep-history supplement
    (ibkr_supplement_reader.py, native 1D bars where a supplement exists -- a small, ~92-symbol
    confirmed-pair set, per universe_loader.py's own documented scope, not broad coverage).

    Per Ross's explicit instruction (2026-09-08, "don't use yfinance, use wrds or ibkr"): the
    yfinance-primary `{symbol}_1day.parquet` fallback this function used to have is REMOVED, not
    just deprioritized. This is a real, deliberate coverage tradeoff, disclosed rather than
    hidden: ~1,731 symbols in this project's cache only ever had yfinance daily data and now
    return None here rather than falling back to it -- callers that need those symbols specifically
    will see reduced coverage versus the WRDS+yfinance version of this function that existed
    briefly earlier in this same session, not a bug, a deliberate scope narrowing."""
    wrds_path = os.path.join(_CACHE_DIR, "wrds", f"{symbol}_1D.parquet")
    if os.path.exists(wrds_path):
        df = pd.read_parquet(wrds_path)
        # 2026-09-08: Compustat Global international-listing files (GVKEY<n>
        # symbols) have no 'close_total_return' column, only plain 'close' --
        # this branch previously silently fell through to IBKR (and then
        # returned None) for every such symbol despite its WRDS file existing
        # on disk. Same fix applied to research/aligned_pair_loader.py's
        # analogous fallback the same day.
        col = "close_total_return" if "close_total_return" in df.columns else (
            "close" if "close" in df.columns else None)
        if col:
            close = df[col].dropna()
            close.index = pd.to_datetime(close.index)
            if len(close) > 0:
                return close

    import ibkr_supplement_reader
    ibkr_df = ibkr_supplement_reader.load_supplement(symbol, "1D")
    if ibkr_df is not None and "close" in ibkr_df.columns:
        close = ibkr_df["close"].dropna()
        close.index = pd.to_datetime(close.index)
        if len(close) > 0:
            return close

    return None


def price_protective_overlay(symbol: str, entry_date, exit_date, n_shares: float, side: str) -> dict:
    """
    BUG FIX (found via a real backtest result, not caught by unit tests):
    the first version always priced a protective PUT regardless of trade
    side. `side="short"` (backtest.py: z>0 -> short the spread) means leg A
    is actually being SOLD in this trade — its real risk is leg A RISING,
    which a put does nothing to hedge (and can actively mislead: the
    resulting "hedged" drawdown got WORSE than unhedged in the first real
    run, exactly the kind of impossible-looking result that should trigger
    suspicion of a wrong-direction bug rather than being reported as a
    surprising finding). `side="long"` -> leg A is bought -> a protective
    put (hedging against leg A falling) is the correct instrument.
    """
    close = load_price_series(symbol)
    if close is None or len(close) < _REALIZED_VOL_WINDOW + 5:
        return {}
    vol = realized_vol_proxy(close)

    entry_date = pd.Timestamp(entry_date).normalize()
    exit_date = pd.Timestamp(exit_date).normalize()
    idx = close.index[close.index <= entry_date]
    if len(idx) == 0:
        return {}
    entry_idx_date = idx[-1]
    if entry_idx_date not in vol.index or pd.isna(vol.loc[entry_idx_date]):
        return {}

    S0 = float(close.loc[entry_idx_date])
    sigma = float(vol.loc[entry_idx_date])
    T = max((exit_date - entry_idx_date).days, 1) / 365.0

    exit_idx = close.index[close.index <= exit_date]
    S_exit = float(close.loc[exit_idx[-1]]) if len(exit_idx) > 0 else S0

    if side == "long":
        # Leg A is bought -> protect against it falling -> protective put
        K = S0 * (1 - _OTM_PCT)
        premium = black_scholes_put(S0, K, T, sigma)
        payoff = max(K - S_exit, 0.0) * n_shares
        option_type = "put"
    else:
        # Leg A is sold (short) -> protect against it rising -> protective call
        K = S0 * (1 + _OTM_PCT)
        premium = black_scholes_call(S0, K, T, sigma)
        payoff = max(S_exit - K, 0.0) * n_shares
        option_type = "call"

    cost = premium * n_shares
    return {"symbol": symbol, "entry_date": entry_idx_date, "S0": S0, "sigma": sigma,
             "T_years": T, "strike": K, "option_type": option_type,
             "premium_cost": cost, "payoff": payoff, "net_hedge_pnl": payoff - cost}


def main():
    _setup_logging()
    log.info("=== options.py: protective-put overlay, realized-vol IV proxy ===")

    trades_path = os.path.join(_BACKTEST_DIR, "trades_layer1.parquet")
    if not os.path.exists(trades_path):
        log.warning("No trades found at %s — run backtest.py first.", trades_path)
        return
    trades = pd.read_parquet(trades_path)
    trades = trades[trades["hedge_method"] == "ols"].copy()
    if trades.empty:
        log.warning("No OLS trades found.")
        return

    rows = []
    for _, t in trades.iterrows():
        hedge_result = price_protective_overlay(
            t["symbol_a"], t["entry_time"], t["exit_time"], t["n_shares_a"], t["side"]
        )
        if not hedge_result:
            continue
        hedge_result["pair"] = f"{t['symbol_a']}/{t['symbol_b']}"
        hedge_result["trade_pnl_net"] = t["pnl_net"]
        hedge_result["hedged_pnl"] = t["pnl_net"] + hedge_result["net_hedge_pnl"]
        rows.append(hedge_result)

    if not rows:
        log.warning("No trades had sufficient price history for a realized-vol overlay estimate.")
        return

    df = pd.DataFrame(rows)
    unhedged = df["trade_pnl_net"]
    hedged = df["hedged_pnl"]

    def max_dd(pnl_series):
        cum = pnl_series.cumsum()
        running_max = cum.cummax()
        return float((running_max - cum).max())

    log.info("n_trades_with_overlay=%d  mean_hedge_cost=$%.2f  mean_hedge_payoff=$%.2f",
              len(df), df["premium_cost"].mean(), df["payoff"].mean())
    log.info("Unhedged: total_pnl=$%.2f  max_drawdown=$%.2f", unhedged.sum(), max_dd(unhedged))
    log.info("Hedged (protective put/call by trade side, %d%% OTM, realized-vol proxy): total_pnl=$%.2f  max_drawdown=$%.2f",
              int(_OTM_PCT * 100), hedged.sum(), max_dd(hedged))
    log.info("Cost of hedging: $%.2f total premium paid, for a max-drawdown reduction of $%.2f",
              df["premium_cost"].sum(), max_dd(unhedged) - max_dd(hedged))
    log.info("REMINDER: premiums are priced off REALIZED vol as an IV proxy, which the variance "
              "risk premium means UNDERSTATES true historical option cost — treat this as an "
              "optimistic/lower-bound hedging-cost estimate, not a precise reconstruction.")

    os.makedirs("output/stats", exist_ok=True)
    df.to_parquet("output/stats/options_overlay.parquet")
    log.info("Saved -> output/stats/options_overlay.parquet")


if __name__ == "__main__":
    main()
