from typing import List, Dict, Optional, Tuple
import re
from models.schemas import Product
from rag.retriever import ProductRetriever


class IntentType:
    """意图类型枚举"""
    CONDITIONAL_FILTER = "conditional_filter"  # 条件筛选
    MULTI_ROUND_REFINE = "multi_round_refine"  # 多轮追问
    COMPARISON = "comparison"  # 对比决策
    ASK_MORE_INFO = "ask_more_info"  # 主动反问
    DIRECT_RECOMMEND = "direct_recommend"  # 直接推荐
    SCENARIO_RECOMMEND = "scenario_recommend"  # 场景化推荐


class ChatResponse:
    """统一的聊天响应格式"""
    def __init__(self, reply_text: str, products: List = None, need_more_info: bool = False, questions: List[str] = None):
        self.reply_text = reply_text
        self.products = products or []
        self.need_more_info = need_more_info
        self.questions = questions or []
    
    def to_dict(self):
        return {
            "reply_text": self.reply_text,
            "products": [p.to_dict() if hasattr(p, 'to_dict') else p for p in self.products],
            "need_more_info": self.need_more_info,
            "questions": self.questions
        }


class CapabilityManager:
    """能力管理器"""
    def __init__(self, retriever: ProductRetriever):
        self.retriever = retriever
    
    def _is_comparison(self, query: str) -> bool:
        """检测是否为对比意图"""
        # 简单关键词检测
        keywords = ['对比', '比较', 'vs', '和', '哪款', '哪个好', '选哪个', '更']
        for keyword in keywords:
            if keyword in query:
                return True
        return False
    
    def _extract_comparison_products(self, query: str) -> List[str]:
        """提取对比的商品名称"""
        # 先找关键词位置
        compare_keywords = ['和', '与', 'vs', '对比', '比较']
        product_names = []
        
        # 简单分割提取
        for keyword in compare_keywords:
            if keyword in query:
                parts = query.split(keyword)
                if len(parts) >= 2:
                    # 简单清理，取前后部分作为产品名
                    name1 = parts[0].strip()
                    name2 = parts[1].strip()
                    # 进一步清理（去掉问题词）
                    for q_word in ['哪款', '哪个好', '对比', '比较', '选哪个', '更好', '更']:
                        name2 = name2.replace(q_word, '').strip()
                        name1 = name1.replace(q_word, '').strip()
                    
                    if name1 and name2:
                        product_names = [name1, name2]
                        break
        
        return product_names
    
    def _extract_filter_conditions(self, query: str) -> Dict:
        """提取筛选条件（否定条件等）"""
        conditions = {}
        
        # 提取"不要"、"不含"等否定条件
        negation_patterns = [
            r'不要(.+?)',
            r'不[要|含|喜欢](.+?)',
            r'不含(.+?)',
            r'避免(.+?)',
            r'避开(.+?)',
            r'排除(.+?)'
        ]
        
        forbidden_items = []
        for pattern in negation_patterns:
            matches = re.findall(pattern, query)
            for match in matches:
                item = match.strip()
                if item:
                    forbidden_items.append(item)
        
        if forbidden_items:
            conditions['forbidden'] = forbidden_items
        
        return conditions
    
    def _detect_scenario(self, query: str, context: Dict = None) -> Optional[str]:
        """检测用户场景"""
        # 场景关键词
        scenario_keywords = {
            '海边度假': ['海边', '度假', '沙滩', '三亚', '海南', '游泳', '阳光'],
            '户外运动': ['户外', '运动', '跑步', '健身', '爬山', '骑行', '露营'],
            '商务出差': ['商务', '出差', '办公', '会议', '通勤'],
            '学生开学': ['开学', '学生', '上学', '作业', '考试'],
            '护肤化妆': ['护肤', '化妆', '美容', '补水', '防晒', '美白']
        }
        
        for scenario, keywords in scenario_keywords.items():
            for keyword in keywords:
                if keyword in query:
                    return scenario
        
        return None
    
    def _generate_comparison_response(self, products: List[str], context: Dict = None) -> ChatResponse:
        """生成对比决策的回复"""
        # 搜索商品
        all_products = []
        for product_name in products:
            product_results = self.retriever.search_by_name(product_name)
            if product_results:
                all_products.extend(product_results[:3])  # 每个名称最多找3个
        
        if not all_products:
            return ChatResponse(
                reply_text="抱歉，我暂时找不到这些商品的信息。您能换个方式描述一下吗？",
                need_more_info=True,
                questions=["您想对比的具体商品名称是什么？"]
            )
        
        # 对比商品
        comparison_text = "我来帮您对比这几款商品：\n\n"
        
        # 构建对比表格
        comparison_summary = {}
        for p in all_products:
            comparison_summary[p.title] = {
                '价格': p.base_price,
                '评分': getattr(p, 'rating', 4.5),
                '特点': getattr(p, 'description', '暂无描述')[:50] + '...'
            }
        
        # 生成对比内容
        for name, details in comparison_summary.items():
            comparison_text += f"【{name}】\n"
            comparison_text += f"  价格：¥{details['价格']}\n"
            comparison_text += f"  评分：{details['评分']}星\n"
            comparison_text += f"  特点：{details['特点']}\n\n"
        
        # 给出推荐建议
        best_pick = max(all_products, key=lambda x: getattr(x, 'rating', 4.5))
        comparison_text += f"✨ 综合推荐：{best_pick.title}，这款在评分和性价比方面表现更出色！\n"
        
        return ChatResponse(
            reply_text=comparison_text,
            products=all_products,
            need_more_info=False
        )
    
    def _generate_scenario_recommendation(self, scenario: str, context: Dict = None) -> ChatResponse:
        """生成场景化组合推荐"""
        recommendations = []
        
        # 场景对应的商品组合
        scenario_recommendations = {
            '海边度假': ['防晒霜', '遮阳帽', '墨镜', '泳衣', '沙滩鞋', '晒后修复'],
            '户外运动': ['运动耳机', '跑鞋', '运动手环', '速干衣', '防晒霜', '水杯'],
            '商务出差': ['商务笔记本', '降噪耳机', '公文包', '商务服装', '便携充电宝', '剃须刀'],
            '学生开学': ['笔记本', '笔袋', '书包', '计算器', '台灯', '保温杯'],
            '护肤化妆': ['保湿霜', '粉底液', '口红', '防晒', '精华液', '面膜']
        }
        
        if scenario not in scenario_recommendations:
            return ChatResponse(
                reply_text="这个场景很有趣！您能告诉我更多细节吗？比如具体是做什么活动？",
                need_more_info=True,
                questions=[f"您能描述下{scenario}的具体需求吗？"]
            )
        
        # 搜索推荐商品
        product_types = scenario_recommendations[scenario]
        recommended_products = []
        
        for product_type in product_types:
            products = self.retriever.search_by_keyword(product_type, limit=2)
            if products:
                recommended_products.extend(products)
        
        reply_text = f"🌴 为您的{scenario}准备了一套精选组合：\n\n"
        
        # 按类型分组
        from collections import defaultdict
        products_by_type = defaultdict(list)
        for p in recommended_products:
            products_by_type[p.category].append(p)
        
        # 生成推荐
        for category, products in products_by_type.items():
            if products:
                reply_text += f"【{category}】\n"
                for p in products:
                    reply_text += f"  - {p.title}：¥{p.base_price}\n"
                reply_text += "\n"
        
        reply_text += "希望这套组合能让您的行程更完美！有什么需要调整的随时告诉我哦~"
        
        return ChatResponse(
            reply_text=reply_text,
            products=recommended_products,
            need_more_info=False
        )
    
    def _needs_more_info(self, query: str, context: Dict = None) -> bool:
        """判断是否需要追问更多信息"""
        if not context:
            # 直接请求推荐但没有具体条件
            recommend_patterns = ['推荐', '帮我选', '哪个好', '有什么']
            has_recommend = any(p in query for p in recommend_patterns)
            
            if not has_recommend:
                return False
            
            # 如果没有提到具体条件，需要追问
            has_condition = any(c in query for c in ['价格', '预算', '品牌', '类型', '哪个', '什么'])
            if has_condition:
                return False
            
            # 检查是否有上下文
            prefs = context.get('preferences', {}) if context else {}
            has_category = prefs.get('category')
            has_price = prefs.get('price_range') != (0, float('inf'))
            
            if not has_category and not has_price:
                return True
        
        return False
    
    def detect_intent(self, query: str, context: Dict = None) -> Tuple[IntentType, Dict]:
        """识别用户意图"""
        # 检测对比意图
        if self._is_comparison(query):
            products = self._extract_comparison_products(query)
            if products:
                return IntentType.COMPARISON, {"products": products}
        
        # 检测筛选意图
        filter_conditions = self._extract_filter_conditions(query)
        if filter_conditions:
            return IntentType.CONDITIONAL_FILTER, filter_conditions
        
        # 检测场景
        scenario = self._detect_scenario(query, context)
        if scenario:
            return IntentType.SCENARIO_RECOMMEND, {"scenario": scenario}
        
        # 检查是否需要追问
        if self._needs_more_info(query, context):
            return IntentType.ASK_MORE_INFO, {}
        
        # 默认直接推荐
        return IntentType.DIRECT_RECOMMEND, {}
    
    def process(self, query: str, context: Dict = None) -> ChatResponse:
        """处理用户请求"""
        intent_type, params = self.detect_intent(query, context)
        
        if intent_type == IntentType.COMPARISON:
            return self._generate_comparison_response(params['products'], context)
        elif intent_type == IntentType.SCENARIO_RECOMMEND:
            return self._generate_scenario_recommendation(params['scenario'], context)
        elif intent_type == IntentType.ASK_MORE_INFO:
            # 这里应该生成追问问题
            return ChatResponse(
                reply_text="您好！为了更好地帮您推荐，我需要了解一些信息：",
                need_more_info=True,
                questions=["您想要什么类别的商品？", "您的预算大概是多少？", "有什么偏好的品牌吗？"]
            )
        else:
            # 直接推荐 — 返回空商品列表，让调用方走 RAG + AI 管道
            # 绝对不返回不相关的随机商品
            return ChatResponse(
                reply_text="",
                products=[],
                need_more_info=False
            )
