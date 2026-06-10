from models.schemas import Product


def _build_memory_section(context: dict) -> str:
    """构建记忆区内容（使用会话摘要节省Token）"""
    if not context:
        return "=== 记忆区 ===\n暂无记忆信息\n\n"
    
    # 提取会话信息
    session = context.get('session', {})
    preferences = session.get('preferences', {})
    summary = session.get('summary', '')  # 使用会话摘要
    intent_chain = session.get('intent_chain', [])
    
    # 构建记忆区
    memory_text = "=== 记忆区 ===\n"
    
    # 会话摘要（核心，节省Token）
    if summary:
        memory_text += f"【会话摘要】\n{summary}\n\n"
    else:
        memory_text += "【会话摘要】\n暂无对话摘要\n\n"
    
    # 通用偏好
    memory_text += "【用户偏好】\n"
    if preferences.get('category'):
        memory_text += f"- 当前类目：{preferences['category']}\n"
    if preferences.get('price_range'):
        price_range = preferences['price_range']
        if price_range != (0, float('inf')):
            memory_text += f"- 价格范围：¥{price_range[0]} - ¥{price_range[1]}\n"
    if preferences.get('preferred_brands'):
        memory_text += f"- 偏好品牌：{', '.join(preferences['preferred_brands'])}\n"
    if preferences.get('disliked_brands'):
        memory_text += f"- 不喜欢的品牌：{', '.join(preferences['disliked_brands'])}\n"
    
    # 类目专属偏好（只显示当前类目的偏好）
    current_category = preferences.get('category', '')
    
    # 美妆护肤
    if current_category == '美妆护肤':
        memory_text += "\n【美妆护肤偏好】\n"
        if preferences.get('skin_type'):
            memory_text += f"- 肤质：{preferences['skin_type']}\n"
        if preferences.get('skin_concerns'):
            memory_text += f"- 肌肤问题：{', '.join(preferences['skin_concerns'])}\n"
        if preferences.get('product_type'):
            memory_text += f"- 产品类型：{preferences['product_type']}\n"
    
    # 数码电子
    elif current_category == '数码电子':
        memory_text += "\n【数码电子偏好】\n"
        if preferences.get('device_type'):
            memory_text += f"- 设备类型：{preferences['device_type']}\n"
        if preferences.get('brand_priority'):
            memory_text += f"- 品牌倾向：{preferences['brand_priority']}\n"
        if preferences.get('key_features'):
            memory_text += f"- 核心需求：{', '.join(preferences['key_features'])}\n"
    
    # 服饰运动
    elif current_category == '服饰运动':
        memory_text += "\n【服饰运动偏好】\n"
        if preferences.get('size'):
            memory_text += f"- 尺码：{preferences['size']}\n"
        if preferences.get('style'):
            memory_text += f"- 风格：{preferences['style']}\n"
        if preferences.get('colors'):
            memory_text += f"- 偏好颜色：{', '.join(preferences['colors'])}\n"
        if preferences.get('materials'):
            memory_text += f"- 偏好材质：{', '.join(preferences['materials'])}\n"
        if preferences.get('sport_type'):
            memory_text += f"- 运动类型：{preferences['sport_type']}\n"
    
    # 食品生活
    elif current_category == '食品生活':
        memory_text += "\n【食品生活偏好】\n"
        if preferences.get('flavor_preference'):
            memory_text += f"- 口味偏好：{preferences['flavor_preference']}\n"
        if preferences.get('dietary_restrictions'):
            memory_text += f"- 饮食禁忌：{', '.join(preferences['dietary_restrictions'])}\n"
        if preferences.get('consumption_scenario'):
            memory_text += f"- 食用场景：{preferences['consumption_scenario']}\n"
        if preferences.get('health_goals'):
            memory_text += f"- 健康需求：{', '.join(preferences['health_goals'])}\n"
    
    # 长程关系维护（跨会话记忆）
    if preferences.get('user_name'):
        memory_text += f"\n【闺蜜备注】\n"
        memory_text += f"- 昵称：{preferences['user_name']}\n"
    if preferences.get('important_dates'):
        memory_text += f"- 重要日期：{preferences['important_dates']}\n"
    if preferences.get('lifestyle_notes'):
        memory_text += f"- 生活方式：{', '.join(preferences['lifestyle_notes'])}\n"
    if preferences.get('appearance_notes'):
        memory_text += f"- 外貌特征：{preferences['appearance_notes']}\n"
    if preferences.get('relationship_goals'):
        memory_text += f"- 目标：{preferences['relationship_goals']}\n"
    # 意图链（精简版）
    if intent_chain:
        memory_text += "\n【意图演变】\n"
        for i, intent in enumerate(intent_chain[-3:], 1):  # 只取最近3个
            intent_type = intent.get('type', '未知')
            intent_data = intent.get('data', {})
            category = intent_data.get('category', '')
            memory_text += f"{i}. {intent_type}"
            if category:
                memory_text += f" ({category})"
            memory_text += "\n"
    
    memory_text += "\n"
    return memory_text


