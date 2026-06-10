"""
Scene Agent — 场景化购物方案规划。

职责：
  Step 1: 拦截 "重新规划" / "结束购物" 控制指令
  Step 2: LLM 把用户场景拆成 2-4 个购物主题（theme + query）
  Step 3: 硬校验：topic query 必须命中数据集中存在的品类
  Step 4: 保存 scene_context 到会话（session.scene_context）
  Step 5: 推送方案概述文字 + 主题选择按钮

后续流程：用户点击 "了解X" → chat.py 路由到 search_agent 正常检索出卡。
每个主题独立走 search_agent，和单品流程完全统一（包括澄清、对比）。


"""
import json
import re
from datetime import datetime
from typing import AsyncIterator

from models.events import (
    tool_progress, content as ev_content, clarification as ev_clarification,
)


# 本平台商品库实际存在的品类（来自 product_repo 加载的 100 个商品）
# 这是硬校验——topic query 必须命中其中之一才算有效，防止 LLM 规划库外商品
# 从 category_detector 导入关键词列表作为权威来源，避免两个地方分别维护
from utils.category_detector import (
    beauty_keywords, sports_keywords, fashion_keywords,
    digital_keywords, food_keywords,
)

_VALID_CATEGORY_KEYWORDS = (
    beauty_keywords + sports_keywords + fashion_keywords +
    digital_keywords + food_keywords
)


def _is_valid_topic(query: str) -> bool:
    """检查 topic query 是否对应数据集中存在的品类。"""
    return any(kw in query for kw in _VALID_CATEGORY_KEYWORDS)


# 控制指令关键词
_REPLAN_KEYWORDS = ["重新规划"]
_END_KEYWORDS = ["结束购物"]


class SceneAgent:
    """场景化购物方案规划 Agent"""

    def __init__(self, doubao_service, session_manager):
        self.doubao = doubao_service
        self.sessions = session_manager

    async def run(
        self,
        session_id: str,
        message: str,
        params: dict,
    ) -> AsyncIterator[str]:
        """
        主入口，yield SSE 事件字符串。
        """

        # ── Step 1: 控制指令拦截 ─────────────────────────
        if any(k in message for k in _END_KEYWORDS):
            session = self.sessions.get_session(session_id)
            if session:
                session.scene_context = None
            yield ev_content("好的，本次场景购物已结束，期待下次为您服务～").to_sse_compact()
            return

        if any(k in message for k in _REPLAN_KEYWORDS):
            session = self.sessions.get_session(session_id)
            if session:
                session.scene_context = None
            yield ev_content(
                "好的，已清空当前方案。请重新描述您的场景需求，比如换个时间、地点或预算～"
            ).to_sse_compact()
            return

        # ── Step 2: 告知用户在规划 ─────────────────────────
        yield tool_progress("scene_plan", "正在为您规划方案…").to_sse_compact()

        # ── Step 3: LLM 拆解场景 ───────────────────────────
        plan = await self._plan_scene(message)
        if not plan or not plan.get("topics"):
            session = self.sessions.get_session(session_id)
            if session:
                session.scene_context = None
            yield ev_content(
                "暂时没能识别您的场景需求，您可以换个表达，"
                "或直接告诉我想买的具体商品类目～"
            ).to_sse_compact()
            return

        scene_summary = plan.get("scene_summary", "").strip()
        raw_topics: list[dict] = plan.get("topics", [])[:4]

        # ── Step 4: 硬校验 topics ──────────────────────────
        topics: list[dict] = []
        seen_themes: set[str] = set()
        for t in raw_topics:
            theme = (t.get("theme") or "").strip()
            query = (t.get("query") or "").strip()
            if not theme or not query:
                continue
            if theme in seen_themes:
                continue
            if not _is_valid_topic(query):
                continue  # 库外品类直接剔除
            seen_themes.add(theme)
            topics.append({"theme": theme, "query": query})

        if not topics:
            session = self.sessions.get_session(session_id)
            if session:
                session.scene_context = None
            yield ev_content(
                "暂时没能识别出有效的主题，您可以换个表达再试试～"
            ).to_sse_compact()
            return

        # ── Step 5: 保存 scene_context 到会话 ──────────────
        scene_context = {
            "original_message": message,
            "scene_summary": scene_summary,
            "topics": topics,
            "created_at": datetime.utcnow().isoformat(),
        }
        session = self.sessions.get_session(session_id)
        if session:
            session.scene_context = scene_context

        # ── Step 6: 推送方案概述 + 主题选择按钮 ────────────
        theme_list = "、".join(f"「{t['theme']}」" for t in topics)
        intro = (
            f"已为您规划好方案：{scene_summary}\n"
            f"包含 {len(topics)} 个主题：{theme_list}\n"
            f"请选择您想先了解的主题，我会针对该主题为您推荐商品。"
        )
        yield ev_content(intro).to_sse_compact()

        options = [f"了解{t['theme']}" for t in topics] + ["重新规划"]
        yield ev_clarification(
            question="您想先了解哪个主题？",
            options=options,
        ).to_sse_compact()

    # ─────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────

    async def _plan_scene(self, message: str) -> dict | None:
        """LLM 拆解场景为主题列表（JSON Mode），返回解析后字典或 None"""
        # 构建可用品类列表
        cat_list = "、".join(_VALID_CATEGORY_KEYWORDS)

        prompt = (
            f"你是电商导购的场景规划助手。用户描述了一个生活/出行场景，"
            f"你要把它拆成 2-4 个具体购物主题，每个主题对应后续单独的商品搜索流程。\n\n"
            f"## 输出格式（严格 JSON）\n\n"
            f'{{"scene_summary": "一句话场景概述", '
            f'"topics": [{{"theme": "主题名", "query": "检索短语"}}]}}\n\n'
            f"## 本平台商品库（规划主题只能从中选择，绝不能规划库外品类）\n\n"
            f"{cat_list}\n\n"
            f"## 规则\n\n"
            f"1. topics 总数 2-4 个\n"
            f"2. 每个 query 必须包含商品库中的品类关键词\n"
            f"3. 主题之间要互补，不要重复（如'防晒'和'防晒霜'）\n"
            f"4. theme 是按钮文字，2-6 个汉字，独特、不重复\n"
            f"5. 用户消息中提到的具体品类一定要包含（前提是库内存在）\n"
            f"6. 只输出 JSON，不要任何解释文字\n\n"
            f"用户场景：{message}"
        )

        try:
            raw = await self.doubao.generate_response(prompt)
            # 提取 JSON
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if isinstance(data, dict) and isinstance(data.get("topics"), list):
                    return data
        except Exception as e:
            print(f"[scene_agent] _plan_scene 失败: {e}")

        return None


scene_agent = SceneAgent(None, None)  # 占位，启动时注入
