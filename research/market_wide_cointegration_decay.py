"""
research/market_wide_cointegration_decay.py -- Scope 2 from Ross's 2026-08-23 request: is the
RATE/DENSITY of cointegration across the whole universe declining over calendar time? A genuine
gap, distinct from the already-done Do & Faff (2010) era-decay replication (PAPER.md Sec 7.11),
which tested SHARPE/TRADE-PERFORMANCE decay for the confirmed-pair SET across eras -- a question
about whether the STRATEGY still works, not whether the MARKET still produces cointegrated pairs
at the same rate it used to.

REAL CONFOUND, already found and documented this session (docs/HANDOFF.md, Thread J's
static-vs-rolling-window discrepancy): confirmed-pair count scales MECHANICALLY with window
length and number of independent test opportunities, not just real market structure -- a
rolling-window scan with more independent rolls per pair mechanically raises the "at least one
hit" confirmation rate regardless of any real change in edge. Controlled here the same way
Thread J's own reconciliation controlled for it: every era uses the SAME fixed window length,
SAME correlation threshold, and SAME EG max_lag/BH-FDR alpha -- a genuine apples-to-apples
comparison across calendar time, not "did this era get more chances to find something."

Method, reusing production code directly (not reimplemented):
  1. Load the full universe once (universe_loader.load_full_universe).
  2. Slice every symbol's price series to each era's [start, end) date range.
  3. Build log returns, run UniverseFilter.chunked_pearson_matrix() for the correlation
     prefilter (same function the production pipeline and k-BAHC discovery both use).
  4. Candidate pairs above the SAME |rho| threshold in every era get EG-tested via
     analysis.py::_eg_worker (the same production per-pair test), then BH-FDR corrected via
     analysis.py::_benjamini_hochberg (same production correction).
  5. Report, per era: candidate-pool size, confirmed-pair count, and confirmed-pair count
     NORMALIZED by candidate-pool size (raw count alone conflates market change with
     universe-size change -- IPOs/delistings shift how many symbols even have data in each era).

HONEST LIMITATIONS, disclosed not hidden:
  - Survivorship: a symbol needs price history covering an era to be included in that era's
    universe at all -- delisted/not-yet-IPO'd symbols are structurally excluded from eras they
    don't span, the same survivorship caveat this project's other full-history work already
    carries (CLAUDE.md rule 6).
  - This uses the standard full-history EG methodology (autolag="aic", NOT the PIT-safe episodic
    methodology) -- a real, disclosed choice for comparability with the era-decay-replication
    precedent (PAPER.md Sec 7.11), not a claim that this is PIT-safe.
  - Era boundaries and window length are a real, disclosed methodological choice (see DEFAULT_ERAS
    below), not empirically re-derived from an optimality search.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from analysis import UniverseFilter, _eg_worker, _benjamini_hochberg
from config import Config
from universe_loader import load_full_universe

log_time = lambda: time.strftime("%Y-%m-%d %H:%M:%S")

# Non-overlapping, fixed-length (3yr) calendar eras -- a real, disclosed choice (see module
# docstring), not re-derived from an optimality search. Deliberately fixed-length across all
# four so window-length itself can never be the confound.
DEFAULT_ERAS = [
    ("2012-01-01", "2015-01-01"),
    ("2015-01-01", "2018-01-01"),
    ("2018-01-01", "2021-01-01"),
    ("2021-01-01", "2024-01-01"),
]
CORR_THRESHOLD = 0.40  # same default threshold analysis.py's own candidate gate uses
EG_MAX_LAG = Config.ANALYSIS.EG_MAX_LAG if hasattr(Config.ANALYSIS, "EG_MAX_LAG") else 10
FDR_ALPHA = 0.05


def _slice_era(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return df.loc[(df.index >= start) & (df.index < end)]


def run_era(symbols, price_data, start, end, min_bars=500):
    """One era's full cascade: slice -> log returns -> corr prefilter -> EG -> BH-FDR.
    Returns (n_candidates, n_confirmed)."""
    log_prices = {}
    for sym in symbols:
        df = price_data.get(sym)
        if df is None:
            continue
        sliced = _slice_era(df, start, end)
        if len(sliced) < min_bars:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            lp = np.log(sliced["close"].to_numpy(dtype=np.float64))
        lp[~np.isfinite(lp)] = np.nan
        log_prices[sym] = pd.Series(lp, index=sliced.index)

    if len(log_prices) < 2:
        return 0, 0

    aligned = pd.DataFrame(log_prices).ffill(limit=5)
    returns = aligned.diff().to_numpy().T  # (n_symbols, n_bars), matches chunked_pearson_matrix's contract
    era_symbols = list(aligned.columns)

    corr = UniverseFilter.chunked_pearson_matrix(returns, batch_size=1500)
    n = corr.shape[0]
    iu, ju = np.triu_indices(n, k=1)
    mask = np.abs(corr[iu, ju]) >= CORR_THRESHOLD
    cand_i, cand_j = iu[mask], ju[mask]
    n_candidates = len(cand_i)
    if n_candidates == 0:
        return 0, 0

    log_price_arr = aligned.to_numpy().T  # (n_symbols, n_bars)
    tasks = [
        (era_symbols[i], era_symbols[j], log_price_arr[i], log_price_arr[j], EG_MAX_LAG, "1D")
        for i, j in zip(cand_i, cand_j)
    ]
    results = [_eg_worker(t) for t in tasks]
    pvals = np.array([r["pvalue"] for r in results if r["ok"]])
    if pvals.size == 0:
        return n_candidates, 0
    rejected, _adj = _benjamini_hochberg(pvals, FDR_ALPHA)
    return n_candidates, int(rejected.sum())


def main():
    import argparse
    p = argparse.ArgumentParser(description="Market-wide cointegration density across calendar eras")
    p.add_argument("--limit-symbols", type=int, default=None,
                    help="Cap universe size for a fast smoke-test run (full universe if omitted).")
    args = p.parse_args()

    print(f"{log_time()}  Loading full universe (1D)...", flush=True)
    universe = load_full_universe(tf_label="1D")
    symbols = sorted(universe.keys())
    if args.limit_symbols:
        symbols = symbols[:args.limit_symbols]
    print(f"{log_time()}  {len(symbols)} symbols loaded", flush=True)

    rows = []
    for start, end in DEFAULT_ERAS:
        t0 = time.time()
        n_cand, n_conf = run_era(symbols, universe, start, end)
        dt = time.time() - t0
        frac = n_conf / n_cand if n_cand > 0 else float("nan")
        rows.append({"era_start": start, "era_end": end, "n_candidates": n_cand,
                      "n_confirmed": n_conf, "confirmed_fraction": frac, "runtime_s": dt})
        print(f"{log_time()}  [{start} -> {end}] candidates={n_cand} confirmed={n_conf} "
              f"fraction={frac:.5f} ({dt:.1f}s)", flush=True)

    out = pd.DataFrame(rows)
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "output", "research", "market_wide_cointegration_decay.parquet")
    out.to_parquet(out_path)
    print(f"\n{log_time()}  Saved: {out_path}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
