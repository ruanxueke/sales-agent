@echo off
rem Vision Agent launcher. Edit values below before running.
cd /d %~dp0
set VISION_AGENT_API_BASE=http://127.0.0.1:5000
set VISION_AGENT_MODE=wecom
set VISION_AGENT_INSTANCE_ID=desktop-1
set VISION_DEBUG_NO_SEND=1
rem Set DASHSCOPE_API_KEY in your environment before running.
rem Set API_KEYS in your environment before running.
set VISION_AGENT_MONITOR=
set VISION_IGNORE_CONTACTS=
if "%DASHSCOPE_API_KEY%"=="" (
  echo Error: DASHSCOPE_API_KEY is not set.
  pause
  exit /b 1
)
if "%API_KEYS%"=="" (
  echo Error: API_KEYS is not set.
  pause
  exit /b 1
)

python -m vision_agent.worker
pause
