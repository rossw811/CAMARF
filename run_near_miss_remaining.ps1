# Temporary runner for task #53's remaining timeframes (1h, 4h, 1D, 7D, 1M, 3M, 6M).
# Launched via Start-Process for genuine OS-level detachment (bash `&`/nohup was
# tied to the shell/pty session and died silently -- see Development.md task #53
# entry for the diagnostic history). Safe to delete once task #53 completes.
$python = "C:\Users\RossW\anaconda3\envs\trading\python.exe"
$log = "C:\Users\RossW\Projects\CAMARF\near_miss_remaining.log"
"=== run_near_miss_remaining.ps1 started $(Get-Date) ===" | Out-File -FilePath $log -Append
foreach ($tf in @("1h", "4h", "1D", "7D", "1M", "3M", "6M")) {
    "===== TF=$tf START $(Get-Date) =====" | Out-File -FilePath $log -Append
    & $python "C:\Users\RossW\Projects\CAMARF\research\near_miss_lag_scan.py" --tf $tf *>> $log
    "===== TF=$tf END $(Get-Date) =====" | Out-File -FilePath $log -Append
}
"ALL_TFS_COMPLETE_3" | Out-File -FilePath $log -Append
