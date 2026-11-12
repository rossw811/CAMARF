"""Is the 10-25 -> 11-04 change in edge-accounting pnl_dollar_net the BUG-D121 commission fix alone?
Matched trades (tf, pair, entry, exit, side, hedge_ratio, n_shares_a) in old and new files. Recompute with current
pnl_dollar twice: as is (should equal the new file) and with _share_px forced to the adjusted close (the pre-fix share
count; should equal the old file). Gross and slippage are untouched by the fix, so if both match, the whole delta is
commission. Read-only; prints only."""
import os, sys
sys.path[:0] = [os.path.expanduser("~/CAMARF"), os.path.expanduser("~/CAMARF/research")]
os.chdir(os.path.expanduser("~/CAMARF"))
import numpy as np, pandas as pd
import parquet_io
import pnl_dollar

KEY = ["tf", "symbol_a", "symbol_b", "entry_time", "exit_time", "side"]
COLS = ["tf", "symbol_a", "symbol_b", "hedge_ratio", "entry_time", "exit_time", "side", "n_shares_a"]
orig_share_px = pnl_dollar._share_px
for arm in ("wh_k1", "wh_k2", "pit_k1", "pit_k2"):
    old = parquet_io.read_parquet(f"output/research/_superseded_edge_20261025/edge_accounting_trades_{arm}.parquet")
    new = parquet_io.read_parquet(f"output/research/edge_accounting_trades_{arm}.parquet")
    m = old.merge(new, on=KEY, suffixes=("_o", "_n"))
    same_in = np.isclose(m.hedge_ratio_o, m.hedge_ratio_n, rtol=0, atol=1e-12) & (m.n_shares_a_o == m.n_shares_a_n)
    m = m[same_in].reset_index(drop=True)
    T = m[KEY].copy(); T["hedge_ratio"] = m.hedge_ratio_n; T["n_shares_a"] = m.n_shares_a_n
    pnl_dollar._share_px = orig_share_px
    now = pnl_dollar.add_dollar_pnl(T[COLS], check_holes=False)
    pnl_dollar._share_px = lambda row: (float(row["close"]), True)
    pre = pnl_dollar.add_dollar_pnl(T[COLS], check_holes=False)
    pnl_dollar._share_px = orig_share_px
    ok = np.isfinite(m.pnl_dollar_net_o) & np.isfinite(m.pnl_dollar_net_n)
    d_file = (m.pnl_dollar_net_n - m.pnl_dollar_net_o)[ok]
    r_new = (now.pnl_dollar_net - m.pnl_dollar_net_n)[ok].abs()
    r_old = (pre.pnl_dollar_net - m.pnl_dollar_net_o)[ok].abs()
    g_same = (now.pnl_dollar_gross - pre.pnl_dollar_gross)[ok].abs().max()
    d_cost = (pre.pnl_dollar_cost - now.pnl_dollar_cost)[ok]
    print(f"{arm}: old {len(old)} new {len(new)} matched {len(m)} (both finite {int(ok.sum())}); "
          f"sum delta net file {d_file.sum():,.2f}; sum commission cut (recomputed) {d_cost.sum():,.2f}; "
          f"max|recompute-new file| {r_new.max():.3e}; max|pre-fix recompute-old file| {r_old.max():.3e}; "
          f"trades off >$0.01: new {int((r_new > 0.01).sum())}, old {int((r_old > 0.01).sum())}; gross max diff {g_same:.1e}",
          flush=True)
    if (r_old > 0.01).any():
        bad = m[ok][(r_old > 0.01).to_numpy()].head(5)
        print("  first old mismatches:\n", bad[KEY + ["pnl_dollar_net_o"]].to_string(), flush=True)
