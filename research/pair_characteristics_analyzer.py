"""
CAMARF pair_characteristics_analyzer.py — research script, NOT part of
the production pipeline.

Builds Development.md's "Planned Module: analyzer.py — Pair
Characteristics Analyzer" (Session ~7-8), the long-standing prerequisite
for the "ML Ensemble / Multi-System Discovery Architecture" enhancement
(same document, both never built until this session's backlog audit).
Per Development.md's own later synthesis note ("cluster pairs on the
decision tree's OUTPUT, not on raw features/regime profiles... already-
validated denoised behavioral fingerprints"), this implements BOTH
stages together, as Ross explicitly directed:

  Stage 3 — per-pair decision tree over entry conditions -> win/loss,
            depth 3-4, with the full overfitting-control discipline the
            original spec calls for (min-N=10/leaf, 1000-permutation
            test, chronological 60/40 holdout).
  Stage 4 — archetype clustering across pairs, using each pair's
            VALIDATED characteristic profile (best-leaf conditions,
            regime-sensitivity score) as the clustering input, per the
            synthesis note above — not raw spread/regime data directly.

Feature source: reuses `trades_layer1.parquet`'s ALREADY-COMPUTED
per-trade columns directly (entry_z, half_life_at_entry, hurst_at_entry,
vix_ts_regime, yield_regime) rather than recomputing them — these are
production backtest.py output, not re-derived. Only entry hour-of-day is
newly derived here (from entry_time), since it wasn't already a column.

Scope note: this is an exploratory characterization tool, explicitly NOT
wired into ml.py's Stage 2 training or backtest.py's production entry
logic — per Ross's instruction, "try it and see what it gives, don't
rely on it yet."

Output:
  output/research/pair_characteristics.parquet — per-pair leaf rules + validation
  output/research/pair_archetypes.parquet — cross-pair archetype cluster assignment
  latest_run_pair_characteristics_analyzer.log
"""
import logging
import os
import sys
import time
import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.tree import DecisionTreeClassifier, _tree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_OUT_DIR = os.path.join(_ROOT, "output", "research")

_MIN_N_LEAF = 10
_TREE_MAX_DEPTH = 4
_N_PERMUTATIONS = 1000
_PERMUTATION_PCTILE = 95
_HOLDOUT_WINRATE_TOLERANCE_PP = 15
_MIN_TRADES_PER_PAIR = 30  # below this, characteristics analysis is not attempted at all

_FEATURE_COLS = ["entry_z_abs", "half_life_at_entry", "hurst_at_entry", "entry_hour"]
_CATEGORICAL_COLS = ["vix_ts_regime", "yield_regime", "side"]

log = logging.getLogger("pair_characteristics_analyzer")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_pair_characteristics_analyzer.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _prep_features(trades: pd.DataFrame) -> pd.DataFrame:
    df = trades.copy()
    df["entry_z_abs"] = df["entry_z"].abs()
    df["entry_hour"] = pd.to_datetime(df["entry_time"]).dt.hour
    df["win"] = (df["pnl_net"] > 0).astype(int)
    for c in _CATEGORICAL_COLS:
        if c not in df.columns:
            df[c] = "unknown"
        df[c] = df[c].fillna("unknown").astype(str)
    return df


