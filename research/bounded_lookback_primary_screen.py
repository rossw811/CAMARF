"""
CAMARF bounded_lookback_primary_screen.py — research script, NOT part of
the production pipeline.

Motivation (Development.md, Session ~4-5 planning note, never built until
this session's backlog audit): the project's own headline "Strictness
Paradox" finding is that a full-sample EG cointegration test can pass a
pair (p<0.005) while the SAME test restricted to the last five years
fails it — the pair looks confirmed only because of decades-old history
that no longer describes the relationship. `coint_fraction_rolling`
operationalizes this as a SECONDARY diagnostic gating the full-sample
screen. This script asks the more direct question the original note
proposed: what does the CURRENT confirmed-pair set look like if a bounded
recent lookback (5yr and 10yr) is used as its own PRIMARY screen instead,
independently re-running EG + the stats.py Section 1 KPSS/PO tiering on
just that window — not merely a secondary gate on top of the full-sample
result?

Scope, stated honestly: this re-screens the pairs ALREADY in
pairs.parquet (not a full candidate-universe rediscovery pass — that
would need re-running analysis.py's whole CointScanner/DataAligner
pipeline against truncated data, a much larger undertaking than a
comparison script should attempt). It answers "would today's confirmed
set survive under bounded-lookback-as-primary" not "would a fresh
bounded-lookback-primary full-universe scan find a different candidate
set from scratch." Only 1D/1M/3M/6M pairs can show a real effect here —
data.py's own fetch windows cap 1h/4h at 730 days and shorter intraday
TFs at days, so "bounded lookback" is a no-op (same as full sample) for
anything shorter than the fetch window itself; this is expected, not a
bug, and is reported plainly per pair rather than hidden.

Method per confirmed pair:
  1. Load aligned log-price series via aligned_pair_loader.load_aligned_pair
     (production DataAligner convention — gap_flag masking applied).
  2. Full-sample: EG test (statsmodels.coint, same trend="c"/autolag="aic"
     convention as analysis.py's CointScanner._eg_worker) + OLS hedge ratio
     + spread, then stats.py's own _run_coint_tests (KPSS+PO tiering) —
     reused directly, not reimplemented, so the tiering logic matches
     production exactly (same BUG-D55 gap-masking fix already applied
     upstream by load_aligned_pair).
  3. Bounded lookback (5yr, 10yr): same procedure, but log-price arrays
     truncated to the last N calendar years of REAL (non-DATA_GAP) bars
     before the EG test — hedge ratio is RE-fit on the truncated window,
     not reused from the full sample, since that's what a system that
     only had bounded-window data would actually do.
  4. Report full-sample tier vs. 5yr tier vs. 10yr tier side by side.

Output:
  output/research/bounded_lookback_primary_screen.parquet
  latest_run_bounded_lookback_primary_screen.log
"""
import logging
import os
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from statsmodels.tsa.stattools import coint

from aligned_pair_loader import TF_DIRS, DIR_TO_LABEL, resolve_tf_results_dir, load_aligned_pair
from data import GapFlag, clean_close

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_STATS_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _STATS_PATH not in sys.path:
    sys.path.insert(0, _STATS_PATH)
from stats import _run_coint_tests  # reused directly, not reimplemented

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_EG_MAX_LAG = 20
_LOOKBACK_YEARS = (5, 10)

