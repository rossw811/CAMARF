"""
CAMARF era_decay_replication.py — exploratory diagnostic, NOT part of the
production pipeline.

Motivation (2026-06-30 STORM literature survey): Do & Faff (2010) split the
Gatev-Goetzmann-Rouwenhorst distance method's sample into eras (1962-1988,
1989-2002, 2003-2009) and found profitability decayed more than 70%,
explicitly testing and rejecting hedge-fund "crowding" as the primary
mechanism in favor of weakening pair convergence properties. Ross asked
that CAMARF's own project be used to independently answer open literature
questions rather than only cite them — this script is that attempt for the
decay-mechanism question, honestly scoped to what CAMARF's data can actually
speak to.

Scope limit, stated explicitly: CAMARF cannot test the "crowding" hypothesis
at all — that requires external capital-flow/AUM data this project has no
access to. What it CAN test, using the IBKR 10-year deep-history supplement
for 1h pairs (the only pairs with enough history for a multi-era split to
be meaningful), is the alternative, non-crowding mechanism Do & Faff
themselves preferred: does performance decay across sequential eras WITHIN
CAMARF's own data, and if so, does it coincide with a measurable weakening
of the pairs' own convergence properties (rising half-life = slower mean
reversion)? A decay that coincides with rising half-life is evidence
consistent with the "convergence deterioration" mechanism; a decay that
does NOT coincide with any half-life trend would suggest a different or
unidentified mechanism — reported honestly either way, including if no
decay is present at all (a null result is a real result here, not a
failure to find something).

Method: for each confirmed 1h pair, split its available spread_series
history (which reflects IBKR deep history where available — see
analysis.py's _enrich_with_deep_history) into N_ERAS roughly equal
sequential chronological thirds. Backtest each era independently (plain
BacktestEngine, no STORM flags, no ML gate, OLS hedge — the same
"apples-to-apples" convention distance.py uses for baseline comparisons),
and separately compute each era's mean half_life_rolling from the spread
data directly (not from a backtest — a pure descriptive statistic of the
pair's own mean-reversion speed in that era).

Output:
  output/research/era_decay_replication.parquet — per-pair, per-era metrics
  latest_run_era_decay_replication.log
"""
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import (
    BacktestEngine, RegimeConditioner, MLConditioner,
    _load_spread, compute_metrics, aggregate_portfolio,
)
from config import Config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_TF_DIR, _TF_LABEL = "1hr", "1h"
_N_ERAS = 3

