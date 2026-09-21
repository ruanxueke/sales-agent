"""公众号管理接口：菜单读取、发布与删除"""
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from connectors.wechat_official import official_client
from core.security import require_admin, require_api_key

router = APIRouter(prefix="/api/v1", tags=["official"], dependencies=[Depends(require_api_key)])


class MenuModel(BaseModel):
    button: list[dict] = []


@router.get("/official/menu")
async def get_official_menu():
    return official_client.get_menu()


@router.post("/official/menu", dependencies=[Depends(require_admin)])
async def publish_official_menu(req: MenuModel):
    return official_client.create_menu({"button": req.button})


@router.delete("/official/menu", dependencies=[Depends(require_admin)])
async def delete_official_menu():
    return official_client.delete_menu()
