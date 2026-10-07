"""
Synthetic check for research/d18_arm_comparison.py (2026-10-07). NOTE: written after the module (a process slip,
recorded in the commit message); the expected values below are computed by hand from the construction, not read
back from the module.
Temp WRDS cache: legs X, Y, Z (CRSP: close, close_total_return, volume) and Q (quote-only file in _quote_only/).
X has close = NaN (a no-trade midpoint day) on 100 days inside the deciding window; every leg trades at $10 x 1000
shares. Window files for both arms are built so each one-arm pair lands in one known reason:
  (X,Y) include-only, same raw p in exclude (adjusted p above alpha)   -> multiplicity
  (X,Z) include-only, exclude raw p differs                           -> data_changed
  (Q,X) include-only, Q quote-only                                    -> quote_only_leg
  (Y,Z) exclude-only, pair not tested at all in include              -> pair_not_tested
  (V,X) include-only, exclude tested the pair on a SHIFTED window grid -> grid_shift (nearest window, its p, offset)
  (Y,Q) confirmed in both                                             -> not in the report
Other-arm rows in both regression directions: the smaller p is used.
Checks: the reasons; the shared pair excluded; window = last 2520 aligned bars; X's no-trade share = 100/2520;
median dollar volume = 10,000; Q's no-trade share = 1 (every price is a quote).
Run: python debug/_verify_d18_arm_comparison.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research.d18_arm_comparison as m

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    d = tempfile.mkdtemp(prefix="d18cmp_")
    try:
        os.makedirs(os.path.join(d, "_quote_only"))
        idx = pd.bdate_range("2000-01-03", periods=3000)
        end = idx[2799]
        base = pd.DataFrame({"close": 10.0, "close_total_return": 10.0, "volume": 1000.0}, index=idx)
        x = base.copy()
        x.iloc[300:400, x.columns.get_loc("close")] = np.nan          # 100 no-trade days, all inside [280, 2799]
        x.to_parquet(os.path.join(d, "X_1D.parquet"))
        base.to_parquet(os.path.join(d, "Y_1D.parquet"))
        base.to_parquet(os.path.join(d, "Z_1D.parquet"))
        base.to_parquet(os.path.join(d, "V_1D.parquet"))
        q = base.drop(columns=["close"]).assign(quote_only=True)
        q.to_parquet(os.path.join(d, "_quote_only", "Q_1D.parquet"))
        m._WRDS = d

        def w(a, b, p, ap, rej, e=end):
            return {"symbol_a": a, "symbol_b": b, "pvalue": p, "window_end_date": e, "fdr_rejected": rej,
                    "fdr_adjusted_pvalue": ap}
        inc = pd.DataFrame([w("X", "Y", 0.001, 0.01, True), w("X", "Z", 0.001, 0.01, True),
                            w("Q", "X", 0.001, 0.01, True), w("Y", "Q", 0.001, 0.01, True),
                            w("V", "X", 0.001, 0.01, True)])
        # V/X in exclude: windows 120 and 400 days away from the deciding end -> nearest is the 120-day one
        exc = pd.DataFrame([w("Y", "X", 0.5, 0.9, False), w("X", "Y", 0.001, 0.08, False),   # both directions
                            w("X", "Z", 0.2, 0.9, False), w("Y", "Z", 0.001, 0.01, True),
                            w("Y", "Q", 0.001, 0.01, True),
                            w("X", "V", 0.04, 0.95, False, end - pd.Timedelta(days=120)),
                            w("V", "X", 0.3, 0.99, False, end + pd.Timedelta(days=400))])
        conf = {"include": pd.DataFrame({"symbol_a": ["X", "X", "Q", "Y", "V"], "symbol_b": ["Y", "Z", "X", "Q", "X"]}),
                "exclude": pd.DataFrame({"symbol_a": ["Y", "Y"], "symbol_b": ["Z", "Q"]})}
        rep = m.compare_tier(3, {"exclude": exc, "include": inc}, conf)
        reason = {(r.symbol_a, r.symbol_b): r.reason for r in rep.itertuples()}
        check("multiplicity", reason.get(("X", "Y")) == "multiplicity", reason)
        check("data_changed", reason.get(("X", "Z")) == "data_changed")
        check("quote_only_leg", reason.get(("Q", "X")) == "quote_only_leg")
        check("pair_not_tested", reason.get(("Y", "Z")) == "pair_not_tested", reason.get(("Y", "Z")))
        check("shared_pair_excluded", ("Q", "Y") not in reason and len(rep) == 5, f"{len(rep)} rows")
        vx = rep[(rep.symbol_a == "V") & (rep.symbol_b == "X")].iloc[0]
        check("grid_shift", vx.reason == "grid_shift", vx.reason)
        check("grid_shift_nearest_window", vx.other_offset_days == -120 and np.isclose(vx.other_pvalue, 0.04)
              and np.isclose(vx.other_adj_pvalue, 0.95), f"{vx.other_offset_days} {vx.other_pvalue}")
        xy = rep[(rep.symbol_a == "X") & (rep.symbol_b == "Y")].iloc[0]
        check("other_arm_uses_smaller_p", np.isclose(xy.other_pvalue, 0.001), xy.other_pvalue)
        check("window_is_2520_aligned_bars", xy.window_start_date == idx[280] and xy.window_end_date == end,
              f"{xy.window_start_date} .. {xy.window_end_date}")
        check("no_trade_share_exact", np.isclose(xy.no_trade_frac_a, 100 / 2520), xy.no_trade_frac_a)
        check("traded_leg_zero_no_trade", xy.no_trade_frac_b == 0.0)
        check("median_dollar_volume", np.isclose(xy.median_dollar_vol_b, 10_000.0), xy.median_dollar_vol_b)
        qx = rep[(rep.symbol_a == "Q")].iloc[0]
        check("quote_only_all_quotes", qx.quote_only_a and np.isclose(qx.no_trade_frac_a, 1.0), qx.no_trade_frac_a)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
