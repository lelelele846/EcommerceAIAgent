"""
商品发现引擎 — 处理单品查找请求，通过渐进式维度确认实现精准推荐。

执行链路：
  1. 收集结构化查询条件（会话级持久化）
  2. 逐轮更新查询参数（单值覆盖 / 多值追加）
  3. 完整重新检索（非增量筛选）
  4. 候选超过3个且需求不清晰时，按品类特征维度主动询问
  5. 用户指定品牌或要求直接展示时，立即呈现结果
"""
import json
from typing import AsyncIterator, Optional

from models.events import (
    tool_progress, content as ev_content, product_card_compact,
    clarification as ev_clarification, image_searching, end as ev_end,
)
from rag.hyde import hyde_generator
from rag.query_decomposer import query_decomposer
from rag.relevance_checker import relevance_checker
from rag.product_graph import product_graph as _product_graph



# 品类 → 关键维度清单
_CATEGORY_SLOTS: dict[str, list[dict]] = {
    "美妆护肤": [
        {"name": "肤质", "kind": "attr", "question": "您的肤质偏向哪种呢？", "options": ["干皮", "油皮", "敏感肌", "混合性"]},
        {"name": "功效", "kind": "attr", "question": "您更看重哪种功效？", "options": ["保湿补水", "美白提亮", "抗老紧致", "修护屏障"]},
        {"name": "预算", "kind": "budget", "question": "预算大概在什么范围？", "options": []},
    ],
    "服饰运动": [
        {"name": "场景", "kind": "attr", "question": "主要在什么场景穿/用呢？", "options": ["跑步", "篮球", "徒步户外", "日常通勤"]},
        {"name": "偏好", "kind": "attr", "question": "更看重哪一点？", "options": ["轻量", "缓震", "防水透气", "百搭"]},
        {"name": "预算", "kind": "budget", "question": "预算大概在什么范围？", "options": []},
    ],
    "数码电子": [
        {"name": "用途", "kind": "attr", "question": "主要用来做什么呢？", "options": ["办公商务", "游戏性能", "学生学习", "影音娱乐"]},
        {"name": "偏好", "kind": "attr", "question": "更看重哪一点？", "options": ["轻薄便携", "长续航", "大屏", "高性能"]},
        {"name": "预算", "kind": "budget", "question": "预算大概在什么范围？", "options": []},
    ],
    "食品饮料": [
        {"name": "偏好", "kind": "attr", "question": "有什么口味/健康偏好吗？", "options": ["无糖低卡", "高蛋白", "整箱囤货", "尝鲜体验"]},
        {"name": "预算", "kind": "budget", "question": "预算大概在什么范围？", "options": []},
    ],
}


# Slot 名称 → session preference 键名（避免 _next_slot 和 _session_prefs_cover_key_slots 重复定义）
_SLOT_TO_PREFS_KEY: dict[str, str | tuple[str, ...]] = {
    "肤质": "skin_type",
    "功效": "skin_concerns",
    "场景": "sport_type",
    "偏好": ("key_features", "style"),
    "用途": "device_type",
}


def _slot_covered_by_session_prefs(slot_name: str, session_prefs: dict) -> bool:
    """检查 session 偏好是否已覆盖指定 slot，避免重复追问。"""
    if not session_prefs or slot_name not in _SLOT_TO_PREFS_KEY:
        return False
    key = _SLOT_TO_PREFS_KEY[slot_name]
    if isinstance(key, tuple):
        return any(session_prefs.get(k) for k in key)
    return bool(session_prefs.get(key))


CATEGORY_NAME_ALIASES = frozenset({
    "数码", "数码产品", "数码电子", "电子产品",
    "美妆", "美妆护肤", "护肤品", "化妆品",
    "服饰", "服饰运动", "运动", "运动户外", "鞋服", "穿搭",
    "食品", "食品饮料", "零食", "饮料",
    "家居", "家居生活", "家电", "家用电器",
    "母婴", "母婴用品",
    "图书", "图书文具",
})

