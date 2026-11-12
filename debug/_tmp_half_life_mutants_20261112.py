import sys, runpy, io, contextlib
import numpy as np, pandas as pd
sys.path.insert(0, r"C:\Users\RossW\Projects\CAMARF")
import analysis
from analysis import SpreadModel
orig = SpreadModel.rolling_half_life_hedged
def raw(log_a, log_b, hedge, window, step, bias_correct):
    n = log_a.size; hl = np.full(n, np.nan); refs = []
    if n < window: return hl, refs
    for t in range(window - 1, n, step):
        refs.append(t)
        if t - window < 0 or not np.isfinite(hedge[t - window]): continue
        a, b = log_a[t-window+1:t+1], log_b[t-window+1:t+1]
        hl[t] = SpreadModel.half_life_ar1(a - hedge[t-window]*b, bias_correct=bias_correct)
    return hl, refs
def hold(hl, refs, n):
    out = np.full(n, np.nan)
    for k, t in enumerate(refs):
        e = refs[k+1] if k+1 < len(refs) else n
        out[t:e] = hl[t]
    return out
def mk(kind):
    def f(log_a, log_b, hedge, window=252, step=21, bias_correct=False):
        n = log_a.size; hl, refs = raw(log_a, log_b, hedge, window, step, bias_correct)
        if not refs: return hl
        if kind == "old_ffill": return pd.Series(hl).ffill().values
        if kind == "ffill_one_refresh": return pd.Series(hl).ffill(limit=2*step-1).values
        if kind == "next_refresh":  # lookahead: each bar carries the NEXT refresh
            out = np.full(n, np.nan)
            for k, t in enumerate(refs):
                s = refs[k-1]+1 if k > 0 else t
                out[s:t+1] = hl[t]
            out[refs[-1]:] = hl[refs[-1]]
            return out
        if kind == "late_by_one": o = hold(hl, refs, n); return np.r_[np.nan, o[:-1]]
        if kind == "early_by_one": o = hold(hl, refs, n); return np.r_[o[1:], o[-1]]
        if kind == "bc_arm_old_ffill":
            return pd.Series(hl).ffill().values if bias_correct else hold(hl, refs, n)
    return f
for kind in ["old_ffill","ffill_one_refresh","next_refresh","late_by_one","early_by_one","bc_arm_old_ffill"]:
    SpreadModel.rolling_half_life_hedged = staticmethod(mk(kind))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try: runpy.run_path(r"C:\Users\RossW\Projects\CAMARF\debug\_verify_half_life_hedge_consistency.py", run_name="__main__")
        except SystemExit: pass
    lines = buf.getvalue().splitlines()
    print(kind, [l for l in lines if "checks passed" in l], [l[:60] for l in lines if l.startswith("[FAIL]")])
