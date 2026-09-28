"""
Regression test for code-review finding D12 (2026-09-26): DataStore._reconcile_split_adjustment measured the
adjustment-basis change as new_df.close[0] / existing.close[-1] -- two DIFFERENT dates. An incremental refresh
(period="1mo") overlaps the cache, so that "ratio" mixed ~a month of real returns with any basis change; and
yfinance auto_adjust shifts the whole price basis at every ex-dividend (~0.5-2%, under the gap tolerance), so
every refresh after a dividend left a seam that was never reconciled.
Fix: when existing and new_df share timestamps, the basis ratio is measured on those SAME timestamps (median of
new/old); a ratio that is constant across the overlap is an adjustment change by construction (a real market move
cannot re-price an already-closed bar), so it is applied to existing's prices (and a consistent volume ratio to
volume). The recorded-split check remains only for the no-overlap case.
Checks (cache in a temp dir, DataStore.append end to end, no network):
  1. overlap + dividend basis change (x0.99): combined prices equal the current-basis series everywhere;
  2. overlap + 2:1 split (prices /2, volume x2): combined prices and volume equal the current basis;
  3. overlap, no basis change, 30% real move within the overlap month: nothing rescaled;
  4. overlap rows that disagree inconsistently (revised last bar only): nothing rescaled.
Run: python debug/_verify_append_basis_reconcile.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from data import DataStore

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _frame(idx, close, vol):
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": vol},
                        index=idx)


def main():
    tmp = tempfile.mkdtemp(prefix="verify_d12_")
    orig = Config.DATA.CACHE_DIR
    Config.DATA.CACHE_DIR = tmp
    try:
        idx = pd.bdate_range("2026-01-02", periods=180)
        true = 50 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.01, len(idx))))
        vol = np.full(len(idx), 1e6)
        cut, start_new = 170, 150           # cache ends at bar 169; the refresh re-fetches bars 150..179

        for name, px_mult, vol_mult in (("dividend", 1 / 0.99, 1.0), ("split", 2.0, 0.5)):
            sym = f"T_{name}"
            DataStore.save(sym, "1D", _frame(idx[:cut], true[:cut] * px_mult, vol[:cut] * vol_mult))
            out = DataStore.append(sym, "1D", _frame(idx[start_new:], true[start_new:], vol[start_new:]))
            check(f"{name}:prices_on_current_basis", np.allclose(out["close"].to_numpy(), true, rtol=1e-10),
                  f"max rel err={np.max(np.abs(out['close'].to_numpy() / true - 1)):.2e}")
            check(f"{name}:volume_on_current_basis", np.allclose(out["volume"].to_numpy(), vol, rtol=1e-10))

        moved = true.copy()
        moved[160:] *= 1.30                 # a genuine +30% move inside the overlap window
        DataStore.save("T_move", "1D", _frame(idx[:cut], moved[:cut], vol[:cut]))
        out = DataStore.append("T_move", "1D", _frame(idx[start_new:], moved[start_new:], vol[start_new:]))
        check("real_move:not_rescaled", np.allclose(out["close"].to_numpy(), moved, rtol=1e-12))

        rev = true.copy()
        DataStore.save("T_rev", "1D", _frame(idx[:cut], rev[:cut], vol[:cut]))
        new = _frame(idx[start_new:], rev[start_new:], vol[start_new:])
        new.iloc[cut - 1 - start_new, new.columns.get_loc("close")] *= 1.05   # only the last cached bar revised
        out = DataStore.append("T_rev", "1D", new)
        check("inconsistent_overlap:not_rescaled", np.allclose(out["close"].to_numpy()[: cut - 1], rev[: cut - 1], rtol=1e-12))
    finally:
        Config.DATA.CACHE_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
