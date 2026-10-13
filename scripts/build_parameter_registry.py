"""
scripts/build_parameter_registry.py -- every tunable numeric value in the code, in one registry with WHY it has that
value (Ross 2026-10-12: "we shouldn't have any arbitrary values and we need to show why they were chosen, then we
need to account for the overfitting").

Scans (AST, no import side effects):
  config.py               -- every numeric class attribute of the Config sections (e.g. BACKTEST.ENTRY_ZSCORE)
  core + research modules -- every module-level UPPERCASE numeric constant (e.g. EPISODIC_WINDOW_BARS)
and merges with docs/PARAMETER_REGISTRY.csv, keeping the hand-written columns:
  category        definition | convention | data_constraint | calibrated | preregistered | engineering | unjustified
                  definition      -- follows from a definition/unit (252 trading days, 1e-12 tolerance)
                  convention      -- standard practice, with a citation (alpha 0.05, BH, Newey-West lag rule)
                  data_constraint -- forced by the data (Yahoo's 8-day 1m limit, CRSP coverage)
                  calibrated      -- set from an empirical test; evidence names the script/output
                  preregistered   -- fixed in a pre-registration before results (doc + commit)
                  engineering     -- performance/memory/IO only; must not change any result (evidence says why)
                  unjustified     -- no recorded reason yet (the backlog)
  justification   one or two sentences
  evidence        file:line / script / doc / commit
  outcome_informed  yes | no | unknown -- was the value chosen or changed AFTER seeing a result it affects?
                  (yes/unknown feed the overfitting account: docs/PARAMETER_REGISTRY.md)
  alternatives_tried  how many other values were tried on outcome data (blank = unknown)
Code-derived columns (value, file, line) are refreshed on every run; a row whose name disappears from the code is
kept with value "REMOVED" (never silently dropped).
Usage: python scripts/build_parameter_registry.py
Test:  debug/_verify_parameter_registry.py
"""
import ast
import glob
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "PARAMETER_REGISTRY.csv")
CORE = ["analysis.py", "backtest.py", "ml.py", "stats.py", "pit_wfa.py", "portfolio_sim.py", "portfolio_math.py",
        "data.py", "data_wrds.py", "macro.py", "universe_loader.py", "pnl_dollar.py", "dollar_volume.py",
        "period_bars.py", "sensitivity.py", "deflated_sharpe.py"]
HAND = ["category", "justification", "evidence", "outcome_informed", "alternatives_tried"]
CATEGORIES = {"definition", "convention", "data_constraint", "calibrated", "preregistered", "engineering",
              "unjustified"}


def _num(node):
    """Numeric literal value (incl. unary minus and simple arithmetic of literals), else None."""
    try:
        v = ast.literal_eval(node)
    except Exception:
        try:
            v = eval(compile(ast.Expression(node), "<c>", "eval"), {"__builtins__": {}}, {})
        except Exception:
            return None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _assigned(st):
    """(name, value-node) pairs for simple and tuple assignments ("A, B = 0.9, 1e-3"; 2026-10-12: tuple assignments
    were missed). Unpacked values that are not a literal tuple of the same length are skipped."""
    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
        return [(st.target.id, st.value)]
    if not isinstance(st, ast.Assign) or len(st.targets) != 1:
        return []
    t, v = st.targets[0], st.value
    if isinstance(t, ast.Name):
        return [(t.id, v)]
    if isinstance(t, (ast.Tuple, ast.List)) and isinstance(v, (ast.Tuple, ast.List)) and len(t.elts) == len(v.elts):
        return [(e.id, x) for e, x in zip(t.elts, v.elts) if isinstance(e, ast.Name)]
    return []


def scan_config(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    rows = []
    for top in tree.body:
        if isinstance(top, ast.ClassDef):
            for cls in [top] + [n for n in top.body if isinstance(n, ast.ClassDef)]:
                for st in cls.body:
                    for nm, node in _assigned(st):
                        v = _num(node) if nm.isupper() else None
                        if v is not None:
                            rows.append({"name": f"{cls.name}.{nm}", "file": "config.py", "line": st.lineno,
                                         "value": repr(v)})
    return rows


def scan_module(path):
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    tree = ast.parse(open(path, encoding="utf-8").read())
    rows = []
    for st in tree.body:
        for nm, node in _assigned(st):
            v = _num(node) if nm.isupper() else None
            if v is not None:
                rows.append({"name": f"{rel}:{nm}", "file": rel, "line": st.lineno, "value": repr(v)})
    return rows


def scan_all():
    rows = scan_config(os.path.join(ROOT, "config.py"))
    for f in CORE + sorted(glob.glob(os.path.join(ROOT, "research", "*.py"))):
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        if os.path.exists(p):
            rows += scan_module(p)
    return pd.DataFrame(rows, columns=["name", "file", "line", "value"])


def merge(code: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    prev = prev.copy() if prev is not None else pd.DataFrame(columns=["name"] + HAND)
    for c in HAND:
        if c not in prev:
            prev[c] = ""
    m = code.merge(prev[["name"] + HAND], on="name", how="left")
    m["category"] = m["category"].fillna("").replace("", "unjustified")
    for c in HAND[1:]:
        m[c] = m[c].fillna("")
    gone = prev[~prev["name"].isin(code["name"])].copy()
    if len(gone):
        gone["value"] = "REMOVED"
        for c in ("file", "line"):
            if c not in gone:
                gone[c] = ""
        m = pd.concat([m, gone[m.columns]], ignore_index=True)
    return m.sort_values(["file", "name"]).reset_index(drop=True)


def main():
    prev = pd.read_csv(OUT, dtype=str).fillna("") if os.path.exists(OUT) else None
    reg = merge(scan_all(), prev)
    reg.to_csv(OUT, index=False)
    live = reg[reg["value"] != "REMOVED"]
    print(f"{len(live)} parameters ({(live.file == 'config.py').sum()} in config.py) -> {OUT}")
    print(live["category"].value_counts().to_string())


if __name__ == "__main__":
    main()