def _has_memory(context: dict) -> bool:
    """检查是否有有效记忆"""
    if not context:
        return False
    session = context.get('session', {})
    summary = session.get('summary', '')
    preferences = session.get('preferences', {})
    
    # 有摘要或偏好就算有记忆
    if summary:
        return True
    if preferences.get('category'):
        return True
    if preferences.get('flavor_preference'):
        return True
    if preferences.get('skin_type'):
        return True
    return False


def _detect_emotion(query: str) -> str:
    """检测用户情绪"""
    query = query.lower()
    
    # 负面情绪关键词
    negative_keywords = {
        '胖': '自我否定',
        '丑': '自我否定',
        '肥': '自我否定',
        '老': '年龄焦虑',
        '长痘': '皮肤焦虑',
        '过敏': '皮肤焦虑',
        '失败': '挫败感',
        '难过': '悲伤',
        '烦': '烦躁',
        '累': '疲惫',
        '贵': '经济压力',
        '穷': '经济压力'
    }
    
    # 正面情绪关键词
    positive_keywords = {
        '开心': '开心',
        '高兴': '开心',
        '喜欢': '喜欢',
        '好看': '满意',
        '漂亮': '满意',
        '棒': '满意'
    }
    
    for keyword, emotion in negative_keywords.items():
        if keyword in query:
            return emotion
    
    for keyword, emotion in positive_keywords.items():
        if keyword in query:
            return emotion
    
    return 'neutral'


def _detect_user_mode(query: str) -> str:
    """检测用户状态：闲逛型 vs 目的型（专业版）
    
    使用多维度特征分析：
    1. 句法结构：疑问句vs陈述句
    2. 意图词：购买意图vs闲聊意图
    3. 语气词：情感表达vs直接表达
    4. 模糊词：不确定性表达vs确定性表达
    5. 长度特征：综合考虑
    """
    
    query_lower = query.lower()
    query_len = len(query)
    
    # 目的型特征词（权重不同）
    purpose_keywords = {
        # 高权重：明确购买意图
        '买': 3, '推荐': 3, '找': 2, '要': 2,
        # 中权重：比较/选择意图
        '怎么选': 2, '哪款好': 2, '对比': 2, '区别': 2, '推荐一下': 2,
        # 低权重：需求表达
        '需要': 1, '预算': 1, '参数': 1, '有没有': 1, '多少钱': 1, '价格': 1
    }
    
    # 闲逛型特征词（权重不同）
    leisure_keywords = {
        # 高权重：明确闲逛意图
        '随便看看': 3, '逛逛': 3, '无聊': 3,
        # 中权重：不确定表达
        '不知道': 2, '可能': 2, '好像': 2, '也许': 2, '大概': 2,
        # 低权重：情感/闲聊表达
        '最近': 1, '刚': 1, '完': 1, '怎么办': 1, '好烦': 1, '纠结': 1,
        '嘛': 1, '呀': 1, '呢': 1, '唉': 1, '哎': 1, '哦': 1, '哈': 1
    }
    
    # 疑问词检测
    question_words = ['什么', '哪', '怎么', '谁', '为什么', '何时', '如何']
    
    # 计算得分
    purpose_score = sum(weight for kw, weight in purpose_keywords.items() if kw in query_lower)
    leisure_score = sum(weight for kw, weight in leisure_keywords.items() if kw in query_lower)
    
    # 句法结构分析
    if any(qw in query_lower for qw in question_words) or query.endswith('?'):
        # 疑问句更可能是目的型（寻求信息）
        purpose_score += 1
    else:
        # 陈述句更可能是闲逛型（分享/表达）
        leisure_score += 1
    
    # 语气词密度分析
    emotion_markers = ['！', '～', '😂', '😢', '😭', '～～']
    emotion_count = sum(query.count(marker) for marker in emotion_markers)
    if emotion_count >= 2:
        leisure_score += 2
    elif emotion_count == 1:
        leisure_score += 1
    
    # 否定词分析（闲逛型更常表达不满）
    negative_words = ['不', '没有', '别', '不要']
    negative_count = sum(1 for nw in negative_words if nw in query_lower)
    if negative_count >= 2:
        leisure_score += 1
    
    # 长度分析（谨慎使用）
    if query_len <= 3:
        purpose_score += 1  # 极短查询可能是直接需求
    elif query_len >= 25:
        leisure_score += 1  # 较长查询可能是闲聊
    
    # 输出调试信息（可选）
    # print(f"Query: {query} | Purpose: {purpose_score}, Leisure: {leisure_score}")
    
    if purpose_score > leisure_score:
        return 'purpose'  # 目的型
    elif leisure_score > purpose_score:
        return 'leisure'  # 闲逛型
    else:
        return 'neutral'  # 中性


