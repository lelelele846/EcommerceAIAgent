"""
采购篮管理器 — 通过自然语言指令操控购物车内容。

支持的意图识别：加入采购 / 浏览 / 移出 / 修改数量 / 清空采购篮。
所有变更写入 Session.cart_items，通过 cart_update SSE 事件实时推送至客户端。
"""
import re
from typing import AsyncIterator

from models.events import (
    content as ev_content, cart_update, end as ev_end,
    clarification as ev_clarification,
)
from utils.position_resolver import extract_position_from_message
from utils.product_repo import product_repo
from utils.category_detector import detect_category


class CartAgent:
    """采购篮管理器：解析自然语言指令并操控购物车"""

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
        """
        主入口，yield SSE 事件字符串。
        params 应包含：
          - action: "add" | "remove" | "update" | "view" | "clear"
          - product_id: 目标商品 ID（add 操作）
          - index: 目标商品索引（remove/update 操作）
          - quantity: 数量（add/update 操作）
        """
        action = params.get("action", self._detect_action(query))
        print(f"[cart_agent v3] run() action={action} query='{query[:50]}'", flush=True)

        if action == "view":
            async for ev in self._handle_view(session_id, base_url):
                yield ev
            yield ev_end(True).to_sse_compact()
            return

        if action == "remove":
            async for ev in self._handle_remove(session_id, query, params):
                yield ev
            yield ev_end(True).to_sse_compact()
            return

        if action == "update":
            async for ev in self._handle_update(session_id, query, params):
                yield ev
            yield ev_end(True).to_sse_compact()
            return

        if action == "clear":
            async for ev in self._handle_clear(session_id):
                yield ev
            yield ev_end(True).to_sse_compact()
            return

        # 默认: add
        async for ev in self._handle_add(session_id, query, params, base_url):
            yield ev
        yield ev_end(True).to_sse_compact()


    async def _handle_add(self, session_id, query, params, base_url):
        """加购：解析目标商品 + 数量 → 写入 session.cart_items"""
        product_id = params.get("product_id", "")

        if not product_id:
            session = self.sessions.get_session(session_id)
            last_shown = getattr(session, 'last_shown_products', []) or []
            pending = getattr(session, 'cart_clarify_candidates', None)
            print(f"[cart_agent v3] query='{query[:40]}' last_shown={[s.get('title','')[:20] for s in last_shown[:3]]} pending={bool(pending)}", flush=True)

            # 0) 有待确认的多规格候选 → 从用户回复中解析选择
            if pending:
                product_id = self._resolve_clarify(query, pending)
                session.cart_clarify_candidates = None
                print(f"[cart_agent v3] resolved clarify → {product_id}", flush=True)

            # 1) 位置指代："第一个"/"第二个"
            if not product_id:
                pos = extract_position_from_message(query)
                if pos and 1 <= pos <= len(last_shown):
                    product_id = last_shown[pos - 1].get("product_id", "")
                    print(f"[cart_agent v3] position ref #{pos} → {product_id}", flush=True)

            # 2) 按商品名在 last_shown 中匹配
            if not product_id and last_shown:
                for sp in last_shown:
                    pid = sp.get("product_id", "")
                    product = product_repo.get(pid)
                    if product and self._match_name(product.title, query):
                        product_id = pid
                        print(f"[cart_agent v3] last_shown match '{product.title[:30]}' → {pid}", flush=True)
                        break

            # 3) last_shown 没有 → 从 query 提取商品名搜索全库
            if not product_id:
                name = self._extract_product_name(query)
                print(f"[cart_agent v3] extracted name='{name}'", flush=True)
                if name:
                    products = product_repo.search_by_name(name, limit=5)
                    candidates = [p for p in products if p.base_price > 0]
                    # 类目过滤：避免"防晒帽"混入"防晒霜"
                    cat = detect_category(name)
                    if cat:
                        candidates = [p for p in candidates if p.category == cat]
                    print(f"[cart_agent v3] search '{name}' → {len(candidates)} candidates (cat={cat}): {[p.title[:30] for p in candidates[:5]]}", flush=True)
                    if len(candidates) == 1:
                        product_id = candidates[0].id
                        if session:
                            session.last_shown_products = [
                                {"product_id": p.id, "title": p.title} for p in candidates[:3]
                            ]
                    elif len(candidates) >= 2:
                        opts = [f"{p.title}（¥{p.base_price:.0f}）" for p in candidates[:4]]
                        yield ev_clarification(f"搜到多款「{name}」，你要哪一个？", opts).to_sse_compact()
                        if session:
                            session.cart_clarify_candidates = [
                                {"product_id": p.id, "title": p.title,
                                 "brand": p.brand or "", "price": p.base_price}
                                for p in candidates[:4]
                            ]
                        print(f"[cart_agent v3] clarification with {len(candidates)} options", flush=True)
                        return

        if not product_id:
            yield ev_content("抱歉，我没找到要加购的是哪个商品，可以说具体一点吗？").to_sse_compact()
            return

        # 获取商品信息
        product = product_repo.get(product_id)
        if not product:
            for p in self.retriever.products:
                if p.id == product_id:
                    product = p
                    break
        if not product:
            yield ev_content("抱歉，暂时没找到这个商品，可能已经下架了。").to_sse_compact()
            return

        qty = self._extract_quantity(query)

        image_url = ""
        if hasattr(product, 'image_path') and product.image_path:
            image_url = f"{base_url}/static/{product.image_path}"

        item = {
            "product_id": product.id,
            "name": product.title if hasattr(product, 'title') else product.get('title', ''),
            "brand": product.brand if hasattr(product, 'brand') else product.get('brand', ''),
            "price": product.base_price if hasattr(product, 'base_price') else product.get('base_price', 0),
            "quantity": qty,
            "image_url": image_url,
        }

        items = self.sessions.add_to_cart(session_id, item)
        total = self._calc_total(items)

        yield ev_content(f"已将 {item['name']} x{qty} 加入购物车！🛒").to_sse_compact()
        yield cart_update(items=items, total=total, action="add").to_sse_compact()

    async def _handle_view(self, session_id, base_url):
        """查看购物车"""
        items = self.sessions.get_cart(session_id)
        if not items:
            yield ev_content("购物车还是空的哦，对我说「加购物车」把商品放进来吧～").to_sse_compact()
            return

        total = self._calc_total(items)
        lines = [f"🛒 你的购物车共有 {len(items)} 件商品：\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['name']} — ¥{item['price']:.0f} x {item['quantity']}")
        lines.append(f"\n💰 合计：**¥{total:.0f}**")

        yield ev_content("\n".join(lines)).to_sse_compact()
        yield cart_update(items=items, total=total, action="view").to_sse_compact()

    async def _handle_remove(self, session_id, query, params):
        """删除购物车商品"""
        items = self.sessions.get_cart(session_id)
        if not items:
            yield ev_content("购物车已经是空的了～").to_sse_compact()
            return

        index = params.get("index")
        if index is None:
            pos = extract_position_from_message(query)
            if pos and 1 <= pos <= len(items):
                index = pos - 1
            else:
                # 尝试按商品名匹配
                for i, item in enumerate(items):
                    if self._match_name(item["name"], query):
                        index = i
                        break

        if index is None:
            yield ev_content(f"要删除哪一个呢？购物车有 {len(items)} 件商品，告诉我是第几个就行～").to_sse_compact()
            return

        if not (0 <= index < len(items)):
            yield ev_content(f"购物车只有 {len(items)} 件商品，找不到第 {index + 1} 个哦～").to_sse_compact()
            return

        removed_name = items[index]["name"]
        items = self.sessions.remove_from_cart(session_id, index)
        total = self._calc_total(items)

        yield ev_content(f"已从购物车移除「{removed_name}」。").to_sse_compact()
        yield cart_update(items=items, total=total, action="remove").to_sse_compact()

    async def _handle_update(self, session_id, query, params):
        """修改商品数量"""
        items = self.sessions.get_cart(session_id)
        if not items:
            yield ev_content("购物车是空的，没什么可以改的～").to_sse_compact()
            return

        index = params.get("index")
        if index is None:
            pos = extract_position_from_message(query)
            if pos and 1 <= pos <= len(items):
                index = pos - 1
            else:
                # 尝试按商品名匹配
                for i, item in enumerate(items):
                    if self._match_name(item["name"], query):
                        index = i
                        break

        if index is None:
            yield ev_content(f"要修改哪一个呢？购物车有 {len(items)} 件商品，告诉我是第几个就行～").to_sse_compact()
            return

        if not (0 <= index < len(items)):
            yield ev_content(f"购物车只有 {len(items)} 件商品，找不到第 {index + 1} 个哦～").to_sse_compact()
            return

        qty = self._extract_quantity(query)
        if qty is None:
            nums = re.findall(r'(\d+)', query)
            qty = int(nums[-1]) if nums else 1

        item_name = items[index]["name"]
        items = self.sessions.update_cart_quantity(session_id, index, qty)
        total = self._calc_total(items)

        if qty <= 0:
            yield ev_content(f"已从购物车移除「{item_name}」。").to_sse_compact()
        else:
            yield ev_content(f"已将「{item_name}」数量改为 {qty}。").to_sse_compact()
        yield cart_update(items=items, total=total, action="update").to_sse_compact()

    async def _handle_clear(self, session_id):
        """清空购物车"""
        items = self.sessions.get_cart(session_id)
        if not items:
            yield ev_content("购物车已经是空的了～").to_sse_compact()
            return

        self.sessions.clear_cart(session_id)
        yield ev_content("已清空购物车。").to_sse_compact()
        yield cart_update(items=[], total=0, action="clear").to_sse_compact()


    def _resolve_clarify(self, query: str, candidates: list) -> str:
        """从用户对多规格追问的回复中解析出 product_id"""
        # 位置指代："第一个"/"第2个"
        pos = extract_position_from_message(query)
        if pos and 1 <= pos <= len(candidates):
            return candidates[pos - 1].get("product_id", "")
        # 名称匹配
        for c in candidates:
            if self._match_name(c["title"], query):
                return c.get("product_id", "")
        # 兜底取第一个
        return candidates[0].get("product_id", "") if candidates else ""

    def _match_name(self, name: str, query: str) -> bool:
        """检查商品名是否与 query 匹配（兼容"可口可乐 330ml"等含规格后缀的名称）。"""
        if name in query:
            return True
        # 提取纯中文部分（"可口可乐 330ml" → "可口可乐"）再匹配
        chinese = re.sub(r'[^一-鿿]', '', name)
        if len(chinese) >= 2 and chinese in query:
            return True
        return False

    def _extract_product_name(self, query: str) -> str:
        """从加购 query 中提取商品名。"""
        # 去掉数量词（"一件"/"两件"/"3个" 等）
        query = re.sub(r'\d*\s*[件个份台把瓶包盒箱袋支罐]', '', query)
        for phrase in ["加入购物车", "加购物车", "添加到购物车", "放进购物车", "放购物车",
                       "加进购物车", "帮我加到购物车", "帮我加购", "加购", "加车", "加进来",
                       "帮我把", "把", "帮我", "我想买", "我想", "我要买", "我要", "加入", "买"]:
            query = query.replace(phrase, "")
        return query.strip()

    def _detect_action(self, query: str) -> str:
        """从 NL 中检测购物车操作类型"""
        if any(k in query for k in ["删除", "移除", "去掉", "不要", "删掉"]):
            return "remove"
        if any(k in query for k in ["数量", "改成", "改为", "换成", "改称"]):
            return "update"
        if any(k in query for k in ["清空", "全删", "全部删除"]):
            return "clear"
        # 加入/添加购物车 → add（必须在"购物车→view"之前判断）
        if any(k in query for k in ["加入购物车", "加购物车", "添加到购物车", "放进购物车", "放购物车", "加进购物车", "加进来", "帮我加到购物车"]):
            return "add"
        if any(k in query for k in ["看看购物车", "购物车里有什么", "打开购物车", "查看购物车", "我的购物车", "里面有什么"]):
            return "view"
        return "add"

    def _extract_quantity(self, query: str) -> int:
        """从 query 中提取数量，支持"2件"和"改4"两种形式，默认 1"""
        match = re.search(r'(\d+)\s*[件个份台把瓶包盒箱袋支罐]', query)
        if match:
            return int(match.group(1))
        # 没有量词 → 取最后一个非价格/非规格的数字
        cleaned = re.sub(r'[¥￥]\s*\d+', '', query)              # ¥170
        cleaned = re.sub(r'\(\s*[¥￥]\s*\d+[^)]*\)', '', cleaned)  # (¥170)
        cleaned = re.sub(r'\d+\s*元', '', cleaned)               # 170元
        cleaned = re.sub(r'\d+\s*(ml|g|kg|oz|L|mm|cm|英寸|寸)', '', cleaned)  # 30ml/60g
        nums = re.findall(r'(\d+)', cleaned)
        return int(nums[-1]) if nums else 1

    def _calc_total(self, items: list[dict]) -> float:
        return sum(i["price"] * i["quantity"] for i in items)


cart_agent = CartAgent(None, None, None)  # 占位，启动时注入
