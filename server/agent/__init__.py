"""Agent 编排层 — 状态机 + 子 Agents"""

from agent.state_machine import AgentState, get_next_state, is_agent_allowed
from agent.search_agent import SearchAgent, search_agent
from agent.compare_agent import CompareAgent, compare_agent
from agent.scene_agent import SceneAgent, scene_agent


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
