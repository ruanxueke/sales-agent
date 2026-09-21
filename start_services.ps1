param()

$project = 'C:\Users\1\Documents\销售客服智能体'
$python = 'C:\Program Files\Python311\python.exe'
$node = 'C:\Program Files\nodejs\node.exe'

function Start-ChildProc($name, $file, $argsList, $workdir) {
    Write-Host "启动 $name ..."
    $p = Start-Process -FilePath $file -ArgumentList $argsList -WorkingDirectory $workdir -WindowStyle Hidden -PassThru
    return $p
}

$jobs = @(
    @{ Name = 'AI服务-5000'; File = $python; Args = @('api_server.py'); Dir = $project },
    @{ Name = 'AI服务-5002'; File = $python; Args = @('-m', 'uvicorn', 'api_server:app', '--host', '0.0.0.0', '--port', '5002', '--workers', '4', '--log-level', 'info'); Dir = $project },
    @{ Name = '公众号服务-8080'; File = $python; Args = @('main.py', '--channel', 'official'); Dir = $project },
    @{ Name = '微信机器人'; File = $node; Args = @('bot.cjs'); Dir = Join-Path $project 'wechat-bot' }
    # Celery worker（按需启用：配置 REDIS_URL 后取消注释）
    # @{ Name = 'Celery-Worker'; File = $python; Args = @('-m', 'celery', '-A', 'core.queue', 'worker', '--loglevel=info'); Dir = $project }
)

$procs = @{}
foreach ($job in $jobs) {
    $procs[$job.Name] = Start-ChildProc $job.Name $job.File $job.Args $job.Dir
}

Write-Host '服务监控中，进程退出后 5 秒自动重启，按 Ctrl+C 退出...'
while ($true) {
    Start-Sleep -Seconds 5
    foreach ($job in $jobs) {
        $p = $procs[$job.Name]
        if ($p -and $p.HasExited) {
            Write-Host "$($job.Name) 已退出，5 秒后自动重启..."
            $procs[$job.Name] = Start-ChildProc $job.Name $job.File $job.Args $job.Dir
        }
    }
}
