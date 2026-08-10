# CAMARF overnight research pipeline runner (2026-08-03/04)
#
# Runs every non-data-fetch script in the project, strictly sequentially,
# unattended, independent of any Claude session -- launched via Start-Process
# so it is a fully detached OS process that survives regardless of what
# happens to the terminal/session that started it.
#
# SCOPE, exactly as specified:
#   EXCLUDED: data.py, data_wrds.py, data_ibkr.py, data_crypto.py (the
#     data-FETCH layer -- needs live network/WRDS-VPN/IBKR connections,
#     matches the "not including wrds ibkr or data.py" instruction)
#   EXCLUDED: analysis.py (skip this time, per explicit instruction)
#   EXCLUDED (same reasoning as the data-fetch layer, found while scoping
#     this script, not explicitly named by Ross but same category): macro.py
#     (imports `requests`, live FRED fetch) and seed_sp_caches.py (live
#     Wikipedia scraper). Flagged here, not silently dropped -- if these were
#     meant to be included, re-run this script with them added back.
#   EXCLUDED: library-only modules with no __main__ block (portfolio_math.py,
#     trial_registry.py, earnings.py, ibkr_supplement_reader.py) -- not
#     runnable standalone, nothing to execute.
#   INCLUDED: every other root-level runnable script (backtest.py all
#     variants, stats/wfa/distance/sensitivity/deflated_sharpe/report,
#     pit_wfa.py, ml.py, run_storm_grid.py, run_verify_suite.py,
#     fresh_holdout_compare.py, reproduce.py, absorption_ratio.py, cvar.py,
#     decay_proxy.py, portfolio_sim.py, survivorship.py, options.py, gics.py)
#     plus EVERY research\*.py script, discovered dynamically via
#     Get-ChildItem (121 as of this writing) -- verified none of them import
#     `requests` or open a live WRDS/IBKR connection (grepped directly, not
#     assumed), so all should run safely off already-cached data.
#
# Resumability: same pattern as run_session30.ps1 (proven working today) --
# each completed stage is appended to $StateFile; re-running this script
# skips stages already recorded there. Use -Fresh to ignore prior state.
#
# Per-stage timeout: unlike run_session30.ps1, this run is unattended
# overnight and includes ~140 scripts of widely varying and unknown
# runtime -- a single hung script must not consume the whole night. Each
# stage is killed and marked FAILED (not fatal -- the run continues) if it
# exceeds $TimeoutMinutes.
#
# Usage (from an already-running session):
#   Start-Process powershell.exe -ArgumentList "-ExecutionPolicy","Bypass","-NonInteractive","-File","run_overnight_research.ps1" -WindowStyle Hidden

param(
    [int]$Workers = 6,
    [int]$TimeoutMinutes = 45,
    [switch]$Fresh
)

$ErrorActionPreference = "Continue"

$Python    = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$LogDir    = "logs\overnight"
$StateFile = "logs\overnight\_completed_stages.txt"
$MasterLog = "logs\overnight\_runner.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
if ($Fresh -and (Test-Path $StateFile)) { Remove-Item $StateFile -Force }
if (-not (Test-Path $StateFile)) { New-Item -ItemType File -Path $StateFile | Out-Null }

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Output $line
    Add-Content -Path $MasterLog -Value $line -Encoding utf8
}

