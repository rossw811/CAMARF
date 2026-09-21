"""
research/degenerate_column_audit.py -- Scans real output parquet files for
degenerate numeric columns (100% NaN, all-zero, zero-variance, or
suspiciously high NaN rate) that silently produce wrong-looking-right
results downstream, the exact failure shape that hid the half_life_rolling
bug (2026-09-10): a column that should carry real signal was 100% NaN for
a subset of pairs, no error, no warning, only visible by hand-comparing a
traded pair against a non-traded one.

Item #1 of the 5-part bug-catching plan (docs/HANDOFF.md 2026-09-10 entry):
"A degenerate-output auditor, run automatically after every pipeline
stage." This is the standalone, runnable version; wiring it into each
pipeline stage's own post-run hook is a separate, later step.

Flags, per numeric column in a scanned file:
- ALL_NAN: 100% of values are NaN.
- HIGH_NAN: NaN rate exceeds --nan-threshold (default 90%), excluding
  columns whose name suggests a warm-up/lag artifact is expected
  (heuristic allowlist, see _EXPECTED_HIGH_NAN_PATTERNS).
- ZERO_VARIANCE: every non-NaN value is identical (a real number, just
  never varies -- e.g. a hardcoded fallback silently overriding a real
  computation).
- ALL_ZERO: every non-NaN value is exactly 0 (a common silent-failure
  signature distinct from NaN).

Run: python research/degenerate_column_audit.py [--dir output/research]
     [--nan-threshold 0.9] [--pattern "*.parquet"]
Prints a report; also saves a machine-readable summary to
output/research/degenerate_column_audit_report.parquet.
"""
import argparse
import fnmatch
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# Column-name substrings where a high NaN rate is an EXPECTED warm-up/lag
# artifact, not a bug -- named explicitly so the auditor doesn't cry wolf
# on every rolling-window column, but still catches ALL_NAN (100%) even
# for these, since 100% NaN is never legitimate warm-up.
_EXPECTED_HIGH_NAN_PATTERNS = [
    r"^z_rolling$", r"^z_expanding$", r"trend_slope", r"_t$",
]


def _is_expected_high_nan(col_name: str) -> bool:
    return any(re.search(pat, col_name) for pat in _EXPECTED_HIGH_NAN_PATTERNS)


def audit_file(path: Path, nan_threshold: float) -> list:
    findings = []
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return [{"file": str(path), "column": None, "flag": "UNREADABLE", "detail": str(e)}]

    if len(df) == 0:
        return [{"file": str(path), "column": None, "flag": "EMPTY_FILE", "detail": "0 rows"}]

    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        series = df[col]
        n = len(series)
        n_nan = series.isna().sum()
        nan_rate = n_nan / n if n > 0 else 0.0

        if nan_rate == 1.0:
            findings.append({
                "file": str(path), "column": col, "flag": "ALL_NAN",
                "detail": f"{n_nan}/{n} NaN (100%)",
            })
            continue

        if nan_rate >= nan_threshold and not _is_expected_high_nan(col):
            findings.append({
                "file": str(path), "column": col, "flag": "HIGH_NAN",
                "detail": f"{n_nan}/{n} NaN ({nan_rate:.1%})",
            })

        valid = series.dropna()
        if len(valid) > 1:
            if (valid == 0).all():
                findings.append({
                    "file": str(path), "column": col, "flag": "ALL_ZERO",
                    "detail": f"{len(valid)} non-NaN values, all exactly 0",
                })
            elif valid.nunique() == 1:
                findings.append({
                    "file": str(path), "column": col, "flag": "ZERO_VARIANCE",
                    "detail": f"{len(valid)} non-NaN values, all == {valid.iloc[0]!r}",
                })

    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="output/research", help="Directory to scan (relative to repo root)")
    ap.add_argument("--pattern", default="*.parquet")
    ap.add_argument("--nan-threshold", type=float, default=0.90)
    ap.add_argument("--out", default="output/research/degenerate_column_audit_report.parquet")
    args = ap.parse_args()

    scan_dir = ROOT / args.dir
    files = sorted(f for f in scan_dir.rglob(args.pattern) if f.is_file())
    print(f"Scanning {len(files)} files under {scan_dir} (pattern={args.pattern})")

    all_findings = []
    for f in files:
        all_findings.extend(audit_file(f, args.nan_threshold))

    if not all_findings:
        print("No degenerate columns found.")
        return

    report = pd.DataFrame(all_findings)
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_parquet(out_path)

    print(f"\n{len(report)} findings across {report['file'].nunique()} files:")
    for flag in ["ALL_NAN", "ALL_ZERO", "ZERO_VARIANCE", "HIGH_NAN", "EMPTY_FILE", "UNREADABLE"]:
        sub = report[report["flag"] == flag]
        if len(sub) == 0:
            continue
        print(f"\n=== {flag} ({len(sub)}) ===")
        for _, row in sub.iterrows():
            rel = Path(row["file"]).relative_to(ROOT) if ROOT in Path(row["file"]).parents else row["file"]
            col = f".{row['column']}" if row["column"] else ""
            print(f"  {rel}{col}: {row['detail']}")

    print(f"\nSaved full report to {out_path}")


if __name__ == "__main__":
    main()
