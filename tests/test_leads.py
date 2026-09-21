"""销售线索中台测试：创建、导入去重、公海回收、L3 自动建档"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 使用独立临时数据库，避免污染正式 CRM 数据
_tmp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import config.settings as cfg
from core.lead import LEAD_STATUSES, lead_manager, parse_import_file, template_csv

print("=" * 60)
print("销售客服智能体 - 线索中台测试")
print("=" * 60)

# ==================== 测试1：创建线索并固定分配给叙白 ====================
print("\n--- 测试1: 创建线索默认归属叙白 ---")

lead = lead_manager.create({
    "name": "张客户",
    "phone": "13800000001",
    "source": "import",
    "channel_id": "ad-001",
    "goal": "AI副业变现",
})
assert lead["owner"] == "叙白", f"默认归属人应为叙白，实际 {lead['owner']}"
assert lead["status"] == "assigned", "新线索应自动分配"
assert lead["source"] == "import"
assert lead["channel_id"] == "ad-001"
print(f"  创建线索 #{lead['id']} 归属人={lead['owner']} 状态={lead['status']} [OK]")

# ==================== 测试2：批量导入 CSV 解析与去重 ====================
print("\n--- 测试2: CSV 导入、模板、去重 ---")

csv_content = (
    "\ufeff姓名,手机号,微信号,来源,广告位/活码ID,目标\n"
    "李客户,13800000002,li_wx,ad,ad-002,AI内容创作\n"
    "王客户,13800000003,wang_wx,form,form-001,AI副业\n"
    "错误行,,\n"
).encode("utf-8")

rows, errors = parse_import_file("leads.csv", csv_content)
assert len(rows) == 2, f"有效行应为 2，实际 {len(rows)}"
assert len(errors) == 1, "缺少联系方式的行应报错"
assert rows[0]["channel_id"] == "ad-002", "模板表头 广告位/活码ID 应映射到 channel_id"
print(f"  解析有效 {len(rows)} 条，错误 {len(errors)} 条 [OK]")

result = lead_manager.import_rows(rows)
assert result["created"] == 2, "首次导入应新增 2 条"
assert result["failed"] == 0

# 再次导入同手机号，应更新而不是新增
rows2, _ = parse_import_file("leads.csv", csv_content)
result2 = lead_manager.import_rows(rows2[:1])
assert result2["updated"] == 1 and result2["created"] == 0, "重复手机号应去重更新"
print(f"  首次导入新增 {result['created']} 条，重复导入更新 {result2['updated']} 条 [OK]")

template = template_csv()
assert "手机号" in template and "广告位/活码ID" in template
print(f"  模板下载内容完整 [OK]")

# ==================== 测试3：公海回收 ====================
print("\n--- 测试3: 超时线索退回公海 ---")

cfg.settings.LEAD_RECYCLE_AFTER_DAYS = -1
expire_lead = lead_manager.create({
    "name": "超时客户",
    "phone": "13800000009",
    "source": "form",
})
assert expire_lead["status"] == "assigned"

recycled = lead_manager.recycle()
assert recycled >= 1, "超时线索应被回收"
ocean = lead_manager.ocean()
assert any(item["id"] == expire_lead["id"] for item in ocean), "回收后应出现在公海"
assert all(item["owner"] == "" for item in ocean), "公海线索不应有归属人"
print(f"  回收 {recycled} 条，公海当前 {len(ocean)} 条 [OK]")

# 公海认领后重新回到归属人
claimed = lead_manager.claim(expire_lead["id"])
assert claimed["owner"] == "叙白" and claimed["status"] == "claimed"
print(f"  认领后归属人={claimed['owner']} 状态={claimed['status']} [OK]")

# ==================== 测试4：L3 客户自动建档为线索 ====================
print("\n--- 测试4: L3 客户自动生成线索 ---")

customer = {
    "id": 1001,
    "session_id": "wx_openid_test",
    "nickname": "高意向客户",
    "phone": "13800000010",
    "name": "赵客户",
    "goal": "AI副业变现",
    "budget": "5000",
    "stage": "recommended",
    "intent_level": "L3",
    "intent_score": 70,
}
lead_from_customer = lead_manager.upsert_from_customer(customer, source="official")
assert lead_from_customer["session_id"] == "wx_openid_test"
assert lead_from_customer["owner"] == "叙白"
assert lead_from_customer["status"] == "assigned"
assert lead_from_customer["intent_level"] == "L3"
print(f"  线索 #{lead_from_customer['id']} 已建档，归属 {lead_from_customer['owner']} [OK]")

# 同一客户重复 L3，应更新而不是新建
again = lead_manager.upsert_from_customer(customer, source="official")
assert again["id"] == lead_from_customer["id"], "重复 L3 应复用同一条线索"
print(f"  重复 L3 复用线索 #{again['id']} [OK]")

# ==================== 测试5：渠道事件沉淀 ====================
print("\n--- 测试5: 公众号带参二维码沉淀线索 ---")

channel_lead = lead_manager.upsert_from_channel(
    session_id="wx_openid_scan",
    source="official",
    channel_id="qrscene_course_a",
)
assert channel_lead["source"] == "official"
assert channel_lead["channel_id"] == "qrscene_course_a"
assert channel_lead["owner"] == "叙白"
print(f"  线索 #{channel_lead['id']} 渠道=official 广告位/活码={channel_lead['channel_id']} [OK]")

# ==================== 测试6：首次私聊先建线索，L3 后关联客户 ====================
print("\n--- 测试6: 首次私聊线索升级正式客户 ---")

from core.agent import sales_agent
from core.sales_crm import crm

first_session = "personal_wechat_first_contact"
sales_agent._ensure_channel_lead(first_session, "初次咨询客户", "personal_wechat")
first_lead = lead_manager.get_by_session_id(first_session)
assert first_lead is not None, "首次私聊应自动创建线索"
assert first_lead["source"] == "personal_wechat", "个人微信线索来源保存错误"
assert first_lead["nickname"] == "初次咨询客户"
print(f"  首次私聊生成线索 #{first_lead['id']} [OK]")

customer = crm.get_or_create(
    first_session,
    nickname="初次咨询客户",
    source="personal_wechat",
)
sales_agent._sync_lead_customer(customer, "personal_wechat")
upgraded = lead_manager.get_by_session_id(first_session)
assert upgraded["id"] == first_lead["id"], "升级正式客户时不应重复创建线索"
assert upgraded["customer_id"] == customer["id"], "线索应关联正式客户"
print(f"  L3 后线索 #{upgraded['id']} 关联客户 #{upgraded['customer_id']} [OK]")

from core.db import engine
engine.dispose()
try:
    os.unlink(_tmp_db.name)
except OSError:
    pass
print("\n" + "=" * 60)
print("线索中台测试全部通过!")
print("=" * 60)
