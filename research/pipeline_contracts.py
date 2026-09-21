"""
research/pipeline_contracts.py -- Schema/contract validation for the major
intermediate artifacts scripts pass between each other. Item #2 of the
5-part bug-catching plan (docs/HANDOFF.md 2026-09-10 entry).

Three real bugs from a single session motivated this: a hand-built
--pairs-override file stripped to 3 columns silently zeroed every pair
in backtest.py (it needs the full pairs.parquet row schema); stats.py's
cache-path lookup doesn't recognize WRDS's "1D" label, silently NaN-ing
every WRDS-daily pair's hedge-ratio comparison; a non-boolean default in
backtest.py's storm_flags dict poisoned an any()-truthiness check, mis-
labeling every output file. Each is a different script trusting an
input's shape or convention without checking it at the boundary.

This module defines the expected schema (required columns, dtypes, valid
ranges where meaningful) for each major artifact type, and a validate_*
function that checks a real DataFrame against it, returning a list of
violations (empty list = passes). Fail LOUD at the boundary, not three
layers downstream as a silent NaN cascade.

Run standalone to validate real files: python research/pipeline_contracts.py
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ColumnContract:
    name: str
    required: bool = True
    numeric: bool = False
    # Optional validity check on the column's own values, e.g. lambda s: (s > 0).all()
    valid_check: Optional[Callable[[pd.Series], bool]] = None
    valid_check_desc: str = ""


@dataclass
class TableContract:
    name: str
    columns: list = field(default_factory=list)
    min_rows: int = 1


def validate(df: pd.DataFrame, contract: TableContract) -> list:
    violations = []
    if len(df) < contract.min_rows:
        violations.append(f"{contract.name}: only {len(df)} rows, expected >= {contract.min_rows}")

    for col in contract.columns:
        if col.name not in df.columns:
            if col.required:
                violations.append(f"{contract.name}: missing required column '{col.name}'")
            continue
        series = df[col.name]
        if col.numeric:
            n_na = series.isna().sum()
            if n_na == len(series) and len(series) > 0:
                violations.append(f"{contract.name}.{col.name}: 100% NaN, contract requires a numeric column with real values")
        if col.valid_check is not None:
            try:
                ok = col.valid_check(series.dropna())
                if not ok:
                    desc = col.valid_check_desc or "custom check"
                    violations.append(f"{contract.name}.{col.name}: failed validity check ({desc})")
            except Exception as e:
                violations.append(f"{contract.name}.{col.name}: validity check raised {e}")

    return violations


# ---------------------------------------------------------------------------
# Contracts for the artifacts that actually caused real bugs this session
# ---------------------------------------------------------------------------

PAIRS_OVERRIDE_CONTRACT = TableContract(
    name="pairs_override_file",
    min_rows=1,
    columns=[
        ColumnContract("symbol_a", required=True),
        ColumnContract("symbol_b", required=True),
        ColumnContract("tf_label", required=True),
        # The exact field whose absence silently zeroed every pair
        # (backtest.py's engine.run() reads it as a scalar fallback and
        # skips the pair outright if non-finite/<=0).
        ColumnContract("hedge_ratio_ols", required=True, numeric=True,
                        valid_check=lambda s: len(s) == 0 or (np.isfinite(s) & (s != 0)).mean() > 0.5,
                        valid_check_desc="most rows should have a finite, nonzero hedge ratio"),
        ColumnContract("coint_fraction_rolling", required=False, numeric=True),
        ColumnContract("coint_pvalue_adjusted", required=False, numeric=True),
    ],
)

SPREAD_SERIES_CONTRACT = TableContract(
    name="spread_series_file",
    min_rows=60,  # backtest.py's own engine.run() minimum
    columns=[
        ColumnContract("spread", required=True, numeric=True),
        ColumnContract("z_rolling", required=True, numeric=True),
        ColumnContract("half_life_rolling", required=True, numeric=True,
                        valid_check=lambda s: len(s) == 0 or s.notna().mean() > 0.0,
                        valid_check_desc="half_life_rolling should not be 100% NaN "
                                         "(the exact 2026-09-10 KVUE/KMB bug)"),
    ],
)

TRADES_CONTRACT = TableContract(
    name="trades_file",
    min_rows=0,  # zero trades can be legitimate (e.g. a genuinely non-trading pair)
    columns=[
        ColumnContract("symbol_a", required=True),
        ColumnContract("symbol_b", required=True),
        ColumnContract("total_pnl", required=False, numeric=True),
    ],
)


def _check_file(path: Path, contract: TableContract):
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return [f"{path}: UNREADABLE ({e})"]
    return [f"{path}: {v}" for v in validate(df, contract)]


if __name__ == "__main__":
    import glob

    print("=== Validating pairs-override-style files ===")
    for f in glob.glob(str(ROOT / "output" / "research" / "*pair*override*.parquet")):
        for v in _check_file(Path(f), PAIRS_OVERRIDE_CONTRACT):
            print(" ", v)

    print("\n=== Validating spread_series files (sample) ===")
    spread_files = list((ROOT / "output" / "results").rglob("spread_series_*.parquet"))
    print(f"({len(spread_files)} total, checking all)")
    n_violations = 0
    for f in spread_files:
        vs = _check_file(f, SPREAD_SERIES_CONTRACT)
        n_violations += len(vs)
        for v in vs:
            print(" ", v)
    print(f"\n{n_violations} contract violations across {len(spread_files)} spread_series files")
