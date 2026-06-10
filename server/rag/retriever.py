"""
混合检索器 — Chunk 级向量召回 + BM25 召回 → RRF 融合 → 商品聚合。

RRF（Reciprocal Rank Fusion）：
    score(d) = Σ 1 / (k + rank(d))，k=60
    向量分数（0-1 余弦）和 BM25 分数（无上界）量纲不同，
    RRF 只用排名，完全绕开量纲问题。

Query 解析：
    "200元以内的洗面奶" → semantic_query="洗面奶" + where={"base_price": {"$lte": 200}}
    价格数字在向量空间是噪声，由结构化过滤处理才可靠。

Chunk 级检索：
    每个商品拆成 3-6 个 chunk（标题+属性 / 描述 / FAQ / 评价），
    分别 embedding → 检索时召回 chunk → 按 product_id 聚合取 max score。
    避免长文本信息在单一 embedding 中被稀释。
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

import chromadb
import jieba
from chromadb.config import Settings
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from models.schemas import Product
from utils.product_repo import product_repo
from rag.keyword_retriever import AttributeMatcher
from rag.product_graph import product_graph as _product_graph


# ══════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════

RRF_K = 60
CHUNK_TYPE_TITLE = "title_block"
CHUNK_TYPE_DESC = "description_block"
CHUNK_TYPE_FAQ = "faq_block"
CHUNK_TYPE_REVIEW = "review_block"

# ChromaDB 集合名（chunk 级，区别于旧 product 级）
COLLECTION_NAME = "product_chunks"


# ══════════════════════════════════════════════════════════════
# Query 解析 — 从自然语言中提取结构化约束
# ══════════════════════════════════════════════════════════════

@dataclass
class ParsedQuery:
    """Query 解构结果"""
    semantic_query: str                       # 语义部分 → RAG
    where_filter: Optional[dict[str, Any]] = None  # 结构化部分 → metadata filter


_PRICE_PATTERNS = [
    (r"(\d+)\s*元以内",        lambda m: {"base_price": {"$lte": float(m.group(1))}}),
    (r"(\d+)\s*元以下",        lambda m: {"base_price": {"$lt":  float(m.group(1))}}),
    (r"(\d+)\s*元以上",        lambda m: {"base_price": {"$gte": float(m.group(1))}}),
    (r"预算\s*(\d+)",          lambda m: {"base_price": {"$lte": float(m.group(1))}}),
    (r"(\d+)\s*-\s*(\d+)\s*元", lambda m: {"$and": [
        {"base_price": {"$gte": float(m.group(1))}},
        {"base_price": {"$lte": float(m.group(2))}},
    ]}),
]

_PRICE_REMOVE_PATTERN = re.compile(
    r"\d+\s*元(以内|以下|以上)|\d+\s*-\s*\d+\s*元|预算\s*\d+"
)

# 移除价格文本后清理连接词残留
_PRICE_ARTIFACT_PATTERN = re.compile(r'^(的|以内|以下|价格|价钱|大概|大约)?\s*')


def parse_query(query: str) -> ParsedQuery:
    """从 query 中提取结构化约束，返回纯语义 query + metadata filter。"""
    where_filter = None
    semantic = query

    for pattern, builder in _PRICE_PATTERNS:
        m = re.search(pattern, query)
        if m:
            where_filter = builder(m)
            semantic = _PRICE_REMOVE_PATTERN.sub("", query).strip()
            semantic = _PRICE_ARTIFACT_PATTERN.sub("", semantic).strip()
            break

    return ParsedQuery(semantic_query=semantic or query, where_filter=where_filter)


# ══════════════════════════════════════════════════════════════
# RRF 融合
# ══════════════════════════════════════════════════════════════

def _rrf_fuse(*rankings: list[dict[str, Any]], k: int = RRF_K) -> list[tuple[str, float]]:
    """多路检索结果 RRF 融合，返回 [(chunk_id, rrf_score), ...] 降序"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            doc_id = item["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ══════════════════════════════════════════════════════════════
