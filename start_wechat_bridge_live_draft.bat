@echo off
cd /d "%~dp0"
python -m wechat_bridge.run --live-draft
