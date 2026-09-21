@echo off
cd /d "%~dp0"
python -m wechat_bridge.run --config "%~dp0wechat_bridge\config.cloud-test.json"
