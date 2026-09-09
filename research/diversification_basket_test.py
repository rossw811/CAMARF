"""
research/diversification_basket_test.py -- Phase 4 (part A) of the discovery-event research
program (Ross: build a "diversification-basket signal" from currently-uncorrelated pairs, tested
with/without comparison arms against a correlated basket and a random control).

Uses Phase 1's `correlation_transitions.parquet` (research/correlation_transition_detector.py) to
find each pair's LATEST known state (coint vs not_coint) as of Tier 3's build cutoff. Extracts the
unique SYMBOLS involved in pairs whose latest state is "not_coint" (a "decoupled basket") vs
"coint" (a "coupled basket"), plus a random-symbol control basket, then tests the textbook
diversification claim directly on real daily returns: does an equal-weight basket of currently-
uncorrelated assets have LOWER realized portfolio volatility, relative to its members' own average
volatility, than a basket of currently-correlated assets or a random basket?

diversification_ratio = mean(individual asset vol) / basket (portfolio) vol -- a ratio > 1 means
the basket is less volatile than its average member, the classic quantification of a real
diversification benefit (Markowitz). A ratio near the random-control basket's own ratio would mean
"not_coint" status carries no ADDITIONAL diversification information beyond typical cross-sectional
diversification; a ratio meaningfully HIGHER than both other arms would be the real, useful signal.

Swept across basket size {10, 20, 30} as a with/without-style robustness comparison arm, per
Ross's own "figure out optimal figures" instruction, rather than one fixed basket size.

Verified against synthetic ground truth first: debug/_verify_diversification_basket_test.py.

Usage:
    python research/diversification_basket_test.py
"""
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("diversification_basket_test")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_TRANSITIONS_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "correlation_transitions.parquet")
_OUT_PATH = os.path.join(os.path.dirname(_ROOT), "output", "research", "diversification_basket_test.parquet")

BASKET_SIZES = [10, 20, 30]
_RNG_SEED = 42


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def latest_state_symbols(transitions: pd.DataFrame) -> dict:
    """Returns {state: sorted unique symbol list} for each pair's LATEST known state
    (coint/not_coint), derived by sorting on transition_date and taking each pair's last row --
    the same convention used throughout this project's discovery-event work."""
    latest = transitions.sort_values("transition_date").groupby(
        ["symbol_a", "symbol_b"], as_index=False).last()
    out = {}
    for state in ("coint", "not_coint"):
        subset = latest[latest["new_state"] == state]
        symbols = sorted(set(subset["symbol_a"]).union(set(subset["symbol_b"])))
        out[state] = symbols
    return out


def diversification_ratio(returns: pd.DataFrame) -> dict:
    """returns: DataFrame of daily returns, columns = symbols. Computes the classic
    diversification ratio (mean individual vol / equal-weight basket vol) plus the basket's
    mean pairwise correlation, for interpretability."""
    returns = returns.dropna(how="all", axis=1)
    if returns.shape[1] < 2:
        return {"n_symbols_used": returns.shape[1], "diversification_ratio": np.nan,
                "mean_pairwise_corr": np.nan, "basket_vol": np.nan, "mean_individual_vol": np.nan}
    individual_vols = returns.std()
    mean_individual_vol = float(individual_vols.mean())
    basket_returns = returns.mean(axis=1)  # equal-weight
    basket_vol = float(basket_returns.std())
    corr = returns.corr()
    n = corr.shape[0]
    mean_pairwise_corr = float((corr.values.sum() - n) / (n * (n - 1))) if n > 1 else np.nan
    ratio = mean_individual_vol / basket_vol if basket_vol and basket_vol > 0 else np.nan
    return {"n_symbols_used": returns.shape[1], "diversification_ratio": ratio,
            "mean_pairwise_corr": mean_pairwise_corr, "basket_vol": basket_vol,
            "mean_individual_vol": mean_individual_vol}


def main():
    _setup_logging()
    log.info("=== diversification_basket_test.py: does a basket of currently-uncorrelated "
              "assets show a REAL diversification benefit vs a correlated or random basket? ===")
    import universe_loader

    transitions = pd.read_parquet(_TRANSITIONS_PATH)
    state_symbols = latest_state_symbols(transitions)
    log.info(f"Symbol pool: {len(state_symbols['not_coint'])} symbols in currently-decoupled "
             f"pairs, {len(state_symbols['coint'])} in currently-coupled pairs.")

    all_symbols = sorted(set(state_symbols["not_coint"]) | set(state_symbols["coint"]))
    universe = universe_loader.load_full_universe(
        tf_label="1D", include_yfinance=True, include_wrds=True, include_binance=True, include_ibkr=True,
        columns=["close"],
    )
    close = {}
    for sym in all_symbols:
        df = universe.get(sym)
        if df is not None and not df.empty and "close" in df.columns:
            close[sym] = df["close"]
    log.info(f"Real price data available for {len(close)}/{len(all_symbols)} pool symbols.")

    rng = np.random.default_rng(_RNG_SEED)
    rows = []
    for basket_size in BASKET_SIZES:
        for arm, symbols in state_symbols.items():
            available = [s for s in symbols if s in close]
            if len(available) < basket_size:
                log.warning(f"  SKIP {arm}/n={basket_size}: only {len(available)} symbols with "
                            f"real price data, need {basket_size}")
                continue
            chosen = list(rng.choice(available, size=basket_size, replace=False))
            price_df = pd.concat({s: close[s] for s in chosen}, axis=1)
            returns = np.log(price_df.astype("float64").where(price_df.astype("float64") > 0)).diff()
            r = diversification_ratio(returns)
            r.update({"basket_size": basket_size, "arm": arm})
            rows.append(r)
            log.info(f"  {arm:>10}/n={basket_size}: diversification_ratio={r['diversification_ratio']:.4f}, "
                      f"mean_pairwise_corr={r['mean_pairwise_corr']:.4f}")

        # Random control: basket_size symbols drawn from the FULL pool regardless of coint state.
        available = [s for s in all_symbols if s in close]
        if len(available) >= basket_size:
            chosen = list(rng.choice(available, size=basket_size, replace=False))
            price_df = pd.concat({s: close[s] for s in chosen}, axis=1)
            returns = np.log(price_df.astype("float64").where(price_df.astype("float64") > 0)).diff()
            r = diversification_ratio(returns)
            r.update({"basket_size": basket_size, "arm": "random_control"})
            rows.append(r)
            log.info(f"  {'random':>10}/n={basket_size}: diversification_ratio={r['diversification_ratio']:.4f}, "
                      f"mean_pairwise_corr={r['mean_pairwise_corr']:.4f}")

    out = pd.DataFrame(rows)
    out.to_parquet(_OUT_PATH)
    log.info(f"Saved -> {_OUT_PATH}")
    log.info("diversification_basket_test.py complete")


if __name__ == "__main__":
    main()
