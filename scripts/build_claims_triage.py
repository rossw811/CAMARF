"""
scripts/build_claims_triage.py -- plan S34 draft (Ross approved the rule 2026-10-10: thesis-central claims are fixed and
re-derived, peripheral ones withdrawn). Proposes a class for every claim row of docs/claims_table.csv from the scrutiny
section it sits in (docs/PAPER_SCRUTINY_2026-09-27.md headings), for Ross to confirm or flip per row:
  central    -- headline / abstract; PAPER.md §7.20-§7.22 (current headline sections), §5 empirical findings,
                §4 methodology; PAPER_MAGNITUDE.md §4 Finding 1, §5 Finding 2, §6 Synthesis, §3 shared methodology
  peripheral -- everything else (literature review, pre-WRDS Layer-1 results, §7.4-§7.19 side analyses, bias /
                AI-tool / future-work / references sections, MAGNITUDE §7 supporting findings, §8-§10)
WITHDRAWN rows stay withdrawn either way; the class matters for REGISTERED and CORRECTED rows.
Output: docs/claims_triage_S34.csv (id, paper, section, location, scrutiny_verdict, registry_status, proposed_class,
ross_class [blank, to fill]). Usage: python scripts/build_claims_triage.py
"""
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRUT = os.path.join(ROOT, "docs", "PAPER_SCRUTINY_2026-09-27.md")
TABLE = os.path.join(ROOT, "docs", "claims_table.csv")
OUT = os.path.join(ROOT, "docs", "claims_triage_S34.csv")
CENTRAL = [r"Headline and abstract", r"title block", r"opening paragraph", r"§7\.20", r"§5 Empirical", r"§4 Methodology",
           r"MAGNITUDE\.md §4", r"MAGNITUDE\.md §5", r"MAGNITUDE\.md §6", r"MAGNITUDE\.md §3"]


def section_of_ids(text: str) -> dict:
    sec, out = "", {}
    for line in text.splitlines():
        if line.startswith("### ") or line.startswith("## "):
            sec = line.lstrip("#").strip()
        m = re.match(r"^\| ([PM]-\d+[a-z]?) \|", line)
        if m:
            out[m.group(1)] = sec
    return out


def classify(section: str) -> str:
    return "central" if any(re.search(p, section) for p in CENTRAL) else "peripheral"


def main():
    t = pd.read_csv(TABLE)
    sec = section_of_ids(open(SCRUT, encoding="utf-8").read())
    t["section"] = t["id"].map(sec).fillna("")
    t["proposed_class"] = t["section"].map(classify)
    t["ross_class"] = ""
    t[["id", "paper", "section", "location", "claim", "scrutiny_verdict", "registry_status", "proposed_class",
       "ross_class"]].to_csv(OUT, index=False)
    live = t[t["registry_status"] != "WITHDRAWN"]
    print(f"{len(t)} claims -> {OUT}; not withdrawn: {len(live)}")
    print(pd.crosstab(live["paper"], live["proposed_class"]).to_string())


if __name__ == "__main__":
    main()