function Invoke-Stage {
    param(
        [string]$Name,
        [string]$Script,
        [string[]]$Arguments = @()
    )

    $done = Get-Content $StateFile -ErrorAction SilentlyContinue
    if ($done -contains $Name) {
        Log "SKIP    $Name (already completed)"
        return
    }

    $outLog = Join-Path $LogDir "$Name.out.log"
    $errLog = Join-Path $LogDir "$Name.err.log"
    $argLine = ($Arguments -join " ")
    Log "START   $Name  ->  $Script $argLine"
    $t0 = Get-Date

    # Raw System.Diagnostics.Process with EVENT-based async output reading
    # (OutputDataReceived/ErrorDataReceived + BeginOutputReadLine), the
    # standard .NET idiom for timeout+redirection together. Two earlier
    # approaches both failed, found live, in order:
    #   1. Start-Process -PassThru: ExitCode read back EMPTY after a timed
    #      WaitForExit(), even with the documented Refresh() fix --
    #      misreported a real, successful run (PNC/ZION 5 trades, SR=68.80
    #      in the actual log) as FAILED.
    #   2. Raw Process + ReadToEndAsync().Result: deadlocked -- Windows
    #      PowerShell 5.1's synchronous execution model doesn't pump the
    #      .NET Task continuation machinery while blocked in WaitForExit,
    #      so the async read task's .Result never resolved (confirmed: the
    #      child python.exe process had already exited per Get-CimInstance,
    #      but the outer script never logged DONE/FAILED -- classic
    #      redirected-stream deadlock).
    # Event-based reading avoids both: output is drained continuously by
    # the runtime's own I/O completion callbacks, not by a blocked .Result.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Python
    $allArgs = @($Script) + $Arguments
    # ProcessStartInfo.ArgumentList (a collection, no manual quoting needed)
    # is a newer .NET Core-only API -- it comes back NULL in this Windows
    # PowerShell 5.1 / .NET Framework environment, found live: every
    # .ArgumentList.Add() call errored, and the process launched with NO
    # arguments at all (silently dropped into the bare python.exe
    # interactive REPL instead of running the intended script). Use the
    # classic .Arguments STRING property instead, with manual quoting for
    # any argument containing whitespace or a double quote.
    $quotedArgs = $allArgs | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }
    $psi.Arguments = ($quotedArgs -join " ")
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.WorkingDirectory = (Get-Location).Path

    $outWriter = New-Object System.IO.StreamWriter($outLog, $false)
    $errWriter = New-Object System.IO.StreamWriter($errLog, $false)
    $outWriter.AutoFlush = $true
    $errWriter.AutoFlush = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $proc.EnableRaisingEvents = $true
    Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
        if ($null -ne $Event.SourceEventArgs.Data) { $Event.MessageData.WriteLine($Event.SourceEventArgs.Data) }
    } -MessageData $outWriter | Out-Null
    Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
        if ($null -ne $Event.SourceEventArgs.Data) { $Event.MessageData.WriteLine($Event.SourceEventArgs.Data) }
    } -MessageData $errWriter | Out-Null

    $proc.Start() | Out-Null
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    $exited = $proc.WaitForExit($TimeoutMinutes * 60 * 1000)
    $dur = [int]((Get-Date) - $t0).TotalMinutes

    if (-not $exited) {
        Log "TIMEOUT $Name after ${TimeoutMinutes} min -- killing and moving on"
        # $proc.Kill($true) is a .NET 5+/Core-only overload (kills the
        # entire process tree) -- SILENTLY DOES NOTHING on Windows
        # PowerShell 5.1's .NET Framework runtime, which only has the
        # parameterless Kill() (single process, no children). Found live,
        # the hard way: 31_run_verify_suite timed out at 02:02, this call
        # threw internally and was swallowed by the catch{}, and the
        # process (plus a downstream analysis.py --workers 12 it/a sibling
        # stage had spawned) kept running fully unsupervised for 5+ hours,
        # consuming 2.7GB+ and driving free RAM down to ~0.3GB overnight
        # before being found and killed manually. taskkill /T /F is the
        # correct, verified-working tree-kill on this runtime.
        try { & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null } catch {}
        Start-Sleep -Milliseconds 500
        $outWriter.Close(); $errWriter.Close()
        Get-EventSubscriber | Where-Object { $_.SourceObject -eq $proc } | Unregister-Event
        return
    }

    Start-Sleep -Milliseconds 500  # let final async event callbacks land before closing
    $outWriter.Close(); $errWriter.Close()
    Get-EventSubscriber | Where-Object { $_.SourceObject -eq $proc } | Unregister-Event

    if ($proc.ExitCode -eq 0) {
        Log "DONE    $Name in ${dur} min (exit 0)"
        Add-Content -Path $StateFile -Value $Name -Encoding utf8
    } else {
        Log "FAILED  $Name after ${dur} min (exit $($proc.ExitCode)) - see $errLog"
    }
}

