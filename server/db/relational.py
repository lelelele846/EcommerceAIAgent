"""
数据持久化层 — SQLite 数据库封装，存储会话和消息历史。

数据库设计：
    - sessions 表：会话状态（状态机状态、最近展示商品、搜索状态、场景上下文、订单状态、偏好）
    - messages 表：消息记录（角色、内容、富内容块数组）
    - 线程本地连接：每个线程独立连接，避免并发冲突

特性：
    - WAL 模式：支持并发读写，提升性能
    - 异步接口：所有业务方法通过 executor 在线程池执行
    - 增量迁移：启动时自动补齐新增字段
    - JSON 序列化：复杂字段自动序列化/反序列化
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional



DB_DIR = os.path.join(os.path.dirname(__file__), "..")
DB_PATH = os.path.join(DB_DIR, "app.db")


def _now() -> str:
    return datetime.utcnow().isoformat()



_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id          TEXT PRIMARY KEY,
    agent_state         TEXT NOT NULL DEFAULT 'browsing',
    last_shown_products TEXT NOT NULL DEFAULT '[]',
    search_state        TEXT NOT NULL DEFAULT '{}',
    scene_context       TEXT NOT NULL DEFAULT '{}',
    order_state         TEXT NOT NULL DEFAULT '{}',
    preferences         TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    blocks      TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


_conn_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """每个线程一个连接，支持并发读"""
    if not hasattr(_conn_local, "conn") or _conn_local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _conn_local.conn = conn
    return _conn_local.conn


# 主线程同步连接（初始化用）
_init_conn: Optional[sqlite3.Connection] = None


def _get_init_conn() -> sqlite3.Connection:
    global _init_conn
    if _init_conn is None:
        _init_conn = sqlite3.connect(DB_PATH)
        _init_conn.row_factory = sqlite3.Row
    return _init_conn


async def init_db() -> None:
    """初始化数据库表（启动时调用一次）"""
    import asyncio
    loop = asyncio.get_running_loop()

    def _init():
        conn = _get_init_conn()
        conn.executescript(_CREATE_TABLES)
        conn.commit()
        # 增量迁移：补老表缺失的列
        cur = conn.execute("PRAGMA table_info(sessions)")
        cols = [r[1] for r in cur.fetchall()]
        for col, default in [
            ("search_state", "'{}'"),
            ("scene_context", "'{}'"),
            ("order_state", "'{}'"),
            ("preferences", "'{}'"),
        ]:
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE sessions ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                )
        cur = conn.execute("PRAGMA table_info(messages)")
        if "blocks" not in [r[1] for r in cur.fetchall()]:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN blocks TEXT NOT NULL DEFAULT '[]'"
            )
        conn.commit()
        print("[startup] SQLite: 数据库初始化完成")

    await loop.run_in_executor(None, _init)


def _execute(sql: str, params=()) -> sqlite3.Cursor:
    """同步执行（非查询用）"""
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur


def _fetchone(sql: str, params=()) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _fetchall(sql: str, params=()) -> list[dict]:
    conn = _get_conn()
    return [dict(r) for r in conn.execute(sql, params).fetchall()]



async def create_session(session_id: str) -> dict:
    """创建新会话"""
    import asyncio
    loop = asyncio.get_running_loop()
    now = _now()

    def _create():
        _execute(
            "INSERT OR IGNORE INTO sessions "
            "(session_id, agent_state, last_shown_products, search_state, scene_context, "
            "order_state, preferences, created_at, updated_at) "
            "VALUES (?, 'browsing', '[]', '{}', '{}', '{}', '{}', ?, ?)",
            (session_id, now, now),
        )

    await loop.run_in_executor(None, _create)
    return {"session_id": session_id, "agent_state": "browsing", "created_at": now}


async def get_session(session_id: str) -> Optional[dict]:
    """获取会话完整状态"""
    import asyncio
    loop = asyncio.get_running_loop()

    def _get():
        return _fetchone("SELECT * FROM sessions WHERE session_id = ?", (session_id,))

    row = await loop.run_in_executor(None, _get)
    if not row:
        return None
    # 反序列化 JSON 字段
    for field in ("last_shown_products", "search_state", "scene_context",
                  "order_state", "preferences"):
        row[field] = json.loads(row.get(field) or ("[]" if field == "last_shown_products" else "{}"))
    return row


async def update_session_state(
    session_id: str,
    agent_state: Optional[str] = None,
    last_shown_products: Optional[list] = None,
    search_state: Optional[dict] = None,
    scene_context: Optional[dict] = None,
    order_state: Optional[dict] = None,
    preferences: Optional[dict] = None,
) -> None:
    """部分更新会话字段"""
    import asyncio
    loop = asyncio.get_running_loop()

    parts, vals = [], []
    field_map = {
        "agent_state": agent_state,
        "last_shown_products": last_shown_products,
        "search_state": search_state,
        "scene_context": scene_context,
        "order_state": order_state,
        "preferences": preferences,
    }
    for field, value in field_map.items():
        if value is not None:
            parts.append(f"{field} = ?")
            if field == "agent_state":
                vals.append(value)
            else:
                vals.append(json.dumps(value, ensure_ascii=False))

    if not parts:
        return
    parts.append("updated_at = ?")
    vals.extend([_now(), session_id])

    def _update():
        _execute(f"UPDATE sessions SET {', '.join(parts)} WHERE session_id = ?", vals)

    await loop.run_in_executor(None, _update)



async def add_message(
    session_id: str,
    role: str,
    content: str,
    blocks: Optional[list] = None,
) -> None:
    """保存一条消息到历史"""
    import asyncio
    loop = asyncio.get_running_loop()
    now = _now()

    def _add():
        _execute(
            "INSERT INTO messages (session_id, role, content, blocks, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content,
             json.dumps(blocks or [], ensure_ascii=False), now),
        )

    await loop.run_in_executor(None, _add)


async def get_recent_messages(session_id: str, limit: int = 10) -> list[dict]:
    """获取最近 N 条消息（按时间正序），用于注入 LLM 上下文"""
    import asyncio
    loop = asyncio.get_running_loop()

    def _get():
        rows = _fetchall(
            "SELECT role, content, blocks, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        # 反转成正序（最早在前）
        return list(reversed(rows))

    rows = await loop.run_in_executor(None, _get)
    for r in rows:
        r["blocks"] = json.loads(r.get("blocks") or "[]")
    return rows


async def get_all_messages(session_id: str) -> list[dict]:
    """获取全部消息（用于客户端回填）"""
    import asyncio
    loop = asyncio.get_running_loop()

    def _get():
        return _fetchall(
            "SELECT role, content, blocks, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )

    rows = await loop.run_in_executor(None, _get)
    for r in rows:
        r["blocks"] = json.loads(r.get("blocks") or "[]")
    return rows


async def delete_session(session_id: str) -> None:
    """删除会话及全部关联数据"""
    import asyncio
    loop = asyncio.get_running_loop()

    def _delete():
        conn = _get_conn()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()

    await loop.run_in_executor(None, _delete)