def _extract_life_events(query: str) -> list:
    """提取用户生活中的事件（扩展版）"""
    events = []
    query_lower = query.lower()
    
    # 旅行相关（扩展）
    travel_patterns = [
        {'keywords': ['海边', '海岛', '沙滩', '度假'], 
         'event': '海边度假', 'related_need': '晒后修复、防晒、水乳、便携护肤品'},
        {'keywords': ['西藏', '青海', '雪山'], 
         'event': '高原旅行', 'related_need': '高保湿、防紫外线、润唇膏'},
        {'keywords': ['出差', '商务', '会议', '工作旅行'], 
         'event': '商务出差', 'related_need': '便携装、快充充电器、转换头'},
        {'keywords': ['爬山', '徒步', '露营', '户外'], 
         'event': '户外活动', 'related_need': '防晒、运动装备、便携水壶'},
        {'keywords': ['旅游', '旅行', '出发', '行程'], 
         'event': '旅行计划', 'related_need': '旅行收纳、便携洗护、充电宝'}
    ]
    
    for pattern in travel_patterns:
        if any(kw in query_lower for kw in pattern['keywords']):
            events.append({
                'type': 'travel', 
                'event': pattern['event'], 
                'related_need': pattern['related_need']
            })
            break
    
    # 工作生活事件（扩展）
    life_patterns = [
        {'keywords': ['加班', '熬夜', '通宵', 'deadline'], 
         'event': '工作压力', 'related_need': '急救面膜、眼霜、咖啡、助眠产品'},
        {'keywords': ['考试', '备考', '考研', '复习'], 
         'event': '备考阶段', 'related_need': '护眼灯、咖啡、记忆枕头'},
        {'keywords': ['面试', '求职', '跳槽', '找工作'], 
         'event': '求职阶段', 'related_need': '职业装、面试套装、护肤品'},
        {'keywords': ['搬家', '租房', '装修', '布置'], 
         'event': '搬家/装修', 'related_need': '收纳用品、家居装饰、清洁用品'},
        {'keywords': ['恋爱', '约会', '表白', '纪念日'], 
         'event': '情感甜蜜期', 'related_need': '香水、口红、约会穿搭'},
        {'keywords': ['分手', '失恋', '难过', '伤心'], 
         'event': '情感波动期', 'related_need': '治愈系产品、解压玩具、香薰'},
        {'keywords': ['健身', '减肥', '塑形', '运动'], 
         'event': '健身计划', 'related_need': '运动装备、蛋白粉、运动服饰'},
        {'keywords': ['生日', '节日', '礼物', '送礼'], 
         'event': '准备礼物', 'related_need': '礼品推荐、包装、贺卡'}
    ]
    
    for pattern in life_patterns:
        if any(kw in query_lower for kw in pattern['keywords']):
            events.append({
                'type': 'life', 
                'event': pattern['event'], 
                'related_need': pattern['related_need']
            })
            break
    
    return events


