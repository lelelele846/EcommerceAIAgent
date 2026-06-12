import json
import re
import asyncio
import time
from fastapi import APIRouter, Request, HTTPException
from models.schemas import ChatRequest
from models.events import (
    thinking, tool_progress, content as ev_content,
    product_card_compact, comparison_table, clarification as ev_clarification,
    end as ev_end, error as ev_error,
)
from utils.category_detector import detect_category, detect_all_categories
from utils.price_parser import detect_price_range
from utils.product_card_parser import PRODUCT_CARD_PATTERN, strip_product_card_markers, StreamCardParser
from utils.query_analyzer import analyze_query, get_clarification_prompt, SPECIFIC_PRODUCT_KEYWORDS, ALL_BRANDS
from utils.position_resolver import resolve_product_id, has_product_reference, extract_position_from_message
from utils.product_repo import products_to_dict_list
from agent.state_machine import AgentState, get_next_state, is_agent_allowed
from db import relational as db  # 🆕 持久化层


router = APIRouter(prefix="/api", tags=["chat"])


def get_base_url(http_request: Request) -> str:
    """获取服务器基础URL"""
    import os
    env_url = os.getenv("SERVER_BASE_URL")
    if env_url:
        return env_url.rstrip("/")
    host = http_request.headers.get("host", "localhost:8080")
    scheme = http_request.headers.get("x-forwarded-proto", "http")
    return f"{scheme}://{host}"


# 全局服务实例（通过依赖注入设置）
_retriever = None
_doubao_service = None
_session_manager = None
_image_service = None


def set_services(retriever, doubao_service, session_manager, image_service=None):
    """设置全局服务实例"""
    global _retriever, _doubao_service, _session_manager, _image_service
    _retriever = retriever
    _doubao_service = doubao_service
    _session_manager = session_manager
    _image_service = image_service


def _check_services_initialized():
    """检查服务是否已初始化"""
    if None in [_retriever, _doubao_service, _session_manager]:
        raise HTTPException(status_code=503, detail="服务正在初始化中，请稍后重试")


# ══════════════════════════════════════════════════════════════
# 规则快速通道 — 让常见意图秒级判定，避开 LLM 延迟
# ══════════════════════════════════════════════════════════════

_COMPARE_KEYWORDS = ["对比", "比较", "哪个更", "哪个好", "哪款更", "vs", "选哪个", "区别", "有什么不同", "哪款更好"]
_SEARCH_KEYWORDS = ["推荐", "求推荐", "有什么", "找一款", "找一下", "想买", "看看有没有", "有没有", "帮我找", "帮我推荐"]
_SHOW_NOW_WORDS = {"都行", "无所谓", "看看吧", "不用问了", "直接推荐", "不用了", "就这些了", "直接帮我搜", "直接搜", "都想要", "都看看"}
_DISSATISFY_WORDS = ["不行", "不满意", "都不行", "不太行", "不够好", "不喜欢这些", "没有合适", "没合适", "没有喜欢", "都不喜欢"]
_BATCH_WORDS = ["换一批", "换一换", "换一组", "还有别的", "还有其他", "重新推荐"]
_SCENE_KEYWORDS = ["准备去", "打算去", "要去", "想去", "度假", "出行", "旅游",
                    "出差", "海边", "爬山", "露营", "健身计划", "搬家", "装修",
                    "开学", "换季", "入秋", "入冬", "入夏", "备孕", "坐月子",
                    "布置新家", "新房", "入职", "面试穿搭"]
_CART_KEYWORDS = ["加购物车", "加入购物车", "加进购物车", "添加到购物车", "放入购物车",
                  "买这个", "来一个", "来一款", "要这个", "就这个", "加车", "加进来",
                  "帮我加到购物车", "放购物车", "购物车", "加入", "加购"]
_ORDER_KEYWORDS = ["下单", "结算", "结账", "确认订单", "去支付", "去结算", "付款", "买单", "提交订单", "帮我下单", "帮我结算"]


def _quick_cart_action(query: str) -> str:
    """从 query 快速判定购物车操作类型"""
    if any(k in query for k in ["删除", "移除", "去掉"]):
        return "remove"
    if any(k in query for k in ["数量", "改成", "改为", "换成"]):
        return "update"
    if any(k in query for k in ["清空", "全删", "全部删除"]):
        return "clear"
    if any(k in query for k in ["加入购物车", "加购物车", "添加到购物车", "放进购物车", "放购物车", "加进购物车", "帮我加到购物车"]):
        return "add"
    if any(k in query for k in ["看看购物车", "购物车里有什么", "打开购物车", "查看购物车", "我的购物车"]):
        return "view"
    return "add"


# LLM 意图分类缓存（session 级别，同 query 不重复分类）
_INTENT_CACHE: dict[str, str] = {}


