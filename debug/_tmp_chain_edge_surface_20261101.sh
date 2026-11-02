#!/bin/bash
# Edge accounting re-run (Ross 2026-10-26 decision 3, "yes to all" 10-27) on the SURFACE, after the Amendment 7 chain:
# BUG-D121 commission fix in the dollar P&L, each arm on its own span + same-era decomposition (c3cd4bd4). All four
# phases, because Amendment 7 rebuilds discovery, the pools and output/results. The 10-25 outputs are kept.
cd /c/Users/RossW/Projects/CAMARF || exit 1
L=logs/latest/latest_run_edge_surface_20261101.log; S=output/research; PY=/c/Users/RossW/anaconda3/envs/trading/python.exe
A7=logs/latest/latest_run_rerun_a7_surface_20261028.log
export PYTHONUTF8=1
echo "$(date '+%F %T') waiting for the Amendment 7 chain" >> $L
until grep -q "chain complete\|STOPPED" $A7 2>/dev/null; do sleep 300; done
grep -q "chain complete" $A7 || { echo "$(date '+%F %T') Amendment 7 chain stopped -- not starting" >> $L; exit 1; }
echo "$(date '+%F %T') start: $(git log --oneline -1)" >> $L
K=$S/_superseded_edge_20261025; mkdir -p $K
for f in $S/edge_accounting_*.parquet; do cp -n "$f" $K/ || exit 1; done
[ -d output/results_wholehistory ] && { [ -e $K/results_wholehistory ] || cp -r output/results_wholehistory $K/results_wholehistory || exit 1; }
echo "$(date '+%F %T') 10-25 outputs kept in $K" >> $L
$PY seal.py --audit > logs/edge_surface_seal_audit.log 2>&1 || { echo "GUARD: sealed rows in live caches -- STOPPED" >> $L; exit 1; }
run() { local name=$1; shift; echo "$(date '+%F %T') START $name" >> $L
  "$@" > logs/edge_surface_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
run pools   $PY -u research/edge_accounting.py pools
run spreads $PY -u research/edge_accounting.py spreads
run run     $PY -u research/edge_accounting.py run
run eval    $PY -u research/edge_accounting.py eval
echo "$(date '+%F %T') edge accounting complete" >> $L
