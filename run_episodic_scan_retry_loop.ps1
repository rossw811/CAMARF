# CAMARF intraday episodic scan retry-until-success loop (2026-08-11)
#
# WHY THIS EXISTS: research/intraday_episodic_scan.py --tf both has been killed
# repeatedly by an unexplained external cause (investigated directly --
# Windows Event Viewer, power settings, memory, disk, all checked and clean
# at the exact kill timestamps, no OS-level explanation found) while launched
# via Claude's own Bash tool run_in_background mechanism. The script's own
# internal checkpointing (atomic writes, per-tier disk persistence) makes
# each resume cheap and safe -- this wraps that in an OUTER, fully-detached
# retry loop (Start-Process, same pattern run_overnight_research.ps1 already
# uses successfully) so it keeps resuming unattended without needing a Claude
# session alive to notice each kill and manually relaunch, AND to test
# whether a Start-Process-launched detached process is immune to whatever
# has been killing Bash-tool-launched ones (a real, untested hypothesis, not
# assumed to fix it).
#
# Stops when the underlying script exits 0 (genuinely complete: both 1h and
# 4h, all tiers) or after $MaxAttempts retries (safety backstop against an
# infinite loop on a real, non-transient bug rather than an external kill).
#
# Usage (from an already-running session, fully detached):
#   Start-Process powershell.exe -ArgumentList "-ExecutionPolicy","Bypass","-NonInteractive","-File","run_episodic_scan_retry_loop.ps1" -WindowStyle Hidden

param(
    [int]$Workers = 6,   # reduced from 8 (2026-08-11): this loop and
                          # run_overnight_research.ps1 run concurrently most
                          # of the night on a 12-PHYSICAL-core machine
                          # (Snapdragon X1E80100, no SMT). Combined worst-case
                          # load is now 6 (here) + 4 (research runner) = 10,
                          # leaving 2 cores free rather than the old 8+6=14
                          # oversubscription.
    [int]$MaxAttempts = 100
)

$ErrorActionPreference = "Continue"
$Python = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$LogDir = "logs\overnight"
$MasterLog = "logs\overnight\_episodic_retry_loop.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Output $line
    Add-Content -Path $MasterLog -Value $line -Encoding utf8
}

Log "================ Episodic scan retry loop started (workers=$Workers, max attempts=$MaxAttempts) ================"

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $outLog = Join-Path $LogDir "episodic_scan_attempt_$attempt.out.log"
    $errLog = Join-Path $LogDir "episodic_scan_attempt_$attempt.err.log"
    Log "ATTEMPT $attempt / $MaxAttempts -- launching intraday_episodic_scan.py --tf both --workers $Workers"
    $t0 = Get-Date

    # Same event-based async-read pattern run_overnight_research.ps1 already
    # established as the working one on this runtime (Start-Process -PassThru
    # and raw ReadToEndAsync().Result both failed live, see that script's own
    # comments) -- reused verbatim, not rediscovered.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Python
    $psi.Arguments = "research\intraday_episodic_scan.py --tf both --workers $Workers"
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
    $proc.WaitForExit()  # no timeout here -- this script's job IS to babysit an unbounded-length run

    Start-Sleep -Milliseconds 500
    $outWriter.Close(); $errWriter.Close()
    Get-EventSubscriber | Where-Object { $_.SourceObject -eq $proc } | Unregister-Event

    $dur = [int]((Get-Date) - $t0).TotalMinutes
    if ($proc.ExitCode -eq 0) {
        Log "SUCCESS attempt $attempt finished in ${dur} min (exit 0) -- episodic scan genuinely complete, stopping loop."
        break
    } else {
        Log "ENDED   attempt $attempt after ${dur} min (exit $($proc.ExitCode)) -- resuming via next attempt (checkpoints/per-tier saves make this cheap)."
    }
}

Log "================ Episodic scan retry loop finished ================"
