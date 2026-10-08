"""
Regression test for code review S5 (verified 2026-10-07, fixed the same day): stats.run_permutation_test (the
"White Reality Check", PAPER.md line ~458: "IS p=0.559; OOS p=0.546") block-bootstrapped the RAW daily P&L and
counted bootstrap Sharpes >= the realized Sharpe. Without demeaning, the bootstrap distribution is centred on the
realized Sharpe itself, so p ~ 0.5 whatever the skill. Fix: resample the DEMEANED series (the zero-mean null of
White 2000 / Politis-Romano), keeping the block structure.
Checks (synthetic trades, one exit per business day, fixed seeds): strong skill (daily mean 0.25 sd 1, annualized
Sharpe ~4) -> p < 0.05; no skill (mean 0) -> p > 0.05 in most of 10 seeds; the old behaviour (p ~ 0.5 for strong
skill) is gone.
Run: python debug/_verify_reality_check_null.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stats

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def trades(mu, seed, n=500):
    rng = np.random.default_rng(seed)
    t = pd.bdate_range("2020-01-02", periods=n)
    return pd.DataFrame({"exit_time": t, "entry_time": t - pd.Timedelta(days=3), "pnl_net": rng.normal(mu, 1.0, n)})


def p_of(tr):
    r = stats.run_permutation_test(tr, portfolio_parquet_suffix="__none__")
    for k in ("p_value", "pvalue"):
        if isinstance(r, dict) and k in r:
            return float(r[k])
    df = next((v for v in (r or {}).values() if isinstance(v, pd.DataFrame)), None)
    for k in ("p_value", "pvalue"):
        if df is not None and k in df.columns:
            return float(df[k].iloc[0])
    raise RuntimeError(f"no p-value in result: {r}")


def main():
    p_skill = p_of(trades(0.25, 1))
    p_null = [p_of(trades(0.0, s)) for s in range(10, 20)]
    check("strong_skill_rejects", p_skill < 0.05, f"p={p_skill:.3f}")
    check("no_skill_mostly_not_rejected", sum(p > 0.05 for p in p_null) >= 8, f"{[round(p, 2) for p in p_null]}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
