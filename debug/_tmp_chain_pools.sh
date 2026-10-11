#!/bin/bash
# 2026-10-10 chain (CachyOS): intraday re-run (1h/4h ran 2026-09-28 at 7201bb9d, before the October fixes), then the
# pool chain on the signed Amendment 2 addendum (a918c5b0; S32/S35/S36 in 74e54dfa), then the second pre-registered
# strategy search. The 1D discovery (beb004b4) is lineage-flagged only for later code changes that a real-data
# equivalence check showed to be behaviour-neutral (debug/_check_discovery_code_neutrality.py, log in
# ~/neutrality_20261010.log) -> the adapter is run with --allow-stale-upstream (logged).
# Hardware: every pooled stage defaults to Config.RUNTIME.N_WORKERS with BLAS capped at 1 thread per worker.
# stdout goes to separate _stdout files, never to a script's own log name.
cd ~/CAMARF || exit 1
L=latest_run_pool_chain.log
S=output/research
run() {  # name, command...
  local name=$1; shift
  echo "$(date '+%F %T') START $name: $*" >> $L
  "$@" > $S/_stdout_pool_chain_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L
}
echo "$(date '+%F %T') chain start: $(git log --oneline -1)" >> $L
run intraday .venv/bin/python -u research/intraday_episodic_scan.py --tf both --fresh
run adapter .venv/bin/python -u research/episodic_pairs_adapter.py --fresh --allow-stale-upstream
run comparison_arms .venv/bin/python -u research/build_comparison_arm_pairs.py
run pit_eligibility .venv/bin/python -u research/purity_pit_eligibility.py
run clean_pools .venv/bin/python -u research/clean_pool_identity_pairs.py
run pool_spreads .venv/bin/python -u research/regenerate_pool_spread_series.py --pairs $S/purity_pairs_pit_k1_clean.parquet
run squeeze .venv/bin/python -u research/squeeze_momentum_features.py --pairs-file $S/purity_pairs_pit_k1_clean.parquet
run audit_degenerate .venv/bin/python -u research/degenerate_column_audit.py --dir output/results --pattern "spread_series_*.parquet" --out output/research/degenerate_column_audit_pool_chain.parquet
run audit_contracts .venv/bin/python -u research/pipeline_contracts.py
run search_run .venv/bin/python -u research/strategy_search.py run
run search_eval .venv/bin/python -u research/strategy_search.py eval
echo "$(date '+%F %T') chain complete" >> $L
