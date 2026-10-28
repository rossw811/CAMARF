#!/bin/bash
# 2026-10-28 Amendment 7 re-run on the SURFACE (docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md): BUG-D122 liquidity
# gate ADV, BUG-D121 commission share count, the `--adv-missing zero` discovery comparison arm. Ross 2026-10-27 "yes to
# all", 2026-10-28 "do it on the surface". Data = a mirror of CachyOS's output/cache (sync_cache.py, names + sizes);
# the cache is NOT swept or rebuilt here, so the snapshot stays CachyOS's. Every step stops the chain on failure.
# Restart after a stop: fix the cause, then run the remaining steps by hand (discovery resumes from its checkpoints
# when run without --fresh and the lineage is up to date).
cd /c/Users/RossW/Projects/CAMARF || exit 1
L=logs/latest/latest_run_rerun_a7_surface_20261028.log; S=output/research; W=output/cache/wrds
PY=/c/Users/RossW/anaconda3/envs/trading/python.exe
export PYTHONUTF8=1
run() { local name=$1; shift; echo "$(date '+%F %T') START $name: $*" >> $L
  "$@" > $S/_stdout_a7_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
seal_gate() { $PY seal.py --audit > $S/_stdout_a7_seal_audit_$1.log 2>&1 \
  || { echo "$(date '+%F %T') GUARD: live caches hold sealed rows ($1) -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') seal audit ($1): 0 live files with sealed rows" >> $L; }
parity_gate() { $PY - "$1" >> $L 2>&1 <<'EOF' || { echo "$(date '+%F %T') GUARD: cache differs from CachyOS's listing -- STOPPED" >> $L; exit 1; }
import hashlib, os, sys
root = os.path.join("output", "cache")
saved = open(os.path.join("output", "research", "a7_cachyos_cache_listing.tsv"), encoding="utf-8").read()
cur = {}
for r, _, fs in os.walk(root):
    for f in fs:
        p = os.path.join(r, f); cur[os.path.relpath(p, root).replace("\\", "/")] = os.path.getsize(p)
now = "".join(f"{p}\t{cur[p]}\n" for p in sorted(cur))
h = hashlib.sha256(saved.encode()).hexdigest()
print(f"parity ({sys.argv[1]}): {len(cur)} files; listing sha256 {h}; {'MATCH' if now == saved else 'DIFFERS'}")
sys.exit(0 if now == saved else 1)
EOF
}
echo "$(date '+%F %T') start: $(git log --oneline -1) on $(hostname)" >> $L
[ -s $S/a7_cachyos_cache_listing.tsv ] || { echo "no saved CachyOS listing (run sync_cache.py --apply) -- STOPPED" >> $L; exit 1; }
for f in wrds_label_permno_final crsp_stocknames_all ciq_link_gvkey ciq_link_cusip crsp_ccm_link global_security_exchange; do
  [ -s $W/$f.parquet ] || { echo "missing $W/$f.parquet -- STOPPED" >> $L; exit 1; }; done
parity_gate start
seal_gate start
# The Amendment 5 result and Amendment 6 arm (mirrored from CachyOS's output/research) are reported as superseded,
# never overwritten: keep every eval output (all arms' suffixes) and the pools.
K=$S/_superseded_a5_a6_20261028; mkdir -p $K
for f in $S/strategy_search/*.parquet $S/strategy_search/*.json $S/purity_pairs_pit_k1_clean.parquet \
         $S/purity_pairs_pit_k2_clean.parquet $S/purity_pairs.parquet $S/purity_pairs_pit_k?_dyn*.parquet; do
  [ -e "$f" ] && { cp -n "$f" $K/ || exit 1; }; done
[ -s $K/summary.parquet ] || { echo "GUARD: no Amendment 5 summary to keep (output/research not mirrored?) -- STOPPED" >> $L; exit 1; }
echo "$(date '+%F %T') Amendment 5/6 outputs kept in $K: $(ls $K | wc -l) files" >> $L
$PY debug/_run_all_verify.py --workers 4 --timeout 900 > docs/bug_recheck/suite_20261028_a7_surface.log 2>&1
FAILS=$(grep -E "\] (FAIL|TIMEOUT|ERROR) " docs/bug_recheck/suite_20261028_a7_surface.log \
  | grep -v "_verify_paper_claims.py\|_verify_paper_magnitude_claims.py" | wc -l)
echo "$(date '+%F %T') suite: $(grep -cE '\] (PASS|FAIL|TIMEOUT|ERROR) ' docs/bug_recheck/suite_20261028_a7_surface.log) tests, unexplained failures: $FAILS" >> $L
[ "$FAILS" -eq 0 ] || { echo "unexplained suite failures -- STOPPED" >> $L; exit 1; }
run discovery $PY -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude
run discovery_advzero $PY -u research/wrds_deep_history_episodic_scan.py --d18 exclude --adv-missing zero
run intraday $PY -u research/intraday_episodic_scan.py --tf both --fresh
run adapter $PY -u research/episodic_pairs_adapter.py --fresh
run comparison_arms $PY -u research/build_comparison_arm_pairs.py
run pit_eligibility $PY -u research/purity_pit_eligibility.py
run clean_pools $PY -u research/clean_pool_identity_pairs.py
run pool_spreads $PY -u research/regenerate_pool_spread_series.py --pairs $S/purity_pairs_pit_k1_clean.parquet
run squeeze $PY -u research/squeeze_momentum_features.py --pairs-file $S/purity_pairs_pit_k1_clean.parquet
run audit_degenerate $PY -u research/degenerate_column_audit.py --dir output/results/1day --pattern "spread_series_*.parquet" --out $S/degenerate_column_audit_a7.parquet
run audit_contracts $PY -u research/pipeline_contracts.py
run market_calendars $PY -u research/build_market_calendars.py
seal_gate before_search
T0=$(date +%s)
run search_run $PY -u research/strategy_search.py run --fresh
DT=$(( $(date +%s) - T0 ))
for p in pit_k1 pit_k2; do n=$(find $S/strategy_search/$p -maxdepth 1 -name "*.parquet" -newermt "@$T0" | wc -l)
  echo "$(date '+%F %T') $p: $n fresh trade files; run took ${DT}s" >> $L
  [ "$n" -eq 216 ] || { echo "GUARD: expected 216 fresh files in $p -- STOPPED" >> $L; exit 1; }; done
[ "$DT" -ge 120 ] || { echo "GUARD: 432 backtests in ${DT}s is implausible -- STOPPED" >> $L; exit 1; }
run search_eval $PY -u research/strategy_search.py eval
( parity_gate end ) || echo "$(date '+%F %T') note: the cache changed during the chain (reported, not a stop)" >> $L
echo "$(date '+%F %T') chain complete" >> $L
