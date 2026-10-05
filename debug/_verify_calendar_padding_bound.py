"""
Reproduction check for claims-registry C-002 (calendar-padding artifact in rolling z-scores; PAPER.md:803-812).
Claim: a z-score computed over a window whose other n-1 rows are identical (calendar padding: forward-filled
non-trading rows) equals (n-1)/sqrt(n) in magnitude -- 15.81 at n = 252 -- whatever the size of the real move, and no
window can exceed it. This is Samuelson's inequality (1968) for the SAMPLE standard deviation (ddof = 1, pandas'
rolling default): |x_i - mean| <= s * (n-1)/sqrt(n), with equality iff the other n-1 values are equal.
Checks:
  1. attained: n-1 equal values + one move of ANY size (1e-6 .. 1e6) -> |z| = (n-1)/sqrt(n) exactly (n = 5, 30, 252);
  2. bound holds: 200,000 random windows (normal, heavy-tailed, trending, mixed) never exceed it;
  3. pandas rolling z on a padded series reproduces the value at the first real bar after a long pad.
The EMPIRICAL part of C-002 ("4 of 32 intraday examples |z| > 10") is not covered here -- it needs re-derivation on
current intraday data.
Run: python debug/_verify_calendar_padding_bound.py
"""
import sys

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def z_last(w):
    w = np.asarray(w, float)
    return (w[-1] - w.mean()) / w.std(ddof=1)


def main():
    ok, worst = True, []
    for n in (5, 30, 252):
        bound = (n - 1) / np.sqrt(n)
        for d in (1e-6, 0.01, 1.0, 37.5, 1e6):
            z = z_last(np.r_[np.zeros(n - 1), d])
            ok &= np.isclose(abs(z), bound, rtol=1e-9)
            worst.append((n, d, round(z, 6), round(bound, 6)))
    check("1.bound_attained_by_padding", ok, f"n=252 -> {(251) / np.sqrt(252):.4f}; examples {worst[-2:]}")
    rng = np.random.default_rng(0)
    mx = 0.0
    for kind in ("normal", "t2", "trend", "mixed"):
        for _ in range(50_000):
            n = int(rng.integers(3, 300))
            if kind == "normal":
                w = rng.normal(size=n)
            elif kind == "t2":
                w = rng.standard_t(2, size=n)
            elif kind == "trend":
                w = np.cumsum(rng.normal(size=n))
            else:
                w = np.r_[np.full(int(rng.integers(1, n)), rng.normal()), rng.normal(size=n)][:n]
            if np.std(w, ddof=1) == 0:
                continue
            mx = max(mx, abs(z_last(w)) / ((n - 1) / np.sqrt(n)))
    check("2.bound_never_exceeded", mx <= 1 + 1e-9, f"max |z| / bound over 200,000 windows = {mx:.6f}")
    n = 252
    s = pd.Series(np.r_[np.full(400, 100.0), 103.0])        # long padded run, then the first real move
    z = ((s - s.rolling(n).mean()) / s.rolling(n).std()).iloc[-1]
    check("3.pandas_rolling_reproduces", np.isclose(z, (n - 1) / np.sqrt(n)), f"z = {z:.4f}")
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
