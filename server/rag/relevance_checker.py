"""
Relevance Checker — Self-RAG 风格的相关性校验。

检索后对候选商品做轻量级相关性判断：
- 相关 → 保留
- 不相关 → 过滤
- 全部不相关 → 触发重搜（放宽条件）

使用 doubao 快速判断（max_tokens=10，~300ms/批）。
"""
from typing import Optional


RELEVANCE_PROMPT = """用户需求："{query}"
候选商品列表：
{products_text}

对每个商品，判断是否真正满足用户需求。只输出JSON数组：
[{{"id": "商品ID", "relevant": true/false, "reason": "1句话原因"}}, ...]

判断标准：
- 类目匹配：商品类目与用户需要的一致或相近即为relevant
- 功能匹配：商品功能满足用户描述的需求
- 价格匹配：如果在用户预算范围内则 relevant=true
- **宽松判断：只要存在合理关联就算 relevant，不要过于严格**
- **即使全部都不完全符合，也至少选3个最接近的标记为 relevant=true**"""


class RelevanceChecker:
    """检索相关性校验器"""

    def __init__(self, doubao_service=None):
        self._doubao = doubao_service

    def set_service(self, doubao_service):
        self._doubao = doubao_service

    async def check(
        self,
        query: str,
        products: list,
        min_keep: int = 3,
    ) -> tuple[list, list]:
        """
        校验商品相关性，返回 (relevant_products, irrelevant_products)。

        如果 relevant < min_keep，返回全部（不强行过滤到太少）。
        """
        if not products or not self._doubao:
            return products, []

        # 构建候选文本
        lines = []
        for p in products:
            title = getattr(p, 'title', '')
            brand = getattr(p, 'brand', '')
            cat = getattr(p, 'category', '')
            price = getattr(p, 'base_price', 0)
            lines.append(f"ID:{p.id} 《{title}》 品牌:{brand} 类目:{cat} 价格:¥{price:.0f}")

        prompt = RELEVANCE_PROMPT.format(
            query=query,
            products_text="\n".join(lines),
        )

        try:
            raw = await self._doubao.generate_response(prompt)
            import json
            import re as _re

            # 提取 JSON
            match = _re.search(r'\[.*\]', raw, _re.DOTALL)
            if not match:
                return products, []

            judgments = json.loads(match.group())
            relevant_ids = {
                j["id"] for j in judgments
                if j.get("relevant", True)
            }

            relevant = [p for p in products if p.id in relevant_ids]
            irrelevant = [p for p in products if p.id not in relevant_ids]

            # 保底：不要过滤到太少
            if len(relevant) < min_keep:
                print(f"[relevance_checker] 保留 {len(relevant)} < {min_keep}，恢复全部 {len(products)} 个")
                return products, []

            if irrelevant:
                print(f"[relevance_checker] 过滤掉 {len(irrelevant)} 个不相关商品，保留 {len(relevant)} 个")

            return relevant, irrelevant

        except Exception as e:
            print(f"[relevance_checker] 校验失败: {e}")
            return products, []


# 全局单例
relevance_checker = RelevanceChecker()
