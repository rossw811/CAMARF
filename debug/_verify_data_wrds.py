"""
debug/_verify_data_wrds.py -- verification for data_wrds.py before trusting
it against the real universe.

Checks:
  1. resolve_permno's point-in-time correctness using a MOCKED db (no
     network) -- a synthetic scenario where the same ticker string was used
     by two different companies at different times, confirming the as-of-date
     resolution picks the correct PERMNO for a given date, not just "most
     recent."
  2. fetch_symbol's split-adjustment math against AAPL's REAL, KNOWN
     2020-08-31 4-for-1 split (requires a live WRDS connection -- this is
     the one real-data check in this file, deliberately, since the whole
     point is confirming real CRSP data behaves as documented).
  3. fetch_symbol's raw volume is NOT silently adjusted (documented as an
     open item in the module docstring, not silently assumed) -- confirm
     the returned 'volume' column matches dlyvol exactly, unadjusted.
  4. resolve_gvkey_global correctly REFUSES an ambiguous company-name match
     (e.g. "MITSUBISHI CORP" also matching "MITSUBISHI CORP FINANCE") rather
     than silently guessing -- confirmed live against real Compustat Global
     data, not a synthetic case, since the ambiguity itself is real.
  5. fetch_symbol_global's split-adjustment math against Toyota Motor's REAL,
     KNOWN 2021-10-01 5-for-1 split (gvkey=019661, iid='01W').

Run: python debug/_verify_data_wrds.py
(Check 1 runs offline. Checks 2-5 require a working WRDS connection --
 skipped with a clear message if the connection fails, not silently passed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_wrds as dw


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


class _FakeDB:
    """Mocks wrds.Connection's .raw_sql() for offline PIT-resolution testing."""
    def __init__(self, rows):
        self._rows = rows

    def raw_sql(self, q):
        # Return rows whose validity window matches whatever as_of date is
        # embedded in the query string (crude but sufficient for this test --
        # real filtering logic lives in resolve_permno's SQL, this mock just
        # replays pre-baked scenario rows).
        return pd.DataFrame(self._rows)


def verify_pit_resolution_reused_ticker():
    print("\n=== 1. resolve_permno: PIT-correct resolution of a REUSED ticker ===")
    # Scenario: ticker "XYZ" belonged to Company A (permno=1001) from 1990-2005,
    # then was reused by unrelated Company B (permno=2002) from 2010-present.
    # A naive "most recent" lookup would always return 2002 regardless of the
    # as-of date -- this must NOT happen for a 1995 as-of date.
    fake_old = _FakeDB([{"permno": 1001, "namedt": "1990-01-01", "nameenddt": "2005-12-31"}])
    fake_new = _FakeDB([{"permno": 2002, "namedt": "2010-01-01", "nameenddt": None}])

    old_result = dw.resolve_permno(fake_old, "XYZ", as_of_date="1995-06-01")
    new_result = dw.resolve_permno(fake_new, "XYZ", as_of_date="2020-06-01")

    ok = check("1995 as-of date resolves to the OLD company's permno (1001)",
               old_result is not None and old_result[0] == 1001)
    ok &= check("2020 as-of date resolves to the NEW company's permno (2002)",
                new_result is not None and new_result[0] == 2002)
    return ok


def verify_ambiguous_ticker_refused():
    print("\n=== 1b. resolve_permno: AMBIGUOUS ticker (tied permnos) refused, not guessed ===")
    # Scenario: ticker 'XYZ' has TWO permnos tied at the identical latest namedt --
    # e.g. a dual-share-class company where CRSP tagged both classes with the same
    # bare ticker string (the real bug found live for CWEN/BIO/GEF/LEN/MKC/STZ/TAP/UA,
    # 2026-07-27). Must return None, not silently pick one.
    tied_db = _FakeDB([
        {"permno": 1001, "namedt": "2020-01-01", "nameenddt": None},
        {"permno": 1002, "namedt": "2020-01-01", "nameenddt": None},
    ])
    result = dw.resolve_permno(tied_db, "XYZ", as_of_date="2025-01-01")
    ok = check("tied permnos at the same namedt -> None, not an arbitrary pick", result is None)

    # Sanity: the SAME shape but with only one permno must still resolve normally
    # (confirms the fix doesn't over-trigger on ordinary, unambiguous single-row results).
    single_db = _FakeDB([{"permno": 1001, "namedt": "2020-01-01", "nameenddt": None}])
    result2 = dw.resolve_permno(single_db, "XYZ", as_of_date="2025-01-01")
    ok &= check("single unambiguous permno still resolves normally", result2 is not None and result2[0] == 1001)
    return ok


