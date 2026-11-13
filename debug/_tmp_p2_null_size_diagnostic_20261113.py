# Why does fixed_adf over-reject on the P2 placebo null? Seed 20261024: per null pair-year, lag-1..5 autocorrelation of the
# placebo spread returns, the AIC lag chosen, share of zero spread returns; size by lag-1 autocorrelation bin; and the same
# tests with fixed lag orders (0, Schwert 12*(T/100)^0.25) for comparison. Placebo data only. Run on CachyOS from the repo.
import sys, numpy as np, pandas as pd, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, "."); sys.path.insert(0, "research")
from statsmodels.tsa.stattools import adfuller
from p2_placebo_power import families, rebuild_legs
SEED = 20261024
N = pd.read_parquet("output/research/p2_placebo_power_null.parquet")
N = N[(N.seed == SEED) & (N.family == "ungated") & np.isfinite(N.pvalue)]
fams, labels = families("output/cache/wrds")
LP = rebuild_legs("output/cache/wrds", labels, SEED)
rows = []
for r in N.itertuples():
    a, b = LP[r.symbol_a], LP[r.symbol_b]
    j = pd.concat([a[a.index.year == r.year], b[b.index.year == r.year]], axis=1, join="inner").dropna()
    s = (j.iloc[:, 0] - j.iloc[:, 1]).to_numpy(); d = np.diff(s)
    ac = [float(pd.Series(d).autocorr(k)) for k in range(1, 6)]
    res = adfuller(s, regression="c", autolag="AIC")
    sch = int(12 * (len(s) / 100) ** 0.25)
    rows.append({"pvalue": r.pvalue, "ac1": ac[0], "ac_sum5": sum(ac), "aic_lag": res[2], "zero_share": float(np.mean(np.abs(d) < 1e-12)),
                 "p_lag0": adfuller(s, regression="c", maxlag=0, autolag=None)[1],
                 "p_schwert": adfuller(s, regression="c", maxlag=sch, autolag=None)[1],
                 "p_bic": adfuller(s, regression="c", autolag="BIC")[1]})
D = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(len(D), "null pair-years, seed", SEED)
print(D[["ac1", "ac_sum5", "aic_lag", "zero_share"]].describe().round(3).to_string())
D["ac1_bin"] = pd.cut(D.ac1, [-1, -0.4, -0.3, -0.2, -0.1, 0, 1])
print(D.groupby("ac1_bin").agg(n=("pvalue", "size"), aic=("pvalue", lambda x: (x < .05).mean()),
      lag0=("p_lag0", lambda x: (x < .05).mean()), schwert=("p_schwert", lambda x: (x < .05).mean()),
      bic=("p_bic", lambda x: (x < .05).mean()), med_aic_lag=("aic_lag", "median")).round(3).to_string())
for c in ("pvalue", "p_lag0", "p_schwert", "p_bic"):
    print(c, {t: round(float((D[c] < t).mean()), 4) for t in (0.05, 0.01, 0.001)})
