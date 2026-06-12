"""
中文指代消解器 — 将"第一个"/"这款"/"它"等自然语言指代转换为具体商品 ID。

痛点场景：
    用户说"把第一个加购物车"时，LLM 可能返回 "1"、"第一个" 或编造 "P001" 等不存在的 ID。
    需要在代码层做三次纠正尝试：
        第一层：扫描用户原始消息中的位置词（"第一""第二"等）
        第二层：处理 LLM 返回的数字或位置词
        第三层：验证 ID 有效性，查不到时回退到最近展示的第一个商品
"""

import re
from typing import Optional

# 中文位置词 → 排名映射（1-based）
_POSITION_WORDS: dict[str, int] = {
    "第一": 1, "第一个": 1, "第一款": 1, "第1个": 1, "第1款": 1,
    "第二": 2, "第二个": 2, "第二款": 2, "第2个": 2, "第2款": 2,
    "第三": 3, "第三个": 3, "第三款": 3, "第3个": 3, "第3款": 3,
    "第四": 4, "第四个": 4, "第四款": 4, "第4个": 4, "第4款": 4,
    "第五": 5, "第五个": 5, "第五款": 5, "第5个": 5, "第5款": 5,
}

# 模糊指代词（指代"当前正在看的那款"）→ 默认第一个
_VAGUE_REF_WORDS = [
    "这款", "这个", "这件", "这条", "这双", "这瓶", "这盒", "这套",
    "那款", "那个", "那件", "那条", "那双", "那瓶", "那盒", "那套",
    "它", "上面那款", "刚才那款", "前面那款",
]

def resolve_product_id(
    product_id: Optional[str],
    last_shown: list[dict],
    user_message: str = "",
) -> Optional[str]:
    """
    解析位置指代 → 真实 product_id。

    Args:
        product_id: LLM/规则给出的 product_id（可能是位置词、数字、或幻觉 id）
        last_shown: 上一轮展示的商品列表 [{"product_id": "...", "title": "..."}, ...]
        user_message: 用户原始消息（用于直接扫描位置词）

    Returns:
        解析后的 product_id，无法解析则返回 None
    """
    if not last_shown:
        return product_id  # 没有上下文，原样返回

    valid_ids = {p.get("product_id") for p in last_shown if p.get("product_id")}
    pos: Optional[int] = None

    for word, p in _POSITION_WORDS.items():
        if word in user_message:
            pos = p
            break

    # 模糊指代（"这款"/"它"）→ 默认第一个
    if pos is None and any(w in user_message for w in _VAGUE_REF_WORDS):
        pos = 1

    pid = product_id
    if pos is None and pid and isinstance(pid, str):
        if pid.isdigit():
            pos = int(pid)
        elif pid in _POSITION_WORDS:
            pos = _POSITION_WORDS[pid]

    if pos is not None and 1 <= pos <= len(last_shown):
        return last_shown[pos - 1].get("product_id", product_id)

    if pid and isinstance(pid, str) and pid not in valid_ids:
        # 有模糊指代 → 取第一个
        if any(w in user_message for w in _VAGUE_REF_WORDS) and last_shown:
            return last_shown[0].get("product_id", pid)

    return product_id


def extract_position_from_message(message: str) -> Optional[int]:
    """从用户消息中提取位置序号。返回 1-based 序号或 None。

    >>> extract_position_from_message("第一个")
    1
    >>> extract_position_from_message("对比第二款和第三款")
    2
    >>> extract_position_from_message("第2件")
    2
    >>> extract_position_from_message("第3台")
    3
    """
    # 正则匹配：第 + 数字 + 可选量词（兼容"第2件""第3个""第1款"等任意量词）
    m = re.search(r'第\s*(\d+)\s*[件个款台把瓶包盒箱袋支罐]?', message)
    if m:
        return int(m.group(1))
    # 中文数字：第一 / 第二 ...
    m = re.search(r'第\s*([一二三四五六七八九十])\s*[件个款]?', message)
    if m:
        chinese = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                   '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
        return chinese.get(m.group(1))
    # 回退到静态字典（兼容"最后一个""倒数第一个"等特殊表述）
    for word, pos in sorted(_POSITION_WORDS.items(), key=lambda x: -len(x[0])):
        if word in message:
            return pos
    return None


def has_product_reference(message: str) -> bool:
    """检查消息是否包含对已展示商品的指代。

    >>> has_product_reference("第一个")
    True
    >>> has_product_reference("这款怎么样")
    True
    >>> has_product_reference("第2件")
    True
    >>> has_product_reference("推荐防晒")
    False
    """
    if re.search(r'第\s*[一二三四五六七八九十\d]', message):
        return True
    if any(w in message for w in _POSITION_WORDS):
        return True
    if any(w in message for w in _VAGUE_REF_WORDS):
        return True
    return False
