"""
scripts/build_bug_inventory.py must never silently drop a logged bug on rebuild (2026-10-10: a rebuild dropped
SWEEP-M-1 because its sweep heading was retitled from "M-1 OPEN ..." to "M-1 -- comparison arm BUILT ...", which the
status regex no longer matches; the inventory would have shrunk 310 -> 309 with no message). Written failing-first.
Checks on carry_forward(out, prev):
  1. hand/derived columns (verify_scripts_by_content, recheck_verdict) survive for ids still parsed
  2. an id in the previous inventory that the rebuild no longer parses is KEPT (its previous row) and reported
  3. ids new in this rebuild are added
Run: python debug/_verify_build_bug_inventory.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        from scripts.build_bug_inventory import carry_forward
    except ImportError as e:
        check("carry_forward_exists", False, str(e)); return finish()
    out = [{"id": "BUG-D1", "source": "Development.md", "doc_status": "fixed", "recheck_verdict": ""},
           {"id": "BUG-D2", "source": "Development.md", "doc_status": "open", "recheck_verdict": ""}]
    prev = {"BUG-D1": {"id": "BUG-D1", "source": "Development.md", "doc_status": "fixed", "recheck_verdict": "fixed-test",
                       "verify_scripts_by_content": "_verify_x.py"},
            "SWEEP-M-1": {"id": "SWEEP-M-1", "source": "INCONSISTENCY_SWEEP", "doc_status": "open",
                          "recheck_verdict": "documented-open", "verify_scripts_by_content": ""}}
    res, dropped = carry_forward(out, prev)
    by = {r["id"]: r for r in res}
    check("hand_columns_kept", by["BUG-D1"]["recheck_verdict"] == "fixed-test"
          and by["BUG-D1"]["verify_scripts_by_content"] == "_verify_x.py", by.get("BUG-D1"))
    check("unparsed_id_kept", "SWEEP-M-1" in by and by["SWEEP-M-1"]["recheck_verdict"] == "documented-open",
          sorted(by))
    check("unparsed_id_reported", dropped == ["SWEEP-M-1"], dropped)
    check("new_id_added", "BUG-D2" in by and len(res) == 3, len(res))
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
