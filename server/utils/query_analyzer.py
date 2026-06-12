"""
查询分析器 — 检测模糊查询、提取用户偏好、生成澄清反问。

核心职责：
    1. 模糊检测：判断查询是否过于笼统需要追问澄清
    2. 偏好提取：从查询中提取价格、品牌、肤质、口味等偏好
    3. 生成反问：根据类目生成自然的澄清问题

支持的偏好类型：
    - 价格范围：通过 price_parser 解析
    - 品牌倾向：国产/国际/性价比
    - 肤质类型：干性/油性/混合性/敏感性/中性
    - 功效需求：保湿/美白/抗老/祛痘/控油等
    - 口味偏好：辣/甜/酸/咸/清淡
    - 运动类型：跑步/健身/篮球/瑜伽/户外等
    - 风格偏好：休闲/运动/商务/时尚/复古

关键设计：
    - 一次遍历同时完成模糊检测和偏好提取，高效
    - 不同类目有不同的关键维度，生成针对性反问
    - 闺蜜风格的反问话术，自然口语化
"""
from typing import Optional, Dict, List, Tuple
from utils.price_parser import detect_price_range


SPECIFIC_FEATURE_KEYWORDS = [
    # 数码
    '拍照', '摄像', '续航', '性能', '轻薄', '屏幕', '高刷', '快充', '无线充',
    '5g', '大屏', '小屏', '折叠', '游戏', '工作', '办公', '学习',
    # 美妆（含口语化表达，覆盖 slot 问题的简答如"干皮""干的"）
    '干性', '干皮', '干的', '油性', '油皮', '混油', '混干', '混合性', '混合', '敏感肌', '敏感', '中性',
    '保湿', '美白', '抗老', '祛痘', '控油', '修护', '舒缓', '紧致',
    '清爽', '滋润', '不油腻', '提亮', '淡纹', '抗皱', '遮瑕', '持妆', '定妆',
    # 服饰
    '跑步', '健身', '篮球', '瑜伽', '户外', '登山', '骑行', '游泳', '徒步', '训练', '越野',
    '休闲', '商务', '运动', '时尚', '复古', '日常', '通勤',
    # 食品
    '辣', '甜', '酸', '咸', '清淡', '低卡', '低脂', '无糖', '高蛋白', '零糖', '零卡',
    # 通用
    '性价比', '高端', '国产', '便宜', '实惠', '耐用', '轻量', '防水', '透气', '速干',
]

SPECIFIC_PRODUCT_KEYWORDS = [
    # 美妆
    '洗面奶', '面膜', '面霜', '精华', '防晒', '防晒霜', '防晒乳',
    '粉底', '粉底液', '口红', '唇釉', '眉笔', '眼霜', '眼影', '腮红',
    '爽肤水', '柔肤水', '卸妆油', '卸妆', '洁面', '洁面乳', '散粉', '蜜粉', '粉饼',
    # 数码
    '手机', '笔记本', '笔记本电脑', '平板', '平板电脑', '蓝牙耳机', '无线耳机', '耳机',
    '充电器', '数据线', '智能手表', '手环',
    # 服饰鞋包
    '鞋', '鞋子', '跑鞋', '跑步鞋', '篮球鞋', '运动鞋', '徒步鞋', '登山鞋', '越野鞋', '休闲鞋',
    '衣服', '上衣', 'T恤', '短袖', '长袖', '衬衫', '卫衣', '外套', '羽绒服',
    '裤子', '短裤', '长裤', '运动裤', '紧身裤', '瑜伽裤', '牛仔裤',
    '裙子', '短裙', '连衣裙', '半身裙',
    '包', '背包', '双肩包', '帽子', '棒球帽', '鸭舌帽',
    # 食品
    '薯片', '巧克力', '坚果', '咖啡', '酸奶', '牛奶', '方便面', '泡面',
    '气泡水', '功能饮料', '茶饮料', '酱油',
    # 品牌（用户可能直接用品牌名搜索）
    '迪卡侬', '优衣库', '耐克', '阿迪达斯', '阿迪', '李宁', '安踏', '特步',
    '露露乐蒙', '始祖鸟', '萨洛蒙', '迈乐',
    '苹果', '华为', '小米', 'OPPO', 'vivo', '联想',
    '雅诗兰黛', '兰蔻', '科颜氏', '资生堂', '理肤泉', '薇诺娜', '珀莱雅', '花西子',
    '雀巢', '三只松鼠', '良品铺子', '百草味', '元气森林', '康师傅', '统一',
]

