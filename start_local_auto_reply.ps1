$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command python).Source
$LogDir = Join-Path $Root "wechat_bridge\data"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$Stdout = Join-Path $LogDir "local_api_stdout.log"
$Stderr = Join-Path $LogDir "local_api_stderr.log"
$Api = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "api_server:app", "--host", "127.0.0.1", "--port", "5000") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $Stdout `
    -RedirectStandardError $Stderr `
    -PassThru

try {
    $Ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:5000/health" -TimeoutSec 2
            if ($Health.status -eq "ok") {
                $Ready = $true
                break
            }
        } catch {
        }
    }
    if (-not $Ready) {
        throw "本地销售智能体 API 启动失败，请查看 $Stderr"
    }

    & $Python -m wechat_bridge.run --config (Join-Path $Root "wechat_bridge\config.live.json")
} finally {
    if ($Api -and -not $Api.HasExited) {
        Stop-Process -Id $Api.Id -Force
    }
}
