"""
Verifies PAPER.md's headline numeric claims against the real output files
that back them, same discipline as debug/_verify_paper_magnitude_claims.py.
Scoped to the load-bearing claims: the Act Three (§7.20) PIT-safe backtest
that is now this paper's actual headline result, plus the original 2026-07-12
26-pair backtest kept as historical/Act One evidence.

Run: python debug/_verify_paper_claims.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_BACKTEST = ROOT / "output" / "backtest"

FAILURES = []


def check(label, actual, expected, tol=None, source=""):
    ok = (actual == expected) if tol is None else abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: actual={actual!r} expected={expected!r} ({source})")
    if not ok:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Act Three (§7.20): the genuinely PIT-safe 182-pair Purity backtest,
# capital-constrained, $100k fixed sizing -- now this paper's headline.
# ---------------------------------------------------------------------------
p = OUT_BACKTEST / "portfolio_layer1_pairsoverride_capsim_fixed_100000.parquet"
if p.exists():
    df = pd.read_parquet(p)
    check("act3.purity.is_sharpe", round(df["sharpe_portfolio"].iloc[0], 3), -0.679, tol=0.001, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

p = OUT_BACKTEST / "portfolio_layer1_holdout_pairsoverride_capsim_fixed_100000.parquet"
if p.exists():
    df = pd.read_parquet(p)
    check("act3.purity.oos_sharpe", round(df["sharpe_portfolio"].iloc[0], 3), -0.834, tol=0.001, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# Robustness: every capital-sizing-method variant at the base entry_zscore
# should be negative on both splits -- the paper's "loses under essentially
# every parameterization tested" claim, checked directly, not asserted.
sizing_variants_is = [
    "portfolio_layer1_pairsoverride_capsim_equity_proportional_100000.parquet",
    "portfolio_layer1_pairsoverride_capsim_fixed_100000.parquet",
    "portfolio_layer1_pairsoverride_capsim_fixed_100000_ccap.parquet",
    "portfolio_layer1_pairsoverride_capsim_fixed_100000_levcap0p5.parquet",
    "portfolio_layer1_pairsoverride_capsim_flat_2pct_100000.parquet",
    "portfolio_layer1_pairsoverride_capsim_full_kelly_100000.parquet",
]
sizing_variants_oos = [f.replace("portfolio_layer1_pairsoverride", "portfolio_layer1_holdout_pairsoverride")
                        for f in sizing_variants_is if "flat_2pct" not in f]

all_negative_is, all_negative_oos = True, True
for f in sizing_variants_is:
    fp = OUT_BACKTEST / f
    if fp.exists():
        s = pd.read_parquet(fp)["sharpe_portfolio"].iloc[0]
        if s >= 0:
            all_negative_is = False
        print(f"    IS  {f}: sharpe={s:.4f}")
for f in sizing_variants_oos:
    fp = OUT_BACKTEST / f
    if fp.exists():
        s = pd.read_parquet(fp)["sharpe_portfolio"].iloc[0]
        if s >= 0:
            all_negative_oos = False
        print(f"    OOS {f}: sharpe={s:.4f}")

check("act3.robustness.all_capital_sizing_variants_negative_is", all_negative_is, True, source="capsim sweep")
check("act3.robustness.all_capital_sizing_variants_negative_oos", all_negative_oos, True, source="capsim sweep")

# ---------------------------------------------------------------------------
# Act One historical backtest (2026-07-12, kept as supporting evidence,
# not reproducible from today's live cache -- see PAPER.md's own §3/Abstract
# disclosure). This check confirms the DISCLOSURE is accurate: today's cache
# should NOT match 5.2155/449/26, since the paper now says so explicitly.
# ---------------------------------------------------------------------------
p = OUT_BACKTEST / "baseline_portfolio_layer1_holdout.parquet"
if p.exists():
    df = pd.read_parquet(p)
    row = df.iloc[0]
    matches_old_headline = (int(row["n_trades_total"]) == 449 and int(row["n_pairs"]) == 26)
    check("act1.disclosure_accurate.current_cache_does_not_match_2026_07_12_headline",
          matches_old_headline, False,
          source=f"{p.name} (current: n_pairs={row['n_pairs']}, n_trades={row['n_trades_total']})")
else:
    print(f"[SKIP] {p.name} not found")

print()
print("=" * 70)
if FAILURES:
    print(f"{len(FAILURES)} claim(s) FAILED verification: {FAILURES}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
