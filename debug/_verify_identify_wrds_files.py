"""
Label-map identity bug (2026-10-12): output/cache/wrds/full_us_market_label_map.parquet maps ADR tickers to a reused
ticker's OLD holder (TM -> Toastmaster 77456, but TM_1D.parquet is Toyota's ADR 1972-2025) because the security
master it was built from has ordinary shares only. research/identify_wrds_files.py re-identifies every CRSP-labelled
file from its content against the FULL names history (crsp.stocknames, every share type). Written failing-first.
Checks on identify(spans, stocknames):
  1. a reused ticker resolves to the holder whose listing span contains the file's first..last dates
  2. a span ending at the names table's last date (2024-12-31) is open through the data end (2025-12-31)
  3. +-10 day tolerance at both ends
  4. no candidate contains the span -> 'unidentified'; two candidates contain it -> 'ambiguous' (never guessed)
  5. a candidate's span is its WHOLE listing life across all its tickers (Toyota traded as TOYOY before TM; the
     TM file starts 1972) -- min(namedt)..max(nameenddt) over every row of that permno
  6. PERMNO<n> labels identify themselves
  7. the candidate must HOLD the ticker on the file's last date (capped at the names table's end): a long-lived
     former holder whose life also contains the span (Barrick for a 2020-2025 ABX file) is not a match
Run: python debug/_verify_identify_wrds_files.py
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        from research.identify_wrds_files import identify
    except ImportError as e:
        check("module_exists", False, e); return finish()
    D = pd.Timestamp
    names = pd.DataFrame([
        # TM: Thompson Medical (old), Toastmaster (old), Toyota ADR (current, open-ended)
        (62754, "TM", D("1980-01-01"), D("1988-11-09")), (77456, "TM", D("1992-01-01"), D("1999-01-07")),
        (76655, "TOYOY", D("1972-12-14"), D("1999-09-28")),   # same security, earlier ticker
        (76655, "TM", D("1999-09-29"), D("2015-06-30")), (76655, "TM", D("2015-07-01"), D("2024-12-31")),
        # XX: two holders whose spans both contain a short file -> ambiguous
        (1, "XX", D("2000-01-01"), D("2010-01-01")), (2, "XX", D("2000-01-01"), D("2010-01-01")),
        (3, "OLD", D("1990-01-01"), D("1995-01-01")),
        # ABX: Barrick used ABX until 2019 then GOLD (life runs on); Abacus Life holds ABX from 2020. A 2020-2025 ABX
        # file is Abacus -- Barrick's whole life also contains the span, so containment alone would misidentify it
        (71298, "ABX", D("1985-02-01"), D("2019-01-01")), (71298, "GOLD", D("2019-01-02"), D("2024-12-31")),
        (19826, "ABX", D("2020-09-14"), D("2024-12-31")),
    ], columns=["permno", "ticker", "namedt", "nameenddt"])
    spans = pd.DataFrame([
        ("TM", D("1972-12-14"), D("2025-12-31")),      # Toyota: earlier ticker TOYOY, beyond the names table's end
        ("TMOLD", D("1992-03-01"), D("1998-12-31")),   # not a ticker in names -> unidentified
        ("XX", D("2003-01-01"), D("2004-01-01")),
        ("OLD", D("1989-12-25"), D("1995-01-08")),     # within +-10 days
        ("PERMNO77456", D("1992-01-02"), D("1999-01-07")),
        ("ABX", D("2020-09-14"), D("2025-12-31")),
    ], columns=["label", "first", "last"])
    r = identify(spans, names, names_end=D("2024-12-31"), data_end=D("2025-12-31")).set_index("label")
    check("reused_ticker_current_holder", r.loc["TM", "permno"] == 76655 and r.loc["TM", "status"] == "identified",
          r.loc["TM"].to_dict())
    check("open_ended_span", r.loc["TM", "status"] == "identified")
    check("tolerance", r.loc["OLD", "permno"] == 3 and r.loc["OLD", "status"] == "identified", r.loc["OLD"].to_dict())
    check("unidentified", r.loc["TMOLD", "status"] == "unidentified" and pd.isna(r.loc["TMOLD", "permno"]))
    check("ambiguous_not_guessed", r.loc["XX", "status"] == "ambiguous" and pd.isna(r.loc["XX", "permno"]))
    check("permno_label_self", r.loc["PERMNO77456", "permno"] == 77456 and r.loc["PERMNO77456", "status"] == "self")
    # renames: TM's two Toyota rows were one candidate (otherwise the 1999-2025 span fits neither row alone)
    check("holder_at_last_date", r.loc["ABX", "permno"] == 19826 and r.loc["ABX", "status"] == "identified",
          r.loc["ABX"].to_dict())
    # return-based resolution (written AFTER the code -- disclosed; the mutation check shows the test can fail)
    from research.identify_wrds_files import return_match_share, pick
    import numpy as np
    idx = pd.bdate_range("2010-01-01", periods=200)
    rng = np.random.default_rng(0)
    true = pd.Series(rng.normal(0, 0.02, 200), index=idx)
    other = pd.Series(rng.normal(0, 0.02, 200), index=idx)
    dates = [idx[30], idx[100], idx[170]]
    s_true, s_other = return_match_share(true, true, dates), return_match_share(true, other, dates)
    check("return_match_true", s_true == 1.0, s_true)
    check("return_match_other", s_other < 0.1, s_other)
    check("return_match_untestable", np.isnan(return_match_share(true, true.iloc[:5], dates)))
    check("pick_one", pick({1: 0.98, 2: 0.05}) == (1, "returns"))
    check("pick_none", pd.isna(pick({1: 0.3, 2: 0.05})[0]) and pick({1: 0.3})[1] == "unresolved_none")
    check("pick_multiple", pick({1: 0.95, 2: 0.97})[1] == "unresolved_multiple")
    check("pick_untestable", pick({1: np.nan})[1] == "unresolved_untestable")
    import research.identify_wrds_files as _m
    _orig = _m.MATCH_SHARE
    _m.MATCH_SHARE = 0.0
    try:
        check("mutation_threshold_caught", pick({1: 0.3, 2: 0.05})[1] != "unresolved_none")
    finally:
        _m.MATCH_SHARE = _orig
    check("renames_merged", r.loc["TM", "n_candidates_containing"] == 1, r.loc["TM", "n_candidates_containing"])
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
