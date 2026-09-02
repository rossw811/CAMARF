"""
debug/_verify_no_private_universe_globs.py -- structural guard against the
duplicated-universe-loader bug class, added 2026-09-01 per a code-quality
council review's recommendation.

The bug: a research/*.py script privately reimplements universe discovery
(a raw glob() over a cache directory, or a loop of DataStore.load() calls
building its own symbol list) instead of calling
universe_loader.load_full_universe() -- silently scoping itself to
whichever single cache directory it happened to glob (usually the old
~1,700-symbol yfinance-only cache), missing WRDS's ~44,700-symbol merge
entirely. This has recurred independently at least 13 times across this
project's history (see Development.md's 2026-08-24 and 2026-09-01 entries)
-- 13 separate manual-audit-triggered fixes for the exact same mistake,
with nothing structural stopping a 14th. This script is that structural
guard: a fast, static, grep-based scan (not a full AST/type analysis --
deliberately cheap, matching the project's own "don't over-engineer a
one-off diagnostic" convention) that fails loudly if a NEW instance of the
pattern appears, rather than waiting for the next manual audit to catch it
by chance.

What it flags: any research/*.py file that either
  (a) calls glob.glob(...) or os.listdir(...) against a path containing
      "cache" (case-insensitive) WITHOUT also importing
      universe_loader.load_full_universe in the same file, or
  (b) defines its own function literally named discover_symbols,
      _load_full_universe, or load_full_universe (shadowing the real one)
      that is not itself universe_loader.py.

What it deliberately does NOT flag (known, legitimate exceptions,
maintained here explicitly rather than silently -- add to this list with a
one-line reason if a new legitimate exception is found, don't just widen
the pattern until it stops complaining):
  - universe_loader.py itself (the canonical implementation).
  - Scripts that load ONE specific, named symbol (not universe-wide
    discovery) -- audit_price_degeneracy.py's DataStore.list_cached() at
    its default --tf 1m is a real, checked exception (WRDS has no
    intraday data, so the yfinance-only cache IS the correct full scope
    there) but is intentionally NOT auto-exempted here, since the same
    function would be a real bug at --tf 1D; flagged and reasoned about
    manually instead, see EXPECTED_FLAGS below.
  - wrds_deep_history_episodic_scan.py's direct output/cache/wrds/ glob --
    checked and confirmed correct 2026-09-01 (that directory alone
    already IS the full ~44,700-symbol merged universe on disk).

Usage: python debug/_verify_no_private_universe_globs.py
Exits 1 (fails loudly) if a NEW, unreasoned-about instance is found.
"""
import glob
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESEARCH_DIR = os.path.join(_ROOT, "research")

# Known, manually-reasoned-about exceptions -- filename -> one-line reason.
# A file in this dict is still SCANNED (so a NEW pattern elsewhere in it
# would still be caught) but its already-reviewed glob/loader pattern is
# not re-flagged every run.
EXPECTED_FLAGS = {
    "wrds_deep_history_episodic_scan.py": (
        "output/cache/wrds/ glob confirmed 2026-09-01: that directory alone "
        "already IS the full ~44,700-symbol merged universe on disk (WRDS-scoped "
        "script, by design, not missing yfinance/Binance/IBKR since those add no "
        "WRDS-covered daily-equity symbols this script needs)."
    ),
    "audit_price_degeneracy.py": (
        "DataStore.list_cached() at default --tf 1m is correct AS-IS: WRDS has "
        "no intraday data, so the yfinance/IBKR-only cache genuinely is the full "
        "achievable scope at that timeframe. Would be a real bug if ever run at "
        "--tf 1D -- not currently exercised that way, flagged for awareness, not "
        "auto-fixed."
    ),
    "lead_lag_scan.py": (
        "discover_symbols() is a helper only, not called by this file's own "
        "main() (which operates on already-confirmed pairs read from "
        "output/results/, not a fresh universe scan). The helper itself was the "
        "root cause of the near_miss_lag_scan.py bug (fixed 2026-09-01) when a "
        "DIFFERENT file imported and called it without an override -- kept here "
        "as dead-ish legacy code, not removed, but any NEW caller of this "
        "specific function should be treated as a fresh instance of the bug."
    ),
    "rolling_adv_comparison.py": (
        "Same pattern as wrds_deep_history_episodic_scan.py, checked 2026-09-01: "
        "_WRDS_CACHE_DIR = output/cache/wrds/, which already IS the full "
        "~44,700-symbol merged universe on disk. Not a bug."
    ),
    "cross_listing_lead_lag.py": (
        "Deliberately, correctly scoped to GVKEY*_1D.parquet only -- this script's "
        "entire purpose (2026-07-27) is comparing DIFFERENT LISTINGS of the SAME "
        "company via their shared Compustat Global gvkey, a genuine subset by "
        "design, not a 'full universe' claim that happens to be too narrow."
    ),
    "data_contamination_scan.py": (
        "FIXED 2026-09-01, not just an accepted exception: list_price_cache_files() "
        "now scans CACHE_DIR + ADDITIONAL_CACHE_DIRS (output/cache/wrds, output/"
        "cache/binance), with a suffix-normalization map (_SUFFIX_TO_CANONICAL_TF) "
        "since WRDS uses a completely different on-disk suffix convention (1D/1M/"
        "3M/6M/7D/1Y vs yfinance's 1day/1mo/3mo/6mo/7day). Still flagged here "
        "because it still globs a 'cache' path without importing "
        "universe_loader.load_full_universe -- by design: this script needs raw "
        "per-file access (timestamps, split-detection) that the merged-dict "
        "interface load_full_universe() returns doesn't expose, so reusing the "
        "canonical loader isn't the right fix here, multi-directory scanning is."
    ),
    "eg_null_calibration_montecarlo.py": (
        "GENUINE, LOWER-PRIORITY INSTANCE, not yet fixed (found 2026-09-01, "
        "flagged here rather than silently left broken): CACHE_DIR = 'output/"
        "cache' only, missing WRDS. Lower priority than a pair-discovery script "
        "because this tests EG-test Type-I error CALIBRATION on real-symbol nulls, "
        "not a step that itself certifies confirmed pairs -- still worth fixing so "
        "the calibration check is representative of the real ~44,700-symbol "
        "candidate pool, not just yfinance's ~1,700."
    ),
    "trend_dominance_diagnostic.py": (
        "GENUINE, LOWER-PRIORITY INSTANCE, not yet fixed (found 2026-09-01): "
        "CACHE_DIR = 'output/cache' only, missing WRDS. Diagnoses an already-"
        "known artifact (DD-hub concentration) in the existing 1h candidate pool "
        "rather than independently certifying pairs, so the undercount doesn't "
        "invalidate the finding's mechanism, but a full re-run at corrected scale "
        "would give a more representative concentration percentage than 259/353."
    ),
}

