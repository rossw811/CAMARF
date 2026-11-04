"""
Side-by-side report of two registered runs (2026-11-03, for the Amendment 7 report against Amendment 5).

  search:    the pre-registered strategy search of each run -- per cell (pool x split) the selected config, holdout
             capsim Sharpe, DSR, PBO, passes; per pool the share of all trials with a positive holdout Sharpe and the
             pool size. Old run = a kept copy (e.g. output/research/_superseded_a5_a6_20261102), new = live outputs.
  discovery: two discovery arms written side by side in one research dir (primary vs a suffixed arm, e.g. _advzero):
             tier-2/tier-3 confirmed counts, pair overlap, FDR-rejected window counts.

Pairs are unordered (A/B and B/A are one pair). Read-only; writes one markdown report.
    python research/compare_amendment_runs.py search --old output/research/_superseded_a5_a6_20261102 \
        --new output/research --out output/research/compare_a7_vs_a5.md
    python research/compare_amendment_runs.py discovery --dir output/research --arm _advzero \
        --out output/research/compare_a7_advzero.md
debug/_verify_compare_amendment_runs.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

import parquet_io

POOLS = ("pit_k1", "pit_k2")
SCAN = "wrds_deep_history_episodic_scan_{}{}.parquet"


def _search_files(d: str) -> dict:
    """Summary / trials / pools of one run; a kept copy is flat, live outputs keep the search in strategy_search/."""
    sub = os.path.join(d, "strategy_search")
    s = sub if os.path.exists(os.path.join(sub, "summary.parquet")) else d
    return {"summary": os.path.join(s, "summary.parquet"), "trials": os.path.join(s, "all_trials.parquet"),
            **{p: os.path.join(d, f"purity_pairs_{p}_clean.parquet") for p in POOLS}}


def pair_set(df: pd.DataFrame) -> set:
    return {tuple(sorted(ab)) for ab in zip(df["symbol_a"].astype(str), df["symbol_b"].astype(str))}


def search_table(old: str, new: str) -> tuple:
    fo, fn = _search_files(old), _search_files(new)
    so, sn = parquet_io.read_parquet(fo["summary"]), parquet_io.read_parquet(fn["summary"])
    keep = ["pool", "split", "selected", "holdout_capsim_sharpe", "dsr", "pbo", "passes"]
    cells = so[keep].merge(sn[keep], on=["pool", "split"], how="outer", suffixes=("_old", "_new"))
    to, tn = parquet_io.read_parquet(fo["trials"]), parquet_io.read_parquet(fn["trials"])
    rows = []
    for p in POOLS:
        r = {"pool": p}
        for tag, T, F in (("old", to, fo), ("new", tn, fn)):
            h = T.loc[T["pool"] == p, "holdout_capsim_sharpe"]
            r[f"n_trials_{tag}"] = int(len(h))
            r[f"positive_holdout_share_{tag}"] = float((h > 0).mean()) if len(h) else float("nan")
            r[f"pool_pairs_{tag}"] = int(len(pair_set(parquet_io.read_parquet(F[p], columns=["symbol_a", "symbol_b"]))))
        A = pair_set(parquet_io.read_parquet(fo[p], columns=["symbol_a", "symbol_b"]))
        B = pair_set(parquet_io.read_parquet(fn[p], columns=["symbol_a", "symbol_b"]))
        r.update(pool_pairs_both=len(A & B), pool_pairs_only_old=len(A - B), pool_pairs_only_new=len(B - A))
        rows.append(r)
    return cells.sort_values(["pool", "split"]).reset_index(drop=True), pd.DataFrame(rows)


def discovery_table(d: str, arm: str, base: str = "") -> pd.DataFrame:
    rows = []
    for tier in ("tier2_confirmed", "tier3_confirmed"):
        A = pair_set(parquet_io.read_parquet(os.path.join(d, SCAN.format(tier, base)), columns=["symbol_a", "symbol_b"]))
        B = pair_set(parquet_io.read_parquet(os.path.join(d, SCAN.format(tier, arm)), columns=["symbol_a", "symbol_b"]))
        rows.append({"tier": tier, "primary": len(A), arm: len(B), "both": len(A & B),
                     "only_primary": len(A - B), f"only{arm}": len(B - A)})
    for tier in ("tier2_windows", "tier3_windows"):
        r = {"tier": tier + " (fdr-rejected windows / tested)"}
        for tag, sfx in (("primary", base), (arm, arm)):
            p = os.path.join(d, SCAN.format(tier, sfx))
            cols = ["fdr_rejected"] if tier == "tier3_windows" else ["pvalue"]
            W = parquet_io.read_parquet(p, columns=cols)
            r[tag] = f"{int(W['fdr_rejected'].sum())} / {len(W)}" if "fdr_rejected" in W else f"- / {len(W)}"
        rows.append(r)
    return pd.DataFrame(rows)


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    def fmt(v):
        # counts become floats when another row is NaN (pandas upcasts the column); print them as integers
        if isinstance(v, float):
            return "" if pd.isna(v) else (str(int(v)) if v.is_integer() else f"{v:.4f}")
        return str(v)
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] +
                     ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["search", "discovery"])
    ap.add_argument("--old"); ap.add_argument("--new")
    ap.add_argument("--dir"); ap.add_argument("--arm", default="_advzero")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.mode == "search":
        cells, pools = search_table(a.old, a.new)
        text = (f"# Strategy search: {a.new} (new) vs {a.old} (old)\n\n## Cells\n\n{_md(cells)}\n\n"
                f"## Pools and trials\n\n{_md(pools)}\n\n"
                f"Cells passing: old {int(cells['passes_old'].fillna(False).sum())}, "
                f"new {int(cells['passes_new'].fillna(False).sum())} of {len(cells)}.\n")
    else:
        text = f"# Discovery: primary vs {a.arm} ({a.dir})\n\n{_md(discovery_table(a.dir, a.arm))}\n"
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
