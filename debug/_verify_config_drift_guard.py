"""
Config-drift guard, generalised (DEV-023; template: _verify_wfa_config_consistency.py, BUG-D71). A module-level
constant in a production or research script that reuses a Config field's NAME but hard-codes a literal is the drift
pattern that bit wfa.py (local copies silently diverging from config.py). This test scans every top-level *.py and
research/*.py (AST) and fails on any such literal, except the reviewed ones below (each a different meaning that
happens to share the name). Fixed 2026-10-05: three relative CACHE_DIR = "output/cache" (also the U1 relative-path
bug class) and a duplicated FDR_ALPHA now read Config.
Run: python debug/_verify_config_drift_guard.py
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config

# reviewed 2026-10-05: same name as a Config field, deliberately different meaning
EXCEPTIONS = {
    ("period_bars.py", "TIMEFRAMES"): "the coarse period-bar timeframes this module builds, not Config's fetch TF list",
    ("research/coint_strength_bar_system.py", "Z_WINDOW"): "Finding #49's study parameter (20), not the production z window",
    ("research/pdr_calmar_comparison.py", "SIZING_METHODS"): "the comparison's own sweep set (a superset), not Config's",
    ("research/eg_null_calibration_montecarlo.py", "TIMEFRAMES"): "the study's own {label: file suffix} map of its 3 TFs",
}


def main():
    fields = {}
    for sec in dir(Config):
        obj = getattr(Config, sec)
        if isinstance(obj, type):
            for k in dir(obj):
                if k.isupper():
                    fields.setdefault(k, sec)
    files = [p for p in glob.glob(os.path.join(ROOT, "*.py")) if os.path.basename(p) != "config.py"]
    files += glob.glob(os.path.join(ROOT, "research", "*.py"))
    bad, seen_exc = [], set()
    for f in sorted(files):
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        try:
            tree = ast.parse(open(f, encoding="utf-8").read())
        except Exception:
            continue
        for n in tree.body:
            if not (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)):
                continue
            name = n.targets[0].id
            if name not in fields:
                continue
            try:
                ast.literal_eval(n.value)               # a literal (number, string, list...) = a duplicated value
            except Exception:
                continue                               # an expression (e.g. Config.X) -- fine
            if (rel, name) in EXCEPTIONS:
                seen_exc.add((rel, name))
                continue
            bad.append(f"{rel}:{n.lineno} {name} (Config.{fields[name]}.{name})")
    stale = sorted(set(EXCEPTIONS) - seen_exc)
    print(f"[{'PASS' if not bad else 'FAIL'}] no duplicated config literals {bad}")
    print(f"[{'PASS' if not stale else 'FAIL'}] every exception still exists (no stale entries) {stale}")
    ok = not bad and not stale
    print(f"\n{2 if ok else int(not bad) + int(not stale)}/2 checks passed")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
