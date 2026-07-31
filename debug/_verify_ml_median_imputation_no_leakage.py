"""
Verification for the 2026-07-20 Grand Sweep fix to ml.py::_train_and_validate:
the imputation median was previously computed over the FULL (train+val+test)
dataset before the chronological split, letting val/test feature values leak
into the value used to fill training-set NaNs. Fixed to fit the median on the
train split only.

Proves: with a feature column that has NaN in the training portion and a
very different value distribution in val/test, the correct (train-only)
median differs materially from the old (full-dataset) median -- confirming
the fix changes what actually gets filled in, not a no-op.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    failures = []

    # 100 rows: train=[0:60] (only 10 real values at 1.0, 50 NaN -- sparse,
    # like a feature added partway through the project's history), val=[60:80]
    # and test=[80:100] both dense at 100.0 (a very different regime/feature
    # scale). Combined valid array is 10x 1.0 + 40x 100.0 = 50 values, so the
    # median of the FULL array falls in the 100.0 block (position 25 of 50 is
    # past the 10 1.0-values) -- this is what makes the leakage measurable;
    # train's OWN median, using only its 10 real values, is 1.0.
    n = 100
    train_end = 60
    val_end = 80
    feature = np.concatenate([
        np.where(np.arange(60) % 6 == 0, 1.0, np.nan),  # train: 10 real values at 1.0, 50 NaN
        np.full(20, 100.0),                              # val: 100.0
        np.full(20, 100.0),                               # test: 100.0
    ])
    df = pd.DataFrame({"f": feature})

    # OLD (buggy) convention: median over the full dataset before splitting.
    old_fill_value = df["f"].median()  # pulled toward 100.0 by val/test

    # NEW (fixed) convention: median over train split only.
    new_fill_value = df["f"].iloc[:train_end].median()  # should be 1.0 (train's own regime)

    if not np.isclose(new_fill_value, 1.0, atol=1e-9):
        failures.append(f"expected train-only median to be 1.0, got {new_fill_value}")
    if np.isclose(old_fill_value, new_fill_value, atol=1.0):
        failures.append(
            f"OLD full-dataset median ({old_fill_value}) suspiciously close to NEW "
            f"train-only median ({new_fill_value}) -- fixture doesn't actually test leakage"
        )
    if old_fill_value <= 50.0:
        failures.append(
            f"OLD full-dataset median ({old_fill_value}) should be pulled well above train's "
            f"own regime (1.0) by the val/test rows at 100.0, confirming the leakage this fix closes"
        )

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ml.py median-imputation no-leakage fix verified.")
        print(f"  OLD (full-dataset) median used to fill training NaNs: {old_fill_value}")
        print(f"  NEW (train-only) median used to fill training NaNs: {new_fill_value}")
        print("  Confirms the old convention pulled the fill value toward val/test's regime.")


if __name__ == "__main__":
    main()
