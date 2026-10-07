"""
research/d18_arm_comparison.py -- the D18 comparison report (Ross 2026-10-02: run discovery under both arms, then he
decides). Arm "exclude" (primary) masks CRSP no-trade days (bid/ask-midpoint returns) and drops quote-only files;
arm "include" keeps both. Both arms' episodic scans are finished (Tier 2: 278 vs 285, 272 shared; Tier 3: 703 vs
706, 684 shared). This report explains every pair confirmed by only ONE arm.

For each one-arm pair: the confirming arm's deciding window (its FDR-rejected window with the smallest adjusted p),
the SAME window in the other arm (matched on pair + window_end_date -- window_start offsets differ between arms
because masked days shorten the aligned series), each leg's quote-only flag, share of no-trade (midpoint) days and
median dollar volume over that window (close x restated volume; window = the 2520 aligned bars ending at
window_end_date under the include arm's alignment), and a reason (classify()):
  quote_only_leg  a leg is a quote-only series -- only the include arm admits it
  pair_not_tested the other arm never tested the pair at all
  grid_shift      the other arm tested the pair, but on a shifted window grid (no window with the same end date):
                  windows are counted in BARS from the pair's first common date, so masked/extra days move every
                  window's position. Reported: the other arm's NEAREST window, its p / adjusted p, offset in days.
  multiplicity    raw p identical in both arms; only the BH-adjusted p crossed alpha (the arms differ in test count)
  data_changed    raw p differs -- the midpoint days changed the test statistic itself
Usage:  python research/d18_arm_comparison.py          (CachyOS: reads both arms' window files, ~6.9M rows each)
Output: output/research/d18_arm_comparison.parquet, printed summary
Synthetic check: debug/_verify_d18_arm_comparison.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RES = os.path.join("output", "research")
_WRDS = os.path.join("output", "cache", "wrds")
OUT = os.path.join(_RES, "d18_arm_comparison.parquet")
WINDOW_BARS = 2520                                   # = wrds_deep_history_episodic_scan.EPISODIC_WINDOW_BARS
ARMS = {"exclude": "", "include": "_d18incl"}


def classify(quote_only_leg: bool, other_p, conf_p, tested: bool = True, same_window: bool = True,
             rtol: float = 1e-6) -> str:
    if quote_only_leg:
        return "quote_only_leg"
    if not tested:
        return "pair_not_tested"
    if not same_window:
        return "grid_shift"
    if np.isclose(other_p, conf_p, rtol=rtol, atol=0.0):
        return "multiplicity"
    return "data_changed"


def _key(a, b):
    return tuple(sorted((a, b)))


def load_leg(label: str):
    for p in (os.path.join(_WRDS, f"{label}_1D.parquet"), os.path.join(_WRDS, "_quote_only", f"{label}_1D.parquet")):
        if os.path.exists(p):
            return pd.read_parquet(p)
    return None


def _price(df):
    for c in ("close_total_return", "close_usd", "close"):
        if c in df.columns:
            return pd.to_numeric(df[c], errors="coerce")
    return None


def leg_window_stats(df: pd.DataFrame, start, end) -> dict:
    """No-trade share and median dollar volume of one leg over [start, end]."""
    w = df.loc[start:end]
    px = _price(w)
    quote_only = "quote_only" in w.columns and bool(w["quote_only"].fillna(False).any())
    valid = px.notna()
    if quote_only or "close" not in w.columns:
        no_trade = valid                                   # every price is a quote
        trade_px = px.abs()
    else:
        no_trade = w["close"].isna() & valid
        trade_px = pd.to_numeric(w["close"], errors="coerce").abs()
    dv = trade_px * pd.to_numeric(w["volume"], errors="coerce") if "volume" in w.columns else pd.Series(dtype=float)
    return {"quote_only": quote_only, "no_trade_frac": float(no_trade.sum() / max(valid.sum(), 1)),
            "median_dollar_vol": float(dv.median()) if len(dv.dropna()) else np.nan, "n_days": int(valid.sum())}


def window_bounds(da: pd.DataFrame, db: pd.DataFrame, end) -> tuple:
    """Start/end of the WINDOW_BARS aligned (both legs priced) bars ending at `end` (include-arm alignment)."""
    pa, pb = _price(da), _price(db)
    idx = pa.dropna().index.intersection(pb.dropna().index)
    idx = idx[idx <= pd.Timestamp(end)]
    if len(idx) == 0:
        return None, None
    return idx[max(0, len(idx) - WINDOW_BARS)], idx[-1]


def deciding_windows(win: pd.DataFrame, pairs: set) -> pd.DataFrame:
    """Per pair in `pairs`: its FDR-rejected window with the smallest adjusted p."""
    w = win[win["fdr_rejected"].astype(bool)].copy()
    w["key"] = [_key(a, b) for a, b in zip(w["symbol_a"], w["symbol_b"])]
    w = w[w["key"].isin(pairs)]
    return w.sort_values("fdr_adjusted_pvalue").drop_duplicates("key")


def compare_tier(tier: int, windows: dict, confirmed: dict) -> pd.DataFrame:
    keys = {arm: {_key(a, b) for a, b in zip(c["symbol_a"], c["symbol_b"])} for arm, c in confirmed.items()}
    rows = []
    for arm, other in (("exclude", "include"), ("include", "exclude")):
        only = keys[arm] - keys[other]
        dec = deciding_windows(windows[arm], only)
        ow = windows[other]
        ow = ow.assign(key=[_key(a, b) for a, b in zip(ow["symbol_a"], ow["symbol_b"])])
        ow = ow[ow["key"].isin(only)]
        # a pair can have several rows per window (both regression directions): keep the smallest p
        ow = ow.sort_values("pvalue").drop_duplicates(["key", "window_end_date"])
        by_key = {k: g for k, g in ow.groupby("key")}
        for _, r in dec.iterrows():
            a, b = r["key"]
            end = pd.Timestamp(r["window_end_date"])
            g = by_key.get(r["key"])
            rec = {"tier": tier, "confirmed_by": arm, "symbol_a": a, "symbol_b": b, "window_end_date": end,
                   "conf_pvalue": float(r["pvalue"]), "conf_adj_pvalue": float(r["fdr_adjusted_pvalue"]),
                   "other_pvalue": np.nan, "other_adj_pvalue": np.nan, "other_offset_days": np.nan,
                   "other_any_rejected": False}
            if g is not None:
                off = (pd.DatetimeIndex(g["window_end_date"]) - end).days
                n = int(np.argmin(np.abs(off)))
                rec.update(other_pvalue=float(g["pvalue"].iloc[n]), other_adj_pvalue=float(g["fdr_adjusted_pvalue"].iloc[n]),
                           other_offset_days=int(off[n]), other_any_rejected=bool(g["fdr_rejected"].any()))
            da, db = load_leg(a), load_leg(b)
            if da is not None and db is not None:
                s, e = window_bounds(da, db, end)
                rec["window_start_date"] = s
                if s is not None:
                    for leg, d in (("a", da), ("b", db)):
                        for kk, vv in leg_window_stats(d, s, e).items():
                            rec[f"{kk}_{leg}"] = vv
            qo = bool(rec.get("quote_only_a", False)) or bool(rec.get("quote_only_b", False))
            rec["reason"] = classify(qo, rec["other_pvalue"], rec["conf_pvalue"], tested=g is not None,
                                     same_window=rec["other_offset_days"] == 0)
            rows.append(rec)
    return pd.DataFrame(rows)


def _read(tier, arm, part, cols=None):
    return pd.read_parquet(os.path.join(_RES, f"wrds_deep_history_episodic_scan_tier{tier}_{part}{ARMS[arm]}.parquet"),
                           columns=cols)


def with_fdr(win: pd.DataFrame, confirmed: pd.DataFrame) -> pd.DataFrame:
    """Tier 2's window file is written BEFORE the scan's BH step, so it has no fdr columns: apply the scan's own
    _benjamini_hochberg (same family = all rows, same alpha) and require the result to reproduce the saved
    confirmed set exactly."""
    if "fdr_rejected" in win.columns:
        return win
    from config import Config
    from research.wrds_deep_history_episodic_scan import _benjamini_hochberg
    rej, adj = _benjamini_hochberg(win["pvalue"].to_numpy(), Config.STATS.FDR_ALPHA)
    win = win.assign(fdr_rejected=np.asarray(rej, bool), fdr_adjusted_pvalue=np.asarray(adj, float))
    got = {_key(a, b) for a, b in zip(win.loc[win.fdr_rejected, "symbol_a"], win.loc[win.fdr_rejected, "symbol_b"])}
    saved = {_key(a, b) for a, b in zip(confirmed["symbol_a"], confirmed["symbol_b"])}
    if got != saved:
        raise SystemExit(f"recomputed BH does not reproduce the saved confirmed set: {len(got ^ saved)} pairs differ")
    return win


def main():
    base = ["symbol_a", "symbol_b", "pvalue", "window_end_date"]
    out = []
    for tier in (2, 3):
        confirmed = {arm: _read(tier, arm, "confirmed") for arm in ARMS}
        windows = {}
        for arm in ARMS:
            w = _read(tier, arm, "windows")
            w = w[[c for c in base + ["fdr_rejected", "fdr_adjusted_pvalue"] if c in w.columns]]
            windows[arm] = with_fdr(w, confirmed[arm])
        out.append(compare_tier(tier, windows, confirmed))
        del windows
    rep = pd.concat(out, ignore_index=True)
    rep.to_parquet(OUT)
    pd.set_option("display.width", 220)
    print(rep.groupby(["tier", "confirmed_by", "reason"]).size().to_string())
    rep["worst_leg_no_trade_frac"] = rep[["no_trade_frac_a", "no_trade_frac_b"]].max(axis=1)
    rep["thinnest_leg_dollar_vol"] = rep[["median_dollar_vol_a", "median_dollar_vol_b"]].min(axis=1)
    print("\nmedians per group: worst leg's no-trade share, thinnest leg's median daily $ volume")
    print(rep.groupby(["tier", "confirmed_by"])[["worst_leg_no_trade_frac", "thinnest_leg_dollar_vol"]]
          .median().to_string())
    gs = rep[rep.reason == "grid_shift"]
    if len(gs):
        print(f"\ngrid_shift ({len(gs)}): |offset| to the other arm's nearest window, days: median "
              f"{gs.other_offset_days.abs().median():.0f}, max {gs.other_offset_days.abs().max():.0f}; nearest-window raw "
              f"p < 0.01 in {(gs.other_pvalue < 0.01).mean():.0%}, < 0.05 in {(gs.other_pvalue < 0.05).mean():.0%}")
    print(f"one-arm pairs with any no-trade day in the deciding window: {(rep.worst_leg_no_trade_frac > 0).sum()} "
          f"of {len(rep)}; max share {rep.worst_leg_no_trade_frac.max():.3f}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
