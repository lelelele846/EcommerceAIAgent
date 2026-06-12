"""
统一管理 ChromaDB 客户端实例，确保全局只有一个连接。

设计目的：
    - 避免创建多个客户端导致的配置冲突
    - 统一数据库路径配置
    - 简化调用方式，无需重复初始化

使用示例：
    from rag.chroma_client import get_or_create_collection

    collection = get_or_create_collection("my_collection")
    collection.add(embeddings=[...], documents=[...], ids=[...])
"""
import os
import chromadb
from chromadb.config import Settings

_client = None
_db_path = None

# 统一的 Settings，所有调用方必须一致
_SHARED_SETTINGS = Settings(
    anonymized_telemetry=False,
    allow_reset=True,
)


def get_client() -> chromadb.PersistentClient:
    """获取全局唯一的 ChromaDB PersistentClient 实例"""
    global _client, _db_path
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    if _client is None or _db_path != db_path:
        os.makedirs(db_path, exist_ok=True)
        _client = chromadb.PersistentClient(path=db_path, settings=_SHARED_SETTINGS)
        _db_path = db_path
    return _client


def get_or_create_collection(name: str):
    """获取或创建集合（线程安全由 ChromaDB 保证）"""
    client = get_client()
    return client.get_or_create_collection(name=name)
