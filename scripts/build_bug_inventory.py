"""
scripts/build_bug_inventory.py -- one inventory of every logged bug (plan of action T14.1/T14.2, 2026-10-03).

Sources: Development.md (canonical registry; every BUG-* id), docs/BUG_LOG.md (index), docs/CODE_REVIEW_2026-09-26.md
(ledger table rows), docs/INCONSISTENCY_SWEEP_2026-09-27.md (sweep findings). For each id: where it is logged (first
and last mention), the latest status word found next to it, the verify scripts that mention it, and whether the
index (BUG_LOG) lists it. This is a STARTING POINT for the recheck, not a verdict: "status" is what the docs say,
which is exactly what T14 re-checks.
Output: docs/bug_recheck/inventory.csv (+ a summary printed).
Usage: python scripts/build_bug_inventory.py
"""
import collections
import csv
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    return open(os.path.join(ROOT, p), encoding="utf-8", errors="replace").read()


STATUS_WORDS = [("WITHDRAWN", "withdrawn"), ("REFUTED", "not confirmed"), ("NOT CONFIRMED", "not confirmed"),
                ("REVERTED", "reverted"), ("FIXED", "fixed"), ("RESOLVED", "fixed"), ("CONFIRMED", "confirmed-open"),
                ("UNVERIFIED", "unverified"), ("OPEN", "open")]


def status_near(text, pos, span=260):
    w = text[pos: pos + span].upper()
    for k, v in STATUS_WORDS:
        if k in w:
            return v
    return ""


def carry_forward(out, prev):
    """Merge a rebuild with the previous inventory. Hand/derived columns survive (2026-10-03: a re-run had wiped the
    T14.2 content mapping), and an id the rebuild no longer parses is KEPT with its previous row and returned in
    `dropped` -- never silently removed (2026-10-10: SWEEP-M-1 vanished after its sweep heading was retitled)."""
    keep = ("verify_scripts_by_content", "recheck_verdict")
    for r in out:
        for k in keep:
            if prev.get(r["id"], {}).get(k):
                r[k] = prev[r["id"]][k]
    have = {r["id"] for r in out}
    dropped = sorted(i for i in prev if i not in have)
    out = out + [dict(prev[i]) for i in dropped]
    return sorted(out, key=lambda r: r["id"]), dropped


