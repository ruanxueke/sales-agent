"""请求级租户上下文和 SQLAlchemy 自动隔离。"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria


_tenant_id: ContextVar[int | None] = ContextVar("sales_agent_tenant_id", default=None)
_tenant_filter_disabled: ContextVar[bool] = ContextVar(
    "sales_agent_tenant_filter_disabled",
    default=False,
)


def set_tenant_context(tenant_id: int | None) -> object:
    value = None if tenant_id is None else int(tenant_id)
    return _tenant_id.set(value)


def reset_tenant_context(token) -> None:
    _tenant_id.reset(token)


def get_tenant_context() -> int | None:
    return _tenant_id.get()


@contextmanager
def tenant_scope(tenant_id: int | None, *, disable_filter: bool = False):
    tenant_token = set_tenant_context(tenant_id)
    disabled_token = _tenant_filter_disabled.set(bool(disable_filter))
    try:
        yield
    finally:
        _tenant_filter_disabled.reset(disabled_token)
        reset_tenant_context(tenant_token)


@contextmanager
def all_tenants_scope():
    with tenant_scope(None, disable_filter=True):
        yield


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(execute_state) -> None:
    if not execute_state.is_select or execute_state.execution_options.get("include_all_tenants"):
        return
    if _tenant_filter_disabled.get():
        return
    tenant_id = _tenant_id.get()
    if tenant_id is None:
        return
    for mapper in execute_state.all_mappers:
        if "tenant_id" not in mapper.columns:
            continue
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                mapper.class_,
                mapper.class_.tenant_id == tenant_id,
                include_aliases=True,
            )
        )


@event.listens_for(Session, "before_flush")
def _stamp_tenant_id(session, flush_context, instances) -> None:
    tenant_id = _tenant_id.get()
    if tenant_id is None:
        return
    for obj in session.new:
        if not hasattr(obj, "tenant_id"):
            continue
        current = getattr(obj, "tenant_id", None)
        if current in (None, 0, "0", ""):
            setattr(obj, "tenant_id", tenant_id)