def _quick_classify(query: str, last_shown: list = None) -> dict | None:
    """规则快速通道：覆盖 70%+ 模板化查询，避开 LLM 3-10s 延迟。

    返回 {'intent', 'params'} 或 None。
    """
    msg = query.strip()
    if not msg:
        return None

    # ── 纯位置指代（"第一个"/"第二款"）→ 追问意图 ──
    # 用户可能想看第一个的详情或问"这款怎么样"
    if last_shown and has_product_reference(msg) and len(msg) <= 10:
        pos = extract_position_from_message(msg)
        if pos and 1 <= pos <= len(last_shown):
            target = last_shown[pos - 1]
            return {
                "intent": "search",
                "params": {
                    "query": f"介绍一下{target.get('title', '这款商品')}",
                    "product_id": target.get("product_id", ""),
                },
            }

    if any(k in msg for k in _COMPARE_KEYWORDS):
        return {"intent": "compare", "params": {"query": msg}}
    if any(k in msg for k in _ORDER_KEYWORDS):
        return {"intent": "order", "params": {"query": msg}}
    if any(k in msg for k in _CART_KEYWORDS):
        return {"intent": "cart", "params": {"query": msg}}
    if any(k in msg for k in _SEARCH_KEYWORDS):
        return {"intent": "search", "params": {"query": msg}}
    # 场景关键词优先于宽泛正则（避免"下周要去三亚"被误判为 search）
    if any(k in msg for k in _SCENE_KEYWORDS):
        return {"intent": "scene", "params": {"query": msg}}
    if re.match(r'^[\w\s一-鿿]{2,8}$', msg) and not any(
        k in msg for k in ["吗", "呢", "吧", "？", "?", "怎么", "什么", "哪"]
    ):
        return {"intent": "search", "params": {"query": msg}}
    return None


async def _llm_classify_intent(query: str, doubao_service=None, last_shown: list = None) -> str:
    """
    LLM 驱动意图分类（规则通道 miss 时的 fallback）。
    🆕 注入 last_shown_products 上下文，让 LLM 知道用户正在看什么。

    返回：'search' | 'compare' | 'scene' | 'clarify' | 'cart' | 'order'
    """
    cache_key = query.strip()
    if cache_key in _INTENT_CACHE:
        return _INTENT_CACHE[cache_key]

    if not doubao_service:
        return "search"

    try:
        # 🆕 构建带上下文的分类 prompt
        context_parts = [f'用户说："{query}"']
        if last_shown:
            shown_str = "、".join(
                f"#{i+1} {p.get('title', p.get('product_id', '?'))}"
                for i, p in enumerate(last_shown[:5])
            )
            context_parts.append(f"上一轮已展示商品：{shown_str}")
            context_parts.append("（注意：如果用户提到'第一个''第二款'等，说明在引用已展示商品）")
        context_parts.append("\n意图是以下哪种？\n- search（搜索推荐商品）\n- compare（对比多个商品）\n- scene（场景规划）\n- clarify（需要追问澄清）\n- cart（加入购物车）\n- order（下单结算）\n\n只输出一个词。")

        prompt = "\n".join(context_parts)
        raw = await doubao_service.generate_response(prompt)
        raw = raw.strip().lower()

        intent = "search"  # 默认
        if "compare" in raw:
            intent = "compare"
        elif "scene" in raw:
            intent = "scene"
        elif "clarify" in raw:
            intent = "clarify"
        elif "order" in raw:
            intent = "order"
        elif "cart" in raw:
            intent = "cart"

        _INTENT_CACHE[cache_key] = intent
        print(f"[llm_classify] '{query[:30]}' → {intent}")
        return intent
    except Exception as e:
        print(f"[llm_classify] 失败: {e}")
        return "search"


# ══════════════════════════════════════════════════════════════
# 原始消息过滤词抽取 — 从用户原话中提取排除约束（LLM 经常漏）
# ══════════════════════════════════════════════════════════════

# 品牌排除关键词（地域/类型）
_BRAND_NEG_PATTERNS = ["不要", "不喜欢", "避开", "排除", "不买", "不用"]

# 品牌地域关键词 → 实际品牌名（从商品库动态补充）
_BRAND_REGION_KEYWORDS = {
    "日系": ["资生堂", "SK-II", "SK2", "芙丽芳丝", "CANMAKE", "KATE", "植村秀"],
    "欧美": ["兰蔻", "雅诗兰黛", "科颜氏", "欧莱雅", "露得清", "MAC", "YSL", "迪奥",
             "Nike", "耐克", "Adidas", "阿迪达斯", "始祖鸟", "露露乐蒙", "lululemon",
             "Apple", "苹果"],
    "国货": ["华为", "小米", "OPPO", "vivo", "联想", "李宁", "安踏", "特步", "361",
             "珀莱雅", "花西子", "薇诺娜", "完美日记", "迪卡侬"],
    "韩系": ["兰芝", "雪花秀", "悦诗风吟", "爱茉莉"],
}

# 属性否定关键词
_ATTR_NEGATIONS = [
    ("酒精", ["不含酒精", "无酒精", "不要含酒精", "不要酒精", "拒绝酒精"]),
    ("香精", ["不含香精", "无香精", "不要香精", "无香", "拒绝香精"]),
    ("防腐剂", ["不含防腐剂", "无防腐剂", "拒绝防腐剂"]),
    ("色素", ["不含色素", "无色素"]),
    ("油脂", ["不含油脂", "无油脂"]),
    ("酒精成分", ["不要含酒精成分"]),
]


def _extract_product_id_from_event(event_str: str) -> str | None:
    """从 SSE 事件字符串中提取 product_id（product_card / comparison_table 事件）。"""
    import json as _json
    for line in event_str.strip().split("\n"):
        if not line.startswith("data:"):
            continue
        try:
            data = _json.loads(line[5:].strip())
        except Exception:
            continue
        if "product_id" in data:
            return data["product_id"]
        if "products" in data and isinstance(data["products"], list):
            # comparison_table 含多个商品，取第一个的 product_id
            for p in data["products"]:
                if isinstance(p, dict) and "product_id" in p:
                    return p["product_id"]
    return None


