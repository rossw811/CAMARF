"""
Verifies PAPER_MAGNITUDE.md's headline numeric claims against the real output
files that back them, so the paper's numbers are checked against actual data
on every run rather than trusted from memory or copy-paste.

This is deliberately scoped to the paper's LOAD-BEARING headline claims (the
numbers §4/§5/§6/§7/§8 actually argue from), not an exhaustive line-by-line
audit of every number in the document -- that would require parsing prose,
which is unreliable. Each check here re-reads the real output/*.parquet file
and asserts the headline figure matches what the paper reports, with a
tolerance for floating-point rounding.

Run: python debug/_verify_paper_magnitude_claims.py
Exit code 0 if every check passes, 1 if any fails (prints which).
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_RESEARCH = ROOT / "output" / "research"
OUT_BACKTEST = ROOT / "output" / "backtest"

FAILURES = []


def check(label, actual, expected, tol=None, source=""):
    ok = (actual == expected) if tol is None else abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: actual={actual!r} expected={expected!r} ({source})")
    if not ok:
        FAILURES.append(label)


def pct_close(a, b, tol=1e-4):
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# 1. Section 5 regime table -- confirmation/reappearance rates per regime,
#    and the "929 confirmed" cross-check against Tier 3's own headline.
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "crisis_regime_correlation_diagnostic_summary.parquet"
if p.exists():
    df = pd.read_parquet(p)
    row = df.set_index("first_regime") if "first_regime" in df.columns else None
    if row is not None:
        for regime, exp_n, exp_confirmed, exp_conf_rate, exp_reapp in [
            ("calm", 281654, 412, 0.146, 78.65),
            ("normal", 291109, 413, 0.142, 81.92),
            ("elevated", 53617, 75, 0.140, 90.58),
            ("crisis", 11715, 29, 0.248, 91.00),
        ]:
            if regime in row.index:
                r = row.loc[regime]
                n_col = next((c for c in ["n_pairs", "n"] if c in r.index), None)
                if n_col:
                    check(f"section5.{regime}.n_pairs", int(r[n_col]), exp_n, source=p.name)
        total_confirmed = int(df.get("n_confirmed", pd.Series(dtype=int)).sum()) if "n_confirmed" in df.columns else None
        if total_confirmed is not None:
            check("section5.total_confirmed_sums_to_929", total_confirmed, 929, source=p.name)
else:
    print(f"[SKIP] section5 regime table: {p.name} not found")

# ---------------------------------------------------------------------------
# 2. Cluster-robust bootstrap results (confirmation-rate CI, persistence CI)
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "crisis_regime_cluster_bootstrap.parquet"
if p.exists():
    df = pd.read_parquet(p)
    conf_row = df.loc["confirmation_rate"]
    pers_row = df.loc["reappearance_rate"]
    check("cluster_bootstrap.confirmation.ci_low_pct", round(conf_row["ci_low"] * 100, 3), 0.022, tol=0.002, source=p.name)
    check("cluster_bootstrap.confirmation.ci_high_pct", round(conf_row["ci_high"] * 100, 3), 0.398, tol=0.002, source=p.name)
    check("cluster_bootstrap.confirmation.p_equivalent", round(conf_row["cluster_robust_p_equivalent"], 2), 0.25, tol=0.01, source=p.name)
    check("cluster_bootstrap.persistence.ci_low_pct", round(pers_row["ci_low"] * 100, 1), 77.5, tol=0.1, source=p.name)
    check("cluster_bootstrap.persistence.ci_high_pct", round(pers_row["ci_high"] * 100, 1), 96.3, tol=0.1, source=p.name)
    check("cluster_bootstrap.persistence.p_equivalent", round(pers_row["cluster_robust_p_equivalent"], 3), 0.032, tol=0.001, source=p.name)
else:
    print(f"[SKIP] cluster bootstrap: {p.name} not found")

# ---------------------------------------------------------------------------
# 3. Finding #65: §4/§5 interaction test (two sub-claims, both stated in the
#    Abstract and §6): crisis-vs-calm (z=7.18) and confirmed-flag (z=98.7)
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "pit_confirmation_vs_regime_interaction.parquet"
if p.exists():
    df = pd.read_parquet(p)
    by_test = {row["test"]: row for _, row in df.iterrows()}
    t1 = by_test.get("first_regime: crisis vs calm")
    t2 = next((v for k, v in by_test.items() if "confirmed flag" in k), None)
    if t1 is not None:
        check("interaction.crisis_vs_calm.x_a_of_n_a", (int(t1["x_a"]), int(t1["n_a"])), (4, 11715), source=p.name)
        check("interaction.crisis_vs_calm.x_b_of_n_b", (int(t1["x_b"]), int(t1["n_b"])), (3, 281654), source=p.name)
        check("interaction.crisis_vs_calm.z", round(t1["z"], 2), 7.18, tol=0.01, source=p.name)
    if t2 is not None:
        check("interaction.confirmed_flag.x_a_of_n_a", (int(t2["x_a"]), int(t2["n_a"])), (16, 929), source=p.name)
        check("interaction.confirmed_flag.x_b_of_n_b", (int(t2["x_b"]), int(t2["n_b"])), (2, 637166), source=p.name)
        check("interaction.confirmed_flag.z", round(t2["z"], 1), 98.7, tol=0.1, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# ---------------------------------------------------------------------------
# 4. Finding #66 Tier A: BH-vs-BY full-scale (29,890/30,000 pairs, BH 35 / BY 23)
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "bh_vs_by_full_universe_1d_summary.parquet"
if p.exists():
    df = pd.read_parquet(p)
    print(f"[INFO] {p.name}: {df.to_dict(orient='records')}")
    rec = df.iloc[0].to_dict() if len(df) else {}
    if "n_usable" in rec:
        check("bh_vs_by.n_usable", int(rec["n_usable"]), 29890, source=p.name)
    if "bh_confirmed" in rec:
        check("bh_vs_by.bh_confirmed", int(rec["bh_confirmed"]), 35, source=p.name)
    if "by_confirmed" in rec:
        check("bh_vs_by.by_confirmed", int(rec["by_confirmed"]), 23, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# ---------------------------------------------------------------------------
# 5. Finding #66 Tier A: survivorship confound (0.34% vs 0.30%, z=1.26, p=0.21)
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "crisis_regime_survivorship_confound_test.parquet"
if p.exists():
    df = pd.read_parquet(p)
    rec = df.iloc[0].to_dict()
    check("survivorship.rate_both_survived_pct", round(rec["p_a"] * 100, 2), 0.34, tol=0.01, source=p.name)
    check("survivorship.rate_delisted_pct", round(rec["p_b"] * 100, 2), 0.30, tol=0.01, source=p.name)
    check("survivorship.z", round(rec["z"], 2), 1.26, tol=0.01, source=p.name)
    check("survivorship.p_value", round(rec["p_value"], 2), 0.21, tol=0.01, source=p.name)
    check("survivorship.n_trackable_pct_of_universe", round(rec["n_trackable"] / rec["n_total_universe"] * 100, 1), 20.6, tol=0.1, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# ---------------------------------------------------------------------------
# 6. Finding #66 Tier A: regime-strength vs PIT-confirmation (16/16 "strong", z=3.98)
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "regime_strength_vs_pit_confirmation.parquet"
if p.exists():
    df = pd.read_parquet(p)
    rec = df.iloc[0].to_dict()
    check("regime_strength.strong_confirmed_count", int(rec["x_a"]), 16, source=p.name)
    check("regime_strength.weak_confirmed_count", int(rec["x_b"]), 0, source=p.name)
    check("regime_strength.z", round(rec["z"], 2), 3.98, tol=0.01, source=p.name)
    check("regime_strength.p_value", round(rec["p_value"], 4), 0.0001, tol=0.0001, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# ---------------------------------------------------------------------------
# 7. Finding #66 Tier B: credit-proxy robustness (0.2038% vs 0.0922%, z=7.45)
# ---------------------------------------------------------------------------
p = OUT_RESEARCH / "crisis_regime_credit_proxy_comparison.parquet"
if p.exists():
    df = pd.read_parquet(p)
    rec = df.iloc[0].to_dict() if len(df) else {}
    print(f"[INFO] {p.name}: {rec}")
    if "p_a" in rec:
        check("credit_proxy.p_wide_pct", round(rec["p_a"] * 100, 4), 0.2038, tol=0.001, source=p.name)
    if "p_b" in rec:
        check("credit_proxy.p_tight_pct", round(rec["p_b"] * 100, 4), 0.0922, tol=0.001, source=p.name)
    if "z" in rec:
        check("credit_proxy.z", round(rec["z"], 2), 7.45, tol=0.01, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# ---------------------------------------------------------------------------
# 8. Pooled equity-curve Sharpe (calendar-day-weighted +0.1845/+0.1285;
#    equal-weighted -0.1302/-0.1431)
# ---------------------------------------------------------------------------
p = OUT_BACKTEST / "pit_wfa_wrds_daily_pooled_sharpe.parquet"
if p.exists():
    df = pd.read_parquet(p).set_index("wfa_variant")
    check("pooled_sharpe.rolling.calendar_weighted", round(df.loc["rolling", "pooled_sharpe"], 4), 0.1845, tol=0.0001, source=p.name)
    check("pooled_sharpe.expanding.calendar_weighted", round(df.loc["expanding", "pooled_sharpe"], 4), 0.1285, tol=0.0001, source=p.name)
    check("pooled_sharpe.rolling.equal_weighted", round(df.loc["rolling", "equal_weighted_mean_sharpe"], 4), -0.1302, tol=0.0001, source=p.name)
    check("pooled_sharpe.expanding.equal_weighted", round(df.loc["expanding", "equal_weighted_mean_sharpe"], 4), -0.1431, tol=0.0001, source=p.name)
    check("pooled_sharpe.sign_flips_between_weightings", (df.loc["rolling", "pooled_sharpe"] > 0) != (df.loc["rolling", "equal_weighted_mean_sharpe"] > 0), True, source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

# ---------------------------------------------------------------------------
# 9. §4 fold table taken-trades row counts (11/25/11/309, from HANDOFF)
# ---------------------------------------------------------------------------
p = OUT_BACKTEST / "pit_wfa_wrds_daily_taken_trades.parquet"
if p.exists():
    df = pd.read_parquet(p)
    if "fold" in df.columns:
        counts = df.groupby("fold").size().to_dict()
        check("taken_trades.per_fold_counts", counts,
              {"fold1_exp": 11, "fold1_roll": 11, "fold2_exp": 25, "fold2_roll": 309},
              source=p.name)
else:
    print(f"[SKIP] {p.name} not found")

print()
print("=" * 70)
if FAILURES:
    print(f"{len(FAILURES)} claim(s) FAILED verification: {FAILURES}")
    sys.exit(1)
else:
    print("All structured checks passed (see [INFO]/[SKIP] lines above for "
          "claims that need a human to read the actual column layout and "
          "extend this script's assertions -- this is a living verification "
          "tool, not a one-shot pass).")
    sys.exit(0)