def main():
    rows = {}
    dev = read("Development.md")
    dev_lines = dev.split("\n")
    line_starts = [0]
    for l in dev_lines:
        line_starts.append(line_starts[-1] + len(l) + 1)

    def lineno(pos):
        import bisect
        return bisect.bisect_right(line_starts, pos)

    # normalise BUG-D01 / BUG-D1, and read slash lists ("BUG-D107/D109/D110") as one mention of each id
    for m in re.finditer(r"\bBUG-([A-Z]+)(\d+)((?:/(?:BUG-)?[A-Z]*\d+)*)\b", dev):
        ids = [f"BUG-{m.group(1)}{int(m.group(2))}"] + [
            f"BUG-{p or m.group(1)}{int(n)}" for p, n in re.findall(r"/(?:BUG-)?([A-Z]*)(\d+)", m.group(3))]
        for bid in ids:
            r = rows.setdefault(bid, {"id": bid, "source": "Development.md", "first_line": lineno(m.start()),
                                      "last_line": 0, "n_mentions": 0, "doc_status": ""})
            r["last_line"] = lineno(m.start())
            r["n_mentions"] += 1
            st = status_near(dev, m.start())
            if st:
                r["doc_status"] = st                      # latest mention's status wins
    idx = read("docs/BUG_LOG.md")
    # 2026-10-03: the index writes ids as table rows "| D01 |" (zero-padded, no "BUG-" prefix); the first version
    # matched only "BUG-D1" and under-counted coverage as 47/125 (true: 124/125). Normalise both forms.
    indexed = ({f"BUG-{p}{int(n)}" for p, n in re.findall(r"^\| ([A-Z]+)(\d+) \|", idx, re.M)}
               | {f"BUG-{p}{int(n)}" for p, n in re.findall(r"\bBUG-([A-Z]+)(\d+)\b", idx)})

    rev = read("docs/CODE_REVIEW_2026-09-26.md")
    for l in rev.split("\n"):
        m = re.match(r"^\| ([A-Z]+\d+(?:\.\d+)?) \|", l)
        if m:
            last = l.rstrip().rstrip("|").split("|")[-1].upper()
            st = next((v for k, v in STATUS_WORDS if k in last), "")
            rows[m.group(1)] = {"id": m.group(1), "source": "CODE_REVIEW ledger", "first_line": "", "last_line": "",
                                "n_mentions": 1, "doc_status": st}
    sw = read("docs/INCONSISTENCY_SWEEP_2026-09-27.md")
    for m in re.finditer(r"\*\*((?:C\d-\d|M-\d|S\d|M\d+|C0-\d|C1-\d|C4-\d|C6-\d|A6/S10))\b[^*]*?(FIXED|OPEN|SURFACED|CORRECTED)", sw):
        bid = "SWEEP-" + m.group(1)
        rows[bid] = {"id": bid, "source": "INCONSISTENCY_SWEEP", "first_line": "", "last_line": "", "n_mentions": 1,
                     "doc_status": {"FIXED": "fixed", "OPEN": "open", "SURFACED": "surfaced", "CORRECTED": "fixed"}[m.group(2)]}

    tests = {}
    for f in glob.glob(os.path.join(ROOT, "debug", "_verify_*.py")):
        txt = open(f, encoding="utf-8", errors="replace").read()
        head = txt[:4000]
        for bid in rows:
            key = bid.replace("SWEEP-", "")
            if re.search(rf"(?<![\w.-]){re.escape(key)}(?![\w.])", head):
                tests.setdefault(bid, []).append(os.path.basename(f))
    out = []
    for bid, r in sorted(rows.items()):
        r["verify_scripts"] = ";".join(sorted(tests.get(bid, [])))
        r["n_tests"] = len(tests.get(bid, []))
        r["in_bug_log_index"] = bid in indexed if bid.startswith("BUG-") else ""
        r["recheck_verdict"] = ""                       # filled by T14.3-14.5: holds / regressed / obsolete / untested
        out.append(r)
    os.makedirs(os.path.join(ROOT, "docs", "bug_recheck"), exist_ok=True)
    inv_path = os.path.join(ROOT, "docs", "bug_recheck", "inventory.csv")
    if os.path.exists(inv_path):
        prev = {r["id"]: r for r in csv.DictReader(open(inv_path, encoding="utf-8"))}
        out, dropped = carry_forward(out, prev)
        if dropped:
            print(f"WARNING: {len(dropped)} previously inventoried id(s) no longer parsed from the docs -- kept from the "
                  f"previous inventory (fix the parser or the doc heading): {dropped}")
    cols = ["id", "source", "doc_status", "n_tests", "verify_scripts", "verify_scripts_by_content",
            "in_bug_log_index", "first_line", "last_line", "n_mentions", "recheck_verdict"]
    with open(inv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in out:
            w.writerow({c: r.get(c, "") for c in cols})
    by = collections.Counter((r["source"], r["doc_status"] or "-") for r in out)
    print(f"{len(out)} logged items")
    for k, v in sorted(by.items()):
        print(f"  {k[0]:22s} {k[1]:15s} {v}")
    with_test = sum(1 for r in out if r["n_tests"])
    print(f"with >=1 verify script mentioning the id: {with_test}/{len(out)}")
    bugs = [r for r in out if r["id"].startswith("BUG-")]
    print(f"Development.md BUG ids: {len(bugs)}; in BUG_LOG index: {sum(1 for r in bugs if r['in_bug_log_index'])}")


if __name__ == "__main__":
    main()
