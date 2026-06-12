"""
数据模型定义 — Pydantic  schemas for request/response validation.

核心模型：
    - Sku：商品规格属性（颜色、尺码等）
    - FaqItem：官方问答对
    - UserReview：用户评价
    - RagKnowledge：RAG 知识库（营销描述、FAQ、用户评价）
    - Product：完整商品结构（ID、标题、品牌、类目、价格、图片、SKU、知识库）
    - ChatRequest / MessageResponse：对话接口请求和响应格式
"""
import os
from pydantic import BaseModel
from typing import List, Optional, Dict

class Sku(BaseModel):
    sku_id: str
    properties: Dict[str, str]
    price: float

class FaqItem(BaseModel):
    question: str
    answer: str

class UserReview(BaseModel):
    nickname: str
    rating: int
    content: str

class RagKnowledge(BaseModel):
    marketing_description: str
    official_faq: List[FaqItem]
    user_reviews: List[UserReview]

class Product(BaseModel):
    id: str
    title: str
    brand: str
    category: str
    sub_category: str
    base_price: float
    image_path: str
    skus: List[Sku]
    rag_knowledge: RagKnowledge
    
    def to_dict(self, base_url: Optional[str] = None) -> Dict[str, any]:
        reviews = self.rag_knowledge.user_reviews or []
        rating = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 4.5
        review_count = len(reviews) if reviews else 1000
        host = (base_url or os.getenv("SERVER_BASE_URL") or "http://localhost:8080").rstrip("/")

        return {
            "id": self.id,
            "name": self.title,
            "brand": self.brand,
            "category": self.category,
            "price": self.base_price,
            "image_url": f"{host}/static/{self.image_path}" if self.image_path else "",
            "rating": rating,
            "review_count": review_count,
            "description": self.rag_knowledge.marketing_description,
            "product_url": f"{host}/product/{self.id}",
            "reviews": [
                {"nickname": r.nickname, "rating": r.rating, "content": r.content}
                for r in reviews
            ],
            "faq": [
                {"question": f.question, "answer": f.answer}
                for f in (self.rag_knowledge.official_faq or [])
            ],
            "skus": [
                {"sku_id": s.sku_id, "properties": s.properties, "price": s.price}
                for s in self.skus
            ],
        }

class MessageResponse(BaseModel):
    response: str
    products: List[Product]
    session_id: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    image_base64: Optional[str] = None