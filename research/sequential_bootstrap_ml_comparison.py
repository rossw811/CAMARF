"""
Comparison arm to ml.py's `_train_and_validate` baseline training scheme
(sklearn's class-"balanced" sample_weight only, no overlap correction).
Tests Lopez de Prado's (AFML Ch. 4) average-uniqueness weighting and
sequential-bootstrap resampling on the SAME chronological train/val/test
split and SAME XGBoost hyperparameters ml.py already uses -- this script
changes only the training-sample selection/weighting, per this project's
standing rule (CLAUDE.md) that a new methodology is built as a comparison
arm alongside the existing method, never dropped straight into production.

Approved by Ross 2026-09-08 as the first of PAPER.md §10's three future-
work candidates to build, after an explicit design discussion. That
discussion flagged one real open question this script resolves and
discloses rather than assumes: overlap is computed PER PAIR (each
(symbol_a, symbol_b, tf_label)'s own entry-event sequence is the
underlying "series" AFML's overlap concept applies to), NOT pooled across
different pairs -- two different pairs' trades occurring at the same
wall-clock time is a portfolio-concurrency question, not a labeling-
uniqueness one, and this project's ml.py already treats each pair's
entry-event sequence as its own independent bet stream feeding one
pooled training set.

Real motivating bias this targets (already documented as a limitation in
PAPER.md §8): with only 12-32 labeled examples currently, overlapping
labels from the same pair's repeated re-entries overstate the effective
sample size XGBoost's "balanced" class-weighting alone does not correct
for -- an example that shares most of its holding window with 3 other
examples from the same pair is currently weighted as if it were 4
independent observations.

Label-window end-time approximation, disclosed: ml.py's EntryEvent does
not persist an explicit label end-timestamp, only horizon_bars (an
integer bar count). This script approximates end_time = entry_time +
horizon_bars * bar_duration(tf_label) using this project's own documented
per-timeframe bar durations -- ignores non-trading-hour/weekend gaps for
intraday TFs. This is a disclosed approximation used ONLY for computing
overlap weights here; it is not used anywhere trading-relevant and does
not touch ml.py's own horizon/resolution logic.
"""
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import ml
from config import Config

_OUT_DIR = os.path.join(_ROOT, "output", "research")
_LOG_PATH = os.path.join(_ROOT, "latest_run_sequential_bootstrap_ml_comparison.log")

import logging
log = logging.getLogger(__name__)


_TF_TIMEDELTA = {
    "1m": pd.Timedelta(minutes=1), "3m": pd.Timedelta(minutes=3),
    "5m": pd.Timedelta(minutes=5), "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30), "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4), "1D": pd.Timedelta(days=1),
}


def compute_label_end_times(df: pd.DataFrame) -> pd.Series:
    """entry_time + horizon_bars * bar_duration(tf_label). See module
    docstring's disclosed-approximation note."""
    deltas = df["tf_label"].map(_TF_TIMEDELTA)
    unknown = deltas.isna()
    if unknown.any():
        bad = sorted(df.loc[unknown, "tf_label"].unique())
        raise ValueError(f"No bar-duration mapping for tf_label(s): {bad} -- "
                          f"add to _TF_TIMEDELTA before using this script on that data.")
    return df["entry_time"] + deltas * df["horizon_bars"].astype(float)


def _pair_average_uniqueness(starts: np.ndarray, ends: np.ndarray,
                              extra_starts: np.ndarray = None,
                              extra_ends: np.ndarray = None) -> np.ndarray:
    """Average uniqueness of each label i in (starts, ends), i.e. the mean
    of 1/concurrency(t) over t in label i's own span, where concurrency(t)
    counts label i itself plus every other label (from `starts`/`ends`, and
    optionally an `extra_*` set representing already-bootstrap-drawn copies)
    whose span covers t. AFML Ch. 4's own definition, evaluated at the
    boundary timestamps (entries and exits) rather than a fixed time grid --
    exact, not a discretization approximation, since concurrency only
    changes at a start or end event."""
    n = len(starts)
    all_starts = starts if extra_starts is None else np.concatenate([starts, extra_starts])
    all_ends = ends if extra_ends is None else np.concatenate([ends, extra_ends])
    avg_u = np.empty(n)
    for i in range(n):
        # Concurrency is piecewise-constant between consecutive start/end
        # events, so partitioning label i's own span at every OTHER label's
        # start/end event that falls strictly inside it gives an EXACT
        # (not discretized) set of constant-concurrency segments -- average
        # uniqueness is then the DURATION-weighted mean of 1/concurrency
        # across those segments (AFML Ch.4's own definition, generalized
        # from a fixed bar grid to continuous time). An earlier version
        # equal-weighted per breakpoint instead of by duration and failed
        # debug/_verify_sequential_bootstrap_ml_comparison.py's partial-
        # overlap check (unequal-duration segments must not count equally).
        events = np.concatenate([all_starts, all_ends])
        events = events[(events > starts[i]) & (events < ends[i])]
        breakpoints = np.unique(np.concatenate([[starts[i]], events, [ends[i]]]))
        durations = np.diff(breakpoints).astype(np.float64)
        segment_starts = breakpoints[:-1]
        concurrency = np.array([
            np.sum((all_starts <= s) & (all_ends > s)) for s in segment_starts
        ])
        total_duration = durations.sum()
        avg_u[i] = 1.0 if total_duration <= 0 else float(
            np.sum((1.0 / concurrency) * durations) / total_duration
        )
    return avg_u


