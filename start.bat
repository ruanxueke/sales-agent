@echo off
REM 销售客服智能体 - 快捷启动脚本
REM 用法: start.bat web    启动 Web 服务
REM       start.bat worker  启动 Celery Worker
REM       start.bat console 启动控制台模式

if "%1"=="web" (
    echo [启动] FastAPI Web 服务...
    python main.py web
    goto end
)
if "%1"=="worker" (
    echo [启动] Celery Worker...
    python main.py worker
    goto end
)
if "%1"=="console" (
    echo [启动] 控制台模式...
    python main.py --console
    goto end
)

echo 用法: start.bat [web^|worker^|console]
echo   web      - 启动 Web 服务 (多 worker 并发)
echo   worker   - 启动 Celery Worker (处理队列任务)
echo   console  - 启动控制台测试模式

:end
pause
