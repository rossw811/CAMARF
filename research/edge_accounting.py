"""
research/edge_accounting.py -- how much of the gap between the pipeline as originally run and the corrected pipeline
each identified error accounts for (Ross 2026-10-25). Design, committed before any result:
docs/EDGE_ACCOUNTING_DESIGN_2026-10-25.md. DESCRIPTIVE, development data only (sealed rows never read: the loaders
and seal_trades), never a decision input.

2 x 2 x 2 factorial per pool k in {1, 2}: S pair selection (whole-history pool, no eligible_from gate, full-sample
spread windows | PIT pool, gate, formation-only windows), P P&L basis (legacy spread units with a drifting hedge |
dollar at entry hedge), X executability (trades across > 5-trading-day holes kept | dropped). One production
configuration (Config.BACKTEST defaults, OLS). Metric: equal-notional daily Sharpe; Shapley attribution with a joint
stationary block bootstrap.

Phases (CachyOS):
  python research/edge_accounting.py pools      whole-history pools, cleaned by the PIT pools' rules
  python research/edge_accounting.py spreads    whole-history spreads -> output/results_wholehistory/ (WH_RESULTS)
  python research/edge_accounting.py run        engine once per (arm, k), legacy P&L, both dollar passes
  python research/edge_accounting.py eval       cells, Shapley, bootstrap intervals, capital-sim corners
Check: debug/_verify_edge_accounting.py
"""
import argparse
import itertools
import math
import os
import sys
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

import parquet_io
from config import Config  # noqa: E402

R_DIR = os.path.join(ROOT, "output", "research")
WH_RESULTS = os.path.join(ROOT, "output", "results_wholehistory")
FACTORS = ("S", "P", "X")
CELLS = list(itertools.product((0, 1), repeat=3))     # (S, P, X), 1 = corrected
BOOT_REPS = 2000


def wh_pool_path(k):
    return os.path.join(R_DIR, f"edge_accounting_wh_pool_k{k}.parquet")


def trades_path(arm, k):
    return os.path.join(R_DIR, f"edge_accounting_trades_{arm}_k{k}.parquet")


# ---------------------------------------------------------------------------
# Pure pieces (debug/_verify_edge_accounting.py)
# ---------------------------------------------------------------------------

def in_universe(T: pd.DataFrame) -> pd.Series:
    """Trades the dollar basis can price apart from holes: the one trade set every cell uses."""
    return T["status_noholes"] == "ok"


def n_excluded(T: pd.DataFrame) -> int:
    return int((~in_universe(T)).sum())


def cell_returns(T: pd.DataFrame, p_corrected: bool, x_corrected: bool) -> pd.DataFrame:
    """Per-trade return per unit gross notional in one (P, X) cell of one selection arm's trades."""
    U = T[in_universe(T)]
    if x_corrected:
        U = U[U["status_holes"] != "unrealizable_gap"]
    if p_corrected:
        ret = U["pnl_dollar_net"] / U["notional_dollar_entry"]
    else:
        ret = U["pnl_net"] / U["n_shares_a"] / (1.0 + U["hedge_ratio"].abs())
    return pd.DataFrame({"exit_time": pd.to_datetime(U["exit_time"]).values, "ret": ret.to_numpy(float)})


def daily_series(C: pd.DataFrame, days: pd.DatetimeIndex) -> np.ndarray:
    """Equal-notional book: the day's return is the sum over trades exiting that business day (0 otherwise)."""
    t = pd.to_datetime(C["exit_time"])
    t = t.dt.tz_localize(None) if getattr(t.dt, "tz", None) is not None else t
    s = pd.Series(C["ret"].to_numpy(float), index=t.dt.normalize()).groupby(level=0).sum()
    return s.reindex(days, fill_value=0.0).to_numpy(float)


def sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    sd = x.std(ddof=1) if len(x) > 1 else 0.0
    return float(x.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan")


def shapley(v: dict) -> dict:
    """Shapley value of each factor for a function of 3 binary factors (1 = corrected), from all 8 cells: the mean
    over the 6 orderings of the change when the factor is corrected."""
    out = {}
    for i, f in enumerate(FACTORS):
        tot = 0.0
        for order in itertools.permutations(range(3)):
            state = [0, 0, 0]
            for j in order:
                if j == i:
                    before = v[tuple(state)]
                    state[j] = 1
                    tot += v[tuple(state)] - before
                    break
                state[j] = 1
        out[f] = tot / 6.0
    return out


def _naive_day(s: pd.Series) -> pd.Series:
    t = pd.to_datetime(s)
    return (t.dt.tz_localize(None) if getattr(t.dt, "tz", None) is not None else t).dt.normalize()


def _exits(T: pd.DataFrame) -> pd.Series:
    return _naive_day(T["exit_time"])


def eval_spans(T: dict, sealed_from) -> dict:
    """Evaluation calendars (Ross 2026-10-26 decision 3). One 1931-2025 grid for both selection arms zero-padded the
    PIT book's empty pre-2006 years (review: own-span PIT k1 -1.95, not -0.907), so each arm gets its own span (first
    to last pre-seal exit of its common-universe trades); the S/P/X decomposition uses the overlap ("same_era"), where
    both arms trade; "union" is the original single grid, kept for comparison with the 10-25 numbers."""
    end_cap = pd.Timestamp(sealed_from) - pd.Timedelta(days=1)
    own = {}
    for arm, t in T.items():
        e = _exits(t[in_universe(t)])
        e = e[e <= end_cap]
        own[arm] = (e.min(), e.max())
    starts, ends = [s for s, _ in own.values()], [e for _, e in own.values()]
    return {"own": own, "same_era": (max(starts), min(ends)), "union": (min(starts), max(ends))}


def span_table(T: dict, sealed_from):
    """Per (span, cell): trades exiting inside the span, days, mean trade return, Sharpe. Returns (table, matrices):
    matrices[span] = days x 8 cells (CELLS order) for the spans that share one calendar across cells -- same_era and
    union, the only ones a Shapley split or joint bootstrap is defined on ("own" changes the era along with S)."""
    sp = eval_spans(T, sealed_from)
    rows, mats = [], {}
    for span in ("own", "same_era", "union"):
        cols = []
        for s, p, x in CELLS:
            arm = "pit" if s else "wh"
            lo, hi = sp["own"][arm] if span == "own" else sp[span]
            days = pd.bdate_range(lo, hi)
            C = cell_returns(T[arm], bool(p), bool(x))
            e = _exits(C)
            C = C[((e >= lo) & (e <= hi)).to_numpy()]
            d = daily_series(C, days)
            cols.append(d)
            rows.append({"span": span, "S": s, "P": p, "X": x, "start": lo.date(), "end": hi.date(), "n_days": len(days),
                         "n_trades": len(C), "mean_trade_ret": float(C["ret"].mean()) if len(C) else float("nan"),
                         "sharpe": sharpe(d),
                         # arm-level count over all history (not this span): trades the P/X rules could not price
                         "n_excluded_arm": n_excluded(T[arm])})
        if span != "own":
            mats[span] = np.column_stack(cols)
    return pd.DataFrame(rows), mats


def joint_bootstrap_sharpes(M: np.ndarray, block: float, reps: int = BOOT_REPS, seed: int = 20261025) -> np.ndarray:
    """(reps x cells) Sharpes, each draw one stationary-bootstrap day path applied to every cell (column)."""
    from eg_null_correlation_matched_n14 import stationary_indices
    rng = np.random.default_rng(seed)
    out = np.empty((reps, M.shape[1]))
    for r in range(reps):
        idx = stationary_indices(M.shape[0], block, rng)
        out[r] = [sharpe(M[idx, c]) for c in range(M.shape[1])]
    return out


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

def phase_pools():
    import clean_pool_identity_pairs as cpi
    W = parquet_io.read_parquet(os.path.join(R_DIR, "purity_pairs.parquet"))
    cache = {}
    for k in (1, 2):
        P = W[W["n_windows_fdr_rejected"] >= k].drop(columns=["eligible_from"], errors="ignore").reset_index(drop=True)
        C, rows = cpi.clean_pool(P, k, cache)
        C.to_parquet(wh_pool_path(k), index=False)
        print(f"whole-history k{k}: {len(P)} -> {len(C)} after cleaning -> {wh_pool_path(k)}", flush=True)


def _wh_one(task):
    import episodic_pairs_adapter as ad
    from analysis import AnalysisPipeline
    a, b, tf = task
    ad._RESULTS_DIR = WH_RESULTS                       # never output/results (the production spreads)
    try:
        al = ad._load_aligned(a, b, tf, as_of_date=None, preloaded=_PRE.get(tf))
        if al is None:
            raise RuntimeError("insufficient data / alignment failed")
        built = AnalysisPipeline._build_pair_result({"symbol_a": a, "symbol_b": b, "eligible_from": None}, al, tf)
        if built is None:
            raise RuntimeError("_build_pair_result returned None")
        ad.write_spread_series(a, b, tf, built[1])
        return a, b, tf, "built"
    except Exception as e:  # noqa: BLE001 -- recorded per pair; the pair then has no spread and cannot trade
        return a, b, tf, f"FAILED: {type(e).__name__}: {e}"[:200]


_PRE = {}


def phase_spreads(workers):
    import multiprocessing as mp
    import episodic_pairs_adapter as ad
    from data import DataStore
    ad._RESULTS_DIR = WH_RESULTS
    P = pd.concat([parquet_io.read_parquet(wh_pool_path(k)) for k in (1, 2)]).drop_duplicates(["symbol_a", "symbol_b", "tf_label"])
    tasks = list(zip(P["symbol_a"], P["symbol_b"], P["tf_label"]))
    for tf in sorted(set(P["tf_label"])):
        syms = set(P.loc[P["tf_label"] == tf, "symbol_a"]) | set(P.loc[P["tf_label"] == tf, "symbol_b"])
        needed = {s for s in syms if (lambda d: d is None or d.empty)(DataStore.load(s, tf))}
        if needed:
            fu = ad._get_full_universe(tf)
            _PRE[tf] = {s: fu[s] for s in needed if s in fu}
            del fu
            print(f"{tf}: pre-resolved {len(_PRE[tf])}/{len(needed)} placeholder symbols", flush=True)
    import mp_pool   # fork on Linux, spawn on Windows; workers get the parent's _PRE either way
    t0, res = time.time(), []
    with mp_pool.worker_pool(workers, _wh_one, {"_PRE": _PRE}) as pool:
        for i, r in enumerate(pool.imap_unordered(_wh_one, tasks), 1):
            res.append(r)
            if i % 100 == 0 or i == len(tasks):
                print(f"{i}/{len(tasks)} ({time.time() - t0:.0f}s)", flush=True)
    R = pd.DataFrame(res, columns=["symbol_a", "symbol_b", "tf_label", "status"])
    R.to_parquet(os.path.join(R_DIR, "edge_accounting_wh_spreads_report.parquet"))
    print(R["status"].str.split(":").str[0].value_counts().to_string(), flush=True)


def _pool_for(arm, k):
    return parquet_io.read_parquet(wh_pool_path(k) if arm == "wh" else Config.DATA.PIT_POOL_PATHS[f"k{k}"])


def phase_run():
    import backtest as bt
    import pnl_dollar
    from strategy_search import seal_trades
    for arm, k in itertools.product(("wh", "pit"), (1, 2)):
        bt.SPREAD_ROOT = os.path.relpath(WH_RESULTS, ROOT) if arm == "wh" else "output/results"
        eng = bt.BacktestEngine(cfg=Config.BACKTEST, regime_cond=bt.RegimeConditioner(enabled=False),
                                ml_cond=bt.MLConditioner(enabled=False), layer2_enabled=False, legacy_pnl=True)
        trades, _ = bt._run_all_pairs(eng, ["ols"], SimpleNamespace(tf=None), _pool_for(arm, k), pd.DataFrame(),
                                      holdout_only=False, log_pairs=False)
        T = seal_trades(pd.DataFrame([vars(t) for t in trades]))
        if len(T) == 0:
            print(f"{arm} k{k}: 0 trades", flush=True)
            continue
        cols = ["tf", "symbol_a", "symbol_b", "hedge_ratio", "entry_time", "exit_time", "side", "n_shares_a"]
        d1 = pnl_dollar.add_dollar_pnl(T[cols])
        d0 = pnl_dollar.add_dollar_pnl(T[cols], check_holes=False)
        T["status_holes"] = d1["pnl_dollar_status"].to_numpy()
        T["status_noholes"] = d0["pnl_dollar_status"].to_numpy()
        T["pnl_dollar_net"] = d0["pnl_dollar_net"].to_numpy()          # identical to d1 wherever d1 is ok
        T["notional_dollar_entry"] = d0["notional_dollar_entry"].to_numpy()
        T.to_parquet(trades_path(arm, k), index=False)
        print(f"{arm} k{k}: {len(T)} trades; status (holes checked) {T['status_holes'].value_counts().to_dict()}",
              flush=True)
    bt.SPREAD_ROOT = "output/results"


def phase_eval():
    from pit_wfa_trade_bootstrap import politis_white_block_length
    for k in (1, 2):
        if not all(os.path.exists(trades_path(a, k)) for a in ("wh", "pit")):
            print(f"k{k}: trades missing, skipped", flush=True)
            continue
        T = {a: parquet_io.read_parquet(trades_path(a, k)) for a in ("wh", "pit")}
        cells, mats = span_table(T, Config.DATA.SEALED_FROM)
        cells.to_parquet(os.path.join(R_DIR, f"edge_accounting_k{k}.parquet"), index=False)
        print(f"\nk{k}: cells per span (own = each selection arm on its own span; descriptive, no decomposition)")
        print(cells.to_string(index=False))
        shap_rows = []
        for span in ("same_era", "union"):              # same_era is the headline; union = the 10-25 single grid
            M = mats[span]
            v = {c: cells[(cells.span == span) & (cells.S == c[0]) & (cells.P == c[1]) & (cells.X == c[2])]["sharpe"].iloc[0]
                 for c in CELLS}
            sh = shapley(v)
            block = max(1, int(round(politis_white_block_length(M[:, CELLS.index((0, 0, 0))]))))
            B = joint_bootstrap_sharpes(M, block)
            Bsh = np.array([[shapley({c: B[r, j] for j, c in enumerate(CELLS)})[f] for f in FACTORS] for r in range(len(B))])
            S = pd.DataFrame({"span": span, "factor": FACTORS, "shapley": [sh[f] for f in FACTORS],
                              "lo95": np.nanpercentile(Bsh, 2.5, axis=0), "hi95": np.nanpercentile(Bsh, 97.5, axis=0),
                              "alone_from_all_old": [v[tuple(int(i == j) for j in range(3))] - v[(0, 0, 0)] for i in range(3)],
                              "block": block, "n_days": M.shape[0]})
            shap_rows.append(S)
            fwd = [v[(0, 0, 0)], v[(1, 0, 0)], v[(1, 1, 0)], v[(1, 1, 1)]]
            print(f"\nk{k} {span}: {M.shape[0]} business days, block {block}")
            print(S.to_string(index=False))
            print(f"forward S -> P -> X: " + " -> ".join(f"{x:.2f}" for x in fwd))
        pd.concat(shap_rows).to_parquet(os.path.join(R_DIR, f"edge_accounting_shapley_k{k}.parquet"), index=False)
        _capsim_corners(T, k, eval_spans(T, Config.DATA.SEALED_FROM)).to_parquet(
            os.path.join(R_DIR, f"edge_accounting_capsim_k{k}.parquet"), index=False)


def _capsim_corners(T, k, sp):
    """Capital-constrained ($100k fixed) Sharpe for the two dollar-basis, holes-dropped corner cells (S old / new), on
    each arm's own span and on the same-era span. The same-era book starts fresh at the era start with only the trades
    that enter and exit inside it: the replay carries cash across the whole path, so clipping only the scoring grid let
    pre-era losses set the era's capital (review 2026-11-04: wh k1 entered 2005 with ~$2.7k and took 74 trades).
    Returns one row per (arm, span), saved by phase_eval; a failed corner is a row with its error, not a gap."""
    from strategy_search import _capsim_sharpe
    out = []
    for arm in ("wh", "pit"):
        U = T[arm][(T[arm]["status_holes"] == "ok")].copy()
        U["pnl_net"], U["pnl_basis"] = U["pnl_dollar_net"], "dollar"
        lo_e, hi_e = sp["same_era"]
        inside = (_naive_day(U["entry_time"]) >= lo_e) & (_exits(U) <= hi_e)
        for label, (lo, hi), V in (("own span", sp["own"][arm], U), ("same era", (lo_e, hi_e), U[inside])):
            row = {"k": k, "arm": arm, "span": label, "start": lo.date(), "end": hi.date(), "n_offered": len(V),
                   "n_taken": 0, "sharpe": float("nan"), "error": ""}
            try:
                sr, n = _capsim_sharpe(V, lo, hi)
                row.update(sharpe=float(sr), n_taken=int(n))
                print(f"  capital-sim ($100k fixed), {arm} k{k}, dollar, holes dropped, {label} {lo.date()}..{hi.date()}: "
                      f"Sharpe {sr:.2f} on {n} trades taken of {len(V)}")
            except Exception as e:  # noqa: BLE001 -- recorded, the corner cells are supplementary
                row["error"] = f"{type(e).__name__}: {e}"
                print(f"  capital-sim {arm} k{k} {label}: {row['error']}")
            out.append(row)
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("pools", "spreads", "run", "eval"))
    ap.add_argument("--workers", type=int, default=Config.RUNTIME.N_WORKERS)
    a = ap.parse_args()
    {"pools": phase_pools, "spreads": lambda: phase_spreads(a.workers), "run": phase_run, "eval": phase_eval}[a.phase]()


if __name__ == "__main__":
    main()