def average_uniqueness_per_pair(df: pd.DataFrame) -> pd.Series:
    """AFML Ch. 4 average uniqueness, computed independently within each
    (symbol_a, symbol_b, tf_label) pair. See module docstring for why
    cross-pair overlap is deliberately out of scope."""
    df = df.copy()
    df["_end_time"] = compute_label_end_times(df)
    uniq = pd.Series(index=df.index, dtype=float)
    for _, group in df.groupby(["symbol_a", "symbol_b", "tf_label"]):
        idx = group.index
        starts = group["entry_time"].values.astype("datetime64[ns]").astype(np.int64)
        ends = group["_end_time"].values.astype("datetime64[ns]").astype(np.int64)
        if len(group) == 1:
            uniq.loc[idx] = 1.0
            continue
        uniq.loc[idx] = _pair_average_uniqueness(starts, ends)
    return uniq


def sequential_bootstrap_indices(df: pd.DataFrame, n_samples: int = None,
                                  random_state: int = 42) -> np.ndarray:
    """AFML Snippet 4.3, applied independently per pair (same scope as
    average_uniqueness_per_pair) then concatenated: draws n_samples
    positional indices (into df, default len(df)) WITH replacement, one at
    a time, each draw's probability proportional to the CURRENT average
    uniqueness -- recomputed after every draw to account for already-drawn
    overlapping labels, so a region that has already been sampled densely
    becomes progressively less likely to be re-drawn."""
    rng = np.random.RandomState(random_state)
    n_total = n_samples if n_samples is not None else len(df)
    df = df.reset_index(drop=False).rename(columns={"index": "_orig_idx"})
    df["_end_time"] = compute_label_end_times(df)

    chosen_orig_idx = []
    groups = {key: g for key, g in df.groupby(["symbol_a", "symbol_b", "tf_label"])}
    # Allocate draws proportionally to each pair's own example count so a
    # pair with more examples isn't starved relative to the baseline
    # (non-bootstrap) scheme, which implicitly gives every row equal say.
    weights = np.array([len(g) for g in groups.values()], dtype=float)
    weights /= weights.sum()
    n_per_group = np.random.RandomState(random_state).multinomial(n_total, weights)

    for (key, group), n_draw in zip(groups.items(), n_per_group):
        starts = group["entry_time"].values.astype("datetime64[ns]").astype(np.int64)
        ends = group["_end_time"].values.astype("datetime64[ns]").astype(np.int64)
        orig_idx = group["_orig_idx"].values
        n = len(group)
        if n == 1 or n_draw == 0:
            chosen_orig_idx.extend([orig_idx[0]] * n_draw)
            continue
        drawn_positions = []
        for _ in range(n_draw):
            if drawn_positions:
                extra_starts = starts[drawn_positions]
                extra_ends = ends[drawn_positions]
            else:
                extra_starts = extra_ends = None
            avg_u = _pair_average_uniqueness(starts, ends, extra_starts, extra_ends)
            probs = avg_u / avg_u.sum()
            choice = rng.choice(n, p=probs)
            drawn_positions.append(choice)
            chosen_orig_idx.append(orig_idx[choice])
    return np.array(chosen_orig_idx)


def _fit_xgb(X_train, y_train, sample_weight, n_classes):
    import xgboost as xgb
    if n_classes <= 2:
        objective, eval_metric = "binary:logistic", "logloss"
    else:
        objective, eval_metric = "multi:softprob", "mlogloss"
    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        objective=objective, eval_metric=eval_metric,
        random_state=42, n_jobs=1,
    )
    model.fit(X_train, y_train, sample_weight=sample_weight)
    return model


