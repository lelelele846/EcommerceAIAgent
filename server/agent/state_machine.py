"""
会话流程控制器 — 跟踪对话阶段流转，按规则限制操作防止状态发散。

内置 Agent：search / compare / scene / cart / order

设计原则：
    - 每个状态只允许合理的下一步操作（search/cart 几乎总可用）
    - compare/scene/order 按上下文限制，避免状态跳变
    - BROWSING 作为枢纽，所有深度操作最终可回到 BROWSING
"""
from enum import Enum


class AgentState(str, Enum):
    BROWSING = "browsing"
    COMPARING = "comparing"
    SCENE_PLANNING = "scene_planning"
    CART = "cart"
    CHECKOUT = "checkout"


AGENT_NAMES = ["search", "compare", "scene", "cart", "order"]


# 每个状态下允许执行的操作（未列出的将被拦截）
STATE_ALLOWED_AGENTS: dict[AgentState, list[str]] = {
    AgentState.BROWSING:        ["search", "compare", "scene", "cart", "order"],
    AgentState.COMPARING:       ["search", "compare", "cart"],
    AgentState.SCENE_PLANNING:  ["search", "scene", "cart"],
    AgentState.CART:            ["search", "compare", "cart", "order"],
    AgentState.CHECKOUT:        ["search", "cart", "order"],
}


# 操作触发后的下一状态（未列出的保持当前状态不变）
TRANSITIONS: dict[tuple[AgentState, str], AgentState] = {
    (AgentState.BROWSING,        "compare"):     AgentState.COMPARING,
    (AgentState.BROWSING,        "scene"):       AgentState.SCENE_PLANNING,
    (AgentState.BROWSING,        "cart"):        AgentState.CART,
    (AgentState.BROWSING,        "order"):       AgentState.CHECKOUT,
    (AgentState.COMPARING,       "search"):      AgentState.BROWSING,
    (AgentState.COMPARING,       "cart"):        AgentState.CART,
    (AgentState.SCENE_PLANNING,  "search"):      AgentState.BROWSING,
    (AgentState.SCENE_PLANNING,  "cart"):        AgentState.CART,
    (AgentState.CART,            "search"):      AgentState.BROWSING,
    (AgentState.CART,            "compare"):     AgentState.COMPARING,
    (AgentState.CART,            "order"):       AgentState.CHECKOUT,
    (AgentState.CHECKOUT,        "search"):      AgentState.BROWSING,
    (AgentState.CHECKOUT,        "cart"):        AgentState.CART,
}


def get_next_state(current: AgentState, intent: str) -> AgentState:
    """返回操作后的下一状态，未定义则保持当前状态。"""
    return TRANSITIONS.get((current, intent), current)


def is_agent_allowed(state: AgentState, agent_name: str) -> bool:
    """检查当前状态是否允许执行该操作。"""
    allowed = STATE_ALLOWED_AGENTS.get(state, AGENT_NAMES)
    return agent_name in allowed