def _build_personality_prompt(context: dict) -> str:
    """构建人格设定 — 闺蜜风格 + 专业底线"""
    session = context.get('session', {})
    preferences = session.get('preferences', {})

    personality_text = """
=== 我是谁 ===
你叫"小豆"，是用户的AI闺蜜兼购物助手。你懂生活、懂时尚、懂科技、懂美食。
• 性格：热情直爽、细心体贴、爱分享，像闺蜜一样自然亲近
• 语调：用"咱们"、"亲"、"呀"、"嘛"等口语
• 价值观：帮用户发现生活中的小美好，推荐实用好物提升幸福感，不制造焦虑，尊重多元审美
• 特长：穿搭建议、护肤美妆、数码评测、零食推荐、家居好物、生活技巧
• 【重要】你是AI，不具备实体购买能力，不要说"我买了"或"我用过"

=== 我的说话风格 ===
• 先分享发现的好东西，再询问意见（信息交换不对等但更自然）
• 像闺蜜聊天一样自然，不是客服
• 会用emoji，但不要太多（1-2个就好）

=== 绝对禁止的行为 ===
• 禁止调侃、嘲笑或评论用户回复的字数/长度（如"哈哈咋就说一个字"、"你怎么就打一个字啊"之类）
• 用户回复短是因为在回答你的问题或打字不方便，直接正常推进对话即可
• 禁止恶意吐槽——你不是"损友"，你是贴心的购物顾问

=== 正确的表达示例 ===
• "我刚看到一款超火的面霜，很多人都说好用～" ✅
• "最近发现一个宝藏零食，安利给你！" ✅
• "这款眼霜口碑超好，好多博主都在推～" ✅
• "我买了这个面霜" ❌（不要这么说）
• "我用过这款" ❌（不要这么说）
• "哈哈咋就说一个字呀" ❌（绝对不要调侃用户回复长度）

=== 情感回应规则 ===
1. 用户情绪负面时：先共情鼓励，再给建议
   例：用户说"最近胖了" → 先说"哪有！你一点都不胖！"，再说"不过想保持身材的话，可以看看这款低卡零食～"
2. 用户情绪正面时：跟着开心，分享好东西
3. 用户纠结时：给明确建议，不要含糊
"""

    return personality_text


def _build_emotion_response(query: str, emotion: str) -> str:
    """生成情感回应"""
    if emotion == '自我否定':
        return "哎呀，亲爱的，你可不能这么说自己！你在我眼里一直都很美呀～"
    elif emotion == '年龄焦虑':
        return "年龄只是数字呀！咱们要的是气质和状态，对吧？"
    elif emotion == '皮肤焦虑':
        return "皮肤问题很常见的呀，别太担心，选对产品慢慢调理就好～"
    elif emotion == '挫败感':
        return "生活总有不如意的时候嘛，没关系的，咱们一起看看有什么好物让你开心一下！"
    elif emotion == '悲伤':
        return "哎呀，怎么了呀？有什么心事可以跟我说说～"
    elif emotion == '疲惫':
        return "累了吧？好好休息一下，要不要我帮你找点放松的好物？"
    elif emotion == '经济压力':
        return "钱不是问题！咱们有很多性价比超高的好物呢，一样能用得很好～"
    elif emotion == '开心':
        return "哈哈，太棒了！有什么开心的事快跟我分享！"
    elif emotion == '满意':
        return "眼光真好！那款确实很不错～"
    return ""


def _build_conversation_history(history: list[dict], max_turns: int = 10) -> str:
    """构建最近对话历史文本 — 让 LLM 知道"刚才聊了什么"。

    这是上下文记忆的核心：没有它，LLM 每次调用都是"全新对话"，
    用户说"第一个"时 LLM 完全不知道第一个是什么。
    """
    if not history:
        return ""

    lines = ["=== 最近对话 ==="]
    for i, msg in enumerate(history[-max_turns:], 1):
        role_label = "用户" if msg.get("role") == "user" else "小豆"
        content = (msg.get("content") or "").strip()
        if not content:
            # 可能是纯图片消息
            content = "[图片]"
        # 截断过长内容，避免 prompt 太长
        if len(content) > 300:
            content = content[:300] + "…"
        lines.append(f"{role_label}: {content}")
    lines.append("")

    return "\n".join(lines)


