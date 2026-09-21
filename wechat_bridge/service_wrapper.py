"""Console-free wrapper that keeps the bridge daemon alive."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def stop_stale_worker(worker_pid_path: Path) -> None:
    try:
        worker_pid = int(worker_pid_path.read_text(encoding="ascii").strip())
    except Exception:
        return
    if worker_pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/PID", str(worker_pid), "/T", "/F"],
        creationflags=CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--secret-file", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    worker_pid_path = data_dir / "bridge.worker.pid"
    command = [
        sys.executable,
        "-m",
        "wechat_bridge.daemon",
        "--config",
        args.config,
        "--secret-file",
        args.secret_file,
        "--log",
        args.log,
        "--log-max-mb",
        "10",
        "--log-backups",
        "5",
    ]
    while True:
        stop_stale_worker(worker_pid_path)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parent.parent),
                creationflags=CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
            )
            process.wait()
        except Exception:
            time.sleep(5)
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
