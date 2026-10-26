#!/bin/bash
# Edge accounting (Ross 2026-10-25; docs/EDGE_ACCOUNTING_DESIGN_2026-10-25.md): after the Amendment 6 chain -- one heavy job at a time.
cd ~/CAMARF || exit 1
L=logs/latest/latest_run_edge_20261025.log; PY=.venv/bin/python; A6=logs/latest/latest_run_a6_20261025.log
echo "$(date '+%F %T') waiting for the Amendment 6 chain" >> $L
until grep -q "A6 complete\|STOPPED" $A6 2>/dev/null; do sleep 300; done
grep -q "A6 complete" $A6 || { echo "$(date '+%F %T') Amendment 6 chain stopped -- not starting" >> $L; exit 1; }
git pull -q --ff-only origin main
echo "$(date '+%F %T') start: $(git log --oneline -1)" >> $L
$PY seal.py --audit > logs/edge_seal_audit.log 2>&1 || { echo "GUARD: sealed rows in live caches -- STOPPED" >> $L; exit 1; }
run() { local name=$1; shift; echo "$(date '+%F %T') START $name" >> $L
  "$@" > logs/edge_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
run pools   $PY -u research/edge_accounting.py pools
run spreads $PY -u research/edge_accounting.py spreads
run run     $PY -u research/edge_accounting.py run
run eval    $PY -u research/edge_accounting.py eval
echo "$(date '+%F %T') edge accounting complete" >> $L
