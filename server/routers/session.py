"""
会话管理 API — 管理用户会话生命周期和偏好设置。

核心功能：
    - 获取会话信息
    - 更新用户偏好（类目、价格范围、品牌倾向等）
    - 获取会话历史消息
    - 删除会话
    - 获取会话统计
    - 从数据库恢复会话消息（用于客户端回填）

设计说明：
    - 会话数据支持内存 + 数据库双层存储
    - 数据库不可用时自动回退到内存存储
    - 偏好设置持久化到会话，支持跨轮次复用
"""
from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/session", tags=["session"])

# 全局服务实例
_session_manager = None


def set_session_manager(session_manager):
    """设置全局会话管理器实例"""
    global _session_manager
    _session_manager = session_manager


@router.get("/{session_id}")
async def get_session(session_id: str):
    """获取会话信息"""
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.dict()


@router.post("/{session_id}/preferences")
async def update_preferences(session_id: str, preferences: dict):
    """更新用户偏好"""
    _session_manager.update_preferences(session_id, **preferences)
    return {"message": "Preferences updated successfully", "session_id": session_id}


@router.get("/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 10):
    """获取会话历史"""
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "history": session.get_history(limit)}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if session_id in _session_manager.sessions:
        del _session_manager.sessions[session_id]
        return {"message": "Session deleted successfully", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/stats")
async def get_session_stats():
    """获取会话统计信息"""
    active_count = _session_manager.get_active_sessions_count()
    return {"active_sessions": active_count}


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str):
    """🆕 获取会话全部消息（从 DB 读取，用于客户端回填对话历史）"""
    try:
        from db import relational as _db
        messages = await _db.get_all_messages(session_id)
        return {
            "session_id": session_id,
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "blocks": m.get("blocks", []),
                    "timestamp": m.get("created_at"),
                }
                for m in messages
            ],
        }
    except Exception as e:
        # DB 不可用时回退到内存
        session = _session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "session_id": session_id,
            "messages": session.get_history(100),
        }
