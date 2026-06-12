"""
商品仓储层 — 统一管理商品数据的加载、索引和查询。

设计原则：
    所有商品查询必须通过 ProductRepo，不直接访问 retriever.products。
    这样设计的好处：
        - 统一索引：按 ID、类目、品牌多维度索引
        - 缓存友好：内存加载，避免重复解析
        - 解耦数据源：更换数据源时只需修改 load() 方法

索引结构：
    - _products：商品列表
    - _by_id：ID → Product 映射
    - _by_category：类目 → 商品列表
    - _by_brand：品牌 → 商品列表
    - _all_brands/_all_categories：全局品牌/类目集合
"""
import glob
import json
import os
from typing import Optional
from models.schemas import Product


class ProductRepo:
    """商品仓库：加载、索引、查询"""

    def __init__(self):
        self._products: list[Product] = []
        self._by_id: dict[str, Product] = {}
        self._by_category: dict[str, list[Product]] = {}
        self._by_brand: dict[str, list[Product]] = {}
        self._all_brands: set[str] = set()
        self._all_categories: set[str] = set()
        self._all_sub_categories: set[str] = set()
        self._loaded = False


    def load(self, dataset_path: str = "./data/ecommerce_agent_dataset"):
        """从数据集目录加载所有商品 JSON"""
        if self._loaded:
            return

        if not os.path.exists(dataset_path):
            print(f"[product_repo] 数据集路径不存在: {dataset_path}")
            return

        json_files = glob.glob(os.path.join(dataset_path, "*", "data", "*.json"))
        print(f"[product_repo] 发现 {len(json_files)} 个商品文件")

        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                product = self._parse_product(data)
                self._index(product)
            except Exception as e:
                print(f"[product_repo] 加载失败 {jf}: {e}")

        self._loaded = True
        print(f"[product_repo] 加载完成: {len(self._products)} 个商品, "
              f"{len(self._all_brands)} 个品牌, {len(self._all_categories)} 个类目")

    def _parse_product(self, data: dict) -> Product:
        return Product(
            id=data["product_id"],
            title=data["title"],
            brand=data["brand"],
            category=data["category"],
            sub_category=data.get("sub_category", ""),
            base_price=data["base_price"],
            image_path=data["image_path"],
            skus=data.get("skus", []),
            rag_knowledge=data.get("rag_knowledge", {
                "marketing_description": "",
                "official_faq": [],
                "user_reviews": [],
            }),
        )

    def _index(self, product: Product):
        self._products.append(product)
        self._by_id[product.id] = product
        self._all_brands.add(product.brand)
        self._all_categories.add(product.category)
        if product.sub_category:
            self._all_sub_categories.add(product.sub_category)
        self._by_category.setdefault(product.category, []).append(product)
        self._by_brand.setdefault(product.brand, []).append(product)


    def all(self) -> list[Product]:
        return self._products

    def get(self, product_id: str) -> Optional[Product]:
        return self._by_id.get(product_id)

    def by_category(self, category: str) -> list[Product]:
        return self._by_category.get(category, [])

    def by_brand(self, brand: str) -> list[Product]:
        return self._by_brand.get(brand, [])

    def brands(self) -> list[str]:
        return sorted(self._all_brands)

    def categories(self) -> list[str]:
        return sorted(self._all_categories)

    def sub_categories(self) -> list[str]:
        return sorted(self._all_sub_categories)

    def search_by_name(self, name: str, limit: int = 5) -> list[Product]:
        """按名称/品牌模糊搜索"""
        name_lower = name.lower()
        scored = []
        for p in self._products:
            score = 0
            if name_lower in p.title.lower():
                score += 10
            if name_lower in p.brand.lower():
                score += 8
            # bigram 加分
            for i in range(len(name_lower) - 1):
                bigram = name_lower[i:i + 2]
                if bigram in p.title.lower():
                    score += 2
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:limit]]


    @property
    def count(self) -> int:
        return len(self._products)

    @property
    def brand_count(self) -> int:
        return len(self._all_brands)


# 全局单例
product_repo = ProductRepo()


def products_to_dict_list(products, base_url: str = "") -> list:
    """将商品对象统一转换为字典列表（共享工具，供 routers 使用）"""
    if not products:
        return []

    result = []
    for i, p in enumerate(products):
        try:
            if hasattr(p, 'to_dict'):
                result.append(p.to_dict(base_url=base_url))
            elif isinstance(p, dict):
                product_dict = p.copy()
                if 'image_path' in product_dict and 'image_url' not in product_dict:
                    image_path = product_dict['image_path']
                    if image_path:
                        if image_path.startswith('http'):
                            product_dict['image_url'] = image_path
                        else:
                            product_dict['image_url'] = f"{base_url}/api/products/image/{product_dict.get('id', '')}"
                result.append(product_dict)
            else:
                result.append({
                    "id": getattr(p, 'id', str(i)),
                    "name": getattr(p, 'title', getattr(p, 'name', f"Product {i}")),
                    "brand": getattr(p, 'brand', "Unknown"),
                    "category": getattr(p, 'category', "Unknown"),
                    "price": getattr(p, 'base_price', getattr(p, 'price', 0.0)),
                    "image_url": "",
                    "rating": 4.5,
                    "review_count": 1000,
                    "description": getattr(p, 'description', "暂无描述")
                })
        except Exception as e:
            print(f"转换商品 {i} 失败: {str(e)}")
    return result
