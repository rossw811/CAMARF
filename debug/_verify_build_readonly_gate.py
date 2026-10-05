"""
Regression test for DEV-014 (flagged twice since 2026-06; fixed 2026-10-05, plan T11): UniverseBuilder.build(fetch=False)
-- analysis.py's read-only mode (BUG-D39) -- still ran two CACHE-MUTATING maintenance steps unconditionally, before any
fetch check: _run_cache_migration() (renames/deletes files) and _clean_contaminated_cache() (deletes files it judges
wrong-frequency). That mechanism caused a real near-incident (1,500+ valid 4h files reduced to 7; Development.md).
Fix: both run only when fetch=True; read-only mode logs that they were skipped.
Check (AST of data.py -- build() loads the whole universe, too heavy for a unit test): every call to a cache-mutating
maintenance function inside build() sits under an `if fetch` guard; and the read-only skip is logged.
Run: python debug/_verify_build_readonly_gate.py
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUTATING = {"_run_cache_migration", "_clean_contaminated_cache"}

src = open(os.path.join(ROOT, "data.py"), encoding="utf-8").read()
tree = ast.parse(src)
build = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build")


def guarded_calls(node, guarded=False, out=None):
    out = [] if out is None else out
    if isinstance(node, ast.If):
        test = ast.unparse(node.test)
        g = guarded or test.strip() in ("fetch", "fetch is True", "bool(fetch)")
        for child in node.body:
            guarded_calls(child, g, out)
        for child in node.orelse:
            guarded_calls(child, guarded, out)
        return out
    if isinstance(node, ast.Call):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in MUTATING:
            out.append((name, node.lineno, guarded))
    for child in ast.iter_child_nodes(node):
        guarded_calls(child, guarded, out)
    return out


calls = guarded_calls(build)
unguarded = [(n, l) for n, l, g in calls if not g]
checks = {
    "mutating_calls_found": len(calls) >= 2,
    "all_mutating_calls_guarded_by_fetch": not unguarded,
    "read_only_skip_logged": "read-only (fetch=False): skipping cache migration" in src,
}
for k, v in checks.items():
    print(f"[{'PASS' if v else 'FAIL'}] {k} {unguarded if k.startswith('all') else ''}")
print(f"\n{sum(checks.values())}/{len(checks)} checks passed")
sys.exit(0 if all(checks.values()) else 1)
