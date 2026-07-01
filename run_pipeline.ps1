# CAMARF full pipeline runner — Session 22
# Waits for data.py (already running), then chains analysis.py → backtest variants → stats → wfa → report
param([int]$DataPid = 0)

$python = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$log = "pipeline_runner.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $msg" | Tee-Object -Append $log
}

Log "=== CAMARF Pipeline Runner started ==="

# --- Wait for data.py ---
if ($DataPid -gt 0) {
    Log "Waiting for data.py (PID $DataPid) to finish..."
    try {
        Wait-Process -Id $DataPid -ErrorAction Stop
        Log "data.py completed."
    } catch {
        Log "data.py PID not found — assuming already complete."
    }
} else {
    Log "No DataPid given — assuming data.py already complete."
}

# --- analysis.py ---
Log "Starting analysis.py..."
$t0 = Get-Date
& $python analysis.py 2>&1 | Tee-Object -Append $log
$dur = [int]((Get-Date) - $t0).TotalMinutes
Log "analysis.py done in ${dur} min. Exit: $LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { Log "ERROR: analysis.py failed. Stopping pipeline."; exit 1 }

# --- backtest.py: IS baseline (OLS + Kalman) ---
Log "Starting backtest.py IS baseline..."
& $python backtest.py 2>&1 | Tee-Object -Append $log
Log "backtest.py IS done. Exit: $LASTEXITCODE"

# --- backtest.py: OOS holdout ---
Log "Starting backtest.py OOS holdout..."
& $python backtest.py --holdout 2>&1 | Tee-Object -Append $log
Log "backtest.py OOS done. Exit: $LASTEXITCODE"

# --- backtest.py: STORM variants (holdout) ---
$variants = @(
    @("--storm-session-edge",         "session_edge"),
    @("--storm-session-edge-postopen", "session_edge_postopen"),
    @("--storm-mm-exec",              "mm_exec"),
    @("--storm-coint-frac",           "coint_frac_sizing"),
    @("--storm-all",                  "storm_all"),
    @("--hub-weight",                 "hub_weight"),
    @("--risk-parity",                "risk_parity"),
    @("--pnl-cap",                    "pnl_cap"),
    @("--neg-hedge",                  "neg_hedge")
)
foreach ($v in $variants) {
    $flag = $v[0]; $name = $v[1]
    Log "Starting backtest.py --holdout $flag ($name)..."
    & $python backtest.py --holdout $flag 2>&1 | Tee-Object -Append $log
    Log "backtest.py --holdout $flag done. Exit: $LASTEXITCODE"
}

# --- backtest.py: z=1.5 diagnostic for DD pairs ---
Log "Starting backtest.py IS --entry-z 1.5 (DD pair diagnostic)..."
& $python backtest.py --entry-z 1.5 2>&1 | Tee-Object -Append $log
Log "backtest.py entry-z 1.5 IS done."

Log "Starting backtest.py OOS --entry-z 1.5 (DD pair diagnostic)..."
& $python backtest.py --holdout --entry-z 1.5 2>&1 | Tee-Object -Append $log
Log "backtest.py entry-z 1.5 OOS done."

# --- stats.py ---
Log "Starting stats.py..."
& $python stats.py 2>&1 | Tee-Object -Append $log
Log "stats.py done. Exit: $LASTEXITCODE"

# --- wfa.py ---
Log "Starting wfa.py..."
& $python wfa.py 2>&1 | Tee-Object -Append $log
Log "wfa.py done. Exit: $LASTEXITCODE"

# --- distance.py ---
Log "Starting distance.py..."
& $python distance.py 2>&1 | Tee-Object -Append $log
Log "distance.py done. Exit: $LASTEXITCODE"

# --- sensitivity.py ---
Log "Starting sensitivity.py..."
& $python sensitivity.py 2>&1 | Tee-Object -Append $log
Log "sensitivity.py done. Exit: $LASTEXITCODE"

# --- report.py ---
Log "Starting report.py..."
& $python report.py 2>&1 | Tee-Object -Append $log
Log "report.py done. Exit: $LASTEXITCODE"

Log "=== Pipeline complete ==="
