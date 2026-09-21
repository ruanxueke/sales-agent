@echo off
set PUPPETEER_EXECUTABLE_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
set AI_API_URL=http://127.0.0.1:5002/api/v1/chat
pushd "%~dp0"
"C:\Program Files\nodejs\node.exe" bot.cjs
popd