# 同义词扩展词典
# ══════════════════════════════════════════════════════════════

_SYNONYM_DICT: dict[str, list[str]] = {
    "洗面奶": ["洗面奶", "洁面乳", "洁面", "洗颜", "洁面泡沫", "洁面膏"],
    "精华": ["精华", "精华液", "精华露", "精华素", "安瓶"],
    "面霜": ["面霜", "乳霜", "保湿霜", "护肤霜", "霜"],
    "防晒": ["防晒", "防晒霜", "防晒乳", "防晒露", "隔离", "SPF"],
    "卸妆": ["卸妆", "卸妆油", "卸妆水", "卸妆乳", "卸妆膏"],
    "眼霜": ["眼霜", "眼部精华", "眼周护理"],
    "化妆水": ["化妆水", "爽肤水", "柔肤水", "水", "神仙水", "调理水"],
    "面膜": ["面膜", "涂抹面膜", "膜"],
    "粉底": ["粉底", "粉底液", "粉底霜", "底妆"],
    "口红": ["口红", "唇膏", "唇釉", "唇彩", "唇色"],
    "蜜粉": ["蜜粉", "散粉", "定妆粉", "控油粉"],
    "眉笔": ["眉笔", "画眉", "眉粉"],
    "手机": ["手机", "智能手机", "移动电话", "机"],
    "耳机": ["耳机", "无线耳机", "蓝牙耳机", "入耳式耳机"],
    "笔记本": ["笔记本", "笔记本电脑", "电脑", "本子", "轻薄本", "MacBook"],
    "平板": ["平板", "平板电脑", "iPad", "Pad"],
    "跑步鞋": ["跑步鞋", "跑鞋", "慢跑鞋", "运动跑鞋"],
    "篮球鞋": ["篮球鞋", "球鞋", "实战篮球鞋"],
    "登山鞋": ["登山鞋", "徒步鞋", "户外鞋", "越野鞋"],
    "速干": ["速干", "快干", "透气", "排汗"],
    "卫衣": ["卫衣", "连帽衫", "套头衫", "Hoodie"],
    "咖啡": ["咖啡", "速溶咖啡", "黑咖啡", "美式"],
    "气泡水": ["气泡水", "苏打水", "碳酸水", "气泡饮料"],
    "坚果": ["坚果", "每日坚果", "混合坚果", "果仁"],
    "方便面": ["方便面", "泡面", "速食面", "桶面", "袋面"],
    "牛奶": ["牛奶", "纯牛奶", "全脂奶", "乳"],
}

_EXPANSION_MAP: dict[str, list[str]] = {}
for _canonical, _synonyms in _SYNONYM_DICT.items():
    for _syn in _synonyms:
        if _syn not in _EXPANSION_MAP:
            _EXPANSION_MAP[_syn] = []
        for _s in _synonyms:
            if _s not in _EXPANSION_MAP[_syn]:
                _EXPANSION_MAP[_syn].append(_s)


def _expand_query(query: str) -> str:
    """同义词扩展：'洗面奶' → '洗面奶 洁面乳 洁面 洗颜'"""
    expansions: list[str] = []
    for term, expanded in _EXPANSION_MAP.items():
        if term in query:
            for syn in expanded:
                if syn != term and syn not in query:
                    expansions.append(syn)
    if expansions:
        return query + " " + " ".join(expansions)
    return query


# ══════════════════════════════════════════════════════════════
# BM25 where filter — 与 ChromaDB where 语法一致
# ══════════════════════════════════════════════════════════════

