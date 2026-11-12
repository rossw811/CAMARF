#!/bin/bash
# E1 v2c (Ross 2026-11-12, "I'll take your recommendation"): v2b + top volatility bin without replacement (every stress
# day once). v2b seed 1 stopped at the guard (0.757); 5-seed proxy: v2c whole-history share 0.92-1.40 x real.
# 5 seeds (20261024-28; the first 3 are v2's seed numbers, but v2b's day paths are volatility-matched, so they are NOT
# v2's paths). Same pipeline as debug/_tmp_chain_e1_v2_20261102.sh.
# Worktree ~/CAMARF_e1 (its output/cache/wrds is the placebo universe); outputs kept in ~/CAMARF_e1_runs/v2c_seed<seed>/.
# ~20 h per seed on CachyOS; one heavy job at a time, so it refuses to start while the A8 chain runs.
set -u
MAIN=~/CAMARF; E=~/CAMARF_e1; RUNS=~/CAMARF_e1_runs; PY=$MAIN/.venv/bin/python
L=$MAIN/logs/latest/latest_run_e1_v2c_20261112.log
if pgrep -f "_tmp_chain_a8_cachyos" > /dev/null; then echo "$(date '+%F %T') A8 chain still running -- not started" >> $L; exit 1; fi
# bash keeps reading the file it opened: pull, then re-exec the pulled script (A8 relaunch 4, 2026-11-11)
if [ "${1:-}" != "--pulled" ]; then
  cd $MAIN && git pull -q --ff-only origin main || { echo "$(date '+%F %T') git pull failed -- STOPPED" >> $L; exit 1; }
  exec bash "$MAIN/debug/_tmp_chain_e1_v2c_20261112.sh" --pulled
fi
cd $MAIN
echo "$(date '+%F %T') E1 v2c start; main at $(git log --oneline -1 | cut -c1-60)" >> $L
mkdir -p $RUNS
cd $E && git checkout -q --detach $(git -C $MAIN rev-parse HEAD) || { echo "checkout failed -- STOPPED" >> $L; exit 1; }
echo "$(date '+%F %T') E1 v2c worktree at $(git log --oneline -1 | cut -c1-60)" >> $L
ln -sfn $MAIN/.venv $E/.venv
clear_outputs() {   # placebo cache and every derived output of the worktree; never the real cache
  local W=$E/output/cache/wrds
  [ -L $W ] && { echo "GUARD: $W is a symlink -- STOPPED" >> $L; exit 1; }
  case "$(realpath -m $W)" in "$(realpath $E)"/*) ;; *) echo "GUARD: $W outside the worktree -- STOPPED" >> $L; exit 1;; esac
  rm -rf $W $E/output/cache/_universe_loader_memo $E/output/results $E/output/lineage $E/output/reports $E/output/research
  mkdir -p $W $E/output/research $E/logs/latest
}
for SEED in 20261024 20261025 20261026 20261027 20261028; do
  [ -d $RUNS/v2c_seed$SEED ] && { echo "$(date '+%F %T') [$SEED] already complete, skipped" >> $L; continue; }
  O=$E/output/research
  run() { local name=$1; shift; echo "$(date '+%F %T') [$SEED] START $name" >> $L
    "$@" > $O/_stdout_e1v2c_$name.log 2>&1 || { echo "$(date '+%F %T') [$SEED] FAILED $name -- STOPPED" >> $L; exit 1; }
    echo "$(date '+%F %T') [$SEED] done $name" >> $L; }
  clear_outputs
  run build $PY -u research/placebo_discovery_e1.py build --src $MAIN/output/cache/wrds --dst $E/output/cache/wrds --seed $SEED --version v2c
  run check_us_plants $PY -c "
import sys, pandas as pd; sys.path.insert(0, '.')
from research.wrds_deep_history_episodic_scan import load_membership_gate
P = pd.read_parquet('output/cache/wrds/_e1_plants.parquet'); us = P[P.arm == 'us']
m, pm = load_membership_gate()
bad = [r.plant for r in us.itertuples() if pm.get(r.plant) is None or m[m.permno == pm[r.plant]].empty]
print(len(us), 'US plants;', len(bad), 'unresolved', bad[:5]); sys.exit(1 if bad or len(us) == 0 else 0)"
  echo "$(date '+%F %T') [$SEED] START discovery" >> $L
  # own process group (setsid execs in place, so $! = PGID): the guard kills the pool workers too (2026-11-12: a
  # plain kill left 15 orphaned workers holding ~27 GB on CachyOS)
  setsid $PY -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude > $O/_stdout_e1v2c_discovery.log 2>&1 &
  DPID=$!
  until grep -q "\[TIER 1\] Saved ->" $O/_stdout_e1v2c_discovery.log 2>/dev/null || ! kill -0 $DPID 2>/dev/null; do sleep 60; done
  if ! $PY -u research/placebo_discovery_e1.py check_tier1 --research $O --real-research $MAIN/output/research >> $L 2>&1; then
    kill -- -$DPID 2>/dev/null; echo "$(date '+%F %T') [$SEED] GUARD: tier-1 candidate gap -- discovery killed, STOPPED" >> $L; exit 1
  fi
  wait $DPID || { echo "$(date '+%F %T') [$SEED] FAILED discovery -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') [$SEED] done discovery" >> $L
  run adapter $PY -u research/episodic_pairs_adapter.py --fresh
  run comparison_arms $PY -u research/build_comparison_arm_pairs.py
  run pit_eligibility $PY -u research/purity_pit_eligibility.py
  run clean_pools $PY -u research/clean_pool_identity_pairs.py
  run score $PY -u research/placebo_discovery_e1.py score --research $O --dst $E/output/cache/wrds --real-research $MAIN/output/research
  mkdir -p $RUNS/v2c_seed$SEED && mv $O $RUNS/v2c_seed$SEED/research && cp $E/output/cache/wrds/_e1_*.parquet $RUNS/v2c_seed$SEED/
  echo "$(date '+%F %T') [$SEED] seed complete -> $RUNS/v2c_seed$SEED" >> $L
done
echo "$(date '+%F %T') E1 v2c complete" >> $L
