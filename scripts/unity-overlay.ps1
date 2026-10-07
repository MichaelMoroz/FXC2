# Builds a lightweight "overlay" copy of a Unity editor whose shader compiler
# loads the fxc2 d3dcompiler_47.dll, without touching the real install (which
# lives in Program Files and needs admin rights to modify).
#
# Unity.exe and the Data\Tools folder (home of UnityShaderCompiler.exe and
# D3DCompiler_47.dll) are copied; every other folder is a directory junction
# back into the real install, so the overlay costs ~0.5 GB instead of ~7 GB.
#
#   powershell -File scripts\unity-overlay.ps1 -Editor "C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor" -Dest out\unity-overlay
#   out\unity-overlay\Unity.exe -projectPath <project>
#
# To delete the overlay use -Remove: it unlinks the junctions first. Deleting
# the folder recursively by other means can follow them into the real install.
param(
    [Parameter(Mandatory = $true)][string]$Editor,
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$Dll = (Join-Path $PSScriptRoot "..\bin\d3dcompiler_47.dll"),
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

function Remove-Overlay($path) {
    if (-not (Test-Path $path)) { return }
    # Junctions first, non-recursively, so nothing below them is touched.
    Get-ChildItem $path -Recurse -Force -Attributes ReparsePoint -Directory |
        ForEach-Object { [System.IO.Directory]::Delete($_.FullName, $false) }
    Remove-Item $path -Recurse -Force
}

if ($Remove) {
    Remove-Overlay $Dest
    Write-Host "removed $Dest"
    exit 0
}

$Editor = (Resolve-Path $Editor).Path
Remove-Overlay $Dest
New-Item -ItemType Directory -Force $Dest, (Join-Path $Dest "Data") | Out-Null
$Dest = (Resolve-Path $Dest).Path

function Link-Or-Copy($source, $target, $copyDirs) {
    foreach ($item in Get-ChildItem $source -Force) {
        $to = Join-Path $target $item.Name
        if (-not $item.PSIsContainer) {
            if ($item.Extension -ne ".pdb") { Copy-Item $item.FullName $to }
        } elseif ($copyDirs -contains $item.Name) {
            Copy-Item $item.FullName $to -Recurse
        } elseif ($item.Name -ne "Data") {
            New-Item -ItemType Junction -Path $to -Target $item.FullName | Out-Null
        }
    }
}

Link-Or-Copy $Editor $Dest @()
Link-Or-Copy (Join-Path $Editor "Data") (Join-Path $Dest "Data") @("Tools")

$target = Join-Path $Dest "Data\Tools\D3DCompiler_47.dll"
Copy-Item $target (Join-Path $Dest "Data\Tools\D3DCompiler_47.dll.microsoft")
Copy-Item $Dll $target -Force
Write-Host "overlay ready: $(Join-Path $Dest 'Unity.exe')"
