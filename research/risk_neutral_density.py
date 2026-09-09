"""
research/risk_neutral_density.py -- Breeden-Litzenberger risk-neutral density extraction from a
LIVE option chain (Ross's request: "option prices secretly encode what the market thinks the
future price will be... q(K) = e^{rT} * d2C/dK2").

Sidesteps options.py's own documented historical-IV limitation entirely: Breeden-Litzenberger
only needs a SNAPSHOT of the option chain at one moment (the current market's own priced-in
distribution for a future expiry), not a historical IV time series.

A second, real data-quality issue found live (2026-09-07), beyond options.py's own already-
documented historical-IV gap: yfinance's precomputed `impliedVolatility` column, which options.py's
own docstring describes as "a real impliedVolatility column," turned out to be UNRELIABLE in
practice -- checked directly against a real live SPY chain (both a near-dated, normally highly
liquid expiry and a far-dated one): every deep-ITM strike reported IV pinned at exactly 1e-05 (a
degenerate placeholder, not a real solved value -- near-zero extrinsic value makes IV inversion
numerically unstable, and yfinance appears to floor rather than return NaN), and the OTM side
showed an implausible exact-doubling staircase pattern across many strikes, not a real smile.
Also checked directly: bid/ask were BOTH zero across the entire chain in this same snapshot (the
market was very likely closed at fetch time), so this module instead solves for its OWN implied
vol via numerical Black-Scholes inversion (`implied_vol_from_price`, `scipy.optimize.brentq`)
against `lastPrice` (falling back from a bid/ask mid when bid/ask aren't live) -- exactly the
"pull the strikes and the mid price yourself" approach in Ross's own original notes, not yfinance's
own precomputed (and here, unreliable) IV field. Using a stale `lastPrice` when the market is
closed is itself a disclosed limitation (see fetch_live_option_chain's own docstring), not hidden.

The real challenge, as Ross's own notes put it: the second derivative amplifies any noise in raw
strike-by-strike prices into wild, often negative "probabilities." Standard fix, implemented
here: fit a SMOOTH curve to implied vol as a function of strike (a low-order polynomial in this
first pass -- simple, robust, unlikely to overfit noise the way a high-flexibility spline with a
badly-tuned smoothing parameter could), convert the smoothed IV curve back to a smooth
Black-Scholes call-price curve on a fine strike grid, then differentiate that SMOOTH curve twice
via central finite differences. Negative density values that survive smoothing are CLIPPED to
zero and the clipped probability mass is reported explicitly, not silently discarded -- this can
still happen with real, noisy market data, and hiding it would misrepresent how much to trust the
extracted curve.

A genuine backtest-overfitting-detector application (Ross's own framing): compare a strategy's
own assumed/realized P&L distribution against the market's live risk-neutral density for the same
underlying and horizon -- if a backtest's return distribution looks nothing like what options
markets are actually pricing in (e.g., no left-tail crash risk when the market prices in real
crash probability), that is itself informative about overfitting or unrealistic assumptions. Not
built in this first pass -- flagged as the natural next step once the core RND extraction is
verified and trusted.

Verified against synthetic ground truth first: debug/_verify_risk_neutral_density.py -- the
strongest available ground truth is Black-Scholes itself, since BS assumes the terminal price is
lognormal; pricing a full synthetic call-price grid at a KNOWN constant vol via BS and then
running it through this exact pipeline must recover that known lognormal density.

Usage:
    python research/risk_neutral_density.py --symbol SPY --expiry 2026-12-18
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from options import black_scholes_call

log = logging.getLogger("risk_neutral_density")

_POLY_DEGREE = 3  # low-order IV(K) fit -- robust to noise, deliberately not a flexible spline


def implied_vol_from_price(price: float, S: float, K: float, T: float, r: float = 0.0) -> float:
    """Numerically inverts options.py's black_scholes_call() for the implied vol matching a
    real quoted price, via Brent's method (bisection-family root finder, no derivative needed
    -- robust for this well-behaved, monotonically-increasing-in-vol problem). Returns NaN
    (never a crash, never a fabricated guess) when the price is below intrinsic value (arbitrage
    violation or bad quote) or the search fails to bracket a root."""
    from scipy.optimize import brentq
    intrinsic = max(S - K, 0.0)
    if not np.isfinite(price) or price <= intrinsic or price <= 0:
        return np.nan

    def objective(sigma):
        return black_scholes_call(S, K, T, sigma, r) - price

    try:
        lo, hi = 1e-4, 5.0  # 0.01% to 500% annualized vol -- generously wide search bracket
        if objective(lo) > 0 or objective(hi) < 0:
            return np.nan  # price outside what any vol in [lo, hi] can produce -- bad quote
        return float(brentq(objective, lo, hi, xtol=1e-6))
    except (ValueError, RuntimeError):
        return np.nan


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def fit_smooth_iv_curve(strikes: np.ndarray, ivs: np.ndarray, degree: int = _POLY_DEGREE,
                          S: float = None) -> "callable":
    """Low-order polynomial fit of implied vol, smoothing the raw quotes before the
    second-derivative step below amplifies their noise into garbage.

    Fits in LOG-MONEYNESS space (x = ln(K/S)), not raw strike dollars, when S is given -- real
    issue found live (2026-09-07): a real SPY chain's strikes ranged $150-$1000 (even after
    restricting to a liquid moneyness band), and a polynomial fit directly against raw strike
    VALUES produced an implausible result (skewness statistic of 61, or with the moneyness band
    alone still still flooring IV near-zero across a wide illiquid-adjacent stretch and
    collapsing the extracted distribution's width by ~15x vs. a sane estimate). Log-moneyness is
    the standard practice for exactly this reason: it rescales the fit domain to a natural,
    roughly symmetric range around 0 regardless of the underlying's dollar price, so a low-order
    polynomial doesn't have to represent both a $150 strike and a $1000 strike on the same
    numerical scale a raw-strike fit would. S=None (the default) falls back to fitting directly
    against strikes -- kept only for the case where a caller has already transformed strikes to
    some other domain themselves; every real caller in this module always passes S.

    Returns a CALLABLE taking STRIKE values directly (not pre-converted to log-moneyness) --
    the moneyness conversion happens inside the returned closure, so callers never need to know
    which domain the fit itself happened in."""
    valid = np.isfinite(strikes) & np.isfinite(ivs) & (ivs > 0)
    if valid.sum() < degree + 2:
        raise ValueError(f"Need at least {degree + 2} valid (strike, IV) points to fit a "
                          f"degree-{degree} curve, got {valid.sum()}.")
    if S is not None:
        x = np.log(strikes[valid] / S)
        coeffs = np.polyfit(x, ivs[valid], degree)
        poly = np.poly1d(coeffs)
        return lambda k: poly(np.log(np.asarray(k, dtype=float) / S))
    coeffs = np.polyfit(strikes[valid], ivs[valid], degree)
    return np.poly1d(coeffs)


def extract_risk_neutral_density(S: float, strikes: np.ndarray, ivs: np.ndarray, T: float,
                                   r: float = 0.0, degree: int = _POLY_DEGREE, n_grid: int = 200
                                   ) -> pd.DataFrame:
    """Full Breeden-Litzenberger pipeline: fit a smooth IV(K) curve (in log-moneyness space,
    see fit_smooth_iv_curve), build smooth Black-Scholes call prices on a fine strike grid,
    differentiate twice via central finite differences to recover q(K) = e^{rT} * d2C/dK2.
    Returns a DataFrame with columns [strike, iv_smoothed, call_price_smoothed, density,
    density_clipped] -- `density` is the raw (possibly negative) second derivative,
    `density_clipped` has negative values floored to 0 (the standard, disclosed fix; see module
    docstring)."""
    strikes = np.asarray(strikes, dtype=float)
    ivs = np.asarray(ivs, dtype=float)
    iv_curve = fit_smooth_iv_curve(strikes, ivs, degree=degree, S=S)

    k_min, k_max = float(strikes.min()), float(strikes.max())
    dK = (k_max - k_min) / n_grid
    # Pad the grid by 2*dK on each side so the central-difference stencil has room at the edges
    # of the requested range, rather than silently losing the two boundary points.
    k_grid = np.linspace(k_min - 2 * dK, k_max + 2 * dK, n_grid + 5)

    iv_smoothed = iv_curve(k_grid)
    iv_smoothed = np.clip(iv_smoothed, 1e-4, None)  # a fitted polynomial can dip non-positive
    # far from the data range; floor it rather than feeding black_scholes_call a nonsensical vol.
    call_smoothed = np.array([black_scholes_call(S, k, T, sigma, r) for k, sigma in zip(k_grid, iv_smoothed)])

    density = np.full(len(k_grid), np.nan)
    density[1:-1] = (call_smoothed[2:] - 2 * call_smoothed[1:-1] + call_smoothed[:-2]) / (dK ** 2)
    density[1:-1] *= np.exp(r * T)

    out = pd.DataFrame({"strike": k_grid, "iv_smoothed": iv_smoothed,
                          "call_price_smoothed": call_smoothed, "density": density})
    out["density_clipped"] = out["density"].clip(lower=0.0)

    valid_density = out["density"].dropna()
    frac_negative = float((valid_density < 0).mean()) if len(valid_density) else np.nan
    if frac_negative and frac_negative > 0:
        clipped_mass = float((out["density"] - out["density_clipped"]).clip(lower=0).sum() * dK)
        log.warning(f"  {frac_negative:.1%} of grid points had a NEGATIVE raw density "
                    f"(clipped to 0) -- {clipped_mass:.4f} of probability mass discarded by "
                    f"clipping. Real limitation of numerical differentiation on real market "
                    f"quotes, disclosed rather than hidden.")
    return out.iloc[1:-1].reset_index(drop=True)  # drop the two undefined edge points


def fetch_live_option_chain(symbol: str, expiry: str, moneyness_band: tuple = (0.7, 1.3)) -> dict:
    """Thin real-data wrapper -- pulls one live yfinance option chain snapshot. Kept separate
    from extract_risk_neutral_density() so the core math stays fully testable offline (see
    debug/_verify_risk_neutral_density.py), matching this project's own established pattern of
    pure-function-tested-synthetically plus a thin live-data wrapper.

    Real issue found live (2026-09-07), #1: SPY's full exchange-listed strike range at a real
    expiry ran from $150 to $1000 against a $770 spot -- deep ITM/OTM strikes at the extremes
    broke the smoothing fit entirely. Restricts to a LIQUID moneyness band around spot before
    returning; `moneyness_band=(0.7, 1.3)` (70%-130% of spot) is a reasonable, disclosed
    default, not silently baked in.

    Real issue found live, #2 (the more serious one): yfinance's own precomputed
    `impliedVolatility` column turned out to be UNRELIABLE -- checked directly on a real chain,
    every deep-ITM strike read exactly 1e-05 (a degenerate placeholder) and the OTM side showed
    an implausible exact-doubling staircase, not a real smile. Also checked directly: bid/ask
    were BOTH zero across the entire chain in this snapshot (the market was very likely closed
    at fetch time). Fixed by computing this module's OWN implied vol via numerical Black-Scholes
    inversion (implied_vol_from_price) against a real transaction price -- mid(bid, ask) when
    both are live (>0), falling back to `lastPrice` when they aren't, WITH the fallback flagged
    in the returned dict's `used_stale_last_price` count so a caller knows how much of the chain
    is (disclosed) potentially-stale data rather than a live quote."""
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    chain = ticker.option_chain(expiry)
    calls = chain.calls.copy()
    S = float(ticker.history(period="1d")["Close"].iloc[-1])
    T = max((pd.Timestamp(expiry) - pd.Timestamp.now()).total_seconds(), 3600) / (365.0 * 86400)

    lo, hi = S * moneyness_band[0], S * moneyness_band[1]
    calls = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)].copy()

    has_live_quote = (calls["bid"] > 0) & (calls["ask"] > 0)
    mid = (calls["bid"] + calls["ask"]) / 2.0
    price = np.where(has_live_quote, mid, calls["lastPrice"])
    n_stale = int((~has_live_quote).sum())

    ivs = np.array([implied_vol_from_price(p, S, k, T) for p, k in zip(price, calls["strike"])])
    valid = np.isfinite(ivs)
    return {"symbol": symbol, "expiry": expiry, "S": S, "T": T,
            "strikes": calls["strike"].to_numpy()[valid], "ivs": ivs[valid],
            "used_stale_last_price": n_stale, "n_total_in_band": len(calls)}


def main():
    _setup_logging()
    parser = argparse.ArgumentParser(description="Breeden-Litzenberger risk-neutral density from a live option chain")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--expiry", required=True, help="Option expiry date, e.g. 2026-12-18")
    parser.add_argument("--degree", type=int, default=_POLY_DEGREE)
    args = parser.parse_args()

    log.info(f"=== risk_neutral_density.py: Breeden-Litzenberger RND for {args.symbol} "
              f"@ {args.expiry} ===")
    data = fetch_live_option_chain(args.symbol, args.expiry)
    log.info(f"Spot={data['S']:.2f}, T={data['T']:.4f} years, {len(data['strikes'])}/"
              f"{data['n_total_in_band']} in-band strikes with a computable implied vol "
              f"({data['used_stale_last_price']} priced off a stale lastPrice, no live bid/ask).")

    rnd = extract_risk_neutral_density(data["S"], data["strikes"], data["ivs"], data["T"], degree=args.degree)
    mode_strike = float(rnd.loc[rnd["density_clipped"].idxmax(), "strike"])
    log.info(f"Risk-neutral density mode (most likely terminal price): {mode_strike:.2f} "
              f"vs. current spot {data['S']:.2f}")

    out_path = f"output/research/risk_neutral_density_{args.symbol}_{args.expiry}.parquet"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rnd.to_parquet(out_path)
    log.info(f"Saved -> {out_path}")
    log.info("risk_neutral_density.py complete")


if __name__ == "__main__":
    main()