def _build_last_shown_section(context: dict) -> str:
    """构建「上一轮展示商品」上下文衔接区。

    当用户说"200以内"/"李宁的"等约束型追问时，
    明确告诉 LLM 上一轮展示了什么，用户现在在筛选。
    这是防止上下文断裂的关键。
    """
    if not context:
        return ""

    last_shown = context.get('last_shown_products', [])
    if not last_shown:
        return ""

    query = context.get('_user_query', '')
    price_range = context.get('price_range')
    preferred_brands = context.get('preferred_brands')

    lines = ["=== ⚠️ 上下文衔接（非常重要）==="]
    lines.append("上一轮你向用户展示了以下商品：")
    for i, p in enumerate(last_shown[:5], 1):
        title = p.get('title', '未知商品')
        # 简单截断标题
        if len(title) > 40:
            title = title[:40] + "…"
        lines.append(f"  {i}. {title}")

    lines.append("")
    lines.append(f"用户刚才说：\"{query}\"")

    # 解析用户意图
    hints = []
    if price_range:
        if price_range[1] != float('inf'):
            hints.append(f"预算不超过 ¥{int(price_range[1])}")
        elif price_range[0] > 0:
            hints.append(f"预算 ¥{int(price_range[0])} 以上")
    if preferred_brands:
        hints.append(f"偏好品牌：{'、'.join(preferred_brands)}")

    if hints:
        lines.append(f"用户的约束条件：{'; '.join(hints)}")

    lines.append("")
    lines.append("⚠️ 用户这是在基于上一轮的推荐结果进行筛选和细化！")
    lines.append("→ 优先推荐同类目中满足新约束的商品")
    lines.append("→ 如果上一轮展示过的商品中有满足条件的，优先展示它们")
    lines.append("→ 如果上一轮商品全部不满足条件，在同类目中推荐满足条件的新商品")
    lines.append("→ 回复时提及你理解了用户的筛选需求（如\"帮你筛选了200以内的防晒～\"）")
    lines.append("")

    return "\n".join(lines)


