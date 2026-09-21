@echo off
chcp 65001 >nul
echo 正在启动公网通道，窗口请保持打开...
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -o ExitOnForwardFailure=yes -R 80:127.0.0.1:8080 nokey@localhost.run
pause
