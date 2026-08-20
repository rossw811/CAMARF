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
    [int]$Workers = 10,  # 2026-08-11: this is now the ONLY orchestrator running
                          # (the separate parallel episodic-scan loop was retired
                          # and consolidated into stage 00 below, sequential, not
                          # concurrent) -- no second process to share cores with,
                          # so use most of this 12-PHYSICAL-core machine
                          # (Snapdragon X1E80100, no SMT -- 12 is the real hard
                          # limit), leaving 2 cores free for the OS rather than
                          # the intermediate 4/6-split used while two orchestrators
                          # ran concurrently.
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
        [string[]]$Arguments = @(),
        [int]$TimeoutOverrideMinutes = 0   # 0 = use the script-wide $TimeoutMinutes default
    )

    $done = Get-Content $StateFile -ErrorAction SilentlyContinue
    if ($done -contains $Name) {
        Log "SKIP    $Name (already completed)"
        return
    }
    $effectiveTimeout = if ($TimeoutOverrideMinutes -gt 0) { $TimeoutOverrideMinutes } else { $TimeoutMinutes }

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

    $exited = $proc.WaitForExit($effectiveTimeout * 60 * 1000)
    $dur = [int]((Get-Date) - $t0).TotalMinutes

    if (-not $exited) {
        Log "TIMEOUT $Name after ${effectiveTimeout} min -- killing and moving on"
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

function Invoke-StageUntilSuccess {
    # For a genuinely long-running, resumable-via-its-own-checkpoint script
    # (research/intraday_episodic_scan.py -- atomic per-tier checkpointing,
    # BUG-D108 fix) where a single Invoke-Stage timeout would just discard
    # partial progress and never actually finish. Loops re-launching the
    # SAME script (no timeout -- the underlying script's own checkpoints are
    # what make each relaunch cheap, not an outer time limit) until it exits
    # 0 or $MaxAttempts is reached. Absorbs what used to be a SEPARATE,
    # PARALLEL process (run_episodic_scan_retry_loop.ps1) -- consolidated
    # here 2026-08-11 per Ross's explicit direction that the intraday scan
    # must run and complete BEFORE the adapter/ML/PIT-backtest stages, not
    # alongside them; running both concurrently also meant two processes
    # contending for the same checkpoint files.
    param(
        [string]$Name,
        [string]$Script,
        [string[]]$Arguments = @(),
        [int]$MaxAttempts = 100
    )

    $done = Get-Content $StateFile -ErrorAction SilentlyContinue
    if ($done -contains $Name) {
        Log "SKIP    $Name (already completed)"
        return
    }

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $outLog = Join-Path $LogDir "$Name.attempt$attempt.out.log"
        $errLog = Join-Path $LogDir "$Name.attempt$attempt.err.log"
        $argLine = ($Arguments -join " ")
        Log "START   $Name attempt $attempt/$MaxAttempts  ->  $Script $argLine"
        $t0 = Get-Date

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Python
        $allArgs = @($Script) + $Arguments
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
        $proc.WaitForExit()  # no timeout -- babysitting an unbounded-length run is the point

        Start-Sleep -Milliseconds 500
        $outWriter.Close(); $errWriter.Close()
        Get-EventSubscriber | Where-Object { $_.SourceObject -eq $proc } | Unregister-Event

        $dur = [int]((Get-Date) - $t0).TotalMinutes
        if ($proc.ExitCode -eq 0) {
            Log "DONE    $Name in ${dur} min on attempt $attempt (exit 0)"
            Add-Content -Path $StateFile -Value $Name -Encoding utf8
            return
        } else {
            Log "ENDED   $Name attempt $attempt after ${dur} min (exit $($proc.ExitCode)) -- retrying (checkpoints make this cheap)"
        }
    }
    Log "GAVE UP on $Name after $MaxAttempts attempts -- moving on without marking it complete"
}

Log "================ CAMARF overnight research runner started (workers=$Workers, timeout=${TimeoutMinutes}min/stage) ================"
$freeGB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
Log "Free RAM at start: ${freeGB} GB"

# --- ADDED 2026-08-11, Ross's explicit order: the intraday episodic scan
# (the pipeline already running before the earlier usage-limit interruption)
# runs to completion FIRST -- not in parallel, not deferred -- so the
# adapter/ML/PIT-backtest stages that follow use the COMPLETE episodic
# universe (WRDS/1D + intraday 1h/4h), not just WRDS/1D. Uses
# Invoke-StageUntilSuccess (no per-attempt timeout, retries via the script's
# own atomic checkpointing) since a single 45-min Invoke-Stage timeout would
# never let this genuinely multi-hour scan finish.
Invoke-StageUntilSuccess -Name "00_intraday_episodic_scan" -Script "research\intraday_episodic_scan.py" -Arguments @("--tf", "both", "--workers", "$Workers")

# ML trains fully BEFORE any backtest run (Ross's explicit gate). The
# adapter stage builds the real pairs.parquet-schema + spread_series data
# ml.py --pit-safe's fallback path needs (see research/episodic_pairs_
# adapter.py / ml.py's build() docstring) from BOTH the WRDS/1D episodic
# scan (647 pairs, already complete) and the intraday scan that just
# finished above -- its main() already checks for and includes whichever
# sources exist on disk, no separate WRDS-only invocation needed.
# -TimeoutOverrideMinutes 240 (added 2026-08-11): a live overnight run showed
# this stage is genuinely CPU-bound for far longer than 45 min -- it builds
# two full DataAligner.align_universe + AnalysisPipeline._build_pair_result
# passes (truncated + full history) per PIT-confirmed pair, sequentially,
# single-threaded (n_workers=1 in build_one_row's rolling_fraction call).
# The 647-pair WRDS/1D source alone is the bulk of the cost; some pairs with
# very long history (e.g. 13,000+ daily sessions since the 1970s) take
# materially longer per pair than the ~10-20s typical case. The 45-min
# default silently killed this stage before it produced any output, which
# then propagated into 00b_ml_pit_safe silently falling back to
# discover_pit_confirmed_pairs() (647 pairs, no scalar fields) instead of
# the adapter's PIT-safe output -- not a crash, just wrong/incomplete data
# flowing downstream. Not a mystery kill like Step 2's -- this one was our
# own runner's per-stage timeout doing exactly what it's configured to do.
Invoke-Stage -Name "00a_episodic_adapter" -Script "research\episodic_pairs_adapter.py" -TimeoutOverrideMinutes 240
Invoke-Stage -Name "00b_ml_pit_safe"      -Script "ml.py" -Arguments @("--pit-safe")

# --- ADDED 2026-08-11, Ross's explicit re-prioritization: PIT-safe backtest
# (pit_wfa.py) runs BEFORE the regular backtest.py suite, not after -- was
# previously placed last in this file specifically because it's "the most
# expensive single item" (see the comment that used to sit at the bottom of
# this file, now moved here since the reasoning moved with the stage). That
# reasoning still applies to its RUNTIME (already observed hitting the old
# uniform 45-min stage timeout without finishing, and separately documented
# elsewhere in this project as a ~2.5-hour run) but not to its PRIORITY --
# given a longer, dedicated timeout via -TimeoutOverrideMinutes instead of
# silently keeping the same 45-min budget that already proved too short.
Invoke-Stage -Name "00c_pit_wfa" -Script "pit_wfa.py" -Arguments @("--workers", "$Workers") -TimeoutOverrideMinutes 180

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

Log "================ CAMARF overnight research runner finished ================"
$doneCount = (Get-Content $StateFile | Measure-Object -Line).Lines
Log "Stages completed: $doneCount"
