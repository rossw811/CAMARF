#!/bin/bash
# E1 end-to-end placebo discovery (Ross 2026-10-24: "build, yes to all"). Runs in a SEPARATE git worktree
# (~/CAMARF_e1) whose output/cache/wrds is the placebo universe, so no real cache or output is touched. Starts only
# after the Amendment 5 chain has finished (RAM: never two discovery runs at once). research/placebo_discovery_e1.py
set -u
MAIN=~/CAMARF; E=~/CAMARF_e1; PY=$MAIN/.venv/bin/python; L=$MAIN/logs/latest/latest_run_e1.log
A5=$MAIN/logs/latest/latest_run_rerun_a5_20261021.log
echo "$(date '+%F %T') E1 waiting for the Amendment 5 chain" >> $L
until tail -1 $A5 | grep -q "chain complete\|STOPPED"; do sleep 300; done
tail -1 $A5 | grep -q "chain complete" || { echo "$(date '+%F %T') A5 chain stopped -- E1 not started" >> $L; exit 1; }
cd $MAIN || exit 1
[ -d $E ] || git worktree add --detach $E HEAD >> $L 2>&1 || { echo "worktree failed -- STOPPED" >> $L; exit 1; }
cd $E && git checkout -q --detach $(git -C $MAIN rev-parse HEAD) || exit 1
mkdir -p $E/output/cache $E/output/research $E/logs/latest
ln -sfn $MAIN/.venv $E/.venv
run() { local name=$1; shift; echo "$(date '+%F %T') START $name" >> $L
  "$@" > $E/output/research/_stdout_e1_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
run build $PY -u research/placebo_discovery_e1.py build --src $MAIN/output/cache/wrds --dst $E/output/cache/wrds
run discovery $PY -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude
run adapter $PY -u research/episodic_pairs_adapter.py --fresh
run comparison_arms $PY -u research/build_comparison_arm_pairs.py
run pit_eligibility $PY -u research/purity_pit_eligibility.py
run clean_pools $PY -u research/clean_pool_identity_pairs.py
run score $PY -u research/placebo_discovery_e1.py score --research $E/output/research --dst $E/output/cache/wrds
echo "$(date '+%F %T') E1 complete" >> $L
