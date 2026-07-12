# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# ml.py — Multiclass meta-labeler on spread resolution outcomes
# github.com/rossw811/CAMARF
#
# Lopez de Prado meta-labeling architecture: the cointegration z-score
# threshold (Config.ANALYSIS.OU_ZSCORE_ENTRY) is the PRIMARY signal; this
# module predicts P(the primary signal is correct) — i.e. given an entry
# event, what's the probability distribution over how the spread actually
# resolves (DEVELOPMENT.md ml.py section).
#
# Same role as macro.py: this module consumes analysis.py's persisted
# output (spread_series_*.parquet, pairs.parquet — added 2026-06-21
# specifically so this module would have real per-bar history to train
# on) and produces a model + diagnostics. It never fetches or re-runs
# analysis.
#
# STAGE 1 of the staged-build discipline discussed and locked in
# DEVELOPMENT.md (2026-06-21): core spread-level features only, validated
# on their own BEFORE macro context / asset characteristics / archetype
# clustering get added in later stages. Per-bar regime labels and macro
# context are deliberately NOT joined in here yet — see DEVELOPMENT.md.
# =============================================================================

from __future__ import annotations

import glob
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.ml")

_RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "results")


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class EntryEvent:
    """One labeled training example: an entry signal + its forward outcome."""

    symbol_a: str
    symbol_b: str
    tf_label: str
    entry_time: pd.Timestamp
    horizon_bars: int
    z_entry: float
    z_future: float
    label: str
    # Features (Stage 1 core set — see module docstring)
    zscore: float
    zscore_velocity: float
    half_life_current: float
    hurst_exponent: Optional[float]
    coint_fraction_rolling: float
    half_life_trend_slope: float
    mean_reversion_speed: float
    hedge_ratio_drift: float


@dataclass
class MLResult:
    examples: pd.DataFrame  # one row per EntryEvent
    pairs_used: List[Tuple[str, str, str]]  # (symbol_a, symbol_b, tf_label)
    pairs_skipped: List[Tuple[str, str, str, str]]  # + reason
    model: Optional[Any] = None
    holdout_report: Optional[Dict[str, Any]] = None
    feature_importance: Optional[Dict[str, float]] = None
    conformal: Optional["ConformalPredictor"] = None


# =============================================================================
# LABEL CONSTRUCTION — pure functions (mirrors macro.py's _classify_*
# convention: stateless transforms as plain functions, not class methods)
# =============================================================================


def _classify_outcome(z_entry: float, z_future: float) -> str:
    """
    Priority-ordered 4-class label at horizon N = RESOLUTION_BARS_MULT *
    half_life bars ahead of entry. Resolves an ambiguity in the original
    spec (DEVELOPMENT.md's ml.py table defines strong/weak_converge by
    ABSOLUTE z-score bands but diverge_further by a RELATIVE-to-entry
    condition, leaving a gap between |z_future|<=1.5 and "wider than
    entry" unaddressed for e.g. z_entry=2.0, z_future=1.7). Resolution
    (documented here, not silently assumed): no_move fills that gap —
    "improved some, but not enough to count as weak_converge" — rather
    than leaving it unclassifiable.
    """
    c = Config.ML
    az_future = abs(z_future)
    if az_future <= c.RESOLUTION_THRESHOLD:
        return "strong_converge"
    if az_future <= 1.0:
        return "weak_converge"
    if az_future < abs(z_entry):
        return "no_move"
    return "diverge_further"


def _find_entry_events(
    z_rolling: pd.Series, entry_threshold: float, clean_mask: pd.Series
) -> pd.DatetimeIndex:
    """
    Entry event: bar where |z_rolling| crosses entry_threshold from below,
    AND the bar is "clean" (clean_mask True — both legs GapFlag.NONE).

    This matters because analysis.py's DataAligner.align_intraday()
    reindexes onto the FULL 24/7 calendar (not just trading hours) and
    forward-fills the gaps — so the persisted spread_series_*.parquet for
    intraday TFs is mostly overnight/weekend padding (e.g. SPY/VOO at 1h:
    25,446 total rows vs. ~4,359 actual trading-hour bars). Without this
    filter, entry events would fire on forward-filled prices at 2am, which
    is meaningless. entry_threshold is caller-supplied — as of 2026-06-22
    this is Config.ML.TRAINING_ENTRY_THRESHOLD (1.5), deliberately lower
    than the live Config.ANALYSIS.OU_ZSCORE_ENTRY (2.0), so the
    meta-labeler trains on a broader range of divergence outcomes than the
    live signal trades on. This docstring previously claimed it reused
    OU_ZSCORE_ENTRY directly — stale as of that change, corrected here.
    """
    az = z_rolling.abs()
    crossed = (az.shift(1) < entry_threshold) & (az >= entry_threshold)
    crossed = crossed & clean_mask
    return z_rolling.index[crossed.fillna(False)]


