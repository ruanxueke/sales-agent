"""销售线索中台：统一线索模型、批量导入、公海池、自动分配与回收"""
from __future__ import annotations
import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select

from config.settings import settings
from core.db import init_db, session_scope
from core.models import Lead

logger = logging.getLogger(__name__)

LEAD_STATUSES = ["pending", "assigned", "claimed", "following", "won", "lost"]
LEAD_STATUS_LABELS = {
    "pending": "公海",
    "assigned": "已分配",
    "claimed": "已认领",
    "following": "跟进中",
    "won": "已成交",
    "lost": "已流失",
}
LEAD_SOURCES = [
    "wechat",
    "personal_wechat",
    "official",
    "ad",
    "form",
    "import",
    "other",
]
LEAD_SOURCE_LABELS = {
    "wechat": "个人微信",
    "personal_wechat": "个人微信",
    "official": "公众号",
    "ad": "广告",
    "form": "表单",
    "import": "批量导入",
    "other": "其他",
}

LEAD_FIELDS = {
    "session_id",
    "customer_id",
    "name",
    "display_id",
    "phone",
    "wechat_id",
    "unionid",
    "nickname",
    "source",
    "channel_id",
    "identity",
    "level",
    "goal",
    "budget",
    "interest",
    "stage",
    "intent_level",
    "intent_score",
    "status",
    "owner",
    "sales_status",
    "notes",
    "next_follow_up",
}

HEADER_ALIASES = {
    "姓名": "name",
    "名字": "name",
    "手机": "phone",
    "手机号": "phone",
    "电话": "phone",
    "微信号": "wechat_id",
    "微信": "wechat_id",
    "unionid": "unionid",
    "来源": "source",
    "渠道": "source",
    "广告位": "channel_id",
    "广告位/活码id": "channel_id",
    "活码id": "channel_id",
    "活码": "channel_id",
    "身份": "identity",
    "基础": "level",
    "目标": "goal",
    "预算": "budget",
    "兴趣": "interest",
    "兴趣课程": "interest",
    "意向等级": "intent_level",
    "备注": "notes",
    "客户id": "session_id",
    "会话id": "session_id",
    "昵称": "nickname",
}