ALL_BRANDS = [
    # 数码电子
    '苹果', 'apple', '华为', 'huawei', '小米', 'xiaomi', 'oppo', 'vivo', '联想', 'lenovo',
    '三星', 'samsung',
    # 运动户外
    '耐克', 'nike', '阿迪达斯', '阿迪', 'adidas', '李宁', '安踏', '特步',
    '361', '361度', '鸿星尔克', '匹克', '亚瑟士', 'asics',
    '露露乐蒙', 'lululemon', '始祖鸟', '萨洛蒙', 'salomon', '迈乐', 'merrell',
    '迪卡侬', 'decathlon', '优衣库', 'uniqlo', '北面', 'the north face',
    'hoka', 'osprey',
    # 美妆护肤
    '兰蔻', 'lancome', '雅诗兰黛', '科颜氏', '资生堂', '理肤泉', '薇诺娜', '珀莱雅',
    '花西子', '玉兰油', 'olay', '欧莱雅', '巴黎欧莱雅', '完美日记',
    'sk-ii', 'skii', 'sk2', 'ahc', 'the ordinary', 'ordinary',
    '安热沙', 'anessa', '方里', '珊珂', 'senka', '芳珂', 'fancl',
    'canmake', 'kate', 'mac', 'ysl', '迪奥', 'dior',
    # 食品饮料
    '雀巢', '三只松鼠', '良品铺子', '百草味', '元气森林', '康师傅', '统一',
    '三顿半', '农夫山泉', '可口可乐', '蒙牛', '伊利', '东鹏', '红牛',
    '东方树叶', '日清', 'nissin', '纯甄', '金典', 'satine',
    # 调味品
    '李锦记', '海天',
]

CATEGORY_DIMENSIONS = {
    '数码电子': {
        'dimensions': ['功能侧重（拍照/续航/性能/轻薄）', '预算范围', '品牌倾向（国产/国际/性价比）'],
        'example': '比如你更看重拍照还是续航？预算大概多少呀～',
    },
    '美妆护肤': {
        'dimensions': ['肤质（干性/油性/混合/敏感）', '功效需求（保湿/美白/抗老/祛痘）', '预算范围'],
        'example': '比如你是什么肤质呀？主要想保湿还是美白呢～',
    },
    '服饰运动': {
        'dimensions': ['穿着场景（跑步/健身/日常/商务）', '风格偏好（休闲/运动/时尚）', '预算范围'],
        'example': '比如你是跑步穿还是日常穿呀？喜欢什么风格呢～',
    },
    '食品饮料': {
        'dimensions': ['口味偏好（辣/甜/酸/咸/清淡）', '零食类型（薯片/坚果/糖果/饮品）', '健康诉求'],
        'example': '比如你喜欢辣的还是甜的？有没有在控糖呀～',
    },
}


