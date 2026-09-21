# Build SalesAgentConsole.exe with PyInstaller
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $project

python -m pip install -r desktop_app\requirements.txt
python -m pip install pyinstaller

pyinstaller --noconfirm --clean --windowed --name "SalesAgentConsole" `
  --add-data "static;static" `
  --add-data "vision_agent;vision_agent" `
  --add-data "vision_agent_config.json;." `
  --paths "$project" `
  desktop_app\main.py

Write-Host "Build done: dist\SalesAgentConsole.exe"
