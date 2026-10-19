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
    print("1. pair source (one shared resolver, config.resolve_pit_pair_source -- code review of 99bf428f)")
    try:
        from config import resolve_pit_pair_source as r
        s = r()
        check("default_k2_pool_labelled", s["path"] == Config.DATA.PIT_POOL_PATHS["k2"] and s["label"] == "_pitk2"
              and s["strict"] and s["canonical_model"], f"{s}")
        s = r(pool="k1")
        check("k1_pool_labelled", s["path"] == Config.DATA.PIT_POOL_PATHS["k1"] and s["label"] == "_pitk1", f"{s}")
        s = r(full_sample_descriptive=True)
        check("descriptive_full_sample", s["path"] is None and s["label"] == "_fullsample_descriptive"
              and not s["strict"] and not s["canonical_model"], f"{s}")
        s = r(pairs_override="x.parquet")
        check("override_wins_strict", s["path"] == "x.parquet" and s["strict"], f"{s}")
        for kw, name in ((dict(pool="k1", full_sample_descriptive=True), "descriptive_plus_pool_refused"),
                         (dict(pairs_override="x.parquet", full_sample_descriptive=True), "descriptive_plus_override_refused"),
                         (dict(pit_safe=True, pool="k1"), "pit_safe_plus_pool_refused")):
            try:
                r(**kw)
                check(name, False)
            except ValueError:
                check(name, True)
        check("backtest_uses_shared_resolver", bt.resolve_pair_source is r or getattr(bt, "resolve_pit_pair_source", None) is r)
    except (ImportError, AttributeError, KeyError) as e:
        check("shared_resolver_exists", False, f"{type(e).__name__}: {e}")

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

        # code review of 99bf428f: the strict skip checked the UNSLICED frame; per-bar hedge finite only in bars the
        # dropna removes -> the sliced frame has none and the old code traded on a NaN hedge
        sd = spread_df()
        sd.iloc[:100, sd.columns.get_loc("z_rolling")] = np.nan
        h = np.full(len(sd), np.nan)
        h[:100] = 1.0
        sd["hedge_ratio_ols_t"], sd["hedge_ratio_kalman_t"] = h, h.copy()
        t = engine(True).run(pair(), sd, hedge_method="ols")
        check("strict_skips_when_sliced_frame_has_no_pit_hedge", len(t) == 0, f"{len(t)} trades")
        # pit_wfa-style callers whose pair-row scalars are train-only (PIT-valid) keep the scalar path
        kw = dict(cfg=Config.BACKTEST, regime_cond=bt.RegimeConditioner(enabled=False),
                  ml_cond=bt.MLConditioner(enabled=False), storm_flags={}, mm_hedge_map={})
        e_valid = bt.BacktestEngine(**kw, scalars_pit_valid=True)
        check("scalars_pit_valid_keeps_scalar_path",
              len(e_valid.run(pair(hedge_scalar=-1.0), spread_df(), hedge_method="ols")) == 0
              and len(e_valid.run(pair(), spread_df(hedge=False), hedge_method="ols")) > 0)
        # serving features match training (ml.py): signed zscore; squeeze_min / rsi_diff_velocity from per-bar columns
        sdq = spread_df()
        sdq["squeeze_indicator_a_t"], sdq["squeeze_indicator_b_t"], sdq["rsi_diff_velocity_t"] = 0.3, 0.7, 0.25
        spy3 = _SpyML()
        engine(True, ml=spy3).run(pair(), sdq, hedge_method="ols")
        zs = [c["zscore"] for c in spy3.calls]
        check("serving_zscore_signed_like_training", any(v < 0 for v in zs) and any(v > 0 for v in zs),
              f"{len(zs)} calls, min {min(zs) if zs else None}")
        check("serving_passes_squeeze_and_rsi", all(c.get("squeeze_min") == 0.3 and c.get("rsi_diff_velocity") == 0.25
                                                    for c in spy3.calls) and len(spy3.calls) > 0)
        # a Layer-2 run must use a gate model trained on the same pair source (review of a51f926c)
        try:
            bt.check_gate_source("_pitk1", "_pitk2")
            check("gate_source_mismatch_refused", False)
        except ValueError:
            check("gate_source_mismatch_refused", True)
        check("gate_source_match_ok", bt.check_gate_source("_pitk2", "_pitk2") is None)
    except TypeError as e:
        check("engine_accepts_pit_strict", False, str(e))

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
