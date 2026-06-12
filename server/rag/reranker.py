"""
Cross-Encoder 精排器，在 RRF 融合后对候选 chunk 进行精排。

相比双塔向量化模型更精准：
    Cross-Encoder 同时考虑查询和文档内容进行交互打分，
    输出一个 0-1 之间的相关性分数，而非分别编码后计算余弦相似度。

处理流程：
    RRF top-20 chunks → CrossEncoder 逐对打分 → 重新排序 → 商品聚合

默认模型：BAAI/bge-reranker-base（可通过 RERANKER_MODEL 环境变量配置）
模型大小约 500MB，单对推理耗时约 50ms，20 对约 1 秒。
"""
import os
from typing import Optional

from sentence_transformers import CrossEncoder


class CrossEncoderReranker:
    """Cross-Encoder 精排器 — 对 chunk 级别做逐对相关性打分"""

    def __init__(self, model_name: Optional[str] = None):
        self._model: Optional[CrossEncoder] = None
        self._model_name = model_name or os.getenv(
            "RERANKER_MODEL", "BAAI/bge-reranker-base"
        )

    def _ensure_model(self):
        """延迟加载模型（首次调用时才下载），下载失败则优雅降级"""
        if self._model is not None:
            return

        # 先尝试本地加载（设置离线环境变量）
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            self._model = CrossEncoder(self._model_name)
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            print(f"[reranker] 模型 {self._model_name} 从本地加载")
            return
        except Exception:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)

        # 多端点 fallback 下载
        endpoints = [
            ("HF 镜像", None),                      # 默认（通常为 hf-mirror.com）
            ("HF 官方", "https://huggingface.co"),  # 官方源
        ]
        for label, endpoint in endpoints:
            try:
                if endpoint:
                    print(f"[reranker] 尝试 {label} ({endpoint}) 下载 {self._model_name}...")
                    os.environ["HF_ENDPOINT"] = endpoint
                else:
                    print(f"[reranker] 正在下载模型 {self._model_name}...")
                self._model = CrossEncoder(self._model_name)
                print(f"[reranker] 模型下载完成 ({label})")
                return
            except Exception as e:
                print(f"[reranker] {label} 下载失败: {e}")
                continue

        # 全部失败
        self._model = None
        print(f"[reranker] 所有端点下载失败，将跳过 Cross-Encoder 精排")

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_k: int = 20,
    ) -> list[dict]:
        """
        对 chunks 做 Cross-Encoder 精排，返回按 relevance score 降序的 chunks。

        Args:
            query: 用户查询
            chunks: RRF 融合后的 chunk 列表，每个含 {"id", "document", "metadata", "score"}
            top_k: 返回 top-N chunks

        Returns:
            按 cross_score 降序的 chunks（新增 "cross_score" 字段）
        """
        if not chunks:
            return chunks

        self._ensure_model()
        if self._model is None:
            return chunks  # 模型未就绪，跳过精排

        # 构建 (query, document) 对
        pairs = [(query, chunk.get("document", "")) for chunk in chunks]

        # Cross-Encoder 打分
        scores = self._model.predict(pairs, show_progress_bar=False)

        # 归一化到 0-1（sigmoid）
        import numpy as np

        def _sigmoid(x):
            return 1.0 / (1.0 + np.exp(-x))

        normalized = _sigmoid(np.array(scores)).tolist()

        # 注入 cross_score 并排序
        for chunk, cross_score in zip(chunks, normalized):
            chunk["cross_score"] = float(cross_score)

        chunks.sort(key=lambda c: c.get("cross_score", 0), reverse=True)

        return chunks[:top_k]


# 全局单例
reranker = CrossEncoderReranker()
