"""
CAMARF research/archetype_conditional_sizing.py — comparison/diagnostic
script, NOT part of the production pipeline (2026-07-14, task #45).

Connects `research/pair_characteristics_analyzer.py`'s existing
per-pair decision-tree output to a real sizing rule: does scaling
position size by the CURRENT entry's decision-tree leaf's historical
(train) win rate — using the pair's own `regime_sensitivity_score`
(max_leaf_winrate - min_leaf_winrate) / mean_leaf_winrate, already
computed there) as the signal that this is worth doing at all — improve
outcomes versus flat sizing?

Honest scope note, stated up front: `output/research/pair_characteristics.parquet`
(2026-07-11) has `regime_sensitivity_score` populated for only 2 of 61
rows (AXP/CRWD, TMHC/WAL) — the analyzer's own prior finding already
disclosed this is thin ("3 small clusters, n=6... too thin to treat as
real archetypes yet"). This script tests the sizing MECHANISM on the
only 2 pairs with real archetype data, reports honestly that this is a
2-pair test, and does not extrapolate to a general claim.

Method: parse each pair's confirmed decision-tree leaf rules (self-
generated strings like "entry_z_abs <= 3.550 AND entry_z_abs > 2.278" —
evaluated via a restricted eval() namespace containing only the known
feature columns, safe here because the rules are entirely self-generated
by pair_characteristics_analyzer.py, not external/user input). For each
simulated trade (reusing breakout_vs_reversion.py's spread/z
construction and entry convention), classify which leaf it falls into
and size proportionally to that leaf's TRAIN win rate relative to the
pair's mean train win rate across its confirmed leaves. Compare total
P&L and Sharpe-like against flat (uniform) sizing.

Usage:
    python research/archetype_conditional_sizing.py --tf 1hr
"""
import argparse
import ast
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from aligned_pair_loader import load_aligned_pair
from lead_lag_scan import _gap_masked_log_price

ENTRY_Z = 2.0
EXIT_Z = 0.0
MAX_HOLD_BARS = 100
_CHAR_PATH = "output/research/pair_characteristics.parquet"
_ALLOWED_NAMES = {"entry_z_abs", "half_life_at_entry", "side_long", "side_short", "entry_hour"}


