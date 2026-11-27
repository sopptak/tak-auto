@echo off
setlocal
rem Local free dashboard. Keep this launcher usable when PowerShell scripts are restricted.
set "TAK_AUTO_FREE_MODE=true"
set "TAK_AUTO_PUBLISHING_ENABLED=false"
set "TAK_AUTO_DATA_DIR=%~dp0..\data\free-trend-factory"

set "task_python=%~dp0..\.venv\Scripts\python.exe"
if exist "%task_python%" goto run_python
set "task_python=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%task_python%" goto run_python

where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_path_python
echo Python 3 was not found. Install Python, then try again.
exit /b 1

:run_python
"%task_python%" "%~dp0run_trend_content_mvp.py" --host 127.0.0.1 --port 8080
exit /b %errorlevel%

:run_py
py -3 "%~dp0run_trend_content_mvp.py" --host 127.0.0.1 --port 8080
exit /b %errorlevel%

:run_path_python
python "%~dp0run_trend_content_mvp.py" --host 127.0.0.1 --port 8080
exit /b %errorlevel%
