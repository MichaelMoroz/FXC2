# Benchmarks ShaderEmu's rvc_harness under one compiler and prints the BENCH
# line (emulated instructions per second and the machine state hash).
#
#   pwsh tools\se_bench.ps1 -Which fxc2 [-Runs 3] [-Frames 6000] [-Fresh]
#
# -Which: fxc   D3D11, Microsoft's d3dcompiler (bin\rvc_harness.exe)
#         fxc2  D3D11, bin\d3dcompiler_47.dll from this repo (bin_fxc2\)
#         dxc   D3D12, DXC
# -Fresh clears that compiler's shader cache first, so the shader is rebuilt.
param(
    [Parameter(Mandatory = $true)][ValidateSet("fxc", "fxc2", "dxc")][string]$Which,
    [int]$Runs = 3,
    [int]$Frames = 6000,
    [string]$ShaderEmu = (Join-Path $PSScriptRoot "..\out\ShaderEmu"),
    [switch]$Fresh,
    [switch]$NoDoubles
)
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ShaderEmu
$cache = "build\cache_$Which"
if ($Which -eq "fxc2") {
    New-Item -ItemType Directory -Force bin_fxc2 | Out-Null
    Copy-Item bin\rvc_harness.exe bin_fxc2\ -Force
    Copy-Item (Join-Path $repo "bin\d3dcompiler_47.dll") bin_fxc2\ -Force
    $exe = "bin_fxc2\rvc_harness.exe"
} else {
    $exe = "bin\rvc_harness.exe"
}
if ($Fresh -and (Test-Path $cache)) { Remove-Item $cache -Recurse -Force }
$common = @("--rvc", "experiments\rvc_opt", "--payload", "rvc\_Nix\rvc\data-net", "--no-stdin",
    "--fixed-dt", "0.004", "--ticks", "2048", "--frames", "$Frames", "--bench", "100", "--cache", $cache)
if ($Which -eq "dxc") { $common = @("--dxc", "--no-bands") + $common } else { $common = @("--d3d11") + $common }
if ($NoDoubles) { $common += "--no-doubles" }
for ($i = 0; $i -lt $Runs; $i++) {
    $out = & $exe @common 2>&1 | ForEach-Object { "$_" }
    $out | Select-String -Pattern "CPUTick' fragment: compiled|FAILED|error" | ForEach-Object { "   " + $_.Line.Trim() }
    $bench = $out | Select-String -Pattern "^BENCH" | Select-Object -First 1
    if ($bench) { "$Which  $($bench.Line)" } else { "$Which  no BENCH line (exit $LASTEXITCODE)"; $out | Select-Object -Last 4 }
}
