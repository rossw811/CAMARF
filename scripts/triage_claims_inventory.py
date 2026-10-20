"""
scripts/triage_claims_inventory.py -- first-pass dependency tags for the 2026-10-19 claims evaluation (Ross: "for all
of our claims we need to double check and evaluate if they're worth reporting ... every claim, all papers and docs").

Input:  docs/drafts/claims_inventory_2026-10-19.csv (806 claims, 12 files; extracted read-only by a Sonnet agent)
Output: docs/drafts/claims_evaluation_2026-10-19.csv -- the inventory plus
  depends_on   topic tags (';'-separated) naming the fix or pending run each claim hangs on
  check_route  rederive | verify_code | verify_data | verify_source | confirm_withdrawn
  first_pass   PENDING_CHAIN (needs the 2026-10-19 chain outputs) | CHANGED_BY_FIX (a 2026-10-17..19 fix changes it)
               | CHECK_NOW (verifiable on current code/data/sources) | WITHDRAWN (already withdrawn: confirm the doc says so)
  verdict, verdict_reason, evidence   blank -- filled claim by claim (keep / qualify / cut / withdraw)
Keyword tags are a FIRST PASS only; every row is reviewed by hand before a verdict.
"""
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, "docs", "drafts", "claims_inventory_2026-10-19.csv")
OUT = os.path.join(ROOT, "docs", "drafts", "claims_evaluation_2026-10-19.csv")

TOPICS = [  # (tag, regex on claim_text + section + cited_source, first_pass)
    ("D11_null_calibration", r"false.positive|null calibration|strictness paradox|7\.75|12\.75|type.i|over.conservative|random(ly)?.paired", "CHANGED_BY_FIX"),
    ("D13_durability", r"NTRS|STT|durab|last.?5.?y|five.year|currency", "CHANGED_BY_FIX"),
    ("PIT_spread_strict", r"sharpe|p&l|pnl|backtest|trades?\b|drawdown|return|profit|loses money|walk.forward|WFA|capital", "PENDING_CHAIN"),
    ("regime_crisis", r"crisis|calm|regime|episode|reappear|VIX|concentrat", "PENDING_CHAIN"),
    ("survivorship_D5_D6", r"survivor|delist|S&P 500 member|index member", "PENDING_CHAIN"),
    ("stress_test_D7_D9", r"stress test|quant quake|2007|GFC|covid|breakdown|dislocation", "PENDING_CHAIN"),
    ("discovery_counts", r"confirmed pairs?|tier.?[123]|BH.?FDR|candidates?|prefilter|pool|k1|k2|929|908|891", "PENDING_CHAIN"),
    ("endogeneity_arms", r"inclusion|Barberis|Forbes|Rigobon|DOLS|FM.?OLS|Johansen|ownership|volatility bias", "PENDING_CHAIN"),
    ("ibkr_universe", r"IBKR|44,?7\d\d|full.universe|45,?4\d\d", "CHECK_NOW"),
    ("ml_gate", r"meta.label|ML gate|layer.?2|classifier|XGB|gradient boost|random forest", "PENDING_CHAIN"),
]


def main():
    d = pd.read_csv(IN)
    text = (d["claim_text"].fillna("") + " " + d["section"].fillna("") + " " + d["cited_source"].fillna(""))
    tags, first = [], []
    for t, st in zip(text, d["status_marker"].fillna("none")):
        hit = [(tag, fp) for tag, rx, fp in TOPICS if re.search(rx, t, flags=re.I)]
        tags.append(";".join(h[0] for h in hit))
        if str(st).upper() == "WITHDRAWN":
            first.append("WITHDRAWN")
        elif any(fp == "CHANGED_BY_FIX" for _, fp in hit):
            first.append("CHANGED_BY_FIX")
        elif any(fp == "PENDING_CHAIN" for _, fp in hit):
            first.append("PENDING_CHAIN")
        else:
            first.append("CHECK_NOW")
    route = d["claim_type"].map({"literature": "verify_source", "method_description": "verify_code",
                                 "data_description": "verify_data"}).fillna("rederive")
    route = route.where(pd.Series(first) != "WITHDRAWN", "confirm_withdrawn")
    out = d.assign(depends_on=tags, check_route=route, first_pass=first, verdict="", verdict_reason="", evidence="")
    out.to_csv(OUT, index=False)
    print(out["first_pass"].value_counts().to_string())
    print(pd.crosstab(out["file"], out["first_pass"]).to_string())
    print(out["check_route"].value_counts().to_string())


if __name__ == "__main__":
    main()
