#!/bin/bash
# 2026-10-07 chain (CachyOS): primary episodic scan re-run on corrected volume (offset 0, --fresh moves the old
# outputs to a backup dir), then the grid-phase robustness offsets, then the pre-declared report.
# stdout goes to separate _stdout files -- never to the scan's own log name (that is how the primary log was lost).
cd ~/CAMARF || exit 1
L=latest_run_grid_chain.log
S=output/research
echo "$(date '+%F %T') chain start: $(git log --oneline -1)" >> $L
echo "$(date '+%F %T') primary (offset 0, exclude) --fresh" >> $L
.venv/bin/python -u research/wrds_deep_history_episodic_scan.py --fresh --d18 exclude > $S/_stdout_episodic_scan.log 2>&1 \
  || { echo "$(date '+%F %T') primary FAILED -- STOPPED" >> $L; exit 1; }
echo "$(date '+%F %T') primary done" >> $L
for o in 63 126 189; do
  echo "$(date '+%F %T') grid offset $o" >> $L
  .venv/bin/python -u research/wrds_deep_history_episodic_scan.py --d18 exclude --grid-offset $o > $S/_stdout_episodic_scan_grid$o.log 2>&1 \
    || { echo "$(date '+%F %T') grid $o FAILED -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') grid offset $o done" >> $L
done
PYTHONPATH=. .venv/bin/python research/grid_phase_robustness.py >> $L 2>&1
echo "$(date '+%F %T') chain complete" >> $L
