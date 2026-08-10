# CAMARF Session 30 sequential pipeline runner
#
# Runs the full production pipeline plus every Session 30 corrected/modified script,
# STRICTLY ONE AT A TIME. Built after three separate incidents where concurrently-launched
# background jobs were killed simultaneously on this machine (see docs/HANDOFF.md,
# "2026-08-03 update"). Never run two of these stages in parallel.
#
# Resumability: each completed stage appends its name to $StateFile. Re-running the script
# skips stages already recorded there, so a kill at stage 12 does not restart stage 1.
# Use -Fresh to ignore prior state and run everything again.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File run_session30.ps1
#   powershell -ExecutionPolicy Bypass -File run_session30.ps1 -Workers 4
#   powershell -ExecutionPolicy Bypass -File run_session30.ps1 -IncludeData    # also refetch data.py
#   powershell -ExecutionPolicy Bypass -File run_session30.ps1 -Fresh

param(
    [int]$Workers = 6,
    [switch]$IncludeData,
    [switch]$Fresh
)

$ErrorActionPreference = "Continue"

$Python    = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$LogDir    = "logs\session30"
$StateFile = "logs\session30\_completed_stages.txt"
$MasterLog = "logs\session30\_runner.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
if ($Fresh -and (Test-Path $StateFile)) { Remove-Item $StateFile -Force }
if (-not (Test-Path $StateFile)) { New-Item -ItemType File -Path $StateFile | Out-Null }

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Output $line
    Add-Content -Path $MasterLog -Value $line -Encoding utf8
}

# Runs one stage to completion. Returns $true on success.
# Critical stages abort the whole run on failure; non-critical ones are logged and skipped past.
function Invoke-Stage {
    param(
        [string]$Name,
        [string]$Script,
        [string[]]$Arguments = @(),
        [switch]$Critical
    )

    $done = Get-Content $StateFile -ErrorAction SilentlyContinue
    if ($done -contains $Name) {
        Log "SKIP    $Name (already completed)"
        return $true
    }

    $outLog = Join-Path $LogDir "$Name.out.log"
    $errLog = Join-Path $LogDir "$Name.err.log"
    $argLine = ($Arguments -join " ")
    Log "START   $Name  ->  $Script $argLine"
    $t0 = Get-Date

    $allArgs = @($Script) + $Arguments
    $proc = Start-Process -FilePath $Python -ArgumentList $allArgs -NoNewWindow -Wait -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog

    $dur  = [int]((Get-Date) - $t0).TotalMinutes
    $code = $proc.ExitCode

    if ($code -eq 0) {
        Log "DONE    $Name in ${dur} min (exit 0)"
        Add-Content -Path $StateFile -Value $Name -Encoding utf8
        return $true
    }

    Log "FAILED  $Name after ${dur} min (exit $code) - see $errLog"
    if ($Critical) {
        Log "ABORT   $Name is a critical stage; stopping the run."
        exit 1
    }
    return $false
}

Log "================ CAMARF Session 30 runner started (workers=$Workers) ================"
$freeGB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
Log "Free RAM at start: ${freeGB} GB"

# --- Stage 0 (opt-in): data.py refetch -------------------------------------------------
# OFF by default. The post-BUG-D105 data.py run completed 2026-08-02 16:47 and its cache is
# current, so a refetch cannot change the WRDS-vs-yfinance comparison this run exists to produce.
if ($IncludeData) {
    Invoke-Stage -Name "00_data"           -Script "data.py" -Critical
}

# --- Stage 1: the two-handoff blocker --------------------------------------------------
# The WRDS-vs-yfinance comparison. Named as "the next concrete step" in two consecutive
# handoffs and never once completed. Everything downstream depends on it.
Invoke-Stage -Name "01_analysis"           -Script "analysis.py"  -Arguments @("--workers", "$Workers") -Critical

# --- Stage 2: backtest baseline + holdout ----------------------------------------------
Invoke-Stage -Name "02_backtest_is"        -Script "backtest.py"
Invoke-Stage -Name "03_backtest_oos"       -Script "backtest.py" -Arguments @("--holdout")

# --- Stage 3: STORM / sizing variants --------------------------------------------------
$variants = @(
    @("04_storm_session_edge",         "--storm-session-edge"),
    @("05_storm_session_edge_postopen","--storm-session-edge-postopen"),
    @("06_storm_mm_exec",              "--storm-mm-exec"),
    @("07_storm_coint_frac",           "--storm-coint-frac"),
    @("08_storm_all",                  "--storm-all"),
    @("09_hub_weight",                 "--hub-weight"),
    @("10_risk_parity",                "--risk-parity"),
    @("11_pnl_cap",                    "--pnl-cap"),
    @("12_neg_hedge",                  "--neg-hedge")
)
foreach ($v in $variants) {
    Invoke-Stage -Name $v[0] -Script "backtest.py" -Arguments @("--holdout", $v[1])
}

# --- Stage 4: entry-z diagnostic -------------------------------------------------------
Invoke-Stage -Name "13_entryz15_is"        -Script "backtest.py" -Arguments @("--entry-z", "1.5")
Invoke-Stage -Name "14_entryz15_oos"       -Script "backtest.py" -Arguments @("--holdout", "--entry-z", "1.5")

# --- Stage 5: statistics / robustness --------------------------------------------------
Invoke-Stage -Name "15_stats"              -Script "stats.py"
Invoke-Stage -Name "16_wfa"                -Script "wfa.py"
Invoke-Stage -Name "17_distance"           -Script "distance.py"
Invoke-Stage -Name "18_sensitivity"        -Script "sensitivity.py"
Invoke-Stage -Name "19_deflated_sharpe"    -Script "deflated_sharpe.py"
Invoke-Stage -Name "20_report"             -Script "report.py"

# --- Stage 6: Session 30 comparison arms -----------------------------------------------
# All five were built and synthetically verified last session; the SVM arm is the one that
# never produced real-data output (its run collided with a concurrent analysis.py rerun).
Invoke-Stage -Name "21_cycle_detection"    -Script "research\cycle_detection.py"
Invoke-Stage -Name "22_levy_jump"          -Script "research\levy_jump_diffusion.py"
Invoke-Stage -Name "23_rough_vol"          -Script "research\rough_volatility.py"
Invoke-Stage -Name "24_options_greeks"     -Script "research\options_greeks_features.py"
Invoke-Stage -Name "25_svm_classifier"     -Script "research\svm_gradient_descent_classifier.py"

# --- Stage 7: point-in-time re-screen --------------------------------------------------
# Multi-hour (~45-50 min/fold, 4 folds). Its own checkpoint does NOT resume a partial run,
# so this restarts from fold 1 every time it is killed. Placed late deliberately: everything
# above finishes first, so a kill here costs only this stage.
Invoke-Stage -Name "26_pit_wfa"            -Script "pit_wfa.py" -Arguments @("--workers", "$Workers")

# --- Stage 8: crypto backfill ----------------------------------------------------------
# Has never survived a full run (three attempts, zero bars persisted). Last because it is
# supplemental and nothing else depends on it.
Invoke-Stage -Name "27_data_crypto"        -Script "data_crypto.py"

Log "================ CAMARF Session 30 runner finished ================"
$doneCount = (Get-Content $StateFile | Measure-Object -Line).Lines
Log "Stages completed this run or earlier: $doneCount"
