"""
Regression test for T1.8 (plan of action, 2026-10-03): data.py had 26 broad `except Exception` handlers that neither
logged nor re-raised. Triage: 2 now FAIL LOUD (an unreadable exclusions file used to mean "no exclusions"; an unreadable
delisted registry used to return {} -- both silently changed the universe), the rest log (warning where data can be
wrong: timezone fallbacks, a frequency check that could not run, IBKR retries, constituent caches; debug for caches),
and two alternative yfinance column layouts are commented as such.
Checks:
  1. no broad handler in data.py is silent: its body logs, raises, or the handler line carries an explanatory comment;
  2. a corrupt exclusions file raises RuntimeError (temp file -- the real one is never touched);
  3. a corrupt delisted registry raises RuntimeError (temp file).
Run: python debug/_verify_data_no_silent_handlers.py
"""
import ast
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    src = open(os.path.join(ROOT, "data.py"), encoding="utf-8").read()
    lines = src.split("\n")
    silent = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.ExceptHandler):
            continue
        if not (n.type is None or (isinstance(n.type, ast.Name) and n.type.id in ("Exception", "BaseException"))):
            continue
        body = "\n".join(ast.unparse(b) for b in n.body)
        handled = any(k in body for k in ("log.", "logger.", "raise", "print(", "+= 1"))
        commented = "#" in lines[n.lineno - 1] or lines[n.lineno].strip().startswith("#")
        if not (handled or commented):
            silent.append(n.lineno)
    check("1.no_silent_broad_handlers", not silent, f"silent at lines {silent}")
    from data import UniverseBuilder as U
    tmp = tempfile.mkdtemp(prefix="t18_")
    bad = os.path.join(tmp, "bad.json")
    open(bad, "w").write("{not json")
    for name, attr, call in (("2.corrupt_exclusions_raise", "_EXCLUSION_CACHE", U.load_exclusions),
                             ("3.corrupt_delisted_registry_raises", "_DELISTED_REGISTRY", U.load_delisted_registry)):
        orig = getattr(U, attr)
        setattr(U, attr, bad)
        try:
            call()
            check(name, False, "no exception")
        except RuntimeError as e:
            check(name, True, str(e)[:80])
        except Exception as e:
            check(name, False, f"{type(e).__name__}: {e}")
        finally:
            setattr(U, attr, orig)
    shutil.rmtree(tmp, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
