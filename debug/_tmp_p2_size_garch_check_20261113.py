# Reviewer claim check (2026-11-13): is the AIC fixed_adf oversize driven by volatility clustering + fat tails rather than
# the negative MA, and is Schwert's lag NOT robust to it? Unit-root spreads, 252 bars, 1,500 paired draws per null.
import sys, os, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research.yearly_family_test import _pvalue
rng = np.random.default_rng(int(sys.argv[1]) if len(sys.argv) > 1 else 1113)
T, R = 252, 1500
d = pd.bdate_range("2015-01-01", periods=T); z = pd.Series(np.zeros(T), d)
def garch(n, a=0.10, b=0.85, df=4):
    e = rng.standard_t(df, n + 200) / np.sqrt(df / (df - 2)); h = np.ones(n + 200); x = np.zeros(n + 200)
    for t in range(1, n + 200):
        h[t] = (1 - a - b) + a * x[t - 1] ** 2 + b * h[t - 1]; x[t] = np.sqrt(h[t]) * e[t]
    return x[200:]
NULLS = {"iid": lambda: rng.normal(size=T + 1),
         "MA -0.13": lambda: rng.normal(size=T + 1),
         "GARCH t4": lambda: garch(T + 1),
         "GARCH t4 + MA -0.13": lambda: garch(T + 1)}
for name, gen in NULLS.items():
    rej = np.zeros((R, 3), bool)
    for i in range(R):
        e = gen(); th = -0.13 if "MA" in name else 0.0
        s = pd.Series(np.cumsum(e[1:] + th * e[:-1]), d)
        for k, t in enumerate(("fixed_adf", "fixed_adf_schwert", "fixed_adf_tstat")):
            rej[i, k] = _pvalue(s, z, t) <= 0.05
    m = rej.mean(0)
    print(f"{name:22s} AIC {m[0]:.3f}  Schwert {m[1]:.3f}  t-stat {m[2]:.3f}  (SE {np.sqrt(.05*.95/R):.3f})", flush=True)
