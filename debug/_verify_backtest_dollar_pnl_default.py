"""
Regression test for code-review B2/B3 made the DEFAULT (Ross, 2026-10-03: "dollar P&L the default everywhere; legacy
only behind an explicit --legacy-pnl flag labelled known-wrong"). Before: backtest.py's trades, per-pair metrics and
--capital-sim (portfolio_sim.replay_portfolio, default pnl_mode="legacy") used spread-unit P&L with a hedge ratio
re-estimated every bar; dollar P&L existed only as an opt-in column set.
Checks (synthetic prices, hand-computed answer):
  1. backtest.apply_pnl_basis exists and converts a daily trade to dollars: long A 100->110, B 50->52, beta 1.5,
     $10,000 notional -> gross = 10,000 * (0.10 - 1.5 * 0.04) = $400; cost per pnl_dollar's formula;
  2. the spread-unit values are kept in pnl_legacy_*; pnl_basis == "dollar"; notional recorded;
  3. a trade that cannot be priced (here: intraday with no intraday price file; intraday marking exists since
     2026-10-03) -> DROPPED and counted {"missing_price": 1}, never kept at a spread-unit value;
  4. legacy=True keeps the spread-unit values, labelled "legacy_known_wrong";
  5. portfolio_sim.replay_portfolio defaults to pnl_mode="dollar";
  6. re-pricing already-converted trades with add_dollar_pnl gives the identical dollar P&L (so research/
     strategy_search.py, which prices its own trades, is unchanged by the earlier conversion);
  7. portfolio_sim.ensure_dollar_columns reuses converted trades' dollar P&L.
Run: python debug/_verify_backtest_dollar_pnl_default.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import pnl_dollar
import portfolio_sim
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        from backtest import Trade, apply_pnl_basis
    except ImportError as e:
        check("apply_pnl_basis_exists", False, str(e)); _finish(); return
    idx = pd.bdate_range("2024-01-02", periods=30)
    A = pd.DataFrame({"close": 100.0, "tr": 100.0}, index=idx); A.loc[idx[10]:, ["close", "tr"]] = 110.0
    B = pd.DataFrame({"close": 50.0, "tr": 50.0}, index=idx); B.loc[idx[10]:, ["close", "tr"]] = 52.0
    prices = {"SYNA": A, "SYNB": B}
    orig = pnl_dollar.load_daily_prices
    pnl_dollar.load_daily_prices = lambda s: prices.get(s)
    orig_i = pnl_dollar.load_intraday_prices
    pnl_dollar.load_intraday_prices = lambda s, tf: None
    try:
        def mk(tf="1D"):
            return Trade(tf=tf, symbol_a="SYNA", symbol_b="SYNB", hedge_method="ols", hedge_ratio=1.5,
                         entry_time=idx[2], entry_z=-3.1, entry_spread=-0.2, side="long", n_shares_a=100,
                         n_shares_b=150.0, half_life_at_entry=10.0, hurst_at_entry=0.4, exit_time=idx[15],
                         exit_z=0.0, exit_spread=0.0, exit_reason="signal_exit", pnl_gross=20.0, pnl_cost=1.0,
                         pnl_net=19.0)
        kept, dropped = apply_pnl_basis([mk(), mk("1h")])
        N_a, beta = 10_000.0, 1.5
        gross = N_a * (0.10 - beta * 0.04)
        n_a, n_b = N_a / 100.0, beta * N_a / 50.0
        cost = Config.BACKTEST.COMMISSION_PER_SHARE * (n_a + n_b) * 2 + Config.BACKTEST.SLIPPAGE_BPS / 1e4 * N_a * (1 + beta) * 2
        t = kept[0] if kept else None
        check("1.dollar_values", t is not None and np.isclose(t.pnl_gross, gross) and np.isclose(t.pnl_cost, cost)
              and np.isclose(t.pnl_net, gross - cost), f"gross={getattr(t, 'pnl_gross', None)} expected {gross}; "
              f"net={getattr(t, 'pnl_net', None)} expected {gross - cost}")
        check("2.legacy_kept_and_labelled", t is not None and t.pnl_legacy_net == 19.0 and t.pnl_legacy_gross == 20.0
              and t.pnl_basis == "dollar" and np.isclose(t.notional_dollar_entry, N_a * (1 + beta)))
        check("3.unpriceable_dropped_and_counted", len(kept) == 1 and dropped == {"missing_price": 1}, f"dropped={dropped}")
        lk, ld = apply_pnl_basis([mk()], legacy=True)
        check("4.legacy_flag", lk[0].pnl_net == 19.0 and lk[0].pnl_basis == "legacy_known_wrong" and ld == {})
        default = inspect.signature(portfolio_sim.replay_portfolio).parameters["pnl_mode"].default
        check("5.replay_default_dollar", default == "dollar", f"default={default!r}")
        T = pd.DataFrame([vars(x) for x in kept])
        again = pnl_dollar.add_dollar_pnl(T)
        check("6.reprice_identical", np.isclose(again["pnl_dollar_net"].iloc[0], T["pnl_net"].iloc[0]))
        E = portfolio_sim.ensure_dollar_columns(T)
        check("7.ensure_dollar_reuses", len(E) == 1 and np.isclose(E["pnl_dollar_net"].iloc[0], gross - cost))
    finally:
        pnl_dollar.load_daily_prices = orig
        pnl_dollar.load_intraday_prices = orig_i
    _finish()


def _finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
