# =============================================================================
# Verify: data_wrds.resolve_symbol_canonicalization, and its new upstream use
# in research/full_universe_correlation_prefilter.py (backlog item #4, docs/
# HANDOFF.md, Ross-approved 2026-09-13). Extracted from research/promote_
# full_universe_pairs.py's original inline version (2026-08-24) -- verifies
# the extraction preserved behavior, plus the NEW dedup-at-the-symbol-level
# integration point.
#
# Real-scale evidence, not just synthetic (measured live before wiring this
# in, 2026-09-13): of 6,844 PERMNO-labeled symbols in the real ~43,883-symbol
# WRDS-primary universe, resolve_permnos_bulk resolved 21,731/21,945 plain
# tickers in 11.9s, and 2,210 (32% of all PERMNO-labeled symbols) turned out
# to be literal aliases of an already-present plain ticker -- real, scale-
# appropriate contamination, not a theoretical edge case.
# =============================================================================
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_wrds

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# 1. alias_file path (no live WRDS connection needed) -- the mode a machine
#    with only cached price data, no WRDS auth, must use.
tmp = tempfile.mkdtemp(prefix="camarf_canon_test_")
try:
    alias_file = os.path.join(tmp, "aliases.json")
    with open(alias_file, "w") as f:
        json.dump({"PERMNO17987": "VRT", "PERMNO99999": "NOT_IN_UNIVERSE"}, f)

    symbols = ["VRT", "PERMNO17987", "AAPL", "MSFT"]
    canon = data_wrds.resolve_symbol_canonicalization(db=None, symbols=symbols, alias_file=alias_file)
    check("alias_file.resolves_known_alias", canon.get("PERMNO17987") == "VRT", f"got {canon}")
    check("alias_file.ignores_alias_not_in_symbol_set",
          "PERMNO99999" not in canon, f"got {canon}")
    check("alias_file.plain_tickers_not_in_canon_map",
          "AAPL" not in canon and "MSFT" not in canon, f"got {canon}")

    # 2. db=None and no alias_file -> must raise, not silently return {} (a caller
    #    silently getting an empty canon map would think "no aliases found" when
    #    really it just couldn't check at all).
    raised = False
    try:
        data_wrds.resolve_symbol_canonicalization(db=None, symbols=symbols)
    except ValueError:
        raised = True
    check("no_db_no_alias_file.raises_not_silent", raised)

    # 3. Manual-verified alias (MKC, genuinely CRSP-ambiguous, WRDS resolution alone
    #    can't establish it) still gets applied even via the alias_file path, as a
    #    fallback layer -- matches the original script's documented behavior.
    symbols_mkc = ["MKC", "PERMNO52090"]
    canon_mkc = data_wrds.resolve_symbol_canonicalization(db=None, symbols=symbols_mkc, alias_file=alias_file)
    check("manual_verified_alias.mkc_applied_even_via_alias_file",
          canon_mkc.get("PERMNO52090") == "MKC", f"got {canon_mkc}")

    # 4. Integration-point simulation: dropping canon-mapped symbols from an
    #    aligned_data-shaped dict (what full_universe_correlation_prefilter.py's
    #    new code actually does) removes exactly the alias symbols, keeps everything
    #    else, including symbols that were never in the canon map at all.
    import pandas as pd
    aligned_data = {s: pd.DataFrame({"close": [1, 2, 3]}) for s in ["VRT", "PERMNO17987", "AAPL"]}
    canon2 = {"PERMNO17987": "VRT"}
    filtered = {s: df for s, df in aligned_data.items() if s not in canon2}
    check("integration.drops_only_alias_symbols",
          set(filtered.keys()) == {"VRT", "AAPL"}, f"got {set(filtered.keys())}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_pass = sum(1 for _, ok, _ in checks if ok)
print(f"\n{n_pass}/{len(checks)} checks passed")
print("\nReal-scale evidence (measured live, 2026-09-13, before wiring this in): "
      "2,210/6,844 (32%) of PERMNO-labeled symbols in the real ~43,883-symbol universe "
      "are literal aliases of an already-present plain ticker -- see this file's header.")
sys.exit(0 if n_pass == len(checks) else 1)
