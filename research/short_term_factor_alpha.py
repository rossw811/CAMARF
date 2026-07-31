"""
research/short_term_factor_alpha.py — comparison/diagnostic method, NOT
part of the production pipeline.

Blitz, Hanauer, Honarvar, Huisman & van Vliet (2023), "Beyond Fama-French
Factors: Alpha from Short-Term Signals," Financial Analysts Journal 79(4)
— a composite of short-term reversal, short-term momentum, analyst-revision,
and seasonality signals, robust out-of-sample and largely uncorrelated with
the standard Fama-French factors. CAMARF has NO cross-sectional single-asset
factor layer at all — its entire methodology trades the SPREAD between two
cointegrated legs, never a single asset's own short-term factor exposure.
This is a genuine orthogonal-alpha-source test, not a substitute for the
pairs-trading approach.

No analyst-revision data available (would need a paid data source, same
constraint as options.py) — implements the two signals buildable from data
CAMARF already has:
  1. Short-term reversal: negative of the trailing 5-day cumulative return
     (the classic reversal effect — confirmed as a REAL pattern in this
     exact universe by research/network_momentum.py's own finding tonight,
     that single-asset momentum shows a slightly NEGATIVE correlation with
     forward returns, i.e. reversal not momentum, at the daily frequency).
  2. Seasonality: day-of-week effect (Monday indicator, the most-replicated,
     simplest seasonality signal in the literature — French 1980 and many
     replications since).

Both z-scored and combined into an equal-weight composite, evaluated the
same way network_momentum.py evaluates its signal (pooled correlation
between signal[t] and realized forward return[t]) for direct comparability
— NOT a full backtest with transaction costs, a signal-existence check.

Reuses absorption_ratio.py's universe/returns loading directly (same
universe, same data source, not reimplemented).

Read-only. Never fetches, never modifies analysis.py's cointegration
pipeline — this is an orthogonal signal layer, not a replacement.

Usage:
    python research/short_term_factor_alpha.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from absorption_ratio import confirmed_universe_symbols, _load_daily_log_returns

_REVERSAL_WINDOW = 5


def zscore(df: pd.DataFrame) -> pd.DataFrame:
    return (df - df.mean()) / df.std().replace(0, 1)


def reversal_signal(returns_df: pd.DataFrame, window: int = _REVERSAL_WINDOW) -> pd.DataFrame:
    # Per-column dropna before rolling, then reindex back onto the full
    # (dense, outer-joined) calendar — same gap-aware-rolling fix already
    # applied to big_move_lead_lag.py/hub_leg_stop_conditioning.py this
    # session. returns_df is outer-joined across symbols with different
    # trading calendars (foreign-listing holidays, etc.); a naive
    # .rolling(window).sum() on the raw (ragged) column requires every one
    # of the `window` CALENDAR rows to be non-NaN, so one isolated holiday
    # for a given symbol nulls out its whole trailing-window return even
    # though that symbol's own `window` most recent TRADED days are fine.
    trailing_cumret = pd.DataFrame(
        {col: s.dropna().rolling(window).sum().reindex(returns_df.index)
         for col, s in returns_df.items()},
        index=returns_df.index,
    )
    return -zscore(trailing_cumret)  # negative: high past return -> low predicted future return


def seasonality_signal(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Monday indicator (French 1980) — broadcast the same scalar signal
    across every asset on Monday, 0 elsewhere. A market-wide, not
    asset-specific, seasonality effect (the standard convention)."""
    is_monday = pd.Series(returns_df.index).dt.dayofweek.eq(0).to_numpy()
    signal = np.tile(is_monday.astype(float).reshape(-1, 1), (1, returns_df.shape[1]))
    return pd.DataFrame(signal, index=returns_df.index, columns=returns_df.columns)


def evaluate_signal(signal: pd.DataFrame, returns_df: pd.DataFrame, lag: int = 1) -> dict:
    """Signal at t predicts return at t+lag — pooled correlation across all
    assets/days, same evaluation convention as network_momentum.py.

    Tier 4.2 fix (Grand Sweep 2026-07-20): `n_obs` (day x asset flattened
    count) overstates the true independent sample size for a
    CROSS-SECTIONALLY IDENTICAL signal like the Monday dummy — the same
    scalar value is broadcast across every asset on a given day, so its
    real information content scales with the number of DAYS, not
    days*assets. Also reports `n_effective_days` (unique dates with at
    least one valid signal/return pair) alongside the existing `n_obs`, so
    a reader isn't misled into reading a large days*assets count as if it
    were that many independent observations — most relevant for the
    seasonality signal specifically, harmless (a looser but still honest
    bound) for signals that genuinely vary asset-by-asset."""
    sig_shifted = signal.shift(lag)
    sig_flat = sig_shifted.to_numpy().flatten()
    ret_flat = returns_df.to_numpy().flatten()
    valid = np.isfinite(sig_flat) & np.isfinite(ret_flat)
    valid_2d = np.isfinite(sig_shifted.to_numpy()) & np.isfinite(returns_df.to_numpy())
    n_effective_days = int(np.sum(valid_2d.any(axis=1)))
    if valid.sum() < 100:
        return {"corr": np.nan, "n_obs": int(valid.sum()), "n_effective_days": n_effective_days}
    corr = float(np.corrcoef(sig_flat[valid], ret_flat[valid])[0, 1])
    return {"corr": corr, "n_obs": int(valid.sum()), "n_effective_days": n_effective_days}


def main():
    symbols = confirmed_universe_symbols()
    print(f"Universe: {len(symbols)} unique symbols across all confirmed pairs")
    if len(symbols) < 10:
        print("Too few symbols — run analysis.py first. Aborting.")
        return

    returns_df = _load_daily_log_returns(symbols)
    print(f"Loaded daily returns: {returns_df.shape[0]} dates x {returns_df.shape[1]} symbols")
    if returns_df.empty or returns_df.shape[0] < 100:
        print("Insufficient daily history — aborting.")
        return

    reversal = reversal_signal(returns_df)
    seasonality = seasonality_signal(returns_df)
    composite = zscore(reversal) + zscore(seasonality)

    r_reversal = evaluate_signal(reversal, returns_df)
    r_seasonality = evaluate_signal(seasonality, returns_df)
    r_composite = evaluate_signal(composite, returns_df)

    print(f"\nShort-term reversal signal: corr(signal, forward return)={r_reversal['corr']:.4f} "
          f"(n={r_reversal['n_obs']}, n_effective_days={r_reversal['n_effective_days']})")
    print(f"Day-of-week (Monday) seasonality: corr(signal, forward return)={r_seasonality['corr']:.4f} "
          f"(n={r_seasonality['n_obs']}, n_effective_days={r_seasonality['n_effective_days']} -- "
          f"the Monday dummy is IDENTICAL across every asset on a given day, so this signal's true "
          f"independent sample size is ~n_effective_days, not n_obs)")
    print(f"Equal-weight composite: corr(signal, forward return)={r_composite['corr']:.4f} "
          f"(n={r_composite['n_obs']}, n_effective_days={r_composite['n_effective_days']})")

    os.makedirs("output/research", exist_ok=True)
    pd.DataFrame([
        {"signal": "reversal", **r_reversal},
        {"signal": "seasonality", **r_seasonality},
        {"signal": "composite", **r_composite},
    ]).to_parquet("output/research/short_term_factor_alpha.parquet")
    print("\nWrote output/research/short_term_factor_alpha.parquet")


if __name__ == "__main__":
    main()
