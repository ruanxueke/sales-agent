$ErrorActionPreference = "Stop"

Write-Host "Stopping old bridge and client..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "SalesAgentWechatBridge" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "SalesAgentWechatBridge" -Confirm:$false -ErrorAction SilentlyContinue

$targets = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq "SalesAgentConsole.exe" -or
  (
    $_.Name -in @("python.exe", "pythonw.exe", "cmd.exe", "powershell.exe") -and
    $_.CommandLine -match "wechat_bridge|start_bridge_service"
  )
}
foreach ($target in $targets) {
  Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

$installer = Get-ChildItem `
  -LiteralPath $PSScriptRoot `
  -Filter "SalesAgentConsole Setup*.exe" `
  | Sort-Object LastWriteTime -Descending `
  | Select-Object -First 1
if (-not $installer) {
  throw "SalesAgentConsole installer was not found."
}

Write-Host "Installing $($installer.Name)..." -ForegroundColor Cyan
$process = Start-Process `
  -FilePath $installer.FullName `
  -ArgumentList "/S" `
  -Wait `
  -PassThru
if ($process.ExitCode -ne 0) {
  throw "Installer failed with exit code $($process.ExitCode)"
}

Start-Sleep -Seconds 3
$exe = Join-Path $env:LOCALAPPDATA "Programs\SalesAgentConsole\SalesAgentConsole.exe"
Start-Process -FilePath $exe
Start-Sleep -Seconds 15

$task = Get-ScheduledTask -TaskName "SalesAgentWechatBridge" -ErrorAction SilentlyContinue
if ($task) {
  Write-Host "Service task: $($task.State)" -ForegroundColor Green
  Write-Host "Service action: $($task.Actions.Execute)"
}
Write-Host ""
Write-Host "Upgrade completed. Login to the client and open Start Recognition." -ForegroundColor Green
Read-Host "Press Enter to exit"
