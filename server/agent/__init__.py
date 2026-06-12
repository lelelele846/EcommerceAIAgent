"""
多组件协调模块 — 负责会话流程控制和子模块初始化。

包含的子组件：
    - SearchAgent：单品发现和需求明确化
    - CompareAgent：多商品横向分析
    - SceneAgent：情境化购物规划
    - CartAgent：采购篮操作管理
    - OrderAgent：交易完成引导

依赖注入：
    - setup_agents() 将 retriever、doubao_service、session_manager 注入各组件单例
    - 解耦服务实例化，便于单元测试和模块替换
"""

from agent.state_machine import AgentState, get_next_state, is_agent_allowed
from agent.search_agent import SearchAgent, search_agent
from agent.compare_agent import CompareAgent, compare_agent
from agent.scene_agent import SceneAgent, scene_agent
from agent.cart_agent import CartAgent, cart_agent
from agent.order_agent import OrderAgent, order_agent


def setup_agents(retriever, doubao_service, session_manager):
    """注入服务依赖到各 Agent 单例"""
    search_agent.retriever = retriever
    search_agent.doubao = doubao_service
    search_agent.sessions = session_manager

    compare_agent.retriever = retriever
    compare_agent.doubao = doubao_service
    compare_agent.sessions = session_manager

    scene_agent.doubao = doubao_service
    scene_agent.sessions = session_manager

    cart_agent.retriever = retriever
    cart_agent.doubao = doubao_service
    cart_agent.sessions = session_manager

    order_agent.retriever = retriever
    order_agent.doubao = doubao_service
    order_agent.sessions = session_manager