def run_comparison(result: "ml.MLResult") -> dict:
    """Reuses ml.py's exact chronological train/val/test split, feature
    columns, and XGBoost hyperparameters (_train_and_validate's own
    convention) -- only the TRAIN split's sampling/weighting changes
    between the two arms."""
    from sklearn.preprocessing import LabelEncoder
    from sklearn.utils.class_weight import compute_sample_weight

    df = result.examples.sort_values("entry_time").reset_index(drop=True)
    X_raw = df[ml._FEATURE_COLS]
    le = LabelEncoder()
    y = le.fit_transform(df["label_for_training"])
    n_classes = len(le.classes_)

    n = len(df)
    train_end = int(n * Config.ML.TRAIN_PCT)
    val_end = train_end + int(n * Config.ML.VAL_PCT)

    train_median = X_raw.iloc[:train_end].median()
    X = X_raw.fillna(train_median)

    df_train = df.iloc[:train_end]
    X_train_base, y_train = X.iloc[:train_end], y[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y[val_end:]

    if len(df_train) < 4 or len(X_test) == 0:
        return {"status": "insufficient_data", "n_train": len(df_train), "n_test": len(X_test)}

    # ---- Arm A: baseline (ml.py's existing scheme, reproduced exactly) ----
    weights_baseline = compute_sample_weight("balanced", y_train)
    model_baseline = _fit_xgb(X_train_base, y_train, weights_baseline, n_classes)
    acc_baseline = float(model_baseline.score(X_test, y_test))

    # ---- Arm B: average-uniqueness weighting (no resampling) ----
    uniq = average_uniqueness_per_pair(df_train).values
    weights_uniqueness = compute_sample_weight("balanced", y_train) * uniq
    model_uniqueness = _fit_xgb(X_train_base, y_train, weights_uniqueness, n_classes)
    acc_uniqueness = float(model_uniqueness.score(X_test, y_test))

    # ---- Arm C: sequential bootstrap (resample train rows, then weight) ----
    # boot_idx are positions into df_train (0..len(df_train)-1): df was
    # reset_index(drop=True) above, so df_train's own index already equals
    # its row position, and sequential_bootstrap_indices returns exactly
    # those index values -- safe to use directly against X_train_base/
    # y_train, which share that same 0-based positional index.
    boot_idx = sequential_bootstrap_indices(df_train, random_state=42)
    X_train_boot = X_train_base.loc[boot_idx].reset_index(drop=True)
    y_train_boot = y_train[boot_idx]
    weights_boot = compute_sample_weight("balanced", y_train_boot)
    model_boot = _fit_xgb(X_train_boot, y_train_boot, weights_boot, n_classes)
    acc_boot = float(model_boot.score(X_test, y_test))

    return {
        "status": "ok",
        "n_train": len(df_train), "n_val": len(X_val), "n_test": len(X_test),
        "n_classes": n_classes,
        "avg_uniqueness_mean": float(uniq.mean()), "avg_uniqueness_min": float(uniq.min()),
        "effective_n_train": float(uniq.sum()),
        "test_acc_baseline": acc_baseline,
        "test_acc_uniqueness_weighted": acc_uniqueness,
        "test_acc_sequential_bootstrap": acc_boot,
    }


def main():
    import argparse
    p = argparse.ArgumentParser(description="Sequential-bootstrap / average-uniqueness comparison arm to ml.py")
    p.add_argument("--pit-safe", action="store_true",
                    help="Same as ml.py's own --pit-safe: source pairs from the wider PIT-safe "
                         "episodic screen instead of the standard full-history one.")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s  %(levelname)-8s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(_LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)

    log.info("=== sequential_bootstrap_ml_comparison.py: AFML Ch.4 average-uniqueness / "
             "sequential-bootstrap comparison arm vs. ml.py's baseline sample weighting ===")
    result = ml.build(pit_safe=args.pit_safe)
    if result.examples.empty:
        log.warning("ml.build() produced zero labeled examples -- nothing to compare.")
        return
    log.info(f"{len(result.examples)} labeled examples across {len(result.pairs_used)} pairs")

    stats = run_comparison(result)
    log.info(f"Result: {stats}")

    os.makedirs(_OUT_DIR, exist_ok=True)
    pd.DataFrame([stats]).to_parquet(
        os.path.join(_OUT_DIR, "sequential_bootstrap_ml_comparison.parquet"))
    log.info(f"Saved to output/research/sequential_bootstrap_ml_comparison.parquet")


if __name__ == "__main__":
    main()