# =============================================================================
# TRAINING EXAMPLE CONSTRUCTION
# =============================================================================


def _discover_confirmed_pairs() -> List[Tuple[str, str, str]]:
    """
    (symbol_a, symbol_b, tf_label) for every pair with a persisted
    spread_series_*.parquet — i.e. every confirmed pair analysis.py has
    already enriched, across all timeframes, not just one.
    """
    out = []
    for pairs_path in glob.glob(os.path.join(_RESULTS_DIR, "*", "pairs.parquet")):
        tf_dir = os.path.basename(os.path.dirname(pairs_path))
        if "_stale_" in tf_dir:
            continue
        try:
            df = pd.read_parquet(pairs_path)
        except Exception:
            continue
        for _, row in df.iterrows():
            series_path = os.path.join(
                os.path.dirname(pairs_path),
                f"spread_series_{row['symbol_a']}_{row['symbol_b']}.parquet",
            )
            if os.path.exists(series_path):
                out.append((row["symbol_a"], row["symbol_b"], row["tf_label"]))
    return out


def _build_examples_for_pair(
    symbol_a: str, symbol_b: str, tf_label: str, pair_row: pd.Series, summary: "MLRunSummary",
    series: Optional[pd.DataFrame] = None, feature_lag: int = 0,
) -> List[EntryEvent]:
    """
    feature_lag: bars to shift the FEATURE snapshot (zscore/half_life_current/
    zscore_velocity — the _FEATURE_COLS actually fed to the model) back from
    the true entry bar. Default 0 preserves exact original behavior for every
    real caller. Entry-event detection, the label's z_entry (via
    _classify_outcome), and the outcome horizon all stay anchored to the TRUE
    entry bar regardless of feature_lag — only what the MODEL sees at
    "decision time" gets staled. Used by
    research/ml_lookahead_selftest.py's mechanical lookahead self-test; not
    used by ml.py's own production build().
    """
    if series is None:
        series_path = os.path.join(
            _RESULTS_DIR, _tf_dirname(tf_label), f"spread_series_{symbol_a}_{symbol_b}.parquet"
        )
        series = pd.read_parquet(series_path)
    # Deliberately the training-only threshold, not the live OU_ZSCORE_ENTRY
    # (2.0) — see Config.ML.TRAINING_ENTRY_THRESHOLD's comment.
    entry_threshold = Config.ML.TRAINING_ENTRY_THRESHOLD

    # Clean bars only — both legs GapFlag.NONE. See _find_entry_events'
    # docstring: intraday spread_series files are mostly overnight/weekend
    # padding from align_intraday()'s 24/7 reindex; gap_flag_a/b may be
    # entirely absent (the deep-history enrichment path doesn't carry it —
    # documented limitation) in which case every bar is treated as clean
    # (deep-history series are already real, non-padded IBKR/yfinance bars
    # at their native intraday frequency, not reindexed onto a 24/7
    # calendar, so this is correct, not a fallback of convenience).
    if "gap_flag_a" in series.columns and series["gap_flag_a"].notna().any():
        from data import GapFlag

        clean_mask = (series["gap_flag_a"] == GapFlag.NONE) & (
            series["gap_flag_b"] == GapFlag.NONE
        )
    else:
        clean_mask = pd.Series(True, index=series.index)

    entries = _find_entry_events(series["z_rolling"], entry_threshold, clean_mask)

    half_life_fallback = pair_row.get("half_life_rolling", np.nan)
    hedge_drift = np.nan
    ols = pair_row.get("hedge_ratio_ols", np.nan)
    kal = pair_row.get("hedge_ratio_kalman_mean", np.nan)
    if np.isfinite(ols) and ols != 0 and np.isfinite(kal):
        hedge_drift = abs(ols - kal) / abs(ols)

    events: List[EntryEvent] = []
    n_censored = 0
    n_no_half_life = 0
    n_future_not_clean = 0
    for t in entries:
        pos = series.index.get_loc(t)
        feat_pos = max(0, pos - feature_lag)  # == pos when feature_lag=0 (all real callers)
        z_entry = float(series["z_rolling"].iloc[pos])  # true entry z -- drives the label, never staled
        hl = series["half_life_rolling"].iloc[pos]
        if not np.isfinite(hl) or hl <= 0:
            hl = half_life_fallback
        if not np.isfinite(hl) or hl <= 0:
            n_no_half_life += 1
            continue  # no usable half-life anywhere — can't set a horizon
        horizon = max(1, int(round(Config.ML.RESOLUTION_BARS_MULT * hl)))
        future_pos = pos + horizon
        if future_pos >= len(series):
            n_censored += 1
            continue  # not enough forward data yet to know the outcome
        if not bool(clean_mask.iloc[future_pos]):
            n_future_not_clean += 1
            continue  # outcome bar is padding/gap-filled — not a real observed price
        z_future = float(series["z_rolling"].iloc[future_pos])
        if not np.isfinite(z_future):
            continue

        # FEATURE snapshot (what the model actually trains on) -- sourced from
        # feat_pos, which is staled by feature_lag bars relative to the true
        # entry bar. hl_feat falls back to the (unstaled) horizon-defining hl
        # if the staled bar itself has no usable half-life, so the horizon
        # computed above never changes with feature_lag.
        z_feat = float(series["z_rolling"].iloc[feat_pos])
        hl_feat = series["half_life_rolling"].iloc[feat_pos]
        if not np.isfinite(hl_feat) or hl_feat <= 0:
            hl_feat = hl
        zvel = float(
            series["z_rolling"].iloc[feat_pos] - series["z_rolling"].iloc[max(0, feat_pos - 5)]
        )
        events.append(
            EntryEvent(
                symbol_a=symbol_a,
                symbol_b=symbol_b,
                tf_label=tf_label,
                entry_time=t,
                horizon_bars=horizon,
                z_entry=z_entry,
                z_future=z_future,
                label=_classify_outcome(z_entry, z_future),
                zscore=z_feat,
                zscore_velocity=zvel,
                half_life_current=float(hl_feat),
                hurst_exponent=(
                    float(pair_row["hurst_rs"])
                    if np.isfinite(pair_row.get("hurst_rs", np.nan))
                    else None
                ),
                coint_fraction_rolling=float(pair_row.get("coint_fraction_rolling", np.nan)),
                half_life_trend_slope=float(pair_row.get("half_life_trend_slope", np.nan)),
                mean_reversion_speed=float(pair_row.get("mean_reversion_speed", np.nan)),
                hedge_ratio_drift=float(hedge_drift),
            )
        )
    perm_robust = pair_row.get("permutation_robust", None)
    if perm_robust is not None:
        perm_robust = bool(perm_robust)
    summary.record_pair(
        f"{symbol_a}/{symbol_b}@{tf_label}",
        entry_events=len(entries),
        labeled=len(events),
        censored=n_censored,
        no_half_life=n_no_half_life,
        future_not_clean=n_future_not_clean,
        permutation_robust=perm_robust,
    )
    return events


