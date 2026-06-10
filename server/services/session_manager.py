import json
import time
import threading
from typing import List, Dict, Optional
from datetime import datetime

class ChatMessage:
    """聊天消息类"""
    def __init__(self, role: str, content: str, timestamp: float = None):
        self.role = role  # "user" or "assistant"
        self.content = content
        self.timestamp = timestamp or time.time()
    
    def dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }

class UserPreferences:
    """用户偏好类（优化版）- 支持长程关系维护"""
    def __init__(self):
        # 【通用属性】
        self.category = None  # 当前浏览类目（美妆护肤/数码电子/服饰运动/食品生活等）
        self.price_range = (0, float('inf'))  # 价格范围（元）
        self.preferred_brands = []  # 偏好品牌列表
        self.disliked_brands = []  # 不喜欢的品牌列表
        self.favorite_products = []  # 收藏的商品ID列表
        self.disliked_products = []  # 不喜欢的商品ID列表
        
        # 【美妆护肤专属】
        self.skin_type = None  # 肤质（干性/油性/混合性/敏感性/中性）
        self.skin_concerns = []  # 肌肤问题（控油/保湿/美白/抗老/祛痘/敏感修护）
        self.product_type = None  # 产品类型（面霜/精华/洁面/面膜/防晒/彩妆）
        
        # 【数码电子专属】
        self.device_type = None  # 设备类型（手机/平板/耳机/笔记本/智能穿戴）
        self.brand_priority = None  # 品牌倾向（国产/国际/性价比/高端）
        self.key_features = []  # 核心功能需求（续航/拍照/性能/轻薄/屏幕）
        
        # 【服饰运动专属】
        self.size = None  # 尺码（S/M/L/XL/XXL/定制）
        self.style = None  # 风格（休闲/运动/商务/时尚/复古）
        self.colors = []  # 偏好颜色列表
        self.materials = []  # 偏好材质（棉/涤纶/羊毛/透气/防水）
        self.sport_type = None  # 运动类型（跑步/健身/篮球/户外/瑜伽）
        
        # 【食品生活专属】
        self.flavor_preference = None  # 口味偏好（甜/咸/酸/辣/清淡）
        self.dietary_restrictions = []  # 饮食禁忌（无糖/低脂/素食/无乳糖/过敏成分）
        self.consumption_scenario = None  # 食用场景（零食/早餐/正餐/下午茶/送礼）
        self.health_goals = []  # 健康需求（低卡/高蛋白/膳食纤维/益生菌）
        
        # 【长程关系维护】- 跨会话记忆
        self.user_name = None  # 用户昵称
        self.important_dates = {}  # 重要日期 {"生日": "1995-06-15", "纪念日": "2020-01-01"}
        self.lifestyle_notes = []  # 生活习惯备注 ["经常加班", "喜欢早起跑步", "过敏体质"]
        self.past_purchases = []  # 历史购买记录
        self.appearance_notes = {}  # 外貌特征备注 {"肤色": "偏白", "体型": "匀称", "身高": "165cm"}
        self.relationship_goals = {}  # 关系目标 {"护肤": "变白", "穿搭": "显瘦", "健康": "减重5斤"}
        self.last_interaction = None  # 上次互动时间
        self.interaction_count = 0  # 总互动次数
        
        # 【时空连续性关怀】- 记住用户生活中的事件
        self.recent_life_events = []  # 最近生活事件 [{"event": "去三亚旅游", "timestamp": "...", "related_need": "晒后修复"}]
        self.recurring_themes = []  # 反复出现的话题 ["减肥", "找工作", "恋爱"]
        self.shared_secrets = []  # 用户分享的小秘密（增强亲密感）
    
    def dict(self):
        return {
            # 通用属性
            "category": self.category,
            "price_range": self.price_range,
            "preferred_brands": self.preferred_brands,
            "disliked_brands": self.disliked_brands,
            "favorite_products": self.favorite_products,
            "disliked_products": self.disliked_products,
            # 美妆护肤
            "skin_type": self.skin_type,
            "skin_concerns": self.skin_concerns,
            "product_type": self.product_type,
            # 数码电子
            "device_type": self.device_type,
            "brand_priority": self.brand_priority,
            "key_features": self.key_features,
            # 服饰运动
            "size": self.size,
            "style": self.style,
            "colors": self.colors,
            "materials": self.materials,
            "sport_type": self.sport_type,
            # 食品生活
            "flavor_preference": self.flavor_preference,
            "dietary_restrictions": self.dietary_restrictions,
            "consumption_scenario": self.consumption_scenario,
            "health_goals": self.health_goals,
            # 长程关系维护
            "user_name": self.user_name,
            "important_dates": self.important_dates,
            "lifestyle_notes": self.lifestyle_notes,
            "past_purchases": self.past_purchases,
            "appearance_notes": self.appearance_notes,
            "relationship_goals": self.relationship_goals,
            "last_interaction": self.last_interaction,
            "interaction_count": self.interaction_count,
            # 时空连续性
            "recent_life_events": self.recent_life_events,
            "recurring_themes": self.recurring_themes,
            "shared_secrets": self.shared_secrets
        }

