"""
ProductRepo — 商品数据访问抽象层。

所有商品查询必须通过这里，不直接访问 retriever.products。
好处：统一索引、缓存、替换数据源时只改这里。
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

    # ── 加载 ──────────────────────────────────────────

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

    # ── 查询 ──────────────────────────────────────────

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

    # ── 统计 ──────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._products)

    @property
    def brand_count(self) -> int:
        return len(self._all_brands)


# 全局单例
product_repo = ProductRepo()
