$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-Python311 {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
    "C:\Program Files\Python311\python.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }
  try {
    $resolved = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved)) {
      return $resolved.Trim()
    }
  } catch {}
  return ""
}

function Install-Python311 {
  $installer = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
  Write-Step "Installing Python 3.11"
  Invoke-WebRequest `
    -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
    -OutFile $installer
  $process = Start-Process `
    -FilePath $installer `
    -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_pip=1", "Include_launcher=1" `
    -Wait `
    -PassThru
  if ($process.ExitCode -ne 0) {
    throw "Python installation failed with exit code $($process.ExitCode)"
  }
}

function Start-WeChatIfNeeded {
  $running = Get-Process -Name "Weixin", "WeChat" -ErrorAction SilentlyContinue
  if ($running) {
    return
  }
  $candidates = @(
    "C:\Program Files\Tencent\Weixin\Weixin.exe",
    "C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
    (Join-Path $env:LOCALAPPDATA "Tencent\Weixin\Weixin.exe"),
    "C:\Program Files\Tencent\WeChat\WeChat.exe",
    "C:\Program Files (x86)\Tencent\WeChat\WeChat.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
      Start-Process -FilePath $candidate
      return
    }
  }
  throw "WeChat executable was not found. Install WeChat first."
}

function Stop-ExistingInstallation {
  Write-Step "Stopping old SalesAgent processes"
  Stop-ScheduledTask -TaskName "SalesAgentWechatBridge" -ErrorAction SilentlyContinue
  $targets = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "SalesAgentConsole.exe" -or
    (
      $_.Name -in @("python.exe", "pythonw.exe", "cmd.exe", "powershell.exe") -and
      $_.CommandLine -match "wechat_bridge\.(service_wrapper|daemon|run)" -or
      $_.CommandLine -match "start_bridge_service"
    )
  }
  foreach ($target in $targets) {
    Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 3
}

Stop-ExistingInstallation

$python = Resolve-Python311
if (-not $python) {
  Install-Python311
  $python = Resolve-Python311
}
if (-not $python) {
  throw "Python 3.11 installation was not detected."
}

Write-Step "Installing desktop client"
$clientInstaller = Get-ChildItem `
  -LiteralPath $PSScriptRoot `
  -Filter "SalesAgentConsole Setup*.exe" `
  | Sort-Object LastWriteTime -Descending `
  | Select-Object -First 1
if (-not $clientInstaller) {
  throw "SalesAgentConsole installer was not found beside this script."
}
$install = Start-Process `
  -FilePath $clientInstaller.FullName `
  -ArgumentList "/S" `
  -Wait `
  -PassThru
if ($install.ExitCode -ne 0) {
  throw "Desktop client installation failed with exit code $($install.ExitCode)"
}

$resourceRoot = Join-Path $env:LOCALAPPDATA "Programs\SalesAgentConsole\resources"
$bridgeRoot = Join-Path $resourceRoot "wechat_bridge"
$requirements = Join-Path $bridgeRoot "requirements.txt"
$capture = Join-Path $bridgeRoot "vendor\capture.py"

Write-Step "Installing bridge dependencies"
& $python -m pip install --upgrade pip
& $python -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) {
  throw "Bridge dependency installation failed."
}

Write-Step "Preparing WeChat reader"
& $python $capture setup
Start-WeChatIfNeeded
Write-Host "请先登录这个电脑上的专用微信账号，并确认聊天列表已经加载。" -ForegroundColor Yellow
Read-Host "登录完成后按回车继续"

Write-Step "Extracting and decrypting WeChat data"
& $python $capture key
if ($LASTEXITCODE -ne 0) {
  throw "WeChat key extraction failed. Keep WeChat running and retry."
}
& $python $capture decrypt
if ($LASTEXITCODE -ne 0) {
  throw "WeChat database decryption failed."
}
& $python $capture doctor
& $python $capture sessions
if ($LASTEXITCODE -ne 0) {
  throw "WeChat reader is installed, but no decrypted account can be read."
}

Write-Step "Starting desktop client"
Start-Process -FilePath (Join-Path $env:LOCALAPPDATA "Programs\SalesAgentConsole\SalesAgentConsole.exe")
Write-Host ""
Write-Host "部署完成。" -ForegroundColor Green
Write-Host "请在客户端登录同一个中台租户，然后进入“客户接待链路”，打开“开始识别”。" -ForegroundColor Yellow
Read-Host "按回车退出"
