FROM python:3.11-slim

# 非 root 运行：容器内进程一旦被攻破（比如提示词注入诱导出来的代码执行），
# 不应该顺手就拿到 root。UID/GID 做成可覆盖的构建参数，因为宿主机的
# data/ 与 vector_store/ 是 bind mount，容器要往里写，两边属主必须一致——
# deploy.sh 会在启动前把这两个目录 chown 到同一组 UID/GID。
ARG APP_UID=1000
ARG APP_GID=1000

# PYTHONUNBUFFERED：不加的话 stdout 会被缓冲，`docker logs` 看不到实时日志——
# 排查"已连接但待识别"这类现场问题时这是刚需。
# PYTHONDONTWRITEBYTECODE：不生成 __pycache__，避免只读挂载与权限问题。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 10 -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

RUN groupadd --gid "${APP_GID}" app \
 && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/data /app/vector_store \
 && chown -R "${APP_UID}:${APP_GID}" /app

ENV WECHAT_OFFICIAL_SERVER_HOST=0.0.0.0
ENV WECHAT_OFFICIAL_SERVER_PORT=8080
ENV ENABLE_SCHEDULER=true

USER ${APP_UID}:${APP_GID}

EXPOSE 5000 8080

# 健康检查针对 API（5000）。official / worker / beat / migrate 不监听 5000，
# 必须在 compose 里显式覆盖或 disable，否则会被误判为 unhealthy。
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=5).status==200 else 1)"

# 单进程 CMD：一个容器跑一个进程。api/official/worker/beat 由 compose 各自
# 指定 command，这里只是 `docker run` 裸跑时的合理默认值。
CMD ["python", "api_server.py"]
