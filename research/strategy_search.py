"""
research/strategy_search.py -- the pre-registered strategy parameter search (Design 1).
Pre-registration: docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md (committed and pushed BEFORE any result).

Phase "run": every grid configuration x pool is backtested ONCE over the full history, in-process through
backtest._run_all_pairs (the production per-pair loop, no copy), OLS hedge only, forked workers sharing the
parent's memory; each configuration's trades are written to output/research/strategy_search/<pool>/<cfg>.parquet
(resumable -- existing files are skipped). No holdout flag: splitting is done afterwards by calendar date.

Phase "eval": dollar P&L (pnl_dollar.py, USD-only legs), then for each split s in {0.5,0.6,0.7,0.8}:
development = entries before c(s) whose exit is also before c(s) (straddlers purged); holdout = entries on/after
c(s) + 1% embargo; development split into 4 equal calendar folds (fold straddlers purged); score = median fold
capital-sim Sharpe ($100k, fixed, portfolio_sim pnl_mode="dollar", business days zero-filled over the fold);
selected = best score. Deflated Sharpe over all trials of the split; PBO via CSCV (16 blocks) on the
development-period unconstrained daily dollar P&L matrix.

Usage (CachyOS): python research/strategy_search.py run [--workers N]
                 python research/strategy_search.py eval
Verified first: debug/_verify_strategy_search.py.
"""
import argparse
import itertools
import json
import os
import sys
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_OUT = os.path.join("output", "research", "strategy_search")
# Pre-registration Amendment 1: identity-pair-free pools
POOLS = {"pit_k1": os.path.join("output", "research", "purity_pairs_pit_k1_clean.parquet"),
         "pit_k2": os.path.join("output", "research", "purity_pairs_pit_k2_clean.parquet")}
SPLITS = (0.5, 0.6, 0.7, 0.8)
N_FOLDS = 4
EMBARGO_PCT = 0.01
CAPITAL = 100_000.0


# ---------------------------------------------------------------------------
# Grid (pre-registered)
# ---------------------------------------------------------------------------

def build_grid():
    stop_rules = [("legacy35", 3.5, False), ("dir35", 3.5, True), ("legacy45", 4.5, False)]
    grid = []
    for entry, (sname, stop, directional), rearm, exit_z, mh, gate in itertools.product(
            (2.0, 2.5, 3.0), stop_rules, (False, True), (0.0, 0.5), (1, 2, 3), ("none", "momentum")):
        cid = f"e{entry}_{sname}_rearm{int(rearm)}_x{exit_z}_mh{mh}_{gate}"
        grid.append({"id": cid, "ENTRY_ZSCORE": entry, "ENTRY_ZSCORE_MAX": stop, "STOP_ZSCORE": stop,
                     "directional_stop": directional, "reentry_rearm": rearm, "EXIT_ZSCORE": exit_z,
                     "MAX_HOLD_MULTIPLIER": mh, "momentum_gate": gate == "momentum"})
    return grid


# ---------------------------------------------------------------------------
# Run phase
# ---------------------------------------------------------------------------

_POOL_DF = {}


def _run_one(task):
    import copy
    import backtest as bt
    from config import Config
    pool_name, c = task
    out = os.path.join(_OUT, pool_name, f"{c['id']}.parquet")
    if os.path.exists(out):
        return c["id"], "cached"
    cfg = copy.copy(Config.BACKTEST)
    for k in ("ENTRY_ZSCORE", "ENTRY_ZSCORE_MAX", "STOP_ZSCORE", "EXIT_ZSCORE", "MAX_HOLD_MULTIPLIER"):
        setattr(cfg, k, c[k])
    flags = {"directional_stop": c["directional_stop"], "reentry_rearm": c["reentry_rearm"],
             "momentum_gate": c["momentum_gate"]}
    eng = bt.BacktestEngine(cfg=cfg, regime_cond=bt.RegimeConditioner(enabled=False),
                            ml_cond=bt.MLConditioner(enabled=False), layer2_enabled=False, storm_flags=flags)
    args = SimpleNamespace(tf=None)
    trades, _ = bt._run_all_pairs(eng, ["ols"], args, _POOL_DF[pool_name], pd.DataFrame(), holdout_only=False,
                                  log_pairs=False)
    df = pd.DataFrame([vars(t) for t in trades])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_parquet(out + ".tmp")
    os.replace(out + ".tmp", out)
    return c["id"], len(df)


