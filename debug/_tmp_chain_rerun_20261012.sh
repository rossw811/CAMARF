#!/bin/bash
# 2026-10-12 re-run after BUG-D115 (crashed tests in BH's m), BUG-D116 (search reused first-pass trades), BUG-D117
# (label -> PERMNO identity) and the S36 same-company gap (CCM + Capital IQ links). Ross: "fix everything first then
# resume running scripts and re run what was broken". Every step stops the chain on failure.
cd ~/CAMARF || exit 1
L=latest_run_rerun_20261012.log; S=output/research; W=output/cache/wrds
run() { local name=$1; shift; echo "$(date '+%F %T') START $name: $*" >> $L
  "$@" > $S/_stdout_rerun_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
echo "$(date '+%F %T') start: $(git log --oneline -1)" >> $L
for f in wrds_label_permno_final crsp_stocknames_all ciq_link_gvkey ciq_link_cusip crsp_ccm_link; do
  [ -s $W/$f.parquet ] || { echo "missing $W/$f.parquet -- STOPPED" >> $L; exit 1; }; done
run volume_reapply .venv/bin/python -u research/apply_crsp_volume_adjustment.py
.venv/bin/python debug/_run_all_verify.py --workers 4 --timeout 900 > docs/bug_recheck/suite_20261012b_cachyos.log 2>&1
FAILS=$(grep -E "\] (FAIL|TIMEOUT|ERROR) " docs/bug_recheck/suite_20261012b_cachyos.log | grep -v "_verify_paper_claims.py" | wc -l)
echo "$(date '+%F %T') suite: $(grep -cE '\] (PASS|FAIL|TIMEOUT|ERROR) ' docs/bug_recheck/suite_20261012b_cachyos.log) tests, unexplained failures: $FAILS" >> $L
[ "$FAILS" -eq 0 ] || { echo "unexplained suite failures -- STOPPED" >> $L; exit 1; }
run discovery .venv/bin/python -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude
run intraday .venv/bin/python -u research/intraday_episodic_scan.py --tf both --fresh
run adapter .venv/bin/python -u research/episodic_pairs_adapter.py --fresh
run comparison_arms .venv/bin/python -u research/build_comparison_arm_pairs.py
run pit_eligibility .venv/bin/python -u research/purity_pit_eligibility.py
run clean_pools .venv/bin/python -u research/clean_pool_identity_pairs.py
run pool_spreads .venv/bin/python -u research/regenerate_pool_spread_series.py --pairs $S/purity_pairs_pit_k1_clean.parquet
run squeeze .venv/bin/python -u research/squeeze_momentum_features.py --pairs-file $S/purity_pairs_pit_k1_clean.parquet
run audit_degenerate .venv/bin/python -u research/degenerate_column_audit.py --dir output/results/1day --pattern "spread_series_*.parquet" --out $S/degenerate_column_audit_rerun.parquet
run audit_contracts .venv/bin/python -u research/pipeline_contracts.py
T0=$(date +%s)
run search_run .venv/bin/python -u research/strategy_search.py run --fresh
DT=$(( $(date +%s) - T0 ))
for p in pit_k1 pit_k2; do n=$(find $S/strategy_search/$p -maxdepth 1 -name "*.parquet" -newermt "@$T0" | wc -l)
  echo "$(date '+%F %T') $p: $n fresh trade files; run took ${DT}s" >> $L
  [ "$n" -eq 216 ] || { echo "GUARD: expected 216 fresh files in $p -- STOPPED" >> $L; exit 1; }; done
[ "$DT" -ge 120 ] || { echo "GUARD: 432 backtests in ${DT}s is implausible -- STOPPED" >> $L; exit 1; }
run search_eval .venv/bin/python -u research/strategy_search.py eval
echo "$(date '+%F %T') chain complete" >> $L