class Session:
    """会话类（扩展版）"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.last_updated_at = time.time()
        self.messages: List[ChatMessage] = []
        self.preferences = UserPreferences()
        self.interaction_count = 0  # 交互次数
        # 新增意图链追踪
        self.intent_chain: List[Dict] = []  # 意图演变链
        self.current_intent = None  # 当前意图
        # 新增会话摘要（用于节省Token）
        self.summary = ""  # 会话摘要
        self.last_summary_time = 0  # 上次生成摘要的时间
        # 🆕 上下文记忆：跟踪最近展示的商品列表
        self.last_shown_products: List[Dict] = []  # [{"product_id": "...", "title": "..."}, ...]
        # 🆕 搜索状态持久化（换一批/不满意时用）
        self.search_state: Dict = {}  # {"category": "...", "price_range": ..., "preferred_brands": [...], ...}
        # 场景上下文
        self.scene_context: Optional[Dict] = None
        # 状态机当前状态
        self.agent_state: str = "browsing"
    
    def add_message(self, role: str, content: str):
        """添加消息"""
        self.messages.append(ChatMessage(role, content))
        self.last_updated_at = time.time()
        self.interaction_count += 1
    
    def add_intent(self, intent_type: str, intent_data: Dict = None):
        """添加意图到意图链"""
        intent_entry = {
            "type": intent_type,
            "data": intent_data or {},
            "timestamp": time.time(),
            "interaction_count": self.interaction_count
        }
        self.intent_chain.append(intent_entry)
        self.current_intent = intent_type
        # 保持最近10个意图
        if len(self.intent_chain) > 10:
            self.intent_chain = self.intent_chain[-10:]
        self.last_updated_at = time.time()
    
    def get_history(self, limit: int = 10) -> List[Dict]:
        """获取对话历史"""
        return [msg.dict() for msg in self.messages[-limit:]]
    
    def get_intent_chain(self, limit: int = 5) -> List[Dict]:
        """获取意图链"""
        return self.intent_chain[-limit:]
    
    def update_preferences(self, **kwargs):
        """更新用户偏好"""
        for key, value in kwargs.items():
            if hasattr(self.preferences, key):
                setattr(self.preferences, key, value)
        self.last_updated_at = time.time()
    
    def is_expired(self, timeout_hours: int = 24) -> bool:
        """检查会话是否过期"""
        return (time.time() - self.last_updated_at) > (timeout_hours * 3600)
    
    def set_summary(self, summary: str):
        """设置会话摘要"""
        self.summary = summary
        self.last_summary_time = time.time()
        self.last_updated_at = time.time()
    
    def get_summary(self) -> str:
        """获取会话摘要"""
        return self.summary
    
    def dict(self):
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "interaction_count": self.interaction_count,
            "preferences": self.preferences.dict(),
            "messages": self.get_history(),
            "intent_chain": self.intent_chain,
            "current_intent": self.current_intent,
            "summary": self.summary,
            "agent_state": self.agent_state,
            "last_shown_products": self.last_shown_products,
            "search_state": self.search_state,
            "scene_context": self.scene_context,
        }

class SessionManager:
    """会话管理器（线程安全）"""
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()  # 线程锁
    
    def create_session(self, session_id: str) -> Session:
        """创建会话"""
        with self._lock:
            if session_id in self.sessions:
                return self.sessions[session_id]
            
            session = Session(session_id)
            self.sessions[session_id] = session
            return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话（🆕 内存 miss 时尝试从 DB 恢复）"""
        with self._lock:
            session = self.sessions.get(session_id)
            if session and session.is_expired():
                del self.sessions[session_id]
                return None
            if session:
                return session

        # 🆕 内存里没有 → 尝试从 DB 恢复（服务重启后）
        return None  # 同步方法不能调 async DB，由调用方处理

    async def get_or_restore_session(self, session_id: str) -> Optional[Session]:
        """获取会话，内存 miss 时从 DB 恢复（异步版本）"""
        with self._lock:
            session = self.sessions.get(session_id)
            if session and not session.is_expired():
                return session
            if session and session.is_expired():
                del self.sessions[session_id]

        # 🆕 从 DB 恢复
        try:
            from db import relational as _db
            db_session = await _db.get_session(session_id)
            if db_session:
                session = Session(session_id)
                session.agent_state = db_session.get("agent_state", "browsing")
                session.last_shown_products = db_session.get("last_shown_products", [])
                session.search_state = db_session.get("search_state", {})
                session.scene_context = db_session.get("scene_context")
                session.interaction_count = db_session.get("interaction_count", 0)
                # 恢复偏好
                prefs = db_session.get("preferences", {})
                if prefs:
                    session.update_preferences(**prefs)
                # 恢复消息
                messages = await _db.get_recent_messages(session_id, limit=50)
                for msg in messages:
                    session.messages.append(ChatMessage(
                        role=msg["role"],
                        content=msg["content"],
                        timestamp=msg.get("created_at", time.time()),
                    ))
                with self._lock:
                    self.sessions[session_id] = session
                print(f"[session] 从 DB 恢复会话 {session_id}，{len(messages)} 条消息")
                return session
        except Exception as e:
            print(f"[session] DB 恢复失败: {e}")
        return None
    
    def update_session(self, session_id: str, role: str, content: str):
        """更新会话（添加消息）"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                session = Session(session_id)
                self.sessions[session_id] = session
            session.add_message(role, content)
    
    def update_preferences(self, session_id: str, **kwargs):
        """更新用户偏好"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                session = Session(session_id)
                self.sessions[session_id] = session
            session.update_preferences(**kwargs)
    
    def add_intent(self, session_id: str, intent_type: str, intent_data: Dict = None):
        """添加意图到意图链"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                session = Session(session_id)
                self.sessions[session_id] = session
            session.add_intent(intent_type, intent_data)
    
    def set_session_summary(self, session_id: str, summary: str):
        """设置会话摘要"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                session = Session(session_id)
                self.sessions[session_id] = session
            session.set_summary(summary)
    
    def get_session_summary(self, session_id: str) -> Optional[Dict]:
        """获取会话摘要"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session or session.is_expired():
                if session:
                    del self.sessions[session_id]
                return None
            return session.dict()
    
    def get_active_sessions_count(self) -> int:
        """获取活跃会话数"""
        with self._lock:
            return len(self.sessions)
    
    def cleanup_expired_sessions(self):
        """清理过期会话"""
        with self._lock:
            expired_ids = [sid for sid, session in self.sessions.items() if session.is_expired()]
            for sid in expired_ids:
                del self.sessions[sid]
            return len(expired_ids)