def run_phase(workers):
    import multiprocessing as mp
    for name, path in POOLS.items():
        _POOL_DF[name] = pd.read_parquet(path)
    tasks = [(p, c) for p in POOLS for c in build_grid()]
    print(f"{len(tasks)} runs, {workers} workers", flush=True)
    t0 = time.time()
    with mp.get_context("fork").Pool(workers) as pool:
        for i, (cid, n) in enumerate(pool.imap_unordered(_run_one, tasks), 1):
            if i % 10 == 0 or i == len(tasks):
                print(f"{i}/{len(tasks)} done ({time.time() - t0:.0f}s); last {cid}: {n}", flush=True)


# ---------------------------------------------------------------------------
# Evaluation helpers (pure; tested in debug/_verify_strategy_search.py)
# ---------------------------------------------------------------------------

def split_trades(trades, t0, T, s, embargo_pct=EMBARGO_PCT):
    """(development, holdout, cutoff). Development purges trades that exit on/after the cutoff."""
    c = t0 + (T - t0) * s
    emb = (T - t0) * embargo_pct
    e, x = pd.to_datetime(trades["entry_time"]), pd.to_datetime(trades["exit_time"])
    dev = trades[(e >= t0) & (e < c) & (x < c)]
    hold = trades[e >= c + emb]
    return dev, hold, c


def fold_edges(t0, c, n=N_FOLDS):
    return [t0 + (c - t0) * i / n for i in range(n + 1)]


def fold_trades(dev, edges, i):
    e, x = pd.to_datetime(dev["entry_time"]), pd.to_datetime(dev["exit_time"])
    return dev[(e >= edges[i]) & (e < edges[i + 1]) & (x < edges[i + 1])]


def sharpe_daily(daily):
    daily = np.asarray(daily, float)
    if len(daily) < 5 or daily.std(ddof=1) == 0:
        return float("nan")
    return float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))


