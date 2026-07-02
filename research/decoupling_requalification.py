"""
CAMARF decoupling_requalification.py — exploratory diagnostic, NOT part of
the production pipeline.

Motivation: decoupling_analysis.py's real result (142 detected Zivot-Andrews
breaks, 2026-07-01) found 0% of breaks revert to the OLD equilibrium, 50%
keep diverging with no way to time an exit, and only 15.5% settle into a
new, stable relationship. Neither "trade the divergence" (unbounded risk,
the majority outcome) nor "bet on quick reversion" (empirically the wrong
bet — nothing reverts to the old level) is supported by that finding. What
IS supported: since some pairs genuinely do settle into a new equilibrium,
the responsible design is RE-QUALIFICATION, not a new trading signal on the
break itself — after a detected break, wait a settling period, then re-run
the SAME existing Engle-Granger cointegration test the production pipeline
already uses, but on the POST-BREAK window alone (not full-sample). If the
pair re-qualifies, it's treated as a fresh cointegration candidate around
its new level — not resurrecting the old relationship, testing whether a
new one has formed. Locked in with Ross 2026-07-01 after reviewing the
decoupling_analysis.py finding.

Method: reuses `_eg_worker` directly from analysis.py (the exact same
Engle-Granger test — same statsmodels.coint() call, same trend="c",
max_lag, autolag="aic" — the production pipeline uses for every candidate
pair) rather than reimplementing cointegration testing. For every pair in
all_candidates.parquet with a detected zivot_andrews_break that is NOT in
the final confirmed pairs.parquet (i.e. excluded specifically because of
that break): load raw log-close prices for both legs, take the window
starting SETTLING_BARS after the break date through the end of available
history, and re-test cointegration on that sub-series alone.

Honest scope note: this asks "would this pair pass the SAME test the
production pipeline uses, if only the pipeline had looked at the post-break
window instead of the full history" — it does not itself decide whether
re-qualified pairs should be automatically re-admitted to a live confirmed
set (that requires its own backtest evidence, not just a re-test p-value,
matching this project's standing "don't decide ranking/selection questions
on statistical grounds alone" discipline).

Output:
  output/research/decoupling_requalification.parquet
  latest_run_decoupling_requalification.log
"""
import glob
import logging
import os
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import _eg_worker
from config import Config
from data import DataStore

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_SETTLING_BARS = 60  # bars to skip immediately after the break before re-testing

log = logging.getLogger("decoupling_requalification")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_decoupling_requalification.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _load_log_close(symbol: str, tf_label: str) -> Optional[pd.Series]:
    df = DataStore.load(symbol, tf_label)
    if df is None or "close" not in df.columns:
        return None
    close = df["close"].dropna()
    close.index = pd.to_datetime(close.index)
    return np.log(close)


def requalify_pair(
    sym_a: str, sym_b: str, tf_label: str, break_date: pd.Timestamp,
    settling_bars: int = _SETTLING_BARS,
) -> Optional[dict]:
    """
    Pure-ish function (one real data load per call, no filesystem writes) —
    kept separate from main() so debug/_verify_decoupling_requalification.py
    can call it directly against real cached prices for a known pair.
    Returns None if there isn't enough post-settling history to test.
    """
    log_a = _load_log_close(sym_a, tf_label)
    log_b = _load_log_close(sym_b, tf_label)
    if log_a is None or log_b is None:
        return None

    aligned = pd.DataFrame({"a": log_a, "b": log_b}).dropna()
    post_break = aligned[aligned.index > break_date]
    if len(post_break) <= settling_bars:
        return None
    settled = post_break.iloc[settling_bars:]
    if len(settled) < 60:  # _eg_worker's own minimum overlap requirement
        return None

    eg_result = _eg_worker((
        sym_a, sym_b, settled["a"].values, settled["b"].values, Config.ANALYSIS.EG_MAX_LAG
    ))
    return {
        "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
        "break_date": break_date, "n_post_settling_bars": len(settled),
        "requalify_pvalue": eg_result.get("pvalue"),
        "requalify_hedge_ratio": eg_result.get("hedge_ratio"),
        "requalifies": bool(eg_result.get("ok") and
                             eg_result.get("pvalue", 1.0) < Config.ANALYSIS.EG_SIGNIFICANCE),
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== decoupling_requalification.py: re-test broken pairs on their post-break window ===")
    log.info("SETTLING_BARS=%d before re-testing; EG_SIGNIFICANCE=%.3f (same threshold "
             "production analysis.py uses)", _SETTLING_BARS, Config.ANALYSIS.EG_SIGNIFICANCE)

    rows = []
    for cand_path in sorted(glob.glob(os.path.join(_RESULTS_DIR, "*", "all_candidates.parquet"))):
        tf_dir = os.path.basename(os.path.dirname(cand_path))
        tf_label = tf_dir.replace("hr", "h").replace("min", "m").replace("day", "D").replace("mo", "M")
        candidates = pd.read_parquet(cand_path)
        pairs_path = os.path.join(_RESULTS_DIR, tf_dir, "pairs.parquet")
        confirmed_keys = set()
        if os.path.exists(pairs_path):
            confirmed = pd.read_parquet(pairs_path)
            confirmed_keys = set(zip(confirmed["symbol_a"], confirmed["symbol_b"]))

        broken = candidates[
            candidates["zivot_andrews_break"].notna()
            & ~candidates.apply(lambda r: (r["symbol_a"], r["symbol_b"]) in confirmed_keys, axis=1)
        ]
        log.info("[%s] %d broken-and-excluded pairs to re-test", tf_dir, len(broken))

        for _, row in broken.iterrows():
            result = requalify_pair(
                row["symbol_a"], row["symbol_b"], tf_label, pd.Timestamp(row["zivot_andrews_break"]),
            )
            if result is not None:
                rows.append(result)

    if not rows:
        log.warning("No pairs had enough post-break history to re-test.")
        return

    result_df = pd.DataFrame(rows)
    n_requalify = int(result_df["requalifies"].sum())
    log.info("\n--- Re-qualification result: %d/%d broken-and-excluded pairs re-qualify "
             "on their post-break window alone ---", n_requalify, len(result_df))
    if n_requalify:
        log.info("\n%s", result_df[result_df["requalifies"]][
            ["symbol_a", "symbol_b", "tf_label", "requalify_pvalue", "requalify_hedge_ratio"]
        ].to_string(index=False))

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "decoupling_requalification.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info("Saved -> %s", out_path)
    log.info("NOTE: a passing re-qualification p-value is evidence a new relationship has "
             "formed, not by itself a decision to re-admit the pair to a live confirmed set "
             "— that needs its own backtest evidence per this project's standing discipline.")

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("decoupling_requalification.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