log = logging.getLogger("bounded_lookback_primary_screen")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_bounded_lookback_primary_screen.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def eg_tier_on_window(log_a: np.ndarray, log_b: np.ndarray, index: pd.DatetimeIndex) -> Optional[dict]:
    """
    Full EG + hedge ratio + KPSS/PO tiering on one (log_a, log_b) window.
    Pure function — no I/O — so debug/_verify_bounded_lookback_primary_screen.py
    can call it directly on synthetic arrays. Returns None if insufficient data.
    """
    mask = np.isfinite(log_a) & np.isfinite(log_b)
    a = log_a[mask]
    b = log_b[mask]
    idx = index[mask]
    n = a.size
    if n < 60:
        return None

    t_stat, eg_pval, _crit = coint(a, b, trend="c", maxlag=_EG_MAX_LAG, autolag="aic")

    b_c = b - b.mean()
    a_c = a - a.mean()
    var_b = np.dot(b_c, b_c)
    hr = float(np.dot(a_c, b_c) / var_b) if var_b > 0 else np.nan
    if not np.isfinite(hr):
        return None

    spread = pd.Series(a - hr * b, index=idx)
    tests = _run_coint_tests(spread, eg_pval)
    tests["n_bars"] = n
    tests["hedge_ratio"] = hr
    tests["window_start"] = idx.min()
    tests["window_end"] = idx.max()
    return tests


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== bounded_lookback_primary_screen.py: bounded-recent-lookback EG/KPSS/PO "
             "as primary screen, vs. full-sample ===")

    rows = []
    for tf_dir in TF_DIRS:
        results_dir, is_stale = resolve_tf_results_dir(tf_dir)
        pairs_path = os.path.join(results_dir, "pairs.parquet")
        if not os.path.exists(pairs_path):
            continue
        if is_stale:
            log.info("NOTE %s: no live output/results/%s, using archived %s instead",
                      tf_dir, tf_dir, results_dir)
        tf_label = DIR_TO_LABEL[tf_dir]
        pairs_df = pd.read_parquet(pairs_path)

        for _, row in pairs_df.iterrows():
            sym_a, sym_b = row["symbol_a"], row["symbol_b"]
            df_a, df_b = load_aligned_pair(sym_a, sym_b, tf_label)
            if df_a is None or df_b is None or "close" not in df_a.columns or "close" not in df_b.columns:
                log.warning("SKIP %s/%s@%s: could not load aligned pair", sym_a, sym_b, tf_label)
                continue

            # align_pair_dataframes does not guarantee identical df_a/df_b length —
            # explicitly intersect indices before building arrays (found live: a
            # 24-row mismatch on AME/MAR@1h crashed the naive same-length assumption).
            common_idx = df_a.index.intersection(df_b.index)
            df_a = df_a.loc[common_idx]
            df_b = df_b.loc[common_idx]

            close_a = clean_close(df_a, exclude_flags=(GapFlag.DATA_GAP,))
            close_b = clean_close(df_b, exclude_flags=(GapFlag.DATA_GAP,))
            with np.errstate(invalid="ignore", divide="ignore"):
                log_a = np.where(close_a > 0, np.log(close_a), np.nan)
                log_b = np.where(close_b > 0, np.log(close_b), np.nan)
            idx = common_idx

            full = eg_tier_on_window(log_a, log_b, idx)
            if full is None:
                log.warning("SKIP %s/%s@%s: insufficient overlap for full-sample EG", sym_a, sym_b, tf_label)
                continue

            rec = {
                "symbol_a": sym_a, "symbol_b": sym_b, "tf_label": tf_label,
                "full_n_bars": full["n_bars"], "full_eg_pval": full["eg_pval"],
                "full_kpss_pval": full["kpss_pval"], "full_po_pval": full["po_pval"],
                "full_tier": full["stats_tier"],
                "full_span_years": (full["window_end"] - full["window_start"]).days / 365.25,
            }

            for yrs in _LOOKBACK_YEARS:
                cutoff = pd.Timestamp(idx.max()) - pd.Timedelta(days=int(yrs * 365.25))
                bounded_mask = idx >= cutoff
                bounded = eg_tier_on_window(log_a[bounded_mask], log_b[bounded_mask], idx[bounded_mask])
                prefix = f"y{yrs}"
                if bounded is None:
                    rec[f"{prefix}_tier"] = "insufficient_data"
                    rec[f"{prefix}_eg_pval"] = np.nan
                    rec[f"{prefix}_n_bars"] = int(bounded_mask.sum())
                    rec[f"{prefix}_is_noop"] = rec["full_span_years"] <= yrs
                    continue
                rec[f"{prefix}_n_bars"] = bounded["n_bars"]
                rec[f"{prefix}_eg_pval"] = bounded["eg_pval"]
                rec[f"{prefix}_kpss_pval"] = bounded["kpss_pval"]
                rec[f"{prefix}_po_pval"] = bounded["po_pval"]
                rec[f"{prefix}_tier"] = bounded["stats_tier"]
                # A "no-op" lookback means the pair's own history is already
                # shorter than the requested window — full-sample IS the
                # bounded window, so tier agreement there is definitional,
                # not evidence of robustness. Flag it so it isn't miscounted.
                rec[f"{prefix}_is_noop"] = bounded["n_bars"] >= full["n_bars"] * 0.98

            rec["tier_survives_5y"] = rec.get("y5_tier") in ("gold", "silver")
            rec["tier_survives_10y"] = rec.get("y10_tier") in ("gold", "silver")
            rows.append(rec)
            log.info("%s/%s@%s: full=%s (p=%.4f, %.1fy)  5y=%s (p=%s)  10y=%s (p=%s)%s",
                      sym_a, sym_b, tf_label, rec["full_tier"], rec["full_eg_pval"],
                      rec["full_span_years"],
                      rec.get("y5_tier"), f"{rec.get('y5_eg_pval'):.4f}" if pd.notna(rec.get("y5_eg_pval")) else "n/a",
                      rec.get("y10_tier"), f"{rec.get('y10_eg_pval'):.4f}" if pd.notna(rec.get("y10_eg_pval")) else "n/a",
                      "  [5y window is a no-op, full history < 5y]" if rec.get("y5_is_noop") else "")

    if not rows:
        log.warning("No confirmed pairs found across any timeframe — nothing to screen.")
        return

    result_df = pd.DataFrame(rows)
    n_total = len(result_df)
    n_meaningful_5y = int((~result_df.get("y5_is_noop", pd.Series([True] * n_total))).sum())
    n_meaningful_10y = int((~result_df.get("y10_is_noop", pd.Series([True] * n_total))).sum())
    n_downgraded_5y = int(((result_df.get("y5_is_noop") == False) & (~result_df["tier_survives_5y"])).sum())
    n_downgraded_10y = int(((result_df.get("y10_is_noop") == False) & (~result_df["tier_survives_10y"])).sum())

    log.info("\n--- Summary across %d confirmed pairs ---", n_total)
    log.info("  Pairs with real (non-no-op) 5y window:  %d", n_meaningful_5y)
    log.info("  Pairs with real (non-no-op) 10y window: %d", n_meaningful_10y)
    log.info("  Pairs downgraded to bronze/fail under 5y-as-primary:  %d/%d", n_downgraded_5y, n_meaningful_5y)
    log.info("  Pairs downgraded to bronze/fail under 10y-as-primary: %d/%d", n_downgraded_10y, n_meaningful_10y)
    log.info("\nHonest scope note: this re-screens the ALREADY-confirmed set on a bounded window; it "
             "does not rediscover candidates from scratch under a bounded-lookback-primary regime, "
             "which would require re-running the full CointScanner pipeline on truncated data.")

    os.makedirs(_OUT_DIR, exist_ok=True)
    out_path = os.path.join(_OUT_DIR, "bounded_lookback_primary_screen.parquet")
    result_df.to_parquet(out_path, index=False)
    log.info("Saved -> %s", out_path)

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("bounded_lookback_primary_screen.py complete (%.1f min)", runtime)


if __name__ == "__main__":
    main()
