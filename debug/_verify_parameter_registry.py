"""
Parameter registry gate (Ross 2026-10-12: no arbitrary values; show why each was chosen; account for overfitting).
docs/PARAMETER_REGISTRY.csv (scripts/build_parameter_registry.py) must describe the code exactly:
  1. every numeric Config attribute and module-level UPPERCASE numeric constant in the scanned files is registered
  2. the registered value equals the code's value (a changed value must be re-justified, not silently drift)
  3. category is one of the allowed set; every non-"unjustified" row has a justification AND evidence
  4. outcome_informed is yes / no / unknown / blank; "calibrated" and "preregistered" rows say yes/no, never blank
  5. RATCHET: the number of "unjustified" rows is at most docs/PARAMETER_REGISTRY_CEILING.txt -- the backlog may
     only shrink; a new value without a reason fails the suite
Also checks the gate itself can fail (mutation): a drifted value and an unregistered name are both caught.
Run: python debug/_verify_parameter_registry.py
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {str(detail)[:300]}")


def problems(code: pd.DataFrame, reg: pd.DataFrame, cats: set) -> dict:
    live = reg[reg["value"] != "REMOVED"]
    rv = dict(zip(live["name"], live["value"].astype(str)))
    unreg = sorted(set(code["name"]) - set(rv))
    drift = sorted(n for n, v in zip(code["name"], code["value"].astype(str)) if n in rv and rv[n] != v)
    badcat = sorted(live.loc[~live["category"].isin(cats), "name"])
    j = live[live["category"] != "unjustified"]
    noreason = sorted(j.loc[(j["justification"].str.strip() == "") | (j["evidence"].str.strip() == ""), "name"])
    oi = live["outcome_informed"].fillna("")
    badoi = sorted(live.loc[~oi.isin(["yes", "no", "unknown", ""]), "name"])
    blankoi = sorted(live.loc[live["category"].isin(["calibrated", "preregistered"]) & (oi == ""), "name"])
    return {"unregistered": unreg, "drift": drift, "bad_category": badcat, "no_reason": noreason,
            "bad_outcome_informed": badoi, "calibrated_without_outcome_informed": blankoi}


def main():
    try:
        from scripts.build_parameter_registry import scan_all, CATEGORIES
    except ImportError as e:
        check("builder_exists", False, e); return finish()
    path = os.path.join(ROOT, "docs", "PARAMETER_REGISTRY.csv")
    check("registry_exists", os.path.exists(path))
    if not os.path.exists(path):
        return finish()
    reg = pd.read_csv(path, dtype=str).fillna("")
    code = scan_all()
    p = problems(code, reg, CATEGORIES)
    for k, v in p.items():
        check(k, not v, f"{len(v)}: {v[:8]}")
    n_unj = int(((reg["category"] == "unjustified") & (reg["value"] != "REMOVED")).sum())
    ceil_path = os.path.join(ROOT, "docs", "PARAMETER_REGISTRY_CEILING.txt")
    ceiling = int(open(ceil_path).read().split()[0]) if os.path.exists(ceil_path) else -1
    check("unjustified_within_ceiling", 0 <= n_unj <= ceiling, f"{n_unj} unjustified, ceiling {ceiling}")
    # mutation: the gate must catch drift and an unregistered name
    m = code.copy()
    m.loc[0, "value"] = "999999"
    m = pd.concat([m, pd.DataFrame([{"name": "config.py:NEW_MAGIC", "file": "config.py", "line": 1, "value": "7"}])])
    pm = problems(m, reg, CATEGORIES)
    # 2026-10-12: tuple assignments ("A, B = 0.9, 1e-3") must be scanned too -- the scanner missed four constants
    import tempfile
    from scripts.build_parameter_registry import scan_module
    tf = os.path.join(tempfile.mkdtemp(), "tup.py")
    open(tf, "w").write("A_ONE, B_TWO = 0.9, 1e-3\nC_THREE = 5\nlower, D_FOUR = 1, 2\n")
    names = {r["name"].split(":")[-1] for r in scan_module(tf)}
    check("tuple_assignments_scanned", names == {"A_ONE", "B_TWO", "C_THREE", "D_FOUR"}, sorted(names))
    check("mutation_caught", code.loc[0, "name"] in pm["drift"] and "config.py:NEW_MAGIC" in pm["unregistered"])
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
