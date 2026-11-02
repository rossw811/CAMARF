# Starts the edge accounting re-run (waits for the Amendment 7 chain itself) with Windows kept awake while it runs.
Add-Type -Namespace CamarfPowerEdge -Name Exec -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[CamarfPowerEdge.Exec]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null
try {
    & "C:\Program Files\Git\usr\bin\bash.exe" -lc "/c/Users/RossW/Projects/CAMARF/debug/_tmp_chain_edge_surface_20261101.sh"
} finally {
    [CamarfPowerEdge.Exec]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
}
