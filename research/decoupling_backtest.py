"""
CAMARF decoupling_backtest.py — exploratory diagnostic, NOT part of the
production pipeline.

Motivation: decoupling_requalification.py found 5/142 broken-and-excluded 1h
pairs statistically re-qualify (EG p < 0.05) on their post-break window
alone. A passing p-value is not, by itself, evidence of a tradeable
strategy — no fresh spread/hedge-ratio model or backtest exists for that
post-break window yet, so there is currently nothing here to actually trade.
Ross's explicit direction (2026-07-01): build that model and backtest it for
real before deciding whether to wire re-qualification into the live
pipeline. If it holds up, that's the evidence needed to add these pairs
back; if not, the finding stays research-only and that's a legitimate,
cheap answer.

Method: reuses AnalysisPipeline._build_pair_result() directly — the exact
same hedge-ratio (OLS/TLS/Kalman), OU spread-fit, half-life, and
structural-break machinery every normal confirmed pair goes through, NOT a
simplified/reimplemented version — restricted to each re-qualified pair's
post-break settling window (DataAligner.align_universe(), then a date slice,
matching the "compact_bars_only" alignment convention analysis.py always
uses). The resulting PairResult + per-bar spread series feed directly into
backtest.py's own BacktestEngine, unmodified — an apples-to-apples backtest
using the identical engine every other CAMARF result in this project uses,
just with a freshly-built spread model on new data.

Output:
  output/research/decoupling_backtest.parquet — per-pair backtest metrics
  latest_run_decoupling_backtest.log
"""
import logging
import os
import sys
import time
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import AnalysisPipeline
from backtest import BacktestEngine, RegimeConditioner, MLConditioner, compute_metrics
from config import Config
from data import DataAligner, DataStore

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_SETTLING_BARS = 60  # must match decoupling_requalification.py's SETTLING_BARS