_GLOB_PATTERN = re.compile(r"(glob\.glob\(|os\.listdir\()[^)]*cache", re.IGNORECASE)
_BAD_FUNC_DEF = re.compile(r"^def\s+(discover_symbols|_load_full_universe|load_full_universe)\s*\(", re.MULTILINE)


def scan_file(path: str) -> list:
    """Pure-ish function (does its own file read, kept simple rather than
    threading file content through as a param -- this is a lightweight
    static check, not a candidate for synthetic ground-truth testing the
    way the project's real research logic is)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    imports_loader = "load_full_universe" in content and "from universe_loader import" in content
    issues = []
    if _GLOB_PATTERN.search(content) and not imports_loader:
        issues.append("globs/listdirs a cache path without importing universe_loader.load_full_universe")
    for func_match in _BAD_FUNC_DEF.finditer(content):
        func_name = func_match.group(1)
        # Not a false positive if it's a thin wrapper that itself delegates to the
        # real load_full_universe() -- check the ~500 chars after the def for a call
        # to it (crude but sufficient: catches inverse_polarity.py's correct
        # `return load_full_universe(tf_label=tf_label)` pattern without needing a
        # real AST parse for what's still a lightweight static check).
        body_window = content[func_match.end():func_match.end() + 500]
        if imports_loader and re.search(r"\bload_full_universe\(", body_window):
            continue
        issues.append(f"defines its own {func_name}() (shadows the canonical universe_loader.py one, "
                       f"and does not appear to delegate to it)")
    return issues


def main():
    files = sorted(glob.glob(os.path.join(_RESEARCH_DIR, "*.py")))
    new_flags = []
    known_flags = []
    for path in files:
        fname = os.path.basename(path)
        issues = scan_file(path)
        if not issues:
            continue
        if fname in EXPECTED_FLAGS:
            known_flags.append((fname, issues, EXPECTED_FLAGS[fname]))
        else:
            new_flags.append((fname, issues))

    print(f"Scanned {len(files)} files in research/.")
    if known_flags:
        print(f"\n{len(known_flags)} already-reviewed exception(s) (not failing):")
        for fname, issues, reason in known_flags:
            print(f"  {fname}: {issues}")
            print(f"    -> {reason}")

    if new_flags:
        print(f"\n{len(new_flags)} NEW, UNREVIEWED instance(s) of the universe-loader bug pattern:")
        for fname, issues in new_flags:
            print(f"  {fname}: {issues}")
        print(
            "\nFAIL: a new script appears to reinvent universe discovery instead of calling "
            "universe_loader.load_full_universe(). Either fix it to use the canonical loader, "
            "or -- if this is a genuine, reasoned exception (like the 3 already in "
            "EXPECTED_FLAGS above) -- add it to EXPECTED_FLAGS with a one-line justification, "
            "not silently. Do not widen the regex patterns above just to stop this failing."
        )
        sys.exit(1)

    print("\nPASS: no new instances of the duplicated-universe-loader bug pattern found.")


if __name__ == "__main__":
    main()
