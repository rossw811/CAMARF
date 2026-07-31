"""
research/comparison_arm_scaffold.py — mandatory walk-forward scaffold for
research/ comparison-arm scripts that FIT something (weights, a model, a
threshold) and then SCORE its performance.

Built 2026-07-20 (Grand Sweep task #22) after finding the same
in-sample-circularity mistake — fitting and scoring on the IDENTICAL
sample, with no held-out split — independently in 3 files:
eigenvalue_weighted_position_sizing.py, portfolio_position_sizing_correction.py,
convex_portfolio_construction.py. This reads like a template problem, not 3
unrelated authoring mistakes: `research/k_bahc_covariance_cleaning.py` is
the one script in this family that already gets this right (real
walk-forward: fit on a train window, realize variance on the strictly
following test window) — this module generalizes exactly that pattern so
future comparison-arm scripts don't have to rediscover it, and existing
ones can be retrofit onto it.

Retrofitting the 3 offenders above is NOT done by this module alone — each
involves re-deriving its own optimization (SLSQP, MP-adaptive eigenvalue
clustering, ERC) to fit per-window rather than once on the full sample,
which changes what each script's headline comparison actually measures, not
just how the code is wired. That is separate, per-file follow-up work, not
retrofit here. Do NOT treat building/verifying this module as also having
retrofit those 3 files.
"""
from typing import Callable, Iterator, List, Optional, Tuple

import pandas as pd


def walk_forward_windows(
    data: pd.DataFrame, train_window: int, test_window: int, step: Optional[int] = None
) -> Iterator[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Yields (train, test) DataFrame slices. train is STRICTLY the
    train_window rows immediately preceding test; test is the following
    test_window rows. Slides forward by `step` (default test_window, i.e.
    non-overlapping test windows). Matches
    k_bahc_covariance_cleaning.py::run()'s existing convention exactly.
    """
    step = step or test_window
    n = len(data)
    start = train_window
    while start + test_window <= n:
        yield data.iloc[start - train_window:start], data.iloc[start:start + test_window]
        start += step


def evaluate_walk_forward(
    data: pd.DataFrame,
    fit_fn: Callable[[pd.DataFrame], object],
    score_fn: Callable[[object, pd.DataFrame], float],
    train_window: int,
    test_window: int,
    step: Optional[int] = None,
) -> List[float]:
    """
    Generic walk-forward harness. For each (train, test) window: fit_fn(train)
    returns a fitted object (weights dict, model, threshold, whatever the
    caller is comparing) using ONLY the train window; score_fn(fitted, test)
    returns a realized metric using ONLY the test window. Prevents the
    in-sample-circularity mistake by construction — fit_fn never receives
    the test window's data, score_fn never re-fits.

    Returns the list of per-window realized scores (e.g. realized OOS
    Sharpe/variance/whatever score_fn computes) — callers aggregate
    (mean, distribution, etc.) themselves, matching how
    k_bahc_covariance_cleaning.py reports its own per-window realized
    variances rather than a single pooled number.
    """
    scores = []
    for train, test in walk_forward_windows(data, train_window, test_window, step):
        fitted = fit_fn(train)
        scores.append(score_fn(fitted, test))
    return scores
