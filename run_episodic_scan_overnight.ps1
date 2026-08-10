# CAMARF overnight episodic scan runner (2026-08-04)
#
# Prerequisite for Ross's "entire PIT universe" priority: re-runs
# research/wrds_deep_history_episodic_scan.py so its rolling-window output
# carries window_end_date (today's BUG-D106 fix) -- the cached output from
# 2026-07-28 predates that fix and lacks the field entirely (verified
# directly: 0 of 406,924 cached rows have it), so episodic_bhfdr_confirm_asof
# cannot be used on it as-is. This run produces the data that function needs.
#
# Already operates on the FULL WRDS universe's candidate pairs by design
# (load_wrds_universe -> correlation matrix -> candidate_pairs at threshold),
# not just already-confirmed pairs -- no change needed for that part of
# Ross's "discovery scripts on the entire universe" instruction.
#
# Has genuine per-batch checkpointing (checkpoint_every=5, resumable) --
# safer than pit_wfa.py/data_crypto.py's coarser fold/symbol-level
# checkpoints for an unattended overnight run.
#
# Runs independently of the concurrent run_overnight_research.ps1 pipeline
# and the still-active data_crypto.py backfill -- accepted resource-sharing
# risk (workers left at the script's own default of 12, not hand-edited
# here) since this is the only one of the three actually doing sustained
# multiprocessing-pool CPU work; the pipeline's individual stages are fast,
# and crypto backfill is largely network-bound.

$Python = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$LogDir = "logs\overnight"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path "logs\overnight\_episodic_scan_runner.log" -Value "$ts  START episodic scan (full WRDS universe, PIT-fix rebuild)"

& $Python "research\wrds_deep_history_episodic_scan.py" 2>&1 | Tee-Object -FilePath "logs\overnight\episodic_scan.out.log"

$exitCode = $LASTEXITCODE
$ts2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path "logs\overnight\_episodic_scan_runner.log" -Value "$ts2  DONE episodic scan, exit code $exitCode"