def _matches_where(metadata: dict, where: Optional[dict]) -> bool:
    """BM25 侧的 metadata 过滤。支持 $and/$or/$lt/$lte/$gt/$gte/$ne。"""
    if not where:
        return True
    if "$and" in where:
        return all(_matches_where(metadata, cond) for cond in where["$and"])
    if "$or" in where:
        return any(_matches_where(metadata, cond) for cond in where["$or"])

    for key, condition in where.items():
        if key.startswith("$"):
            continue
        val = metadata.get(key)
        if isinstance(condition, dict):
            for op, threshold in condition.items():
                if op in ("$lt", "$lte", "$gt", "$gte"):
                    if val is None:
                        return False
                if op == "$lt"  and not (val < threshold):   return False
                if op == "$lte" and not (val <= threshold):  return False
                if op == "$gt"  and not (val > threshold):   return False
                if op == "$gte" and not (val >= threshold):  return False
                if op == "$ne"  and not (val != threshold):  return False
        else:
            if val != condition:
                return False
    return True


# ══════════════════════════════════════════════════════════════
# BM25 检索器 — jieba 分词 + BM25Okapi
# ══════════════════════════════════════════════════════════════

def _tokenize(text: str) -> list[str]:
    """中文分词 — jieba 词级分词，比字符 bigram 更准"""
    return list(jieba.cut(text))