log = logging.getLogger("era_decay_replication")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_era_decay_replication.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _split_eras(spread_df: pd.DataFrame, n_eras: int) -> List[pd.DataFrame]:
    """Roughly equal sequential chronological thirds, by bar count (simple,
    deterministic — not calendar-date-equal, since bar density can vary
    across a pair's history, e.g. around data gaps)."""
    n = len(spread_df)
    edges = np.linspace(0, n, n_eras + 1).astype(int)
    return [spread_df.iloc[edges[i]:edges[i + 1]] for i in range(n_eras)]


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== era_decay_replication.py: Do & Faff (2010)-style era-decay replication on CAMARF's own data ===")
    log.info("SCOPE: tests decay + convergence-property (half-life) trend only — "
              "cannot test the 'crowding' hypothesis (requires external capital-flow "
              "data CAMARF does not have). See module docstring.")

    pairs_path = os.path.join(_RESULTS_DIR, _TF_DIR, "pairs.parquet")
    if not os.path.exists(pairs_path):
        log.warning("No pairs.parquet at %s — nothing to replicate.", pairs_path)
        return
    pairs = pd.read_parquet(pairs_path)
    if "tf_label" not in pairs.columns:
        pairs["tf_label"] = _TF_LABEL

    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
    )

    era_rows = []
    for _, pair_row in pairs.iterrows():
        sym_a, sym_b = pair_row["symbol_a"], pair_row["symbol_b"]
        spread_df = _load_spread(_TF_DIR, sym_a, sym_b)
        if spread_df is None or len(spread_df) < _N_ERAS * 60:
            log.info("SKIP %s/%s: insufficient history for a %d-era split", sym_a, sym_b, _N_ERAS)
            continue

        eras = _split_eras(spread_df, _N_ERAS)
        for era_idx, era_df in enumerate(eras):
            if era_df.empty:
                continue
            trades = engine.run(pair_row, era_df, hedge_method="ols", holdout_only=False)
            metrics = compute_metrics(trades, _TF_LABEL, sym_a, sym_b, "ols")
            mean_hl = float(era_df["half_life_rolling"].mean()) if "half_life_rolling" in era_df else np.nan
            era_rows.append({
                "symbol_a": sym_a, "symbol_b": sym_b, "era": era_idx,
                "era_start": era_df.index.min(), "era_end": era_df.index.max(),
                "n_bars": len(era_df),
                "n_trades": metrics.get("n_trades", 0),
                "total_pnl": metrics.get("total_pnl", np.nan),
                "sharpe": metrics.get("sharpe", np.nan),
                "mean_half_life": mean_hl,
                "trades_obj": trades,  # kept for portfolio aggregation below, dropped before save
            })

    if not era_rows:
        log.warning("No era-level results produced.")
        return

    era_df_all = pd.DataFrame(era_rows)

    # Portfolio-level aggregation per era (pools every pair's trades within that era)
    log.info("\n%-6s %10s %10s %12s %14s", "era", "n_pairs", "n_trades", "sharpe_port", "mean_half_life")
    portfolio_summary = []
    for era_idx in sorted(era_df_all["era"].unique()):
        era_slice = era_df_all[era_df_all["era"] == era_idx]
        all_trades = [t for trades in era_slice["trades_obj"] for t in trades]
        port_stats = aggregate_portfolio(all_trades, era_slice.to_dict("records"))
        mean_hl = era_slice["mean_half_life"].mean()
        n_pairs_with_trades = (era_slice["n_trades"] > 0).sum()
        sharpe_port = port_stats.get("sharpe_portfolio", np.nan)
        log.info("%-6d %10d %10d %12.4f %14.2f",
                  era_idx, n_pairs_with_trades, len(all_trades), sharpe_port, mean_hl)
        portfolio_summary.append({
            "era": era_idx, "n_pairs_with_trades": int(n_pairs_with_trades),
            "n_trades": len(all_trades), "sharpe_portfolio": sharpe_port,
            "mean_half_life_across_pairs": mean_hl,
        })

    summary_df = pd.DataFrame(portfolio_summary)
    sharpes = summary_df["sharpe_portfolio"].values
    half_lives = summary_df["mean_half_life_across_pairs"].values

    is_monotonic_decay = all(
        sharpes[i] >= sharpes[i + 1] or not np.isfinite(sharpes[i]) or not np.isfinite(sharpes[i + 1])
        for i in range(len(sharpes) - 1)
    ) and np.isfinite(sharpes).sum() >= 2
    is_monotonic_hl_increase = all(
        half_lives[i] <= half_lives[i + 1]
        for i in range(len(half_lives) - 1)
        if np.isfinite(half_lives[i]) and np.isfinite(half_lives[i + 1])
    )

    log.info("\n--- Honest interpretation (report whichever pattern actually appears) ---")
    log.info("Portfolio Sharpe monotonically declining across eras: %s", is_monotonic_decay)
    log.info("Mean half-life monotonically increasing across eras: %s", is_monotonic_hl_increase)
    if is_monotonic_decay and is_monotonic_hl_increase:
        log.info("Pattern CONSISTENT with Do & Faff's preferred mechanism: decay "
                 "coincides with weakening convergence properties (rising half-life) "
                 "in CAMARF's own data, over the available history window.")
    elif is_monotonic_decay and not is_monotonic_hl_increase:
        log.info("Decay present but does NOT coincide with a rising half-life trend — "
                 "suggests a different or unidentified mechanism than convergence "
                 "deterioration is driving any decay seen here. Cannot attribute to "
                 "crowding either (not testable with this data).")
    elif not is_monotonic_decay:
        log.info("No consistent decay pattern found across %d eras in CAMARF's available "
                 "history for confirmed 1h pairs. This is a genuine null result, not a "
                 "failure — CAMARF's history window may simply be too short relative to "
                 "the multi-decade span Do & Faff's original replication covered.", _N_ERAS)

    os.makedirs(_OUT_DIR, exist_ok=True)
    era_df_all.drop(columns=["trades_obj"]).to_parquet(
        os.path.join(_OUT_DIR, "era_decay_replication.parquet"), index=False
    )
    summary_path = os.path.join(_OUT_DIR, "era_decay_replication_summary.parquet")
    summary_df.to_parquet(summary_path, index=False)
    log.info("Saved -> %s, %s", os.path.join(_OUT_DIR, "era_decay_replication.parquet"), summary_path)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("era_decay_replication.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
