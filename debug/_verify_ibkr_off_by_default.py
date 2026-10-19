"""
debug/_verify_ibkr_off_by_default.py -- architecture rule 2 (Ross 2026-09-27): IBKR deep history is off by default; it
holds only previously confirmed pairs' symbols, so turning it on makes data depth depend on earlier results. It may be
used only as a separately labelled, opt-in side arm. Found 2026-10-19 (review of 2ec0c521):
full_universe_eg_confirmation.py loaded IBKR unless --no-ibkr was passed, and hedge_blend_test.py hardcoded it on.
Fails if any research/ script turns include_ibkr on without an explicit opt-in flag.
"""
import glob
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAD = [re.compile(r"include_ibkr\s*=\s*True"), re.compile(r"include_ibkr\s*=\s*not\s+args\.no_ibkr"),
       re.compile(r"add_argument\(\s*[\"']--no-ibkr[\"']")]

hits = []
for path in sorted(glob.glob(os.path.join(_ROOT, "research", "*.py"))):
    for i, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        if any(b.search(line) for b in BAD):
            hits.append(f"{os.path.relpath(path, _ROOT)}:{i}: {line.strip()}")

for h in hits:
    print(f"  FAIL: IBKR on by default -> {h}")
print(f"  {'PASS' if not hits else 'FAIL'}: no research/ script loads IBKR without an explicit opt-in "
      f"[{len(hits)} hits]")
sys.exit(0 if not hits else 1)
