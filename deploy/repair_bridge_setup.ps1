$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

$pythonCandidates = @(
  (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
  "C:\Program Files\Python311\python.exe"
)
$python = $pythonCandidates |
  Where-Object { Test-Path -LiteralPath $_ } |
  Select-Object -First 1
if (-not $python) {
  throw "Python 3.11 was not found. Run the one-click deployment package first."
}

function Resolve-ClientResourceRoot {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\SalesAgentConsole"),
    (Join-Path $env:LOCALAPPDATA "SalesAgentConsole"),
    (Join-Path ${env:ProgramFiles} "SalesAgentConsole"),
    (Join-Path ${env:ProgramFiles(x86)} "SalesAgentConsole")
  )
  $uninstallKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )
  foreach ($key in $uninstallKeys) {
    try {
      $entries = Get-ItemProperty $key -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -match "SalesAgentConsole|SalesAgent" }
      foreach ($entry in $entries) {
        if ($entry.InstallLocation) {
          $candidates += $entry.InstallLocation.TrimEnd("\")
        }
      }
    } catch {}
  }
  foreach ($base in @(
    (Join-Path $env:LOCALAPPDATA "Programs"),
    ${env:ProgramFiles},
    ${env:ProgramFiles(x86)},
    $env:LOCALAPPDATA,
    $env:USERPROFILE
  )) {
    try {
      $candidates += Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "sales.?agent" } |
        ForEach-Object { $_.FullName }
    } catch {}
  }
  try {
    $runningExe = Get-CimInstance Win32_Process |
      Where-Object { $_.Name -eq "SalesAgentConsole.exe" } |
      Select-Object -First 1 -ExpandProperty ExecutablePath
    if ($runningExe) {
      $candidates += Split-Path -Parent $runningExe
    }
  } catch {}
  foreach ($searchRoot in @(
    $env:LOCALAPPDATA,
    $env:USERPROFILE,
    ${env:ProgramFiles},
    ${env:ProgramFiles(x86)}
  )) {
    try {
      $foundExe = Get-ChildItem `
        -LiteralPath $searchRoot `
        -Filter "SalesAgentConsole.exe" `
        -File `
        -Recurse `
        -Depth 6 `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
      if ($foundExe) {
        $candidates += Split-Path -Parent $foundExe.FullName
      }
    } catch {}
  }
  foreach ($candidate in ($candidates | Select-Object -Unique)) {
    $resource = Join-Path $candidate "resources"
    if (Test-Path -LiteralPath (Join-Path $resource "wechat_bridge\vendor\capture.py")) {
      return $resource
    }
  }
  return ""
}

$resourceRoot = Resolve-ClientResourceRoot
if (-not $resourceRoot) {
  throw "SalesAgentConsole installation was not found. Install version 1.0.11 first."
}
$bridgeRoot = Join-Path $resourceRoot "wechat_bridge"
$capture = Join-Path $bridgeRoot "vendor\capture.py"
$patchedCapture = Join-Path $PSScriptRoot "capture.py"
$patchedReader = Join-Path $PSScriptRoot "reader_adapter.py"
$patchedConfig = Join-Path $PSScriptRoot "config.py"
$patchedServiceWrapper = Join-Path $PSScriptRoot "service_wrapper.py"
$patchedServiceInstaller = Join-Path $PSScriptRoot "install_wechat_bridge_service.ps1"
if (-not (Test-Path -LiteralPath $capture)) {
  throw "The desktop client is not installed correctly."
}
if (Test-Path -LiteralPath $patchedCapture) {
  Copy-Item -LiteralPath $patchedCapture -Destination $capture -Force
}
if (Test-Path -LiteralPath $patchedReader) {
  Copy-Item -LiteralPath $patchedReader -Destination (Join-Path $bridgeRoot "reader_adapter.py") -Force
}
if (Test-Path -LiteralPath $patchedConfig) {
  Copy-Item -LiteralPath $patchedConfig -Destination (Join-Path $bridgeRoot "config.py") -Force
}
if (Test-Path -LiteralPath $patchedServiceWrapper) {
  Copy-Item -LiteralPath $patchedServiceWrapper -Destination (Join-Path $bridgeRoot "service_wrapper.py") -Force
}
if (Test-Path -LiteralPath $patchedServiceInstaller) {
  Copy-Item -LiteralPath $patchedServiceInstaller -Destination (Join-Path $resourceRoot "deploy\install_wechat_bridge_service.ps1") -Force
}
foreach ($bridgeFile in @(
  "run.py",
  "daemon.py",
  "central_client.py",
  "durable_queue.py",
  "ui_sender.py",
  "message_filter.py"
)) {
  $sourceFile = Join-Path $PSScriptRoot $bridgeFile
  if (Test-Path -LiteralPath $sourceFile) {
    Copy-Item -LiteralPath $sourceFile -Destination (Join-Path $bridgeRoot $bridgeFile) -Force
  }
}

