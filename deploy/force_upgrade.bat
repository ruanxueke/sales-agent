@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0force_upgrade_1_0_8.ps1"
if errorlevel 1 pause
