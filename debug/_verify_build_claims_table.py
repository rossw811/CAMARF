"""
Synthetic check for scripts/build_claims_table.py (2026-10-07, written before the script). The script turns the
section-by-section scrutiny (docs/PAPER_SCRUTINY_2026-09-27.md, one row per claim: ID | Location | Claim | Verdict |
Finding IDs | Proposed replacement) into a claims table with a registry status:
  WITHDRAW -> WITHDRAWN (rests on a confirmed defect; S34 may move a central claim back to fix-and-re-derive)
  REPLACE  -> CORRECTED (a committed corrected value exists; cite it with its scope)
  STANDS / QUALIFY / UNVERIFIED -> REGISTERED (nothing counts as REPLICATED until re-derived on current data)
Checks: rows parsed with id/location/verdict/findings; status mapping; non-claim tables (verdict key, counts) ignored;
an unknown verdict is an error, not silently REGISTERED.
Run: python debug/_verify_build_claims_table.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


DOC = """# Paper Scrutiny
| Verdict | Meaning |
|---|---|
| **STANDS** | Checked |

| Paper | Rows | STANDS |
|---|---|---|
| PAPER.md | 196 | 30 |

| ID | Location | Claim (short quote) | Verdict | Finding IDs | Proposed replacement text |
|---|---|---|---|---|---|
| P-001 | PAPER.md:16-17 | Title "x" | QUALIFY | B2, B3 | Keep |
| P-002 | PAPER.md:19-26 | Retitled | WITHDRAW | S3 | gone |
| P-004 | PAPER.md:36-39 | loses money | REPLACE | B2; CR-1 | new text |
| M-010 | PAPER_MAGNITUDE.md:5 | durability | STANDS | - | keep |
| M-011 | PAPER_MAGNITUDE.md:9 | something | UNVERIFIED | - | run |
| P-091 | PAPER.md:803-812 | 4 of 32 examples |z|>10 at market open | STANDS | — | no change |
"""


def main():
    try:
        from scripts.build_claims_table import parse_claims
    except ImportError as e:
        check("module_exists", False, str(e)); return finish()
    t = parse_claims(DOC).set_index("id")
    check("six_claim_rows", len(t) == 6, list(t.index))
    check("pipe_inside_claim", t.loc["P-091", "claim"] == "4 of 32 examples |z|>10 at market open"
          and t.loc["P-091", "scrutiny_verdict"] == "STANDS", t.loc["P-091", "claim"] if "P-091" in t.index else None)
    check("status_withdrawn", t.loc["P-002", "registry_status"] == "WITHDRAWN")
    check("status_corrected", t.loc["P-004", "registry_status"] == "CORRECTED")
    check("status_registered", all(t.loc[i, "registry_status"] == "REGISTERED" for i in ("P-001", "M-010", "M-011")))
    check("fields", t.loc["P-004", "location"] == "PAPER.md:36-39" and t.loc["P-004", "findings"] == "B2; CR-1"
          and t.loc["M-010", "paper"] == "PAPER_MAGNITUDE.md")
    try:
        parse_claims(DOC.replace("| STANDS | - | keep |", "| MAYBE | - | keep |"))
        check("unknown_verdict_error", False)
    except ValueError:
        check("unknown_verdict_error", True)
    # 2026-10-10: decisions recorded after the scrutiny (S34 class, re-derivations) live in an overrides file the
    # builder applies last, so a rebuild cannot silently revert them
    try:
        from scripts.build_claims_table import apply_overrides
    except ImportError as e:
        check("apply_overrides_exists", False, str(e)); return finish()
    import pandas as pd
    ov = pd.DataFrame([{"id": "P-001", "registry_status": "WITHDRAWN", "s34_class": "peripheral", "status_reason": "S34"},
                       {"id": "P-004", "registry_status": "CORRECTED", "s34_class": "central", "status_reason": "C-001"}])
    u = apply_overrides(parse_claims(DOC), ov).set_index("id")
    check("override_status", u.loc["P-001", "registry_status"] == "WITHDRAWN" and u.loc["P-001", "status_reason"] == "S34")
    check("override_class", u.loc["P-004", "s34_class"] == "central")
    check("no_override_unchanged", u.loc["M-010", "registry_status"] == "REGISTERED" and u.loc["M-010", "status_reason"] == "")
    try:
        apply_overrides(parse_claims(DOC), pd.DataFrame([{"id": "P-999", "registry_status": "WITHDRAWN",
                                                          "s34_class": "", "status_reason": ""}]))
        check("unknown_override_id_error", False)
    except ValueError:
        check("unknown_override_id_error", True)
    try:
        apply_overrides(parse_claims(DOC), pd.DataFrame([{"id": "P-001", "registry_status": "MAYBE",
                                                          "s34_class": "", "status_reason": ""}]))
        check("bad_override_status_error", False)
    except ValueError:
        check("bad_override_status_error", True)
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