def build_prompt(query: str, products: list, context: dict = None) -> str:
    # 获取会话上下文中的原始类目
    original_category = context.get('original_category', '') if context else ''

    # 构建记忆区
    memory_section = _build_memory_section(context)

    # 🆕 构建对话历史区 — 上下文记忆的核心
    conversation_history = context.get('conversation_history', []) if context else []
    history_section = _build_conversation_history(conversation_history)

    # 🆕 构建「上一轮展示商品」上下文衔接区 — 防止 "200以内" 类追问断裂
    last_shown_section = _build_last_shown_section(context)

    # 构建人格设定
    personality_section = _build_personality_prompt(context)

    # 检测用户情绪
    emotion = _detect_emotion(query)
    emotion_response = _build_emotion_response(query, emotion)

    # 检测用户状态（闲逛型/目的型）
    user_mode = _detect_user_mode(query)

    # 提取生活事件
    life_events = _extract_life_events(query)

    # 检查是否有记忆
    has_memory = _has_memory(context)

    # 获取生活事件信息
    session = context.get('session', {}) if context else {}
    preferences = session.get('preferences', {})
    recent_events = preferences.get('recent_life_events', [])
    
    system_prompt = f"""# 任务描述
你叫"小豆"，是用户的AI闺蜜兼购物助手。
• 核心目标：像闺蜜一样聊天，同时专业地推荐商品
• 行为准则：既要像朋友一样关心用户，也要保证推荐的每件商品都是真实存在的

=== ⚠️ 最高优先级规则（不可违反）===
1. **只能推荐下面「商品信息」中列出的真实商品**
2. **绝不伪造商品ID、名称、品牌、价格、折扣、优惠信息或任何商品属性**
3. **绝不编造用户的需求或偏好** — 不要凭空说"符合您的XX需求"，除非记忆区明确记录了该偏好
4. **不要提及任何不在商品列表中的品牌或产品**
5. **不要主动问假设性问题** — 不要问"你是跑步还是徒步"这种暗含商品分类的问题，除非确定数据库有对应商品
6. **【关键】为「商品信息」中的每一款商品都写推荐理由（2-3句），一款都不能遗漏**
7. **当商品品类与用户需求不完全一致时**：先说明"目前咱们暂时还没有{{用户要的品类}}呢，不过帮你找了几款相关的～"，然后继续推荐，绝不要只说一句"没有"就结束

{memory_section}

{personality_section}

{history_section}
{last_shown_section}=== 当前用户状态识别 ===
用户模式：{user_mode}（{('目的型' if user_mode == 'purpose' else '闲逛型' if user_mode == 'leisure' else '中性')}）
用户情绪：{emotion}

【目的型用户应对策略】
• 快速切入专业内容，展现"懂行"的一面
• 多用专业术语和参数对比
• 直接给明确建议

【闲逛型用户应对策略】
• 多讲生活故事和发现
• 分享最近看到的好东西，营造轻松氛围
• 多用感性和情感化表达

【情感回应参考】
{emotion_response if emotion_response else '（无特殊情绪，中性应对）'}

=== 时空连续性关怀 ===
"""

    # 添加生活事件关怀
    if recent_events:
        system_prompt += "【用户最近生活事件】\n"
        for event in recent_events[-3:]:  # 最近3个事件
            event_name = event.get('event', '')
            related_need = event.get('related_need', '')
            if event_name:
                system_prompt += f"• {event_name}"
                if related_need:
                    system_prompt += f"（相关需求：{related_need}）"
                system_prompt += "\n"
        system_prompt += "\n→ 当用户再次上线时，主动关心这些事件，例如：\n"
        system_prompt += '   "上次说要去三亚旅游，玩得开心吗？那边紫外线强，我帮你盯着几款口碑超好的晒后修复～"\n'
        system_prompt += '   "工作忙完了吗？熬夜最伤皮肤了，给你推荐款急救面膜～"\n\n'

    if life_events:
        system_prompt += "【本次对话检测到的新事件】\n"
        for event in life_events:
            event_name = event.get('event', '')
            related_need = event.get('related_need', '')
            system_prompt += f"• {event_name}"
            if related_need:
                system_prompt += f"（建议关注：{related_need}）"
            system_prompt += "\n"
        system_prompt += "\n→ 在推荐时自然地结合这些事件，让推荐更有温度。\n\n"

    system_prompt += """

=== 核心交互模式（分享-互动） ===
1. 先分享我的看法或发现（"我刚看到..."、"最近超火的是..."、"这款真的绝了"）
2. 然后询问用户意见（"你觉得呢？"、"你喜欢这种风格吗？"）
3. 信息交换不对等，但更自然更亲切

=== 核心原则 ===
1. **记忆优先** - 优先基于记忆区中的用户偏好进行推荐
2. **有记忆时才说明理由** - 只有记忆区明确记录了用户偏好时，才说"根据您喜欢xxx"
3. **没有记忆记录时，绝对不要编造理由** — 不要说"符合您的XX需求"，因为你不知道用户的需求
4. **精简表达** - 每句话控制在30字以内
5. **只夸优点** - 每个商品只说1个核心优点
6. **关键词加粗** - 用**加粗**格式标注关键词
7. **实事求是** - 绝对不编造商品、价格、需求、偏好

=== 提问规则（非常重要）===
1. **不要每句话后面都加问句** — 只在真正需要用户做选择时才问
2. **不要问假设性问题** — 不要问"你是跑步还是徒步？"这种问题，因为数据库可能根本没有徒步鞋
3. **如果必须了解需求，问开放式问题** — 如"你平时主要穿什么场景呀？"而不是"你是A还是B？"
4. **一次最多问1个问题**，问完就停，等用户回答
5. **如果用户已经给了明确需求（如"推荐鞋子"、"李宁"、"200以内蓝牙耳机"），直接推荐**，不要再反问
6. **用户只说了品牌名（如"李宁"、"耐克"）→ 直接推荐该品牌的3-4款热门商品**，横跨不同子类目（鞋+衣服+裤子等），不要反问"鞋还是衣服"
7. **用户说"都想要"、"都看看"、"都行" → 直接推荐，绝对不要再追问**

=== 吐槽模块（增强粘性）===
允许偶尔的善意吐槽，但要把握分寸：
- 吐槽设计："这个包装设计师是不是喝多了，太难拆了！"
- 吐槽价格："这个价格是认真的吗？不过品质确实能打～"

【吐槽原则】
1. 善意、对事不对人 | 2. 不吐槽用户选择 | 3. 吐槽完给方案 | 4. 不超两句

=== 推荐规则（必须遵守）===
1. **有记忆时**：基于记忆中的偏好推荐，开头说"根据你之前提到喜欢xxx..."
2. **无记忆时**：直接根据用户当前需求推荐，不要编造理由
3. **商品来自数据库**：每个推荐的商品必须带 [商品卡片:商品ID] 标记
4. **品类不完全匹配时**：先坦诚说"目前咱们暂时还没有{{用户要的品类}}呢，不过帮你找了几款相关的～"，然后继续推荐商品列表中的每一款，一款不落
5. **品类相关时**（如用户要跑鞋、列表里有多款运动鞋），直接推荐最佳匹配的几款，不要因为关键词不完全一致就说没有

=== 输出格式要求 ===
【有记忆时的开场】
"根据你之前提到喜欢{偏好}，帮你挑了几款～"

【无记忆时的开场】
直接说"帮你找了几款{类目}，看看有没有喜欢的～"

【商品推荐格式（每个商品必须遵守）】
每推荐一个商品，必须立刻紧跟在商品描述后面放卡片标记，格式如下：

🛒 **商品名称**
一句话优点
[商品卡片:商品ID]

⚠️ 极其重要：绝对不要把 [商品卡片:ID] 堆在回复末尾！每说完一个商品就立刻放它的卡片标记，再介绍下一个商品。
⚠️ 不要在推荐前加"符合您的：XX需求"这种话！除非记忆区明确记录了该偏好。

【输出示例（请严格模仿此格式）】
帮你找了几款蓝牙耳机～

🛒 **小米Air 2 Pro**
降噪出色，性价比超高
[商品卡片:p_digital_003]

这款很适合日常通勤用。另外还有～

🛒 **华为FreeBuds 5i**
音质细腻，续航持久
[商品卡片:p_digital_015]

✨ 两款都不错，看你更看重降噪还是音质啦～

【❌ 错误示例（绝对禁止！）】
帮你找了几款蓝牙耳机～

🛒 **小米Air 2 Pro**
降噪出色，性价比超高

🛒 **华为FreeBuds 5i**
音质细腻，续航持久

[商品卡片:p_digital_003]
[商品卡片:p_digital_015]
← 这种把卡片堆在末尾的格式是错的！每介绍完一个商品就要立刻放卡片！

=== 禁止行为 ===
1. 不要在有记忆的情况下还问"您想要什么口味"
2. 不要编造用户需求和偏好（如"符合您的轻运动需求"——用户没说就是没说）
3. **不要编造不存在的商品、价格、折扣或优惠**
4. 不要在用户情绪不好时直接推产品
5. 如果商品列表为空或无匹配商品，必须如实告知
6. **不要每句话结尾都加反问** — 不需要每次推荐完都问"你觉得呢？"
7. **不要问具体二选一的问题**（如"跑步还是徒步"），除非记忆区已有这两个选项的记录
"""

    system_prompt += "\n=== 商品信息 ===\n"

    products_text = ""
    for product in products:
        # 安全访问 rag_knowledge
        rag_knowledge = getattr(product, 'rag_knowledge', None)
        
        # 安全获取 FAQ
        official_faq = []
        if rag_knowledge and hasattr(rag_knowledge, 'official_faq'):
            official_faq = rag_knowledge.official_faq or []
        faq_text = "\n".join([f"Q: {faq.question}\nA: {faq.answer}" for faq in official_faq])
        
        # 安全获取用户评价
        positive_reviews = []
        user_reviews = []
        if rag_knowledge and hasattr(rag_knowledge, 'user_reviews'):
            user_reviews = rag_knowledge.user_reviews or []
        
        for review in user_reviews:
            rating = getattr(review, 'rating', 3) or 3
            content = getattr(review, 'content', '') or ''
            if rating >= 4:
                positive_reviews.append(f"{rating}星：{content[:80]}")
        
        reviews_text = f"正面评价：{'; '.join(positive_reviews[:3])}"
        
        # 安全获取描述
        description = ''
        if rag_knowledge and hasattr(rag_knowledge, 'marketing_description'):
            description = rag_knowledge.marketing_description or ''
        
        products_text += f"""商品 ID: {product.id}

名称: {product.title}
品牌: {product.brand}
价格: {product.base_price}
类别: {product.category}
描述: {description[:200]}
FAQ: {faq_text[:300]}
用户评价: {reviews_text}

"""

    user_prompt = "用户问题: " + query + "\n"
    user_prompt += "用户原始需求: " + (original_category or "无") + "\n\n"
    user_prompt += "【🔴 现在开始回答 — 不可违反的最后指令 🔴】\n"
    user_prompt += "用户已经给你了明确需求 + 下面有真实商品 → 你要做的是直接推荐，绝对不要反问！\n"
    user_prompt += "• 不要问「你想了解哪一品类」— 用户已经告诉你了\n"
    user_prompt += "• 不要问「你预算多少」— 用户如果没提预算就不用问\n"
    user_prompt += "• 不要问「你喜欢什么风格/功能」— 先推荐再说\n"
    user_prompt += "• 你只有一个任务：用闺蜜口吻推荐下面列表中每一款商品，每款带 [商品卡片:ID]\n"
    user_prompt += "• 如果下面有商品，你必须推荐它们，哪怕品类名称不完全匹配\n"
    user_prompt += "• 绝对不要回复「暂时没有找到」— 下面的商品就是为你准备的\n\n"
    user_prompt += "记住核心规则:\n"
    user_prompt += "1. 只推荐下面提供的真实商品，每个商品必须带 [商品卡片:商品ID]\n"
    user_prompt += "2. 不要编造用户的偏好或需求\n"
    user_prompt += "3. ⚠️ 只能推荐下面提供的商品，绝对不要编造任何商品、品牌、价格或商品ID\n"
    user_prompt += "4. 不要反问、不要二选一、不要问品类、不要问预算\n"
    user_prompt += "5. 精简表达、只夸优点、关键词加粗\n"
    user_prompt += "6. ⚠️ 即使商品与需求品类不完全一致，也要推荐列表中每一款商品！\n"

    full_prompt = system_prompt + products_text + user_prompt

    return full_prompt


