"""
scripts/build_attribution.py -- process-paper task T5.4 (docs/PAPER_PROCESS_OUTLINE.md): what the git history does and
does not record about AI assistance. Reads every commit's `Co-Authored-By:` trailer and its line counts.
Writes docs/process_paper/attribution_by_commit.csv (one row per commit: date, model trailer or "none", python and
other lines added+deleted) and prints the summary by model and by month.

What a trailer means: the commit was made with that AI model as co-author. It does NOT say who wrote which lines,
and a commit without a trailer is "no record", not "written by hand" -- state the paper's claims at that strength.
Usage: python scripts/build_attribution.py
"""
import collections
import csv
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "process_paper", "attribution_by_commit.csv")


def main():
    out = subprocess.run(["git", "log", "--numstat", "--format=@@%H%x1f%ad%x1f%B%x1e", "--date=short"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    rows = []
    for rec in out.split("@@")[1:]:
        head, _, rest = rec.partition("\x1e")
        h, d, body = head.split("\x1f", 2)
        trailers = [t.strip() for t in re.findall(r"Co-Authored-By:\s*([^<\n]+)", body)]
        py = other = 0
        for line in rest.strip().splitlines():
            p = line.split("\t")
            if len(p) == 3 and p[0].isdigit() and p[1].isdigit():
                n = int(p[0]) + int(p[1])
                if p[2].endswith(".py"):
                    py += n
                else:
                    other += n
        rows.append({"commit": h[:10], "date": d, "model": "; ".join(trailers) or "none",
                     "py_lines": py, "other_lines": other})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    by_model = collections.Counter()
    n_model = collections.Counter()
    by_month = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        by_model[r["model"]] += r["py_lines"]
        n_model[r["model"]] += 1
        by_month[r["date"][:7]][0 if r["model"] != "none" else 1] += r["py_lines"]
    tot = sum(by_model.values())
    print(f"{len(rows)} commits {rows[-1]['date']} .. {rows[0]['date']} -> {OUT}")
    for m, v in by_model.most_common():
        print(f"  {m:22s} commits {n_model[m]:4d}  python lines {v:>9,} ({v / max(tot, 1):.0%})")
    print("python lines by month [with trailer, no record]:")
    for k, v in sorted(by_month.items()):
        print(f"  {k}  {v[0]:>8,}  {v[1]:>8,}")


if __name__ == "__main__":
    main()
