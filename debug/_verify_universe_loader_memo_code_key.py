"""
Regression test for code review U6 (re-checked 2026-10-07): universe_loader's memo key covered file counts/mtimes and
arguments, then (2026-09-27) a hand-maintained _LOADER_VERSION string -- which only works if every loader change
remembers to bump it (the drift class this project keeps finding). Fix: the key also carries a hash of
universe_loader.py's own source, so ANY code change invalidates old memos automatically.
Checks: the memo signature contains sha1(universe_loader.py bytes); changing the source (simulated by hashing a
modified copy through the same helper) changes the memo path.
Run: python debug/_verify_universe_loader_memo_code_key.py
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import universe_loader as ul

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    src = open(ul.__file__, "rb").read()
    want = hashlib.sha1(src).hexdigest()
    sig = ul._memo_signature("1D", True, True, False, False, ["close"])
    check("signature_has_source_hash", any(isinstance(p, tuple) and p[0] == "loader_code" and p[1] == want
                                           for p in sig), [p for p in sig if isinstance(p, tuple)][:3])
    if hasattr(ul, "_loader_code_hash"):
        p1 = ul._memo_cache_path("1D", True, True, False, False, ["close"])
        old = ul._LOADER_CODE_HASH
        try:
            ul._LOADER_CODE_HASH = ul._loader_code_hash(src + b"\n# edited\n")
            p2 = ul._memo_cache_path("1D", True, True, False, False, ["close"])
        finally:
            ul._LOADER_CODE_HASH = old
        check("code_change_changes_memo_path", p1 != p2)
    else:
        check("hash_helper_exists", False)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