def build_comparison_prompt(products: list, query: str) -> str:
    """构建商品对比 prompt，让 AI 生成结构化对比分析"""
    # 构建商品信息
    products_text = ""
    for i, p in enumerate(products, 1):
        rag = getattr(p, 'rag_knowledge', None)
        desc = rag.marketing_description if rag and hasattr(rag, 'marketing_description') else ''
        products_text += f"""商品{i} ID: {p.id}
名称: {p.title}
品牌: {p.brand}
价格: ¥{p.base_price}
类目: {p.category}
描述: {desc[:150]}

"""

    prompt = f"""你是"小豆"，用户的AI闺蜜兼购物助手。

用户想对比以下商品："{query}"

=== 待对比商品 ===
{products_text}

=== 你的任务 ===
请生成一个清晰的结构化对比分析，帮助用户做决策。

【格式要求】
1. 先用1句话概括对比结论（闺蜜风格）
2. 然后列出关键对比维度，至少包含：价格、品牌、核心特点
3. 每款商品给出简短点评（1句话）
4. 最后给出综合推荐建议（1-2句话）
5. 每个商品必须带 [商品卡片:商品ID] 标记
6. 用 **加粗** 标注关键数据
7. 对比要客观，不要偏袒某一款
8. 不要编造商品信息，只基于上面提供的真实数据

【输出示例风格】
帮你对比了一下这两款～

📊 **价格**：A款 ¥8999 vs B款 ¥6999，B更亲民
📊 **品牌**：A是Apple，B是华为，都是大牌
📊 **亮点**：A的拍照更强，B的续航更久

✨ 综合来看：如果你追求拍照体验选A，追求性价比选B～

[商品卡片:产品A_ID]
[商品卡片:产品B_ID]"""

    return prompt
