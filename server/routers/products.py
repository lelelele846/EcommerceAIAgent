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