Log "================ CAMARF overnight research runner started (workers=$Workers, timeout=${TimeoutMinutes}min/stage) ================"
$freeGB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
Log "Free RAM at start: ${freeGB} GB"

# --- Core production pipeline (analysis.py's output from today's run is reused as-is) ---
Invoke-Stage -Name "01_backtest_is"          -Script "backtest.py"
Invoke-Stage -Name "02_backtest_oos"         -Script "backtest.py" -Arguments @("--holdout")
$variants = @(
    @("03_storm_session_edge",          "--storm-session-edge"),
    @("04_storm_session_edge_postopen", "--storm-session-edge-postopen"),
    @("05_storm_mm_exec",               "--storm-mm-exec"),
    @("06_storm_coint_frac",            "--storm-coint-frac"),
    @("07_storm_all",                   "--storm-all"),
    @("08_hub_weight",                  "--hub-weight"),
    @("09_risk_parity",                 "--risk-parity"),
    @("10_pnl_cap",                     "--pnl-cap"),
    @("11_neg_hedge",                   "--neg-hedge")
)
foreach ($v in $variants) {
    Invoke-Stage -Name $v[0] -Script "backtest.py" -Arguments @("--holdout", $v[1])
}
Invoke-Stage -Name "12_entryz15_is"   -Script "backtest.py" -Arguments @("--entry-z", "1.5")
Invoke-Stage -Name "13_entryz15_oos"  -Script "backtest.py" -Arguments @("--holdout", "--entry-z", "1.5")
Invoke-Stage -Name "14_stats"         -Script "stats.py"
Invoke-Stage -Name "15_wfa"           -Script "wfa.py"
Invoke-Stage -Name "16_distance"      -Script "distance.py"
Invoke-Stage -Name "17_sensitivity"   -Script "sensitivity.py"
Invoke-Stage -Name "18_deflated_sharpe" -Script "deflated_sharpe.py"
Invoke-Stage -Name "19_report"        -Script "report.py"
Invoke-Stage -Name "20_ml"            -Script "ml.py"
Invoke-Stage -Name "21_run_storm_grid" -Script "run_storm_grid.py"
Invoke-Stage -Name "22_fresh_holdout_compare" -Script "fresh_holdout_compare.py"
Invoke-Stage -Name "23_absorption_ratio" -Script "absorption_ratio.py"
Invoke-Stage -Name "24_cvar"          -Script "cvar.py"
Invoke-Stage -Name "25_decay_proxy"   -Script "decay_proxy.py"
Invoke-Stage -Name "26_portfolio_sim" -Script "portfolio_sim.py"
Invoke-Stage -Name "27_survivorship"  -Script "survivorship.py"
Invoke-Stage -Name "28_options"       -Script "options.py"
Invoke-Stage -Name "29_gics"          -Script "gics.py"
Invoke-Stage -Name "30_reproduce"     -Script "reproduce.py" -Arguments @("--verify-only")
Invoke-Stage -Name "31_run_verify_suite" -Script "run_verify_suite.py"

# --- Every research/*.py script, discovered dynamically (not hardcoded) ---
$researchScripts = Get-ChildItem -Path "research" -Filter "*.py" | Sort-Object Name
$i = 100
foreach ($rs in $researchScripts) {
    $stageName = "r{0:D3}_{1}" -f $i, ($rs.BaseName)
    Invoke-Stage -Name $stageName -Script ("research\" + $rs.Name)
    $i++
}

# --- The most expensive single item, placed last: if still running or timed
# out, everything else has already completed and produced fresh output. ---
Invoke-Stage -Name "99_pit_wfa" -Script "pit_wfa.py" -Arguments @("--workers", "$Workers")

Log "================ CAMARF overnight research runner finished ================"
$doneCount = (Get-Content $StateFile | Measure-Object -Line).Lines
Log "Stages completed: $doneCount"
