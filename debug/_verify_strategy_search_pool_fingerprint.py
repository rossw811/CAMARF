"""
The strategy search must never reuse trades built from a different pool (2026-10-11). The second pre-registered pass
(pool chain 2026-10-10, new pools written 20:36) "ran" in 6 seconds: research/strategy_search.py's run phase skips any
config whose <pool>/<cfg>.parquet exists, and all 432 files were the FIRST pass's (2026-09-27, old pools). The eval
then scored those old trades against the new pools' eligible_from start. Written failing-first. Checks:
  1. pool_fingerprint(path) is a content hash (same bytes -> same value; changed bytes -> different value)
  2. check_pool_dir(dir, fp, fresh=False): a dir with no fingerprint file but existing trade files, or a different
     fingerprint, is REFUSED (SystemExit); an empty/missing dir is initialised with the fingerprint
  3. check_pool_dir(..., fresh=True) MOVES a stale dir to a backup (contents kept, nothing deleted) and starts clean
  4. a matching fingerprint is accepted and its trade files are kept (genuine resume)
  5. run_phase and eval_phase both call check_pool_dir (source check)
Run: python debug/_verify_strategy_search_pool_fingerprint.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import strategy_search as ss
    fp_fn, chk = getattr(ss, "pool_fingerprint", None), getattr(ss, "check_pool_dir", None)
    check("functions_exist", fp_fn is not None and chk is not None)
    if fp_fn is None or chk is None:
        return finish()
    tmp = tempfile.mkdtemp()
    try:
        p1, p2 = os.path.join(tmp, "a.parquet"), os.path.join(tmp, "b.parquet")
        open(p1, "wb").write(b"pool-v1"); open(p2, "wb").write(b"pool-v2")
        f1, f2 = fp_fn(p1), fp_fn(p2)
        check("fingerprint_content_hash", f1 == fp_fn(p1) and f1 != f2)
        d = os.path.join(tmp, "out", "pit_k1")
        os.makedirs(d); open(os.path.join(d, "cfg1.parquet"), "wb").write(b"old trades")
        try:
            chk(d, f1, fresh=False); check("refuses_unfingerprinted_dir", False)
        except SystemExit:
            check("refuses_unfingerprinted_dir", True)
        chk(d, f1, fresh=True)
        backups = [x for x in os.listdir(os.path.dirname(d)) if x.startswith("pit_k1_stale_")]
        kept = backups and os.path.exists(os.path.join(os.path.dirname(d), backups[0], "cfg1.parquet"))
        check("fresh_moves_to_backup", bool(kept) and not os.path.exists(os.path.join(d, "cfg1.parquet")), backups)
        check("fresh_writes_fingerprint", ss._read_fp(d) == f1)
        open(os.path.join(d, "cfg2.parquet"), "wb").write(b"new trades")
        chk(d, f1, fresh=False)
        check("matching_fp_resumes", os.path.exists(os.path.join(d, "cfg2.parquet")))
        try:
            chk(d, f2, fresh=False); check("refuses_other_pool", False)
        except SystemExit:
            check("refuses_other_pool", True)
        e = os.path.join(tmp, "out", "pit_k2")
        chk(e, f2, fresh=False)
        check("initialises_new_dir", ss._read_fp(e) == f2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    src = open(ss.__file__, encoding="utf-8").read()
    run_src = src[src.index("def run_phase("):src.index("\ndef ", src.index("def run_phase(") + 5)]
    ev_src = src[src.index("def eval_phase("):src.index("\ndef ", src.index("def eval_phase(") + 5)]
    check("run_phase_checks", "check_pool_dir(" in run_src)
    check("eval_phase_checks", "check_pool_dir(" in ev_src or "_read_fp(" in ev_src)
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