IMPORT_TEMPLATE_HEADERS = [
    "姓名",
    "手机号",
    "微信号",
    "unionid",
    "来源",
    "广告位/活码ID",
    "身份",
    "基础",
    "目标",
    "预算",
    "兴趣课程",
    "意向等级",
    "备注",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _datetime_plus(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _normalize_source(source: str, default: str = "import") -> str:
    value = (source or "").strip().lower()
    if value in LEAD_SOURCES:
        return value
    return default


def _normalize_row(row: dict) -> dict:
    result = {}
    for raw_key, raw_value in (row or {}).items():
        if raw_value is None:
            continue
        key = str(raw_key or "").strip()
        alias = HEADER_ALIASES.get(key) or HEADER_ALIASES.get(key.lower())
        canonical = alias or key.lower()
        if canonical not in LEAD_FIELDS:
            continue
        value = str(raw_value).strip()
        if value:
            result[canonical] = value
    if result.get("source"):
        result["source"] = _normalize_source(result["source"])
    return result


def _validate_lead(row: dict) -> Optional[str]:
    if not any(row.get(k) for k in ("phone", "wechat_id", "unionid", "session_id")):
        return "至少需要手机号、微信号、unionid 或客户ID 之一"
    return None


def template_csv() -> str:
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(IMPORT_TEMPLATE_HEADERS)
    return buf.getvalue()


def parse_import_file(filename: str, content: bytes) -> tuple[list[dict], list[dict]]:
    """解析 CSV / Excel 线索文件，返回 (有效行, 错误列表)"""
    name = (filename or "").lower()
    rows: list[dict] = []
    errors: list[dict] = []

    if name.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            sheet = workbook.active
            iterator = sheet.iter_rows(values_only=True)
            headers = []
            for raw in iterator:
                if any(v is not None and str(v).strip() for v in raw):
                    headers = [str(v or "").strip() for v in raw]
                    break
            if not headers:
                return [], [{"row": 1, "reason": "文件为空或缺少表头"}]
            for index, raw in enumerate(iterator, start=2):
                if not any(v is not None and str(v).strip() for v in raw):
                    continue
                row = _normalize_row(dict(zip(headers, raw)))
                reason = _validate_lead(row)
                if reason:
                    errors.append({"row": index, "reason": reason})
                else:
                    rows.append(row)
            workbook.close()
        except Exception as e:
            logger.error(f"Excel 解析失败: {e}")
            return [], [{"row": 1, "reason": f"Excel 解析失败: {e}"}]
        return rows, errors

    if name.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for index, raw in enumerate(reader, start=2):
                row = _normalize_row(raw)
                if not row:
                    continue
                reason = _validate_lead(row)
                if reason:
                    errors.append({"row": index, "reason": reason})
                else:
                    rows.append(row)
        except Exception as e:
            logger.error(f"CSV 解析失败: {e}")
            return [], [{"row": 1, "reason": f"CSV 解析失败: {e}"}]
        return rows, errors

    return [], [{"row": 1, "reason": "仅支持 .csv / .xlsx / .xlsm 文件"}]


class LeadManager:
    """线索管理：统一使用 SQLAlchemy 后端，与现有 CRM 共用数据库"""

    def __init__(self):
        init_db()

    def default_owner(self) -> str:
        return settings.LEAD_DEFAULT_OWNER or settings.SALES_NOTIFY_TARGET or "叙白"

    def _apply(self, obj: Lead, data: dict) -> None:
        for key, value in data.items():
            if key in LEAD_FIELDS:
                setattr(obj, key, value)
        obj.updated_at = _now()

    def create(self, data: dict, tenant_id: int | None = None) -> dict:
        owner = (data.get("owner") or "").strip() or self.default_owner()
        status = data.get("status") or ("assigned" if owner else "pending")
        now = _now()
        with session_scope() as session:
            obj = Lead(
                tenant_id=int(tenant_id or data.get("tenant_id") or 0),
                source=_normalize_source(data.get("source"), "import"),
                status=status,
                owner=owner,
                assigned_at=now if owner else "",
                sla_due_at=_datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS) if owner else "",
                created_at=now,
                updated_at=now,
            )
            self._apply(obj, data)
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def get(self, lead_id: int, tenant_id: int | None = None) -> Optional[dict]:
        with session_scope() as session:
            query = select(Lead).where(Lead.id == lead_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            return _row_to_dict(obj) if obj else None

    def get_by_session_id(
        self,
        session_id: str,
        tenant_id: int | None = None,
    ) -> Optional[dict]:
        if not session_id:
            return None
        with session_scope() as session:
            query = select(Lead).where(Lead.session_id == session_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            return _row_to_dict(obj) if obj else None

    def list(
        self,
        status: str = "",
        owner: str = "",
        source: str = "",
        keyword: str = "",
        limit: int = 500,
        offset: int = 0,
        tenant_id: int | None = None,
    ) -> list[dict]:
        with session_scope() as session:
            query = select(Lead).order_by(Lead.id.desc()).offset(offset).limit(limit)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == tenant_id)
            if status:
                query = query.where(Lead.status == status)
            if owner:
                query = query.where(Lead.owner == owner)
            if source:
                query = query.where(Lead.source == source)
            if keyword:
                like = f"%{keyword}%"
                query = query.where(or_(
                    Lead.name.like(like),
                    Lead.nickname.like(like),
                    Lead.phone.like(like),
                    Lead.wechat_id.like(like),
                    Lead.unionid.like(like),
                    Lead.session_id.like(like),
                ))
            rows = session.execute(query).scalars().all()
            return [_row_to_dict(r) for r in rows]

    def ocean(self, limit: int = 500) -> list[dict]:
        return self.list(status="pending", limit=limit)

    def update(
        self,
        lead_id: int,
        tenant_id: int | None = None,
        **fields,
    ) -> Optional[dict]:
        with session_scope() as session:
            query = select(Lead).where(Lead.id == lead_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            if not obj:
                return None
            data = {k: v for k, v in fields.items() if k in LEAD_FIELDS}
            if data.get("source"):
                data["source"] = _normalize_source(data["source"])
            self._apply(obj, data)
            session.flush()
            return _row_to_dict(obj)

    def assign(
        self,
        lead_id: int,
        owner: str = "",
        tenant_id: int | None = None,
    ) -> Optional[dict]:
        owner = owner.strip() or self.default_owner()
        with session_scope() as session:
            query = select(Lead).where(Lead.id == lead_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            if not obj:
                return None
            now = _now()
            obj.owner = owner
            obj.status = "assigned"
            obj.assigned_at = now
            obj.sla_due_at = _datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS)
            obj.recycled_at = ""
            obj.updated_at = now
            session.flush()
            return _row_to_dict(obj)

    def claim(
        self,
        lead_id: int,
        owner: str = "",
        tenant_id: int | None = None,
    ) -> Optional[dict]:
        owner = owner.strip() or self.default_owner()
        with session_scope() as session:
            query = select(Lead).where(Lead.id == lead_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            if not obj:
                return None
            now = _now()
            obj.owner = owner
            obj.status = "claimed"
            obj.assigned_at = now
            obj.sla_due_at = _datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS)
            obj.recycled_at = ""
            obj.updated_at = now
            session.flush()
            return _row_to_dict(obj)

    def follow(
        self,
        lead_id: int,
        owner: str = "",
        note: str = "",
        next_follow_up: str = "",
        tenant_id: int | None = None,
    ) -> Optional[dict]:
        with session_scope() as session:
            query = select(Lead).where(Lead.id == lead_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            if not obj:
                return None
            now = _now()
            obj.owner = owner.strip() or obj.owner or self.default_owner()
            obj.status = "following"
            obj.last_follow_at = now
            obj.updated_at = now
            if next_follow_up:
                obj.next_follow_up = next_follow_up
            if note:
                obj.notes = (obj.notes or "").strip()
                obj.notes = f"{obj.notes}\n[{now}] {note}".strip()
            session.flush()
            return _row_to_dict(obj)

    def mark_status(
        self,
        lead_id: int,
        status: str,
        tenant_id: int | None = None,
    ) -> Optional[dict]:
        if status not in LEAD_STATUSES:
            raise ValueError(f"未知线索状态: {status}")
        with session_scope() as session:
            query = select(Lead).where(Lead.id == lead_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            obj = session.execute(query).scalars().first()
            if not obj:
                return None
            obj.status = status
            obj.updated_at = _now()
            if status in ("won", "lost"):
                obj.sla_due_at = ""
            session.flush()
            return _row_to_dict(obj)

    def recycle(self, tenant_id: int | None = None) -> int:
        """超时未跟进线索退回公海，可重新被认领"""
        now = _now()
        recycled = 0
        with session_scope() as session:
            query = select(Lead).where(
                Lead.status.in_(["assigned", "claimed", "following"]),
                Lead.sla_due_at != "",
                Lead.sla_due_at < now,
            )
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == int(tenant_id))
            rows = session.execute(query).scalars().all()
            for obj in rows:
                obj.status = "pending"
                obj.owner = ""
                obj.sla_due_at = ""
                obj.assigned_at = ""
                obj.recycled_at = now
                obj.updated_at = now
                recycled += 1
        if recycled:
            logger.info("线索回收完成，共 %s 条退回公海", recycled)
        return recycled

    def upsert_from_channel(
        self,
        session_id: str,
        source: str,
        channel_id: str = "",
        nickname: str = "",
        tenant_id: int | None = None,
    ) -> dict:
        """公众号关注/扫码等渠道事件：无客户对话时也先沉淀一条线索"""
        with session_scope() as session:
            query = select(Lead).where(Lead.session_id == session_id)
            if tenant_id is not None:
                query = query.where(Lead.tenant_id == tenant_id)
            obj = session.execute(query).scalar_one_or_none()
            now = _now()
            if obj:
                if channel_id and not obj.channel_id:
                    obj.channel_id = channel_id
                if not obj.source:
                    obj.source = _normalize_source(source)
                if nickname and obj.nickname != nickname:
                    old_name = str(obj.nickname or "").strip()
                    obj.nickname = nickname
                    display_id = str(obj.display_id or "").strip()
                    if (
                        not display_id
                        or display_id == old_name
                        or (old_name and display_id.startswith(old_name) and display_id[len(old_name):].isdigit())
                    ):
                        obj.display_id = nickname
                if obj.status == "pending" or not obj.owner:
                    obj.owner = self.default_owner()
                    obj.status = "assigned"
                    obj.assigned_at = now
                    obj.sla_due_at = _datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS)
                obj.last_message_at = now
                obj.updated_at = now
                session.flush()
                return _row_to_dict(obj)

            obj = Lead(
                tenant_id=tenant_id or 0,
                session_id=session_id,
                nickname=nickname or "",
                source=_normalize_source(source),
                channel_id=channel_id or "",
                owner=self.default_owner(),
                status="assigned",
                assigned_at=now,
                last_message_at=now,
                sla_due_at=_datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS),
                created_at=now,
                updated_at=now,
            )
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def upsert_from_customer(self, customer: dict, source: str = "wechat") -> Optional[dict]:
        """客户达到 L3 建档时同步生成/更新线索，并固定分配给默认接收人"""
        session_id = customer.get("session_id") or ""
        phone = customer.get("phone") or ""
        wechat_id = customer.get("wechat_id") or ""
        with session_scope() as session:
            obj = None
            if session_id:
                tenant_id = customer.get("tenant_id")
                query = select(Lead).where(Lead.session_id == session_id)
                if tenant_id is not None:
                    query = query.where(Lead.tenant_id == int(tenant_id))
                obj = session.execute(query).scalar_one_or_none()
            if obj is None and phone:
                obj = session.execute(
                    select(Lead).where(Lead.phone == phone)
                ).scalars().first()
            if obj is None and wechat_id:
                obj = session.execute(
                    select(Lead).where(Lead.wechat_id == wechat_id)
                ).scalars().first()

            now = _now()
            fields = {
                "name": customer.get("name") or "",
                "phone": phone,
                "wechat_id": wechat_id,
                "display_id": customer.get("display_id") or "",
                "nickname": customer.get("nickname") or "",
                "identity": customer.get("identity") or "",
                "level": customer.get("level") or "",
                "goal": customer.get("goal") or "",
                "budget": customer.get("budget") or "",
                "interest": customer.get("interest") or "",
                "stage": customer.get("stage") or "new",
                "intent_level": customer.get("intent_level") or "",
                "intent_score": int(customer.get("intent_score") or 0),
            }
            if obj:
                if session_id:
                    obj.session_id = session_id
                if customer.get("id"):
                    obj.customer_id = customer.get("id")
                self._apply(obj, fields)
                if not obj.source:
                    obj.source = _normalize_source(source)
                if obj.status != "won":
                    obj.owner = obj.owner or self.default_owner()
                    obj.status = "assigned"
                    obj.assigned_at = obj.assigned_at or now
                    obj.sla_due_at = _datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS)
                obj.last_message_at = now
                obj.updated_at = now
                session.flush()
                return _row_to_dict(obj)

            obj = Lead(
                tenant_id=int(customer.get("tenant_id") or 0),
                session_id=session_id,
                customer_id=customer.get("id"),
                source=_normalize_source(source),
                owner=self.default_owner(),
                status="assigned",
                assigned_at=now,
                last_message_at=now,
                sla_due_at=_datetime_plus(settings.LEAD_RECYCLE_AFTER_DAYS),
                created_at=now,
                updated_at=now,
            )
            self._apply(obj, fields)
            session.add(obj)
            session.flush()
            return _row_to_dict(obj)

    def import_rows(
        self,
        rows: list[dict],
        tenant_id: int | None = None,
    ) -> dict:
        created = 0
        updated = 0
        errors: list[dict] = []
        for index, raw in enumerate(rows, start=1):
            row = _normalize_row(raw)
            reason = _validate_lead(row)
            if reason:
                errors.append({"row": index, "reason": reason})
                continue
            matched = self._find_existing(row, tenant_id=tenant_id)
            if matched:
                self.update(
                    matched["id"],
                    tenant_id=tenant_id,
                    **{k: v for k, v in row.items() if k != "source"},
                )
                updated += 1
            else:
                self.create(row, tenant_id=tenant_id)
                created += 1
        return {
            "total": len(rows),
            "created": created,
            "updated": updated,
            "failed": len(errors),
            "errors": errors,
        }

    def _find_existing(
        self,
        row: dict,
        tenant_id: int | None = None,
    ) -> Optional[dict]:
        with session_scope() as session:
            obj = None
            if row.get("session_id"):
                query = select(Lead).where(Lead.session_id == row["session_id"])
                if tenant_id is not None:
                    query = query.where(Lead.tenant_id == int(tenant_id))
                obj = session.execute(query).scalars().first()
            if obj is None and row.get("phone"):
                query = select(Lead).where(Lead.phone == row["phone"])
                if tenant_id is not None:
                    query = query.where(Lead.tenant_id == int(tenant_id))
                obj = session.execute(query).scalars().first()
            if obj is None and row.get("wechat_id"):
                query = select(Lead).where(Lead.wechat_id == row["wechat_id"])
                if tenant_id is not None:
                    query = query.where(Lead.tenant_id == int(tenant_id))
                obj = session.execute(query).scalars().first()
            if obj is None and row.get("unionid"):
                query = select(Lead).where(Lead.unionid == row["unionid"])
                if tenant_id is not None:
                    query = query.where(Lead.tenant_id == int(tenant_id))
                obj = session.execute(query).scalars().first()
            return _row_to_dict(obj) if obj else None

    def stats(self, tenant_id: int | None = None) -> dict:
        leads = self.list(limit=100000, tenant_id=tenant_id)
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        week_cutoff = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        status_counts = {s: 0 for s in LEAD_STATUSES}
        source_counts = {}
        owner_counts = {}
        today_new = 0
        week_new = 0
        for lead in leads:
            status = lead.get("status") or "pending"
            status_counts[status] = status_counts.get(status, 0) + 1
            source = lead.get("source") or "other"
            source_counts[source] = source_counts.get(source, 0) + 1
            owner = lead.get("owner") or ""
            if owner:
                owner_counts[owner] = owner_counts.get(owner, 0) + 1
            created = (lead.get("created_at") or "")[:10]
            if created == today:
                today_new += 1
            if created >= week_cutoff:
                week_new += 1
        return {
            "total": len(leads),
            "ocean": status_counts["pending"],
            "assigned": status_counts["assigned"],
            "claimed": status_counts["claimed"],
            "following": status_counts["following"],
            "won": status_counts["won"],
            "lost": status_counts["lost"],
            "today_new": today_new,
            "week_new": week_new,
            "by_status": status_counts,
            "by_source": source_counts,
            "by_owner": owner_counts,
        }


lead_manager = LeadManager()
