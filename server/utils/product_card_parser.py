"""
商品卡片解析器 — 从流式文本中提取商品卡片标记。

核心功能：
    1. [商品卡片:ID] 标记检测：快速但依赖 LLM 格式配合
    2. 商品标题匹配检测：不依赖 LLM，直接扫描输出文本中的商品名称
    3. 流式解析：支持边接收边解析，实时推送商品卡片

技术亮点：
    - 双重检测机制解决 LLM 把卡片标记堆在末尾的问题
    - 标题匹配优先按长度降序，确保长标题优先匹配
    - 自动去重，避免重复推送同一商品卡片

业界参考：
    - Perplexity AI: inline citation → card expansion
    - Claude tool_use: structured blocks interleaved in stream
"""
import re


PRODUCT_CARD_PATTERN = re.compile(r'\[商品卡片[：:]\s*([^\]]+?)\]')


def strip_product_card_markers(text: str) -> str:
    """移除文本中的商品卡片标记"""
    return PRODUCT_CARD_PATTERN.sub('', text)


class StreamCardParser:
    """
    流式文本 → 结构化 SSE 事件解析器。

    双重检测机制（解决 LLM 把卡片标记堆在末尾的问题）：
    1. [商品卡片:ID] 标记检测（快，依赖 LLM 配合）
    2. 商品标题匹配检测（可靠，不依赖 LLM 格式遵守）
    """

    def __init__(self, product_lookup: dict[str, dict] | None = None):
        """
        Args:
            product_lookup: {product_id: {title, brand, ...}} 用于标题匹配
        """
        self.buffer = ""
        self.product_lookup = product_lookup or {}
        self._emitted_by_title: set[str] = set()
        # 构建标题 → ID 映射（按标题长度降序，优先匹配长标题）
        self._title_to_id: list[tuple[str, str]] = []
        if product_lookup:
            self._title_to_id = sorted(
                [(info.get("title", ""), pid) for pid, info in product_lookup.items()],
                key=lambda x: len(x[0]),
                reverse=True,
            )

    def feed(self, chunk: str) -> list:
        """输入流式文本块，返回结构化事件列表"""
        self.buffer += chunk

        # 1. [商品卡片:ID] 标记解析（LLM 配合时生效）
        marker_events = self._emit_complete()

        # 2. 标题匹配检测（LLM 不配合时兜底）
        title_events = self._detect_title_mentions()

        # 合并：标记事件优先，标题匹配去重
        marker_ids = {e.get("product_id") for e in marker_events if e["type"] == "product_card"}
        merged = []
        for e in marker_events:
            merged.append(e)
        for e in title_events:
            if e.get("product_id") not in marker_ids:
                merged.append(e)

        return merged

    def flush(self) -> list:
        """流结束，清空缓冲区"""
        events = self._emit_complete(flush_all=True)
        # 最后一次标题匹配
        title_events = self._detect_title_mentions()
        marker_ids = {e.get("product_id") for e in events if e["type"] == "product_card"}
        for e in title_events:
            if e.get("product_id") not in marker_ids:
                events.append(e)
        # 剩余文本
        if self.buffer.strip():
            clean = strip_product_card_markers(self.buffer)
            if clean.strip():
                events.append({"type": "content", "content": clean})
        self.buffer = ""
        return events


    def _detect_title_mentions(self) -> list:
        """
        在 buffer 中检测商品标题首次出现，生成 product_card 事件。

        这是核心创新：不依赖 LLM 格式遵守，直接扫描 LLM 输出的商品名称。
        首次提到某商品 → 立即推送卡片，确保卡片紧跟在文字后面。
        """
        events = []
        for title, pid in self._title_to_id:
            if pid in self._emitted_by_title:
                continue
            if not title or len(title) < 2:
                continue
            # 精确匹配完整标题（LLM 通常输出完整商品名）
            if title in self.buffer:
                self._emitted_by_title.add(pid)
                events.append({"type": "product_card", "product_id": pid})
        return events


    def _hold_back_length(self) -> int:
        """判断需要保留多少字符（避免截断不完整的卡片标记）"""
        idx = self.buffer.rfind('[')
        if idx == -1:
            return 0
        suffix = self.buffer[idx:]

        # 如果已有完整的商品卡片标记，不保留
        if PRODUCT_CARD_PATTERN.search(suffix):
            return 0

        # 检查是否包含 '[' 但还没有闭合的 ']'
        if '[' in suffix and ']' not in suffix:
            return len(self.buffer) - idx

        # 检查是否是不完整的标记开头
        partial_markers = ('[商', '[商品', '[商品卡', '[商品卡片')
        if any(suffix.startswith(marker) for marker in partial_markers):
            return len(self.buffer) - idx
        return 0

    def _emit_complete(self, flush_all: bool = False) -> list:
        """解析 [商品卡片:ID] 标记并返回事件列表"""
        events = []

        while True:
            match = PRODUCT_CARD_PATTERN.search(self.buffer)
            if not match:
                break

            # 提取商品卡片前的文本
            text_before = self.buffer[:match.start()]
            if text_before:
                events.append({"type": "content", "content": text_before})

            # 提取商品ID并添加商品卡片事件
            product_id = match.group(1).strip()
            events.append({"type": "product_card", "product_id": product_id})
            self.buffer = self.buffer[match.end():]

        if flush_all:
            return events

        # 处理剩余的缓冲区
        hold_len = self._hold_back_length()
        if hold_len < len(self.buffer):
            safe = self.buffer[:len(self.buffer) - hold_len]
            if safe:
                events.append({"type": "content", "content": safe})
                self.buffer = self.buffer[len(safe):]

        return events