def analyze_query(query: str, category: str = None) -> Dict:
    """
    统一查询分析：一次遍历同时完成模糊检测 + 偏好提取。

    返回 {'is_vague': bool, 'preferences': {...}}
    - is_vague=True 表示查询太模糊，需要反问澄清
    - preferences 始终会提取，即使 is_vague=True（能提多少提多少）
    """
    text = query.strip()
    text_lower = text.lower()
    prefs = {}
    is_specific = False

    for kw in SPECIFIC_FEATURE_KEYWORDS:
        if kw in text:
            is_specific = True
            break

    if not is_specific:
        for kw in SPECIFIC_PRODUCT_KEYWORDS:
            if kw in text:
                is_specific = True
                break

    price = detect_price_range(query)
    if price and price != (0, float('inf')):
        is_specific = True
        prefs['price_range'] = price

    matched_brands = [b for b in ALL_BRANDS if b.lower() in text_lower]
    if matched_brands:
        is_specific = True
        prefs['preferred_brands'] = matched_brands

    key_features = []
    if any(w in text_lower for w in ['拍照', '摄像', '相机', '摄影']): key_features.append('拍照')
    if any(w in text_lower for w in ['续航', '电池', '电量']): key_features.append('续航')
    if any(w in text_lower for w in ['性能', '快', '流畅', '不卡', '处理器', '芯片']): key_features.append('性能')
    if any(w in text_lower for w in ['轻薄', '轻便', '小巧']): key_features.append('轻薄')
    if any(w in text_lower for w in ['屏幕', '显示', '高刷', '护眼']): key_features.append('屏幕')
    if key_features:
        prefs['key_features'] = key_features

    if any(w in text_lower for w in ['国产', '华为', '小米', 'oppo', 'vivo', '荣耀']): prefs['brand_priority'] = '国产'
    elif any(w in text_lower for w in ['苹果', 'iphone', '三星', '国际']): prefs['brand_priority'] = '国际'
    elif any(w in text_lower for w in ['性价比', '实惠']): prefs['brand_priority'] = '性价比'

    for kw, skin in [('干皮', '干性'), ('干的', '干性'), ('干性', '干性'),
                     ('油皮', '油性'), ('油性', '油性'),
                     ('混油', '混合性'), ('混干', '混合性'), ('混合性', '混合性'), ('混合', '混合性'),
                     ('敏感肌', '敏感性'), ('敏感', '敏感性'),
                     ('中性', '中性')]:
        if kw in text_lower:
            prefs['skin_type'] = skin
            break

    concerns = []
    if any(w in text_lower for w in ['保湿', '补水']): concerns.append('保湿')
    if any(w in text_lower for w in ['美白', '白']): concerns.append('美白')
    if any(w in text_lower for w in ['抗老', '抗皱', '紧致']): concerns.append('抗老')
    if any(w in text_lower for w in ['祛痘', '痘痘', '痘']): concerns.append('祛痘')
    if any(w in text_lower for w in ['控油']): concerns.append('控油')
    if any(w in text_lower for w in ['修护', '修复', '敏感']): concerns.append('修护')
    if concerns:
        prefs['skin_concerns'] = concerns

    for kw, flavor in [('辣', '辣'), ('甜', '甜'), ('酸', '酸'), ('咸', '咸'), ('清淡', '清淡')]:
        if kw in text_lower:
            prefs['flavor_preference'] = flavor
            break

    for kw, sport in [('跑步', '跑步'), ('健身', '健身'), ('篮球', '篮球'), ('瑜伽', '瑜伽'),
                       ('户外', '户外'), ('登山', '登山'), ('骑行', '骑行'), ('游泳', '游泳')]:
        if kw in text_lower:
            prefs['sport_type'] = sport
            break

    for kw, style in [('休闲', '休闲'), ('运动', '运动'), ('商务', '商务'), ('时尚', '时尚'), ('复古', '复古')]:
        if kw in text_lower:
            prefs['style'] = style
            break

    # 如果检测到了类目，即使 query 短也不算模糊
    is_vague = not is_specific and len(text) <= 8 and not category

    return {'is_vague': is_vague, 'preferences': prefs}


def get_clarification_prompt(category: str, query: str) -> str:
    """
    生成发给 doubao 的澄清 prompt。
    要求 doubao 生成简短、自然、闺蜜风格的反问。
    """
    dims = CATEGORY_DIMENSIONS.get(category)

    if dims:
        dimensions_str = '、'.join(dims['dimensions'])
        example = dims['example']
        prompt = f"""你是"小豆"，用户的AI闺蜜兼购物助手。

用户说了一句："{query}"

这句话太模糊了，没有给任何具体偏好。请你自然地追问用户，帮ta细化需求。

【这类商品的关键维度】
{dimensions_str}

【你的任务】
生成1-2句自然的追问，要求：
1. 用闺蜜聊天口吻，自然口语化
2. 引导用户说出关键偏好（从上面的维度中选1-2个最重要的问）
3. 参考风格："{example}"
4. 不要像客服问卷一样列出所有选项
5. 不要用"您可以..."这种客服语气
6. 只输出追问文本，不要任何前缀或标记
7. 【重要】绝对不要调侃或评论用户说了几个字，直接正常问即可"""
    else:
        prompt = f"""你是"小豆"，用户的AI闺蜜兼购物助手。

用户说了一句："{query}"

这句话太模糊了。请你自然地追问用户，帮ta细化需求。

要求：
1. 用闺蜜聊天口吻，问ta具体想要什么类型、什么价位
2. 1-2句话即可
3. 不要用"您可以..."这种客服语气
4. 只输出追问文本，不要任何前缀或标记"""

    return prompt