def _enrich_filters_from_message(params: dict, message: str) -> dict:
    """
    从用户原始消息中抽取 LLM 可能漏填的排除约束。
    RAGent 模式：规则从原话直接抓"不要日系""无酒精"等表达，
    不依赖 LLM 提取，避免 LLM JSON 漏填导致过滤失效。

    返回补全后的 params dict（原地修改 + 返回）。
    """
    excl_brands = list(params.get("exclude_brands") or [])
    excl_attrs = list(params.get("exclude_attrs") or [])

    # 1) 品牌地域否定："不要日系" / "避开欧美" / "不买国货"
    for kw, brands in _BRAND_REGION_KEYWORDS.items():
        if any(f"{neg}{kw}" in message for neg in _BRAND_NEG_PATTERNS):
            for b in brands:
                if b not in excl_brands:
                    excl_brands.append(b)

    # 2) 属性否定："不含酒精" / "无香精"
    for attr, patterns in _ATTR_NEGATIONS:
        if any(p in message for p in patterns):
            if attr not in excl_attrs:
                excl_attrs.append(attr)

    if excl_brands:
        params["exclude_brands"] = excl_brands
    if excl_attrs:
        params["exclude_attrs"] = excl_attrs
    return params


# ══════════════════════════════════════════════════════════════
# 约束型追问检测 — 用户说"200以内/李宁的"但没提新产品 → 承接上文
# ══════════════════════════════════════════════════════════════

# 价格约束模式
_PRICE_CONSTRAINT_PATTERNS = [
    re.compile(r'(\d+)\s*(元\s*)?(以内|以下|以上|左右|上下)'),
    re.compile(r'(不超过|不到|低于|高于|超过)\s*(\d+)\s*元?'),
    re.compile(r'预算\s*(\d+)'),
    re.compile(r'(\d+)\s*块?钱?\s*(的|左右)'),
]

# 纯约束词 — 不含任何产品信息，只是加条件
_CONSTRAINT_ONLY_INDICATORS = [
    "以内", "以下", "以上", "左右", "上下", "不超过", "不到", "低于", "高于", "超过",
    "便宜的", "贵的", "性价比", "实惠", "便宜", "贵",
    "国产", "进口", "大牌", "平价", "高端",
]


def _query_mentions_brand(query: str) -> bool:
    """检测 query 是否提到了具体品牌名（使用 query_analyzer 的 ALL_BRANDS 作为权威来源）"""
    q = query.lower()
    return any(b.lower() in q for b in ALL_BRANDS)


def _is_constraint_only_query(query: str) -> bool:
    """检测 query 是否只是加约束，没有提新的产品/类目/搜索意图。

    例如：
    - "我想200元以内的" → True（只有价格约束）
    - "帮我推荐防晒" → False（有产品词"防晒"）
    - "李宁的有吗" → depends（有品牌但无产品词，且有 last_shown → True）
    """
    msg = query.strip()
    if not msg:
        return False

    # 有搜索/对比关键词 → 不是纯约束
    if any(k in msg for k in _SEARCH_KEYWORDS + _COMPARE_KEYWORDS):
        return False

    # 有具体产品关键词 → 不是纯约束
    if any(kw in msg for kw in SPECIFIC_PRODUCT_KEYWORDS):
        return False

    # 有约束指标 → 是纯约束
    has_price = any(p.search(msg) for p in _PRICE_CONSTRAINT_PATTERNS)
    has_constraint_word = any(kw in msg for kw in _CONSTRAINT_ONLY_INDICATORS)
    has_brand = any(b.lower() in msg.lower() for b in ALL_BRANDS)

    # 有约束指标且消息较短（≤15字）→ 很可能是约束型追问
    if (has_price or has_constraint_word or has_brand) and len(msg) <= 15:
        return True

    return False


def _build_effective_search_query(query: str, last_shown: list, original_category: str) -> str:
    """基于上一轮展示商品 + 原始类目，构建有效的搜索 query。

    当用户 query 只是约束（"200以内"）而没有产品词时，
    从 last_shown 标题中提取产品关键词，构建有意义的搜索词。

    例如：
      query="我想200元以内的", last_shown=[防晒乳, 隔离露, 防晒乳]
      → 返回 "防晒乳 隔离露"（用于检索）
    """
    # 1) 从 last_shown 商品标题中提取产品关键词
    found_keywords = []
    for p in last_shown:
        title = p.get('title', '')
        for kw in SPECIFIC_PRODUCT_KEYWORDS:
            if kw in title and kw not in found_keywords:
                found_keywords.append(kw)

    if found_keywords:
        # 去重后取前 3 个
        effective = ' '.join(found_keywords[:3])
        print(f"[query_enrich] 从 last_shown 提取关键词: {effective}")
        return effective

    # 2) Fallback：用原始类目名
    if original_category:
        # 类目到搜索词映射
        category_search_map = {
            "美妆护肤": "护肤品",
            "服饰运动": "运动鞋服",
            "数码电子": "数码产品",
            "食品饮料": "零食饮品",
            "家居生活": "家居用品",
        }
        effective = category_search_map.get(original_category, original_category)
        print(f"[query_enrich] 用类目 fallback: {effective}")
        return effective

    # 3) 最终 fallback：保留原 query
    return query


