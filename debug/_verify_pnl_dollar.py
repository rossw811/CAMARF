"""
Synthetic ground-truth checks for pnl_dollar.py (2026-09-26, fixes code-review B2/B3).

B2: backtest.py's gross P&L = side * (exit_spread - entry_spread) * n_shares_a, with
spread_t = log_a - beta_t * log_b and beta_t re-estimated every bar, so it contains the term
(beta_entry - beta_exit) * log_b_exit that no held position earns. B3: that gross is in log-units
x shares while costs are dollars.

pnl_dollar.add_dollar_pnl() marks both legs at real prices with shares fixed at entry:
  N_a = n_shares_a * P_a(entry);  leg-B dollar exposure = beta_entry * N_a
  gross = side * N_a * (r_a - beta_entry * r_b),  r = total-return over [entry, exit]
  cost  = commission * (n_a + n_b) * 2 + slippage_bps/1e4 * (N_a + |beta| N_a) * 2

Checks (hand-computed):
  1. flat prices + a drifting beta -> dollar gross exactly 0 (the old formula would not be);
  2. known leg returns -> exact dollar gross and cost;
  3. short side flips the sign;
  4. a non-USD leg (Compustat Global label / exchange suffix) -> NaN with a reason, not a number;
  5. missing price -> NaN with a reason.

Run: python debug/_verify_pnl_dollar.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pnl_dollar

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _series(values, start="2026-03-02"):
    idx = pd.bdate_range(start, periods=len(values))
    v = np.asarray(values, float)
    return pd.DataFrame({"close": v, "tr": v}, index=idx)


def main():
    prices = {
        "AAA": _series([100, 100, 100, 100, 100]),
        "BBB": _series([50, 50, 50, 50, 50]),
        "CCC": _series([100, 101, 103, 105, 110]),   # +10% entry->exit (day0 -> day4)
        "DDD": _series([40, 40, 41, 41, 42]),        # +5%
    }
    loader = lambda s: prices.get(s)
    base = dict(tf="1D", n_shares_a=100, side="long",
                entry_time=pd.Timestamp("2026-03-02"), exit_time=pd.Timestamp("2026-03-06"))
    trades = pd.DataFrame([
        dict(base, symbol_a="AAA", symbol_b="BBB", hedge_ratio=1.3),      # flat prices
        dict(base, symbol_a="CCC", symbol_b="DDD", hedge_ratio=0.8),      # known returns
        dict(base, symbol_a="CCC", symbol_b="DDD", hedge_ratio=0.8, side="short"),
        dict(base, symbol_a="7267.T", symbol_b="DDD", hedge_ratio=0.8),   # non-USD leg
        dict(base, symbol_a="GVKEY001166_01W", symbol_b="DDD", hedge_ratio=0.8),
        dict(base, symbol_a="ZZZ", symbol_b="DDD", hedge_ratio=0.8),      # no price file
    ])
    before = trades.copy()
    out = pnl_dollar.add_dollar_pnl(trades, commission_per_share=0.005, slippage_bps=5.0, price_loader=loader,
                                   sizing="shares")
    # fixed-notional sizing: N_a = $10,000 regardless of price -> for CCC (P=100) identical to 100 shares;
    # for a $0.42 stock it must still be a $10,000 position, not $42.
    prices["PENNY"] = _series([0.42, 0.42, 0.42, 0.42, 0.462])  # +10%
    fx = pnl_dollar.add_dollar_pnl(pd.DataFrame([dict(base, symbol_a="PENNY", symbol_b="DDD", hedge_ratio=0.8)]),
                                  commission_per_share=0.0, slippage_bps=0.0, price_loader=loader)
    check("fixed_notional.penny_is_10k_position", abs(fx.iloc[0]["pnl_dollar_gross"] - 600.0) < 1e-6,
          f"{fx.iloc[0]['pnl_dollar_gross']}")

    r0, r1, r2, r3, r4, r5 = (out.iloc[i] for i in range(6))
    check("flat_prices.gross_zero", r0["pnl_dollar_gross"] == 0.0, f"{r0['pnl_dollar_gross']}")
    # N_a = 100*100 = 10,000; r_a = 0.10, r_b = 0.05; gross = 10,000*(0.10 - 0.8*0.05) = 600
    check("known.gross_600", abs(r1["pnl_dollar_gross"] - 600.0) < 1e-9, f"{r1['pnl_dollar_gross']}")
    # n_b = 0.8*10,000/40 = 200 shares; commission = 0.005*(100+200)*2 = 3.0;
    # slippage = 5e-4*(10,000 + 8,000)*2 = 18.0 -> cost 21.0
    check("known.cost_21", abs(r1["pnl_dollar_cost"] - 21.0) < 1e-9, f"{r1['pnl_dollar_cost']}")
    check("known.net", abs(r1["pnl_dollar_net"] - 579.0) < 1e-9, f"{r1['pnl_dollar_net']}")
    check("known.n_b_dollar_neutral", abs(r1["n_shares_b_dollar"] - 200.0) < 1e-9)
    check("known.notional", abs(r1["notional_dollar_entry"] - 18_000.0) < 1e-9, f"{r1['notional_dollar_entry']}")
    check("short.sign_flips", abs(r2["pnl_dollar_gross"] + 600.0) < 1e-9, f"{r2['pnl_dollar_gross']}")
    check("non_usd_suffix.nan", np.isnan(r3["pnl_dollar_net"]) and r3["pnl_dollar_status"] == "non_usd_leg",
          f"{r3['pnl_dollar_status']}")
    check("non_usd_gvkey.nan", np.isnan(r4["pnl_dollar_net"]) and r4["pnl_dollar_status"] == "non_usd_leg")
    check("missing_price.nan", np.isnan(r5["pnl_dollar_net"]) and r5["pnl_dollar_status"] == "missing_price",
          f"{r5['pnl_dollar_status']}")
    check("input_frame_not_mutated", trades.equals(before) and "pnl_dollar_net" not in trades.columns)

    # Compustat Global leg that HAS been converted to USD (close_usd, R1.1) must now be priced, not rejected.
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="pnl_usd_")
    orig_dir = pnl_dollar._WRDS_DIR
    try:
        pnl_dollar._WRDS_DIR = tmp
        pnl_dollar._cache.clear()
        ix = pd.bdate_range("2026-03-02", periods=5)
        pd.DataFrame({"close": [1500.0] * 5, "close_usd": [10.0, 10.0, 10.0, 10.0, 11.0]}, index=ix).to_parquet(
            os.path.join(tmp, "GVKEY000009_01W_1D.parquet"))
        pd.DataFrame({"close": [40.0] * 5, "close_total_return": [40.0] * 5}, index=ix).to_parquet(
            os.path.join(tmp, "USDLEG_1D.parquet"))
        g = pnl_dollar.add_dollar_pnl(pd.DataFrame([dict(base, symbol_a="GVKEY000009_01W", symbol_b="USDLEG", hedge_ratio=0.5)]),
                                      commission_per_share=0.0, slippage_bps=0.0)
        check("usd_converted_global_leg_priced", g.iloc[0]["pnl_dollar_status"] == "ok"
              and abs(g.iloc[0]["pnl_dollar_gross"] - 1000.0) < 1e-6, f"{g.iloc[0][['pnl_dollar_status', 'pnl_dollar_gross']].to_dict()}")
    finally:
        pnl_dollar._WRDS_DIR = orig_dir
        pnl_dollar._cache.clear()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
