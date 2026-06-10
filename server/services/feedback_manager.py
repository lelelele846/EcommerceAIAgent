import time
import json
from typing import List, Dict, Optional

class Feedback:
    """用户反馈类"""
    def __init__(self, 
                 feedback_id: str,
                 session_id: str,
                 product_id: str,
                 rating: int,  # 1-5星
                 comment: str = "",
                 helpful: bool = None,  # 是否有帮助
                 improvement: str = ""):
        self.feedback_id = feedback_id
        self.session_id = session_id
        self.product_id = product_id
        self.rating = rating
        self.comment = comment
        self.helpful = helpful
        self.improvement = improvement
        self.created_at = time.time()
    
    def dict(self):
        return {
            "feedback_id": self.feedback_id,
            "session_id": self.session_id,
            "product_id": self.product_id,
            "rating": self.rating,
            "comment": self.comment,
            "helpful": self.helpful,
            "improvement": self.improvement,
            "created_at": self.created_at
        }

class FeedbackManager:
    """反馈管理器"""
    def __init__(self):
        self.feedbacks: Dict[str, Feedback] = {}
    
    def add_feedback(self, 
                     session_id: str,
                     product_id: str,
                     rating: int,
                     comment: str = "",
                     helpful: bool = None,
                     improvement: str = "") -> Feedback:
        """添加反馈"""
        feedback_id = f"fb_{int(time.time())}_{len(self.feedbacks)}"
        feedback = Feedback(
            feedback_id=feedback_id,
            session_id=session_id,
            product_id=product_id,
            rating=rating,
            comment=comment,
            helpful=helpful,
            improvement=improvement
        )
        self.feedbacks[feedback_id] = feedback
        return feedback
    
    def get_feedback_by_id(self, feedback_id: str) -> Optional[Feedback]:
        """根据ID获取反馈"""
        return self.feedbacks.get(feedback_id)
    
    def get_feedbacks_by_session(self, session_id: str) -> List[Feedback]:
        """获取会话的所有反馈"""
        return [f for f in self.feedbacks.values() if f.session_id == session_id]
    
    def get_feedbacks_by_product(self, product_id: str) -> List[Feedback]:
        """获取商品的所有反馈"""
        return [f for f in self.feedbacks.values() if f.product_id == product_id]
    
    def get_product_rating(self, product_id: str) -> Dict:
        """获取商品的评分统计"""
        product_feedbacks = self.get_feedbacks_by_product(product_id)
        if not product_feedbacks:
            return {"average_rating": 0, "count": 0}
        
        total_rating = sum(f.rating for f in product_feedbacks)
        average_rating = total_rating / len(product_feedbacks)
        
        return {
            "average_rating": round(average_rating, 2),
            "count": len(product_feedbacks),
            "distribution": {
                "1_star": sum(1 for f in product_feedbacks if f.rating == 1),
                "2_star": sum(1 for f in product_feedbacks if f.rating == 2),
                "3_star": sum(1 for f in product_feedbacks if f.rating == 3),
                "4_star": sum(1 for f in product_feedbacks if f.rating == 4),
                "5_star": sum(1 for f in product_feedbacks if f.rating == 5)
            }
        }
    
    def get_overall_stats(self) -> Dict:
        """获取整体反馈统计"""
        all_feedbacks = list(self.feedbacks.values())
        if not all_feedbacks:
            return {"total_count": 0, "average_rating": 0}
        
        total_rating = sum(f.rating for f in all_feedbacks)
        average_rating = total_rating / len(all_feedbacks)
        
        helpful_count = sum(1 for f in all_feedbacks if f.helpful)
        
        return {
            "total_count": len(all_feedbacks),
            "average_rating": round(average_rating, 2),
            "helpful_count": helpful_count,
            "helpful_rate": round(helpful_count / len(all_feedbacks) * 100, 2) if all_feedbacks else 0
        }