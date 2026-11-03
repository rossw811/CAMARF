"""
research/compare_amendment_runs.py on synthetic runs with known answers.
  1. pair overlap is unordered (B/A in one run = A/B in the other) and the counts are exact;
  2. positive-holdout share per pool = share of trials with holdout Sharpe > 0 (0 is not positive);
  3. kept-copy layout (flat) and live layout (strategy_search/ subdir) are both read;
  4. discovery arm: confirmed counts / overlap / fdr-rejected window counts exact.
Run: python debug/_verify_compare_amendment_runs.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))
import compare_amendment_runs as C

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def pairs(*ab):
    return pd.DataFrame(list(ab), columns=["symbol_a", "symbol_b"])


def write_run(d, live, sharpe_k1, sharpe_k2, k1, k2, passes):
    s = os.path.join(d, "strategy_search") if live else d
    os.makedirs(s, exist_ok=True)
    pd.DataFrame({"pool": ["pit_k1", "pit_k2"], "split": [0.5, 0.5], "selected": ["c1", "c2"],
                  "holdout_capsim_sharpe": [sharpe_k1[0], sharpe_k2[0]], "dsr": [0.1, 0.2], "pbo": [0.5, 0.6],
                  "passes": passes}).to_parquet(os.path.join(s, "summary.parquet"))
    pd.DataFrame({"pool": ["pit_k1"] * len(sharpe_k1) + ["pit_k2"] * len(sharpe_k2),
                  "holdout_capsim_sharpe": sharpe_k1 + sharpe_k2}).to_parquet(os.path.join(s, "all_trials.parquet"))
    k1.to_parquet(os.path.join(d, "purity_pairs_pit_k1_clean.parquet"))
    k2.to_parquet(os.path.join(d, "purity_pairs_pit_k2_clean.parquet"))


def main():
    with tempfile.TemporaryDirectory() as td:
        old, new = os.path.join(td, "old"), os.path.join(td, "new")
        write_run(old, False, [0.5, -0.1, 0.0, 0.2], [0.3, 0.4], pairs(("A", "B"), ("C", "D"), ("E", "F")),
                  pairs(("A", "B")), [False, False])
        write_run(new, True, [-0.5, -0.2, 0.1, 0.0], [0.0, 0.0], pairs(("B", "A"), ("C", "D"), ("G", "H"), ("I", "J")),
                  pairs(("X", "Y")), [False, True])
        cells, pools = C.search_table(old, new)
        k1 = pools[pools.pool == "pit_k1"].iloc[0]
        k2 = pools[pools.pool == "pit_k2"].iloc[0]
        check("unordered_overlap", (k1.pool_pairs_both, k1.pool_pairs_only_old, k1.pool_pairs_only_new) == (2, 1, 2),
              (k1.pool_pairs_both, k1.pool_pairs_only_old, k1.pool_pairs_only_new))
        check("pool_sizes", (k1.pool_pairs_old, k1.pool_pairs_new, k2.pool_pairs_both) == (3, 4, 0))
        check("positive_share_zero_not_positive", (k1.positive_holdout_share_old, k1.positive_holdout_share_new,
                                                   k2.positive_holdout_share_new) == (0.5, 0.25, 0.0))
        check("both_layouts_read", len(cells) == 2 and cells["passes_new"].tolist() == [False, True])

        d = os.path.join(td, "disc")
        os.makedirs(d)
        for sfx, t2, t3, rej in (("", pairs(("A", "B"), ("C", "D")), pairs(("A", "B")), [True, False, True]),
                                 ("_advzero", pairs(("D", "C"), ("E", "F")), pairs(("A", "B"), ("G", "H")), [True, False, False])):
            t2.to_parquet(os.path.join(d, C.SCAN.format("tier2_confirmed", sfx)))
            t3.to_parquet(os.path.join(d, C.SCAN.format("tier3_confirmed", sfx)))
            pd.DataFrame({"pvalue": [0.1, 0.2]}).to_parquet(os.path.join(d, C.SCAN.format("tier2_windows", sfx)))
            pd.DataFrame({"fdr_rejected": rej}).to_parquet(os.path.join(d, C.SCAN.format("tier3_windows", sfx)))
        T = C.discovery_table(d, "_advzero").set_index("tier")
        check("disc_tier2", tuple(T.loc["tier2_confirmed", ["primary", "_advzero", "both", "only_primary", "only_advzero"]])
              == (2, 2, 1, 1, 1))
        check("disc_tier3", tuple(T.loc["tier3_confirmed", ["primary", "_advzero", "both"]]) == (1, 2, 1))
        check("disc_windows", T.loc["tier3_windows (fdr-rejected windows / tested)", "primary"] == "2 / 3"
              and T.loc["tier3_windows (fdr-rejected windows / tested)", "_advzero"] == "1 / 3")

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
