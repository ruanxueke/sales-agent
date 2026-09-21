"""instance_id 与实际微信账号的绑定。

问题
----
`instance_id` 原来是配置文件里一个纯手写的字符串（例如 `local-windows-wechat`），
和这台机器上真正登录的微信账号之间没有任何约束。于是：

  * 同一台机器换了一个微信账号（或同一个进程被复用到别的账号）时，`instance_id`
    不变 —— 中台是按 `claimed_by=instance_id` 回执任务的，A 账号的回复可能被
    B 账号确认掉；
  * 控制台按 `instance_id` 聚合展示，账号一换，界面上的历史数据就是错位的；
  * 反过来，账号没解析出来的时候（"已连接但待识别"），控制台也看不出到底
    绑没绑上、绑的是谁。

做法
----
把「这个 instance 上一次实际跑的是哪个账号」落盘（`data/instance_binding.json`），
每次解析出真实账号后比对：

  * `new`      首次落盘，正常启动
  * `match`    与上次一致，正常启动
  * `rebound`  账号变了且允许改绑，重新落盘
  * `conflict` 账号变了但不允许改绑 —— 此时**自动给 instance_id 加账号后缀**，
               让两个账号在服务端天然是两个实例，避免任务被串号回执。

之所以冲突时选择"自动改后缀"而不是"直接拒绝启动"：桥接跑在客户的 Windows 机器上，
拒绝启动等于整个接待链路静默停摆，代价远大于改个标识。改后缀会让该实例在中台的
个性化设置回到默认值，但至少链路是通的、且日志里说清了原因。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("wechat_bridge.binding")

BINDING_FILE = "instance_binding.json"

STATUS_NEW = "new"
STATUS_MATCH = "match"
STATUS_REBOUND = "rebound"
STATUS_CONFLICT = "conflict"


def binding_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / BINDING_FILE


def load_binding(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("实例绑定文件损坏，按未绑定处理: %s", exc)
        return {}


def save_binding(path: str | Path, instance_id: str, account_id: str) -> None:
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "instance_id": instance_id,
            "account_id": account_id,
            "bound_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as exc:
        logger.warning("实例绑定写入失败: %s", exc)


def resolve_instance(
    instance_id: str,
    account_id: str,
    path: str | Path,
    *,
    allow_rebind: bool = False,
) -> tuple[str, str]:
    """返回 (生效的 instance_id, 状态)。

    账号还没解析出来（account_id 为空）时原样返回，不做任何绑定动作 ——
    "还没识别到账号"和"连到了别的账号"是两件事，日志要能分辨。
    """
    instance_id = (instance_id or "").strip() or "local-wechat"
    account_id = (account_id or "").strip()
    if not account_id:
        return instance_id, "unresolved"

    bound = load_binding(path)
    bound_instance = str(bound.get("instance_id") or "")
    bound_account = str(bound.get("account_id") or "")

    if not bound_account:
        save_binding(path, instance_id, account_id)
        logger.info("实例已绑定微信账号 instance=%s account=%s", instance_id, account_id)
        return instance_id, STATUS_NEW

    if bound_account == account_id:
        if bound_instance != instance_id:
            # 同一个账号换了 instance_id：等价于改名，按新名字落盘即可。
            save_binding(path, instance_id, account_id)
            logger.info("实例标识更新 instance=%s account=%s", instance_id, account_id)
        return instance_id, STATUS_MATCH

    # 走到这里说明：同一个 instance 上出现了不同的微信账号。
    if allow_rebind:
        save_binding(path, instance_id, account_id)
        logger.warning(
            "微信账号已变更并重新绑定 instance=%s %s -> %s",
            instance_id, bound_account, account_id,
        )
        return instance_id, STATUS_REBOUND

    scoped = f"{instance_id}#{account_id}"
    logger.error(
        "检测到 instance_id 被复用于另一个微信账号：instance=%s 原账号=%s 当前账号=%s。"
        "为避免两个账号互相回执任务，本次以 %s 启动（中台会把它当作新实例，"
        "个性化设置回到默认值）。如确认就是换了账号，请在 config.json 里"
        "打开 allow_instance_rebind 或清空 data/%s。",
        instance_id, bound_account or "-", account_id, scoped, BINDING_FILE,
    )
    return scoped, STATUS_CONFLICT


def describe(instance_id: str, account_id: str, path: str | Path) -> dict:
    """给心跳/自检用的只读快照。"""
    bound = load_binding(path)
    return {
        "instance_id": instance_id,
        "account_id": account_id,
        "bound_instance_id": str(bound.get("instance_id") or ""),
        "bound_account_id": str(bound.get("account_id") or ""),
        "bound_at": str(bound.get("bound_at") or ""),
        "bound": bool(bound.get("account_id")),
        "match": bool(bound.get("account_id")) and bound.get("account_id") == account_id,
    }