_CATEGORY_ALIAS_TO_CATEGORY: dict[str, str] = {
    "数码": "数码电子", "数码产品": "数码电子", "数码电子": "数码电子", "电子产品": "数码电子",
    "美妆": "美妆护肤", "美妆护肤": "美妆护肤", "护肤品": "美妆护肤", "化妆品": "美妆护肤",
    "服饰": "服饰运动", "服饰运动": "服饰运动", "运动": "服饰运动", "运动户外": "服饰运动",
    "鞋服": "服饰运动", "穿搭": "服饰运动",
    "食品": "食品饮料", "食品饮料": "食品饮料", "零食": "食品饮料", "饮料": "食品饮料",
    "家居": "家居生活", "家居生活": "家居生活",
    "家电": "家用电器", "家用电器": "家用电器",
    "母婴": "母婴用品", "母婴用品": "母婴用品",
    "图书": "图书文具", "图书文具": "图书文具",
}


class SearchAgent:
    """单品发现引擎：查询 + 渐进式维度确认 + 结果展示"""

    def __init__(self, retriever, doubao_service, session_manager):
        self.retriever = retriever
        self.doubao = doubao_service
        self.sessions = session_manager

    async def run(
        self,
        session_id: str,
        query: str,
        category: str | None,
        original_category: str | None,
        price_range: tuple | None,
        preferred_brands: list[str] | None,
        disliked_brands: list[str] | None,
        extracted_prefs: dict,
        is_clarifying_response: bool,
        user_wants_show_now: bool,
        interaction_count: int,
        intent_chain: list[dict],
        base_url: str = "",
        search_query: str | None = None,  # 🆕 用于检索的有效 query（可能与用户原话不同）
        last_shown: list[dict] | None = None,  # 🆕 上一轮展示的商品列表
    ) -> AsyncIterator[str]:
        """
        主入口，yield SSE 事件字符串。

        🆕 search_query: 如果用户 query 只是约束（如"200以内"），
        会用 last_shown 重建有效搜索词；否则与 query 相同。
        🆕 last_shown: 上一轮展示的商品，注入 prompt 帮助 LLM 理解上下文。
        """

        effective_q = search_query or query
        hyde_text = None
        direct_category = None
        if effective_q.strip() in CATEGORY_NAME_ALIASES:
            direct_category = _CATEGORY_ALIAS_TO_CATEGORY.get(effective_q.strip())
            print(f"[search_agent] 纯类目名 '{effective_q}' → 跳过 HyDE，直接按 {direct_category} 检索", flush=True)
            effective_q = f"{direct_category}类商品"  # 用类目名做检索词

        if direct_category is None and hyde_generator.should_use_hyde(effective_q):
            hyde_generator.set_service(self.doubao)
            hyde_text = await hyde_generator.generate(effective_q)
            if hyde_text:
                print(f"[search_agent] HyDE 已激活: {hyde_text[:60]}...")

        query_decomposer.set_service(self.doubao)
        if query_decomposer.should_decompose(effective_q):
            decomposed = await query_decomposer.decompose(effective_q)
            if len(decomposed) >= 2:
                sub_queries = decomposed
                # 将 HyDE 文本注入第一个子查询，避免浪费已生成的假设文档
                if hyde_text:
                    sub_queries[0] = f"{sub_queries[0]} {hyde_text}"
                print(f"[search_agent] Query 分解: {effective_q} → {sub_queries}")
            else:
                sub_queries = [f"{effective_q} {hyde_text}" if hyde_text else effective_q]
        else:
            sub_queries = [f"{effective_q} {hyde_text}" if hyde_text else effective_q]

        yield tool_progress("hybrid_search", "正在为您检索商品...").to_sse_compact()

        try:
            all_products = []
            seen_ids = set()
            # 获取 session 偏好用于多维 boost
            session_prefs = {}
            if session_id:
                sess = self.sessions.get_session(session_id)
                if sess and hasattr(sess, 'preferences'):
                    session_prefs = sess.preferences.dict()

            for sq in sub_queries:
                # 多子查询（可能跨类目，如"从防晒到穿搭"）时不限制类目过滤
                cat_filter = (direct_category or original_category or category) if len(sub_queries) <= 1 else None
                batch = self.retriever.search(
                    sq,
                    top_k=max(5, 8 // len(sub_queries)),
                    category_filter=cat_filter,
                    price_range=price_range,
                    preferred_brands=preferred_brands,
                    disliked_brands=disliked_brands,
                    preferences=session_prefs,
                )
                for p in batch:
                    if p.id not in seen_ids:
                        seen_ids.add(p.id)
                        all_products.append(p)
            products = all_products[:8] if all_products else []
        except Exception as e:
            print(f"[search_agent] 检索异常: {e}")
            yield ev_content("抱歉，搜索时遇到了问题，请稍后重试。").to_sse_compact()
            return

        if not products:
            # 无结果时尝试放宽条件重搜
            if original_category or category:
                print(f"[search_agent] 无结果，去掉类目过滤重搜...")
                yield tool_progress("retry_search", "放宽条件重新搜索...").to_sse_compact()
                retry_products = self.retriever.search(
                    effective_q, top_k=8, category_filter=None,
                    price_range=price_range,
                    preferred_brands=preferred_brands,
                    disliked_brands=disliked_brands,
                    preferences=session_prefs,
                )
                if retry_products:
                    products = retry_products

            # 🔧 终极兜底：向量+BM25 都没找到 → 直接用标题子串匹配
            # MiniLM 对短中文查询（"遮阳帽""防晒霜"）的 embedding 质量差，绕过向量直接扫标题
            if not products:
                from utils.product_repo import product_repo
                name_matches = product_repo.search_by_name(effective_q, limit=8)
                if name_matches:
                    # 应用价格过滤
                    if price_range:
                        name_matches = [
                            p for p in name_matches
                            if price_range[0] <= p.base_price <= price_range[1]
                        ]
                    if name_matches:
                        print(f"[search_agent] fallback name search: '{effective_q}' → {len(name_matches)} results")
                        products = name_matches

            if not products:
                yield ev_content(
                    "抱歉，暂时没有找到符合您需求的商品。可以换个关键词试试，或者告诉我您想要什么类型的商品～"
                ).to_sse_compact()
                return

        if len(products) > 3:
            relevance_checker.set_service(self.doubao)
            relevant, _ = await relevance_checker.check(query, products, min_keep=3)
            if len(relevant) < len(products):
                products = relevant
                # 过滤后太少 → 重搜
                if len(products) < 3 and (original_category or category):
                    print(f"[search_agent] 相关性过滤后仅 {len(products)} 个，放宽重搜...")
                    retry_products = self.retriever.search(
                        effective_q, top_k=8, category_filter=None,
                        price_range=price_range,
                        preferred_brands=preferred_brands,
                        disliked_brands=disliked_brands,
                        preferences=session_prefs,
                    )
                    seen = {p.id for p in products}
                    for p in retry_products:
                        if p.id not in seen:
                            seen.add(p.id)
                            products.append(p)
                    products = products[:8]

        if len(products) > 5:
            yield tool_progress("llm_judge", "正在筛选最匹配的商品...").to_sse_compact()
            selected_ids = await self._judge(query, products, top_k=5)
            if selected_ids:
                id_order = {pid: i for i, pid in enumerate(selected_ids)}
                products = sorted(
                    [p for p in products if p.id in id_order],
                    key=lambda p: id_order[p.id]
                )

        has_brand = preferred_brands or extracted_prefs.get('preferred_brands')
        has_asked_before = len(intent_chain) >= 2 and any(
            i.get('type') == 'clarifying' for i in intent_chain[-3:]
        )
        # 检查是否已有明确的品类属性（如肤质、风格等），避免重复追问
        session_prefs_cover_slots = self._session_prefs_cover_key_slots(session_prefs, original_category or category or "")

        # 只有 0 个商品时才不出卡
        slot_to_ask = None
        if len(products) > 3 and not has_brand and not has_asked_before and not user_wants_show_now and not session_prefs_cover_slots:
            slot_to_ask = self._next_slot(
                original_category or category or "",
                [],
                {"want_attrs": extracted_prefs.get('key_features', []),
                 "price_max": price_range[1] if price_range else None,
                 "price_min": price_range[0] if price_range else None},
                products,
                session_prefs,
            )

        # 先展示商品
        async for event_str in self._recommend(
            session_id, query, products, original_category, category,
            price_range, preferred_brands, extracted_prefs,
            is_clarifying_response, interaction_count, base_url,
            last_shown=last_shown,
        ):
            yield event_str

        # 商品展示后再追问（最多一次）
        if slot_to_ask:
            options = slot_to_ask["options"]
            yield ev_clarification(question=slot_to_ask["question"], options=options).to_sse_compact()
            self.sessions.add_intent(session_id, "clarifying",
                                     {"category": original_category, "slot": slot_to_ask["name"]})

    # 私有方法

    def _session_prefs_cover_key_slots(self, session_prefs: dict, category: str) -> bool:
        """检查 session 偏好是否已覆盖该品类的关键 slot，避免重复追问。

        例如：session 中已有 skin_type="干性"，美妆护肤品类就不再问"肤质"。
        """
        if not session_prefs or not category:
            return False
        main_cat = self._get_main_cat(category) or category
        slots = _CATEGORY_SLOTS.get(main_cat, [])
        if not slots:
            return False
        covered = True
        for slot in slots:
            if slot["kind"] == "attr":
                if _slot_covered_by_session_prefs(slot["name"], session_prefs):
                    continue
                covered = False
                break
            elif slot["kind"] == "budget":
                price = session_prefs.get("price_range", (0, float('inf')))
                if price[0] > 0 or price[1] < float('inf'):
                    continue
                covered = False
                break
        return covered

    async def _judge(self, query: str, candidates: list, top_k: int = 5) -> list[str]:
        """LLM Judge 从候选中精选最匹配的商品"""
        if len(candidates) <= top_k:
            return [p.id for p in candidates]

        lines = []
        for i, p in enumerate(candidates):
            title = getattr(p, 'title', '')
            brand = getattr(p, 'brand', '')
            price = getattr(p, 'base_price', 0)
            lines.append(f"- [#{i + 1}] id={p.id} 《{title}》 品牌:{brand} 价格:¥{price:.0f}")

        judge_prompt = (
            f"用户需求：{query}\n\n候选商品：\n" + "\n".join(lines) +
            f"\n\n从候选中选出最适合用户的 {top_k} 个商品（即使不完全匹配也要选，宁可选最接近的也不要空着），只输出 JSON：{{\"selected_ids\": [\"id1\", \"id2\", ...]}}"
        )

        try:
            raw = await self.doubao.generate_response(judge_prompt)
            import re as _re
            match = _re.search(r'\{[^{}]*"selected_ids"[^{}]*\}', raw)
            if match:
                data = json.loads(match.group())
                selected = data.get("selected_ids", [])
                valid = {p.id for p in candidates}
                return [pid for pid in selected if pid in valid]
        except Exception as e:
            print(f"[judge] 失败，降级 top-{top_k}: {e}")

        return [p.id for p in candidates[:top_k]]

    def _next_slot(self, category: str, asked_slots: list[str],
                   search_state: dict, products: list, session_prefs: dict | None = None) -> dict | None:
        """获取下一个需要追问的维度（会检查 session 偏好避免重复问）"""
        main_cat = self._get_main_cat(category) or category
        slots = _CATEGORY_SLOTS.get(main_cat, [])
        if not slots:
            return None

        asked = set(asked_slots)
        want_attrs = set(search_state.get("want_attrs", []))
        prefs = session_prefs or {}

        for slot in slots:
            if slot["name"] in asked:
                continue
            kind = slot["kind"]

            # 检查 session 偏好是否已覆盖此 slot，避免重复追问
            if kind == "attr":
                if _slot_covered_by_session_prefs(slot["name"], prefs):
                    continue

                if want_attrs & set(slot["options"]):
                    continue
                present = []
                for opt in slot["options"]:
                    for p in products:
                        text = p.title + " "
                        if hasattr(p, 'rag_knowledge') and p.rag_knowledge.marketing_description:
                            text += p.rag_knowledge.marketing_description
                        if opt in text:
                            present.append(opt)
                            break
                if len(present) >= 2:
                    return {"name": slot["name"], "kind": "attr",
                            "question": slot["question"], "options": present}

            elif kind == "budget":
                price_range = prefs.get("price_range", (0, float('inf')))
                if search_state.get("price_max") or search_state.get("price_min") or price_range[0] > 0:
                    continue
                prices = sorted([p.base_price for p in products if p.base_price > 0])
                if len(prices) >= 3:
                    t1 = int(prices[len(prices) // 3])
                    t2 = int(prices[(2 * len(prices)) // 3])
                    if t2 > t1:
                        return {"name": "预算", "kind": "budget",
                                "question": slot["question"],
                                "options": [f"{t1}元以内", f"{t1}-{t2}元", f"{t2}元以上"]}

        return None

    def _get_main_cat(self, sub_category: str) -> str:
        """子类目 → 主类目映射"""
        for p in self.retriever.products:
            if p.sub_category == sub_category:
                return p.category
        return sub_category

    async def _recommend(
        self,
        session_id: str,
        query: str,
        products: list,
        original_category: str | None,
        category: str | None,
        price_range: tuple | None,
        preferred_brands: list[str] | None,
        extracted_prefs: dict,
        is_clarifying_response: bool,
        interaction_count: int,
        base_url: str = "",
        last_shown: list[dict] | None = None,  # 🆕 上一轮展示的商品
    ) -> AsyncIterator[str]:
        """出卡：构建 prompt + 流式生成 + 推送商品卡片"""
        import re
        from rag.prompt import build_prompt
        from utils.product_card_parser import PRODUCT_CARD_PATTERN, strip_product_card_markers, StreamCardParser

        # 构建 prompt query
        prompt_query = query
        # 🔧 纯类目名查询 → 改写为推荐格式，避免 LLM 说"没有这个品类"
        if not is_clarifying_response and query.strip() in CATEGORY_NAME_ALIASES:
            cat_name = _CATEGORY_ALIAS_TO_CATEGORY.get(query.strip(), query.strip())
            prompt_query = f"帮我推荐{cat_name}类商品"

        if is_clarifying_response:
            cat = original_category or category or ""
            price_info = ""
            if price_range and price_range[1] != float('inf'):
                price_info = f"，预算{int(price_range[1])}元以内"
            feat_info = ""
            if extracted_prefs.get('key_features'):
                feat_info = "，偏好" + "、".join(extracted_prefs['key_features'])
            brand_info = f"，品牌{'、'.join(preferred_brands)}" if preferred_brands else ""
            prompt_query = f"帮我推荐{cat}商品{price_info}{feat_info}{brand_info}（用户原话：{query}）"
            if interaction_count > 1:
                prompt_query += "\n\n【⚠️最高优先级】你上一轮已经问过用户了，用户已经回答了。现在必须直接推荐商品，不要再反问！"
        else:
            yn_match = re.match(r'有(.+?)吗[？?]?$', query)
            if yn_match:
                prompt_query = f"帮我推荐{yn_match.group(1).strip()}（用户原话：{query}）"
            elif re.match(r'(有没有|是否有|还有)(.+?)[吗?？]*$', query):
                target = re.sub(r'(有没有|是否有|还有)', '', query).strip().rstrip('吗?？')
                prompt_query = f"帮我推荐{target}（用户原话：{query}）"

        session = self.sessions.get_session(session_id)
        session_dict = session.dict() if session else {}
        # 🆕 把最近对话历史传给 build_prompt，让 LLM 知道"刚才聊了什么"
        conversation_history = session_dict.get('messages', [])
        prompt_context = {
            'original_category': original_category,
            'interaction_count': interaction_count,
            'session': session_dict,
            'conversation_history': conversation_history,
            'last_shown_products': last_shown or session_dict.get('last_shown_products', []),
            'price_range': price_range,
            'preferred_brands': preferred_brands,
            '_user_query': query,  # 🆕 原始用户消息，供 prompt 上下文衔接使用
        }
        prompt = build_prompt(prompt_query, products, prompt_context)

        # 商品字典
        products_dict = self._products_to_dict(products, base_url)
        product_lookup = {p['id']: p for p in products_dict}

        yield ev_content("").to_sse_compact()  # trigger start

        response_content = ""
        buffered_text_for_guard: list[str] = []   # 🔧 累积文本用于反问检测，但实时流式输出
        streamed_card_ids: set[str] = set()        # 🔧 已流式输出的卡片 ID
        stream_parser = StreamCardParser(product_lookup=product_lookup)

        _CLARIFY_PATTERNS = [
            "你想了解哪", "你想看哪", "你想要哪", "哪一品类", "哪一类",
            "你想找哪", "需要了解", "能说具体", "能具体", "可以具体",
            "想了解什么", "想看什么", "需要什么", "有什么需求",
            "我帮您看看", "我帮你看看",
        ]

        def _check_clarify(text: str) -> bool:
            return any(p in text for p in _CLARIFY_PATTERNS) and len(text) < 80

        try:
            async for chunk in self.doubao.stream_response(prompt):
                response_content += chunk
                for event in stream_parser.feed(chunk):
                    if event["type"] == "content":
                        buffered_text_for_guard.append(event['content'])
                        yield ev_content(event['content']).to_sse_compact()  # 🔧 实时流式输出文字
                    elif event["type"] == "product_card":
                        pid = event["product_id"]
                        prod = product_lookup.get(pid)
                        if prod:
                            streamed_card_ids.add(pid)
                            yield product_card_compact(pid, prod).to_sse_compact()  # 🔧 卡片紧跟文字

            for event in stream_parser.flush():
                if event["type"] == "content":
                    buffered_text_for_guard.append(event['content'])
                    yield ev_content(event['content']).to_sse_compact()
                elif event["type"] == "product_card":
                    pid = event["product_id"]
                    prod = product_lookup.get(pid)
                    if prod:
                        streamed_card_ids.add(pid)
                        yield product_card_compact(pid, prod).to_sse_compact()

            # 🔧 反问/追问检测（后置）：仅在 0 张卡片已发送时生效
            # 有卡片 → LLM 确实在推荐，不是反问；无卡片 → 可能是反问，需替换
            full_text = "".join(buffered_text_for_guard).strip()
            if _check_clarify(full_text) and products and not streamed_card_ids:
                print(f"[search_agent] ⚠️ 检测到反问回复（0 cards），替换为推荐开场: '{full_text[:60]}'", flush=True)
                cat_label = original_category or category or "商品"
                product_names = "、".join(p.get('name', '')[:12] for p in products_dict[:4])
                corrected_intro = f"帮你找了几款{cat_label}～{product_names}，看看有没有喜欢的！"
                yield ev_content("\n" + corrected_intro).to_sse_compact()
                # 🔧 兜底：LLM 没标卡片时，手动推送所有商品
                for p in products:
                    pd_ = product_lookup.get(p.id)
                    if pd_:
                        streamed_card_ids.add(p.id)
                        yield product_card_compact(p.id, pd_).to_sse_compact()

        except Exception as e:
            print(f"[search_agent] 流式失败: {e}")
            if response_content:
                yield ev_content(strip_product_card_markers(response_content)).to_sse_compact()

        # 保存到内存
        clean_content = strip_product_card_markers(response_content)
        self.sessions.update_session(session_id, "assistant", clean_content)

        # 🆕 持久化到 DB（异步，不阻塞流式响应）
        try:
            import asyncio as _asyncio
            from db import relational as _db
            _asyncio.create_task(_db.add_message(session_id, "assistant", clean_content))
        except Exception as e:
            print(f"[db] 保存助手消息失败（非致命）: {e}")

        # 兜底卡片：推送所有未被 LLM 通过标记展示的商品（跳过已流式发送的）
        recommended_ids = [pid.strip() for pid in PRODUCT_CARD_PATTERN.findall(response_content)]
        recommended_set = set(recommended_ids) | streamed_card_ids
        for p in products:
            if p.id not in recommended_set:
                pd_ = product_lookup.get(p.id)
                if pd_:
                    yield product_card_compact(p.id, pd_).to_sse_compact()
                    recommended_set.add(p.id)

        if recommended_set:
            try:
                related = _product_graph.get_related_products(
                    list(recommended_set), self.retriever, limit=2
                )
                if related:
                    yield ev_content("\n💡 **你可能还需要：**\n").to_sse_compact()
                    for r in related:
                        rp = r["product"]
                        pd_ = rp.to_dict(base_url=base_url) if hasattr(rp, 'to_dict') else {"id": rp.id, "name": rp.title}
                        yield ev_content(f"• {r['reason']}：").to_sse_compact()
                        yield product_card_compact(pd_.get('id', rp.id), pd_).to_sse_compact()
            except Exception as e:
                print(f"[search_agent] 关联推荐失败: {e}")

    def _products_to_dict(self, products: list, base_url: str = "") -> list[dict]:
        """商品对象 → 字典列表（内联实现，避免循环导入）"""
        import os
        result = []
        for p in products:
            try:
                if hasattr(p, 'to_dict'):
                    result.append(p.to_dict(base_url=base_url))
                else:
                    result.append({
                        "id": getattr(p, 'id', ''),
                        "name": getattr(p, 'title', ''),
                        "brand": getattr(p, 'brand', ''),
                        "category": getattr(p, 'category', ''),
                        "price": getattr(p, 'base_price', 0),
                        "image_url": "",
                    })
            except Exception:
                pass
        return result


search_agent = SearchAgent(None, None, None)  # 占位，启动时注入
