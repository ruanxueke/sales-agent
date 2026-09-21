"""DPAPI-backed secret storage for the standalone bridge service."""
from __future__ import annotations

import argparse
import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )


def _encrypt(value: str) -> bytes:
    if os.name != "nt":
        raise RuntimeError("secure storage is only available on Windows")
    source = _blob(value.encode("utf-8"))
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source),
        "SalesAgentWechatBridge",
        None,
        None,
        None,
        0,
        ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _decrypt(data: bytes) -> str:
    if os.name != "nt":
        raise RuntimeError("secure storage is only available on Windows")
    source = _blob(data)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def save(path: str | Path, value: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(_encrypt(value))
    os.replace(temp, target)


def load(path: str | Path) -> str:
    return _decrypt(Path(path).read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("save", "load"))
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    if args.action == "load":
        print(load(args.path))
        return 0
    value = os.getenv("WECHAT_BRIDGE_SECRET_VALUE", "")
    if not value:
        raise SystemExit("WECHAT_BRIDGE_SECRET_VALUE is required")
    save(args.path, value)
    print("saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
