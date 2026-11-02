#!/bin/bash
# CachyOS queue 2026-11-02 (Ross: "yes run them on cachy"), one heavy job at a time:
#   1. Amendment 7 chain (debug/_tmp_chain_a7_cachyos_20261102.sh) -- the registered result
#   2. edge accounting, all four phases (commission fix + own-span / same-era eval), 10-25 outputs kept
#   3. E1 v2, 3 seeds (debug/_tmp_chain_e1_v2_20261102.sh); its false share is re-scored against the A7 windows
# A step that does not complete stops the queue.
cd ~/CAMARF || exit 1
Q=logs/latest/latest_run_queue_cachyos_20261102.log; S=output/research; PY=.venv/bin/python
A7=logs/latest/latest_run_rerun_a7_cachyos_20261102.log
echo "$(date '+%F %T') queue start: $(git log --oneline -1 | cut -c1-70)" >> $Q
bash debug/_tmp_chain_a7_cachyos_20261102.sh
grep -q "chain complete" $A7 || { echo "$(date '+%F %T') Amendment 7 chain did not complete -- queue STOPPED" >> $Q; exit 1; }
echo "$(date '+%F %T') Amendment 7 chain complete" >> $Q

E=logs/latest/latest_run_edge_cachyos_20261102.log
K=$S/_superseded_edge_20261025; mkdir -p $K
for f in $S/edge_accounting_*.parquet; do cp -n "$f" $K/ || exit 1; done
[ -d output/results_wholehistory ] && { [ -e $K/results_wholehistory ] || cp -r output/results_wholehistory $K/results_wholehistory || exit 1; }
echo "$(date '+%F %T') edge: 10-25 outputs kept in $K" >> $E
$PY seal.py --audit > logs/edge_cachyos_seal_audit.log 2>&1 || { echo "GUARD: sealed rows in live caches -- STOPPED" >> $E; echo "edge STOPPED" >> $Q; exit 1; }
for ph in pools spreads run eval; do
  echo "$(date '+%F %T') START $ph" >> $E
  $PY -u research/edge_accounting.py $ph > logs/edge_cachyos_$ph.log 2>&1 \
    || { echo "$(date '+%F %T') FAILED $ph -- STOPPED" >> $E; echo "$(date '+%F %T') edge STOPPED -- queue STOPPED" >> $Q; exit 1; }
  echo "$(date '+%F %T') done $ph" >> $E
done
echo "$(date '+%F %T') edge accounting complete" >> $E
echo "$(date '+%F %T') edge accounting complete" >> $Q

bash debug/_tmp_chain_e1_v2_20261102.sh
echo "$(date '+%F %T') E1 v2 chain exited: $(tail -1 logs/latest/latest_run_e1_v2_20261102.log)" >> $Q
