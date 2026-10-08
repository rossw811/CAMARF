"""
Regression test for code review A10 + CLAUDE.md rule 2 (verified 2026-10-07, fixed the same day) in
analysis.AnalysisPipeline._enrich_with_deep_history:
  A10: merged deep-history series were stored per SYMBOL (deep_aligned[sym]), so a leg shared by two pairs (A/B then
       A/C) kept only the LAST pair's overlap; the A/B refit then paired A's A-and-C dates with B's A-and-B dates by
       position (or failed and was skipped silently).
  Rule 2: the enrichment ran by default whenever IBKR supplement files existed and REPLACED production spread series
       with the deep version -- IBKR depth exists only for earlier-confirmed pairs' symbols, so production depth
       depended on earlier results. It is now off unless Config.ANALYSIS.IBKR_DEEP_HISTORY_ENRICH is set (a labelled
       side arm).
Checks (temp cache, load_supplement patched): flag off -> nothing loaded, nothing changed; flag on, A/B (B == A) and
A/C (C overlaps A on the last 300 days only), A/B listed first -> A/B is enriched on its OWN 600-day overlap and its
spread is ~0; A/C on its 300-day overlap.
Run: python debug/_verify_deep_history_enrich.py
"""
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import analysis
    import ibkr_supplement_reader
    from config import Config
    d = tempfile.mkdtemp(prefix="deep_enrich_")
    old_cache, old_sup = Config.DATA.CACHE_DIR, ibkr_supplement_reader.load_supplement
    old_flag = getattr(Config.ANALYSIS, "IBKR_DEEP_HISTORY_ENRICH", "absent")
    try:
        os.makedirs(os.path.join(d, "wrds"))
        idx = pd.bdate_range("2015-01-01", periods=600)
        rng = np.random.default_rng(0)
        a = 50 * np.exp(np.cumsum(rng.normal(0, .01, 600)))
        c = 30 * np.exp(np.cumsum(rng.normal(0, .01, 600)))
        pd.DataFrame({"close": a}, index=idx).to_parquet(os.path.join(d, "wrds", "AAA_1D.parquet"))
        pd.DataFrame({"close": a}, index=idx).to_parquet(os.path.join(d, "wrds", "BBB_1D.parquet"))
        pd.DataFrame({"close": c[300:]}, index=idx[300:]).to_parquet(os.path.join(d, "wrds", "CCC_1D.parquet"))
        calls = []

        def fake_sup(sym, tf):
            calls.append(sym)
            return pd.DataFrame({"close": a[:100]}, index=idx[:100]) if sym == "AAA" else None
        ibkr_supplement_reader.load_supplement = fake_sup
        Config.DATA.CACHE_DIR = d

        def fresh():
            pairs = [SimpleNamespace(symbol_a="AAA", symbol_b="BBB", coint_fraction_rolling_deep=np.nan,
                                     deep_history_used=False),
                     SimpleNamespace(symbol_a="AAA", symbol_b="CCC", coint_fraction_rolling_deep=np.nan,
                                     deep_history_used=False)]
            pb = {("AAA", "BBB"): {"index": idx[:10]}, ("AAA", "CCC"): {"index": idx[:10]}}
            return pairs, pb

        Config.ANALYSIS.IBKR_DEEP_HISTORY_ENRICH = False
        pairs, pb = fresh()
        analysis.AnalysisPipeline._enrich_with_deep_history(pairs, pb, "1D")
        check("flag_off_loads_nothing", calls == [], calls)
        check("flag_off_changes_nothing", all(len(v["index"]) == 10 for v in pb.values())
              and not any(p.deep_history_used for p in pairs))
        Config.ANALYSIS.IBKR_DEEP_HISTORY_ENRICH = True
        pairs, pb = fresh()
        analysis.AnalysisPipeline._enrich_with_deep_history(pairs, pb, "1D")
        ab, ac = pb[("AAA", "BBB")], pb[("AAA", "CCC")]
        check("ab_enriched", pairs[0].deep_history_used and len(ab["index"]) == 600, len(ab["index"]))
        sp = np.asarray(ab.get("spread", []), dtype=float)
        sp = sp[np.isfinite(sp)]
        check("ab_spread_near_zero", sp.size > 0 and np.nanmax(np.abs(sp - np.nanmean(sp))) < 1e-6,
              f"max dev {np.nanmax(np.abs(sp - np.nanmean(sp))) if sp.size else None}")
        check("ac_on_own_overlap", len(ac["index"]) == 300, len(ac["index"]))
    finally:
        Config.DATA.CACHE_DIR = old_cache
        ibkr_supplement_reader.load_supplement = old_sup
        if old_flag == "absent":
            if hasattr(Config.ANALYSIS, "IBKR_DEEP_HISTORY_ENRICH"):
                delattr(Config.ANALYSIS, "IBKR_DEEP_HISTORY_ENRICH")
        else:
            Config.ANALYSIS.IBKR_DEEP_HISTORY_ENRICH = old_flag
        shutil.rmtree(d, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
