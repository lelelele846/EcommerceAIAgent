"""
SSE 事件流 Schema — 类型安全的 SSE 事件定义。

所有 Agent 输出最终都转成这里的某个事件类型推给客户端。
用 Pydantic 校验字段，避免手动 json.dumps 拼写错误。

用法:
    from models.events import ev
    yield ev.thinking("正在理解您的需求...").to_sse()
    yield ev.tool_progress("hybrid_search", "正在为您检索商品...").to_sse()
    yield ev.text_delta("为您推荐以下商品：").to_sse()
    yield ev.product_card(product_id, title, brand, image_url, price, sub_category).to_sse()
    yield ev.done(session_id, "browsing").to_sse()
"""
import json
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    THINKING = "thinking"
    TOOL_PROGRESS = "tool_progress"
    TEXT_DELTA = "text_delta"
    CONTENT = "content"              # 兼容旧格式
    PRODUCT_CARD = "product_card"
    PRODUCT_CARD_LIST = "product_card_list"
    COMPARISON_TABLE = "comparison_table"
    COMPARISON = "comparison"        # 兼容旧格式
    CLARIFICATION = "clarification"
    IMAGE_SEARCHING = "image_searching"
    START = "start"
    END = "end"
    ERROR = "error"
    DONE = "done"
    CART_UPDATE = "cart_update"
    ORDER_CONFIRMED = "order_confirmed"


class SSEEvent(BaseModel):
    """SSE 事件统一结构 — to_sse() 生成符合协议的字符串"""
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)

    def to_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False)
        return f"event: {self.type.value}\ndata: {payload}\n\n"

    def to_sse_compact(self) -> str:
        """兼容旧格式：不带 event: 行，只发 data: 行（type 写入 JSON 内）"""
        payload = json.dumps({"type": self.type.value, **self.data}, ensure_ascii=False)
        return f"data: {payload}\n\n"


# ===== 各事件 data 的类型化构造（工厂方法）=====

def thinking(message: str = "正在理解您的需求...") -> SSEEvent:
    return SSEEvent(type=EventType.THINKING, data={"message": message})


def tool_progress(tool: str, message: str) -> SSEEvent:
    return SSEEvent(type=EventType.TOOL_PROGRESS, data={"tool": tool, "message": message})



def content(text: str) -> SSEEvent:
    """兼容旧格式：content 事件"""
    return SSEEvent(type=EventType.CONTENT, data={"content": text})


def product_card_compact(product_id: str, product: dict) -> SSEEvent:
    """兼容旧格式：product_card + product 嵌套"""
    return SSEEvent(type=EventType.PRODUCT_CARD, data={
        "product_id": product_id,
        "product": product,
    })


def comparison_table(
    products: list[dict],
    dimensions: list[dict],
    recommendation: Optional[dict] = None,
) -> SSEEvent:
    """
    多商品结构化对比表。
      products:       [{product_id, title, price, image_url}]
      dimensions:     [{name, values:[...]}]，values 顺序与 products 对齐
      recommendation: {product_id, reason} 或 None
    """
    data: dict = {"products": products, "dimensions": dimensions}
    if recommendation is not None:
        data["recommendation"] = recommendation
    return SSEEvent(type=EventType.COMPARISON_TABLE, data=data)


def image_searching(message: str = "正在分析图片…") -> SSEEvent:
    return SSEEvent(type=EventType.IMAGE_SEARCHING, data={"message": message})


def clarification(question: str, options: list[str]) -> SSEEvent:
    return SSEEvent(
        type=EventType.CLARIFICATION,
        data={"question": question, "options": options},
    )


def cart_update(items: list[dict], total: float, action: str = "add") -> SSEEvent:
    """购物车状态变更事件。"""
    return SSEEvent(type=EventType.CART_UPDATE, data={
        "items": items,
        "total": round(total, 2),
        "action": action,
        "count": len(items),
    })


def order_confirmed(order_id: str, items: list[dict], total: float) -> SSEEvent:
    """下单成功事件，触发客户端展示订单详情页"""
    return SSEEvent(type=EventType.ORDER_CONFIRMED, data={
        "order_id": order_id,
        "items": items,
        "total": round(total, 2),
        "count": len(items),
    })


def end(complete: bool = True) -> SSEEvent:
    """兼容旧格式 end 事件"""
    return SSEEvent(type=EventType.END, data={"complete": complete})


def error(code: str, message: str) -> SSEEvent:
    return SSEEvent(type=EventType.ERROR, data={"code": code, "message": message})


