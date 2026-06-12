"""
购物车 REST API — 为客户端提供直接操作购物车的接口。

设计说明：
    - 对话式操作走 chat SSE + cart_agent 路径
    - 客户端按钮直接操作走此 REST 端点
    - 下单 API 支持用户自结算，无需 AI 介入

核心功能：
    - 获取购物车内容（GET /api/cart/{session_id}）
    - 添加商品（POST /api/cart/add）
    - 删除商品（DELETE /api/cart/{session_id}/{index}）
    - 更新数量（PUT /api/cart/{session_id}/{index}）
    - 清空购物车（DELETE /api/cart/{session_id}/clear）
    - 直接下单（POST /api/cart/orders）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/cart", tags=["cart"])

_session_manager = None


def set_session_manager(mgr):
    global _session_manager
    _session_manager = mgr


def _check_init():
    if _session_manager is None:
        raise HTTPException(status_code=503, detail="服务正在初始化中")


class AddToCartRequest(BaseModel):
    session_id: str
    product_id: str
    quantity: int = 1


class UpdateCartRequest(BaseModel):
    session_id: str
    index: int
    quantity: int


@router.get("/{session_id}")
async def get_cart(session_id: str):
    """获取购物车内容"""
    _check_init()
    items = _session_manager.get_cart(session_id)
    total = sum(i["price"] * i["quantity"] for i in items)
    return {"session_id": session_id, "items": items, "total": round(total, 2), "count": len(items)}


@router.post("/add")
async def add_to_cart(req: AddToCartRequest):
    """添加商品到购物车"""
    _check_init()
    from utils.product_repo import product_repo
    product = product_repo.get(req.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    import os
    base_url = os.getenv("SERVER_BASE_URL", "http://localhost:8080").rstrip("/")
    image_url = ""
    if hasattr(product, 'image_path') and product.image_path:
        image_url = f"{base_url}/static/{product.image_path}"
    item = {
        "product_id": product.id,
        "name": product.title,
        "brand": product.brand or "",
        "price": product.base_price,
        "quantity": req.quantity,
        "image_url": image_url,
    }
    items = _session_manager.add_to_cart(req.session_id, item)
    total = sum(i["price"] * i["quantity"] for i in items)
    return {"items": items, "total": round(total, 2), "count": len(items)}


@router.delete("/{session_id}/{index}")
async def remove_from_cart(session_id: str, index: int):
    """按索引删除购物车商品"""
    _check_init()
    items = _session_manager.remove_from_cart(session_id, index)
    total = sum(i["price"] * i["quantity"] for i in items)
    return {"items": items, "total": round(total, 2), "count": len(items)}


@router.put("/{session_id}/{index}")
async def update_cart_item(session_id: str, index: int, req: UpdateCartRequest):
    """更新购物车商品数量"""
    _check_init()
    items = _session_manager.update_cart_quantity(session_id, req.index, req.quantity)
    total = sum(i["price"] * i["quantity"] for i in items)
    return {"items": items, "total": round(total, 2), "count": len(items)}


@router.delete("/{session_id}/clear")
async def clear_cart(session_id: str):
    """清空购物车"""
    _check_init()
    _session_manager.clear_cart(session_id)
    return {"items": [], "total": 0, "count": 0}


# 下单 API（用户自结算路径 — 直接提交订单，不走 AI 对话）


class PlaceOrderRequest(BaseModel):
    session_id: str
    address: str

@router.post("/orders")
async def place_order(req: PlaceOrderRequest):
    """用户自结算：直接提交订单，无需 AI 介入"""
    _check_init()
    from datetime import datetime
    items = _session_manager.get_cart(req.session_id)
    if not items:
        raise HTTPException(status_code=400, detail="购物车为空")
    total = sum(i["price"] * i["quantity"] for i in items)
    order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    # 持久化到 session
    session = _session_manager.get_session(req.session_id) if hasattr(_session_manager, 'get_session') else None
    if session:
        try:
            import asyncio
            from db import relational as _db
            session.order_state = {"step": "done", "address": req.address, "order_id": order_id}
            asyncio.create_task(_db.update_session_state(req.session_id, order_state=session.order_state))
        except Exception as e:
            print(f"[orders] 持久化失败: {e}")
    # 清空购物车
    _session_manager.clear_cart(req.session_id)
    return {
        "order_id": order_id,
        "items": items,
        "total": round(total, 2),
        "address": req.address,
        "status": "confirmed"
    }
