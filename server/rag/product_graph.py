"""
Product Graph — 轻量级商品关系图（内存 dict，无需 Neo4j）。

三层关系：
1. 同品牌：same_brand[brand] → [product_ids]
2. 同类目：same_category[category] → [product_ids]
3. 互补品：基于规则的搭配建议（如"跑步鞋"→"运动袜"）

用途：
- 检索 boost：匹配到某品牌商品后 boost 同品牌其他商品
- 搭配推荐：推荐商品后追加 1-2 个互补品
"""
from typing import Optional
from collections import defaultdict


# 互补品搭配规则（关键词 → 搭配品类 + 搜索 query）
_COMPLEMENT_RULES: dict[str, list[dict]] = {
    "跑鞋": [{"category": "服饰运动", "query": "运动袜", "reason": "搭配运动袜"}],
    "跑步鞋": [{"category": "服饰运动", "query": "运动袜", "reason": "搭配运动袜"}],
    "篮球鞋": [{"category": "服饰运动", "query": "运动袜", "reason": "搭配运动袜"}],
    "登山鞋": [{"category": "服饰运动", "query": "户外背包", "reason": "户外搭配"}],
    "手机": [{"category": "数码电子", "query": "手机壳", "reason": "手机配件"},
             {"category": "数码电子", "query": "充电器", "reason": "充电配件"}],
    "笔记本电脑": [{"category": "数码电子", "query": "鼠标", "reason": "电脑配件"}],
    "笔记本": [{"category": "数码电子", "query": "鼠标", "reason": "电脑配件"}],
    "平板": [{"category": "数码电子", "query": "平板保护壳", "reason": "平板配件"}],
    "防晒": [{"category": "美妆护肤", "query": "卸妆", "reason": "防晒需卸妆"}],
    "粉底": [{"category": "美妆护肤", "query": "散粉", "reason": "定妆搭配"}],
    "咖啡": [{"category": "食品饮料", "query": "牛奶", "reason": "咖啡伴侣"}],
}


class ProductGraph:
    """商品关系图"""

    def __init__(self):
        self.by_brand: dict[str, list[str]] = defaultdict(list)
        self.by_category: dict[str, list[str]] = defaultdict(list)
        self.by_sub_category: dict[str, list[str]] = defaultdict(list)
        self._product_map: dict[str, dict] = {}  # id → product_info
        self._built = False

    def build(self, products: list):
        """从商品列表构建关系图"""
        for p in products:
            pid = p.id if hasattr(p, 'id') else p.get('id', '')
            if not pid:
                continue
            brand = (p.brand if hasattr(p, 'brand') else p.get('brand', '')).lower()
            cat = p.category if hasattr(p, 'category') else p.get('category', '')
            sub = p.sub_category if hasattr(p, 'sub_category') else p.get('sub_category', '')
            title = p.title if hasattr(p, 'title') else p.get('title', '')

            self._product_map[pid] = {
                "id": pid, "title": title, "brand": brand,
                "category": cat, "sub_category": sub,
            }

            if brand:
                self.by_brand[brand].append(pid)
            if cat:
                self.by_category[cat].append(pid)
            if sub:
                self.by_sub_category[sub].append(pid)

        self._built = True
        print(f"[product_graph] 图构建完成: {len(self._product_map)} 节点, "
              f"{len(self.by_brand)} 品牌, {len(self.by_category)} 类目")

    def get_same_brand(self, product_id: str, exclude_self: bool = True) -> list[str]:
        """获取同品牌其他商品"""
        info = self._product_map.get(product_id, {})
        brand = info.get("brand", "")
        ids = self.by_brand.get(brand, [])
        if exclude_self:
            ids = [pid for pid in ids if pid != product_id]
        return ids[:5]

    def get_same_category(self, product_id: str, exclude_self: bool = True) -> list[str]:
        """获取同类目其他商品"""
        info = self._product_map.get(product_id, {})
        cat = info.get("category", "")
        ids = self.by_category.get(cat, [])
        if exclude_self:
            ids = [pid for pid in ids if pid != product_id]
        return ids[:10]

    def get_complements(self, product_id: str) -> list[dict]:
        """
        获取互补品推荐。
        返回 [{"query": str, "reason": str, "category": str}, ...]
        """
        info = self._product_map.get(product_id, {})
        title = (info.get("title") or "").lower()

        for keyword, comps in _COMPLEMENT_RULES.items():
            if keyword.lower() in title:
                return comps
        return []

    def _match_complement(self, product, query: str) -> bool:
        """
        校验补荐商品是否真的与补荐 query 相关。

        规则：商品标题至少包含 query 中的一个有效关键词（jieba 分词）。
        避免"搜运动袜返回篮球鞋"这种牛头不对马嘴的情况。
        """
        title = (getattr(product, 'title', '') or '').lower()
        if not title or not query:
            return False

        # 优先用 jieba 分词，提取 ≥2 字符的实义词
        try:
            import jieba
            keywords = [w for w in jieba.lcut(query) if len(w) >= 2]
        except Exception:
            keywords = []

        # 降级：至少 query 整体是标题子串，或取首尾 2-gram
        if not keywords:
            keywords = [query]
            if len(query) >= 2:
                keywords.append(query[:2])
            if len(query) >= 3:
                keywords.append(query[-2:])

        return any(kw in title for kw in keywords)

    def get_related_products(
        self,
        product_ids: list[str],
        retriever=None,
        limit: int = 2,
    ) -> list:
        """
        获取关联推荐商品。
        优先返回互补品，其次同品牌其他商品。

        Args:
            product_ids: 已推荐的商品 ID 列表
            retriever: ProductRetriever 实例（用于搜索互补品）
            limit: 最多返回几个关联推荐
        """
        if not self._built:
            return []

        results = []
        seen = set(product_ids)

        for pid in product_ids[:3]:  # 只对前 3 个推荐做关联
            # 1. 互补品
            comps = self.get_complements(pid)
            for comp in comps:
                if retriever and len(results) < limit:
                    comp_products = retriever.search(
                        comp["query"], top_k=3,  # 多取几个候选，方便过滤
                        category_filter=comp.get("category"),
                    )
                    for p in comp_products:
                        if p.id not in seen:
                            # 🔧 校验：补荐商品必须与补荐 query 关键词匹配
                            if not self._match_complement(p, comp["query"]):
                                continue
                            seen.add(p.id)
                            results.append({
                                "product": p,
                                "reason": comp.get("reason", "搭配推荐"),
                                "type": "complement",
                            })

        # 2. 如果互补品不够，补充同品牌推荐
        if len(results) < limit and product_ids:
            first_pid = product_ids[0]
            same_brand = self.get_same_brand(first_pid)
            for pid in same_brand:
                if pid not in seen and retriever:
                    p = retriever.get_product_by_id(pid)
                    if p and len(results) < limit:
                        seen.add(pid)
                        results.append({
                            "product": p,
                            "reason": "同品牌推荐",
                            "type": "same_brand",
                        })

        return results[:limit]


# 全局单例
product_graph = ProductGraph()
