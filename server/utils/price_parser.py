"""
价格解析器 — 从用户自然语言查询中提取价格范围约束。

支持的价格表达方式：
    - "X元以内" / "X元以下" → (0, X)
    - "X元以上" → (X, +∞)
    - "X到Y元" / "X-Y元" → (X, Y)
    - "预算X元" → (0, X)
    - "不超过X元" → (0, X)

返回格式：(min_price, max_price)，无法解析时返回 None
"""
import re
from typing import Optional, Tuple


def detect_price_range(query: str) -> Optional[Tuple[int, int]]:
    """从用户查询中解析价格范围"""
    query_lower = query.lower()
    
    # 匹配 "X元以内" 或 "X元以下" 或 "X以内" 或 "X以下"
    match = re.search(r'(\d+)\s*(元\s*)?(以内|以下)', query_lower)
    if match:
        return (0, int(match.group(1)))
    
    # 匹配 "X元以上"
    match = re.search(r'(\d+)\s*元\s*(以上)', query_lower)
    if match:
        return (int(match.group(1)), float('inf'))
    
    # 匹配 "X到Y元" 或 "X-Y元"
    match = re.search(r'(\d+)\s*[到-]\s*(\d+)\s*元', query_lower)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    
    # 匹配 "预算X元"
    match = re.search(r'预算\s*(\d+)\s*元?', query_lower)
    if match:
        return (0, int(match.group(1)))
    
    # 匹配 "不超过X元"
    match = re.search(r'不超过\s*(\d+)\s*元?', query_lower)
    if match:
        return (0, int(match.group(1)))
    
    return None
