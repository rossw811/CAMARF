"""
PIT-pool default (Ross 2026-10-16: "k=2 default, --pool k1, full-sample only via --full-sample-descriptive; also fixes
the whole-history fallbacks from docs/drafts/pit_audit_draft.csv"). Point-in-time rule (CLAUDE.md, 2026-10-15): a
metric that selects, sizes, filters or predicts uses only data available at its decision date.
Before: backtest.py read output/results/{tf}/pairs.parquet (pairs selected on their whole history), gated every pair
on its whole-history hedge ratio, and replaced missing per-bar values (hedge ratio in warm-up, hedge drift, coint
fraction, half-life slope, mean-reversion speed, Hurst) with whole-history scalars.
Checks:
  1. pair source: default = PIT k2 pool, --pool k1, --full-sample-descriptive = pairs.parquet labelled descriptive,
     --pairs-override wins, descriptive + --pool is refused;
  2. strict engine: a pair is not gated on its whole-history hedge ratio (only per-bar values decide);
  3. strict engine: no per-bar hedge series -> pair skipped (no whole-history fallback); descriptive keeps old path;
  4. strict engine: per-bar hedge NaN in warm-up -> no entry on those bars;
  5. strict engine: a missing per-bar feature reaches the ML gate as NaN, not the whole-history scalar.
Run: python debug/_verify_backtest_pit_pool_default.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest as bt
bt.apply_pnl_basis = lambda trades, legacy=False, cfg=None: (trades, {})   # synthetic symbols carry no prices

import numpy as np
import pandas as pd

from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def triangle(n, period=40, amp=3.5):
    t = np.arange(n) % period
    h = period / 2.0
    return np.where(t < h, -1 + 2 * t / h, 3 - 2 * t / h) * amp


def spread_df(n=600, hedge=True, warmup=0):
    ts = pd.bdate_range("2015-01-01", periods=n)
    z = triangle(n)
    d = {"spread": z * 0.5, "z_rolling": z, "z_expanding": z, "half_life_rolling": np.full(n, 20.0),
         "gap_flag_a": np.zeros(n, "int8"), "gap_flag_b": np.zeros(n, "int8")}
    if hedge:
        h = np.ones(n)
        h[:warmup] = np.nan
        d["hedge_ratio_ols_t"], d["hedge_ratio_kalman_t"] = h, h.copy()
    return pd.DataFrame(d, index=ts)


def pair(hedge_scalar=1.0):
    return pd.Series({"symbol_a": "SYNA", "symbol_b": "SYNB", "tf_label": "1D", "hedge_ratio_ols": hedge_scalar,
                      "hedge_ratio_kalman_mean": hedge_scalar, "hurst_rs": 0.4, "coint_fraction_rolling": 0.5,
                      "half_life_trend_slope": 0.0, "mean_reversion_speed": 0.1})


class _SpyML:
    enabled = True

    def __init__(self):
        self.calls = []

    def predict_prob(self, f):
        self.calls.append(dict(f))
        return 1.0


def engine(strict, ml=None):
    kw = dict(cfg=Config.BACKTEST, regime_cond=bt.RegimeConditioner(enabled=False),
              ml_cond=ml or bt.MLConditioner(enabled=False), layer2_enabled=ml is not None, storm_flags={},
              mm_hedge_map={})
    return bt.BacktestEngine(**kw, pit_strict=strict)


def main():
    print("1. pair source")
    try:
        r = bt.resolve_pair_source
        p, sfx = r(pool="k2", full_sample_descriptive=False, pairs_override=None)
        check("default_k2_pool", p == Config.DATA.PIT_POOL_PATHS["k2"] and sfx == "", f"{p} {sfx!r}")
        p, sfx = r(pool="k1", full_sample_descriptive=False, pairs_override=None)
        check("k1_pool_labelled", p == Config.DATA.PIT_POOL_PATHS["k1"] and sfx == "_pitk1", f"{p} {sfx!r}")
        p, sfx = r(pool="k2", full_sample_descriptive=True, pairs_override=None)
        check("descriptive_full_sample", p is None and sfx == "_fullsample_descriptive", f"{p} {sfx!r}")
        p, sfx = r(pool="k2", full_sample_descriptive=False, pairs_override="x.parquet")
        check("override_wins", p == "x.parquet" and sfx == "", f"{p} {sfx!r}")
        try:
            r(pool="k1", full_sample_descriptive=True, pairs_override=None)
            check("descriptive_plus_pool_refused", False)
        except ValueError:
            check("descriptive_plus_pool_refused", True)
    except AttributeError as e:
        check("resolve_pair_source_exists", False, str(e))

    print("2-5. strict engine")
    try:
        t_strict = engine(True).run(pair(hedge_scalar=-1.0), spread_df(), hedge_method="ols")
        t_desc = engine(False).run(pair(hedge_scalar=-1.0), spread_df(), hedge_method="ols")
        check("strict_not_gated_on_whole_history_hedge", len(t_strict) > 0 and len(t_desc) == 0,
              f"strict {len(t_strict)}, descriptive {len(t_desc)}")
        t_strict = engine(True).run(pair(), spread_df(hedge=False), hedge_method="ols")
        t_desc = engine(False).run(pair(), spread_df(hedge=False), hedge_method="ols")
        check("strict_skips_pair_without_pit_hedge", len(t_strict) == 0 and len(t_desc) > 0,
              f"strict {len(t_strict)}, descriptive {len(t_desc)}")
        t_strict = engine(True).run(pair(), spread_df(warmup=200), hedge_method="ols")
        first = min(pd.Timestamp(t.entry_time) for t in t_strict) if len(t_strict) else None
        cut = spread_df().index[200]
        check("strict_no_entry_during_hedge_warmup", first is not None and first >= cut, f"first {first}, cut {cut}")
        spy = _SpyML()
        engine(True, ml=spy).run(pair(), spread_df(), hedge_method="ols")
        h = [c.get("hurst_exponent") for c in spy.calls]
        check("strict_missing_feature_is_nan_not_scalar", len(h) > 0 and all(np.isnan(v) for v in h),
              f"{len(h)} calls, first {h[:1]}")
        spy2 = _SpyML()
        engine(False, ml=spy2).run(pair(), spread_df(), hedge_method="ols")
        check("descriptive_keeps_scalar_fallback", len(spy2.calls) > 0
              and all(c.get("hurst_exponent") == 0.4 for c in spy2.calls))
    except TypeError as e:
        check("engine_accepts_pit_strict", False, str(e))

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