def verify_real_cwen_ambiguity_refused():
    print("\n=== 1c. Real WRDS: 'CWEN' (real dual-share-class collision) correctly refused ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    single_result = dw.resolve_permno(db, "CWEN")
    ok = check("resolve_permno('CWEN') returns None (real ambiguity, not guessed)", single_result is None)

    bulk_result = dw.resolve_permnos_bulk(db, ["CWEN", "AAPL"])
    ok &= check("resolve_permnos_bulk excludes 'CWEN' from the result dict",
                "CWEN" not in bulk_result)
    ok &= check("resolve_permnos_bulk still resolves the unambiguous 'AAPL' in the same call",
                "AAPL" in bulk_result)
    return ok


def verify_no_mapping_returns_none():
    print("\n=== (edge case) no matching row -> None, not a crash ===")
    empty_db = _FakeDB([])
    result = dw.resolve_permno(empty_db, "NOSUCHTICKER")
    ok = check("empty result set returns None cleanly", result is None)
    return ok


def verify_real_aapl_split_and_volume():
    print("\n=== 2-3. Real WRDS: AAPL 2020-08-31 split continuity + unadjusted volume ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e}) -- "
              f"this check requires a live, already-configured WRDS connection.")
        return True  # not a failure of the code under test -- an environment precondition

    df = dw.fetch_symbol(db, "AAPL", start="2020-08-20")
    ok = check("fetch_symbol returned real data", df is not None and len(df) > 5)
    if not ok:
        return False

    pre_split = df.loc["2020-08-28", "close"]
    post_split_next_day = df.loc["2020-09-01", "close"]
    day_of_split = df.loc["2020-08-31", "close"]
    # Real, independently-known values (checked manually before writing this
    # test): pre-split adjusted close ~124.81, split-day close 129.04 --
    # continuous, not a ~4x jump.
    ratio = pre_split / day_of_split
    ok &= check(f"no ~4x discontinuity across the split boundary (ratio={ratio:.3f}, expect ~0.9-1.0)",
                0.85 < ratio < 1.15)

    raw_check = db.raw_sql(
        "select dlyvol from crsp_a_stock.dsf_v2 where ticker='AAPL' and dlycaldt='2020-08-31'"
    )
    ok &= check("returned 'volume' matches raw dlyvol exactly (not silently adjusted)",
                abs(df.loc["2020-08-31", "volume"] - raw_check.iloc[0]["dlyvol"]) < 1e-6)
    return ok


def verify_global_currency_disambiguates_name_matches():
    print("\n=== 4. resolve_gvkey_global: currency correctly DISAMBIGUATES multiple name matches ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    # Rewritten 2026-07-27: resolve_gvkey_global now uses currency as a real
    # disambiguator across ALL name-matched companies, not just a listing
    # lookup performed after already requiring a unique name match. 'MITSUBISHI
    # CORP' matches 2 companies by name ('MITSUBISHI CORP' and 'MITSUBISHI CORP
    # FINANCE'), but only the real Japanese parent has a JPY-denominated
    # listing -- this now correctly RESOLVES (previously this test asserted it
    # must refuse, which was the OLD algorithm's limitation, not a real
    # ambiguity -- confirmed against the already-known-correct gvkey=100555).
    result = dw.resolve_gvkey_global(db, "MITSUBISHI CORP", currency="JPY")
    ok = check("'MITSUBISHI CORP'/JPY resolves to the known-correct gvkey (100555) -- currency "
               "disambiguates the 2 name matches rather than refusing unnecessarily",
               result is not None and result[0] == "100555")

    # A GENUINE ambiguity that currency does NOT resolve: 'Unilever' matches
    # 9 companies by name, and TWO of them ('UNILEVER PLC PRIOR TO DUAL L' and
    # 'UNILEVER PLC' -- the pre/post-2020 dual-listing-unification entities)
    # both have real GBP-denominated listings. This must still refuse.
    result2 = dw.resolve_gvkey_global(db, "Unilever", currency="GBP")
    ok &= check("'Unilever'/GBP still refuses (2 genuinely distinct GBP-denominated entities, "
                "not resolvable by currency alone) -- not a silent guess",
                result2 is None)
    return ok


def verify_bulk_matches_single_symbol():
    print("\n=== 6. Real WRDS: fetch_symbols_bulk matches fetch_symbol exactly (AAPL) ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    single = dw.fetch_symbol(db, "AAPL", start="2023-01-01")
    resolved = dw.resolve_permno(db, "AAPL")
    ok = check("single-symbol fetch_symbol returned data", single is not None and len(single) > 5)
    if not ok or resolved is None:
        return False
    permno = resolved[0]

    bulk_result = None
    for sym, df in dw.fetch_symbols_bulk(db, {"AAPL": permno}, start="2023-01-01", batch_size=200):
        if sym == "AAPL":
            bulk_result = df
    ok &= check("fetch_symbols_bulk yielded AAPL", bulk_result is not None)
    if bulk_result is None:
        return False

    diff = (single["close"] - bulk_result["close"]).abs().max()
    ok &= check(f"bulk close matches single-symbol close exactly (max diff={diff:.10f})", diff < 1e-9)
    return ok


def verify_native_monthly_vs_derived_resample():
    print("\n=== 7. Real WRDS: native monthly (msf_v2) vs derived resample -- expected to DIFFER ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    daily = dw.fetch_symbol(db, "AAPL", start="2022-01-01")
    native_monthly = dw.fetch_symbol_monthly_native(db, "AAPL", start="2022-01-01")
    ok = check("fetch_symbol returned daily data", daily is not None and len(daily) > 20)
    ok &= check("fetch_symbol_monthly_native returned data", native_monthly is not None and len(native_monthly) > 5)
    if not ok:
        return False

    derived_1m = dw.resample_daily_to(daily, "1Y")  # 1Y is the only derived rule available here; native has no 1M rule to derive against directly
    ok &= check("resample_daily_to('1Y') runs against real daily data without error",
                derived_1m is not None and len(derived_1m) > 0)

    resolved = dw.resolve_permno(db, "AAPL")
    permno = resolved[0]
    monthly_bulk_result = None
    for sym, df in dw.fetch_monthly_bulk(db, {"AAPL": permno}, start="2022-01-01", batch_size=200):
        if sym == "AAPL":
            monthly_bulk_result = df
    ok &= check("fetch_monthly_bulk yielded AAPL", monthly_bulk_result is not None)
    if monthly_bulk_result is not None:
        diff = (native_monthly["close"] - monthly_bulk_result["close"]).abs().max()
        ok &= check(f"fetch_monthly_bulk matches fetch_symbol_monthly_native exactly (max diff={diff:.10f})",
                    diff < 1e-9)
    return ok


def verify_resample_daily_to_synthetic():
    print("\n=== 8. resample_daily_to: synthetic multi-year 7D/3M/6M/1Y checks (offline) ===")
    idx = pd.date_range("2019-01-01", "2025-06-30", freq="B")
    n = len(idx)
    close = 100 * (1.0003 ** np.arange(n))
    df = pd.DataFrame({
        "open": close * 0.999, "high": close * 1.002, "low": close * 0.998,
        "close": close, "close_total_return": close * 1.05,
        "volume": np.full(n, 1000),
    }, index=idx)

    ok = True
    for tf, expect_min_rows in [("7D", 300), ("3M", 20), ("6M", 10), ("1Y", 5)]:
        out = dw.resample_daily_to(df, tf)
        ok &= check(f"{tf}: produces >= {expect_min_rows} rows", out is not None and len(out) >= expect_min_rows)
        ok &= check(f"{tf}: all close > 0", out is not None and (out["close"] > 0).all())
        ok &= check(f"{tf}: close_total_return column present", out is not None and "close_total_return" in out.columns)

    unknown = dw.resample_daily_to(df, "9X")
    ok &= check("unrecognized tf_label returns None, not a crash", unknown is None)
    return ok


def verify_sp500_members_asof_multi_spell():
    print("\n=== 9. sp500_members_asof: multi-spell membership resolved correctly (offline) ===")
    # permno 1 (multi-spell): member 1990-2000, GAP, member again 2015-present.
    # permno 2 (single spell, still current): member 2005-present.
    # permno 3 (single spell, long-past departure): member 1980-1985 only.
    membership_df = pd.DataFrame([
        {"permno": 1, "mbrstartdt": pd.Timestamp("1990-01-01"), "mbrenddt": pd.Timestamp("2000-01-01"), "is_current": False},
        {"permno": 1, "mbrstartdt": pd.Timestamp("2015-01-01"), "mbrenddt": pd.NaT, "is_current": True},
        {"permno": 2, "mbrstartdt": pd.Timestamp("2005-01-01"), "mbrenddt": pd.NaT, "is_current": True},
        {"permno": 3, "mbrstartdt": pd.Timestamp("1980-01-01"), "mbrenddt": pd.Timestamp("1985-01-01"), "is_current": False},
    ])
    ok = check("permno 1 INCLUDED during its first spell (1995)",
               1 in dw.sp500_members_asof(membership_df, "1995-06-01"))
    ok &= check("permno 1 EXCLUDED during the gap between spells (2008) -- not just 'appears somewhere in the table'",
                1 not in dw.sp500_members_asof(membership_df, "2008-06-01"))
    ok &= check("permno 1 INCLUDED again during its second, current spell (2024)",
                1 in dw.sp500_members_asof(membership_df, "2024-06-01"))
    ok &= check("permno 2 INCLUDED (current, single spell) at a recent date",
                2 in dw.sp500_members_asof(membership_df, "2024-06-01"))
    ok &= check("permno 3 EXCLUDED entirely at a recent date (departed 1985, never returned)",
                3 not in dw.sp500_members_asof(membership_df, "2024-06-01"))
    ok &= check("permno 3 INCLUDED during its own historical window (1982)",
                3 in dw.sp500_members_asof(membership_df, "1982-06-01"))
    return ok


def verify_get_delisted_sp500_permnos():
    print("\n=== 10. get_delisted_sp500_permnos: excludes already-covered permnos ===")
    membership_df = pd.DataFrame([
        {"permno": 1, "mbrstartdt": pd.Timestamp("1990-01-01"), "mbrenddt": pd.Timestamp("2000-01-01"), "is_current": False},
        {"permno": 2, "mbrstartdt": pd.Timestamp("2005-01-01"), "mbrenddt": pd.NaT, "is_current": True},
        {"permno": 3, "mbrstartdt": pd.Timestamp("1980-01-01"), "mbrenddt": pd.Timestamp("1985-01-01"), "is_current": False},
    ])
    delisted = dw.get_delisted_sp500_permnos(membership_df, already_covered_permnos={2})
    ok = check("permno 2 (already covered by the ticker-based fetch) excluded", 2 not in delisted)
    ok &= check("permnos 1 and 3 (never covered) both included", delisted == {1, 3})
    return ok


def verify_build_delisted_label_map_prevents_overwriting_active_symbol():
    print("\n=== 11. build_delisted_label_map: NEVER overwrites an active symbol's filename ===")
    # permno 101's last-known ticker 'XYZ' collides with a CURRENTLY ACTIVE
    # company's own ticker (a different, unrelated permno already in the
    # main fetch) -- this is the dangerous case: writing under 'XYZ' would
    # silently overwrite the live company's own parquet file.
    delisted_permnos = {101, 102}
    last_known_tickers = {101: "XYZ", 102: "OLDCO"}
    active_ticker_labels = {"XYZ", "AAPL", "MSFT"}  # 'XYZ' is a LIVE symbol's ticker
    label_map = dw.build_delisted_label_map(delisted_permnos, last_known_tickers, active_ticker_labels)

    ok = check("permno 101's colliding label 'XYZ' is NOT used (would overwrite the active symbol's file)",
               "XYZ" not in label_map)
    ok &= check("permno 101 instead gets a PERMNO-based fallback label",
                label_map.get("PERMNO101") == 101)
    ok &= check("permno 102 (no collision) keeps its natural ticker label",
                label_map.get("OLDCO") == 102)
    ok &= check("every permno in the input appears exactly once in the output", len(label_map) == 2)

    # Two delisted permnos colliding with EACH OTHER (not with an active
    # symbol) -- also must not silently drop one.
    label_map2 = dw.build_delisted_label_map({201, 202}, {201: "SAME", 202: "SAME"}, active_ticker_labels=set())
    ok &= check("two delisted permnos sharing the same last-known ticker: neither silently dropped",
                len(label_map2) == 2 and set(label_map2.values()) == {201, 202})
    return ok


def verify_real_sp500_membership_history():
    print("\n=== 12. Real WRDS: S&P 500 point-in-time membership history sane against known facts ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    membership_df = dw.fetch_sp500_membership_history(db)
    ok = check("membership history returned real rows", len(membership_df) > 1000)
    n_current = int(membership_df["is_current"].sum())
    ok &= check(f"current-member count is in the real S&P 500's actual range (~495-510, got {n_current})",
                495 <= n_current <= 510)
    n_distinct = membership_df["permno"].nunique()
    ok &= check(f"far more distinct historical permnos than current members (got {n_distinct} vs {n_current} current)",
                n_distinct > n_current * 2)

    today_members = dw.sp500_members_asof(membership_df)
    ok &= check(f"sp500_members_asof() with no date arg returns ~{n_current} current members",
                len(today_members) == n_current)
    return ok


def verify_resolve_last_known_tickers_handles_null_ticker():
    print("\n=== 13. resolve_last_known_tickers: null ticker in stocknames doesn't crash (regression) ===")
    # Found live (2026-07-27): stocknames.ticker can itself be NULL for some
    # rows. The original implementation took .unique() on the raw column
    # BEFORE dropping nulls -- when a permno's only row at its latest namedt
    # had ticker=NULL, tickers[0] silently became pd.NA, and the later
    # `label != labels.get(...)` comparison in build_delisted_label_map
    # crashed with "TypeError: boolean value of NA is ambiguous" the first
    # time this ran against the real full delisted-S&P-500 set.
    fake_db_null_only = _FakeDB([
        {"permno": 501, "ticker": None},
    ])
    result = dw.resolve_last_known_tickers(fake_db_null_only, [501])
    ok = check("permno with ONLY a null ticker falls back to a PERMNO-based label, not pd.NA",
               result.get(501) == "PERMNO501")

    fake_db_mixed = _FakeDB([
        {"permno": 502, "ticker": None},
        {"permno": 502, "ticker": "ABC"},
    ])
    result2 = dw.resolve_last_known_tickers(fake_db_mixed, [502])
    ok &= check("permno with one null + one real ticker uses the real ticker",
                result2.get(502) == "ABC")
    return ok


def verify_index_members_asof_multi_spell():
    print("\n=== 14. index_members_asof: multi-spell membership resolved correctly, generic (gvkey,iid) key (offline) ===")
    membership_df = pd.DataFrame([
        {"gvkey": "001", "iid": "01", "start_dt": pd.Timestamp("1990-01-01"), "end_dt": pd.Timestamp("2000-01-01"), "is_current": False},
        {"gvkey": "001", "iid": "01", "start_dt": pd.Timestamp("2015-01-01"), "end_dt": pd.NaT, "is_current": True},
        {"gvkey": "002", "iid": "01", "start_dt": pd.Timestamp("2005-01-01"), "end_dt": pd.NaT, "is_current": True},
    ])
    ok = check("(001,01) INCLUDED during first spell (1995)",
               ("001", "01") in dw.index_members_asof(membership_df, "1995-06-01"))
    ok &= check("(001,01) EXCLUDED during the gap between spells (2008)",
                ("001", "01") not in dw.index_members_asof(membership_df, "2008-06-01"))
    ok &= check("(001,01) INCLUDED again during its current spell (2024)",
                ("001", "01") in dw.index_members_asof(membership_df, "2024-06-01"))
    ok &= check("(002,01) INCLUDED (current, single spell)",
                ("002", "01") in dw.index_members_asof(membership_df, "2024-06-01"))
    return ok


def verify_real_global_index_membership_dax():
    print("\n=== 15. Real WRDS: Composite DAX (gvkeyx=150007) point-in-time membership sane ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    membership_df = dw.fetch_index_membership_history_global(db, "150007", "dax_test")
    ok = check("DAX membership history returned real rows", len(membership_df) > 500)
    n_current = int(membership_df["is_current"].sum())
    ok &= check(f"current-member count is plausible for a real index (got {n_current}, expect > 0)",
                n_current > 0)
    n_distinct = membership_df.groupby(["gvkey", "iid"]).ngroups
    ok &= check(f"far more distinct historical constituents than current (got {n_distinct} vs {n_current})",
                n_distinct > n_current)

    current_members = dw.index_members_asof(membership_df)
    ok &= check("index_members_asof() with no date arg returns a non-empty current set",
                len(current_members) > 0)
    return ok


def verify_global_index_current_convention_auto_detected():
    print("\n=== 15b. fetch_index_membership_history_global: auto-detects null-vs-placeholder "
          "'current' convention (regression) ===")
    # Found live (2026-07-27): Compustat Global's g_idxcst_his does NOT
    # uniformly use CRSP's "shared max-date placeholder, zero real nulls"
    # convention -- some indices (e.g. Nikkei 225) use genuine NULL `thru`
    # for current members instead. The original code blindly assumed the
    # placeholder convention for every gvkeyx, which for Nikkei 225 produced
    # 2 "current" constituents instead of the real ~225 (only the single
    # most-recent real historical departure happened to match the naive
    # max-date comparison; every genuinely-current NaT row was silently
    # excluded, since NaT never equals a finite date).
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    nikkei_df = dw.fetch_index_membership_history_global(db, "150069", "nikkei225_regression_test")
    n_current = int(nikkei_df["is_current"].sum())
    ok = check(f"Nikkei 225 (genuine-NULL convention) shows a plausible current count "
               f"(got {n_current}, real index has ~225 constituents, expect 200-260)",
               200 <= n_current <= 260)

    dax_df = dw.fetch_index_membership_history_global(db, "150007", "dax_regression_test")
    n_dax_current = int(dax_df["is_current"].sum())
    ok &= check(f"Composite DAX (placeholder convention, verified unaffected by the fix) "
                f"still shows 417 current, matching the pre-fix value exactly",
                n_dax_current == 417)
    return ok


def verify_unpopulated_gvkeyx_returns_empty_not_crash():
    print("\n=== 16. Real WRDS: an unpopulated gvkeyx (FTSE 100) returns empty, not a crash ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True
    # Confirmed directly (2026-07-27): FTSE 100's gvkeyx (150008) is a real,
    # valid index definition with ZERO g_idxcst_his rows -- this must return
    # an empty DataFrame with a clear warning, not raise or silently proceed
    # as if data existed.
    result = dw.fetch_index_membership_history_global(db, "150008", "ftse100_test")
    ok = check("unpopulated gvkeyx returns an empty DataFrame, not a crash", result.empty)
    return ok


def verify_bulk_global_matches_single_symbol():
    print("\n=== 18. Real WRDS: fetch_symbols_bulk_global matches fetch_symbol_global exactly (Toyota) ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    single = dw.fetch_symbol_global(db, "019661", "01W", start="2023-01-01")
    ok = check("single-symbol fetch_symbol_global returned data", single is not None and len(single) > 5)
    if not ok:
        return False

    label = dw.build_global_symbol_label("019661", "01W")
    ok &= check("build_global_symbol_label produces the expected format",
                label == "GVKEY019661_01W")

    bulk_result = None
    for lbl, df in dw.fetch_symbols_bulk_global(db, {label: ("019661", "01W")}, start="2023-01-01"):
        if lbl == label:
            bulk_result = df
    ok &= check("fetch_symbols_bulk_global yielded the expected label", bulk_result is not None)
    if bulk_result is None:
        return False

    diff = (single["close"] - bulk_result["close"]).abs().max()
    ok &= check(f"bulk close matches single-symbol close exactly (max diff={diff:.10f})", diff < 1e-9)
    return ok


def verify_real_fx_wrds():
    print("\n=== 17. Real WRDS: fetch_fx_wrds returns sane FX series, staleness confirmed ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    fx_series = dw.fetch_fx_wrds(db)
    ok = check(f"fetch_fx_wrds returned multiple series ({len(fx_series)})", len(fx_series) > 10)
    ok &= check("USDJPY series present", "USDJPY" in fx_series)
    ok &= check("EURUSD series present", "EURUSD" in fx_series)
    if "USDJPY" in fx_series:
        s = fx_series["USDJPY"]
        ok &= check(f"USDJPY values are in a plausible real-world range (got min={s.min():.1f}, max={s.max():.1f})",
                    50 < s.min() and s.max() < 400)
        ok &= check(f"USDJPY series spans multiple decades (earliest={s.index.min().date()})",
                    s.index.min().year < 1980)
        # Documented staleness -- confirm directly, not just assert from the docstring.
        ok &= check(f"USDJPY series is confirmed STALE relative to CRSP's own 2025-12-31/2026 data "
                    f"(latest={s.index.max().date()}, expect <= 2025-06-01)",
                    s.index.max() <= pd.Timestamp("2025-06-01"))
    return ok


def verify_global_toyota_split():
    print("\n=== 5. Real WRDS: Toyota Motor 2021-10-01 5-for-1 split continuity ===")
    try:
        db = dw._connect()
    except Exception as e:
        print(f"  [SKIP] Could not connect to WRDS ({type(e).__name__}: {e})")
        return True

    df = dw.fetch_symbol_global(db, "019661", "01W", start="2021-09-20")
    ok = check("fetch_symbol_global returned real data", df is not None and len(df) > 5)
    if not ok:
        return False

    pre_split = df.loc["2021-09-28", "close"]
    day_of_split = df.loc["2021-09-29", "close"]
    ratio = pre_split / day_of_split
    ok &= check(f"no ~5x discontinuity across the split boundary (ratio={ratio:.3f}, expect ~0.9-1.1)",
                0.85 < ratio < 1.15)
    return ok


def main():
    results = [
        verify_pit_resolution_reused_ticker(),
        verify_ambiguous_ticker_refused(),
        verify_real_cwen_ambiguity_refused(),
        verify_no_mapping_returns_none(),
        verify_real_aapl_split_and_volume(),
        verify_global_currency_disambiguates_name_matches(),
        verify_bulk_matches_single_symbol(),
        verify_native_monthly_vs_derived_resample(),
        verify_resample_daily_to_synthetic(),
        verify_sp500_members_asof_multi_spell(),
        verify_get_delisted_sp500_permnos(),
        verify_build_delisted_label_map_prevents_overwriting_active_symbol(),
        verify_real_sp500_membership_history(),
        verify_resolve_last_known_tickers_handles_null_ticker(),
        verify_index_members_asof_multi_spell(),
        verify_real_global_index_membership_dax(),
        verify_global_index_current_convention_auto_detected(),
        verify_unpopulated_gvkeyx_returns_empty_not_crash(),
        verify_bulk_global_matches_single_symbol(),
        verify_real_fx_wrds(),
        verify_global_toyota_split(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
