# Local free MVP: data survives application restarts in this checkout.
$env:TAK_AUTO_FREE_MODE = "true"
$env:TAK_AUTO_PUBLISHING_ENABLED = "false"
$env:TAK_AUTO_DATA_DIR = Join-Path (Split-Path $PSScriptRoot -Parent) "data/free-trend-factory"

$pythonCommand = $null
$pythonArgs = @()
$taskPython = $null
if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $taskPython = Join-Path $env:LOCALAPPDATA "Programs/Python/Python312/python.exe"
}
if ($taskPython -and (Test-Path -LiteralPath $taskPython)) {
    $pythonCommand = $taskPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} else {
    throw "Python 3 was not found. Install Python or its py launcher, then try again."
}

$entrypoint = Join-Path $PSScriptRoot "run_trend_content_mvp.py"
& $pythonCommand @pythonArgs $entrypoint --host 127.0.0.1 --port 8080
exit $LASTEXITCODE
