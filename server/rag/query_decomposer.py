"""
Query Decomposer — 将复杂查询拆成子查询，分别检索后合并。

触发条件：
    - query 含 "又/还/也/同时/兼顾/既能...又能/不仅可以...还"
    - query 长度 ≥ 10 字符

流程：
    复杂 query → LLM 拆分 → [子查询1, 子查询2, ...] → 各自检索 → 去重合并
"""
from typing import Optional


DECOMPOSE_PROMPT = """将以下用户购物需求拆成2-3个独立的搜索子句，每句一个核心需求。
只输出JSON数组，不要其他内容。

示例：
输入："适合跑步又适合日常通勤的鞋"
输出：["跑步鞋", "通勤鞋"]

输入："便宜又好用的蓝牙耳机"
输出：["性价比蓝牙耳机", "高评分蓝牙耳机"]

输入："{query}"
输出："""

# 触发分解的连接词
_DECOMPOSE_TRIGGERS = ["又", "还", "也", "同时", "兼顾", "既能", "不仅可以", "不但", "而且", "到", "从", "和", "与", "跟"]


class QueryDecomposer:
    """查询分解器"""

    def __init__(self, doubao_service=None):
        self._doubao = doubao_service
        self.enabled = True

    def set_service(self, doubao_service):
        self._doubao = doubao_service

    def should_decompose(self, query: str) -> bool:
        """判断是否应该触发分解"""
        if not self.enabled:
            return False
        clean = query.strip()
        if len(clean) < 10:
            return False
        return any(trigger in clean for trigger in _DECOMPOSE_TRIGGERS)

    async def decompose(self, query: str) -> list[str]:
        """
        将 query 拆成子查询列表。
        失败时返回原 query 的单元素列表。
        """
        if not self._doubao:
            return [query]

        try:
            prompt = DECOMPOSE_PROMPT.format(query=query)
            raw = await self._doubao.generate_response(prompt)
            import json
            # 尝试提取 JSON 数组
            start = raw.find("[")
            end = raw.rfind("]")
            if start >= 0 and end > start:
                sub_queries = json.loads(raw[start:end + 1])
                if isinstance(sub_queries, list) and len(sub_queries) >= 2:
                    # 过滤空串和过短子句
                    valid = [q.strip() for q in sub_queries if len(q.strip()) >= 2]
                    if len(valid) >= 2:
                        return valid
        except Exception as e:
            print(f"[query_decomposer] 分解失败: {e}")

        return [query]


# 全局单例
query_decomposer = QueryDecomposer()
