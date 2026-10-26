#!/bin/bash
# E1 v2 (review 2026-10-25, Ross "yes to all"; ERRATA "E1 placebo discovery v1"): 3 seeds, one after another, after the
# edge-accounting chain (RAM: one discovery at a time). Worktree ~/CAMARF_e1 (its output/cache/wrds is the placebo
# universe); each seed's outputs are kept in ~/CAMARF_e1_runs/v2_seed<seed>/. research/placebo_discovery_e1.py
set -u
MAIN=~/CAMARF; E=~/CAMARF_e1; RUNS=~/CAMARF_e1_runs; PY=$MAIN/.venv/bin/python
L=$MAIN/logs/latest/latest_run_e1_v2.log; EDGE=$MAIN/logs/latest/latest_run_edge_20261025.log
echo "$(date '+%F %T') E1 v2 waiting for the edge-accounting chain" >> $L
until grep -q "edge accounting complete\|STOPPED\|not starting" $EDGE 2>/dev/null; do sleep 300; done
cd $MAIN && git pull -q --ff-only origin main
mkdir -p $RUNS
# keep v1 (run ad855c8a) before anything is cleared
if [ -d $E/output/research ] && [ ! -d $RUNS/v1_ad855c8a ]; then
  mkdir -p $RUNS/v1_ad855c8a && mv $E/output/research $RUNS/v1_ad855c8a/research
  cp $E/output/cache/wrds/_e1_*.parquet $RUNS/v1_ad855c8a/ 2>/dev/null
fi
cd $E && git checkout -q --detach $(git -C $MAIN rev-parse HEAD) || { echo "checkout failed -- STOPPED" >> $L; exit 1; }
echo "$(date '+%F %T') E1 v2 at $(git log --oneline -1 | cut -c1-60)" >> $L
ln -sfn $MAIN/.venv $E/.venv
clear_outputs() {   # placebo cache and every derived output of the worktree; never the real cache
  local W=$E/output/cache/wrds
  [ -L $W ] && { echo "GUARD: $W is a symlink -- STOPPED" >> $L; exit 1; }
  case "$(realpath -m $W)" in "$(realpath $E)"/*) ;; *) echo "GUARD: $W outside the worktree -- STOPPED" >> $L; exit 1;; esac
  rm -rf $W $E/output/cache/_universe_loader_memo $E/output/results $E/output/lineage $E/output/reports $E/output/research
  mkdir -p $W $E/output/research $E/logs/latest
}
for SEED in 20261024 20261025 20261026; do
  O=$E/output/research
  run() { local name=$1; shift; echo "$(date '+%F %T') [$SEED] START $name" >> $L
    "$@" > $O/_stdout_e1v2_$name.log 2>&1 || { echo "$(date '+%F %T') [$SEED] FAILED $name -- STOPPED" >> $L; exit 1; }
    echo "$(date '+%F %T') [$SEED] done $name" >> $L; }
  clear_outputs
  run build $PY -u research/placebo_discovery_e1.py build --src $MAIN/output/cache/wrds --dst $E/output/cache/wrds --seed $SEED
  # US plants must resolve to their fake PERMNOs with membership spells (else the gate is skipped for them)
  run check_us_plants $PY -c "
import sys, pandas as pd; sys.path.insert(0, '.')
from research.wrds_deep_history_episodic_scan import load_membership_gate
P = pd.read_parquet('output/cache/wrds/_e1_plants.parquet'); us = P[P.arm == 'us']
m, pm = load_membership_gate()
bad = [r.plant for r in us.itertuples() if pm.get(r.plant) is None or m[m.permno == pm[r.plant]].empty]
print(len(us), 'US plants;', len(bad), 'unresolved', bad[:5]); sys.exit(1 if bad or len(us) == 0 else 0)"
  echo "$(date '+%F %T') [$SEED] START discovery" >> $L
  $PY -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude > $O/_stdout_e1v2_discovery.log 2>&1 &
  DPID=$!
  until grep -q "\[TIER 1\] Saved ->" $O/_stdout_e1v2_discovery.log 2>/dev/null || ! kill -0 $DPID 2>/dev/null; do sleep 60; done
  if ! $PY -u research/placebo_discovery_e1.py check_tier1 --research $O --real-research $MAIN/output/research >> $L 2>&1; then
    kill $DPID 2>/dev/null; echo "$(date '+%F %T') [$SEED] GUARD: tier-1 candidate gap -- discovery killed, STOPPED" >> $L; exit 1
  fi
  wait $DPID || { echo "$(date '+%F %T') [$SEED] FAILED discovery -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') [$SEED] done discovery" >> $L
  run adapter $PY -u research/episodic_pairs_adapter.py --fresh
  run comparison_arms $PY -u research/build_comparison_arm_pairs.py
  run pit_eligibility $PY -u research/purity_pit_eligibility.py
  run clean_pools $PY -u research/clean_pool_identity_pairs.py
  run score $PY -u research/placebo_discovery_e1.py score --research $O --dst $E/output/cache/wrds --real-research $MAIN/output/research
  mkdir -p $RUNS/v2_seed$SEED && mv $O $RUNS/v2_seed$SEED/research && cp $E/output/cache/wrds/_e1_*.parquet $RUNS/v2_seed$SEED/
  echo "$(date '+%F %T') [$SEED] seed complete -> $RUNS/v2_seed$SEED" >> $L
done
echo "$(date '+%F %T') E1 v2 complete" >> $L
