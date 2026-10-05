"""
scripts/build_failures_table.py -- process paper task T5.3 (docs/PAPER_PROCESS_OUTLINE.md): one row per logged failure
from the code-review ledger (docs/CODE_REVIEW_2026-09-26.md, 175 rows), as a data file the paper's failure taxonomy
is computed from -- docs/process_paper/failures.csv.

EXTRACTED (facts from the ledger text): id, review group, location, severity, finding, status_text, status (FIXED /
CONFIRMED-OPEN / NEEDS-ROSS / UNVERIFIED / FALSE-POSITIVE / KNOWN), tests (debug/_verify_*.py named), dates seen.
RULE-BASED GUESSES (labelled; NOT facts until reviewed): class_rule (keyword rule), effect_quantified (does the
status text contain a before/after number). `class_reviewed` / `effect_reviewed` are left EMPTY for a human pass --
the paper uses only reviewed values.
Usage: python scripts/build_failures_table.py
"""
import collections
import csv
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "CODE_REVIEW_2026-09-26.md")
OUT = os.path.join(ROOT, "docs", "process_paper", "failures.csv")

# first matching class wins; order = most specific first
CLASS_RULES = [
    ("identity", r"\blabel|ticker|permno|gvkey|collision|identity|same security|symbol"),
    ("accounting", r"p&l|pnl|sharpe|notional|commission|cost|kelly|sizing|equity|drawdown|calmar|profit"),
    ("units_scale", r"currency|\bfx\b|usd|volume|split|unit|scale|pence"),
    ("calendar_time", r"calendar|stamp|timezone|\btz\b|weekend|business.day|period.end|holiday|bar.*date|intraday|session"),
    ("lookahead_selection", r"lookahead|look-ahead|full.sample|holdout|in.sample|survivorship|future|leak|pool|selected"),
    ("data_fabrication", r"forward.fill|ffill|fill_value|fabricat|padding|stale"),
    ("silent_fallback", r"silent|swallow|except|fallback|fail.open|ignored|never (?:reset|checked)"),
    ("statistic", r"p.value|fdr|\btest\b|null|critical|cusum|bootstrap|half.life|hurst|binomial|z-test|regression|statistic"),
]


def status_of(text: str) -> str:
    t = text.upper()
    for k, v in (("FALSE POSITIVE", "FALSE-POSITIVE"), ("NEEDS ROSS", "NEEDS-ROSS"), ("FIXED", "FIXED"),
                 ("RESOLVED", "FIXED"), ("REFUTED", "FALSE-POSITIVE"), ("NOT CONFIRMED", "FALSE-POSITIVE"),
                 ("CONFIRMED", "CONFIRMED-OPEN"), ("KNOWN", "KNOWN"), ("UNVERIFIED", "UNVERIFIED")):
        if k in t:
            return v
    return "UNCLASSIFIED"


def main():
    lines = open(SRC, encoding="utf-8").read().split("\n")
    group = ""
    rows = []
    for l in lines:
        if l.startswith("## "):
            group = l[3:].strip()[:60]
        m = re.match(r"^\| ([A-Z]+\d+(?:\.\d+)?) \|(.*)\|\s*$", l)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 4:
            continue
        loc, sev, finding, status_text = cells[0], cells[1], cells[2], " | ".join(cells[3:])
        low = (finding + " " + status_text).lower()
        cls = next((c for c, rx in CLASS_RULES if re.search(rx, low)), "other")
        rows.append({
            "id": m.group(1), "group": group, "location": loc, "severity": re.sub(r"\*", "", sev),
            "finding": finding, "status": status_of(status_text), "status_text": status_text,
            "tests": ";".join(sorted(set(re.findall(r"_verify_[A-Za-z0-9_]+\.py", status_text)))),
            "dates": ";".join(sorted(set(re.findall(r"20\d\d-\d\d-\d\d", status_text)))),
            "class_rule": cls,
            "effect_quantified": bool(re.search(r"\d[\d,.]*\s*(?:→|->|vs\.?)\s*[-+$]?\d", status_text)),
            "class_reviewed": "", "effect_reviewed": "",
        })
    # human/assistant-assigned classes (docs/process_paper/failure_classes.csv, with who assigned them) override
    # the keyword guess; the guess stays in class_rule for comparison
    cpath = os.path.join(ROOT, "docs", "process_paper", "failure_classes.csv")
    if os.path.exists(cpath):
        assigned = {r["id"]: r for r in csv.DictReader(open(cpath, encoding="utf-8"))}
        for r in rows:
            a = assigned.get(r["id"])
            if a:
                r["class_reviewed"], r["class_assigned_by"] = a["class"], a["assigned_by"]
            else:
                r["class_assigned_by"] = ""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} ledger rows -> {OUT}")
    print("by status:", dict(collections.Counter(r["status"] for r in rows).most_common()))
    print("by class_rule (GUESS until reviewed):", dict(collections.Counter(r["class_rule"] for r in rows).most_common()))
    asg = [r for r in rows if r.get("class_reviewed")]
    print(f"assigned classes ({len(asg)} rows):", dict(collections.Counter(r["class_reviewed"] for r in asg).most_common()))
    agree = sum(1 for r in asg if r["class_reviewed"] == r["class_rule"])
    print(f"keyword rule agrees with the assigned class on {agree}/{len(asg)} rows")
    fixed = [r for r in rows if r["status"] == "FIXED"]
    print(f"FIXED: {len(fixed)}; with a named test: {sum(1 for r in fixed if r['tests'])}; "
          f"with a quantified before/after: {sum(1 for r in fixed if r['effect_quantified'])}")


if __name__ == "__main__":
    main()