class BM25Retriever:
    """BM25 检索器，索引从 chunk 构建，与向量库用同一份数据。"""

    def __init__(self):
        self._ids: list[str] = []
        self._documents: list[str] = []
        self._metadatas: list[dict] = []
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized_corpus: list[list[str]] = []
        self._built = False

    def build_from_records(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
    ) -> int:
        """从全量 chunk 记录构建 BM25 索引"""
        self._ids = ids
        self._documents = documents
        self._metadatas = metadatas
        self._tokenized_corpus = [_tokenize(doc) for doc in self._documents]
        self._bm25 = BM25Okapi(self._tokenized_corpus)
        self._built = True
        return len(self._ids)

    def search(
        self,
        query: str,
        top_k: int = 20,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        BM25 检索（chunk 级）。where 过滤在打分后做。
        返回格式与 ChromaDB query 一致：[{id, document, metadata, score}, ...]
        """
        if not self._built:
            return []

        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)

        # 按分数降序排列
        ranked = sorted(
            zip(self._ids, self._documents, self._metadatas, scores),
            key=lambda x: x[3],
            reverse=True,
        )

        results = []
        for _id, doc, meta, score in ranked:
            if score <= 0:
                break  # BM25 分数为 0 表示不相关
            if where and not _matches_where(meta, where):
                continue
            results.append({
                "id": _id,
                "document": doc,
                "metadata": meta,
                "score": float(score),
            })
            if len(results) >= top_k:
                break

        return results


# ══════════════════════════════════════════════════════════════
# ProductRetriever — 混合检索主入口
# ══════════════════════════════════════════════════════════════

# 查询停用词 — 去掉填充词让语义搜索更精准
_QUERY_STOP_WORDS = {
    '帮我', '推荐', '一款', '一双', '一个', '一件', '一些', '一下',
    '我想', '想要', '我要', '需要', '想买', '帮我推荐', '帮我找',
    '有没有', '有什么', '有哪些', '哪个好', '多少钱',
    '请', '麻烦', '可不可以', '能不能', '可以',
}


class ProductRetriever:
    """Chunk 级混合检索器 — 向量 + BM25 → RRF → 商品聚合"""

    def __init__(self):
        self.client = None
        self.collection = None
        self.embedding_model = None
        self.products: list[Product] = []
        self.bm25 = BM25Retriever()
        self.attribute_matcher = AttributeMatcher()
        # chunk 元数据缓存：chunk_id → {product_id, title, brand, ...}
        self._chunk_meta: dict[str, dict] = {}
        # 检索结果缓存（in-memory，TTL=300s，数据集静态所以长 TTL）
        self._result_cache: dict[str, tuple[float, list[Product]]] = {}
        self._cache_lock = Lock()
        self._CACHE_TTL = 300  # 5 分钟

    def initialize(self):
        self._init_chroma()
        self._load_data()
        self._create_embeddings()
        self._build_bm25()
        # 构建商品关系图
        if not _product_graph._built:
            _product_graph.build(self.products)

    def _init_chroma(self):
        from rag.chroma_client import get_or_create_collection
        self.collection = get_or_create_collection(COLLECTION_NAME)

    def _load_data(self):
        if product_repo.count == 0:
            product_repo.load()
        self.products = product_repo.all()
        print(f"Loaded {len(self.products)} products from ProductRepo")

    # ── Chunk 构建 ────────────────────────────────────

    @staticmethod
    def _build_chunks(product: Product) -> list[dict]:
        """将一个商品拆成多个 chunk，用于细粒度检索"""
        chunks = []
        base_meta = {
            "product_id": product.id,
            "title": product.title,
            "brand": product.brand,
            "category": product.category,
            "sub_category": product.sub_category,
            "base_price": product.base_price,
            "image_path": product.image_path,
        }

        # Chunk 0: 标题 + 属性 + SKU
        sku_text = ""
        if product.skus:
            first = product.skus[0]
            sku_text = "；".join(f"{k}:{v}" for k, v in first.properties.items())
        title_text = (
            f"商品名称: {product.title}\n"
            f"品牌: {product.brand}\n"
            f"类目: {product.category} > {product.sub_category}\n"
            f"价格: ¥{product.base_price:.0f}\n"
            f"规格: {sku_text or '—'}"
        )
        chunks.append({
            "chunk_id": f"{product.id}_c0",
            "chunk_type": CHUNK_TYPE_TITLE,
            "content": title_text,
            "metadata": {**base_meta, "chunk_type": CHUNK_TYPE_TITLE},
        })

        # 上下文前缀：让每个 chunk 自带商品身份，提升 embedding 检索精度
        ctx_prefix = f"[{product.brand}] {product.title} — {product.category}/{product.sub_category}"

        # Chunk 1: 营销描述
        desc = product.rag_knowledge.marketing_description
        if desc:
            chunks.append({
                "chunk_id": f"{product.id}_c1",
                "chunk_type": CHUNK_TYPE_DESC,
                "content": f"{ctx_prefix}\n{desc}",
                "metadata": {**base_meta, "chunk_type": CHUNK_TYPE_DESC},
            })

        # Chunk 2: FAQ
        faqs = product.rag_knowledge.official_faq
        if faqs:
            faq_text = "\n".join(
                f"Q: {f.question}\nA: {f.answer}" for f in faqs
            )
            chunks.append({
                "chunk_id": f"{product.id}_c2",
                "chunk_type": CHUNK_TYPE_FAQ,
                "content": f"{ctx_prefix}\n常见问题:\n{faq_text}",
                "metadata": {**base_meta, "chunk_type": CHUNK_TYPE_FAQ},
            })

        # Chunk 3+: 用户评价（每条一个 chunk，最多 3 条）
        reviews = product.rag_knowledge.user_reviews[:3]
        for i, review in enumerate(reviews):
            chunks.append({
                "chunk_id": f"{product.id}_c{3 + i}",
                "chunk_type": CHUNK_TYPE_REVIEW,
                "content": f"{ctx_prefix}\n用户评价 ({review.rating}星): {review.content}",
                "metadata": {**base_meta, "chunk_type": CHUNK_TYPE_REVIEW},
            })

        return chunks

    # ── Embedding 构建 ─────────────────────────────────

    def _ensure_model(self):
        """确保 embedding 模型已加载（离线优先，避免 HF 网络超时）"""
        if not self.embedding_model:
            try:
                self.embedding_model = SentenceTransformer(
                    'all-MiniLM-L6-v2', local_files_only=True
                )
            except Exception:
                self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

    def _create_embeddings(self):
        """为所有 chunk 创建向量 embedding"""
        self._ensure_model()

        if self.collection.count() > 0:
            print(f"[retriever] 集合 '{COLLECTION_NAME}' 已有 {self.collection.count()} 条，跳过 embedding")
            # 仍需加载 chunk_meta 缓存
            self._load_chunk_meta()
            return

        all_chunks = []
        for product in self.products:
            all_chunks.extend(self._build_chunks(product))

        documents = []
        metadatas = []
        ids = []

        for c in all_chunks:
            documents.append(c["content"])
            metadatas.append(c["metadata"])
            ids.append(c["chunk_id"])
            # 缓存 chunk → product 映射
            self._chunk_meta[c["chunk_id"]] = c["metadata"]

        print(f"Creating embeddings for {len(documents)} chunks from {len(self.products)} products...")
        embeddings = self.embedding_model.encode(documents)

        self.collection.add(
            embeddings=embeddings.tolist(),
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
        print(f"[retriever] Embeddings created: {len(ids)} chunks")

    def _load_chunk_meta(self):
        """从 ChromaDB 加载 chunk → product 映射缓存"""
        if self._chunk_meta:
            return
        result = self.collection.get(include=["metadatas"])
        for i, chunk_id in enumerate(result["ids"]):
            self._chunk_meta[chunk_id] = result["metadatas"][i]
        print(f"[retriever] Loaded {len(self._chunk_meta)} chunk metadata entries")

    def _build_bm25(self):
        """从 ChromaDB 全量 chunk 构建 BM25 索引"""
        if self.bm25._built:
            return
        result = self.collection.get(include=["documents", "metadatas"])
        count = self.bm25.build_from_records(
            result["ids"], result["documents"], result["metadatas"]
        )
        print(f"[retriever] BM25 索引构建完成: {count} chunks")

    # ── 查询清洗 ─────────────────────────────────────

    def _clean_query(self, query: str) -> str:
        """去掉查询中的填充词，保留核心商品描述"""
        cleaned = query
        for word in sorted(_QUERY_STOP_WORDS, key=len, reverse=True):
            cleaned = cleaned.replace(word, ' ')
        cleaned = ' '.join(cleaned.split())
        return cleaned.strip() or query

    def _make_cache_key(self, query: str, top_k: int, category_filter: str,
                        price_range: tuple, preferred_brands: list,
                        disliked_brands: list, preferences: dict) -> str:
        """生成检索结果缓存键（MD5 of canonical JSON）"""
        raw = json.dumps({
            "q": query, "k": top_k, "cat": category_filter,
            "pr": price_range, "pb": preferred_brands,
            "db": disliked_brands, "prefs": preferences,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()

    # ── 主检索入口 ────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        category_filter: str = None,
        price_range: tuple = None,
        preferred_brands: list = None,
        disliked_brands: list = None,
        preferences: dict = None,
    ) -> list[Product]:
        """
        混合检索主入口：向量 + BM25 + 属性匹配 → RRF → Cross-Encoder → 商品聚合。
        preferences: 用户偏好字典，用于多维 boost（价格/风格/肤质/口味等）
        """
        # ── 缓存检查（数据集静态，同参数查询直接返回） ──
        cache_key = self._make_cache_key(
            query, top_k, category_filter, price_range,
            preferred_brands, disliked_brands, preferences,
        )
        with self._cache_lock:
            entry = self._result_cache.get(cache_key)
            if entry is not None:
                ts, cached_result = entry
                if time.time() - ts < self._CACHE_TTL:
                    print(f"[cache] HIT: {query[:30]} → {len(cached_result)} results")
                    return list(cached_result)  # 浅拷贝，避免调用方修改缓存
                else:
                    del self._result_cache[cache_key]

        # ── Query 解析 ────────────────────────────────
        parsed = parse_query(query)
        clean_query = self._clean_query(parsed.semantic_query)

        # 合并 where filter：parse_query 提取的 + 外部传入的
        where = parsed.where_filter or {}
        if category_filter:
            where["category"] = category_filter
        if disliked_brands:
            where = {"$and": [where, {"brand": {"$ne": b for b in disliked_brands}}]} if where else {}

        # ── 向量检索（chunk 级） ───────────────────────
        t0 = time.time()
        vector_results = self._vector_search(clean_query, top_k * 4, where)
        t1 = time.time()

        # ── BM25 检索（chunk 级，同义词扩展） ──────────
        expanded_query = _expand_query(clean_query)
        bm25_results = self.bm25.search(expanded_query, top_k * 4, where)
        t2 = time.time()

        # ── 属性匹配检索（结构化品牌/类目/关键词） ──────
        attr_results = self.attribute_matcher.search(clean_query, top_k * 4, where)
        t3 = time.time()

        print(f"[perf] vector={t1-t0:.3f}s  bm25={t2-t1:.3f}s  attr={t3-t2:.3f}s  "
              f"vec_hits={len(vector_results)}  bm25_hits={len(bm25_results)}  attr_hits={len(attr_results)}")

        # ── RRF 融合（chunk 级，三路） ──────────────────
        fused = _rrf_fuse(vector_results, bm25_results, attr_results, k=RRF_K)

        # 构建 chunk_id → {id, document, metadata} 索引
        id_to_chunk: dict[str, dict] = {}
        for r in vector_results + bm25_results + attr_results:
            if r["id"] not in id_to_chunk:
                id_to_chunk[r["id"]] = r

        # ── Cross-Encoder 精排（可选） ────────────────
        try:
            from rag.reranker import reranker as _reranker
            # 取 RRF top-30 chunks 送入 Cross-Encoder
            rerank_candidates = []
            for chunk_id, rrf_score in fused[:30]:
                c = id_to_chunk.get(chunk_id)
                if c:
                    rerank_candidates.append({**c, "rrf_score": rrf_score})
            if rerank_candidates:
                reranked = _reranker.rerank(clean_query, rerank_candidates, top_k=25)
                # 用 cross_score 重建 fused 排序
                fused = [(c["id"], c.get("cross_score", c.get("rrf_score", 0)))
                         for c in reranked]
        except Exception:
            pass  # 模型未就绪 / 下载失败 / 未安装时静默跳过精排

        # 构建 chunk_id → metadata 索引
        id_to_meta: dict[str, dict] = {}
        for r in vector_results + bm25_results:
            id_to_meta[r["id"]] = r["metadata"]

        # ── 按 product_id 聚合取 max RRF score ────────
        product_scores: dict[str, tuple[float, str]] = {}  # pid → (max_score, best_chunk_id)
        for chunk_id, rrf_score in fused:
            meta = id_to_meta.get(chunk_id, {})
            pid = meta.get("product_id", "")
            if not pid:
                continue
            if pid not in product_scores or rrf_score > product_scores[pid][0]:
                product_scores[pid] = (rrf_score, chunk_id)

        # ── 多维偏好 Boost（在 RRF 分数上加常数） ────
        prefs = preferences or {}
        if preferred_brands or prefs:
            boosted = []
            for pid, (score, cid) in product_scores.items():
                meta = id_to_meta.get(cid, {})
                boost = 0.0

                # 品牌偏好：+0.3
                if preferred_brands and meta.get("brand") in preferred_brands:
                    boost += 0.3

                if prefs:
                    # 价格偏好：接近历史价格带 +0.2
                    pref_price = prefs.get("price_range")
                    if pref_price and pref_price != (0, float("inf")):
                        p_min, p_max = pref_price
                        product_price = meta.get("base_price", 0)
                        if product_price and p_min <= product_price <= p_max:
                            boost += 0.2

                    # 品牌优先级：国产/国际 +0.15
                    brand_priority = prefs.get("brand_priority", "")
                    brand = (meta.get("brand") or "").lower()
                    domestic_brands = {"华为", "小米", "oppo", "vivo", "联想", "李宁", "安踏", "特步",
                                       "珀莱雅", "花西子", "薇诺娜", "完美日记", "迪卡侬"}
                    intl_brands = {"苹果", "apple", "耐克", "nike", "阿迪达斯", "adidas", "兰蔻", "lancome",
                                   "雅诗兰黛", "科颜氏", "资生堂", "露露乐蒙", "lululemon", "始祖鸟"}
                    if brand_priority == "国产" and brand in domestic_brands:
                        boost += 0.15
                    elif brand_priority == "国际" and brand in intl_brands:
                        boost += 0.15

                    # 口味偏好：食品类 +0.2
                    flavor = prefs.get("flavor_preference", "")
                    if flavor:
                        chunk_text = meta.get("title", "") + " "
                        if hasattr(self, '_chunk_meta'):
                            pass  # 用 title 做简单的文本匹配
                        flavor_kw = {"辣": ["辣", "麻辣", "香辣"], "甜": ["甜", "甜品", "糖果"],
                                     "酸": ["酸", "酸辣", "酸甜"], "清淡": ["清淡", "低脂", "轻食"]}
                        if any(kw in chunk_text for kw in flavor_kw.get(flavor, [])):
                            boost += 0.2

                    # 肤质匹配：美妆类 +0.2
                    skin_type = prefs.get("skin_type", "")
                    if skin_type:
                        skin_map = {"干性": ["干性", "干皮", "保湿", "滋润"],
                                    "油性": ["油性", "油皮", "控油", "清爽"],
                                    "敏感性": ["敏感", "修护", "温和", "舒缓"],
                                    "混合性": ["混合", "水油平衡"]}
                        chunk_text = meta.get("title", "") + " "
                        if any(kw in chunk_text for kw in skin_map.get(skin_type, [])):
                            boost += 0.2

                boosted.append((pid, (score + boost, cid)))

            boosted.sort(key=lambda x: x[1][0], reverse=True)
            product_scores = dict(boosted)

        # ── 构建 Product 结果 ─────────────────────────
        merged = []
        for pid, (score, _) in sorted(product_scores.items(), key=lambda x: x[1][0], reverse=True):
            product = product_repo.get(pid)
            if product:
                merged.append(product)
            if len(merged) >= top_k:
                break

        # ── 无结果时去类目重试 ─────────────────────────
        if not merged and category_filter:
            print(f"[retriever] 类目过滤 '{category_filter}' 无结果，去掉类目重试...")
            return self.search(query, top_k, None, price_range, preferred_brands, disliked_brands)

        # ── 写入缓存（只缓存有结果的情况） ─────────────
        if merged:
            with self._cache_lock:
                self._result_cache[cache_key] = (time.time(), list(merged))
            print(f"[cache] SET: {query[:30]} ({len(merged)} results)")

        return merged

    def _vector_search(
        self,
        query: str,
        top_k: int,
        where: dict = None,
    ) -> list[dict[str, Any]]:
        """Chunk 级向量检索"""
        self._ensure_model()

        try:
            query_embedding = self.embedding_model.encode(query).tolist()
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, self.collection.count()),
                where=where if where else None,
            )

            output = []
            for i in range(len(results['ids'][0])):
                output.append({
                    "id": results['ids'][0][i],
                    "document": results['documents'][0][i] if results['documents'] else "",
                    "metadata": results['metadatas'][0][i],
                    "score": 1.0 / (i + 1),
                })
            return output
        except Exception as e:
            print(f"[retriever] 向量搜索失败: {e}")
            return []

    # ── 辅助查询方法 ─────────────────────────────────

    def search_by_name(self, name: str, limit: int = 5) -> list:
        """按商品名称模糊搜索，委托 ProductRepo"""
        return product_repo.search_by_name(name, limit)

    def search_by_keyword(self, keyword: str, limit: int = 5) -> list:
        """按关键词搜索（BM25）"""
        results = self.bm25.search(keyword, top_k=limit)
        seen = set()
        products = []
        for r in results:
            pid = r["metadata"].get("product_id", "")
            if pid and pid not in seen:
                seen.add(pid)
                p = product_repo.get(pid)
                if p:
                    products.append(p)
            if len(products) >= limit:
                break
        return products

    def get_product_by_id(self, product_id: str):
        """按 ID 获取 Product 对象"""
        return product_repo.get(product_id)

    def get_all_products(self):
        return [p.to_dict() if hasattr(p, 'to_dict') else p for p in self.products]
