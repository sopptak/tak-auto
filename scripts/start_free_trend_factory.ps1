# Local free MVP: data survives application restarts in this checkout.
$env:TAK_AUTO_FREE_MODE = "true"
$env:TAK_AUTO_PUBLISHING_ENABLED = "false"
$env:TAK_AUTO_DATA_DIR = Join-Path (Split-Path $PSScriptRoot -Parent) "data/free-trend-factory"
$taskPython = Join-Path $env:LOCALAPPDATA "Programs/Python/Python312/python.exe"
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = "python" }
& $taskPython (Join-Path $PSScriptRoot "run_trend_content_mvp.py") --host 127.0.0.1 --port 8080
