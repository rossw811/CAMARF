#!/bin/bash
# Auto-restart wrapper for wrds_deep_history_episodic_scan.py -- relaunches automatically on a
# mem_guard floor-kill (exit 137) instead of requiring manual relaunch each time. Stops relaunching
# once the underlying script exits 0 (genuine completion) or with any other unexpected code (so a
# real bug does not just loop forever silently).
cd ~/CAMARF
ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT+1))
  LOGFILE="logs/wrds_deep_history_episodic_scan_auto_attempt${ATTEMPT}.log"
  echo "[auto_restart] attempt ${ATTEMPT}, logging to ${LOGFILE}"
  .venv/bin/python scripts/mem_guard.py --min-free-gb 10 -- .venv/bin/python research/wrds_deep_history_episodic_scan.py > "${LOGFILE}" 2>&1
  EXIT_CODE=$?
  echo "[auto_restart] attempt ${ATTEMPT} exited with code ${EXIT_CODE}"
  if [ "${EXIT_CODE}" -eq 0 ]; then
    echo "[auto_restart] completed successfully, stopping."
    break
  fi
  if [ "${EXIT_CODE}" -ne 137 ]; then
    echo "[auto_restart] unexpected exit code (not a mem_guard kill) -- stopping rather than looping on a real bug."
    break
  fi
  sleep 5
done
