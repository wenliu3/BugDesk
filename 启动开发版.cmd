@echo off
setlocal
cd /d "%~dp0"
if not defined BUGDESK_PYTHON if exist "%~dp0.local\python-path.txt" set /p BUGDESK_PYTHON=<"%~dp0.local\python-path.txt"
if defined BUGDESK_PYTHON goto configured_python

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 (
  py -3 -X utf8 "%~dp0app.py" --data-dir "%~dp0.local" --idle-timeout 0 %*
  goto finished
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 (
  python -X utf8 "%~dp0app.py" --data-dir "%~dp0.local" --idle-timeout 0 %*
  goto finished
)
goto missing_python

:configured_python
"%BUGDESK_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto missing_python
"%BUGDESK_PYTHON%" -X utf8 "%~dp0app.py" --data-dir "%~dp0.local" --idle-timeout 0 %*

:finished
if errorlevel 1 (
  echo BugDesk could not start. See the error above.
  pause
  exit /b 1
)
endlocal
exit /b 0

:missing_python
echo Python 3.11 or newer is required. Install Python or set BUGDESK_PYTHON to python.exe.
pause
exit /b 1
