#!/bin/bash
# 2026-10-21 Amendment 5 re-run (docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md): BUG-D119 unrealizable trades,
# BUG-D118 rule on consecutive valid prices, BUG-D120 pool = point-in-time-eligible set, sealed holdout at the data
# layer (seal.py). Ross 2026-10-21: "i sign off on those". Every step stops the chain on failure.
cd ~/CAMARF || exit 1
L=logs/latest/latest_run_rerun_a5_20261021.log; S=output/research; W=output/cache/wrds; PY=.venv/bin/python
run() { local name=$1; shift; echo "$(date '+%F %T') START $name: $*" >> $L
  "$@" > $S/_stdout_a5_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
seal_gate() { $PY seal.py --audit > $S/_stdout_a5_seal_audit_$1.log 2>&1 \
  || { echo "$(date '+%F %T') GUARD: live caches hold sealed rows ($1) -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') seal audit ($1): 0 live files with sealed rows" >> $L; }
echo "$(date '+%F %T') start: $(git log --oneline -1)" >> $L
for f in wrds_label_permno_final crsp_stocknames_all ciq_link_gvkey ciq_link_cusip crsp_ccm_link; do
  [ -s $W/$f.parquet ] || { echo "missing $W/$f.parquet -- STOPPED" >> $L; exit 1; }; done
# Amendment 4's result is reported as superseded, never overwritten: keep its eval outputs and pools.
A4=$S/_superseded_a4_20261020; mkdir -p $A4
cp -n $S/strategy_search/summary.parquet $S/strategy_search/all_trials.parquet $S/strategy_search/trials.json $A4/ || exit 1
cp -n $S/purity_pairs_pit_k1_clean.parquet $S/purity_pairs_pit_k2_clean.parquet $S/purity_pairs.parquet $A4/ || exit 1
echo "$(date '+%F %T') Amendment 4 outputs kept in $A4" >> $L
run seal_sweep $PY -u seal.py
seal_gate after_sweep
run d118_rebuild $PY -u research/split_level_breaks.py
seal_gate after_d118
$PY debug/_run_all_verify.py --workers 4 --timeout 900 > docs/bug_recheck/suite_20261021_a5_cachyos.log 2>&1
# Known, explained: the two paper-claims checks compare the drafts' numbers with re-derived outputs (redraft pending).
FAILS=$(grep -E "\] (FAIL|TIMEOUT|ERROR) " docs/bug_recheck/suite_20261021_a5_cachyos.log \
  | grep -v "_verify_paper_claims.py\|_verify_paper_magnitude_claims.py" | wc -l)
echo "$(date '+%F %T') suite: $(grep -cE '\] (PASS|FAIL|TIMEOUT|ERROR) ' docs/bug_recheck/suite_20261021_a5_cachyos.log) tests, unexplained failures: $FAILS" >> $L
[ "$FAILS" -eq 0 ] || { echo "unexplained suite failures -- STOPPED" >> $L; exit 1; }
run discovery $PY -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude
run intraday $PY -u research/intraday_episodic_scan.py --tf both --fresh
run adapter $PY -u research/episodic_pairs_adapter.py --fresh
run comparison_arms $PY -u research/build_comparison_arm_pairs.py
run pit_eligibility $PY -u research/purity_pit_eligibility.py
run clean_pools $PY -u research/clean_pool_identity_pairs.py
run pool_spreads $PY -u research/regenerate_pool_spread_series.py --pairs $S/purity_pairs_pit_k1_clean.parquet
run squeeze $PY -u research/squeeze_momentum_features.py --pairs-file $S/purity_pairs_pit_k1_clean.parquet
run audit_degenerate $PY -u research/degenerate_column_audit.py --dir output/results/1day --pattern "spread_series_*.parquet" --out $S/degenerate_column_audit_a5.parquet
run audit_contracts $PY -u research/pipeline_contracts.py
# Ross 2026-10-22: holes counted on each market's trading calendar; Compustat Global exchanges come from WRDS job 35
[ -s $W/global_security_exchange.parquet ] || { echo "$(date '+%F %T') GUARD: $W/global_security_exchange.parquet missing (WRDS job 35) -- STOPPED before the search" >> $L; exit 1; }
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
echo "$(date '+%F %T') chain complete" >> $L
