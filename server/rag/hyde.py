"""
基于 HyDE 技术的假设文档生成器。

核心原理：
    当用户查询较短（如"推荐耳机"）时，直接向量化的语义信息有限。
    通过让语言模型生成一份"理想商品描述"，再用这个描述进行向量检索，
    可以显著提升召回效果，因为假设文档与真实商品处于同一语义空间。

激活条件：
    - 查询长度不超过 20 个字符
    - 排除纯品牌名称的精确匹配场景

技术来源：Precise Zero-Shot Dense Retrieval without Relevance Labels (Gao et al., 2022)
"""
from typing import Optional


HYDE_PROMPT = """用户想找："{query}"

请想象一款最符合用户需求的理想商品，用一段话（50字以内）描述它的核心特点。
用中文描述，像电商商品标题一样精炼。

理想商品描述："""


class HyDEGenerator:
    """HyDE 假设文档生成器"""

    def __init__(self, doubao_service=None):
        self._doubao = doubao_service

    def set_service(self, doubao_service):
        """注入 doubao 服务"""
        self._doubao = doubao_service

    def should_use_hyde(self, query: str) -> bool:
        """判断是否应该触发 HyDE"""
        clean = query.strip()
        if len(clean) > 20:
            return False
        # 纯品牌名不触发
        if clean in {"耐克", "阿迪达斯", "阿迪", "李宁", "安踏", "华为", "苹果", "小米",
                      "兰蔻", "雅诗兰黛", "科颜氏", "雀巢", "康师傅", "统一"}:
            return False
        return True

    async def generate(self, query: str) -> Optional[str]:
        """生成假设文档，失败返回 None"""
        if not self._doubao:
            return None
        try:
            prompt = HYDE_PROMPT.format(query=query)
            result = await self._doubao.generate_response(prompt)
            # 清理输出
            result = result.strip().strip('"').strip('"')
            if len(result) < 5:
                return None
            return result
        except Exception as e:
            print(f"[hyde] 生成失败: {e}")
            return None


# 全局单例
hyde_generator = HyDEGenerator()