def cscv_pbo(M: np.ndarray, n_blocks: int = 16):
    """Probability of Backtest Overfitting (Bailey, Borwein, Lopez de Prado & Zhu 2017).
    M: T x N matrix of per-period returns (rows = time, columns = configurations). Rows are split into
    n_blocks contiguous blocks; for every choice of half the blocks as in-sample, the best in-sample
    configuration's out-of-sample relative rank w is recorded; PBO = share of combinations with
    logit(w) <= 0 (the in-sample winner falls at or below the out-of-sample median)."""
    T, N = M.shape
    blocks = np.array_split(np.arange(T), n_blocks)
    logits = []
    for is_idx in itertools.combinations(range(n_blocks), n_blocks // 2):
        oos_idx = [b for b in range(n_blocks) if b not in is_idx]
        IS = M[np.concatenate([blocks[b] for b in is_idx])]
        OS = M[np.concatenate([blocks[b] for b in oos_idx])]
        sr = lambda X: X.mean(0) / np.where(X.std(0, ddof=1) > 0, X.std(0, ddof=1), np.nan)
        s_is, s_os = sr(IS), sr(OS)
        if np.all(np.isnan(s_is)):
            continue
        n_star = int(np.nanargmax(s_is))
        rank = (np.sum(s_os[~np.isnan(s_os)] < s_os[n_star]) + 1) / (np.sum(~np.isnan(s_os)) + 1)
        logits.append(np.log(rank / (1 - rank)))
    logits = np.array(logits)
    return float(np.mean(logits <= 0)) if len(logits) else float("nan"), logits


# ---------------------------------------------------------------------------
# Eval phase
# ---------------------------------------------------------------------------

def _capsim_sharpe(trades, start, end):
    import portfolio_math as pm
    import portfolio_sim
    if len(trades) == 0:
        return float("nan"), 0
    r = portfolio_sim.replay_portfolio(trades, CAPITAL, "fixed", pnl_mode="dollar")
    if r["n_taken"] == 0:
        return float("nan"), 0
    d = pm.daily_pnl_from_exits(r["taken"]["exit_time"], r["taken"]["actual_pnl"], start=start, end=end)
    return sharpe_daily(d.to_numpy()), r["n_taken"]


def eval_phase():
    import pnl_dollar
    import portfolio_math as pm
    from deflated_sharpe import deflated_sharpe_ratio
    from scipy import stats as st
    grid = {c["id"]: c for c in build_grid()}
    rows, summary = [], []
    for pname, ppath in POOLS.items():
        pool = pd.read_parquet(ppath)
        t0 = pd.to_datetime(pool["eligible_from"]).min().normalize()
        cache = {}
        for cid in grid:
            f = os.path.join(_OUT, pname, f"{cid}.parquet")
            if not os.path.exists(f):
                continue
            T = pd.read_parquet(f)
            if len(T) == 0:
                cache[cid] = T
                continue
            D = pnl_dollar.add_dollar_pnl(T)
            cache[cid] = D[D["pnl_dollar_status"] == "ok"]
        T_end = max(pd.to_datetime(d["exit_time"]).max() for d in cache.values() if len(d))
        for s in SPLITS:
            per = {}
            for cid, D in cache.items():
                dev, hold, c = split_trades(D, t0, T_end, s) if len(D) else (D, D, None)
                if c is None:
                    continue
                edges = fold_edges(t0, c)
                fs = [_capsim_sharpe(fold_trades(dev, edges, i), edges[i], edges[i + 1])[0] for i in range(N_FOLDS)]
                h_sh, h_n = _capsim_sharpe(hold, c + (T_end - t0) * EMBARGO_PCT, T_end)
                dev_daily = pm.daily_pnl_from_trades(dev, "pnl_dollar_net", start=t0, end=c)
                per[cid] = {"folds": fs, "score": float(np.nanmedian(fs)) if np.any(np.isfinite(fs)) else np.nan,
                            "holdout": h_sh, "n_hold": h_n, "n_dev": len(dev), "dev_daily": dev_daily}
                rows.append({"pool": pname, "split": s, "config": cid, "score": per[cid]["score"],
                             **{f"fold{i+1}": v for i, v in enumerate(fs)}, "holdout_capsim_sharpe": h_sh,
                             "n_dev_trades": len(dev), "n_holdout_taken": h_n})
            scored = {k: v for k, v in per.items() if np.isfinite(v["score"])}
            if not scored:
                continue
            best = max(scored, key=lambda k: (scored[k]["score"], -scored[k]["n_dev"]))
            sr_per = {k: v["dev_daily"].mean() / v["dev_daily"].std(ddof=1)
                      for k, v in per.items() if len(v["dev_daily"]) > 5 and v["dev_daily"].std(ddof=1) > 0}
            x = per[best]["dev_daily"].to_numpy()
            dsr = deflated_sharpe_ratio(sr_per.get(best, np.nan), len(x), float(st.skew(x)), float(st.kurtosis(x, fisher=False)),
                                        n_trials=2 * len(grid), var_sr_across_trials=float(np.var(list(sr_per.values()))))
            ids = sorted(per)
            M = pd.concat([per[k]["dev_daily"].rename(k) for k in ids], axis=1).fillna(0.0).to_numpy()
            pbo, _ = cscv_pbo(M)
            hold_rank = pd.Series({k: v["holdout"] for k, v in per.items()}).rank(ascending=False)[best]
            summary.append({"pool": pname, "split": s, "cutoff": str(c.date()), "selected": best,
                            "dev_score": scored[best]["score"], "holdout_capsim_sharpe": per[best]["holdout"],
                            "holdout_rank": float(hold_rank), "n_configs": len(per), "dsr": dsr, "pbo": pbo,
                            "passes": bool(per[best]["holdout"] > 0 and dsr >= 0.95 and pbo < 0.20)})
            print(summary[-1], flush=True)
    pd.DataFrame(rows).to_parquet(os.path.join(_OUT, "all_trials.parquet"))
    S = pd.DataFrame(summary)
    S.to_parquet(os.path.join(_OUT, "summary.parquet"))
    for pname in POOLS:
        sub = S[S["pool"] == pname]
        verdict = "REAL SIGNAL (passes every split)" if len(sub) == len(SPLITS) and sub["passes"].all() \
            else "no robust signal found"
        print(f"{pname}: {verdict}")
    with open(os.path.join(_OUT, "trials.json"), "w") as fh:
        json.dump({"n_trials": len(rows), "prereg": "docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md"}, fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["run", "eval"])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    a = ap.parse_args()
    run_phase(a.workers) if a.phase == "run" else eval_phase()


if __name__ == "__main__":
    main()
    if "eval" in sys.argv[1:]:  # lineage: the stage is complete once the pre-registered evaluation has run
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pipeline_stages import stage
        stage("strategy_search").record()
