"""
research/strategy_rule_invariants.py -- does every trading rule actually behave as specified?
(2026-09-27, Ross: "make sure all the rules are happening as they actually should"; prompted by
code-review finding B16, which a distribution fit surfaced: two-thirds of trades are immediate
stop-outs because entry has no upper |z| bound below the stop.)

Checks each rule of backtest.py's engine against every REAL trade in a trades file -- measured, not
inferred from reading the code:

  I1  entry |z| >= ENTRY_ZSCORE
  I2  entry |z| <  STOP_ZSCORE          (a position must not open already past its own stop; B16)
  I3  side = short iff entry_z > 0      (reversion direction)
  I4  every "stop" exit has |exit_z| >= STOP_ZSCORE
  I5  every "signal_exit" crossed EXIT_ZSCORE in the reversion direction
  I6  every "max_hold" exit has hold_bars >= int(MAX_HOLD_MULTIPLIER * half_life_at_entry)
  I8  no overlapping positions per (pair, tf, hedge_method)
  I9  gate conditions hold at the entry bar (squeeze: both legs' squeeze indicator < 1;
      momentum: RSI-divergence velocity sign agrees with reversion) -- read from spread files
  I10 half_life_at_entry >= MIN_HALF_LIFE_BARS
  Diagnostics (rule behaves as coded, but not as intended):
  S1  stop after a FAVORABLE move (|z| fell toward 0 but was still >= STOP): the stop is |z|-based,
      not direction-aware, so any entry at/over the stop is stopped regardless of direction
  S2  "stop" on an overshoot THROUGH zero (sign flipped): the stop is checked before the signal
      exit, so a one-bar reversion past -STOP is recorded as a stop
  S3  immediate re-entry churn: a new entry on the pair within 1 bar of a stop exit
  never_fired: exit reasons the engine can emit that never occur (dead rules, e.g. corr_exit, which
      needs |z| > 2|entry_z| >= 6 but is checked after the |z| >= 3.5 stop)

Verified against planted violations first: debug/_verify_strategy_rule_invariants.py.
Usage (project root; CachyOS has the current trades files):
    python research/strategy_rule_invariants.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ENGINE_EXIT_REASONS = ("stop", "signal_exit", "max_hold", "corr_exit", "real_corr_exit",
                        "decoupling_avoidance_exit", "data_gap", "eod")
_TF_DIR = {"1D": "1day", "1h": "1hr", "4h": "4hr"}


def check_trade_invariants(trades: pd.DataFrame, P: dict) -> dict:
    t = trades.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"])
    t["exit_time"] = pd.to_datetime(t["exit_time"])
    ez, xz = t["entry_z"].astype(float), t["exit_z"].astype(float)
    reason = t["exit_reason"].astype(str)
    stop = reason == "stop"
    same_sign = np.sign(ez) == np.sign(xz)
    limit = (P["MAX_HOLD_MULTIPLIER"] * t["half_life_at_entry"].astype(float)).astype(int)
    short = t["side"] == "short"
    flags = {
        "I1_entry_below_threshold": ez.abs() < P["ENTRY_ZSCORE"],
        "I2_entry_at_or_past_stop": ez.abs() >= P["STOP_ZSCORE"],
        "I3_side_sign_mismatch": short != (ez > 0),
        "I4_stop_without_stop_level": stop & (xz.abs() < P["STOP_ZSCORE"]),
        "I5_signal_exit_not_crossed": (reason == "signal_exit") & np.where(short, xz > P["EXIT_ZSCORE"], xz < -P["EXIT_ZSCORE"]),
        "I6_max_hold_before_limit": (reason == "max_hold") & (t["hold_bars"] < limit),
        "I10_half_life_below_floor": t["half_life_at_entry"].astype(float) < P["MIN_HALF_LIFE_BARS"],
        "S1_stop_after_favorable_move": stop & same_sign & (xz.abs() < ez.abs()) & (xz.abs() >= P["STOP_ZSCORE"]),
        "S2_stop_on_overshoot_through_zero": stop & ~same_sign,
    }
    keys = [c for c in ("symbol_a", "symbol_b", "tf", "hedge_method") if c in t.columns]
    t = t.sort_values(keys + ["entry_time"])
    prev_exit = t.groupby(keys)["exit_time"].shift(1)
    prev_reason = t.groupby(keys)["exit_reason"].shift(1)
    overlap = (t["entry_time"] < prev_exit).reindex(trades.index).fillna(False)
    gap_days = (t["entry_time"] - prev_exit).dt.days
    churn = ((prev_reason == "stop") & (gap_days <= 1)).reindex(trades.index).fillna(False)
    flags["I8_overlapping_positions"] = overlap
    flags["S3_reentry_within_1_bar_of_stop"] = churn
    counts = {k: int(np.asarray(v).sum()) for k, v in flags.items()}
    rc = reason.value_counts().to_dict()
    return {"counts": counts, "n": len(trades), "exit_reasons": rc,
            "never_fired": [r for r in _ENGINE_EXIT_REASONS if rc.get(r, 0) == 0],
            "flags": pd.DataFrame({k: np.asarray(v) for k, v in flags.items()}, index=trades.index)}


def check_gates_at_entry(trades: pd.DataFrame, gate: str, results_dir="output/results") -> dict:
    """I9: re-read the gate inputs at each entry bar from the pair's spread file."""
    bad = checked = missing = 0
    cache = {}
    for tr in trades.itertuples():
        tfd = _TF_DIR.get(str(tr.tf))
        if tfd is None:
            continue
        k = (tr.symbol_a, tr.symbol_b, tfd)
        if k not in cache:
            p = os.path.join(results_dir, tfd, f"spread_series_{tr.symbol_a}_{tr.symbol_b}.parquet")
            cache[k] = pd.read_parquet(p) if os.path.exists(p) else None
        d = cache[k]
        ts = pd.Timestamp(tr.entry_time)
        if d is None or ts not in d.index:
            missing += 1
            continue
        row = d.loc[ts]
        checked += 1
        ok = True
        if gate in ("squeeze", "combined"):
            a, b = row.get("squeeze_indicator_a_t", np.nan), row.get("squeeze_indicator_b_t", np.nan)
            ok &= bool(np.isfinite(a) and np.isfinite(b) and a < 1.0 and b < 1.0)
        if gate in ("momentum", "combined"):
            v = row.get("rsi_diff_velocity_t", np.nan)
            ok &= bool(np.isfinite(v) and ((tr.entry_z > 0 and v < 0) or (tr.entry_z < 0 and v > 0)))
        bad += (not ok)
    return {"I9_gate_violations": bad, "I9_checked": checked, "I9_unverifiable": missing}