# Mirrors DataStore._TF_SAFE (data.py) — duplicated rather than imported so
# ml.py never pulls in data.py's yfinance/IBKR import chain. ml.py is a pure
# read-only consumer of analysis.py's persisted output; it must never fetch.
_TF_SAFE = {
    "1m": "1min",
    "2m": "2min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1hr",
    "4h": "4hr",
    "1D": "1day",
    "7D": "7day",
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
}


def _tf_dirname(tf_label: str) -> str:
    """pairs.parquet's tf_label ('3m') -> the actual results dir name ('3min')."""
    return _TF_SAFE.get(tf_label, tf_label.lower())


# =============================================================================
# CLASS 1 — MLRunSummary
# =============================================================================


class MLRunSummary:
    """Same role as macro.py's MacroRunSummary — written to latest_run_ml.log."""

    _LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_run_ml.log")

    def __init__(self):
        self.start_time = time.time()
        self.pairs: Dict[str, Dict] = {}
        self.label_distribution: Dict[str, int] = {}  # what's actually trained on
        self.granular_label_distribution: Dict[str, int] = {}  # always the full 4-class breakdown
        self.notes: List[str] = []
        self.pairs_skipped: List[Tuple[str, str, str, str]] = []

    def record_pair(self, pair_key: str, **kwargs) -> None:
        self.pairs.setdefault(pair_key, {}).update(kwargs)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def write(self) -> None:
        elapsed = (time.time() - self.start_time) / 60
        lines = [
            "=== CAMARF ml.py ===",
            f"date:        {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            f"runtime_min: {elapsed:.1f}",
            "",
            "=== pairs ===",
        ]
        if self.pairs:
            for pk, s in self.pairs.items():
                perm = s.get("permutation_robust", None)
                perm_str = "" if perm is None else f" perm_robust={perm}"
                lines.append(
                    f"  {pk:<24} entry_events={s.get('entry_events','?'):<5} "
                    f"labeled={s.get('labeled','?'):<5} censored={s.get('censored','?'):<5} "
                    f"no_half_life={s.get('no_half_life','?'):<5} "
                    f"future_not_clean={s.get('future_not_clean','?')}{perm_str}"
                )
        else:
            lines.append("  (none)")

        if self.label_distribution:
            lines += ["", f"=== label_distribution (label_scheme={Config.ML.LABEL_SCHEME}, this is what training/the MIN_CLASS_SAMPLES gate sees) ==="]
            for label, n in self.label_distribution.items():
                lines.append(f"  {label}: {n}")

        if self.granular_label_distribution:
            lines += ["", "=== granular_label_distribution (always the full 4-class outcome, regardless of label_scheme) ==="]
            for label, n in self.granular_label_distribution.items():
                lines.append(f"  {label}: {n}")

        if self.notes:
            lines += ["", "=== notes ==="]
            for n in self.notes:
                lines.append(f"  {n}")

        if self.pairs_skipped:
            lines += ["", "=== pairs_skipped ==="]
            for symbol_a, symbol_b, tf_label, reason in self.pairs_skipped:
                lines.append(f"  {symbol_a}/{symbol_b}@{tf_label}: {reason}")

        lines += ["", "=== end ==="]
        try:
            with open(self._LOG_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            log.info(f"Run summary → {self._LOG_PATH}")
        except Exception as e:
            log.debug(f"MLRunSummary write failed: {e}")


# =============================================================================
# ENTRY POINT
# =============================================================================


def build(min_class_samples: Optional[int] = None) -> MLResult:
    """
    Discover all confirmed pairs with persisted spread series, build
    labeled entry-event examples, and train a meta-labeler if there's
    enough data (Config.ML.MIN_CLASS_SAMPLES per class — honestly reports
    "insufficient data" rather than training on too little to trust, per
    this project's no-bandaid-fixes / verify-everything discipline).
    """
    summary = MLRunSummary()
    pairs = _discover_confirmed_pairs()

    all_events: List[EntryEvent] = []
    pairs_used: List[Tuple[str, str, str]] = []
    pairs_skipped: List[Tuple[str, str, str, str]] = []

    for symbol_a, symbol_b, tf_label in pairs:
        try:
            pairs_df = pd.read_parquet(
                os.path.join(_RESULTS_DIR, _tf_dirname(tf_label), "pairs.parquet")
            )
            row = pairs_df[
                (pairs_df["symbol_a"] == symbol_a) & (pairs_df["symbol_b"] == symbol_b)
            ].iloc[0]
        except Exception as e:
            pairs_skipped.append((symbol_a, symbol_b, tf_label, f"pairs.parquet lookup failed: {e}"))
            continue
        # Skip BUG-D49 degenerate pairs: one/both legs have implausibly few
        # distinct close prices despite adequate dollar volume. Training on
        # these would teach the model to exploit pricing artifacts, not real
        # co-movement — they stay in pairs.parquet for the backtest
        # comparison arm but are excluded from ML training.
        if bool(row.get("thin_info_content", False)):
            pairs_skipped.append((symbol_a, symbol_b, tf_label, "thin_info_content: BUG-D49 price degeneracy — excluded from ML training"))
            summary.pairs_skipped = pairs_skipped
            continue

        try:
            events = _build_examples_for_pair(symbol_a, symbol_b, tf_label, row, summary)
        except Exception as e:
            pairs_skipped.append((symbol_a, symbol_b, tf_label, f"{type(e).__name__}: {e}"))
            continue
        if events:
            pairs_used.append((symbol_a, symbol_b, tf_label))
            all_events.extend(events)
        else:
            pairs_skipped.append((symbol_a, symbol_b, tf_label, "zero labeled entry events"))
    summary.pairs_skipped = pairs_skipped

    examples_df = pd.DataFrame([vars(e) for e in all_events])
    if not examples_df.empty:
        # label stays the granular 4-class outcome on every record regardless
        # of training scheme — nothing is lost by collapsing for training.
        if Config.ML.LABEL_SCHEME == "binary":
            examples_df["label_for_training"] = examples_df["label"].map(
                Config.ML.BINARY_LABEL_MAP
            )
        else:
            examples_df["label_for_training"] = examples_df["label"]
        for label, n in examples_df["label"].value_counts().items():
            summary.granular_label_distribution[label] = int(n)
        for label, n in examples_df["label_for_training"].value_counts().items():
            summary.label_distribution[label] = int(n)

    log.info(
        f"  Discovered {len(pairs)} confirmed pairs with persisted spread series; "
        f"{len(pairs_used)} produced labeled examples, {len(pairs_skipped)} skipped"
    )
    log.info(f"  Total labeled entry events: {len(examples_df)}")

    result = MLResult(examples=examples_df, pairs_used=pairs_used, pairs_skipped=pairs_skipped)

    min_per_class = (
        min_class_samples if min_class_samples is not None else Config.ML.MIN_CLASS_SAMPLES
    )  # `or` previously ate an explicit 0 (e.g. --min-class-samples 0 to force a smoke-test run)
    n_classes_present = (
        examples_df["label_for_training"].nunique() if not examples_df.empty else 0
    )
    min_class_count = (
        examples_df["label_for_training"].value_counts().min()
        if not examples_df.empty
        else 0
    )

    if examples_df.empty or n_classes_present < 2 or min_class_count < min_per_class:
        msg = (
            f"Insufficient data to train: {len(examples_df)} total examples across "
            f"{n_classes_present} classes (label_scheme={Config.ML.LABEL_SCHEME}, "
            f"min class count={min_class_count}, "
            f"need >={min_per_class}/class per Config.ML.MIN_CLASS_SAMPLES). "
            f"This is the expected, honest result tonight — most confirmed pairs "
            f"are on intraday TFs whose history just started accumulating "
            f"(see DEVELOPMENT.md's data.py append-switch, 2026-06-21). Re-run "
            f"as more history accumulates."
        )
        log.warning(f"  {msg}")
        summary.note(msg)
        summary.write()
        return result

    _train_and_validate(result, summary)
    summary.write()
    return result


_FEATURE_COLS = [
    "zscore",
    "zscore_velocity",
    "half_life_current",
    "hurst_exponent",
    "coint_fraction_rolling",
    "half_life_trend_slope",
    "mean_reversion_speed",
    "hedge_ratio_drift",
]


class ConformalPredictor:
    """
    Split conformal prediction wrapper around the meta-labeler's
    XGBClassifier (Development.md Session 10 academic backlog, idea #9).

    The XGBoost probability output is a point estimate with no calibrated
    notion of uncertainty — at this project's current sample size (12-32
    labeled examples), that's a real liability, not a detail. Split
    conformal prediction is distribution-free (no assumption on the
    underlying probability model, only exchangeability of the calibration
    and test data) and gives a marginal coverage GUARANTEE: P(true label
    in the returned set) >= 1 - alpha, for ANY model, ANY sample size,
    given the exchangeability assumption holds. That guarantee is the
    honest tool for a small-N classifier — it doesn't make the model more
    accurate, it makes its stated uncertainty trustworthy. Caveat this
    project must keep in view: exchangeability is exactly the assumption
    time series structurally tends to violate (regime shifts, serial
    correlation in the underlying spread). Framed as an exploratory
    calibration overlay, not a load-bearing guarantee on real trading
    decisions, until that caveat is investigated further.

    Calibration data source: the existing chronological train/val/test
    split (Config.ML.TRAIN_PCT / VAL_PCT) already carves out a validation
    slice between train and test, but nothing previously consumed it —
    found while building this feature. That slice is exactly a calibration
    set in conformal-prediction terms; using it gives this orphaned data
    real purpose instead of leaving it allocated but unused.
    """

    def __init__(self, model: Any, classes: np.ndarray):
        self.model = model
        self.classes = classes  # predict_proba column order
        self.calibration_scores: Optional[np.ndarray] = None

    def calibrate(self, X_cal: pd.DataFrame, y_cal: np.ndarray) -> None:
        """y_cal: integer-encoded labels matching self.classes' index order."""
        probs = self.model.predict_proba(X_cal)
        true_class_probs = probs[np.arange(len(y_cal)), y_cal]
        # Nonconformity score: how surprising the true label's predicted
        # probability was. Higher = more surprising = less conforming.
        self.calibration_scores = 1.0 - true_class_probs

    def predict_sets(self, X: pd.DataFrame, alpha: float = 0.1) -> List[List[Any]]:
        """
        Returns one prediction SET per row — a list of class labels whose
        nonconformity score clears the calibrated (1-alpha) threshold. A
        set can contain 0 (model is confident and confidently wrong on
        calibration data — rare), 1, or all classes (model is uncertain).
        Finite-sample-corrected quantile per Lei et al. (2018).
        """
        if self.calibration_scores is None:
            raise RuntimeError("calibrate() must be called before predict_sets()")
        n_cal = len(self.calibration_scores)
        q_level = min(1.0, np.ceil((n_cal + 1) * (1 - alpha)) / n_cal)
        threshold = np.quantile(self.calibration_scores, q_level, method="higher")
        probs = self.model.predict_proba(X)
        nonconformity = 1.0 - probs
        return [
            [self.classes[i] for i in range(len(row)) if row[i] <= threshold]
            for row in nonconformity
        ]


def _train_and_validate(result: MLResult, summary: MLRunSummary) -> None:
    """
    Chronological holdout (not full CPCV — that needs more data than a
    first run is likely to have; CPCV is the documented future upgrade
    once more history accumulates, per DEVELOPMENT.md's overfitting
    discipline). XGBoost primary model. Feature importance via sklearn's
    permutation_importance (MDA-style) rather than SHAP — shap is
    installed but currently broken in this environment (numba doesn't yet
    support the installed numpy 2.4; see requirements.txt's documented
    KNOWN ISSUE) — not silently worked around.
    """
    import xgboost as xgb
    from sklearn.inspection import permutation_importance
    from sklearn.preprocessing import LabelEncoder
    from sklearn.utils.class_weight import compute_sample_weight

    df = result.examples.sort_values("entry_time").reset_index(drop=True)
    X = df[_FEATURE_COLS].fillna(df[_FEATURE_COLS].median())
    le = LabelEncoder()
    y = le.fit_transform(df["label_for_training"])

    n = len(df)
    train_end = int(n * Config.ML.TRAIN_PCT)
    val_end = train_end + int(n * Config.ML.VAL_PCT)
    X_train, y_train = X.iloc[:train_end], y[:train_end]
    X_val, y_val = X.iloc[train_end:val_end], y[train_end:val_end]
    X_test, y_test = X.iloc[val_end:], y[val_end:]

    if len(X_train) == 0 or len(X_test) == 0:
        summary.note("Chronological split left an empty train or test fold — skipping training.")
        return

    # objective/eval_metric must be derived from the actual class count, not
    # hardcoded — Config.ML.LABEL_SCHEME="binary" means y can have 2 classes,
    # and XGBoost's mlogloss is invalid for a binary objective (would crash
    # at fit() the first time enough data exists to reach this code at all —
    # caught overnight 2026-06-23 before it could fire silently in practice).
    n_classes = len(le.classes_)
    if n_classes <= 2:
        objective, eval_metric = "binary:logistic", "logloss"
    else:
        objective, eval_metric = "multi:softprob", "mlogloss"

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        objective=objective,
        eval_metric=eval_metric,
        random_state=42,  # matches the project's seed convention (KMeans/GMM/HMM all use 42)
        n_jobs=1,  # avoids thread-scheduling float non-determinism; free at this data size
    )
    train_weights = compute_sample_weight("balanced", y_train)
    model.fit(X_train, y_train, sample_weight=train_weights)

    test_acc = float(model.score(X_test, y_test))
    perm = permutation_importance(model, X_test, y_test, n_repeats=20, random_state=0)
    importance = dict(zip(_FEATURE_COLS, perm.importances_mean.tolist()))

    result.model = model
    result.holdout_report = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "test_accuracy": test_acc,
        "classes": list(le.classes_),
    }
    result.feature_importance = importance
    log.info(
        f"  Trained on {len(X_train)} examples, holdout accuracy on "
        f"{len(X_test)} examples: {test_acc:.2%}"
    )
    summary.note(
        f"Trained: n_train={len(X_train)} n_test={len(X_test)} "
        f"test_accuracy={test_acc:.2%}"
    )

    # Conformal calibration uses the val slice (train_end:val_end) that the
    # chronological split already carves out but nothing previously
    # consumed — see ConformalPredictor's docstring.
    if len(X_val) > 0:
        conformal = ConformalPredictor(model, le.inverse_transform(model.classes_))
        conformal.calibrate(X_val, y_val)
        pred_sets = conformal.predict_sets(X_test, alpha=0.1)
        avg_set_size = float(np.mean([len(s) for s in pred_sets]))
        y_test_labels = le.inverse_transform(y_test)
        empirical_coverage = float(
            np.mean([y_test_labels[i] in pred_sets[i] for i in range(len(pred_sets))])
        )
        result.conformal = conformal
        result.holdout_report["conformal"] = {
            "n_calibration": len(X_val),
            "alpha": 0.1,
            "avg_prediction_set_size": avg_set_size,
            "empirical_coverage_on_test": empirical_coverage,
            "n_classes": n_classes,
        }
        log.info(
            f"  Conformal (n_cal={len(X_val)}, alpha=0.1): avg set size "
            f"{avg_set_size:.2f}/{n_classes} classes, empirical coverage on "
            f"test {empirical_coverage:.2%} (target >=90%)"
        )
        summary.note(
            f"Conformal: n_cal={len(X_val)} avg_set_size={avg_set_size:.2f} "
            f"empirical_coverage={empirical_coverage:.2%}"
        )
    else:
        summary.note(
            "Conformal calibration skipped — empty validation slice "
            "(Config.ML.VAL_PCT too small relative to current sample size)."
        )

    # Persist model for Layer 2 backtest gate (MLConditioner._load expects this path)
    import pickle
    _pkl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "ml", "model_stage1.pkl")
    os.makedirs(os.path.dirname(_pkl_path), exist_ok=True)
    with open(_pkl_path, "wb") as _f:
        pickle.dump({
            "model": model,
            "label_encoder": le,
            "feature_names": _FEATURE_COLS,
            "classes": list(le.classes_),
        }, _f)
    log.info("  Model saved → %s", _pkl_path)
    summary.note(f"Model persisted → {_pkl_path}")


def main(min_class_samples: Optional[int] = None) -> MLResult:
    """Entry point — build labeled examples and train the meta-labeler if viable."""
    log.info("=" * 70)
    log.info("CAMARF  —  ml.py  —  Spread Resolution Meta-Labeler")
    log.info("=" * 70)
    result = build(min_class_samples=min_class_samples)
    log.info("=" * 70)
    return result


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="CAMARF ml.py meta-labeler")
    p.add_argument(
        "--min-class-samples",
        type=int,
        default=None,
        help="Override Config.ML.MIN_CLASS_SAMPLES for this run",
    )
    args = p.parse_args()
    main(min_class_samples=args.min_class_samples)
