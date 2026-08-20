"""
research/liquidity_bar_masking.py -- shared bar-level liquidity utility, per
Ross's direct request (2026-08-14): "skip trades and avoid use of illiquid
bars. counting illiquid bars will falsely spike our cointegration number."

Real mechanism this addresses: a day with near-zero trading volume often
shows near-zero price movement too (stale/thin quotes, no real price
discovery) -- if BOTH legs of a pair have illiquid days on the SAME dates,
those days can spuriously look "cointegrated" (both prices barely move
together) even though nothing about the underlying economic relationship is
being observed that day. Counting these bars in a correlation/cointegration
calculation, or trading on them, both risk contaminating the result with an
artifact of thin liquidity, not genuine co-movement.

REAL MECHANISM, VERIFIED DIRECTLY (not assumed) -- the first-pass hypothesis
tried while building this was "stale/flat returns on shared illiquid days
inflate Pearson correlation of RETURNS." A synthetic check disproved this:
Pearson correlation is scale-normalized (divides by each series' own std),
so a block of exact-zero-return days does not clearly bias it in either
direction -- adding zero-return points reduces both the covariance numerator
AND each series' own variance roughly proportionally. The REAL, verified
mechanism is different and more specific to pairs trading: on a genuinely
frozen/stale block, the SPREAD's own variance collapses toward zero (direct
check: 0.133 liquid-only spread std vs. 5.5e-17 during a frozen illiquid
block -- essentially exactly zero) -- because a stale price simply isn't
updating, not because the pair is genuinely mean-reverting. This is exactly
what an ADF/EG cointegration test reads as "very strong mean reversion" (low
variance around the mean spread level) -- an artifact of thin/no trading,
not a real economic relationship. `recompute_correlation_bar_masked` reports
this via the spread-level standard deviation and variance-ratio comparison,
which is the mechanistically correct, directly-relevant quantity for
cointegration/half-life estimation -- not the correlation-of-returns framing
this file started with.

Two real uses, both built here:
  1. `liquid_bar_mask(symbol, threshold)` -- a per-symbol boolean Series,
     True on days where that symbol's OWN dollar volume clears the
     threshold. Reusable by both a diagnostic recomputation (this file's
     own `recompute_correlation_bar_masked`) and backtest.py's real entry
     filter (research/../backtest.py's --storm-liquidity-bar-filter).
  2. `recompute_correlation_bar_masked(sym_a, sym_b, threshold)` -- computes,
     over the SAME shared date range, twice (naive = every bar, masked =
     excluding any bar where EITHER leg is individually illiquid): Pearson
     correlation of returns (reported for completeness, though the direct
     test above shows this isn't the mechanism that matters) AND the
     SPREAD-LEVEL standard deviation (the mechanistically real quantity --
     a naive spread_std well below the masked spread_std signals the
     illiquid bars are artificially suppressing apparent spread variance,
     which would make a cointegration/ADF test look more significant than
     the true underlying process supports).

Uses data.py's cached {symbol}_1day.parquet files (close, volume) -- the
same domestic universe backtest.py already trades, not the international
data Thread I built (a separate universe with its own cache).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config


def liquid_bar_mask(symbol: str, threshold: float = None, cache_dir: str = None) -> pd.Series:
    """True on days where `symbol`'s own dollar volume (close x volume)
    clears `threshold`. Empty Series if the symbol's cache is missing or
    lacks close/volume columns."""
    threshold = threshold if threshold is not None else Config.DATA.MIN_DOLLAR_VOLUME
    cache_dir = cache_dir or Config.DATA.CACHE_DIR
    path = os.path.join(cache_dir, f"{symbol}_1day.parquet")
    if not os.path.exists(path):
        return pd.Series(dtype=bool)
    df = pd.read_parquet(path)
    if "close" not in df.columns or "volume" not in df.columns:
        return pd.Series(dtype=bool)
    df.index = pd.to_datetime(df.index)
    dollar_vol = (df["close"] * df["volume"]).replace([np.inf, -np.inf], np.nan)
    return dollar_vol >= threshold


def recompute_correlation_bar_masked(sym_a: str, sym_b: str, threshold: float = None,
                                      cache_dir: str = None) -> dict:
    """Pearson correlation of daily log-returns over the pair's shared date
    range, computed TWICE: once using every bar ("naive"), once excluding
    any bar where EITHER leg is individually illiquid ("masked"). Reports
    both plus the delta, so the claim ("illiquid bars inflate the number")
    is directly checkable rather than assumed."""
    threshold = threshold if threshold is not None else Config.DATA.MIN_DOLLAR_VOLUME
    cache_dir = cache_dir or Config.DATA.CACHE_DIR
    path_a = os.path.join(cache_dir, f"{sym_a}_1day.parquet")
    path_b = os.path.join(cache_dir, f"{sym_b}_1day.parquet")
    if not (os.path.exists(path_a) and os.path.exists(path_b)):
        return {"ok": False, "reason": "missing_cache"}

    df_a = pd.read_parquet(path_a)
    df_b = pd.read_parquet(path_b)
    df_a.index = pd.to_datetime(df_a.index)
    df_b.index = pd.to_datetime(df_b.index)

    common_idx = df_a.index.intersection(df_b.index)
    if len(common_idx) < 30:
        return {"ok": False, "reason": "insufficient_overlap", "n_bars": len(common_idx)}

    ret_a = np.log(df_a.loc[common_idx, "close"]).diff()
    ret_b = np.log(df_b.loc[common_idx, "close"]).diff()
    spread = np.log(df_a.loc[common_idx, "close"]) - np.log(df_b.loc[common_idx, "close"])

    mask_a = liquid_bar_mask(sym_a, threshold, cache_dir).reindex(common_idx, fill_value=False)
    mask_b = liquid_bar_mask(sym_b, threshold, cache_dir).reindex(common_idx, fill_value=False)
    both_liquid = mask_a & mask_b

    naive = pd.DataFrame({"a": ret_a, "b": ret_b}).dropna()
    masked = pd.DataFrame({"a": ret_a, "b": ret_b})[both_liquid].dropna()

    if len(naive) < 30:
        return {"ok": False, "reason": "insufficient_overlap", "n_bars": len(naive)}

    naive_corr = float(naive["a"].corr(naive["b"]))
    n_illiquid_bars = int((~both_liquid).sum())
    illiquid_frac = n_illiquid_bars / len(common_idx)

    # Spread-level standard deviation -- the mechanistically real quantity for cointegration/
    # half-life estimation (see module docstring: verified directly that this, not correlation
    # of returns, is what illiquid/stale bars actually distort).
    naive_spread_std = float(spread.dropna().std())
    masked_spread = spread[both_liquid].dropna()
    masked_spread_std = float(masked_spread.std()) if len(masked_spread) >= 2 else None
    spread_std_ratio = (naive_spread_std / masked_spread_std) if masked_spread_std else None

    if len(masked) < 30:
        return {
            "ok": True, "naive_corr": naive_corr, "masked_corr": None, "delta": None,
            "naive_spread_std": naive_spread_std, "masked_spread_std": masked_spread_std,
            "spread_std_ratio": spread_std_ratio,
            "n_bars_total": len(naive), "n_bars_masked_out": n_illiquid_bars,
            "illiquid_frac": illiquid_frac,
            "note": "too few liquid-only bars remain for a masked correlation estimate",
        }

    masked_corr = float(masked["a"].corr(masked["b"]))
    return {
        "ok": True, "naive_corr": naive_corr, "masked_corr": masked_corr,
        "delta": masked_corr - naive_corr,
        "naive_spread_std": naive_spread_std, "masked_spread_std": masked_spread_std,
        "spread_std_ratio": spread_std_ratio,
        "n_bars_total": len(naive), "n_bars_masked_out": n_illiquid_bars,
        "n_bars_used_masked": len(masked), "illiquid_frac": illiquid_frac,
    }


def main():
    import argparse
    p = argparse.ArgumentParser(description="Bar-masked correlation recomputation for Purity pairs")
    p.add_argument("--pairs-file", default="output/research/purity_pairs.parquet")
    p.add_argument("--threshold", type=float, default=None)
    args = p.parse_args()

    pairs = pd.read_parquet(args.pairs_file)
    results = []
    for _, row in pairs.drop_duplicates(subset=["symbol_a", "symbol_b"]).iterrows():
        r = recompute_correlation_bar_masked(row["symbol_a"], row["symbol_b"], args.threshold)
        if r.get("ok"):
            r["symbol_a"] = row["symbol_a"]
            r["symbol_b"] = row["symbol_b"]
            results.append(r)

    out = pd.DataFrame(results)
    if out.empty:
        print("No pairs produced a valid comparison.")
        return

    with_ratio = out.dropna(subset=["spread_std_ratio"])
    print(f"=== Bar-masked vs naive SPREAD VARIANCE (the mechanistically real quantity -- see "
          f"module docstring for why correlation-of-returns was checked and ruled out), "
          f"{len(out)} pairs ({len(with_ratio)} with a computable masked estimate) ===")
    print(f"  mean illiquid_frac across pairs: {out['illiquid_frac'].mean():.3f}")
    if len(with_ratio):
        print(f"  mean spread_std_ratio (naive/masked): {with_ratio['spread_std_ratio'].mean():.4f} "
              f"(< 1.0 means naive spread std UNDERSTATES the true, liquid-only variance -- "
              f"the artificial-stability effect)")
        n_suppressed = (with_ratio["spread_std_ratio"] < 0.95).sum()
        print(f"  pairs where naive spread variance is MEANINGFULLY suppressed "
              f"(ratio < 0.95): {n_suppressed}/{len(with_ratio)} "
              f"({n_suppressed/len(with_ratio)*100:.1f}%)")

    with_delta = out.dropna(subset=["delta"])
    if len(with_delta):
        print(f"  (for reference) mean correlation delta (masked - naive): "
              f"{with_delta['delta'].mean():+.4f} -- not the primary metric, see docstring")

    out.to_parquet("output/research/liquidity_bar_masked_correlation.parquet", index=False)
    print("\nSaved -> output/research/liquidity_bar_masked_correlation.parquet")


if __name__ == "__main__":
    main()
