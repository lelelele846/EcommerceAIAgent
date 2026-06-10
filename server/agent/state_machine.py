"""
导购会话状态机 — 定义导购阶段和转移规则。

实际 Agent 清单：
  - search_agent  — 单品搜索推荐（含 slot-filling）
  - compare_agent — 多商品对比
  - scene_agent   — 场景化组合规划

状态和转移只覆盖已实现的三个 agent（搜索推荐、商品对比、场景规划）。
"""
from enum import Enum


class AgentState(str, Enum):
    BROWSING = "browsing"           # 浏览/搜索商品（默认状态）
    COMPARING = "comparing"          # 对比多个商品
    SCENE_PLANNING = "scene_planning"  # 场景化方案规划


# 每个状态允许路由的子 Agent
STATE_ALLOWED_AGENTS: dict[AgentState, list[str]] = {
    AgentState.BROWSING:        ["search", "compare", "scene"],
    AgentState.COMPARING:       ["search", "compare", "scene"],
    AgentState.SCENE_PLANNING:  ["search", "scene"],
}

# 意图 → 下一个状态的转移规则
# key: (当前状态, 意图)  value: 下一个状态
TRANSITIONS: dict[tuple[AgentState, str], AgentState] = {
    # 从浏览出发
    (AgentState.BROWSING,        "compare"):     AgentState.COMPARING,
    (AgentState.BROWSING,        "scene"):       AgentState.SCENE_PLANNING,
    # 从对比出发
    (AgentState.COMPARING,       "search"):      AgentState.BROWSING,
    (AgentState.COMPARING,       "scene"):       AgentState.SCENE_PLANNING,
    # 从场景规划出发
    (AgentState.SCENE_PLANNING,  "search"):      AgentState.BROWSING,
    (AgentState.SCENE_PLANNING,  "compare"):     AgentState.COMPARING,
}


def get_next_state(current: AgentState, intent: str) -> AgentState:
    """根据当前状态和意图返回下一个状态，无匹配则状态不变"""
    return TRANSITIONS.get((current, intent), current)


def get_allowed_agents(state: AgentState) -> list[str]:
    """返回当前状态允许调用的子 Agent 列表"""
    return STATE_ALLOWED_AGENTS.get(state, ["search"])


def is_agent_allowed(state: AgentState, agent_name: str) -> bool:
    return agent_name in get_allowed_agents(state)
