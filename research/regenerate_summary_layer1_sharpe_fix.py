"""
research/regenerate_summary_layer1_sharpe_fix.py -- one-time regeneration of every
output/backtest/*summary*.parquet file using the corrected Sharpe annualization
(backtest.py:compute_metrics, fixed 2026-09-04 -- see docs/FINDINGS.md Finding #51).

Real bug found live: compute_metrics() annualized per-TRADE Sharpe using
sqrt(bars_per_year[tf]), implicitly assuming a trade happens on every bar. This was NEVER the
formula behind any of this project's cited HEADLINE Sharpe numbers (aggregate_portfolio(),
portfolio_math.py, sensitivity.py's _portfolio_sharpe(), and portfolio_sim.py's
portfolio_sharpe_from_replay() all already used the correct daily-resampled-P&L /sqrt(252)
convention, confirmed by direct audit) -- it only affected the PER-PAIR diagnostic summary
tables these *_summary_layer1*.parquet files hold, which are read only by reproduce.py for
reporting (confirmed via grep -- never consumed by any pair-selection/ranking logic).

This script rebuilds every summary file's rows FROM its already-cached matching trades file
(159/159 summary files confirmed to have one, verified before writing this script), grouped by
(tf, symbol_a, symbol_b, hedge_method) -- the exact same grouping the original summary
generation used -- via the now-fixed compute_metrics(). No re-running of backtest.py itself, no
change to which trades exist, purely a recomputation of already-correct trade data through the
corrected formula.

Usage:
    python research/regenerate_summary_layer1_sharpe_fix.py
    python research/regenerate_summary_layer1_sharpe_fix.py --dry-run
"""
import argparse
import glob
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest import Trade, compute_metrics

log = logging.getLogger("regenerate_summary_layer1_sharpe_fix")

_BACKTEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "output", "backtest")
_TRADE_FIELDS = set(Trade.__dataclass_fields__.keys())


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")


def regenerate_one(summary_path: str, trades_path: str) -> pd.DataFrame:
    """Rebuilds one summary file's rows from its matching trades file via the fixed
    compute_metrics(), grouped by (tf, symbol_a, symbol_b, hedge_method)."""
    trades_df = pd.read_parquet(trades_path)
    rows = []
    for (tf, sa, sb, hm), g in trades_df.groupby(["tf", "symbol_a", "symbol_b", "hedge_method"]):
        trade_objs = [Trade(**{k: r[k] for k in _TRADE_FIELDS if k in r}) for _, r in g.iterrows()]
        m = compute_metrics(trade_objs, tf, sa, sb, hm)
        if m:
            rows.append(m)
    return pd.DataFrame(rows)


def main():
    _setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="Compute and report old-vs-new Sharpe deltas without overwriting files.")
    args = parser.parse_args()

    summaries = sorted(glob.glob(os.path.join(_BACKTEST_DIR, "*summary*.parquet")))
    log.info(f"=== regenerate_summary_layer1_sharpe_fix.py: {len(summaries)} summary files "
              f"found, dry_run={args.dry_run} ===")

    n_regenerated, n_skipped_no_trades_file, n_skipped_no_change = 0, 0, 0
    max_abs_shift = 0.0
    for summary_path in summaries:
        base = os.path.basename(summary_path)
        trades_path = os.path.join(_BACKTEST_DIR, base.replace("summary", "trades"))
        if not os.path.exists(trades_path):
            log.warning(f"  SKIP {base}: no matching trades file at {os.path.basename(trades_path)}")
            n_skipped_no_trades_file += 1
            continue

        trades_cols = pd.read_parquet(trades_path).columns
        required = {"tf", "symbol_a", "symbol_b", "hedge_method"}
        if not required.issubset(trades_cols):
            # Real case found live: wfa_summary_{expanding,rolling}.parquet's matching trades
            # files come from wfa.py's own separate pipeline (tf_label/fold/variant schema, not
            # backtest.py's Layer 1 tf/symbol_a/symbol_b/hedge_method schema) -- out of scope for
            # this regeneration pass, skipped explicitly rather than crashing or silently
            # producing wrong groupings.
            log.warning(f"  SKIP {base}: matching trades file has a different schema "
                        f"(missing {required - set(trades_cols)}), not backtest.py's Layer 1 format")
            n_skipped_no_trades_file += 1
            continue

        old = pd.read_parquet(summary_path)
        new = regenerate_one(summary_path, trades_path)
        if len(new) == 0:
            n_skipped_no_change += 1
            continue

        if "sharpe" in old.columns and "sharpe" in new.columns and len(old) == len(new):
            key_cols = [c for c in ("tf", "symbol_a", "symbol_b", "hedge_method") if c in old.columns]
            if key_cols:
                merged = old[key_cols + ["sharpe"]].merge(
                    new[key_cols + ["sharpe"]], on=key_cols, suffixes=("_old", "_new"))
                shift = (merged["sharpe_old"] - merged["sharpe_new"]).abs().max()
                if pd.notna(shift):
                    max_abs_shift = max(max_abs_shift, float(shift))

        if not args.dry_run:
            new.to_parquet(summary_path)
        n_regenerated += 1
        print(f"  [{n_regenerated}/{len(summaries)}] {base}", flush=True)

    log.info(f"Regenerated {n_regenerated}/{len(summaries)} summary files "
              f"({n_skipped_no_trades_file} skipped: no trades file, "
              f"{n_skipped_no_change} skipped: no rows) "
              f"[max observed |old_sharpe - new_sharpe| across all files: {max_abs_shift:.2f}]"
              f"{' -- DRY RUN, nothing written' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
