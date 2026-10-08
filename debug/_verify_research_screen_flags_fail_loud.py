"""
Regression test (2026-10-07; T1.8 leftover / W6.4, flagged again by the independent check on BUG-D97):
analysis.AnalysisPipeline._apply_research_screen_flags read three research files (price-degeneracy flags, degeneracy
metadata, EG-permutation check) inside `except Exception: pass` -- an existing but unreadable file silently produced
UNFLAGGED pairs. Under Ross's DEV-057 decision (flag and include, plus a sensitivity run excluding flagged pairs)
that silently changes a result. Rule (T1.8): a file that is absent -> no flags (the screen was not run, unchanged);
a file that EXISTS but cannot be read -> fail loud with the path. The research dir follows
Config.DATA.OUTPUT_DIR (it was hardcoded next to analysis.py, so the configured output location was ignored).
Checks (temp output dir): absent files -> returns the pairs unchanged; a corrupt price_degeneracy_flagged file ->
RuntimeError naming the file; same for eg_permutation_check.
Run: python debug/_verify_research_screen_flags_fail_loud.py
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def _Pair(a, b):
    """A real PairResult (the function uses dataclasses.replace): symbols set, every other field None."""
    import dataclasses
    import analysis
    kw = {f.name: None for f in dataclasses.fields(analysis.PairResult)}
    kw.update(symbol_a=a, symbol_b=b)
    return analysis.PairResult(**kw)


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import analysis
    from config import Config
    d = tempfile.mkdtemp(prefix="screen_flags_")
    old = Config.DATA.OUTPUT_DIR if hasattr(Config.DATA, "OUTPUT_DIR") else None
    try:
        rd = os.path.join(d, "research")
        os.makedirs(rd)
        analysis.Config.DATA.OUTPUT_DIR = d
        pairs = [_Pair("A", "B")]
        try:
            out = analysis.AnalysisPipeline._apply_research_screen_flags(pairs, "1D")
            check("absent_files_no_error", out is pairs or len(out) == 1)
        except Exception as e:
            check("absent_files_no_error", False, f"{type(e).__name__}: {e}")
        from data import DataStore
        safe = DataStore._TF_SAFE.get("1D", "1d")
        for name in (f"price_degeneracy_flagged_{safe}.parquet", "eg_permutation_check.parquet"):
            for f in os.listdir(rd):
                os.remove(os.path.join(rd, f))
            with open(os.path.join(rd, name), "wb") as fh:
                fh.write(b"not a parquet file")
            try:
                analysis.AnalysisPipeline._apply_research_screen_flags([_Pair("A", "B")], "1D")
                check(f"corrupt_{name}_fails_loud", False, "no error")
            except RuntimeError as e:
                check(f"corrupt_{name}_fails_loud", name in str(e), str(e)[:120])
            except Exception as e:
                check(f"corrupt_{name}_fails_loud", False, f"{type(e).__name__}: {e}")
    finally:
        if old is not None:
            analysis.Config.DATA.OUTPUT_DIR = old
        shutil.rmtree(d, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
