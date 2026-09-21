@echo off
REM ===================================================================
REM  Sales Agent - Personal WeChat Bridge watchdog (STOP)
REM  ASCII-only on purpose: see wechat_bridge/README.md
REM ===================================================================
setlocal
cd /d "%~dp0.."
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

set PY=
for %%C in (python py) do (
  if not defined PY (
    where %%C >nul 2>nul && set PY=%%C
  )
)
if not defined PY (
  if exist "C:\Program Files\Python311\python.exe" set PY="C:\Program Files\Python311\python.exe"
)
if not defined PY (
  echo [ERROR] Python not found in PATH.
  pause
  exit /b 1
)

echo Requesting bridge shutdown...
%PY% -m wechat_bridge.daemon --stop
echo.
pause
endlocal
