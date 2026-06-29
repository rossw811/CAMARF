param([int]$AnalysisPid = 0)

$py   = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$proj = "C:\Users\RossW\Projects\CAMARF"
Set-Location $proj

# Start analysis.py if no PID was supplied
if ($AnalysisPid -eq 0) {
    Write-Host "$(Get-Date -Format 'HH:mm:ss') Starting analysis.py..."
    $ap = Start-Process -FilePath $py -ArgumentList "analysis.py" `
              -WorkingDirectory $proj -PassThru -WindowStyle Normal
    $AnalysisPid = $ap.Id
    Write-Host "$(Get-Date -Format 'HH:mm:ss') analysis.py PID: $AnalysisPid"
}

# Wait for analysis.py to finish
Write-Host "$(Get-Date -Format 'HH:mm:ss') Waiting for analysis.py (PID $AnalysisPid)..."
while (Get-Process -Id $AnalysisPid -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 30
    $done = (Get-ChildItem output\results -Directory |
             Where-Object { $_.Name -notmatch 'stale' -and $_.Name -notmatch 'json' }).Count
    Write-Host "$(Get-Date -Format 'HH:mm:ss') Still running... TF dirs complete: $done"
}
Write-Host "$(Get-Date -Format 'HH:mm:ss') analysis.py finished. Starting comparison runs."

Write-Host ""
Write-Host "$(Get-Date -Format 'HH:mm:ss') [1/6] IS baseline (refreshes trades_layer1.parquet for calibration)..."
& $py backtest.py 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [2/6] Holdout baseline..."
& $py backtest.py --holdout 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [3/6] Holdout + hub-weight..."
& $py backtest.py --holdout --hub-weight 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [4/6] Holdout + P&L cap..."
& $py backtest.py --holdout --pnl-cap 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [5/6] Holdout + risk-parity..."
& $py backtest.py --holdout --risk-parity 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [6/8] Holdout + neg-hedge..."
& $py backtest.py --holdout --neg-hedge 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [7/8] Training ML meta-labeler (ml.py)..."
& $py ml.py 2>&1
Write-Host "$(Get-Date -Format 'HH:mm:ss') [8/8] Holdout + Layer 2 ML gate..."
& $py backtest.py --holdout --layer2 2>&1

Write-Host ""
Write-Host "$(Get-Date -Format 'HH:mm:ss') === All 8 runs complete ==="
Write-Host "Output files:"
Get-ChildItem output\backtest\*.parquet | Select-Object Name, LastWriteTime, Length | Format-Table -AutoSize
