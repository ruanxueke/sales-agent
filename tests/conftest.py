"""pytest 收集配置。

tests/ 下的文件分两类，不能一视同仁：

* **脚本式自测**（9 个）：用 `python tests/xxx.py` 直接跑，靠 print + 退出码判断，
  顶层就带断言 / 建库 / 起线程。被 pytest 当模块导入时这些顶层代码会立刻执行，
  于是出现 `AssertionError: behavior-stats` 之类的 collection error——
  看起来像测试坏了，其实是"把一个 CLI 脚本当测试模块导入"的必然结果。
* **真正的 pytest 用例**：`test_concurrency.py`（6 个 test_* 函数），保留给 pytest。

`collect_ignore` 放在 conftest.py 而不是 pytest.ini：pytest 9 已经不认 ini 里的
`collect_ignore_glob`（会 warning "Unknown config option"），conftest 里的全局变量
才是跨版本稳定的接口。

脚本式自测不会被漏掉——`scripts/quality_gate.py` 的第 4 项会逐个执行它们。
"""
collect_ignore = [
    "test_backup.py",
    "test_business_modules.py",
    "test_enterprise.py",
    "test_leads.py",
    "test_message_splitter.py",
    "test_personal_wechat.py",
    "test_self_check.py",
    "test_solda_modules.py",
    "test_tenant_isolation.py",
    "test_commercial_hardening.py",
]