Write-Step "Installing bridge dependencies"
& $python -m pip install -r (Join-Path $bridgeRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
  throw "Dependency installation failed."
}

Write-Step "Preparing WeChat reader"
& $python $capture setup

$wechat = Get-Process -Name "Weixin", "WeChat" -ErrorAction SilentlyContinue
if (-not $wechat) {
  $exe = @(
    "C:\Program Files\Tencent\Weixin\Weixin.exe",
    "C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
    (Join-Path $env:LOCALAPPDATA "Tencent\Weixin\Weixin.exe")
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if ($exe) {
    Start-Process -FilePath $exe
  } else {
    throw "WeChat was not found. Install and log in to WeChat first."
  }
}

Write-Host "请确认本机只登录本次要使用的专用微信账号。" -ForegroundColor Yellow
Read-Host "微信登录完成并且聊天列表加载后按回车"

Write-Step "Extracting and decrypting WeChat data"
& $python $capture key
if ($LASTEXITCODE -ne 0) {
  throw "WeChat key extraction failed."
}
& $python $capture decrypt
if ($LASTEXITCODE -ne 0) {
  throw "WeChat database decryption failed."
}
& $python $capture doctor
& $python $capture sessions
if ($LASTEXITCODE -ne 0) {
  Write-Host "未能自动找到微信数据目录。" -ForegroundColor Yellow
  Write-Host "请在微信“设置 -> 文件管理”中找到数据目录，例如 D:\\xwechat_files。" -ForegroundColor Yellow
  $customRoot = Read-Host "请粘贴该目录后按回车"
  if (-not $customRoot) {
    throw "No WeChat data directory was provided."
  }
  $env:WECHAT_FILES_ROOT = $customRoot
  $configPath = Join-Path $env:APPDATA "sales-agent-console\wechat_bridge\config.json"
  $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
  $config | Add-Member -NotePropertyName wechat_files_root -NotePropertyValue $customRoot -Force
  $config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $configPath -Encoding UTF8
  & $python $capture doctor
  & $python $capture sessions
  if ($LASTEXITCODE -ne 0) {
    throw "The configured WeChat data directory still cannot be read."
  }
}

Write-Step "Restarting bridge service"
$dataDir = Join-Path $env:APPDATA "sales-agent-console\wechat_bridge"
$configPath = Join-Path $dataDir "config.json"
$secretFile = Join-Path $dataDir "bridge-secret.bin"
$pythonw = $python -replace "python\.exe$", "pythonw.exe"
$bridgeConfig = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$instanceId = if ($bridgeConfig.instance_id) { $bridgeConfig.instance_id } else { "desktop-wechat-auto" }
& powershell.exe `
  -NoProfile `
  -ExecutionPolicy Bypass `
  -File (Join-Path $resourceRoot "deploy\install_wechat_bridge_service.ps1") `
  -ResourceRoot $resourceRoot `
  -PythonPath $pythonw `
  -ConfigPath $configPath `
  -SecretFile $secretFile `
  -DataDir $dataDir `
  -InstanceId $instanceId

Write-Host ""
Write-Host "初始化修复完成。" -ForegroundColor Green
Write-Host "回到客户接待链路，刷新状态并打开“开始识别”。" -ForegroundColor Yellow
Read-Host "按回车退出"