log = logging.getLogger("decoupling_backtest")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_decoupling_backtest.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def build_and_backtest_requalified_pair(
    sym_a: str, sym_b: str, tf_label: str, break_date: pd.Timestamp,
    requalify_pvalue: float, settling_bars: int = _SETTLING_BARS,
) -> Optional[dict]:
    """
    Builds a fresh PairResult + spread model on the post-break settling
    window (reusing _build_pair_result, not reimplementing it), then
    backtests it with the standard, unmodified BacktestEngine (no STORM
    flags, no ML gate — matching distance.py's apples-to-apples convention).
    Returns None if there isn't enough post-break history to model.
    """
    df_a = DataStore.load(sym_a, tf_label)
    df_b = DataStore.load(sym_b, tf_label)
    if df_a is None or df_b is None:
        return None

    # drop_data_gap_rows=True: per DataAligner.align_universe's own docstring,
    # this is a "single-pair/real-timestamp-join consumer," not the main
    # pipeline's cross-symbol dense-matrix construction — the default
    # (False) calendar-pads onto a continuous grid and forward-fills gaps,
    # which inflated bar counts ~5-6x and produced impossible Sharpe ratios
    # (20-55) the first time this ran, caught by comparing aligned bar count
    # against the raw cached data's bar count for the same symbol/TF.
    aligned = DataAligner.align_universe(
        {f"{sym_a}_{tf_label}": df_a, f"{sym_b}_{tf_label}": df_b}, tf_label,
        drop_data_gap_rows=True,
    )
    if sym_a not in aligned or sym_b not in aligned:
        return None

    # drop_data_gap_rows=True drops each symbol's OWN gap rows independently,
    # so the two legs can come back different lengths even after alignment —
    # caught in pit_wfa.py's analogous code path (a real 2203-vs-2202 shape
    # mismatch), fixed here defensively too even though it happened not to
    # manifest for the 5 pairs this script was run against.
    common_idx = aligned[sym_a].index.intersection(aligned[sym_b].index)
    aligned = {sym_a: aligned[sym_a].loc[common_idx], sym_b: aligned[sym_b].loc[common_idx]}

    # Restrict to the post-break settling window — same break date and
    # settling-bars convention decoupling_requalification.py used to decide
    # this pair re-qualifies in the first place.
    full_index = aligned[sym_a].index
    post_break_mask = full_index > break_date
    post_break_idx = full_index[post_break_mask]
    if len(post_break_idx) <= settling_bars:
        return None
    settled_start = post_break_idx[settling_bars]
    aligned_settled = {
        sym: df.loc[df.index >= settled_start] for sym, df in aligned.items()
    }
    if len(aligned_settled[sym_a]) < 120:  # need real history to fit + backtest, not just re-test
        return None

    built = AnalysisPipeline._build_pair_result(
        {"symbol_a": sym_a, "symbol_b": sym_b, "coint_pvalue_raw": requalify_pvalue},
        aligned_settled, tf_label,
    )
    if built is None:
        return None
    pair_result, per_bar = built

    spread_df = pd.DataFrame(
        {
            "spread": per_bar["spread"],
            "z_rolling": per_bar["z_rolling"],
            "z_expanding": per_bar["z_expanding"],
            "half_life_rolling": per_bar["half_life_rolling_series"],
            "gap_flag_a": per_bar["gap_flag_a"],
            "gap_flag_b": per_bar["gap_flag_b"],
            "hedge_ratio_ols_t": per_bar.get("hedge_ratio_ols_t"),
            "hedge_ratio_kalman_t": per_bar.get("hedge_ratio_kalman_t"),
        },
        index=per_bar["index"],
    )
    pair_row = pd.Series({**vars(pair_result), "tf_label": tf_label})

    engine = BacktestEngine(
        cfg=Config.BACKTEST,
        regime_cond=RegimeConditioner(enabled=False),
        ml_cond=MLConditioner(enabled=False),
    )
    trades = engine.run(pair_row, spread_df, hedge_method="ols", holdout_only=False)
    metrics = compute_metrics(trades, tf_label, sym_a, sym_b, "ols") if trades else {}

    return {
        "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
        "break_date": break_date, "n_post_settling_bars": len(aligned_settled[sym_a]),
        "half_life_rolling": pair_result.half_life_rolling,
        "coint_fraction_rolling": pair_result.coint_fraction_rolling,
        "n_trades": metrics.get("n_trades", 0),
        "sharpe": metrics.get("sharpe", float("nan")),
        "total_pnl": metrics.get("total_pnl", float("nan")),
        "win_rate": metrics.get("win_rate", float("nan")),
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== decoupling_backtest.py: backtest the re-qualified pairs on their post-break window ===")

    requal_path = os.path.join(_OUT_DIR, "decoupling_requalification.parquet")
    if not os.path.exists(requal_path):
        log.warning("No %s — run decoupling_requalification.py first.", requal_path)
        return
    requal = pd.read_parquet(requal_path)
    to_test = requal[requal["requalifies"]]
    log.info("%d re-qualified pairs to build and backtest", len(to_test))

    rows = []
    for _, row in to_test.iterrows():
        result = build_and_backtest_requalified_pair(
            row["symbol_a"], row["symbol_b"], row["tf_label"],
            pd.Timestamp(row["break_date"]), float(row["requalify_pvalue"]),
        )
        if result is None:
            log.info("  %s/%s: insufficient post-break history to build+backtest", row["symbol_a"], row["symbol_b"])
            continue
        rows.append(result)
        log.info("  %s/%s@%s: %d trades, Sharpe=%.3f, PnL=%.2f, WR=%.0f%%, HL=%.1f, coint_frac=%.3f",
                  result["symbol_a"], result["symbol_b"], result["tf_label"],
                  result["n_trades"], result["sharpe"], result["total_pnl"],
                  result["win_rate"] * 100 if result["win_rate"] == result["win_rate"] else float("nan"),
                  result["half_life_rolling"], result["coint_fraction_rolling"])

    if not rows:
        log.warning("No re-qualified pairs had enough post-break history to backtest.")
        return

    result_df = pd.DataFrame(rows)
    n_with_trades = int((result_df["n_trades"] > 0).sum())
    n_positive_sharpe = int((result_df["sharpe"] > 0).sum())
    log.info("\n--- Result: %d/%d re-qualified pairs generated trades; %d/%d had positive Sharpe ---",
              n_with_trades, len(result_df), n_positive_sharpe, len(result_df))
    log.info("\n%s", result_df.to_string(index=False))

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "decoupling_backtest.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info("Saved -> %s", out_path)
    log.info("This is IS-only (no holdout split — too little post-break history to split "
             "further for most pairs). A positive result here is evidence for the live-"
             "pipeline wiring decision, not itself an OOS-validated claim.")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("decoupling_backtest.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