def main():
    from config import Config
    B = Config.BACKTEST
    P = dict(ENTRY_ZSCORE=B.ENTRY_ZSCORE, STOP_ZSCORE=B.STOP_ZSCORE, EXIT_ZSCORE=B.EXIT_ZSCORE,
             MAX_HOLD_MULTIPLIER=B.MAX_HOLD_MULTIPLIER, MIN_HALF_LIFE_BARS=B.MIN_HALF_LIFE_BARS)
    print("Rule parameters (Config.BACKTEST):", P)
    rows = []
    for f in sorted(glob.glob("output/backtest/trades_layer1*storm_*gate_pairsoverride.parquet")):
        name = os.path.basename(f).replace("trades_layer1_", "").replace("_pairsoverride.parquet", "")
        gate = "combined" if "sqzmomgate" in name else "squeeze" if "sqzgate" in name else "momentum"
        T = pd.read_parquet(f)
        r = check_trade_invariants(T, P)
        g = check_gates_at_entry(T[T["hedge_method"] == "ols"], gate)
        row = {"file": name, "n": r["n"], **r["counts"], **g, "never_fired": ",".join(r["never_fired"])}
        rows.append(row)
        print(f"\n== {name} (n={r['n']}, gate={gate}) exit reasons {r['exit_reasons']}")
        for k, v in {**r["counts"], **g}.items():
            print(f"   {k:38s} {v:>8}  ({100 * v / max(r['n'], 1):5.1f}%)" if not k.endswith(("checked", "unverifiable")) else f"   {k:38s} {v:>8}")
        print(f"   never fired: {r['never_fired']}")
    out = pd.DataFrame(rows)
    os.makedirs("output/research", exist_ok=True)
    out.to_parquet("output/research/strategy_rule_invariants.parquet")
    print("\nSaved output/research/strategy_rule_invariants.parquet")


if __name__ == "__main__":
    main()
