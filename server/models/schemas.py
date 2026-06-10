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
            "product_url": f"{host}/product/{self.id}"
        }

class MessageResponse(BaseModel):
    response: str
    products: List[Product]
    session_id: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    image_base64: Optional[str] = None