@echo off
REM ===================================================================
REM  Sales Agent - Personal WeChat Bridge watchdog (START)
REM  ASCII-only on purpose: see wechat_bridge/README.md
REM ===================================================================
setlocal enabledelayedexpansion
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
  echo         Install Python 3.10+ or add it to PATH, then retry.
  pause
  exit /b 1
)

echo ============================================================
echo  WeChat bridge watchdog starting...
echo  Python : %PY%
echo  Log    : wechat_bridge\data\bridge.log
echo  Stop   : run stop_bridge.bat  (or create wechat_bridge\data\bridge.stop)
echo ============================================================
echo.

%PY% -m wechat_bridge.daemon --echo
set RC=%ERRORLEVEL%

echo.
if not "%RC%"=="0" (
  echo [ERROR] Bridge watchdog exited with code %RC%.
  echo         Check wechat_bridge\data\bridge.log for details.
) else (
  echo Bridge watchdog stopped.
)
pause
endlocal
exit /b %RC%