# ══════════════════════════════════════════════════════════════
# 负面反馈处理 — 换一批 / 不满意 / 放宽约束
# ══════════════════════════════════════════════════════════════

def _should_handle_dissatisfaction(query: str, session) -> bool:
    """检查是否为负面反馈/换一批请求"""
    return any(k in query for k in _DISSATISFY_WORDS) or any(k in query for k in _BATCH_WORDS)


async def _handle_dissatisfaction(session_id: str, query: str, session, retrieved_products: list,
                                  original_category: str, price_range, preferred_brands) -> str | None:
    """
    处理用户不满/换一批请求。返回 SSE 事件字符串或 None（表示不处理，继续正常流程）。
    """
    # 换一批：在当前约束下取未展示过的
    if any(k in query for k in _BATCH_WORDS):
        # 简单处理：调整 top_k 或告诉用户已展示全部
        if len(retrieved_products) <= 3:
            return (ev_content("已经把符合条件的商品都展示给您啦。要不要放宽一下条件？").to_sse_compact() +
                    ev_clarification("选一个方向：", ["放宽预算", "不限品牌", "重新搜索"]).to_sse_compact() +
                    ev_end(True).to_sse_compact())
        return None  # 交给正常流程（已有 top_k=8 候选池）

    # 不满意/都不行 → 反开调整方向
    if any(k in query for k in _DISSATISFY_WORDS):
        return (ev_content("这些不太合适呀，想从哪方面调整一下？").to_sse_compact() +
                ev_clarification("选一个方向，我帮您重新找：", ["换一批", "放宽预算", "不限品牌", "重新搜索"]).to_sse_compact() +
                ev_end(True).to_sse_compact())

    # 都不是 → 重置
    if "都不是" in query:
        return (ev_content("好的！请告诉我您想找什么商品，也可以发一张图片帮我理解。").to_sse_compact() +
                ev_end(True).to_sse_compact())

    return None


