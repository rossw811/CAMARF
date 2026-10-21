"""
Synthetic checks for research/strategy_search.py (Design 1 harness).
  1. grid = exactly the pre-registered 216 configurations, unique ids, every config's entry cap == its stop;
  2. split_trades: development excludes straddlers (exit after cutoff), holdout starts after the embargo;
  3. fold_trades: calendar folds, fold straddlers purged;
  4. cscv_pbo: pure-noise configurations -> PBO near 0.5; one configuration with a genuine persistent edge
     -> PBO near 0.
Run: python debug/_verify_strategy_search.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.strategy_search import build_grid, cscv_pbo, fold_edges, fold_trades, split_trades

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    g = build_grid()
    check("grid.216", len(g) == 216 and len({c["id"] for c in g}) == 216, f"{len(g)}")
    check("grid.entry_cap_equals_stop", all(c["ENTRY_ZSCORE_MAX"] == c["STOP_ZSCORE"] for c in g))

    t0, T = pd.Timestamp("2010-01-01"), pd.Timestamp("2020-01-01")
    tr = pd.DataFrame({"entry_time": pd.to_datetime(["2012-01-01", "2014-12-20", "2015-02-01", "2015-01-05"]),
                       "exit_time": pd.to_datetime(["2012-02-01", "2015-01-10", "2015-03-01", "2015-01-20"])})
    dev, hold, c = split_trades(tr, t0, T, 0.5)  # cutoff ~2015-01-01, embargo ~36.5 days -> holdout >= ~2015-02-06
    check("split.cutoff", abs((c - pd.Timestamp("2015-01-01")).days) <= 1, f"{c}")
    check("split.straddler_purged_from_dev", len(dev) == 1 and dev["entry_time"].iloc[0] == pd.Timestamp("2012-01-01"), f"{dev.entry_time.tolist()}")
    check("split.embargo_excludes_early_holdout", hold["entry_time"].tolist() == [], f"{hold.entry_time.tolist()}")
    dev2, hold2, _ = split_trades(tr, t0, T, 0.5, embargo_pct=0.0)
    check("split.holdout_without_embargo", sorted(hold2["entry_time"].tolist()) == sorted(pd.to_datetime(["2015-01-05", "2015-02-01"]).tolist()))

    # 5. sealed holdout (DECISIONS_2026-10-12 E13): no trade that touches data on/after SEALED_FROM enters the eval
    try:
        from config import Config
        from research.strategy_search import seal_trades
        sealed = pd.Timestamp(Config.DATA.SEALED_FROM)
        st = pd.DataFrame({"entry_time": pd.to_datetime(["2025-06-01", "2025-12-20", "2026-02-01"]),
                           "exit_time": pd.to_datetime(["2025-07-01", "2026-01-05", "2026-03-01"])})
        kept = seal_trades(st, sealed)
        check("sealed.from_is_2026", sealed == pd.Timestamp("2026-01-01"), f"{sealed}")
        check("sealed.drops_trades_exiting_on_or_after", kept["entry_time"].tolist() == [pd.Timestamp("2025-06-01")],
              f"{kept.entry_time.tolist()}")
        stz = st.assign(entry_time=st.entry_time.dt.tz_localize("America/New_York"),
                        exit_time=st.exit_time.dt.tz_localize("America/New_York"))
        check("sealed.tz_aware_times", len(seal_trades(stz, sealed)) == 1, f"{len(seal_trades(stz, sealed))}")
    except Exception as ex:  # noqa: BLE001
        check("sealed.helper_exists", False, f"{type(ex).__name__}: {ex}")

    # 6. Amendment 5: trades excluded from P&L are counted per status, over pre-seal exits only
    try:
        from research.strategy_search import status_counts
        sd = pd.DataFrame({"exit_time": pd.to_datetime(["2020-01-02", "2021-01-04", "2022-01-03", "2026-02-02"]),
                           "pnl_dollar_status": ["ok", "unrealizable_gap", "unrealizable_gap", "unrealizable_gap"]})
        got = {r["status"]: r["n"] for r in status_counts(sd, "pit_k1", "c1")}
        check("a5.status_counts_pre_seal", got == {"ok": 1, "unrealizable_gap": 2}, str(got))
    except Exception as ex:  # noqa: BLE001
        check("a5.status_counts_exists", False, f"{type(ex).__name__}: {ex}")

    e = fold_edges(pd.Timestamp("2010-01-01"), pd.Timestamp("2014-01-01"), 4)
    ft = pd.DataFrame({"entry_time": pd.to_datetime(["2010-06-01", "2010-12-30", "2011-03-01"]),
                       "exit_time": pd.to_datetime(["2010-07-01", "2011-01-15", "2011-04-01"])})
    f0 = fold_trades(ft, e, 0)
    check("fold.straddler_purged", f0["entry_time"].tolist() == [pd.Timestamp("2010-06-01")], f"{f0.entry_time.tolist()}")

    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (1600, 40))
    p_noise, _ = cscv_pbo(noise)
    check("pbo.noise_near_half", 0.3 < p_noise < 0.7, f"PBO={p_noise:.3f}")
    real = noise.copy()
    real[:, 7] += 0.25  # one configuration with a genuine, persistent edge
    p_real, _ = cscv_pbo(real)
    check("pbo.genuine_edge_near_zero", p_real < 0.05, f"PBO={p_real:.3f}")
    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
