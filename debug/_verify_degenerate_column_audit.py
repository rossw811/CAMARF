"""
Synthetic verification for research/degenerate_column_audit.py. Builds a
small fixture parquet with known-degenerate and known-healthy columns and
confirms the auditor flags exactly the degenerate ones, nothing more,
nothing less.

Run: python debug/_verify_degenerate_column_audit.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.degenerate_column_audit import audit_file, _is_expected_high_nan

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_all_nan_flagged():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fixture.parquet"
        df = pd.DataFrame({
            "healthy_signal": np.random.randn(200),
            "half_life_rolling": [np.nan] * 200,  # the exact real-world bug shape
        })
        df.to_parquet(p)
        findings = audit_file(p, nan_threshold=0.9)
        flags = {f["column"]: f["flag"] for f in findings}
        check("all_nan.flagged_as_ALL_NAN", flags.get("half_life_rolling") == "ALL_NAN", flags)
        check("all_nan.healthy_not_flagged", "healthy_signal" not in flags, flags)


def test_all_zero_flagged():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fixture.parquet"
        df = pd.DataFrame({
            "real_pnl": np.random.randn(150) * 10,
            "always_zero": np.zeros(150),
        })
        df.to_parquet(p)
        findings = audit_file(p, nan_threshold=0.9)
        flags = {f["column"]: f["flag"] for f in findings}
        check("all_zero.flagged", flags.get("always_zero") == "ALL_ZERO", flags)
        check("all_zero.real_pnl_not_flagged", "real_pnl" not in flags, flags)


def test_zero_variance_flagged():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fixture.parquet"
        df = pd.DataFrame({
            "varying": np.arange(100, dtype=float),
            "stuck_constant": np.full(100, 3.14159),
        })
        df.to_parquet(p)
        findings = audit_file(p, nan_threshold=0.9)
        flags = {f["column"]: f["flag"] for f in findings}
        check("zero_var.flagged", flags.get("stuck_constant") == "ZERO_VARIANCE", flags)
        check("zero_var.varying_not_flagged", "varying" not in flags, flags)


def test_high_nan_threshold_and_allowlist():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fixture.parquet"
        n = 200
        high_nan_unexpected = np.full(n, np.nan)
        high_nan_unexpected[:15] = np.random.randn(15)  # 92.5% NaN, not a rolling-window-named column
        z_rolling_warmup = np.full(n, np.nan)
        z_rolling_warmup[:15] = np.random.randn(15)  # same NaN rate, but name matches the warm-up allowlist
        df = pd.DataFrame({
            "suspicious_metric": high_nan_unexpected,
            "z_rolling": z_rolling_warmup,
        })
        df.to_parquet(p)
        findings = audit_file(p, nan_threshold=0.9)
        flags = {f["column"]: f["flag"] for f in findings}
        check("high_nan.unexpected_column_flagged", flags.get("suspicious_metric") == "HIGH_NAN", flags)
        check("high_nan.allowlisted_warmup_column_not_flagged", "z_rolling" not in flags, flags)


def test_below_threshold_not_flagged():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fixture.parquet"
        n = 200
        arr = np.random.randn(n)
        arr[:20] = np.nan  # 10% NaN, below default 0.9 threshold
        df = pd.DataFrame({"mostly_fine": arr})
        df.to_parquet(p)
        findings = audit_file(p, nan_threshold=0.9)
        flags = {f["column"]: f["flag"] for f in findings}
        check("below_threshold.not_flagged", "mostly_fine" not in flags, flags)


def test_empty_file():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fixture.parquet"
        pd.DataFrame({"col": []}).to_parquet(p)
        findings = audit_file(p, nan_threshold=0.9)
        check("empty_file.flagged", any(f["flag"] == "EMPTY_FILE" for f in findings), findings)


def test_allowlist_helper():
    check("allowlist.matches_z_rolling", _is_expected_high_nan("z_rolling"))
    check("allowlist.matches_hedge_ratio_ols_t", _is_expected_high_nan("hedge_ratio_ols_t"))
    check("allowlist.does_not_match_half_life_rolling_incorrectly",
          not _is_expected_high_nan("half_life_rolling"))


if __name__ == "__main__":
    test_all_nan_flagged()
    test_all_zero_flagged()
    test_zero_variance_flagged()
    test_high_nan_threshold_and_allowlist()
    test_below_threshold_not_flagged()
    test_empty_file()
    test_allowlist_helper()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