@router.post("/chat")
async def chat(request: ChatRequest, http_request: Request):
    """普通聊天接口"""
    base_url = get_base_url(http_request)
    
    try:
        # 检查服务是否初始化
        _check_services_initialized()
        
        query = request.message
        if not query or not query.strip():
            raise HTTPException(status_code=400, detail="消息内容不能为空")
        
        print(f"收到用户请求: {query[:50]}...")

        # 获取或创建会话
        session = _session_manager.get_session(request.session_id)
        if not session:
            session = _session_manager.create_session(request.session_id)

        _session_manager.update_session(request.session_id, "user", query)

        # 更新用户偏好
        category = detect_category(query)
        # 🔧 跨类目查询：涉及多个类目时不限制检索范围
        if len(detect_all_categories(query)) >= 2:
            category = None
        if category:
            _session_manager.update_preferences(request.session_id, category=category)
        
        detected_price_range = detect_price_range(query)
        if detected_price_range:
            _session_manager.update_preferences(request.session_id, price_range=detected_price_range)

        # 获取会话上下文
        context = {
            "preferences": session.preferences.dict(),
            "interaction_count": session.interaction_count,
            "history": session.get_history(5)
        }

        # 直接走 RAG + AI 生成管道（意图分类已由流式端点上的 agent 处理）
        prefs = session.preferences
        
        # 保存或获取原始类目（保持会话一致性）
        original_category = prefs.category if prefs.category else category
        if original_category:
            _session_manager.update_preferences(request.session_id, category=original_category)
        
        # 提取类目专属偏好
        detected_preference = None
        preference_updates = {}
        
        # 食品生活类目：口味偏好
        flavor_keywords = {'酸': '酸', '甜': '甜', '辣': '辣', '咸': '咸', '清淡': '清淡'}
        for keyword, flavor in flavor_keywords.items():
            if keyword in query and len(query) <= 5:
                preference_updates['flavor_preference'] = flavor
                detected_preference = 'flavor'
                break
        
        # 美妆护肤类目：肤质
        if not detected_preference:
            skin_type_keywords = {'干性': '干性', '油性': '油性', '混合': '混合性', '敏感': '敏感性', '中性': '中性'}
            for keyword, skin_type in skin_type_keywords.items():
                if keyword in query:
                    preference_updates['skin_type'] = skin_type
                    detected_preference = 'skin_type'
                    break
        
        # 数码电子类目：品牌倾向
        if not detected_preference:
            brand_keywords = {'国产': '国产', '华为': '国产', '小米': '国产', '苹果': '国际', '三星': '国际', '性价比': '性价比', '高端': '高端'}
            for keyword, brand_priority in brand_keywords.items():
                if keyword in query:
                    preference_updates['brand_priority'] = brand_priority
                    detected_preference = 'brand'
                    break
        
        # 更新偏好
        if preference_updates:
            _session_manager.update_preferences(request.session_id, **preference_updates)
        
        # 如果用户只是回答偏好，保持原类目不变
        if detected_preference and original_category:
            category = original_category
        
        # 添加意图追踪
        intent_type = 'recommend' if not detected_preference else 'preference'
        intent_data = {
            'category': category,
            'preference': detected_preference,
            'query': query[:30]
        }
        _session_manager.add_intent(request.session_id, intent_type, intent_data)
        
        price_range = prefs.price_range if prefs.price_range != (0, float('inf')) else None
        preferred_brands = prefs.preferred_brands if prefs.preferred_brands else None
        disliked_brands = prefs.disliked_brands if prefs.disliked_brands else None

        from rag.prompt import build_prompt
        retrieved_products = _retriever.search(
            query,
            top_k=5,
            category_filter=category,
            price_range=price_range,
            preferred_brands=preferred_brands,
            disliked_brands=disliked_brands
        )

        # 如果没有检索到任何商品，直接告知用户，不让 AI 编造
        if not retrieved_products:
            no_result_msg = "抱歉，暂时没有找到符合您需求的商品。可以换个关键词试试，或者告诉我您想要什么类型的商品～"
            _session_manager.update_session(request.session_id, "assistant", no_result_msg)
            return {
                "reply_text": no_result_msg,
                "products": [],
                "need_more_info": False,
                "questions": [],
                "session_id": request.session_id
            }

        # 构建完整的上下文传递给提示词（🆕 含对话历史）
        session_dict = session.dict()
        prompt_context = {
            'original_category': original_category,
            'interaction_count': session.interaction_count,
            'session': session_dict,
            'conversation_history': session_dict.get('messages', []),
        }
        prompt = build_prompt(query, retrieved_products, prompt_context)
        ai_response = await _doubao_service.generate_response(prompt)
        clean_response = strip_product_card_markers(ai_response)

        _session_manager.update_session(request.session_id, "assistant", clean_response)

        # 生成会话摘要（节省Token）
        try:
            from services.summary_generator import SummaryGenerator
            summary_generator = SummaryGenerator(_doubao_service)
            new_summary = await summary_generator.generate_summary(
                session.get_history(),
                session.preferences.dict()
            )
            _session_manager.set_session_summary(request.session_id, new_summary)
        except Exception as e:
            print(f"生成会话摘要失败: {e}")

        # 提取推荐的商品ID
        recommended_ids = []
        card_ids = PRODUCT_CARD_PATTERN.findall(ai_response)
        if card_ids:
            recommended_ids = [pid.strip() for pid in card_ids]

        # 筛选商品
        recommended_products = [
            p for p in retrieved_products if p.id in recommended_ids
        ] if recommended_ids else retrieved_products

        products_dict = products_to_dict_list(recommended_products, base_url)

        return {
            "reply_text": clean_response,
            "products": products_dict,
            "need_more_info": False,
            "questions": [],
            "session_id": request.session_id
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"错误详情: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"堆栈信息:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request):
    """流式聊天接口"""
    from fastapi.responses import StreamingResponse
    
    base_url = get_base_url(http_request)

    async def generate():
        try:
            _check_services_initialized()

            query = request.message
            if not query or not query.strip():
                yield ev_error("INVALID_INPUT", "消息内容不能为空").to_sse_compact()
                return

            # ── 1. 会话管理（🆕 支持 DB 恢复）─────────────────
            session = await _session_manager.get_or_restore_session(request.session_id)
            if not session:
                session = _session_manager.create_session(request.session_id)
                # 🆕 持久化：新会话写入 DB
                try:
                    await db.create_session(request.session_id)
                except Exception as e:
                    print(f"[db] 创建会话失败（非致命）: {e}")

            _session_manager.update_session(request.session_id, "user", query)
            # 🆕 持久化：用户消息写入 DB
            try:
                await db.add_message(request.session_id, "user", query)
            except Exception as e:
                print(f"[db] 保存用户消息失败（非致命）: {e}")

            # ── 2. 图像搜索路径 ───────────────────────────
            image_base64 = request.image_base64
            if image_base64 and _image_service:
                from models.events import image_searching, product_card_compact as ev_pcard
                import base64 as b64

                print(f"[image_search] 收到图片 base64, 长度={len(image_base64)}, query={query[:50]}", flush=True)
                yield image_searching("正在分析图片…").to_sse_compact()

                image_data = None
                try:
                    image_data = b64.b64decode(image_base64)
                    print(f"[image_search] base64 解码成功, 大小={len(image_data)} bytes", flush=True)
                    products, analysis = await _image_service.search_similar_products_by_image(
                        image_data, _retriever
                    )
                    print(f"[image_search] 搜索完成, 找到 {len(products)} 个商品", flush=True)
                except Exception as e:
                    print(f"[image_search] 向量检索失败，降级 VLM: {e}", flush=True)
                    if image_data is not None:
                        try:
                            products, analysis = await _image_service.search_similar_products(image_data, _retriever)
                            print(f"[image_search] VLM 降级成功, 找到 {len(products)} 个商品", flush=True)
                        except Exception as e2:
                            print(f"[image_search] VLM 降级也失败: {e2}", flush=True)
                            yield ev_content("抱歉，图片分析遇到了问题，请稍后重试。").to_sse_compact()
                            yield ev_end(True).to_sse_compact()
                            return
                    else:
                        print(f"[image_search] base64 解码失败，无法继续", flush=True)
                        yield ev_content("抱歉，图片数据解析失败，请重新拍照发送。").to_sse_compact()
                        yield ev_end(True).to_sse_compact()
                        return

                # 生成过渡文案
                obj_name = analysis.get("object_name", "") if isinstance(analysis, dict) else ""
                has_match = len(products) > 0
                print(f"[image_search] analysis={json.dumps(analysis, ensure_ascii=False)[:200] if isinstance(analysis, dict) else str(analysis)[:200]}", flush=True)
                # 如果用户附带文字（如「找同款」），融合到回复中
                user_text_hint = f"，你说「{query}」，我帮你筛选了最接近的" if query.strip() else ""
                if obj_name:
                    if has_match:
                        reply = f"我看到你拍的啦～这是一个{obj_name}{user_text_hint}，帮你找了几款相关的商品～"
                    else:
                        reply = f"嗯嗯我看到啦，这是一个{obj_name}～不过目前暂时还没有这类商品呢。要不要跟我说说你想要什么样的？"
                else:
                    reply = (f"我看到你拍的照片啦{user_text_hint}，帮你找了几款相似的商品，看看有没有喜欢的～" if has_match else
                             "我看到你的照片啦～但目前暂时没有找到匹配的商品呢。可以描述一下你想要什么类型的～")

                print(f"[image_search] 即将发送回复: {reply[:80]}", flush=True)
                yield ev_content(reply).to_sse_compact()
                print(f"[image_search] 已发送 content 事件", flush=True)

                # 如果用户附带文字，用文字过滤/精排图片搜索结果
                if query.strip() and len(products) > 3:
                    try:
                        from rag.relevance_checker import relevance_checker
                        relevance_checker.set_service(_doubao_service)
                        filtered, _ = await relevance_checker.check(query, products, min_keep=2)
                        if filtered:
                            products = filtered
                    except Exception as e:
                        print(f"[image_search] 文字过滤失败: {e}", flush=True)

                # 推送商品卡片
                for p in products[:5]:
                    pd_ = p if isinstance(p, dict) else (p.to_dict(base_url=base_url) if hasattr(p, 'to_dict') else {})
                    pid = pd_.get('id', '') if isinstance(pd_, dict) else getattr(p, 'id', '')
                    yield ev_pcard(pid, pd_).to_sse_compact()

                _session_manager.update_session(request.session_id, "assistant", reply)
                print(f"[image_search] 即将发送 end 事件", flush=True)
                yield ev_end(True).to_sse_compact()
                print(f"[image_search] 已发送 end 事件，图片搜索流程结束", flush=True)
                return

            # ── 3. thinking 事件（即时反馈）─────────────────────
            yield thinking("正在理解您的需求...").to_sse_compact()

            # ── 4. 规则快速通道：秒级意图判定 ──────────────────
            t0 = time.time()
            last_shown = getattr(session, 'last_shown_products', []) or []
            quick = _quick_classify(query, last_shown)
            is_quick = quick is not None
            if is_quick:
                print(f"[perf] quick_classify: {time.time()-t0:.3f}s → {quick['intent']}")
            else:
                # LLM fallback：覆盖规则 miss 的长尾意图（🆕 带上下文）
                llm_intent = await _llm_classify_intent(query, _doubao_service, last_shown)
                if llm_intent != "search":
                    quick = {"intent": llm_intent, "params": {"query": query}}
                    is_quick = True
                    print(f"[perf] llm_classify: {time.time()-t0:.3f}s → {llm_intent}")

            # 🆕 如果正在下单流程中（confirm_address / confirm_final），直接交给 order_agent
            order_state = getattr(session, 'order_state', {}) or {}
            if order_state.get("step") in ("confirm_address", "confirm_final"):
                from agent.order_agent import order_agent as ord_agt
                async for event_str in ord_agt.run(request.session_id, query, {}, base_url=base_url):
                    yield event_str
                yield ev_end(True).to_sse_compact()
                return

            # 🆕 如果购物车有未确认的多规格候选，直接交给 cart_agent
            if getattr(session, 'cart_clarify_candidates', None):
                from agent.cart_agent import cart_agent as crt_agt
                async for event_str in crt_agt.run(request.session_id, query, {"action": "add"}, base_url=base_url):
                    yield event_str
                yield ev_end(True).to_sse_compact()
                return

            # ── 5. 类目检测 ───────────────────────────────────
            category = detect_category(query)

            # 🔧 跨类目查询检测：query 涉及多个类目时（如"露营的零食和衣服"），
            # 不限制单一类目检索，避免漏掉其他类目的商品
            all_detected_cats = detect_all_categories(query)
            multi_category = len(all_detected_cats) >= 2
            if multi_category:
                print(f"[category] 跨类目查询: {all_detected_cats}，不限制类目检索")
                category = None

            prefs = session.preferences if session else None
            existing_category = prefs.category if prefs else None

            # 如果是简单回答（短文本且检测到不同类目），保持原类目
            _PREF_ONLY_KEYWORDS = ['酸', '甜', '辣', '咸', '便宜', '贵', '实惠', '性价比', '高端', '好看', '好用', '耐用', '轻便']
            if (len(query) <= 5 and category and existing_category
                    and category != existing_category
                    and any(k in query for k in _PREF_ONLY_KEYWORDS)):
                category = existing_category

            # 🔧 修复：当用户明确搜索不同类目时，允许切换
            # 避免 "帮我推荐马拉松衣服鞋子" 被之前浏览食品的 session 类目覆盖
            if category and existing_category and category != existing_category:
                # 用户 query 包含搜索意图 + 明确类目关键词 → 切换到新类目
                if any(k in query for k in _SEARCH_KEYWORDS) or len(query) > 10:
                    print(f"[category] 类目切换: {existing_category} → {category}（query: {query[:40]}）")
                    existing_category = category
                    # 🔧 类目切换时，清除旧的品牌偏好（避免"防晒"搜出"nike美妆"）
                    if not _query_mentions_brand(query):
                        _session_manager.update_preferences(request.session_id, preferred_brands=[])
                        print(f"[category] 类目切换 → 清除旧品牌偏好")

            original_category = existing_category if existing_category else category
            # 🔧 跨类目查询：不限制单一类目检索范围
            if multi_category:
                original_category = None
            if original_category:
                _session_manager.update_preferences(request.session_id, category=original_category)

            # ── 6. 澄清检测 ───────────────────────────────────
            is_clarifying_response = any(
                intent.get('type') in ('clarifying', 'recommend', 'preference', 'clarified')
                for intent in session.intent_chain[-2:]
            )

            # 对 scene/compare/cart/order 意图跳过 analyze_query（结果不会被使用）
            if quick and quick.get('intent') in ('scene', 'compare', 'cart', 'order'):
                analysis = {'is_vague': False, 'preferences': {}}
            else:
                analysis = analyze_query(query, category)

            # 用户说了"都想要/都看看/都行" → 直接推荐，不追问
            user_wants_show_now = any(w in query for w in _SHOW_NOW_WORDS)

            if not is_clarifying_response and analysis['is_vague'] and not user_wants_show_now:
                clarification_text = ""
                try:
                    clarification_prompt = get_clarification_prompt(category or "通用", query)
                    async for chunk in _doubao_service.stream_response(clarification_prompt):
                        clarification_text += chunk
                        yield ev_content(chunk).to_sse_compact()
                except Exception as e:
                    print(f"生成澄清问题失败: {e}")
                    clarification_text = "可以说得更详细一点吗？比如你更看重哪些方面、预算大概多少呀～"
                    yield ev_content(clarification_text).to_sse_compact()

                _session_manager.update_session(request.session_id, "assistant", clarification_text)
                _session_manager.add_intent(request.session_id, "clarifying", {"category": original_category})
                yield ev_end(True).to_sse_compact()
                return

            # ── 7. 场景响应：主题按钮点击 ─────────────────
            scene_ctx = getattr(session, 'scene_context', None)
            if query.startswith("了解") and scene_ctx:
                theme_name = query[2:].strip()
                topic_query = None
                for t in scene_ctx.get("topics", []):
                    if t["theme"] == theme_name:
                        topic_query = t["query"]
                        break
                if topic_query:
                    query = topic_query
                    category = detect_category(query)
                    original_category = category
                    user_wants_show_now = True  # 场景主题直接出卡，不追问
                else:
                    yield ev_content(f"抱歉，没找到「{theme_name}」这个主题。").to_sse_compact()
                    yield ev_end(True).to_sse_compact()
                    return

            # ── 8. 场景检测：长场景描述 → scene_agent ────
            # 意图分类（quick_classify + LLM fallback）已做完全部判定，
            # 无需重复对 _COMPARE_KEYWORDS/_SEARCH_KEYWORDS/_SCENE_KEYWORDS 做 any() 扫描
            is_scene = quick is not None and quick.get('intent') == 'scene'

            if is_scene:
                # 状态机校验 + 转移
                current_state = AgentState(getattr(session, 'agent_state', 'browsing'))
                if not is_agent_allowed(current_state, 'scene'):
                    yield ev_content(f"当前在{current_state.value}状态，不支持场景规划哦。").to_sse_compact()
                    yield ev_end(True).to_sse_compact()
                    return
                next_state = get_next_state(current_state, 'scene')
                session.agent_state = next_state.value
                _session_manager.add_intent(request.session_id, 'scene', {"query": query[:30]})

                from agent.scene_agent import scene_agent as scn_agt
                async for event_str in scn_agt.run(request.session_id, query, quick.get('params', {}) if quick else {}):
                    yield event_str
                yield ev_end(True).to_sse_compact()
                return

            # ── 9. 意图追踪 ───────────────────────────────────
            intent_type = 'recommend' if not any(k in query for k in ['酸', '甜', '辣', '咸', '干', '油', '混合', '混油', '混干', '敏感', '中性']) else 'preference'
            intent_data = {'category': category, 'query': query[:30]}
            _session_manager.add_intent(request.session_id, intent_type, intent_data)

            # ── 10. 状态机路由 ────────────────────────────
            # 从会话推导当前状态（默认 BROWSING）
            current_state = AgentState(getattr(session, 'agent_state', 'browsing'))

            # 意图判定
            if quick and quick['intent'] in ('compare', 'cart', 'order'):
                intent = quick['intent']
            elif any(kw in query for kw in _COMPARE_KEYWORDS):
                intent = 'compare'
            else:
                intent = 'search'

            # 状态机校验：当前状态是否允许此操作
            if not is_agent_allowed(current_state, intent):
                yield ev_content(f"当前在{current_state.value}状态，不支持该操作哦。").to_sse_compact()
                yield ev_end(True).to_sse_compact()
                return

            # 计算并持久化下一状态
            next_state = get_next_state(current_state, intent)
            session.agent_state = next_state.value
            _session_manager.add_intent(request.session_id, intent, {"category": original_category})

            if intent == 'compare':
                from agent.compare_agent import compare_agent as comp_agt
                shown_pids = []
                async for event_str in comp_agt.run(request.session_id, query, quick.get('params', {}) if quick else {}, base_url=base_url):
                    yield event_str
                    pid = _extract_product_id_from_event(event_str)
                    if pid and pid not in shown_pids:
                        shown_pids.append(pid)
                if shown_pids:
                    session.last_shown_products = [{"product_id": pid, "title": ""} for pid in shown_pids[:5]]
                yield ev_end(True).to_sse_compact()
                return

            if intent == 'cart':
                params = quick.get('params', {}) if quick else {}
                if not params.get('action'):
                    params['action'] = _quick_cart_action(query)
                from agent.cart_agent import cart_agent as crt_agt
                async for event_str in crt_agt.run(request.session_id, query, params, base_url=base_url):
                    yield event_str
                yield ev_end(True).to_sse_compact()
                return

            if intent == 'order':
                from agent.order_agent import order_agent as ord_agt
                async for event_str in ord_agt.run(request.session_id, query, quick.get('params', {}) if quick else {}, base_url=base_url):
                    yield event_str
                yield ev_end(True).to_sse_compact()
                return

            # ── 11. 搜索路径 ───────────────────────────────────
            extracted = analysis['preferences']
            # 从原始消息补充 LLM 可能漏填的排除约束（RAGent 模式）
            extracted = _enrich_filters_from_message(extracted, query)
            extracted_price = extracted.pop('price_range', None)
            if extracted_price:
                _session_manager.update_preferences(request.session_id, price_range=extracted_price)
            if extracted:
                _session_manager.update_preferences(request.session_id, **extracted)

            if is_clarifying_response:
                pref = session.preferences
                price_range = pref.price_range if pref.price_range != (0, float('inf')) else None
                preferred_brands = pref.preferred_brands if pref.preferred_brands else None
                disliked_brands = pref.disliked_brands if pref.disliked_brands else None
                _session_manager.add_intent(request.session_id, "clarified", {"category": original_category})
            else:
                price_range = extracted_price
                preferred_brands = extracted.get('preferred_brands') if extracted else None
                disliked_brands = extracted.get('exclude_brands') if extracted else None

            # 负面反馈
            if _should_handle_dissatisfaction(query, session):
                dissat_result = await _handle_dissatisfaction(
                    request.session_id, query, session, [],
                    original_category or category, price_range, preferred_brands
                )
                if dissat_result:
                    yield dissat_result
                    _session_manager.update_session(request.session_id, "assistant", query)
                    return

            # 🆕 位置指代解析：把"第一个"映射为真实 product_id
            if quick and quick.get('params', {}).get('product_id'):
                resolved = resolve_product_id(
                    quick['params']['product_id'],
                    last_shown,
                    query,
                )
                if resolved:
                    quick['params']['product_id'] = resolved

            # 🆕 约束型追问检测：用户说"200以内/李宁的"但没提新产品 → 改写搜索 query
            # 核心修复：避免用 "我想200元以内的" 这种无产品词的 query 去检索
            effective_search_query = query
            if last_shown and original_category and _is_constraint_only_query(query):
                effective_search_query = _build_effective_search_query(query, last_shown, original_category)
                print(f"[context] 🔗 检测到约束型追问 → 搜索 query 改写: '{query[:40]}' → '{effective_search_query}'")

            # 委托给 SearchAgent
            from agent.search_agent import search_agent as srch_agt
            shown_product_ids = []  # 🆕 收集本轮展示的商品 ID
            async for event_str in srch_agt.run(
                session_id=request.session_id,
                query=query,
                search_query=effective_search_query,  # 🆕 用于检索的有效 query
                last_shown=last_shown,  # 🆕 上一轮展示的商品，注入 prompt
                category=category,
                original_category=original_category,
                price_range=price_range,
                preferred_brands=preferred_brands,
                disliked_brands=disliked_brands,
                extracted_prefs=extracted,
                is_clarifying_response=is_clarifying_response,
                user_wants_show_now=user_wants_show_now,
                interaction_count=session.interaction_count,
                intent_chain=session.intent_chain,
                base_url=base_url,
            ):
                yield event_str
                # 🆕 从 product_card 事件中提取商品 ID，用于下轮位置指代解析
                pid = _extract_product_id_from_event(event_str)
                if pid and pid not in shown_product_ids:
                    shown_product_ids.append(pid)

            # 更新 last_shown_products（供下轮"第一个"等位置指代使用）
            if shown_product_ids:
                from utils.product_repo import product_repo as _repo
                new_shown = []
                for pid in shown_product_ids[:5]:
                    title = ""
                    try:
                        p = _repo.get(pid)
                        if p:
                            title = getattr(p, 'title', '')
                    except Exception:
                        pass
                    new_shown.append({"product_id": pid, "title": title})
                session.last_shown_products = new_shown

            yield ev_end(True).to_sse_compact()

        except HTTPException as e:
            yield ev_error("HTTP_ERROR", e.detail).to_sse_compact()
        except Exception as e:
            print(f"流式接口错误详情: {type(e).__name__}: {str(e)}")
            import traceback
            print(f"堆栈信息:\n{traceback.format_exc()}")
            yield ev_error("INTERNAL_ERROR", f"{type(e).__name__}: {str(e)}").to_sse_compact()

    return StreamingResponse(generate(), media_type="text/event-stream")
