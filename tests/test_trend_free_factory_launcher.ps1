$ErrorActionPreference = "Stop"
$testRoot = Join-Path $env:TEMP ("tak-auto-free-launcher-test-" + [guid]::NewGuid().ToString("N"))
if (Test-Path -LiteralPath $testRoot) { throw "Unexpected temporary test directory collision." }
$scriptDirectory = Join-Path $testRoot "scripts"
$originalLocalAppData = $env:LOCALAPPDATA
$originalProbe = $env:TAK_LAUNCHER_PROBE
try {
    New-Item -ItemType Directory -Path $scriptDirectory -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $scriptDirectory "run_trend_content_mvp.py") -Value "# test stub" -Encoding UTF8
    $env:LOCALAPPDATA = $testRoot

    function global:py {
        $global:TakAutoLauncherArguments = @($args)
        $global:LASTEXITCODE = 0
    }

    $repoRoot = Split-Path $PSScriptRoot -Parent
    $launcher = Join-Path $repoRoot "scripts/start_free_trend_factory.ps1"
    & $launcher

    $expectedScript = [IO.Path]::GetFullPath((Join-Path (Split-Path $launcher -Parent) "run_trend_content_mvp.py"))
    if ($global:TakAutoLauncherArguments.Count -ne 6) {
        throw "The launcher did not forward the expected six Python arguments."
    }
    if ($global:TakAutoLauncherArguments[0] -ne "-3") {
        throw "The launcher did not select the py -3 fallback."
    }
    if ([IO.Path]::GetFullPath($global:TakAutoLauncherArguments[1]) -ne $expectedScript) {
        throw "The launcher passed an unexpected application path."
    }
    if (($global:TakAutoLauncherArguments[2..5] -join " ") -ne "--host 127.0.0.1 --port 8080") {
        throw "The launcher changed its loopback-only address or port."
    }
    if ($env:TAK_AUTO_FREE_MODE -ne "true" -or $env:TAK_AUTO_PUBLISHING_ENABLED -ne "false") {
        throw "The launcher must enable free mode and keep publishing disabled."
    }
    $expectedData = [IO.Path]::GetFullPath((Join-Path $repoRoot "data/free-trend-factory"))
    if ([IO.Path]::GetFullPath($env:TAK_AUTO_DATA_DIR) -ne $expectedData) {
        throw "The launcher selected an unexpected data directory."
    }
    Write-Output "Windows free launcher fallback passed."

    $cmdLauncher = Join-Path $scriptDirectory "start_free_trend_factory.cmd"
    Copy-Item -LiteralPath (Join-Path $repoRoot "scripts/start_free_trend_factory.cmd") -Destination $cmdLauncher
    $env:TAK_LAUNCHER_PROBE = Join-Path $testRoot "launcher-result.json"
    @'
import json
import os
import sys
from pathlib import Path

Path(os.environ["TAK_LAUNCHER_PROBE"]).write_text(json.dumps({
    "arguments": sys.argv[1:],
    "free_mode": os.environ.get("TAK_AUTO_FREE_MODE"),
    "publishing_enabled": os.environ.get("TAK_AUTO_PUBLISHING_ENABLED"),
    "data_dir": os.environ.get("TAK_AUTO_DATA_DIR"),
}), encoding="utf-8")
'@ | Set-Content -LiteralPath (Join-Path $scriptDirectory "run_trend_content_mvp.py") -Encoding UTF8
    & $cmdLauncher
    if ($LASTEXITCODE -ne 0) { throw "The cmd launcher failed." }
    $result = Get-Content -LiteralPath $env:TAK_LAUNCHER_PROBE -Raw | ConvertFrom-Json
    if (($result.arguments -join " ") -ne "--host 127.0.0.1 --port 8080") {
        throw "The cmd launcher changed its loopback-only address or port."
    }
    if ($result.free_mode -ne "true" -or $result.publishing_enabled -ne "false") {
        throw "The cmd launcher must enable free mode and keep publishing disabled."
    }
    $expectedCmdData = [IO.Path]::GetFullPath((Join-Path $testRoot "data/free-trend-factory"))
    if ([IO.Path]::GetFullPath($result.data_dir) -ne $expectedCmdData) {
        throw "The cmd launcher selected an unexpected data directory."
    }
    Write-Output "Windows cmd launcher passed."
}
finally {
    if ($null -eq $originalLocalAppData) {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    } else {
        $env:LOCALAPPDATA = $originalLocalAppData
    }
    if ($null -eq $originalProbe) {
        Remove-Item Env:TAK_LAUNCHER_PROBE -ErrorAction SilentlyContinue
    } else {
        $env:TAK_LAUNCHER_PROBE = $originalProbe
    }
    if (Test-Path -LiteralPath $testRoot) {
        $tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
        if (-not $resolvedTestRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a test directory outside TEMP."
        }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
