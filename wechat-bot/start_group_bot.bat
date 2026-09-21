@echo off
rem Standalone group customer-service bot. Edit AI_API_URL and run.
cd /d %~dp0
set AI_API_URL=http://127.0.0.1:5000/api/v1/chat
set BOT_NOTIFY_PORT=3900
set LIVE_PING=false
node bot.cjs
pause
