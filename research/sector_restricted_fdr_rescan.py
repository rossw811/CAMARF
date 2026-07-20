"""
research/sector_restricted_fdr_rescan.py -- Ross's direct request (2026-07-20),
the second of two follow-ups to the 4-method FDR comparison
(research/fdr_method_comparison.py). Tests whether a PRE-REGISTERED, economically
motivated restriction of the candidate universe -- same-GICS-sector pairs only,
the classic convention from Gatev, Goetzmann & Rouwenhorst (2006)'s original
distance-method pairs-trading paper -- legitimately shrinks the multiple-testing
burden (m) enough to change which pairs survive FDR correction.

Honesty note on pre-registration (stated here, not glossed over): the choice of
"same-sector" as the restriction rule reflects an independently well-established
literature convention that predates and is unrelated to this session's specific
findings -- it was not invented to rescue any particular pair. However, this
script's author (this session) had already observed, before writing this script,
that 4 of the 8 target pairs from research/confirmatory_cointegration_check.py
(CMS/DUK, EG/WRB, HAL/NOV, UMBF/FHB) plus both new FDR survivors (FELE/MAS,
PNC/ZION) happen to be same-sector pairs. This is disclosed explicitly because a
truly blind pre-registration would have been decided before ever looking at
which specific pairs the rule would keep -- that did not happen here. The rule
itself is not p-hacked (it does not depend on any pair's p-value), but full
transparency requires flagging that the pattern was seen first. Per rule 7,
report the honest result either way, whichever pairs it does or doesn't recover.

By construction, this restriction CANNOT recover LNT/VTR, LNT/WELL, MET/TMHC, or
PFG/STLD -- all four are cross-sector pairs, structurally excluded by the rule
itself regardless of their p-values. This must not be glossed over as a "failure
of FDR" -- it is the rule doing exactly what it says.

Reuses the EXACT SAME raw EG p-values already computed by
research/fdr_method_comparison.py's full-universe run (no re-scan, no new EG
tests -- same underlying data, just re-corrected under a different, smaller m),
restricted to pairs where both symbols carry a GICS sector tag (gics.py's
already-built output/cache/gics_tags.csv, ~1503 S&P symbols) and those tags
match.

Output: output/research/sector_restricted_fdr_rescan_summary.parquet,
latest_run_sector_restricted_fdr_rescan.log
"""
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gics import load_gics_tags
from research.fdr_method_comparison import apply_all_methods, KNOWN_NON_DD_PAIRS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_ROOT, "output", "research")
_RAW_PATH = os.path.join(_OUT_DIR, "fdr_method_comparison_raw.parquet")
ALPHA = 0.05

log = logging.getLogger("sector_restricted_fdr_rescan")


def _setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s  %(message)s", datefmt="%H:%M:%S")
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(_ROOT, "latest_run_sector_restricted_fdr_rescan.log"), mode="w", encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def restrict_to_same_sector(df: pd.DataFrame, sector_map: dict) -> pd.DataFrame:
    """
    Pure function -- given the raw candidate-pair DataFrame (symbol_a,
    symbol_b, pvalue, ...) and a {symbol: sector} map, returns only rows
    where both symbols have a known, matching sector. Kept data-loading-free
    so debug/_verify_sector_restricted_fdr_rescan.py can exercise it directly
    on a small constructed DataFrame + sector map.
    """
    sec_a = df["symbol_a"].map(sector_map)
    sec_b = df["symbol_b"].map(sector_map)
    mask = sec_a.notna() & sec_b.notna() & (sec_a == sec_b)
    out = df[mask].copy()
    out["sector"] = sec_a[mask]
    return out


def main():
    _setup_logging()
    log.info("=== sector_restricted_fdr_rescan.py: same-GICS-sector restriction, "
              "reapply 4 FDR methods to the smaller m ===")

    if not os.path.exists(_RAW_PATH):
        log.error("Missing %s -- run research/fdr_method_comparison.py first", _RAW_PATH)
        sys.exit(1)

    raw = pd.read_parquet(_RAW_PATH)
    log.info("Loaded %d candidate pairs from the prior full-universe EG run", len(raw))

    tags = load_gics_tags()
    sector_map = tags.dropna(subset=["sector"]).set_index("symbol")["sector"].to_dict()
    log.info("GICS sector tags loaded for %d symbols", len(sector_map))

    restricted = restrict_to_same_sector(raw, sector_map)
    log.info("Same-sector restriction: %d/%d candidates retained (m: %d -> %d)",
              len(restricted), len(raw), len(raw), len(restricted))

    by_sector = restricted["sector"].value_counts()
    log.info("Same-sector candidate breakdown:\n%s", by_sector.to_string())

    pvals = restricted["pvalue"].to_numpy()
    rejections = apply_all_methods(pvals, ALPHA)
    for method, rej in rejections.items():
        restricted[f"confirmed_{method}"] = rej

    log.info("")
    log.info("=== Survivor counts under same-sector restriction (m=%d, alpha=%.2f) "
              "vs full-universe m=%d ===", len(pvals), ALPHA, len(raw))
    summary_rows = []
    for method, rej in rejections.items():
        n_survive = int(rej.sum())
        log.info("  %-22s: %d/%d survive", method, n_survive, len(pvals))
        summary_rows.append({"method": method, "n_survive": n_survive, "m_tested": len(pvals)})

    log.info("")
    log.info("=== The 8 known non-DD target pairs under this restriction ===")
    for sym_a, sym_b in KNOWN_NON_DD_PAIRS:
        sec_a = sector_map.get(sym_a)
        sec_b = sector_map.get(sym_b)
        same_sector = sec_a is not None and sec_a == sec_b
        if not same_sector:
            log.info("  %-6s/%-6s: CROSS-SECTOR (%s / %s) -- structurally excluded by this rule, "
                     "not testable here", sym_a, sym_b, sec_a, sec_b)
            continue
        mask = ((restricted["symbol_a"] == sym_a) & (restricted["symbol_b"] == sym_b)) | \
               ((restricted["symbol_a"] == sym_b) & (restricted["symbol_b"] == sym_a))
        if not mask.any():
            log.info("  %-6s/%-6s: same-sector (%s) but not found in restricted candidate pool "
                     "(failed Pearson prefilter or EG overlap)", sym_a, sym_b, sec_a)
            continue
        row = restricted[mask].iloc[0]
        status = {m: bool(row[f"confirmed_{m}"]) for m in rejections}
        log.info("  %-6s/%-6s: same-sector (%s), raw_p=%.6e  %s",
                  sym_a, sym_b, sec_a, row["pvalue"], status)

    os.makedirs(_OUT_DIR, exist_ok=True)
    restricted.to_parquet(os.path.join(_OUT_DIR, "sector_restricted_fdr_rescan_raw.parquet"), index=False)
    pd.DataFrame(summary_rows).to_parquet(
        os.path.join(_OUT_DIR, "sector_restricted_fdr_rescan_summary.parquet"), index=False
    )
    log.info("Saved -> output/research/sector_restricted_fdr_rescan_{raw,summary}.parquet")


if __name__ == "__main__":
    main()
