"""个人微信桥接守护进程：进程级自愈 + 日志轮转。

为什么需要它
------------
`run.py` 自己已经处理了"业务级"失败（读取器构建失败会 30 秒重试、单轮异常会
记日志继续）。但下面这些它兜不住：

  * 进程被外部杀掉（客户机器上杀毒软件、Windows 更新重启、误关窗口）；
  * 进程真的挂死（pyautogui / OCR 卡在某个调用上，`while True` 转不动）——
    此时没有任何异常，`run.py` 的心跳也停了，控制台只会显示「离线」，
    而没有任何人会去把那台 Windows 机器上的黑窗口重新点开；
  * 日志直接打 stderr，重定向到文件后无限增长。

所以这一层负责：拉起子进程 → 退出就重启（指数退避，避免崩溃风暴）→
按大小轮转日志 → 收到停止信号或发现 stop 文件时优雅退出。

用法
----
    python -m wechat_bridge.daemon                      # 前台运行（看得到日志）
    python -m wechat_bridge.daemon --config config.json
    python -m wechat_bridge.daemon --stop               # 停止已在运行的守护

停止文件：`data/bridge.stop`（存在即退出），适合放进计划任务/脚本里控制。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger("wechat_bridge.daemon")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
BRIDGE_CHILD = [sys.executable, "-m", "wechat_bridge.run"]

# 重启退避：连续崩溃时不要打爆 CPU（1s, 2s, 4s ... 最多 60s）
BACKOFF_START = 1.0
BACKOFF_MAX = 60.0
# 子进程活过这么久就认为"这次启动是成功的"，退避重置
HEALTHY_UPTIME = 120.0


class RotatingLog:
    """按大小轮转的简单日志写入器（不依赖 logging.handlers 的进程间行为）。"""

    def __init__(self, path: Path, max_bytes: int = 10 * 1024 * 1024, backups: int = 5):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backups = backups
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = None

    def _open(self):
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8", errors="replace")
        return self._fh

    def _rotate_if_needed(self):
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                if self._fh is not None:
                    self._fh.close()
                    self._fh = None
                for i in range(self.backups - 1, 0, -1):
                    src = self.path.with_suffix(self.path.suffix + f".{i}")
                    dst = self.path.with_suffix(self.path.suffix + f".{i + 1}")
                    if src.exists():
                        if dst.exists():
                            dst.unlink()
                        src.rename(dst)
                first = self.path.with_suffix(self.path.suffix + ".1")
                if first.exists():
                    first.unlink()
                self.path.rename(first)
        except Exception as exc:
            logger.warning("日志轮转失败（继续写原文件）: %s", exc)

    def write(self, line: str) -> None:
        self._rotate_if_needed()
        try:
            fh = self._open()
            fh.write(line if line.endswith("\n") else line + "\n")
            fh.flush()
        except Exception as exc:
            logger.warning("日志写入失败: %s", exc)

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None


class BridgeDaemon:
    def __init__(self, args):
        self.args = args
        if getattr(args, "secret_file", "") and not os.getenv("PERSONAL_WECHAT_API_KEY"):
            try:
                from wechat_bridge.secure_store import load

                os.environ["PERSONAL_WECHAT_API_KEY"] = load(args.secret_file)
            except Exception as exc:
                logger.warning("加载桥接密钥失败: %s", exc)
        data_dir = Path(os.getenv("WECHAT_BRIDGE_HOME") or DEFAULT_DATA_DIR)
        self.data_dir = data_dir
        self.pid_path = data_dir / "bridge.pid"
        self.worker_pid_path = data_dir / "bridge.worker.pid"
        self.stop_path = data_dir / "bridge.stop"
        self.log = RotatingLog(
            Path(args.log) if args.log else data_dir / "bridge.log",
            max_bytes=int(args.log_max_mb) * 1024 * 1024,
            backups=int(args.log_backups),
        )
        self.stopping = False

    # ---------- PID 文件 ----------
    def _read_pid(self) -> int:
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip() or 0)
        except Exception:
            return 0

    def _write_pid(self, pid: int) -> None:
        try:
            self.pid_path.parent.mkdir(parents=True, exist_ok=True)
            self.pid_path.write_text(str(pid), encoding="utf-8")
        except Exception as exc:
            logger.warning("PID 文件写入失败: %s", exc)

    def _clear_pid(self) -> None:
        try:
            if self.pid_path.exists():
                self.pid_path.unlink()
        except Exception as e:
            logger.debug("BridgeDaemon._clear_pid 异常已忽略: %s", e)

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            # Windows 没有 os.kill(pid, 0) 语义，用 tasklist 判断
            try:
                out = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                return str(pid) in out
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    # ---------- 停止 ----------
    def request_stop(self) -> int:
        pid = self._read_pid()
        if not pid or not self._pid_alive(pid):
            print("没有正在运行的桥接守护（PID 文件为空或进程已退出）")
            self._clear_pid()
            return 0
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception as exc:
                print(f"停止失败: {exc}")
                return 1
        print(f"已请求停止守护进程及其子进程 (PID {pid})")
        return 0

    def _handle_signal(self, signum, _frame):
        logger.info("收到信号 %s，准备退出", signum)
        self.stopping = True

    # ---------- 主循环 ----------
    def run(self) -> int:
        if self.args.stop:
            return self.request_stop()

        existing = self._read_pid()
        if existing and self._pid_alive(existing):
            print(f"桥接守护已在运行 (PID {existing})，本次不重复启动")
            return 0

        if self.stop_path.exists():
            try:
                self.stop_path.unlink()
            except Exception as e:
                logger.debug("BridgeDaemon.run 异常已忽略: %s", e)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle_signal)
            except Exception as e:
                logger.debug("BridgeDaemon.run 异常已忽略: %s", e)

        self._write_pid(os.getpid())
        self.log.write(
            "=" * 70 + f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} 守护启动 pid={os.getpid()}\n"
        )
        backoff = BACKOFF_START
        try:
            while not self.stopping:
                if self.stop_path.exists():
                    logger.info("检测到停止文件 %s，退出", self.stop_path)
                    break
                code = self._run_child_once()
                if self.stopping:
                    break
                uptime = time.time() - self._child_started_at
                if uptime >= HEALTHY_UPTIME:
                    backoff = BACKOFF_START
                self.log.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} 子进程退出 code={code} "
                    f"运行 {uptime:.0f}s，{backoff:.0f}s 后重启\n"
                )
                logger.warning(
                    "桥接子进程退出（code=%s，运行 %.0fs），%.0f 秒后重启", code, uptime, backoff
                )
                self._sleep_interruptible(backoff)
                backoff = min(BACKOFF_MAX, backoff * 2)
        finally:
            self._clear_pid()
            self.log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 守护退出\n")
            self.log.close()
        return 0

    def _sleep_interruptible(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while not self.stopping and time.time() < deadline:
            if self.stop_path.exists():
                self.stopping = True
                return
            time.sleep(0.5)

    def _run_child_once(self) -> int:
        cmd = list(BRIDGE_CHILD)
        if self.args.config:
            cmd += ["--config", self.args.config]
        self._child_started_at = time.time()
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except Exception as exc:
            self.log.write(f"子进程启动失败: {exc}\n")
            return -1
        try:
            self.worker_pid_path.write_text(str(proc.pid), encoding="ascii")
        except Exception as exc:
            logger.debug("BridgeDaemon worker pid write failed: %s", exc)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log.write(line.rstrip("\n"))
                if self.args.echo:
                    print(line, end="")
                if self.stopping:
                    break
        except Exception as exc:
            self.log.write(f"读取子进程输出失败: {exc}\n")
        finally:
            if self.stopping and proc.poll() is None:
                self._terminate(proc)
            try:
                code = proc.wait(timeout=30)
            except Exception:
                self._terminate(proc)
                code = -9
            try:
                if self.worker_pid_path.exists():
                    self.worker_pid_path.unlink()
            except Exception as exc:
                logger.debug("BridgeDaemon worker pid cleanup failed: %s", exc)
            return code

    @staticmethod
    def _terminate(proc) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            else:
                proc.terminate()
        except Exception as e:
            logger.debug("BridgeDaemon._terminate 异常已忽略: %s", e)


def main() -> int:
    parser = argparse.ArgumentParser(description="个人微信桥接守护进程（自愈重启 + 日志轮转）")
    parser.add_argument("--config", default="", help="传给 run.py 的配置文件路径")
    parser.add_argument("--stop", action="store_true", help="停止已在运行的守护进程")
    parser.add_argument("--echo", action="store_true", help="同时把子进程日志打到当前终端")
    parser.add_argument("--log", default="", help="日志文件路径（默认 data/bridge.log）")
    parser.add_argument("--log-max-mb", default=10, type=int, help="单个日志文件上限 MB")
    parser.add_argument("--log-backups", default=5, type=int, help="保留的历史日志份数")
    parser.add_argument("--secret-file", default="", help="DPAPI encrypted bridge API key")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return BridgeDaemon(args).run()


if __name__ == "__main__":
    sys.exit(main())
