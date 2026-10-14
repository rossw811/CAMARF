"""
research/inclusion_did.py -- endogeneity arm (c) (Ross 2026-10-13): does co-movement CAUSE / follow from common
ownership? Identification by an exogenous-ish shock: S&P 500 inclusion (Barberis, Shleifer & Wurgler 2005) raises
index-fund ownership without changing fundamentals. Difference-in-differences of a stock's co-movement with incumbent
members, added stock vs matched non-added controls, with a pre-trend test.

Pure core (tested on synthetic data):
  comovement(x, M)          mean Pearson correlation of series x with each row of M
  did_from_events(events)   per event: (treated post - pre) - mean over controls (post - pre); DiD = mean over events;
                            95% CI by bootstrapping events; pre-trend: the pre period split into PRETREND_BINS bins,
                            per-event slope of (treated - control) co-movement on bin index, one-sample t-test
Real-data driver (after WRDS job 29: CRSP SIC + size): events = S&P 500 additions 1990-2024 from the cached PIT
membership history; controls = non-members with the same 2-digit SIC, nearest size, nearest pre-period co-movement.
Disclosed caveat: additions are chosen by a committee on size/liquidity -- matching and the pre-trend test address
selection only partly. Test: debug/_verify_inclusion_did.py
"""
import numpy as np
from scipy import stats

PRETREND_BINS = 12       # one bin per calendar month of the 12-month pre-period (definition; registry)
N_BOOT = 2000            # bootstrap draws over events for the DiD CI (registry)


def comovement(x, M) -> float:
    x = np.asarray(x, float); M = np.atleast_2d(np.asarray(M, float))
    xc = (x - x.mean()) / x.std()
    Mc = (M - M.mean(axis=1, keepdims=True)) / M.std(axis=1, keepdims=True)
    return float(np.mean(Mc @ xc / len(x)))


def _event_delta(ev):
    t0, M = ev["t0"], ev["members"]
    pre, post = slice(0, t0), slice(t0, M.shape[1])
    dt = comovement(ev["treated"][post], M[:, post]) - comovement(ev["treated"][pre], M[:, pre])
    dc = np.mean([comovement(c[post], M[:, post]) - comovement(c[pre], M[:, pre]) for c in ev["controls"]])
    return dt - dc


def _event_pre_slope(ev, bins=PRETREND_BINS):
    t0, M = ev["t0"], ev["members"]
    edges = np.linspace(0, t0, bins + 1).astype(int)
    diffs = []
    for a, b in zip(edges[:-1], edges[1:]):
        s = slice(a, b)
        diffs.append(comovement(ev["treated"][s], M[:, s])
                     - np.mean([comovement(c[s], M[:, s]) for c in ev["controls"]]))
    return float(np.polyfit(np.arange(bins), diffs, 1)[0])


def did_from_events(events, n_boot: int = N_BOOT, rng=None) -> dict:
    rng = rng or np.random.default_rng(0)
    d = np.array([_event_delta(e) for e in events])
    boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n_boot)]
    slopes = np.array([_event_pre_slope(e) for e in events])
    return {"did": float(d.mean()), "ci_low": float(np.quantile(boot, 0.025)), "ci_high": float(np.quantile(boot, 0.975)),
            "n_events": len(d), "pretrend_slope": float(slopes.mean()),
            "pretrend_p": signflip_p(slopes, rng)}


SIGNFLIP_DRAWS = 5000    # sign-flip randomization draws (registry)


def signflip_p(x, rng=None, draws: int = SIGNFLIP_DRAWS) -> float:
    """Two-sided sign-flip randomization p-value for mean(x) = 0 (exact under symmetry; 2026-10-13: the one-sample
    t-test on per-event slopes was oversized, 7.7% +- 1.5% at a nominal 5% over 300 synthetic seeds)."""
    rng = rng or np.random.default_rng(0)
    x = np.asarray(x, float)
    obs = abs(x.mean())
    flips = rng.choice([-1.0, 1.0], size=(draws, len(x)))
    return float((1 + np.sum(np.abs((flips * x).mean(axis=1)) >= obs)) / (draws + 1))
