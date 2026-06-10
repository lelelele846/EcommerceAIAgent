"""会话摘要生成服务"""
from typing import List, Dict

class SummaryGenerator:
    """会话摘要生成器"""
    
    def __init__(self, ai_service):
        self.ai_service = ai_service
    
    async def generate_summary(self, history: List[Dict], preferences: Dict) -> str:
        """
        生成会话摘要
        
        Args:
            history: 对话历史列表，每个元素包含 'role' 和 'content'
            preferences: 用户偏好字典
        
        Returns:
            会话摘要字符串
        """
        # 构建历史文本
        history_text = ""
        for msg in history[-5:]:  # 最多取最近5轮
            role = "用户" if msg.get('role') == 'user' else "AI"
            content = msg.get('content', '')[:100]
            history_text += f"{role}: {content}\n"
        
        # 构建偏好文本
        pref_text = ""
        if preferences.get('category'):
            pref_text += f"类目: {preferences['category']}\n"
        if preferences.get('flavor_preference'):
            pref_text += f"口味: {preferences['flavor_preference']}\n"
        if preferences.get('skin_type'):
            pref_text += f"肤质: {preferences['skin_type']}\n"
        if preferences.get('price_range'):
            price_range = preferences['price_range']
            if price_range != (0, float('inf')):
                pref_text += f"预算: ¥{price_range[0]}-¥{price_range[1]}\n"
        
        prompt = f"""请为以下对话生成一句简短的摘要，用于后续对话的上下文记忆。

【对话历史】
{history_text}

【用户偏好】
{pref_text}

【输出要求】
1. 用一句话总结，不超过50字
2. 格式：用户询问了X，AI推荐了Y，用户表示Z
3. 只保留关键信息，不要详细描述

【示例】
用户询问了零食推荐，AI推荐了坚果，用户表示想要咸口。
"""
        
        try:
            response = await self.ai_service.generate_response(prompt)
            summary = response.strip()
            # 确保摘要不超过50字
            if len(summary) > 50:
                summary = summary[:47] + "..."
            return summary
        except Exception as e:
            print(f"生成摘要失败: {e}")
            return self._generate_fallback_summary(history, preferences)
    
    def _generate_fallback_summary(self, history: List[Dict], preferences: Dict) -> str:
        """
        当AI服务不可用时，使用规则生成摘要
        """
        user_queries = [msg.get('content', '') for msg in history if msg.get('role') == 'user']
        ai_replies = [msg.get('content', '') for msg in history if msg.get('role') == 'assistant']
        
        user_query = user_queries[-1] if user_queries else ""
        ai_reply = ai_replies[-1] if ai_replies else ""
        
        summary_parts = []
        
        # 用户询问内容
        if user_query:
            summary_parts.append(f"用户询问了{user_query[:10]}")
        
        # AI回复内容
        if ai_reply:
            summary_parts.append(f"AI推荐了商品")
        
        # 用户偏好
        if preferences.get('flavor_preference'):
            summary_parts.append(f"用户偏好{preferences['flavor_preference']}")
        elif preferences.get('skin_type'):
            summary_parts.append(f"用户是{preferences['skin_type']}肤质")
        
        summary = "，".join(summary_parts)
        if len(summary) > 50:
            summary = summary[:47] + "..."
        
        return summary