def _safe_eval_rule(rule: str, context: dict) -> bool:
    """Evaluates a self-generated 'col <= X AND col > Y'-style rule
    string against a feature context dict. Restricted to only the known
    feature names (_ALLOWED_NAMES) and comparison operators — refuses to
    evaluate anything containing an unexpected identifier, so even
    though these strings are self-generated (not external input), this
    stays defensive rather than trusting the source unconditionally.

    Normalizes uppercase 'AND'/'OR' (pair_characteristics_analyzer.py's
    own rule-string formatting) to lowercase Python keywords before
    parsing — caught directly, not assumed: the first version parsed
    'AND' literally, which is a SyntaxError in Python (needs lowercase
    'and'), so EVERY compound rule silently failed via the caller's
    `except Exception: continue`, defaulting every trade to size_mult=1.0
    without ever actually applying archetype conditioning. Only single-
    condition rules (no AND at all) happened to parse, which is why one
    pair's result looked partially real (0.996) while the other's looked
    exactly like no conditioning had happened at all (1.000) — that
    asymmetry was itself the tell that something was silently broken."""
    normalized = rule.replace(" AND ", " and ").replace(" OR ", " or ")
    tree = ast.parse(normalized, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
            raise ValueError(f"rule references unexpected name: {node.id}")
        if isinstance(node, ast.Call):
            raise ValueError("rule contains a function call — refusing to evaluate")
    return bool(eval(compile(tree, "<rule>", "eval"), {"__builtins__": {}}, context))


def build_spread_z(symbol_a, symbol_b, tf_label, z_window=60):
    df_a, df_b = load_aligned_pair(symbol_a, symbol_b, tf_label)
    if df_a is None or df_b is None or df_a.empty or df_b.empty:
        return None
    log_a = pd.Series(_gap_masked_log_price(df_a), index=df_a.index)
    log_b = pd.Series(_gap_masked_log_price(df_b), index=df_b.index)
    common_idx = log_a.index.intersection(log_b.index)
    log_a, log_b = log_a.reindex(common_idx), log_b.reindex(common_idx)
    mask = log_a.notna() & log_b.notna()
    la, lb = log_a[mask], log_b[mask]
    if len(la) < 100:
        return None
    beta = np.dot(lb - lb.mean(), la - la.mean()) / np.dot(lb - lb.mean(), lb - lb.mean())
    alpha = la.mean() - beta * lb.mean()
    spread = la - (alpha + beta * lb)
    z = (spread - spread.rolling(z_window).mean()) / spread.rolling(z_window).std()
    return z.dropna()


def simulate_with_sizing(z: pd.Series, leaf_rules, mean_train_winrate):
    """Every entry exits via EXIT_Z, MAX_HOLD_BARS, or end-of-series —
    same completeness guarantee established in breakout_vs_reversion.py.
    size_mult=1.0 (flat) vs. leaf-conditional (train_winrate/mean)."""
    trades = []
    i, n, vals = 0, len(z), z.values
    idx = z.index
    while i < n:
        if abs(vals[i]) >= ENTRY_Z:
            direction = -1 if vals[i] > 0 else 1
            entry_val = vals[i]
            entry_hour = idx[i].hour + idx[i].minute / 60.0
            context = {
                "entry_z_abs": abs(entry_val), "half_life_at_entry": np.nan,
                "side_long": 1.0 if direction == 1 else 0.0,
                "side_short": 1.0 if direction == -1 else 0.0,
                "entry_hour": entry_hour,
            }
            size_mult = 1.0
            for rule in leaf_rules:
                try:
                    if _safe_eval_rule(rule["rule"], context):
                        size_mult = rule["train_winrate"] / mean_train_winrate if mean_train_winrate > 0 else 1.0
                        break
                except Exception:
                    continue
            j = i + 1
            while j < n and j - i < MAX_HOLD_BARS:
                if (direction == -1 and vals[j] <= EXIT_Z) or (direction == 1 and vals[j] >= -EXIT_Z):
                    break
                j += 1
            exit_val = vals[min(j, n - 1)]
            pnl_flat = direction * (exit_val - entry_val)
            trades.append({"entry_idx": i, "exit_idx": min(j, n - 1), "pnl_flat": pnl_flat,
                            "pnl_sized": pnl_flat * size_mult, "size_mult": size_mult})
            i = j + 1
        else:
            i += 1
    return trades


def run_pair(symbol_a, symbol_b, tf_label, char_df):
    rows = char_df[(char_df["symbol_a"] == symbol_a) & (char_df["symbol_b"] == symbol_b)]
    confirmed = rows[rows["holdout_confirmed"] == True]
    if confirmed.empty:
        print(f"{symbol_a}/{symbol_b}: no holdout-confirmed leaves — skipping.")
        return None
    leaf_rules = confirmed[["rule", "train_winrate"]].to_dict("records")
    mean_train_winrate = confirmed["train_winrate"].mean()
    print(f"{symbol_a}/{symbol_b}: {len(leaf_rules)} confirmed leaf rules, "
          f"mean_train_winrate={mean_train_winrate:.3f}, "
          f"regime_sensitivity_score={rows['regime_sensitivity_score'].iloc[0]:.3f}")

    z = build_spread_z(symbol_a, symbol_b, tf_label)
    if z is None:
        print(f"{symbol_a}/{symbol_b}: insufficient price data.")
        return None
    trades = simulate_with_sizing(z, leaf_rules, mean_train_winrate)
    if not trades:
        print(f"{symbol_a}/{symbol_b}: no trades generated.")
        return None

    flat_pnl = np.array([t["pnl_flat"] for t in trades])
    sized_pnl = np.array([t["pnl_sized"] for t in trades])
    flat_sharpe = flat_pnl.mean() / flat_pnl.std() if flat_pnl.std() > 1e-9 else np.nan
    sized_sharpe = sized_pnl.mean() / sized_pnl.std() if sized_pnl.std() > 1e-9 else np.nan
    print(f"  flat sizing: n={len(trades)} total_pnl={flat_pnl.sum():.2f} sharpe_like={flat_sharpe:.3f}")
    print(f"  archetype-conditional sizing: total_pnl={sized_pnl.sum():.2f} sharpe_like={sized_sharpe:.3f} "
          f"(mean size_mult={np.mean([t['size_mult'] for t in trades]):.3f})")
    return {"symbol_a": symbol_a, "symbol_b": symbol_b, "n_trades": len(trades),
            "flat_total_pnl": float(flat_pnl.sum()), "flat_sharpe": float(flat_sharpe),
            "sized_total_pnl": float(sized_pnl.sum()), "sized_sharpe": float(sized_sharpe)}


def main():
    p = argparse.ArgumentParser(description="Archetype-conditional sizing (2026-07-14)")
    p.add_argument("--tf", default="1hr")
    args = p.parse_args()

    if not os.path.exists(_CHAR_PATH):
        print(f"{_CHAR_PATH} not found.")
        return
    char_df = pd.read_parquet(_CHAR_PATH)
    pairs_with_score = char_df[char_df["regime_sensitivity_score"].notna()][["symbol_a", "symbol_b"]].drop_duplicates()
    print(f"Pairs with a real regime_sensitivity_score: {len(pairs_with_score)} "
          f"(honest scope: this is a {len(pairs_with_score)}-pair test, not a general claim)\n")

    rows = []
    for _, r in pairs_with_score.iterrows():
        result = run_pair(r["symbol_a"], r["symbol_b"], args.tf, char_df)
        if result:
            rows.append(result)

    if rows:
        df = pd.DataFrame(rows)
        out_dir = "output/research"
        os.makedirs(out_dir, exist_ok=True)
        df.to_parquet(os.path.join(out_dir, "archetype_conditional_sizing.parquet"))
        print(f"\nResults written to {out_dir}/archetype_conditional_sizing.parquet")


if __name__ == "__main__":
    main()
