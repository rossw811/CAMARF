"""
research/promote_full_universe_pairs.py -- promotes research/full_universe_
eg_confirmation.py's candidate-list output (correlation+EG p-values only, 19
columns) into the PRODUCTION output/results/{tf_dir}/pairs.parquet manifest
(41 columns: full per-bar spread model, hedge ratios, half-life, Hurst,
rolling coint fraction) that research/pair_source.py and everything
downstream of it (backtest.py, every fixed research/*.py script this
session) actually reads. Ross's direct request 2026-08-24, after
full_universe_eg_confirmation.py found 78 confirmed pairs that were sitting
in a separate research/ output file, invisible to production.

Method, reusing production code directly, not reimplemented:
  1. Load the candidate (symbol_a, symbol_b) list from the source file.
  2. Load + align ONLY the symbols these candidates actually need (cheap --
     a couple hundred symbols, not the full ~44k-symbol universe
     full_universe_eg_confirmation.py had to align).
  3. Re-run CointScanner.scan() (the SAME both-direction EG + BH-FDR test)
     restricted to just this candidate list -- cheap at this scale (seconds,
     not the 46 minutes the full ~1M-candidate run took), and GUARANTEES the
     confirmed-pair dict schema exactly matches what
     AnalysisPipeline._build_pair_result() expects, rather than hand-
     reconstructing it from the source file's 19 columns (which would risk
     a subtle field-name mismatch).
  4. CointScanner.rolling_fraction() -- same production step 5.
  5. AnalysisPipeline._build_pair_result() per pair -- same production step 6
     (hedge ratios, spread model, half-life, Hurst, decay tests).
  6. MERGE into output/results/{tf_dir}/pairs.parquet: existing rows for any
     pair already present are KEPT UNCHANGED (already production-validated
     via the normal path); only genuinely new pairs are appended. Written
     atomically (temp file + os.replace) so a concurrent reader (e.g. the
     overnight orchestrator, still mid-run) never sees a partial file.
  7. New spread_series_{a}_{b}.parquet written for each newly-added pair
     only, same schema analysis.py's own _save_tf_results uses -- existing
     spread_series files for already-present pairs are never touched.

HONEST LIMITATIONS, disclosed not hidden:
  - DOES re-apply filter_exact_correlation_duplicates + filter_structural_pairs (found live in
    this script's own first dry run: ~40% of the source file's 66-pair local sample were
    same-company duplicate listings under different GVKEYs, or share-class pairs like WLY/WLYB --
    exactly the contamination full_universe_eg_confirmation.py's driver never filters). Does NOT
    re-apply the coint_frac rolling-significance threshold analysis.py's normal pipeline applies
    later (a quality/inclusion-looseness choice, not an identity-correctness bug the way the
    structural-pair gap was) -- a pair that would have been excluded by that later threshold
    stays in the promoted set here, disclosed via the dry-run diff, not silently dropped or kept.
  - No episodic/deep-history re-test (AnalysisPipeline._enrich_with_deep_history)
    -- same PIT/non-episodic caveat every other full-history-confirmed pair
    in this project already carries (see FINDINGS.md's retroactive
    disclosure entry).

Usage:
    python research/promote_full_universe_pairs.py --tf 1D
    python research/promote_full_universe_pairs.py --tf 1D --dry-run
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import Config
from analysis import CointScanner, AnalysisPipeline
from universe_loader import (
    align_to_common_calendar, load_full_universe,
    filter_exact_correlation_duplicates, filter_structural_pairs,
)
from data import DataStore
from dataclasses import asdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SOURCE_PATH = os.path.join(_ROOT, "output", "research", "full_universe_eg_confirmed_pairs_10y.parquet")


def main():
    p = argparse.ArgumentParser(description="Promote full_universe_eg_confirmation.py's candidate "
                                             "list into production output/results/{tf_dir}/pairs.parquet")
    p.add_argument("--tf", default="1D", help="tf_label -- must match the source file's own timeframe.")
    p.add_argument("--source", default=_SOURCE_PATH)
    p.add_argument("--dry-run", action="store_true",
                    help="Run the full pipeline and report what WOULD be promoted, without writing.")
    p.add_argument("--skip-wrds-check", action="store_true",
                    help="Skip the ticker<->PERMNO duplicate-identity check entirely (no WRDS "
                         "connection, no --alias-file). NOT recommended -- the promoted set may "
                         "then contain alias duplicates/self-pairs.")
    p.add_argument("--alias-file", default=None,
                    help="Path to a precomputed {PERMNO<n>: ticker} JSON alias map (from "
                         "data_wrds.resolve_permnos_bulk run on a machine WITH working WRDS "
                         "credentials) -- lets a machine WITHOUT WRDS access still apply the "
                         "ticker<->PERMNO duplicate-identity check without a live query.")
    p.add_argument("--spac-file", default=None,
                    help="Path to a precomputed JSON list of symbols identified as SPACs (blank-"
                         "check companies -- real company name matched against "
                         "ACQUISITION CORP/ACQ CORP/MERGER CORP/etc via CRSP's own comnam field, "
                         "keyed by the SAME unambiguous permno resolution as --alias-file). SPACs "
                         "cluster near their $10 trust NAV pre-merger -- a known source of spurious "
                         "cointegration, not genuine economic co-movement (Ross's 2026-08-24 "
                         "direction). Any candidate pair with either leg in this list is dropped.")
    args = p.parse_args()

    # Known same-company share-class pairs not caught by filter_structural_pairs' hand-curated
    # whitelist (that whitelist currently only covers GOOGL/GOOG-style cases) NOR by the WRDS
    # ticker<->PERMNO check (WLY/WLYB are two genuinely distinct CRSP permnos -- real, separate
    # securities that happen to be the same company's dual share classes, not a data-source alias
    # collision the permno check would catch). Found by direct inspection of this script's own
    # dry-run output, 2026-08-24 -- a real, disclosed, hand-verified exclusion, not guessed.
    _KNOWN_SHARE_CLASS_PAIRS = {frozenset(("WLY", "WLYB")), frozenset(("MKC", "PERMNO89155"))}

    # Manually-verified aliases the automated WRDS bulk resolution can't establish (its ticker is
    # itself CRSP-ambiguous -- MKC ties between permnos 52090/89155, so resolve_permnos_bulk
    # correctly refuses to guess). Resolved instead by DIRECT price-data comparison, 2026-08-24:
    # MKC_1D.parquet and PERMNO52090_1D.parquet are BYTE-IDENTICAL (max abs close diff = 0.0
    # across 13,373 matching rows, 1972-12-14 -> 2025-12-31) -- MKC's own cached data IS permno
    # 52090's data. PERMNO89155 is a genuinely DIFFERENT security (starts 2001-09-17, real price
    # differences up to $6.18) -- consistent with McCormick's real non-voting share class history
    # (added to _KNOWN_SHARE_CLASS_PAIRS above, not treated as a duplicate-identity alias).
    _MANUAL_VERIFIED_ALIASES = {"PERMNO52090": "MKC"}

    if not os.path.exists(args.source):
        print(f"Source file not found: {args.source}")
        sys.exit(1)

    source = pd.read_parquet(args.source)
    keep_cols = [c for c in ("symbol_a", "symbol_b", "pearson_corr") if c in source.columns]
    candidates_raw_df = source[keep_cols].drop_duplicates(subset=["symbol_a", "symbol_b"])
    candidates_raw_dicts = candidates_raw_df.to_dict("records")
    print(f"Loaded {len(candidates_raw_dicts)} candidate pairs from {args.source}")

    # Structural-pair contamination check (found live 2026-08-24 in this script's own dry run --
    # ~40% of the source file's candidates were same-company duplicate listings, e.g.
    # GVKEY021388_02W/GVKEY021388_01W, or share-class pairs like WLY/WLYB -- exactly the category
    # analysis.py's normal pipeline excludes via CrossAssetTagger/filter_structural_pairs, which
    # full_universe_eg_confirmation.py's driver never calls. Applying both filters here BEFORE
    # promotion, not just disclosing the gap and proceeding -- this project's own "no bandaid,
    # root-cause fix" rule.
    candidates_deduped, dropped_dupes = filter_exact_correlation_duplicates(candidates_raw_dicts)
    print(f"filter_exact_correlation_duplicates: dropped {len(dropped_dupes)}, "
          f"{len(candidates_deduped)} remain")
    candidates_raw_dicts, dropped_structural = filter_structural_pairs(candidates_deduped)
    print(f"filter_structural_pairs: dropped {len(dropped_structural)} structural pairs "
          f"(index-tracking/share-class/GVKEY-cross-listing), {len(candidates_raw_dicts)} remain")
    if dropped_structural:
        print("  Dropped structural pairs:",
              [(d.get('symbol_a'), d.get('symbol_b')) for d in dropped_structural][:20],
              "..." if len(dropped_structural) > 20 else "")

    # Additional gap found live in THIS script's own dry run (2026-08-24), beyond what
    # filter_structural_pairs already catches: that filter's GVKEY-cross-listing heuristic only
    # matches a PLAIN ticker vs a GVKEY-labeled entry -- it misses a pair where BOTH sides are
    # GVKEY-labeled under the SAME base GVKEY number (e.g. GVKEY021388_02W/GVKEY021388_01W),
    # which is an unambiguous same-company signature (different listing/window suffix of the
    # identical underlying), safe to drop without a whitelist or correlation threshold.
    import re
    _gvkey_re = re.compile(r"^GVKEY(\d+)_")

    def _gvkey_num(sym):
        m = _gvkey_re.match(sym)
        return m.group(1) if m else None

    same_gvkey_dropped = []
    kept = []
    for d in candidates_raw_dicts:
        ga, gb = _gvkey_num(d["symbol_a"]), _gvkey_num(d["symbol_b"])
        if ga is not None and ga == gb:
            same_gvkey_dropped.append(d)
        else:
            kept.append(d)
    candidates_raw_dicts = kept
    print(f"same-GVKEY-number filter: dropped {len(same_gvkey_dropped)} more same-company pairs, "
          f"{len(candidates_raw_dicts)} remain")
    if same_gvkey_dropped:
        print("  Dropped same-GVKEY pairs:",
              [(d.get('symbol_a'), d.get('symbol_b')) for d in same_gvkey_dropped])

    # WRDS ticker<->PERMNO duplicate-identity check (found live 2026-08-24, Ross's explicit
    # direction to build this before promoting anything further): a PERMNO<n>-labeled symbol in
    # the merged universe can be a literal alias of an already-present plain ticker (e.g. DCOM
    # resolves to permno 92716, and PERMNO92716 is ALSO a separate symbol in this same universe
    # -- so "DCOM/PBCT" and "PBCT/PERMNO92716" describe the identical real relationship counted
    # twice; VRT/PERMNO17987 is worse -- VRT itself IS permno 17987, so that "pair" is a security
    # cointegrated with itself under an alias). Resolves every plain ticker in the candidate set
    # via CRSP's own ticker->permno table (data_wrds.resolve_permnos_bulk, refuses to guess on
    # genuinely CRSP-ambiguous tickers like MKC/BH rather than silently picking one), canonicalizes
    # any PERMNO<n> symbol that matches a resolved ticker's own permno to that ticker, drops
    # self-pairs, and dedupes pairs that become identical after canonicalization.
    if not args.skip_wrds_check:
        all_syms_now = sorted(set(s for d in candidates_raw_dicts for s in (d["symbol_a"], d["symbol_b"])))
        plain_syms = [s for s in all_syms_now if not s.startswith("PERMNO") and not s.startswith("GVKEY")]
        permno_syms = {s for s in all_syms_now if s.startswith("PERMNO")}
        canon = {}  # symbol -> canonical symbol (itself, unless it's a PERMNO alias of a real ticker)
        if args.alias_file:
            # Precomputed on a machine WITH working WRDS credentials (data_wrds.resolve_permnos_bulk
            # needs a live WRDS connection; a machine with only cached price data, no WRDS auth,
            # can't run that query itself -- see this script's Development.md entry, 2026-08-24).
            print(f"WRDS ticker<->PERMNO check: using precomputed alias file {args.alias_file} "
                  f"(no live WRDS connection needed on this machine)")
            with open(args.alias_file) as f:
                precomputed = json.load(f)
            for alias, ticker in precomputed.items():
                if alias in permno_syms:
                    canon[alias] = ticker
                    print(f"  {alias} == {ticker} (same underlying security, from precomputed alias file)")
        else:
            from data_wrds import _connect, resolve_permnos_bulk
            print(f"WRDS ticker<->PERMNO check: resolving {len(plain_syms)} plain tickers...")
            db = _connect()
            resolved = resolve_permnos_bulk(db, plain_syms)
            db.close()
            for ticker, permno in resolved.items():
                alias = f"PERMNO{permno}"
                if alias in permno_syms:
                    canon[alias] = ticker
                    print(f"  {alias} == {ticker} (same underlying security)")
        for alias, ticker in _MANUAL_VERIFIED_ALIASES.items():
            if alias in permno_syms and alias not in canon:
                canon[alias] = ticker
                print(f"  {alias} == {ticker} (same underlying security, manually verified "
                      f"via direct price-data comparison -- WRDS ticker resolution was ambiguous)")

        def _canon(sym):
            return canon.get(sym, sym)

        self_pairs = []
        dupe_dropped = []
        kept = []
        seen_canon_keys = set()
        # Seed seen_canon_keys with the known share-class pairs so a canonicalized alias of an
        # already-known same-company pair (e.g. PERMNO52090/PERMNO89155 -> canonicalizes to
        # MKC/PERMNO89155, itself a known McCormick voting/non-voting share-class pair) gets
        # caught here too, not just an exact literal-symbol match run before canonicalization.
        for known in _KNOWN_SHARE_CLASS_PAIRS:
            seen_canon_keys.add(tuple(sorted(known)))
        for d in candidates_raw_dicts:
            ca, cb = _canon(d["symbol_a"]), _canon(d["symbol_b"])
            if ca == cb:
                self_pairs.append(d)
                continue
            key = tuple(sorted((ca, cb)))
            if key in seen_canon_keys:
                dupe_dropped.append(d)
                continue
            seen_canon_keys.add(key)
            kept.append(d)
        candidates_raw_dicts = kept
        print(f"WRDS canonicalization: dropped {len(self_pairs)} self-pair(s) "
              f"(a symbol cointegrated with its own PERMNO alias) and {len(dupe_dropped)} "
              f"duplicate pair(s) (same relationship under an alias), {len(candidates_raw_dicts)} remain")
        if self_pairs:
            print("  Self-pairs dropped:", [(d['symbol_a'], d['symbol_b']) for d in self_pairs])
        if dupe_dropped:
            print("  Duplicate pairs dropped:", [(d['symbol_a'], d['symbol_b']) for d in dupe_dropped])
    else:
        print("WRDS ticker<->PERMNO check SKIPPED (--skip-wrds-check) -- promoted set may still "
              "contain alias duplicates/self-pairs. Not recommended for a real promotion run.")
        known_share_class_dropped = [
            d for d in candidates_raw_dicts
            if frozenset((d["symbol_a"], d["symbol_b"])) in _KNOWN_SHARE_CLASS_PAIRS
        ]
        candidates_raw_dicts = [
            d for d in candidates_raw_dicts
            if frozenset((d["symbol_a"], d["symbol_b"])) not in _KNOWN_SHARE_CLASS_PAIRS
        ]
        if known_share_class_dropped:
            print(f"known-share-class exclusion list (literal match only, no WRDS canonicalization "
                  f"in this skip-mode run): dropped {len(known_share_class_dropped)}:",
                  [(d['symbol_a'], d['symbol_b']) for d in known_share_class_dropped])

    # SPAC exclusion (Ross's 2026-08-24 direction): blank-check companies cluster near their $10
    # trust NAV pre-merger, a known source of spurious cointegration/correlation between UNRELATED
    # SPACs, not genuine economic co-movement -- a real methodology concern distinct from the
    # identity-duplication bugs fixed above. Detected via real CRSP company names (comnam) keyed
    # by the same unambiguous permno resolution as the alias check, matched against real SPAC
    # naming conventions (ACQUISITION CORP/ACQ CORP/MERGER CORP/etc) -- see
    # output/research/spac_symbols.json's own generation script (Development.md, 2026-08-24) for
    # the exact query. High-precision, not necessarily exhaustive -- some SPAC families use
    # non-standard names (e.g. "Social Capital Hedosophia Holdings Corp VI" has no "Acquisition"/
    # "Acq"/"Merger" token) and would NOT be caught; disclosed, not silently assumed complete.
    if args.spac_file:
        with open(args.spac_file) as f:
            spac_symbols = set(json.load(f))
        spac_dropped = [
            d for d in candidates_raw_dicts
            if d["symbol_a"] in spac_symbols or d["symbol_b"] in spac_symbols
        ]
        candidates_raw_dicts = [
            d for d in candidates_raw_dicts
            if d["symbol_a"] not in spac_symbols and d["symbol_b"] not in spac_symbols
        ]
        print(f"SPAC exclusion ({args.spac_file}): dropped {len(spac_dropped)} pairs involving a "
              f"known SPAC, {len(candidates_raw_dicts)} remain")
        if spac_dropped:
            print("  Dropped SPAC-involving pairs:",
                  [(d['symbol_a'], d['symbol_b']) for d in spac_dropped])
    else:
        print("WARNING: no --spac-file given -- SPAC pairs (spurious NAV-clustering "
              "cointegration) are NOT excluded from this promotion. Not recommended.")

    candidates_raw = [(d["symbol_a"], d["symbol_b"]) for d in candidates_raw_dicts]
    symbols_needed = sorted(set(s for pair in candidates_raw for s in pair))
    print(f"Loading + aligning {len(symbols_needed)} symbols for tf={args.tf}...")

    t0 = time.time()
    universe = load_full_universe(tf_label=args.tf)
    aligned_full = {sym: df for sym, df in universe.items() if sym in symbols_needed}
    missing = [s for s in symbols_needed if s not in aligned_full]
    if missing:
        print(f"WARNING: {len(missing)} symbols missing from the loaded universe, "
              f"their pairs will be dropped: {missing}")
    aligned = align_to_common_calendar(aligned_full)
    print(f"Loaded + aligned {len(aligned)} symbols in {time.time()-t0:.1f}s")

    candidate_pairs = [
        {"symbol_a": a, "symbol_b": b}
        for a, b in candidates_raw
        if a in aligned and b in aligned
    ]
    print(f"{len(candidate_pairs)}/{len(candidates_raw)} candidate pairs have usable aligned data")
    if not candidate_pairs:
        print("Nothing to promote.")
        return

    print("Re-running EG + BH-FDR confirmation on this candidate list (same production test, "
          "cheap at this scale)...")
    confirmed_dicts, eg_stats = CointScanner.scan(
        candidate_pairs=candidate_pairs,
        aligned_data=aligned,
        symbols_in_corr=list(aligned.keys()),
        tf_label=args.tf,
        n_workers=Config.RUNTIME.N_WORKERS,
    )
    print(f"EG+BH-FDR: {eg_stats}")
    if not confirmed_dicts:
        print("No pairs survived re-confirmation. Nothing to promote -- the original candidate "
              "list may have used a different fdr_alpha/max_lag than this run's defaults.")
        return

    confirmed_dicts = CointScanner.rolling_fraction(
        confirmed_dicts, aligned, args.tf, n_workers=Config.RUNTIME.N_WORKERS,
    )

    print(f"Building full pair results (hedge ratios, spread model, half-life, Hurst) for "
          f"{len(confirmed_dicts)} pairs...")
    pair_results = []
    per_bar_by_pair = {}
    for pd_meta in confirmed_dicts:
        try:
            built = AnalysisPipeline._build_pair_result(pd_meta, aligned, args.tf)
            if built is not None:
                pr, per_bar = built
                pair_results.append(pr)
                per_bar_by_pair[(pr.symbol_a, pr.symbol_b)] = per_bar
        except Exception as e:
            print(f"  {pd_meta.get('symbol_a')}/{pd_meta.get('symbol_b')}: "
                  f"failed in _build_pair_result: {type(e).__name__}: {e}")

    print(f"Built {len(pair_results)} full PairResult objects.")
    if not pair_results:
        print("Nothing to promote.")
        return

    new_pairs_df = pd.DataFrame([asdict(p) for p in pair_results])

    tf_dir = DataStore._TF_SAFE.get(args.tf, args.tf.lower())
    results_dir = os.path.join(_ROOT, "output", "results", tf_dir)
    pairs_path = os.path.join(results_dir, "pairs.parquet")
    os.makedirs(results_dir, exist_ok=True)

    if os.path.exists(pairs_path):
        existing_df = pd.read_parquet(pairs_path)
        existing_keys = set(zip(existing_df["symbol_a"], existing_df["symbol_b"]))
    else:
        existing_df = pd.DataFrame()
        existing_keys = set()

    new_pairs_df["_is_new"] = [
        (a, b) not in existing_keys for a, b in zip(new_pairs_df["symbol_a"], new_pairs_df["symbol_b"])
    ]
    to_add = new_pairs_df[new_pairs_df["_is_new"]].drop(columns=["_is_new"])
    already_present = len(new_pairs_df) - len(to_add)
    print(f"{len(to_add)} genuinely new pairs to promote; {already_present} already present in "
          f"{pairs_path} (kept unchanged, not overwritten).")

    if args.dry_run:
        print("DRY RUN -- not writing. Would add:")
        print(to_add[["symbol_a", "symbol_b", "coint_pvalue_adjusted"]].to_string(index=False)
              if not to_add.empty else "(nothing)")
        return

    if to_add.empty:
        print("Nothing new to promote -- all candidate pairs already present.")
        return

    merged_df = pd.concat([existing_df, to_add], ignore_index=True) if not existing_df.empty else to_add

    tmp_path = pairs_path + ".tmp_promote"
    merged_df.to_parquet(tmp_path)
    os.replace(tmp_path, pairs_path)  # atomic on POSIX -- concurrent readers never see a partial file
    print(f"Wrote {len(merged_df)} total pairs ({len(to_add)} newly promoted) -> {pairs_path}")

    n_series_written = 0
    for _, row in to_add.iterrows():
        key = (row["symbol_a"], row["symbol_b"])
        pb = per_bar_by_pair.get(key)
        if pb is None:
            continue
        n_bars = len(pb["index"])
        nan_fill = np.full(n_bars, np.nan)
        series_df = pd.DataFrame({
            "spread": pb["spread"],
            "z_rolling": pb["z_rolling"],
            "z_expanding": pb["z_expanding"],
            "half_life_rolling": pb["half_life_rolling_series"],
            "gap_flag_a": pb["gap_flag_a"],
            "gap_flag_b": pb["gap_flag_b"],
            "hedge_ratio_ols_t": pb.get("hedge_ratio_ols_t"),
            "hedge_ratio_kalman_t": pb.get("hedge_ratio_kalman_t"),
            "coint_fraction_rolling_t": pb.get("coint_fraction_rolling_t", nan_fill),
            "half_life_trend_slope_t": pb.get("half_life_trend_slope_t", nan_fill),
            "mean_reversion_speed_t": pb.get("mean_reversion_speed_t", nan_fill),
            "hurst_rs_t": pb.get("hurst_rs_t", nan_fill),
        }, index=pb["index"])
        series_path = os.path.join(results_dir, f"spread_series_{key[0]}_{key[1]}.parquet")
        series_df.to_parquet(series_path)
        n_series_written += 1
    print(f"Wrote {n_series_written} new spread_series_*.parquet files -> {results_dir}")

    print("\nHonest scope note: structural-pair/exact-duplicate contamination WAS filtered "
          "(filter_exact_correlation_duplicates + filter_structural_pairs, applied above). Does "
          "NOT re-apply the later coint_frac rolling-significance threshold, and does NOT re-run "
          "episodic/deep-history enrichment. Same PIT/non-episodic caveat as every other "
          "full-history-confirmed pair in this project (see FINDINGS.md).")


if __name__ == "__main__":
    main()
