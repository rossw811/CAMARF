"""
Sealed holdout at the data layer (DECISIONS_2026-10-21 #2). Before this, the seal was a filter in seven research
scripts; every other reader of the price caches saw 2026 data. Checks, on temp cache/vault directories:
  1. kind_of_path: intraday vs daily per source naming, case-sensitive (Binance 1m minute vs WRDS 1M month), _deep
  2. split: daily seals at SEALED_FROM, intraday at SEALED_FROM_INTRADAY; tz-aware index handled
  3. write_parquet: open rows to the cache, sealed rows merged into the vault (second write appends, no duplicates)
  4. sweep moves sealed rows already in the cache and is idempotent; audit counts 0 afterwards (and >0 before)
  5. data.DataStore.save routes through the seal; needs_refresh sees vault bars (no endless re-fetch)
  6. universe_loader._read_one and ibkr_supplement_reader.load_supplement drop sealed rows (readers' backstop)
  7. read_full returns cache + vault
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


from config import Config  # noqa: E402
try:
    import seal  # noqa: E402
except ImportError as e:
    check("seal module exists", False, str(e))
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

D = pd.Timestamp(Config.DATA.SEALED_FROM)
I = pd.Timestamp(Config.DATA.SEALED_FROM_INTRADAY)


def frame(idx):
    return pd.DataFrame({"close": np.arange(1.0, len(idx) + 1), "volume": 1.0}, index=pd.DatetimeIndex(idx))


# 1
cases = {"AAPL_1day.parquet": "daily", "AAPL_1hr.parquet": "intraday", "wrds/AAPL_1D.parquet": "daily",
         "wrds/GVKEY1_01W_1M.parquet": "daily", "binance/ADA_1m.parquet": "intraday", "binance/ADA_1d.parquet": "daily",
         "ibkr_supplement/ACAD_15min_deep.parquet": "intraday", "ibkr_supplement/7267.T_1day_deep.parquet": "daily",
         "AAPL_3mo.parquet": "daily", "binance/ADA_3m.parquet": "intraday", "AAPL_meta.parquet": None,
         "wrds/full_us_market_label_map.parquet": None,
         # review F7/F8: macro caches (DataStore keys "daily"/"weekly") and DataStore's 1Y name are sealed too
         "fred_BAA10Y_daily.parquet": "daily", "cot_es_weekly.parquet": "daily", "AAPL_1yr.parquet": "daily",
         "yf_period_0700.HK_1h_meta.parquet": None, "wrds/index_membership_DAX_recheck.parquet": None}
bad = {k: (seal.kind_of_path(k), v) for k, v in cases.items() if seal.kind_of_path(k) != v}
check("1 kind_of_path per source naming", not bad, str(bad))

# 2
daily = frame(["2025-12-30", "2025-12-31", "2026-01-02"])
o, s = seal.split(daily, "daily")
check("2a daily seals at SEALED_FROM", len(o) == 2 and len(s) == 1 and s.index[0] >= D)
intr = frame([I - pd.Timedelta(hours=1), I + pd.Timedelta(hours=1), pd.Timestamp("2026-03-02 10:00")])
o, s = seal.split(intr, "intraday")
check("2b intraday seals at SEALED_FROM_INTRADAY (2026-03 bar stays open)", len(o) == 2 and len(s) == 1)
tz = frame(pd.DatetimeIndex([I - pd.Timedelta(hours=3), I + pd.Timedelta(hours=3)]).tz_localize("UTC"))
o, s = seal.split(tz, "intraday")
check("2c tz-aware index", len(o) == 1 and len(s) == 1)

with tempfile.TemporaryDirectory() as td:
    old_cache = Config.DATA.CACHE_DIR
    Config.DATA.CACHE_DIR = os.path.join(td, "cache")   # the vault lives inside it (seal.vault_root)
    try:
        os.makedirs(os.path.join(Config.DATA.CACHE_DIR, "wrds"))
        # 3
        p = os.path.join(Config.DATA.CACHE_DIR, "wrds", "X_1D.parquet")
        n_open, n_sealed = seal.write_parquet(daily, p)
        vp = seal.vault_path(p)
        check("3a write_parquet split", (n_open, n_sealed) == (2, 1) and pd.read_parquet(p).index.max() < D
              and len(pd.read_parquet(vp)) == 1)
        seal.write_parquet(frame(["2025-12-31", "2026-01-02", "2026-01-05"]), p)
        v = pd.read_parquet(vp)
        check("3b second write merges the vault without duplicates", len(v) == 2 and v.index.is_unique, str(list(v.index)))

        # 4
        q = os.path.join(Config.DATA.CACHE_DIR, "Y_1hr.parquet")
        intr.to_parquet(q)          # a writer that bypassed the seal
        pre = seal.audit()
        r1 = seal.sweep()
        r2 = seal.sweep()
        post = seal.audit()
        check("4a audit sees the bypassing writer", pre["intraday"] == 1 and pre["daily"] == 0, str(pre))
        check("4b sweep moves it; second sweep is a no-op; audit 0",
              r1["rows_moved"] == 1 and r2["rows_moved"] == 0 and post["intraday"] == 0 and post["daily"] == 0,
              f"{r1} {r2} {post}")

        # 5
        import data  # noqa: E402
        data.DataStore.save("Z", "1D", daily)
        zp = data.DataStore._path("Z", "1D")
        zc = pd.read_parquet(zp)
        check("5a DataStore.save keeps sealed rows out of the cache",
              zc.index.max() < D and os.path.exists(seal.vault_path(zp)), str(zc.index.max()))
        import datetime as _dt
        if _dt.date.today() - pd.Timestamp("2026-01-02").date() > _dt.timedelta(days=2):
            # the vault's last bar (2026-01-02) is itself old, so this case can only check that the vault is consulted
            vlast = seal.last_bar_including_vault(zp)
            check("5b staleness sees the vault's last bar", vlast == pd.Timestamp("2026-01-02"), str(vlast))
        # a vault bar dated today means fresh
        data.DataStore.save("W", "1D", frame(["2025-12-31", pd.Timestamp(_dt.date.today())]))
        check("5c needs_refresh false when the vault holds today's bar", not data.DataStore.needs_refresh("W", "1D"))

        # 6
        import universe_loader as ul  # noqa: E402
        p6 = os.path.join(Config.DATA.CACHE_DIR, "wrds", "R_1D.parquet")
        daily.to_parquet(p6)        # bypassing writer again
        _, got = ul._read_one(os.path.join(Config.DATA.CACHE_DIR, "wrds"), "R_1D.parquet", "R")
        check("6a universe_loader._read_one drops sealed rows", got is not None and got.index.max() < D,
              str(None if got is None else got.index.max()))
        import ibkr_supplement_reader as ibr  # noqa: E402
        old_supp = ibr.SUPPLEMENT_DIR
        ibr.SUPPLEMENT_DIR = os.path.join(Config.DATA.CACHE_DIR, "ibkr_supplement")   # never the real cache
        sp = ibr.supplement_path("S", "1h")
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        intr.to_parquet(sp)
        got = ibr.load_supplement("S", "1h")
        ibr.SUPPLEMENT_DIR = old_supp
        check("6b ibkr load_supplement drops sealed rows", got is not None and len(got) == 2, str(None if got is None else len(got)))

        check("3c the vault lives inside the (redirected) cache dir",
              os.path.commonpath([vp, Config.DATA.CACHE_DIR]) == Config.DATA.CACHE_DIR and seal.VAULT_SUBDIR in vp)

        # 8. macro feeds: a fresh FRED / COT fetch is returned without sealed rows (it fed regime labels in memory)
        import macro  # noqa: E402
        fr = pd.DataFrame({"BAA10Y": [1.0, 2.0]}, index=pd.to_datetime(["2025-12-30", "2026-03-02"]))
        orig_fetch = macro.FREDFeed._fetch_with_retry
        macro.FREDFeed._fetch_with_retry = staticmethod(lambda sid, summary=None: fr)
        macro.FREDFeed._SESSION_CACHE.clear()
        try:
            got = macro.FREDFeed.get_series("BAA10Y", force_refresh=True)
        finally:
            macro.FREDFeed._fetch_with_retry = orig_fetch
        check("8 macro FRED fetch returned without sealed rows", got is not None and got.index.max() < D,
              str(None if got is None else got.index.max()))
        # 8b. macro.build's calendar ends before the seal (else every sealed day reads as stale: CPI 192 days, chain
        # suite 2026-10-21)
        ok8b = hasattr(macro, "_sealed_end_date") and pd.Timestamp(macro._sealed_end_date(None)) < D             and pd.Timestamp(macro._sealed_end_date("2026-06-30")) < D             and macro._sealed_end_date("2020-06-30") == "2020-06-30"
        check("8b macro.build end date capped before the seal", ok8b)

        # 7
        full = seal.read_full(p)
        # writers REPLACE the cache file (as to_parquet did): the second write left 2025-12-31 open, 2 rows sealed
        check("7 read_full = cache + vault", len(full) == 3 and full.index.is_unique, str(len(full)))
    finally:
        Config.DATA.CACHE_DIR = old_cache

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
