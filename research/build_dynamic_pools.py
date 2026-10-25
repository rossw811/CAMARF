"""
research/build_dynamic_pools.py -- Amendment 6 pools (Ross 2026-10-25): the Amendment 5 clean pools with each pair's
active month-ends attached (purity_pit_eligibility.pit_active_months: >= k rejected windows under the as-of BH family
at that month-end, windows before the seal of their timeframe). backtest.py lets a pair enter only in the month after
an active month-end. Pairs, cleaning and spreads are Amendment 5's.
Output: output/research/purity_pairs_pit_k{1,2}_clean_dyn.parquet + a printed summary (active share per year).
Usage: python research/build_dynamic_pools.py        Check: debug/_verify_dynamic_pool_amendment6.py
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

from config import Config  # noqa: E402
import purity_pit_eligibility as ppe  # noqa: E402


def main():
    windows = {tf: ppe._seal_windows(pd.read_parquet(p, columns=["symbol_a", "symbol_b", "window_end_date", "pvalue"]), tf)
               for tf, p in ppe._TIER3.items() if os.path.exists(p)}
    for k in (1, 2):
        src = Config.DATA.PIT_POOL_PATHS[f"k{k}"]
        P = pd.read_parquet(src)
        a, b = P["symbol_a"].astype(str), P["symbol_b"].astype(str)
        P["key_a"], P["key_b"] = a.where(a <= b, b), b.where(a <= b, a)
        parts = []
        for tf, g in P.groupby("tf_label"):
            keys = set(zip(g["key_a"], g["key_b"]))
            A = ppe.pit_active_months(windows[tf], k, keys=keys)
            parts.append(g.merge(A, on=["key_a", "key_b"], how="left"))
        D = pd.concat(parts, ignore_index=True)
        D["active_month_ends"] = [list(x) if isinstance(x, (list, tuple)) or hasattr(x, "__len__") else [] for x in
                                  D["active_month_ends"]]
        D = D.drop(columns=["key_a", "key_b"])
        out = src.replace("_clean.parquet", "_clean_dyn.parquet")
        D.to_parquet(out, index=False)
        n_act = D["active_month_ends"].map(len)
        ever = int((n_act > 0).sum())
        last = pd.Series([max(x) if len(x) else pd.NaT for x in D["active_month_ends"]])
        print(f"k{k}: {len(D)} pairs, {ever} ever active, median active months {int(n_act.median())}; active at "
              f"2025-12-31: {int((last >= pd.Timestamp('2025-12-31')).sum())} -> {out}")


if __name__ == "__main__":
    main()
