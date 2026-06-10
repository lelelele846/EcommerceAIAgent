"""
Compare Agent — 多商品对比（五步法）。

流程：
  Step 1: 商品识别 — 从消息/params/session 解析商品名 → search_by_name 查找
  Step 2: 维度提取 — LLM（JSON Mode）从商品描述中抽取可对比属性
  Step 3: 表格组装 — 推送 comparison_table（数据来自 product_repo，不靠模型编）
  Step 4: 对比文案 — 流式生成自然语言对比分析（核心：用户可读的对比内容）

关键设计：价格/品牌/标题等硬数据全从商品对象取，LLM 只负责抽取维度
和推荐理由，不生成结构化数据——杜绝编造价格/规格。
"""
import json
import re
from typing import AsyncIterator

from models.events import (
    tool_progress, content as ev_content, comparison_table,
    product_card_compact,
)
from utils.product_card_parser import StreamCardParser


class CompareAgent:
    """多商品对比 Agent"""

    def __init__(self, retriever, doubao_service, session_manager):
        self.retriever = retriever
        self.doubao = doubao_service
        self.sessions = session_manager

    async def run(
        self,
        session_id: str,
        query: str,
        params: dict,
        base_url: str = "",
    ) -> AsyncIterator[str]:
        yield tool_progress("compare", "正在生成对比分析...").to_sse_compact()

        # ── Step 1: 商品识别 ─────────────────────────────
        product_ids = await self._resolve_products(session_id, query, params)

        if len(product_ids) < 2:
            yield ev_content(
                "请告诉我您想对比哪几款商品，例如：对比这几款面霜哪个更好。"
            ).to_sse_compact()
            return

        # 从 product_repo 获取完整 Product 对象（get_product_by_id 返回 dict，不适用）
        from utils.product_repo import product_repo
        products = []
        for pid in product_ids:
            p = product_repo.get(pid)
            if p:
                products.append(p)
            else:
                # 回退：从 retriever.products 列表中查找
                found = [pr for pr in self.retriever.products if pr.id == pid]
                if found:
                    products.append(found[0])

        if len(products) < 2:
            yield ev_content("抱歉，未能找到足够商品进行对比，请确认商品名称后重试。").to_sse_compact()
            return

        products = products[:5]  # 最多 5 款

        # ── Step 2: 构建结构化数据 + LLM 资料上下文 ──────
        _CN = ["第一款", "第二款", "第三款", "第四款", "第五款"]
        table_products: list[dict] = []
        price_values: list[str] = []
        context_blocks: list[str] = []

        for i, p in enumerate(products):
            min_price = min(
                (s.price for s in p.skus if s.price > 0),
                default=p.base_price,
            )
            table_products.append({
                "product_id": p.id,
                "title": p.title,
                "price": min_price,
                "image_url": self._image_url(p),
            })
            price_values.append(f"¥{min_price:.0f}")

            # SKU 属性（前 3 个）
            props_text = ""
            if p.skus:
                first_sku = p.skus[0]
                props = list(first_sku.properties.items())[:3]
                props_text = "；".join(f"{k}:{v}" for k, v in props)

            # 营销描述（截前 300 字）
            desc = ""
            if p.rag_knowledge and p.rag_knowledge.marketing_description:
                desc = p.rag_knowledge.marketing_description[:300]

            context_blocks.append(
                f"【{_CN[i]}】{p.brand} {p.title}\n"
                f"价格：¥{min_price:.0f}\n"
                f"规格：{props_text or '—'}\n"
                f"简介：{desc or '—'}"
            )

        context = "\n\n".join(context_blocks)

        # ── Step 3: LLM 维度提取 + 推送对比表 ────────────
        yield tool_progress("compare_table", "正在分析各维度差异，生成对比表…").to_sse_compact()

        dimensions, recommendation = await self._extract_table(
            products=products,
            context=context,
            query=query,
            table_products=table_products,
        )
        # 价格维度由系统补（保证准确，不依赖 LLM）
        dimensions = [{"name": "价格", "values": price_values}] + dimensions

        yield comparison_table(
            products=table_products,
            dimensions=dimensions,
            recommendation=recommendation,
        ).to_sse_compact()

        # ── Step 4: 流式生成对比文案（Natual Language）────
        # 关键：comparison_table 是结构化数据，但用户需要读到
        # 自然语言的对比分析，否则只有两张商品卡 + 一个表格，
        # 体验上"没有任何对比的话"。
        yield tool_progress("compare_text", "正在为您撰写对比分析…").to_sse_compact()

        # 构建商品字典（供 StreamCardParser 按 ID 查找完整数据）
        products_dict: dict[str, dict] = {}
        for p in products:
            pd = p.to_dict(base_url=base_url) if hasattr(p, 'to_dict') else {}
            products_dict[p.id] = pd

        comparison_text_prompt = self._build_comparison_text_prompt(
            products=products,
            context=context,
            query=query,
        )

        stream_parser = StreamCardParser(product_lookup=products_dict)
        response_content = ""
        shown_card_ids: set[str] = set()

        try:
            async for chunk in self.doubao.stream_response(comparison_text_prompt):
                response_content += chunk
                for event in stream_parser.feed(chunk):
                    if event["type"] == "content":
                        yield ev_content(event["content"]).to_sse_compact()
                    elif event["type"] == "product_card":
                        pid = event["product_id"]
                        prod = products_dict.get(pid)
                        if prod:
                            shown_card_ids.add(pid)
                            yield product_card_compact(pid, prod).to_sse_compact()

            for event in stream_parser.flush():
                if event["type"] == "content":
                    yield ev_content(event["content"]).to_sse_compact()
                elif event["type"] == "product_card":
                    pid = event["product_id"]
                    prod = products_dict.get(pid)
                    if prod:
                        shown_card_ids.add(pid)
                        yield product_card_compact(pid, prod).to_sse_compact()
        except Exception as e:
            print(f"[compare_agent] 流式对比文案失败: {e}")
            yield ev_content("对比分析生成失败，请查看下方的对比信息。").to_sse_compact()

        # ── Step 4b: 兜底 — 流式中未展示的卡片补推 ──────
        for p in products:
            if p.id not in shown_card_ids:
                pd_ = products_dict.get(p.id, {})
                yield product_card_compact(p.id, pd_).to_sse_compact()

    # ─────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────

    async def _resolve_products(
        self,
        session_id: str,
        query: str,
        params: dict,
    ) -> list[str]:
        """
        把用户提到的商品名/指代解析成 product_id 列表。
        优先级：
          1. params 里已有 product_ids（上游直接解析好了）
          2. 从 query 中提取商品名 → search_by_name 搜索
          3. 最近展示的商品（用户说"对比这两款"）→ 解析上一条消息中的 [商品卡片:ID]
        """
        # 优先用 params 里的 product_ids
        if params.get("product_ids"):
            return params["product_ids"]

        # 从 query 提取商品名称
        names = self._extract_names(query)

        # 如果没有提取到名称，尝试从最近展示中取
        if not names:
            session = self.sessions.get_session(session_id)
            if session:
                last_shown = self._parse_last_shown(session)
                if len(last_shown) >= 2:
                    return last_shown[:5]

        # 按名称搜索
        product_ids: list[str] = []
        for name in names[:5]:
            found = self.retriever.search_by_name(name, limit=2)
            for p in found:
                pid = p.id if hasattr(p, 'id') else p.get('id', '')
                if pid and pid not in product_ids:
                    product_ids.append(pid)

        # 如果搜索也没结果，回退到最近展示
        if len(product_ids) < 2:
            session = self.sessions.get_session(session_id)
            if session:
                last_shown = self._parse_last_shown(session)
                if len(last_shown) >= 2:
                    return last_shown[:5]

        return product_ids

    def _extract_names(self, query: str) -> list[str]:
        """从对比查询中提取商品名称。

        改进策略（两阶段分离）：
          Stage 1 — 剥离指令前缀/后缀（对比、帮我等），得到"内容段"
          Stage 2 — 在内容段上用商品分隔词（和/与/vs）拆出各商品名
        避免旧实现里『"和"被先命中导致"帮我对比"残留在第一部分』的问题。
        """
        # ── Stage 1: 剥离指令包装 ──────────────────────────
        content = query.strip()

        # 去除前缀中的意图/礼貌词
        _PREFIX_CLEAN = [
            '帮我对比一下', '帮我对比', '帮我比较一下', '帮我比较',
            '请帮我对比', '请对比', '麻烦对比', '对比一下', '比较一下',
            '帮我', '帮', '请', '麻烦',
        ]
        for pf in _PREFIX_CLEAN:
            if content.startswith(pf):
                content = content[len(pf):]
                break

        # 去除后缀中的追问词
        _SUFFIX_CLEAN = [
            '哪个好', '哪个更好', '哪款好', '哪款更好', '选哪个', '怎么选',
            '区别是什么', '有什么区别', '有什么不同', '哪个更适合', '哪个更值得买',
            '怎么样', '好不好', '值得买吗',
        ]
        for sf in _SUFFIX_CLEAN:
            if content.endswith(sf):
                content = content[:-len(sf)]
                break

        # 如果内容段里仍有"对比/比较"关键词，取后面的部分
        for kw in ['对比', '比较']:
            if kw in content:
                # 例如 "一下安热沙对比理肤泉" → 对比后的部分是理肤泉
                # 这里不拆分，只把关键词当作普通分隔符，由 Stage 2 统一处理
                pass

        # ── Stage 2: 商品名拆分 ────────────────────────────
        product_seps = ['和', '与', 'vs', 'VS', '对比', '比较']
        for sep in product_seps:
            if sep in content:
                parts = content.split(sep)
                cleaned = []
                for p in parts:
                    p = p.strip()
                    # 去除残留噪音
                    for noise in [
                        '一下', '哪个好', '哪款好', '更好', '更',
                        '选哪个', '怎么选', '区别', '有什么不同',
                        '哪款更好', '哪个更', '怎么样', '好不好',
                        '值得买吗', '推荐', '帮我', '帮',
                    ]:
                        p = p.replace(noise, '').strip()
                    if p and len(p) >= 2:
                        cleaned.append(p)
                if len(cleaned) >= 2:
                    return cleaned[:5]
                break  # 找到第一个有效分隔符就停止

        # 兜底：没有分隔符 → 整段作为一个名称
        if len(content) >= 2:
            return [content]
        return []

    def _parse_last_shown(self, session) -> list[str]:
        """从会话最后一条助手消息中提取 [商品卡片:ID]"""
        if not session.messages:
            return []
        for msg in reversed(session.messages):
            if msg.role == "assistant":
                ids = re.findall(r'\[商品卡片:([^\]]+)\]', msg.content)
                if ids:
                    return [pid.strip() for pid in ids[:5]]
        return []

    async def _extract_table(
        self,
        products: list,
        context: str,
        query: str,
        table_products: list[dict],
    ) -> tuple[list[dict], dict | None]:
        """
        JSON Mode 抽取对比维度 + 推荐。失败时降级为数据派生维度。
        返回 (dimensions, recommendation|None)。
        """
        n = len(products)
        prompt = (
            f"用户对比需求：{query}\n\n"
            f"以下是 {n} 款商品的信息：\n{context}\n\n"
            f"请从商品信息中提取 {n} 款商品之间可对比的关键维度，输出 JSON：\n"
            f'{{"dimensions": [{{"name": "维度名", "values": ["商品1的值", "商品2的值", ...]}}], '
            f'"recommendation": {{"index": 1, "reason": "推荐理由"}}}}\n\n'
            f"规则：\n"
            f"1. dimensions 的 values 数组长度必须等于 {n}，值与商品顺序对齐\n"
            f"2. 维度值严格取自商品信息，该商品没有则填 '—'\n"
            f"3. 维度 2-4 个，选用户最关心的（如功效/场景/续航/适用人群等）\n"
            f"4. recommendation.index 是推荐商品序号（1-{n}），reason 一句话\n"
            f"5. 只输出 JSON，不要其他文字"
        )

        try:
            raw = await self.doubao.generate_response(prompt)
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
        except Exception as e:
            print(f"[compare_agent] _extract_table 失败: {e}")
            data = {}

        # 校验维度
        dimensions: list[dict] = []
        dims_in = data.get("dimensions") if isinstance(data, dict) else None
        if isinstance(dims_in, list):
            for d in dims_in:
                if not isinstance(d, dict):
                    continue
                name = str(d.get("name", "")).strip()
                vals = d.get("values")
                if name and isinstance(vals, list) and len(vals) == n:
                    dimensions.append({"name": name, "values": [str(v) for v in vals]})

        # 校验推荐
        recommendation = None
        rec_in = data.get("recommendation") if isinstance(data, dict) else None
        if isinstance(rec_in, dict):
            idx = rec_in.get("index")
            reason = str(rec_in.get("reason", "")).strip()
            if isinstance(idx, int) and 1 <= idx <= n and reason:
                recommendation = {
                    "product_id": table_products[idx - 1]["product_id"],
                    "reason": reason,
                }

        # 兜底：LLM 没给出可用维度时，从商品数据派生
        if not dimensions:
            dimensions = self._fallback_dimensions(products)

        return dimensions, recommendation

    def _fallback_dimensions(self, products: list) -> list[dict]:
        """从商品数据派生对比维度（不依赖 LLM），保证表非空且有意义。"""
        dims: list[dict] = []

        # 品牌（必有）
        brands = [p.brand or "—" for p in products]
        dims.append({"name": "品牌", "values": brands})

        # 品类/子类目
        cats = [p.sub_category or p.category or "—" for p in products]
        # 去重检查：如果全相同则跳过
        if len(set(cats)) > 1:
            dims.append({"name": "类型", "values": cats})

        # 从营销描述中提取适用肤质（美妆护肤类）
        skin_types = []
        for p in products:
            desc = ""
            if p.rag_knowledge and p.rag_knowledge.marketing_description:
                desc = p.rag_knowledge.marketing_description
            found = "—"
            for st in ["干皮", "油皮", "混合皮", "敏感肌", "所有肤质", "干性", "油性", "混合性", "敏感性"]:
                if st in desc:
                    found = st
                    break
            skin_types.append(found)
        if any(v != "—" for v in skin_types):
            dims.append({"name": "适用肤质", "values": skin_types})

        # 从营销描述中提取功效
        efficacy = []
        for p in products:
            desc = ""
            if p.rag_knowledge and p.rag_knowledge.marketing_description:
                desc = p.rag_knowledge.marketing_description
            found = "—"
            for kw in ["保湿", "美白", "抗老", "修护", "控油", "防晒", "提亮",
                       "紧致", "舒缓", "抗氧化", "补水", "淡斑"]:
                if kw in desc:
                    found = kw
                    break
            efficacy.append(found)
        if any(v != "—" for v in efficacy):
            dims.append({"name": "核心功效", "values": efficacy})

        return dims

    def _build_comparison_text_prompt(
        self,
        products: list,
        context: str,
        query: str,
    ) -> str:
        """构建流式对比文案 prompt。

        复用 Step 2 已构建的丰富上下文（含 SKU 规格 + 营销描述），
        让 LLM 生成带 [商品卡片:ID] 标记的自然语言对比分析。
        """
        n = len(products)
        # 用实际商品 ID 构建示例，避免 LLM 编造 ID
        example_ids = "、".join(p.id for p in products)

        prompt = (
            f'你是"小豆"，用户的AI闺蜜兼购物助手。\n\n'
            f'用户想对比以下 {n} 款商品："{query}"\n\n'
            f"=== 商品信息 ===\n{context}\n\n"
            f"=== 你的任务 ===\n"
            f"请生成一个清晰的结构化对比分析，帮助用户做决策。\n\n"
            f"【格式要求】\n"
            f"1. 先用1句话开启对比（闺蜜风格，如'帮你对比了一下这几款～'）\n"
            f"2. 然后逐一列出关键对比维度（📊 开头），至少包含：价格、品牌、核心特点/功效\n"
            f"3. 每款商品给出简短点评（💡 开头，1句话，指出适合什么人群/场景）\n"
            f"4. 最后给出综合推荐建议（✨ 开头，1-2句话，明确推荐哪款给什么需求的人）\n"
            f"5. 每个商品介绍完后必须紧跟着放 [商品卡片:商品ID] 标记\n"
            f"6. 用 **加粗** 标注关键数据和核心卖点\n"
            f"7. 对比要客观，不要偏袒某一款\n"
            f"8. 不要编造商品信息，只基于上面提供的真实数据\n"
            f"9. ⚠️ 本对比涉及的商品ID为：{example_ids}，只能使用这些ID\n\n"
            f"【格式示例】\n"
            f"帮你对比了一下这两款防晒乳～\n\n"
            f"📊 **价格**：A款 ¥298 vs B款 ¥268，B更亲民\n"
            f"📊 **品牌**：A是专业防晒品牌，B是法国药妆品牌\n"
            f"📊 **核心特点**：A主打高倍防水防汗，B主打清爽控油\n\n"
            f"💡 **点评**：\n"
            f"A款 — 防水防汗能力强，适合户外运动、游泳\n"
            f"[商品卡片:{products[0].id if products else 'ID'}]\n\n"
            f"B款 — 质地清爽不油腻，适合油皮、日常通勤\n"
            f"[商品卡片:{products[1].id if len(products) >= 2 else 'ID'}]\n\n"
            f"✨ **综合建议**：如果你经常户外运动选A，日常通勤追求清爽选B～"
        )
        return prompt

    def _image_url(self, product) -> str:
        import os
        host = os.getenv("SERVER_BASE_URL", "http://localhost:8080").rstrip("/")
        if hasattr(product, 'image_path') and product.image_path:
            return f"{host}/static/{product.image_path}"
        return ""


compare_agent = CompareAgent(None, None, None)  # 占位，启动时注入
