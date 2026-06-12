"""
用户反馈 API — 收集和管理用户对商品的评价反馈。

核心功能：
    - 添加反馈（评分、评论、改进建议）
    - 查询反馈详情
    - 获取商品的所有反馈
    - 获取商品评分统计
    - 获取会话相关反馈
    - 获取整体统计信息

反馈数据用于：
    - 商品推荐质量评估
    - 检索模型调优
    - 用户满意度分析
"""
from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/feedback", tags=["feedback"])

# 全局服务实例
_feedback_manager = None


def set_feedback_manager(feedback_manager):
    """设置全局反馈管理器实例"""
    global _feedback_manager
    _feedback_manager = feedback_manager


@router.post("")
async def add_feedback(feedback_data: dict):
    """添加用户反馈"""
    session_id = feedback_data.get("session_id")
    product_id = feedback_data.get("product_id")
    rating = feedback_data.get("rating")
    
    if not session_id or not product_id or rating is None:
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    if not (1 <= rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    
    feedback = _feedback_manager.add_feedback(
        session_id=session_id,
        product_id=product_id,
        rating=rating,
        comment=feedback_data.get("comment", ""),
        helpful=feedback_data.get("helpful"),
        improvement=feedback_data.get("improvement", "")
    )
    
    return {"message": "Feedback added successfully", "feedback_id": feedback.feedback_id}


@router.get("/{feedback_id}")
async def get_feedback(feedback_id: str):
    """获取反馈详情"""
    feedback = _feedback_manager.get_feedback_by_id(feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback.dict()


@router.get("/product/{product_id}")
async def get_product_feedbacks(product_id: str):
    """获取商品的所有反馈"""
    feedbacks = _feedback_manager.get_feedbacks_by_product(product_id)
    return {"product_id": product_id, "feedbacks": [f.dict() for f in feedbacks]}


@router.get("/product/{product_id}/rating")
async def get_product_rating(product_id: str):
    """获取商品评分统计"""
    stats = _feedback_manager.get_product_rating(product_id)
    return {"product_id": product_id, **stats}


@router.get("/session/{session_id}")
async def get_session_feedbacks(session_id: str):
    """获取会话的所有反馈"""
    feedbacks = _feedback_manager.get_feedbacks_by_session(session_id)
    return {"session_id": session_id, "feedbacks": [f.dict() for f in feedbacks]}


@router.get("/stats")
async def get_feedback_stats():
    """获取反馈统计信息"""
    return _feedback_manager.get_overall_stats()
