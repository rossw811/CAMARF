"""
scripts/build_claims_table.py -- plan W4.3 / S20 groundwork (2026-10-07): every claim the section-by-section scrutiny
lists (docs/PAPER_SCRUTINY_2026-09-27.md, 284 rows across PAPER.md and PAPER_MAGNITUDE.md) gets a registry status:
  WITHDRAW -> WITHDRAWN  (rests on a confirmed defect; plan S34 may move a central claim back to fix-and-re-derive)
  REPLACE  -> CORRECTED  (a committed corrected value exists -- cite it with its scope)
  STANDS / QUALIFY / UNVERIFIED -> REGISTERED (nothing is REPLICATED until re-derived on current data)
Output: docs/claims_table.csv (id, paper, location, claim, scrutiny_verdict, findings, registry_status); prints counts.
docs/CLAIMS_REGISTRY.md links to it; the full entries C-001.. stay there for claims re-derived one by one.
Usage: python scripts/build_claims_table.py
Synthetic check: debug/_verify_build_claims_table.py
"""
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "PAPER_SCRUTINY_2026-09-27.md")
OUT = os.path.join(ROOT, "docs", "claims_table.csv")
STATUS = {"WITHDRAW": "WITHDRAWN", "REPLACE": "CORRECTED", "STANDS": "REGISTERED", "QUALIFY": "REGISTERED",
          "UNVERIFIED": "REGISTERED"}
_ID = re.compile(r"^[PM]-\d+[a-z]?$")


def parse_claims(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        raw = line.strip().strip("|").split("|")
        c = [x.strip() for x in raw]
        if len(c) < 5 or not _ID.match(c[0]):
            continue
        # claims may contain an unescaped "|" (e.g. |z|): the verdict cell is the anchor -- the first cell after the
        # location that is a known verdict word; the claim is the raw cells in between, re-joined
        vi = next((i for i in range(3, len(c) - 1) if c[i].strip("*").strip().upper() in STATUS), None)
        if vi is None:
            raise ValueError(f"{c[0]}: no known scrutiny verdict in {c[2:]!r}")
        verdict = c[vi].strip("*").strip().upper()
        rows.append({"id": c[0], "paper": c[1].split(":")[0], "location": c[1], "claim": "|".join(raw[2:vi]).strip(),
                     "scrutiny_verdict": verdict, "findings": c[vi + 1], "registry_status": STATUS[verdict]})
    return pd.DataFrame(rows, columns=["id", "paper", "location", "claim", "scrutiny_verdict", "findings",
                                       "registry_status"])


def main():
    t = parse_claims(open(SRC, encoding="utf-8").read())
    t.to_csv(OUT, index=False)
    print(f"{len(t)} claims -> {OUT}")
    print(pd.crosstab(t["paper"], t["registry_status"]).to_string())


if __name__ == "__main__":
    main()
