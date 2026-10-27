"""
Synthetic checks for the per-share commission in pnl_dollar.add_dollar_pnl (2026-10-26; edge-accounting review).

Bug: the share count behind the commission was N_a / P_adj, with P_adj the split-ADJUSTED close. PEP on 1931-08-03
has an adjusted close of $0.0148 (real price $5.25, adjustment factor 354), so a $10,000 leg counted as 674,285 shares
and paid ~$6,700 commission per round trip instead of ~$19. Post-period splits inflate it in the PIT era too (NVDA
2015-06-01: 17,873 shares per $10k instead of 447).
Fix: commission shares use the price actually traded, share_px = adjusted close x volume_adj_factor (the cache's
CRSP / Compustat split factor; adjusted close is smooth through a split, close x factor jumps by the split ratio).
Without a factor (yfinance files, missing values) share_px falls back to the adjusted close (old behaviour).

Checks:
  1. share_px present -> commission from real share counts (hand-computed), not adjusted ones;
  2. share_px absent -> commission from the adjusted close (unchanged behaviour);
  3. gross P&L does not depend on share_px (returns come from the total-return series);
  4. load_daily_prices: US file -> share_px = close x volume_adj_factor; a missing factor -> close;
  5. load_daily_prices: Compustat Global file -> share_px = close_usd x volume_adj_factor;
  6. no volume_adj_factor column (data_wrds.py never writes it; a re-fetched file) -> factor = volume / volume_raw;
  7. a leg priced on the adjusted close (no factor) is flagged per trade (pnl_dollar_share_fallback), not silent.

Run: python debug/_verify_pnl_dollar_share_count.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pnl_dollar

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


IDX = pd.bdate_range("2026-03-02", periods=5)


def _frame(adj, share=None):
    v = np.asarray(adj, float)
    d = pd.DataFrame({"close": v, "tr": v}, index=IDX)
    if share is not None:
        d["share_px"] = np.asarray(share, float)
    d.attrs["usd"] = True
    return d


def _trade(a, b, beta=1.0):
    return pd.DataFrame([dict(tf="1D", n_shares_a=100, side="long", symbol_a=a, symbol_b=b, hedge_ratio=beta,
                              entry_time=IDX[0], exit_time=IDX[-1])])


def main():
    # adjusted closes 0.01 / 0.02 (factor 500): real prices 5 / 10
    prices = {
        "ZZADJA": _frame([0.01, 0.0101, 0.0102, 0.0103, 0.011], share=[5.0, 5.05, 5.1, 5.15, 5.5]),
        "ZZADJB": _frame([0.02, 0.02, 0.02, 0.02, 0.021], share=[10.0, 10.0, 10.0, 10.0, 10.5]),
        "ZZNOFA": _frame([0.01, 0.0101, 0.0102, 0.0103, 0.011]),
        "ZZNOFB": _frame([0.02, 0.02, 0.02, 0.02, 0.021]),
    }
    loader = lambda s: prices.get(s)
    kw = dict(commission_per_share=0.005, slippage_bps=0.0, price_loader=loader, check_holes=False)

    # 1. real shares: n_a = 10,000 / 5 = 2,000; n_b = 0.8 * 10,000 / 10 = 800; cost = 0.005 * 2,800 * 2 = 28.0
    o = pnl_dollar.add_dollar_pnl(_trade("ZZADJA", "ZZADJB", 0.8), **kw)
    c = float(o["pnl_dollar_cost"].iloc[0])
    check("1 commission from real share counts", abs(c - 28.0) < 1e-9, f"cost {c:.4f} (expected 28.0; adjusted shares give 14,000)")
    check("1b n_shares_b_dollar is real shares", abs(float(o["n_shares_b_dollar"].iloc[0]) - 800.0) < 1e-9,
          f"{float(o['n_shares_b_dollar'].iloc[0]):.1f}")

    # 2. no factor: n_a = 10,000 / 0.01 = 1,000,000; n_b = 0.8 * 10,000 / 0.02 = 400,000; cost = 0.005 * 1.4e6 * 2
    o2 = pnl_dollar.add_dollar_pnl(_trade("ZZNOFA", "ZZNOFB", 0.8), **kw)
    c2 = float(o2["pnl_dollar_cost"].iloc[0])
    check("2 no factor -> adjusted close (unchanged)", abs(c2 - 14_000.0) < 1e-6, f"cost {c2:.2f}")

    # 3. gross identical with or without share_px: 10,000 * (0.10 - 0.8 * 0.05) = 600
    g1, g2 = float(o["pnl_dollar_gross"].iloc[0]), float(o2["pnl_dollar_gross"].iloc[0])
    check("3 gross independent of share_px", abs(g1 - 600.0) < 1e-6 and abs(g2 - 600.0) < 1e-6, f"{g1:.4f} {g2:.4f}")

    # 4/5. loader on cache-shaped files
    tmp = tempfile.mkdtemp()
    old_dir, old_cache = pnl_dollar._WRDS_DIR, dict(pnl_dollar._cache)
    try:
        pnl_dollar._WRDS_DIR = tmp
        pnl_dollar._cache.clear()
        us = pd.DataFrame({"close": [0.0148, 0.0150, 30.0], "close_total_return": [0.0148, 0.0150, 30.5],
                           "volume": [1e5, 1e5, 1e5], "volume_raw": [282.5, 282.5, 1e5],
                           "volume_adj_factor": [354.0, np.nan, 1.0]},
                          index=pd.DatetimeIndex(["1931-08-03", "1931-08-04", "2005-06-01"], name="dlycaldt"))
        us.to_parquet(os.path.join(tmp, "ZZUSF_1D.parquet"))
        F = pnl_dollar.load_daily_prices("ZZUSF")
        sp = F["share_px"].to_numpy() if F is not None and "share_px" in F.columns else None
        check("4 US share_px = close x factor; missing factor -> NaN (flagged fallback downstream)",
              sp is not None and np.allclose(sp, [0.0148 * 354.0, np.nan, 30.0], equal_nan=True), f"{sp}")
        intl = pd.DataFrame({"close": [400.0, 100.0], "close_usd": [4.0, 1.0], "volume": [1e4, 4e4],
                             "volume_raw": [2.5e3, 4e4], "volume_adj_factor": [4.0, 1.0]},
                            index=pd.DatetimeIndex(["2024-03-27", "2024-03-28"], name="datadate"))
        intl.to_parquet(os.path.join(tmp, "GVKEY999999_01W_1D.parquet"))
        G = pnl_dollar.load_daily_prices("GVKEY999999_01W")
        sg = G["share_px"].to_numpy() if G is not None and "share_px" in G.columns else None
        check("5 Compustat share_px = close_usd x factor", sg is not None and np.allclose(sg, [16.0, 1.0]), f"{sg}")
        # 6. a file re-fetched by data_wrds.py has volume_raw but no volume_adj_factor (review 2026-10-26): the factor
        #    is volume / volume_raw, so the fix must not silently fall back to the adjusted close
        us.drop(columns=["volume_adj_factor"]).to_parquet(os.path.join(tmp, "ZZREF_1D.parquet"))
        H = pnl_dollar.load_daily_prices("ZZREF")
        sh = H["share_px"].to_numpy() if H is not None and "share_px" in H.columns else None
        check("6 no factor column -> volume / volume_raw", sh is not None and
              np.allclose(sh, [0.0148 * 1e5 / 282.5, 0.0150 * 1e5 / 282.5, 30.0]), f"{sh}")
    finally:
        pnl_dollar._WRDS_DIR = old_dir
        pnl_dollar._cache.clear()
        pnl_dollar._cache.update(old_cache)

    # 7. a fallback to the adjusted close is flagged per trade, not silent (review 2026-10-26)
    fl = o["pnl_dollar_share_fallback"].tolist() if "pnl_dollar_share_fallback" in o.columns else None
    fl2 = o2["pnl_dollar_share_fallback"].tolist() if "pnl_dollar_share_fallback" in o2.columns else None
    check("7 share-count fallback flagged", fl == [False] and fl2 == [True], f"{fl} {fl2}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
