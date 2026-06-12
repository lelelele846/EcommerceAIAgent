"""
商品数据 API — 提供商品列表和详情查询。

核心功能：
    - 获取所有商品列表
    - 获取单个商品详情

设计说明：
    - 作为客户端直接访问商品数据的入口
    - 商品搜索和推荐走 chat 接口（带 RAG 能力）
    - 此接口主要用于商品浏览和详情展示
"""
from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api", tags=["products"])

# 全局服务实例
_retriever = None


def set_retriever(retriever):
    """设置全局检索器实例"""
    global _retriever
    _retriever = retriever


@router.get("/products")
async def get_products():
    """获取所有商品"""
    return _retriever.get_all_products()


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    """获取单个商品详情"""
    product = _retriever.get_product_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
