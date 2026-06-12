"""
图像智能服务 — 整合图像向量化检索和视觉内容分析。

两大核心能力：
    1. 图像向量化搜索：使用 Doubao-embedding-vision 将图片映射到 2048 维向量空间，
       与文本向量统一编码，实现跨模态相似商品检索
    2. VLM 视觉分析：调用多模态大模型识别物体属性（名称、类目、颜色、材质、品牌），
       作为降级方案或辅助检索

索引构建：
    - 启动时批量为商品图片建立向量索引，存入 ChromaDB 的 product_images 集合
    - 支持同步/异步两种调用方式

检索流程（拍照找货）：
    优先向量检索 → 距离阈值过滤 → 商品聚合
    向量检索失败时自动降级到 VLM 识别 + 文本检索
"""
import os
import asyncio
import aiohttp
import base64
import json
from dotenv import load_dotenv
from typing import List, Dict, Optional

load_dotenv()

class ImageService:
    """图像智能服务 — 向量检索与视觉内容分析"""

    def __init__(self):
        self.api_key = os.getenv("DOUBAO_API_KEY")
        self.base_url = os.getenv("DOUBAO_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")
        self.model = os.getenv("DOUBAO_MODEL", "ep-20260514111645-lmgt2")
        # 图像向量化需要独立 endpoint 和 API Key（自己开通的 embedding-vision 与官方给的 chat 端点 Key 不同）
        self.embedding_vision_model = os.getenv(
            "DOUBAO_EMBEDDING_VISION_MODEL",
            "Doubao-embedding-vision"  # 兜底：如果没配 endpoint 则用模型名（会报错提示配 endpoint）
        )
        self.embedding_vision_api_key = os.getenv("DOUBAO_EMBEDDING_VISION_API_KEY") or self.api_key
        self.max_retries = 3
        self.retry_delay = 5
        
        # 图像向量索引集合
        self.image_collection = None
        self._init_image_collection()

    def _init_image_collection(self):
        """初始化图像向量索引集合（使用共享 ChromaDB 客户端）"""
        try:
            from rag.chroma_client import get_or_create_collection
            self.image_collection = get_or_create_collection("product_images")
            print(f"[ImageService] 图像向量集合初始化完成，当前索引 {self.image_collection.count()} 张图片")
        except Exception as e:
            print(f"[ImageService] 初始化图像向量集合失败: {e}")

    async def _get_image_embedding(self, image_data: bytes) -> List[float]:
        """
        使用 Doubao-embedding-vision 获取图像向量（2048维）
        将图像映射到与文本相同的向量空间，支持跨模态检索

        API: POST /api/v3/embeddings/multimodal
        文档: https://www.volcengine.com/docs/82379/1409291
        """
        url = f"{self.base_url}embeddings/multimodal"

        image_base64 = base64.b64encode(image_data).decode('utf-8')

        headers = {
            "Authorization": f"Bearer {self.embedding_vision_api_key}",
            "Content-Type": "application/json"
        }

        # 多模态 API 要求 input 是带 type 标记的对象数组
        payload = {
            "model": self.embedding_vision_model,
            "input": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                }
            ],
            "encoding_format": "float"
        }

        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=60)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"图像向量化失败: {error_text}")

                        data = await response.json()
                        # 多模态 API 返回格式: {"data": {"embedding": [...]}}
                        if "data" in data and "embedding" in data["data"]:
                            return data["data"]["embedding"]
                        raise Exception(f"未获取到图像向量，返回结构: {json.dumps(data, ensure_ascii=False)[:200]}")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"图像向量化请求失败: {str(e)}，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise

    async def analyze_image(self, image_data: bytes) -> Dict:
        """
        使用 Doubao 多模态接口分析图像内容，输出结构化电商属性
        """
        url = f"{self.base_url}chat/completions"

        image_base64 = base64.b64encode(image_data).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{image_base64}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        vlm_prompt = """你是一个电商商品识别助手。请仔细看这张照片，然后严格按以下JSON格式输出（只输出JSON，不要其他内容）：

{
  "object_name": "物品名称（简短，如：无线蓝牙耳机、跑步鞋、防晒霜）",
  "category": "商品类目（从以下选：美妆护肤/数码电子/服饰运动/食品饮料/家居生活/图书文具/家用电器/母婴用品，如果无法确定写未知）",
  "color": "颜色（如：黑色、白色，无则写空字符串）",
  "material": "材质（如：塑料、金属、皮革，无则写空字符串）",
  "brand": "品牌（如果能识别，无则写空字符串）",
  "style": "风格/场景（如：运动、休闲、商务，无则写空字符串）",
  "key_features": ["关键特征1", "特征2"],
  "description": "一句话描述这个物品（30字内）"
}

注意：
- object_name 要具体，不要只说"鞋子"而要说"白色运动跑鞋"
- key_features 列出2-4个对购物搜索有帮助的特征
- 如果某字段无法确定，用空字符串或空数组"""

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url}
                        },
                        {
                            "type": "text",
                            "text": vlm_prompt
                        }
                    ]
                }
            ],
            "max_tokens": 500
        }

        for attempt in range(self.max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=120)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"图像分析请求失败: {error_text}")

                        data = await response.json()
                        raw = data["choices"][0]["message"]["content"]
                        return self._parse_analysis_result(raw)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    print(f"图像分析请求失败: {str(e)}，正在重试 ({attempt + 1}/{self.max_retries})...")
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    raise

    def _parse_analysis_result(self, raw: str) -> Dict:
        """解析 VLM 返回的 JSON 结果，降级兼容纯文本"""
        result = {
            "object_name": "",
            "category": "",
            "color": "",
            "material": "",
            "brand": "",
            "style": "",
            "key_features": [],
            "description": ""
        }

        # 尝试解析 JSON
        try:
            json_str = raw
            if "```json" in raw:
                json_str = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                json_str = raw.split("```")[1].split("```")[0]
            parsed = json.loads(json_str.strip())
            for key in result:
                if key in parsed:
                    result[key] = parsed[key]
            result["description"] = result["description"] or raw[:200]
            return result
        except (json.JSONDecodeError, IndexError):
            pass

        # 降级：自由文本解析
        result["description"] = raw[:200]
        if raw:
            name_keywords = ["物品名称：", "名称：", "是一个", "是一件", "是一款", "这是"]
            for keyword in name_keywords:
                if keyword in raw:
                    idx = raw.index(keyword) + len(keyword)
                    end_idx = raw.find("，", idx)
                    if end_idx == -1: end_idx = raw.find("。", idx)
                    if end_idx == -1: end_idx = min(len(raw), idx + 30)
                    result["object_name"] = raw[idx:end_idx].strip()
                    break

            for color in ["红色", "蓝色", "黑色", "白色", "灰色", "黄色", "绿色", "紫色", "粉色", "棕色"]:
                if color in raw and not result["color"]:
                    result["color"] = color
                    break

            brand_keywords = ["品牌：", "品牌是", "品牌为"]
            for keyword in brand_keywords:
                if keyword in raw:
                    idx = raw.index(keyword) + len(keyword)
                    end_idx = raw.find("，", idx)
                    if end_idx == -1: end_idx = raw.find("。", idx)
                    if end_idx == -1: end_idx = len(raw)
                    result["brand"] = raw[idx:end_idx].strip()
                    break

        return result

    async def search_similar_products_by_image(self, image_data: bytes, retriever=None) -> tuple:
        """
        拍照找货：优先 VLM 识别（与文字聊天共用同一 endpoint），
        仅当 embedding-vision 模型被显式配置时才走向量检索路径。

        流程：
        1. VLM 识别物体属性 → RAG 文本检索（首选，endpoint 已验证可用）
        2. 如果配置了独立的 embedding-vision endpoint，则用向量检索（更精确）
        """
        embedding_model_configured = bool(os.getenv("DOUBAO_EMBEDDING_VISION_MODEL"))
        if not embedding_model_configured:
            print("[ImageService] embedding-vision 未配置，使用 VLM 识别", flush=True)
            return await self.search_similar_products(image_data, retriever)

        try:
            embedding = await self._get_image_embedding(image_data)
            if self.image_collection and self.image_collection.count() > 0:
                results = self.image_collection.query(
                    query_embeddings=[embedding],
                    n_results=8,
                    include=["metadatas", "distances"]
                )
                # 打印所有距离，方便调试阈值
                top_distances = [f"{d:.4f}" for d in results['distances'][0][:8]]
                print(f"[ImageService] 向量检索 top-8 距离: {top_distances}", flush=True)

                product_ids = []
                seen = set()
                for i, pid in enumerate(results['ids'][0]):
                    if pid not in seen:
                        seen.add(pid)
                        distance = results['distances'][0][i]
                        if distance < 0.9:  # 🔧 放宽阈值 0.7→0.9
                            product_ids.append(pid)
                matched_products = []
                if retriever and hasattr(retriever, 'get_product_by_id'):
                    for pid in product_ids[:5]:
                        product = retriever.get_product_by_id(pid)
                        if product:
                            matched_products.append(product)

                # 🔧 向量检索 0 匹配 → 回落 VLM 做二次搜素
                if len(matched_products) == 0:
                    print("[ImageService] 向量检索 0 匹配，回落 VLM", flush=True)
                    vlm_products, vlm_analysis = await self.search_similar_products(image_data, retriever)
                    vlm_analysis["method"] = "vector_fallback_vlm"
                    return vlm_products, vlm_analysis

                return matched_products, {"method": "vector_search", "count": len(matched_products)}
            # 无图像索引 → VLM
            return await self.search_similar_products(image_data, retriever)
        except Exception as e:
            print(f"[ImageService] 图像向量检索失败，降级到 VLM: {e}", flush=True)
            return await self.search_similar_products(image_data, retriever)

    async def search_similar_products(self, image_data: bytes, retriever):
        """
        拍照找货（降级方案）：VLM 识别物体属性 → RAG 检索相似商品

        流程：
        1. VLM 识别 → 结构化属性（名称/类目/颜色/材质/品牌/特征）
        2. 用类目过滤 + 多关键词组合搜索
        3. 返回匹配商品 + 分析结果
        """
        # 1. VLM 分析图像
        analysis = await self.analyze_image(image_data)

        # 2. 构建搜索查询：主要用 object_name + key_features
        search_terms = []
        obj_name = analysis.get("object_name", "")
        if obj_name:
            search_terms.append(obj_name)
        for feat in analysis.get("key_features", [])[:2]:
            if feat:
                search_terms.append(feat)
        if analysis.get("color"):
            search_terms.append(analysis["color"])
        if analysis.get("material"):
            search_terms.append(analysis["material"])

        search_query = " ".join(search_terms) if search_terms else analysis.get("description", "")[:100]

        # 3. 确定类目过滤
        category_filter = analysis.get("category", "")
        valid_categories = ["美妆护肤", "数码电子", "服饰运动", "食品饮料", "家居生活", "图书文具", "家用电器", "母婴用品"]
        if category_filter not in valid_categories:
            category_filter = None

        # 4. RAG 检索：优先用类目过滤，无结果时不过滤
        if search_query.strip() and retriever:
            print(f"[ImageService] VLM 搜索词: '{search_query}', 类目: {category_filter}", flush=True)
            products = retriever.search(search_query, top_k=5, category_filter=category_filter)
            products = [p.to_dict() if hasattr(p, 'to_dict') else p for p in products]
            # 🔧 类目过滤 0 结果 → 去掉类目重试
            if not products and category_filter:
                print(f"[ImageService] 类目 '{category_filter}' 过滤后无结果，去掉类目重试", flush=True)
                products = retriever.search(search_query, top_k=5, category_filter=None)
                products = [p.to_dict() if hasattr(p, 'to_dict') else p for p in products]
        else:
            products = []

        print(f"[ImageService] VLM 最终结果: {len(products)} 个商品", flush=True)
        return products, analysis

    async def index_product_images_async(self, products: List[Dict]):
        """为商品图片建立向量索引（异步版本，用于 startup event）"""
        return await self._index_product_images_impl(products)

    async def _index_product_images_impl(self, products: List[Dict]):
        """商品图片索引实现（共享逻辑）"""
        if not self.image_collection:
            print("[ImageService] 图像向量集合未初始化")
            return 0

        try:
            ids = []
            embeddings = []
            metadatas = []

            for product in products:
                product_id = product.get("id", "")
                if not product_id:
                    continue

                image_data = None
                if "image_base64" in product:
                    image_data = base64.b64decode(product["image_base64"])
                elif "image_url" in product:
                    image_path = product["image_url"]
                    if os.path.exists(image_path):
                        with open(image_path, "rb") as f:
                            image_data = f.read()

                if image_data:
                    ids.append(product_id)
                    embeddings.append(await self._get_image_embedding(image_data))
                    metadatas.append({
                        "product_id": product_id,
                        "title": product.get("title", ""),
                        "brand": product.get("brand", ""),
                        "category": product.get("category", "")
                    })

            if ids:
                self.image_collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    metadatas=metadatas
                )
                print(f"[ImageService] 成功索引 {len(ids)} 张商品图片")
                return len(ids)

            return 0
        except Exception as e:
            print(f"[ImageService] 索引商品图片失败: {e}")
            return 0

    def index_product_images(self, products: List[Dict]):
        """
        为商品图片建立向量索引（同步版本，用于非 async 上下文）

        参数:
            products: 商品列表，每个商品需要包含 id, image_url 或 image_base64
        """
        import asyncio as _asyncio
        return _asyncio.run(self._index_product_images_impl(products))