"""
结构化属性匹配器，作为混合检索的第三路召回源。

与向量检索和 BM25 检索形成互补：
    - 品牌精确匹配：如"耐克"直接匹配品牌字段
    - 价格范围匹配：如"200以内"应用价格过滤
    - 类目关键词匹配：如"跑步鞋"匹配子类目和标题

输出格式与 ChromaDB、BM25 保持一致，便于后续 RRF 融合：
    [{id, document, metadata, score}, ...]
"""
import re
from typing import Any, Optional

from utils.product_repo import product_repo


class AttributeMatcher:
    """结构化属性匹配器 — 基于品牌/类目/价格做精确匹配打分"""

    def search(
        self,
        query: str,
        top_k: int = 20,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        对所有商品做属性匹配打分，返回 chunk 格式的结果列表。

        打分规则（各项累加，max=1.0）：
        - 品牌精确匹配：+0.4
        - 类目关键词匹配：+0.3
        - 子类目关键词匹配：+0.2
        - 标题关键词匹配：+0.1
        """
        products = product_repo.all()
        if not products:
            return []

        results = []
        for p in products:
            score = 0.0
            title_lower = p.title.lower()
            query_lower = query.lower()
            brand_lower = p.brand.lower()
            cat_lower = p.category.lower()
            sub_lower = (p.sub_category or "").lower()
            desc = ""
            if hasattr(p, 'rag_knowledge') and p.rag_knowledge:
                desc = (p.rag_knowledge.marketing_description or "").lower()

            # 品牌精确匹配
            if brand_lower and brand_lower in query_lower:
                score += 0.4

            # 查询词在品牌名中
            query_tokens = set(query_lower.split())
            brand_tokens = set(brand_lower.split())
            if query_tokens & brand_tokens:
                score += 0.3

            # 类目匹配
            if cat_lower:
                cat_keywords = {
                    "美妆护肤": ["美妆", "护肤", "化妆品", "护肤品", "洗面奶", "面膜", "精华", "防晒", "口红", "粉底"],
                    "数码电子": ["数码", "电子", "手机", "电脑", "耳机", "平板", "笔记本"],
                    "服饰运动": ["服饰", "运动", "鞋", "衣服", "裤", "跑步", "健身", "户外", "T恤", "卫衣"],
                    "食品饮料": ["食品", "饮料", "零食", "咖啡", "茶", "牛奶", "方便面", "坚果"],
                    "家居生活": ["家居", "生活", "收纳", "清洁", "装饰"],
                  
                }
                for keyword in cat_keywords.get(p.category, []):
                    if keyword in query_lower:
                        score += 0.2
                        break

            # 子类目匹配
            if sub_lower:
                sub_words = set(sub_lower.split())
                if sub_words & query_tokens:
                    score += 0.2

            # 标题关键词匹配
            title_words = set(title_lower.split())
            match_ratio = len(query_tokens & title_words) / max(len(query_tokens), 1)
            score += min(match_ratio * 0.2, 0.2)

            # 描述关键词匹配（加分项）
            if desc:
                desc_match_count = sum(1 for t in query_tokens if t in desc)
                score += min(desc_match_count * 0.05, 0.15)

            # where 过滤
            if where and not _matches_where_simple(p, where):
                continue

            if score > 0:
                # 构造与 ChromaDB 查询一致的 chunk 格式
                # 用 title chunk (c0) 作为代表
                title_doc = f"商品名称: {p.title}\n品牌: {p.brand}\n类目: {p.category}"
                results.append({
                    "id": f"{p.id}_c0",
                    "document": title_doc,
                    "metadata": {
                        "product_id": p.id,
                        "title": p.title,
                        "brand": p.brand,
                        "category": p.category,
                        "sub_category": p.sub_category,
                        "base_price": p.base_price,
                        "chunk_type": "title_block",
                    },
                    "score": min(score, 1.0),
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]


def _matches_where_simple(product, where: dict) -> bool:
    """简化的 where 过滤，与 BM25Retriever._matches_where 逻辑一致"""
    if not where:
        return True
    if "$and" in where:
        return all(_matches_where_simple(product, cond) for cond in where["$and"])
    if "$or" in where:
        return any(_matches_where_simple(product, cond) for cond in where["$or"])

    for key, condition in where.items():
        if key.startswith("$"):
            continue
        val = getattr(product, key, None)
        if isinstance(condition, dict):
            for op, threshold in condition.items():
                if val is None:
                    return False
                if op == "$lt" and not (val < threshold):
                    return False
                if op == "$lte" and not (val <= threshold):
                    return False
                if op == "$gt" and not (val > threshold):
                    return False
                if op == "$gte" and not (val >= threshold):
                    return False
                if op == "$ne" and val == threshold:
                    return False
        else:
            if val != condition:
                return False
    return True
