"""
交易完成引导器 — 带领用户完成订单创建的全流程。

多阶段确认：init → confirm_address → confirm_final → done
通过 Session.order_state 记录当前阶段，支持跨消息轮次协作。
"""
import re
from datetime import datetime
from typing import AsyncIterator

from models.events import (
    content as ev_content, cart_update, order_confirmed, end as ev_end,
    clarification as ev_clarification,
)


class OrderAgent:
    """交易完成引导器：多阶段确认流程"""

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
        session = self.sessions.get_session(session_id)
        items = session.cart_items if session else []
        order_state = getattr(session, 'order_state', {}) if session else {}
        current_step = order_state.get("step", "init")

        # 上一次下单已完成后再次说"下单XX" → 重置状态，走新流程
        if current_step == "done":
            self._set_order_state(session_id, "init")
            current_step = "init"

        if not items and current_step == "init" and query:
            # 先尝试从 query 提取商品名搜索（优先级高于 last_shown）
            from utils.product_repo import product_repo
            clean_q = self._clean_query_for_search(query)
            qty = self._extract_order_quantity(query)
            if clean_q:
                products = product_repo.search_by_name(clean_q, limit=5)
                candidates = [p for p in products if p.base_price > 0]
                if len(candidates) == 1:
                    p = candidates[0]
                    item = dict(product_id=p.id, name=p.title, brand=p.brand or "",
                                price=p.base_price, quantity=qty, image_url="")
                    items.append(item)
                    self.sessions.add_to_cart(session_id, item)
                    print(f"[order_agent] cart empty, found '{p.title}' x{qty} by name (q='{clean_q}')", flush=True)
                elif len(candidates) >= 2:
                    # 多规格/同品牌不同商品 → 让用户选择
                    opts = [f"{p.title}（¥{p.base_price:.0f}）" for p in candidates[:4]]
                    yield ev_clarification(f"搜到多款「{clean_q}」，你要哪一个？", opts).to_sse_compact()
                    self._set_order_state(session_id, "clarify_product",
                                          candidates=[{"product_id": p.id, "title": p.title,
                                                       "brand": p.brand or "", "price": p.base_price}
                                                      for p in candidates[:4]],
                                          quantity=qty)
                    yield ev_end(True).to_sse_compact()
                    return

        if not items and current_step == "init":
            # 兜底：query 没提具体商品名 → 从 last_shown_products 构造
            last_shown = getattr(session, 'last_shown_products', []) if session else []
            if last_shown:
                from utils.product_repo import product_repo
                valid = []
                for sp in last_shown[:4]:
                    pid = sp.get("product_id", "")
                    product = product_repo.get(pid)
                    if product and product.base_price > 0:
                        valid.append({"product_id": pid, "title": product.title,
                                      "brand": product.brand or "", "price": product.base_price})
                if len(valid) == 1:
                    v = valid[0]
                    item = dict(product_id=v["product_id"], name=v["title"], brand=v["brand"],
                                price=v["price"], quantity=1, image_url="")
                    items.append(item)
                    self.sessions.add_to_cart(session_id, item)
                    print(f"[order_agent] cart empty, using '{v['title']}' from last_shown", flush=True)
                elif len(valid) >= 2:
                    opts = [f"{v['title']}（¥{v['price']:.0f}）" for v in valid]
                    yield ev_clarification("最近浏览了多款商品，你要下单哪一个？", opts).to_sse_compact()
                    self._set_order_state(session_id, "clarify_product",
                                          candidates=[{"product_id": v["product_id"], "title": v["title"],
                                                       "brand": v["brand"], "price": v["price"]}
                                                      for v in valid],
                                          quantity=1)
                    yield ev_end(True).to_sse_compact()
                    return

        if not items and current_step == "init" and current_step != "clarify_product":
            yield ev_content("购物车还是空的哦，先逛逛加购一些商品吧～").to_sse_compact()
            yield ev_end(True).to_sse_compact()
            return

        total = self._calc_total(items) if items else 0

        if current_step == "init":
            # 检测首条消息是否已含地址（自结算路径：OrderFormScreen 发送"下单，收货地址：xxx"）
            addr = self._extract_address(query)
            if addr:
                self._set_order_state(session_id, "confirm_final", address=addr)
                # 直接跳到最终确认，展示完整汇总
                async for ev in self._step_confirm_final_show(session_id, items, addr, total):
                    yield ev
            else:
                async for ev in self._step_show_summary(session_id, items, total):
                    yield ev
        elif current_step == "confirm_address":
            async for ev in self._step_confirm_address(session_id, items, query, total):
                yield ev
        elif current_step == "confirm_final":
            async for ev in self._step_final_confirm(session_id, items, query, total):
                yield ev
        elif current_step == "clarify_product":
            async for ev in self._step_clarify_product(session_id, items, query, total, order_state):
                yield ev

        yield ev_end(True).to_sse_compact()


    async def _step_show_summary(self, session_id, items, total):
        """Step 1: 展示订单汇总 + 提示输入地址"""
        lines = ["📋 **订单确认**\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['name']} — ¥{item['price']:.0f} x {item['quantity']}")
        lines.append(f"\n💰 合计：¥{total:.0f}")
        lines.append("\n请告诉我你的收货地址，直接输入即可～")

        for line in lines:
            yield ev_content(line).to_sse_compact()
        yield cart_update(items=items, total=total, action="checkout").to_sse_compact()
        self._set_order_state(session_id, "confirm_address")

    async def _step_confirm_address(self, session_id, items, query, total):
        """Step 2: 接收地址 → 展示完整汇总"""
        address = query.strip()
        if not address or len(address) < 2:
            yield ev_content("地址好像不太完整哦，请再输入一下收货地址～").to_sse_compact()
            return

        self._set_order_state(session_id, "confirm_final", address=address)

        lines = [f"📍 收货地址：{address}\n", "📋 **订单汇总**："]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['name']} — ¥{item['price']:.0f} x {item['quantity']}")
        lines.append(f"\n💰 合计：¥{total:.0f}")
        lines.append("\n确认无误吗？回复 **确认** 下单，或回复 **取消** 哦～")

        for line in lines:
            yield ev_content(line).to_sse_compact()
        yield cart_update(items=items, total=total, action="checkout").to_sse_compact()

    async def _step_final_confirm(self, session_id, items, query, total):
        """Step 3: 确认/取消 → 完成下单"""
        confirm_words = ["确认", "是的", "没错", "下单", "可以", "好", "ok", "yes", "对", "行"]
        cancel_words = ["取消", "不要", "再看看", "不买", "算了", "no"]

        if any(w in query.lower() for w in confirm_words):
            order_id = f"ORD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            self._set_order_state(session_id, "done", address=None, order_id=order_id)

            # 持久化 order_state 到 DB
            try:
                import asyncio
                from db import relational as _db
                session = self.sessions.get_session(session_id)
                if session:
                    asyncio.create_task(_db.update_session_state(
                        session_id, order_state=session.order_state,
                    ))
            except Exception as e:
                print(f"[order_agent] 持久化订单失败: {e}")

            yield ev_content(f"订单已创建（编号：{order_id}）！我们会尽快为您发货～").to_sse_compact()
            yield order_confirmed(order_id=order_id, items=items, total=total).to_sse_compact()

            # 清空购物车
            self.sessions.clear_cart(session_id)
            yield cart_update(items=[], total=0, action="ordered").to_sse_compact()

        elif any(w in query.lower() for w in cancel_words):
            self._set_order_state(session_id, "init")
            yield ev_content("好的，已取消下单。还有什么可以帮你的吗？").to_sse_compact()
            yield cart_update(items=items, total=total, action="checkout_cancelled").to_sse_compact()
        else:
            yield ev_content("请回复 **确认** 下单，或回复 **取消** 哦～").to_sse_compact()


    def _set_order_state(self, session_id, step, address=None, order_id=None, **kwargs):
        session = self.sessions.get_session(session_id)
        if session:
            order_state = getattr(session, 'order_state', {}) or {}
            order_state["step"] = step
            if address is not None:
                order_state["address"] = address
            if order_id is not None:
                order_state["order_id"] = order_id
            order_state.update(kwargs)
            session.order_state = order_state

    def _calc_total(self, items):
        return sum(i["price"] * i["quantity"] for i in items)

    def _extract_address(self, query: str) -> str | None:
        """从消息中提取地址。支持格式：'收货地址：xxx' / '地址是xxx' / '送到xxx'"""
        for prefix in ["收货地址：", "收货地址:", "地址：", "地址:", "收货信息：", "地址是"]:
            if prefix in query:
                addr = query.split(prefix, 1)[1].strip()
                return addr if len(addr) >= 2 else None
        # 匹配 "送到xxx" / "寄到xxx"
        m = re.search(r'(?:送到|寄到|发到|派送到)\s*(.{4,})', query)
        if m:
            return m.group(1).strip()
        return None

    def _extract_order_quantity(self, query: str) -> int:
        """从下单 query 中提取数量，支持"五件""3个""2件"等中阿数字，默认 1"""
        chinese_num = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                       '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
        m = re.search(r'(\d+|[一二三四五六七八九十两])\s*[件个份台把瓶包盒箱袋支罐]', query)
        if m:
            num_str = m.group(1)
            return chinese_num.get(num_str, 1) if num_str in chinese_num else int(num_str)
        # 没有量词 → 取最后一个非价格的数字
        cleaned = re.sub(r'[¥￥]\s*\d+', '', query)
        cleaned = re.sub(r'\(\s*[¥￥]\s*\d+[^)]*\)', '', cleaned)
        cleaned = re.sub(r'\d+\s*元', '', cleaned)
        nums = re.findall(r'(\d+)', cleaned)
        return int(nums[-1]) if nums else 1

    def _clean_query_for_search(self, query: str) -> str:
        """去掉下单/地址等噪声词，提取纯商品名用于搜索。"""
        # 截断地址部分（地址：xxx → 只取前面的商品名）
        for prefix in ["收货地址：", "收货地址:", "地址：", "地址:", "收货信息：", "地址是"]:
            if prefix in query:
                query = query.split(prefix, 1)[0]
        # 去掉数量词（"一件"/"两件"/"3个"/"五件" 等，支持中阿数字）
        query = re.sub(r'(\d+|[一二三四五六七八九十两])\s*[件个份台把瓶包盒箱袋支罐]', '', query)
        # 去掉下单/结算等意图词（长短语优先，避免"帮我下单"被"下单"先消费）
        for kw in ["帮我下单", "帮我结算", "确认订单", "提交订单", "去支付", "去结算",
                   "下单", "结算", "结账", "付款", "买单", "我要买", "我要", "帮我买", "帮我", "买"]:
            query = query.replace(kw, "")
        return query.strip()

    async def _step_clarify_product(self, session_id, items, query, total, order_state):
        """用户从多规格候选中选择了具体商品"""
        candidates = order_state.get("candidates", [])
        qty = order_state.get("quantity", 1)
        if not candidates:
            yield ev_content("抱歉，候选商品已过期，请重新下单～").to_sse_compact()
            self._set_order_state(session_id, "init")
            return

        chosen = None
        # 1) 位置指代："第一个"/"第2个"
        from utils.position_resolver import extract_position_from_message
        pos = extract_position_from_message(query)
        if pos and 1 <= pos <= len(candidates):
            chosen = candidates[pos - 1]
        # 2) 名称匹配
        if not chosen:
            for c in candidates:
                if c["title"] in query or query.strip() in c["title"]:
                    chosen = c
                    break
        # 3) 兜底取第一个
        if not chosen:
            chosen = candidates[0]

        item = dict(product_id=chosen["product_id"], name=chosen["title"],
                    brand=chosen.get("brand", ""), price=chosen["price"],
                    quantity=qty, image_url="")
        items.append(item)
        self.sessions.add_to_cart(session_id, item)
        yield ev_content(f"好的，已选择「{chosen['title']}」x{qty}～").to_sse_compact()

        total = self._calc_total(items)
        self._set_order_state(session_id, "init")
        async for ev in self._step_show_summary(session_id, items, total):
            yield ev

    async def _step_confirm_final_show(self, session_id, items, address, total):
        """自结算路径：用户已提供地址，直接展示完整汇总 + 确认/取消"""
        lines = [f"📍 收货地址：{address}\n", "📋 **订单汇总**："]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['name']} — ¥{item['price']:.0f} x {item['quantity']}")
        lines.append(f"\n💰 合计：¥{total:.0f}")
        lines.append("\n确认无误吗？回复 **确认** 下单，或回复 **取消** 哦～")

        for line in lines:
            yield ev_content(line).to_sse_compact()
        yield cart_update(items=items, total=total, action="checkout").to_sse_compact()


order_agent = OrderAgent(None, None, None)
