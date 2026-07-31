"""
research/spread_construction.py — shared full-sample OLS spread/z-score
construction for research/ comparison scripts.

This is the identical computation independently copy-pasted into FIVE files
(found 2026-07-20 Grand Sweep): breakout_vs_reversion.py (the origin,
build_spread_and_z), leg_level_early_exit.py (build_spread_z_and_legs),
archetype_conditional_sizing.py, vol_targeting_and_drawdown_derisking.py,
and hub_leg_stop_conditioning.py (all three named build_spread_z). None of
them called a shared function, so a future fix to one would not have
propagated to the others — the same "same bug, independent copies" pattern
already found repeatedly this session (BUG-D62->D64, BUG-D65->D66,
comomentum.py's hedge_ratio_ols_t miss).

IMPORTANT — this module does NOT fix the lookahead bias it computes.
full_sample_ols_spread() fits a SINGLE static hedge ratio from the ENTIRE
aligned series (full-sample mean/covariance, including bars "after" any
given historical point) — explicitly disclosed as non-causal by
breakout_vs_reversion.py's own docstring ("a genuine lookahead bias... uses
data from AFTER any given trade"). Consolidating the five copies into one
function is in scope here (task #17, Grand Sweep); replacing the
full-sample fit with a genuinely rolling/expanding one is a separate,
not-yet-made decision. Every caller must keep disclosing this explicitly.
"""
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price


def full_sample_ols_spread(
    symbol_a: str, symbol_b: str, tf_label: str, min_bars: int = 100
) -> Optional[Tuple[pd.Series, pd.Series, float, float, pd.Series]]:
    """
    Loads the aligned pair, gap-masks to log prices, and fits a single
    full-sample static OLS hedge ratio (log_a ~ alpha + beta*log_b) — NOT
    causal, NOT point-in-time (see module docstring).

    Returns (la, lb, beta, alpha, spread) — la/lb/spread are aligned
    pd.Series (NOT yet rolling-window-dropna'd; callers apply their own
    z_window on top), or None if data is missing or shorter than min_bars.
    """
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    log_a, log_b = log_a.reindex(common_idx), log_b.reindex(common_idx)
    mask = log_a.notna() & log_b.notna()
    la, lb = log_a[mask], log_b[mask]
    if len(la) < min_bars:
        return None
    beta = np.dot(lb - lb.mean(), la - la.mean()) / np.dot(lb - lb.mean(), lb - lb.mean())
    alpha = la.mean() - beta * lb.mean()
    spread = la - (alpha + beta * lb)
    return la, lb, beta, alpha, spread