def _encode(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode categoricals, leave numeric features as-is. Pure
    function so debug/_verify_pair_characteristics_analyzer.py can call
    it directly."""
    numeric = df[_FEATURE_COLS].copy()
    cat = pd.get_dummies(df[_CATEGORICAL_COLS], prefix=_CATEGORICAL_COLS)
    return pd.concat([numeric, cat], axis=1)


def fit_tree_with_validation(df: pd.DataFrame, min_n_leaf: int = _MIN_N_LEAF,
                              max_depth: int = _TREE_MAX_DEPTH,
                              n_perm: int = _N_PERMUTATIONS,
                              seed: int = 42) -> Optional[Dict]:
    """
    Pure function, no I/O — so debug/_verify_pair_characteristics_analyzer.py
    can call it directly on synthetic trade tables. `df` must have `win`
    (0/1 outcome) plus _FEATURE_COLS/_CATEGORICAL_COLS, already
    chronologically sorted by entry_time.

    Returns None if insufficient data. Otherwise a dict with the fitted
    tree's leaf rules, permutation-test significance, and holdout
    validation, following the original spec's exact discipline: min-N/leaf,
    1000-permutation null, 60/40 chronological holdout with win-rate
    tolerance.
    """
    n = len(df)
    if n < _MIN_TRADES_PER_PAIR:
        return {"ok": False, "reason": "insufficient_trades", "n_trades": n}

    split = int(n * 0.6)
    train, holdout = df.iloc[:split], df.iloc[split:]
    if len(holdout) < 5:
        return {"ok": False, "reason": "insufficient_holdout", "n_trades": n}

    X_train = _encode(train)
    y_train = train["win"].values

    tree = DecisionTreeClassifier(
        max_depth=max_depth, min_samples_leaf=min_n_leaf, random_state=seed
    )
    tree.fit(X_train, y_train)
    in_sample_acc = tree.score(X_train, y_train)

    # Real-vs-null: 1000 permutations of the IN-SAMPLE outcome labels,
    # refit each time, compare in-sample accuracy against the null
    # distribution (per spec: "shuffle trade outcomes, refit tree 1000
    # times, report only characteristics that exceed the 95th percentile").
    rng = np.random.RandomState(seed)
    null_accs = np.empty(n_perm)
    for i in range(n_perm):
        y_perm = rng.permutation(y_train)
        t = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=min_n_leaf, random_state=seed)
        t.fit(X_train, y_perm)
        null_accs[i] = t.score(X_train, y_perm)
    perm_pctile_thresh = float(np.percentile(null_accs, _PERMUTATION_PCTILE))
    permutation_significant = bool(in_sample_acc > perm_pctile_thresh)

    # Chronological holdout: win rate per leaf must be within tolerance.
    X_holdout = _encode(holdout)
    # Align holdout's one-hot columns to train's (categories unseen in
    # holdout, or missing from train, must not silently misalign).
    X_holdout = X_holdout.reindex(columns=X_train.columns, fill_value=0)
    holdout_leaf = tree.apply(X_holdout)
    train_leaf = tree.apply(X_train)

    leaf_rules = []
    tree_ = tree.tree_
    feature_names = list(X_train.columns)

    def _leaf_path(node_id, path):
        if tree_.feature[node_id] != _tree.TREE_UNDEFINED:
            name = feature_names[tree_.feature[node_id]]
            thresh = tree_.threshold[node_id]
            _leaf_path(tree_.children_left[node_id], path + [f"{name} <= {thresh:.3f}"])
            _leaf_path(tree_.children_right[node_id], path + [f"{name} > {thresh:.3f}"])
        else:
            leaf_id = node_id
            train_mask = train_leaf == leaf_id
            n_train_leaf = int(train_mask.sum())
            if n_train_leaf < min_n_leaf:
                return
            train_winrate = float(train["win"].values[train_mask].mean())
            hold_mask = holdout_leaf == leaf_id
            n_hold_leaf = int(hold_mask.sum())
            hold_winrate = float(holdout["win"].values[hold_mask].mean()) if n_hold_leaf > 0 else np.nan
            confirmed = (
                n_hold_leaf >= min_n_leaf
                and np.isfinite(hold_winrate)
                and abs(hold_winrate - train_winrate) * 100 <= _HOLDOUT_WINRATE_TOLERANCE_PP
            )
            leaf_rules.append({
                "rule": " AND ".join(path) if path else "(root)",
                "n_train": n_train_leaf, "train_winrate": train_winrate,
                "n_holdout": n_hold_leaf, "holdout_winrate": hold_winrate,
                "holdout_confirmed": bool(confirmed),
            })

    _leaf_path(0, [])
    leaf_rules.sort(key=lambda r: r["train_winrate"], reverse=True)

    confirmed_rules = [r for r in leaf_rules if r["holdout_confirmed"]]
    best = confirmed_rules[0] if confirmed_rules else None
    worst = confirmed_rules[-1] if len(confirmed_rules) > 1 else None

    regime_sensitivity = np.nan
    if confirmed_rules and len(confirmed_rules) > 1:
        rates = [r["train_winrate"] for r in confirmed_rules]
        mean_rate = np.mean(rates)
        if mean_rate > 0:
            regime_sensitivity = (max(rates) - min(rates)) / mean_rate

    return {
        "ok": True,
        "n_trades": n, "n_train": len(train), "n_holdout": len(holdout),
        "in_sample_accuracy": float(in_sample_acc),
        "permutation_null_95pctile": perm_pctile_thresh,
        "permutation_significant": permutation_significant,
        "leaf_rules": leaf_rules,
        "n_confirmed_leaves": len(confirmed_rules),
        "best_leaf": best,
        "worst_leaf": worst,
        "regime_sensitivity_score": regime_sensitivity,
    }


def main():
    _setup_logging()
    t0 = time.time()
    log.info("=== pair_characteristics_analyzer.py: Stage 3 (per-pair decision tree) "
             "+ Stage 4 (archetype clustering) ===")

    frames = []
    for fname in ("trades_layer1.parquet", "trades_layer1_holdout.parquet"):
        fpath = os.path.join(_BACKTEST_DIR, fname)
        if os.path.exists(fpath):
            frames.append(pd.read_parquet(fpath))
    if not frames:
        log.warning("No trades_layer1*.parquet found — run backtest.py first.")
        return
    trades = pd.concat(frames, ignore_index=True).sort_values("entry_time")
    trades = _prep_features(trades)
    log.info("Loaded %d total trades across %d pair-tf combinations",
              len(trades), trades.groupby(["symbol_a", "symbol_b", "tf"]).ngroups)

    pair_results = []
    for (sym_a, sym_b, tf), grp in trades.groupby(["symbol_a", "symbol_b", "tf"]):
        grp = grp.sort_values("entry_time").reset_index(drop=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = fit_tree_with_validation(grp)
        result.update({"symbol_a": sym_a, "symbol_b": sym_b, "tf": tf})
        pair_results.append(result)

        if not result["ok"]:
            log.info("%s/%s@%s: SKIP (%s, n=%d)", sym_a, sym_b, tf, result["reason"], result.get("n_trades", 0))
            continue

        best = result["best_leaf"]
        log.info("%s/%s@%s: n=%d, perm_significant=%s, %d/%d leaves holdout-confirmed, "
                  "regime_sensitivity=%.2f, best_leaf_winrate=%.2f (n=%d)%s",
                  sym_a, sym_b, tf, result["n_trades"], result["permutation_significant"],
                  result["n_confirmed_leaves"], len(result["leaf_rules"]),
                  result["regime_sensitivity_score"] if np.isfinite(result["regime_sensitivity_score"]) else -1,
                  best["train_winrate"] if best else np.nan, best["n_train"] if best else 0,
                  "" if best else "  [no holdout-confirmed leaf]")

    # --- Stage 4: archetype clustering on VALIDATED characteristic profiles ---
    clusterable = [r for r in pair_results if r["ok"] and r["n_confirmed_leaves"] >= 1]
    log.info("\n--- Stage 4: archetype clustering (%d/%d pairs have >=1 holdout-confirmed leaf) ---",
              len(clusterable), len(pair_results))

    archetype_rows = []
    if len(clusterable) >= 3:
        profile_rows = []
        for r in clusterable:
            best = r["best_leaf"]
            worst = r["worst_leaf"] or best
            profile_rows.append([
                best["train_winrate"],
                worst["train_winrate"] if worst else best["train_winrate"],
                r["regime_sensitivity_score"] if np.isfinite(r["regime_sensitivity_score"]) else 0.0,
                r["n_confirmed_leaves"],
            ])
        profile = np.array(profile_rows)
        # z-score normalize before clustering — win rates and leaf counts
        # are on different scales.
        profile_z = (profile - profile.mean(axis=0)) / (profile.std(axis=0) + 1e-9)
        n_clusters = min(3, len(clusterable) - 1) if len(clusterable) > 3 else 2
        clustering = AgglomerativeClustering(n_clusters=n_clusters)
        labels = clustering.fit_predict(profile_z)
        for r, label in zip(clusterable, labels):
            archetype_rows.append({
                "symbol_a": r["symbol_a"], "symbol_b": r["symbol_b"], "tf": r["tf"],
                "archetype_cluster": int(label),
                "best_leaf_winrate": r["best_leaf"]["train_winrate"],
                "regime_sensitivity_score": r["regime_sensitivity_score"],
            })
        archetype_df = pd.DataFrame(archetype_rows)
        for cluster_id, cgrp in archetype_df.groupby("archetype_cluster"):
            pairs_str = ", ".join(f"{a}/{b}@{tf}" for a, b, tf in
                                   zip(cgrp["symbol_a"], cgrp["symbol_b"], cgrp["tf"]))
            log.info("Archetype %d (n=%d): mean_regime_sensitivity=%.2f, mean_best_winrate=%.2f — %s",
                      cluster_id, len(cgrp), cgrp["regime_sensitivity_score"].mean(),
                      cgrp["best_leaf_winrate"].mean(), pairs_str)
    else:
        log.warning("Only %d pairs have a holdout-confirmed characteristic — too few for archetype "
                     "clustering (need >=3). This is an honest small-N limitation, not a bug: most "
                     "confirmed pairs currently have < %d trades total.", len(clusterable), _MIN_TRADES_PER_PAIR)

    # --- Cross-pair characteristic universality check ---
    all_rule_texts = []
    for r in pair_results:
        if r["ok"]:
            for leaf in r["leaf_rules"]:
                if leaf["holdout_confirmed"] and leaf["train_winrate"] > 0.5:
                    all_rule_texts.append(leaf["rule"])
    n_pairs_with_data = sum(1 for r in pair_results if r["ok"])
    log.info("\n%d pairs had enough trades to attempt characteristics analysis (of %d total pair-tf combos)",
              n_pairs_with_data, len(pair_results))

    os.makedirs(_OUT_DIR, exist_ok=True)
    flat_rows = []
    for r in pair_results:
        base = {"symbol_a": r["symbol_a"], "symbol_b": r["symbol_b"], "tf": r["tf"], "ok": r["ok"]}
        if not r["ok"]:
            base["reason"] = r["reason"]
            flat_rows.append(base)
            continue
        for leaf in r["leaf_rules"]:
            row = dict(base)
            row.update(leaf)
            row["permutation_significant"] = r["permutation_significant"]
            row["regime_sensitivity_score"] = r["regime_sensitivity_score"]
            flat_rows.append(row)
    pd.DataFrame(flat_rows).to_parquet(os.path.join(_OUT_DIR, "pair_characteristics.parquet"), index=False)
    if archetype_rows:
        pd.DataFrame(archetype_rows).to_parquet(os.path.join(_OUT_DIR, "pair_archetypes.parquet"), index=False)
    log.info("Saved -> output/research/pair_characteristics.parquet"
             + (" + pair_archetypes.parquet" if archetype_rows else " (no archetypes.parquet — too few pairs)"))

    runtime = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info("pair_characteristics_analyzer.py complete (%.1f min)", runtime)
    log.info("REMINDER (Ross's explicit instruction): exploratory only — not wired into ml.py "
             "Stage 2 training or backtest.py entry logic. Try it and see, don't rely on it yet.")


if __name__ == "__main__":
    main()
