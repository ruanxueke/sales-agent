param(
  [Parameter(Mandatory=$true)][string]$ResourceRoot,
  [Parameter(Mandatory=$true)][string]$PythonPath,
  [Parameter(Mandatory=$true)][string]$ConfigPath,
  [Parameter(Mandatory=$true)][string]$SecretFile,
  [Parameter(Mandatory=$true)][string]$DataDir,
  [string]$InstanceId = "desktop-wechat-auto",
  [string]$TaskName = "SalesAgentWechatBridge",
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  }
  Write-Output "uninstalled"
  exit 0
}

New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$logPath = Join-Path $DataDir "bridge.log"
$arguments = (
  "-m wechat_bridge.service_wrapper " +
  "--config `"$ConfigPath`" " +
  "--secret-file `"$SecretFile`" " +
  "--data-dir `"$DataDir`" " +
  "--log `"$logPath`""
)

$action = New-ScheduledTaskAction `
  -Execute $PythonPath `
  -Argument $arguments `
  -WorkingDirectory $ResourceRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
  -UserId $env:USERNAME `
  -LogonType Interactive `
  -RunLevel Limited

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Output "installed"
