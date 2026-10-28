# Runs the Amendment 7 Surface chain with Windows kept awake (idle sleep blocked while it runs; lid-close and Windows
# Update restarts are NOT blocked -- keep the Surface plugged in, lid open, updates paused). Started from Task Scheduler
# so the chain is not a child of Claude Code (whose low-memory reaper killed background jobs on 10-25):
#   schtasks /Create /TN CAMARF_A7 /SC ONCE /ST 00:00 /F /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\RossW\Projects\CAMARF\debug\_tmp_launch_a7_surface.ps1"
#   schtasks /Run /TN CAMARF_A7
Add-Type -Namespace CamarfPower -Name Exec -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[CamarfPower.Exec]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
try {
    & "C:\Program Files\Git\usr\bin\bash.exe" -lc "/c/Users/RossW/Projects/CAMARF/debug/_tmp_chain_a7_surface_20261028.sh"
} finally {
    [CamarfPower.Exec]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null   # back to normal
}
