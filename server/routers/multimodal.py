import os
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, Response

router = APIRouter(prefix="/api", tags=["multimodal"])

_audio_service = None
_image_service = None
_retriever = None
_session_manager = None
_capability_manager = None
_doubao_service = None


def set_services(audio_service, image_service, retriever, session_manager, capability_manager, doubao_service):
    global _audio_service, _image_service, _retriever, _session_manager, _capability_manager, _doubao_service
    _audio_service = audio_service
    _image_service = image_service
    _retriever = retriever
    _session_manager = session_manager
    _capability_manager = capability_manager
    _doubao_service = doubao_service


def _check_services_initialized():
    if None in [_audio_service, _image_service, _retriever, _session_manager, _capability_manager, _doubao_service]:
        raise HTTPException(status_code=503, detail="服务正在初始化中，请稍后重试")


def get_base_url(http_request: Request) -> str:
    env_url = os.getenv("SERVER_BASE_URL")
    if env_url:
        return env_url.rstrip("/")
    host = http_request.headers.get("host", "localhost:8080")
    scheme = http_request.headers.get("x-forwarded-proto", "http")
    return f"{scheme}://{host}"


def products_to_dict_list(products, base_url: str) -> list:
    if not products:
        return []
    
    result = []
    for i, p in enumerate(products):
        try:
            if hasattr(p, 'to_dict'):
                result.append(p.to_dict(base_url=base_url))
            elif isinstance(p, dict):
                # 已经是字典格式，直接使用
                product_dict = p.copy()
                if 'image_path' in product_dict and 'image_url' not in product_dict:
                    image_path = product_dict['image_path']
                    if image_path:
                        if image_path.startswith('http'):
                            product_dict['image_url'] = image_path
                        else:
                            product_dict['image_url'] = f"{base_url}/api/products/image/{product_dict.get('id', '')}"
                result.append(product_dict)
            else:
                print(f"[WARN] 商品 {i} 缺少 to_dict 方法, type={type(p).__name__}")
                result.append({
                    "id": getattr(p, 'id', str(i)),
                    "name": getattr(p, 'title', getattr(p, 'name', f"Product {i}")),
                    "brand": getattr(p, 'brand', "Unknown"),
                    "category": getattr(p, 'category', "Unknown"),
                    "price": getattr(p, 'base_price', getattr(p, 'price', 0.0)),
                    "image_url": "",
                    "rating": 4.5,
                    "review_count": 1000,
                    "description": getattr(p, 'description', "暂无描述")
                })
        except Exception as e:
            print(f"转换商品 {i} 失败: {str(e)}")
    return result


@router.post("/speech/recognize")
async def speech_recognize(request: Request, file: UploadFile = File(...)):
    _check_services_initialized()
    
    filename = file.filename or ""
    file_ext = filename.split(".")[-1].lower() if "." in filename else "wav"
    
    audio_data = await file.read()
    
    text = await _audio_service.speech_to_text(audio_data, format=file_ext)
    
    if not text:
        raise HTTPException(status_code=400, detail="无法识别语音内容")

    if text.startswith("[ERROR]"):
        return {
            "recognized_text": "",
            "reply_text": text,
            "products": [],
            "need_more_info": False,
            "questions": [],
            "session_id": request.headers.get("X-Session-ID", "default")
        }

    session_id = request.headers.get("X-Session-ID", "default")
    session = _session_manager.get_session(session_id)
    if not session:
        session = _session_manager.create_session(session_id)

    _session_manager.update_session(session_id, "user", text)

    context = {
        "preferences": session.preferences.dict(),
        "interaction_count": session.interaction_count,
        "history": session.get_history(5)
    }

    response = _capability_manager.process(text, context)

    base_url = get_base_url(request)

    if response.products:
        return {
            "recognized_text": text,
            "reply_text": response.reply_text,
            "products": products_to_dict_list(response.products, base_url),
            "need_more_info": response.need_more_info,
            "questions": response.questions,
            "session_id": session_id
        }

    from rag.prompt import build_prompt
    from utils.category_detector import detect_category
    from utils.product_card_parser import PRODUCT_CARD_PATTERN, strip_product_card_markers

    category = detect_category(text)
    retrieved_products = _retriever.search(text, top_k=5, category_filter=category)

    prompt_context = {
        'original_category': category,
        'interaction_count': session.interaction_count,
        'session': session.dict()
    }
    prompt = build_prompt(text, retrieved_products, prompt_context)
    ai_response = await _doubao_service.generate_response(prompt)
    clean_response = strip_product_card_markers(ai_response)

    card_ids = PRODUCT_CARD_PATTERN.findall(ai_response)
    recommended_ids = [pid.strip() for pid in card_ids] if card_ids else []
    recommended_products = [
        p for p in retrieved_products if p.id in recommended_ids
    ] if recommended_ids else retrieved_products

    _session_manager.update_session(session_id, "assistant", clean_response)

    return {
        "recognized_text": text,
        "reply_text": clean_response if clean_response else response.reply_text,
        "products": products_to_dict_list(recommended_products, base_url),
        "need_more_info": response.need_more_info,
        "questions": response.questions,
        "session_id": session_id
    }


@router.post("/speech/synthesize")
async def speech_synthesize(text: str, voice: str = "female"):
    _check_services_initialized()
    
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="文本内容不能为空")
    
    audio_data = await _audio_service.text_to_speech(text, voice)
    
    if not audio_data:
        raise HTTPException(status_code=500, detail="语音合成失败")
    
    return Response(
        content=audio_data,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f"attachment; filename=speech.mp3"
        }
    )


@router.post("/image/search")
async def image_search(request: Request, file: UploadFile = File(...)):
    """
    拍照找货 - 使用图像向量化检索相似商品
    
    流程：
    1. 端侧等比缩放（800px上限）+ JPEG压缩（quality=80）
    2. Base64编码
    3. 后端Doubao-embedding-vision图像向量化
    4. 向量检索product_images collection（独立图像索引）
    5. 返回视觉相似商品
    
    Doubao-embedding-vision将文本和图像映射到同一2048维向量空间，
    图搜和文搜结果可直接关联商品ID，无需额外跨模态映射。
    """
    _check_services_initialized()

    image_data = await file.read()

    if not image_data:
        raise HTTPException(status_code=400, detail="图像数据为空")

    # 使用图像向量化检索
    products, analysis = await _image_service.search_similar_products_by_image(image_data, _retriever)

    base_url = get_base_url(request)

    analysis_text = ""
    object_name = ""
    search_method = analysis.get("method", "vlm") if isinstance(analysis, dict) else "vlm"
    
    if isinstance(analysis, dict):
        analysis_text = analysis.get("description", "")
        object_name = analysis.get("object_name", "")
    elif analysis:
        analysis_text = str(analysis)

    reply_text = ""
    has_match = len(products) > 0

    if object_name or analysis_text:
        attr_parts = []
        if object_name: attr_parts.append(f"物品: {object_name}")
        if isinstance(analysis, dict):
            if analysis.get("color"): attr_parts.append(f"颜色: {analysis['color']}")
            if analysis.get("brand"): attr_parts.append(f"品牌: {analysis['brand']}")
            if analysis.get("style"): attr_parts.append(f"风格: {analysis['style']}")
            if analysis.get("key_features"): attr_parts.append(f"特征: {', '.join(analysis['key_features'])}")
        attr_text = ", ".join(attr_parts) if attr_parts else analysis_text[:200]

        transition_prompt = f"""你是"小豆"，用户的AI闺蜜兼购物助手。

用户刚刚拍了一张照片，AI视觉识别结果：
{attr_text}

商品库匹配结果：{len(products)} 个相关商品

请生成一句自然的回复（30-50字），要求：
1. 先确认你看到了什么（如"我看到了你拍的{object_name}～"）
2. 有匹配商品：自然地引出推荐
3. 无匹配商品：诚实告知，建议用户描述需求
4. 闺蜜风格，自然口语化
5. 只输出回复文本"""

        try:
            ai_transition = await _doubao_service.generate_response(transition_prompt)
            reply_text = ai_transition.strip() if ai_transition else ""
        except Exception as e:
            print(f"生成图片过渡回复失败: {e}")

    if not reply_text:
        if object_name:
            if has_match:
                reply_text = f"我看到你拍的啦～这是一个{object_name}对吧？帮你找了几款相关的商品，看看有没有喜欢的～"
            else:
                reply_text = f"嗯嗯我看到啦，这是一个{object_name}～不过目前暂时还没有这类商品呢。要不要跟我说说你想要什么样的，我帮你找找？"
        else:
            if has_match:
                reply_text = "我看到你拍的照片啦～帮你找了几款相似的商品，看看有没有喜欢的～"
            else:
                reply_text = "我看到你的照片啦～但目前暂时没有找到匹配的商品呢。可以描述一下你想要什么类型的，我帮你精准推荐～"

    return {
        "analysis": analysis_text,
        "reply_text": reply_text,
        "products": products_to_dict_list(products, base_url),
        "count": len(products) if products else 0,
        "search_method": search_method
    }


@router.post("/image/search/vlm")
async def image_search_vlm(request: Request, file: UploadFile = File(...)):
    """
    拍照找货（VLM降级模式）- 使用VLM识别物体属性后进行文本检索
    
    流程：
    1. VLM识别物体属性（名称/类目/颜色/材质/品牌/特征）
    2. 用类目过滤 + 多关键词组合搜索
    3. 返回匹配商品 + 分析结果
    """
    _check_services_initialized()

    image_data = await file.read()

    if not image_data:
        raise HTTPException(status_code=400, detail="图像数据为空")

    products, analysis = await _image_service.search_similar_products(image_data, _retriever)

    base_url = get_base_url(request)

    analysis_text = ""
    object_name = ""
    if isinstance(analysis, dict):
        analysis_text = analysis.get("description", "")
        object_name = analysis.get("object_name", "")
    elif analysis:
        analysis_text = str(analysis)

    reply_text = ""
    has_match = len(products) > 0

    if object_name or analysis_text:
        attr_parts = []
        if object_name: attr_parts.append(f"物品: {object_name}")
        if isinstance(analysis, dict):
            if analysis.get("color"): attr_parts.append(f"颜色: {analysis['color']}")
            if analysis.get("brand"): attr_parts.append(f"品牌: {analysis['brand']}")
            if analysis.get("style"): attr_parts.append(f"风格: {analysis['style']}")
            if analysis.get("key_features"): attr_parts.append(f"特征: {', '.join(analysis['key_features'])}")
        attr_text = ", ".join(attr_parts) if attr_parts else analysis_text[:200]

        transition_prompt = f"""你是"小豆"，用户的AI闺蜜兼购物助手。

用户刚刚拍了一张照片，AI视觉识别结果：
{attr_text}

商品库匹配结果：{len(products)} 个相关商品

请生成一句自然的回复（30-50字），要求：
1. 先确认你看到了什么（如"我看到了你拍的{object_name}～"）
2. 有匹配商品：自然地引出推荐
3. 无匹配商品：诚实告知，建议用户描述需求
4. 闺蜜风格，自然口语化
5. 只输出回复文本"""

        try:
            ai_transition = await _doubao_service.generate_response(transition_prompt)
            reply_text = ai_transition.strip() if ai_transition else ""
        except Exception as e:
            print(f"生成图片过渡回复失败: {e}")

    if not reply_text:
        if object_name:
            if has_match:
                reply_text = f"我看到你拍的啦～这是一个{object_name}对吧？帮你找了几款相关的商品，看看有没有喜欢的～"
            else:
                reply_text = f"嗯嗯我看到啦，这是一个{object_name}～不过目前暂时还没有这类商品呢。要不要跟我说说你想要什么样的，我帮你找找？"
        else:
            if has_match:
                reply_text = "我看到你拍的照片啦～帮你找了几款相似的商品，看看有没有喜欢的～"
            else:
                reply_text = "我看到你的照片啦～但目前暂时没有找到匹配的商品呢。可以描述一下你想要什么类型的，我帮你精准推荐～"

    return {
        "analysis": analysis_text,
        "reply_text": reply_text,
        "products": products_to_dict_list(products, base_url),
        "count": len(products) if products else 0,
        "search_method": "vlm"
    }


@router.post("/chat/voice")
async def voice_chat(request: Request, file: UploadFile = File(...)):
    _check_services_initialized()
    
    filename = file.filename or ""
    file_ext = filename.split(".")[-1].lower() if "." in filename else "wav"
    
    audio_data = await file.read()
    
    text = await _audio_service.speech_to_text(audio_data, format=file_ext)
    
    if not text:
        raise HTTPException(status_code=400, detail="无法识别语音内容")

    if text.startswith("[ERROR]"):
        return {
            "recognized_text": "",
            "reply_text": text,
            "products": [],
            "need_more_info": False,
            "questions": [],
            "session_id": request.headers.get("X-Session-ID", "default")
        }

    session_id = request.headers.get("X-Session-ID", "default")
    session = _session_manager.get_session(session_id)
    if not session:
        session = _session_manager.create_session(session_id)

    _session_manager.update_session(session_id, "user", text)

    context = {
        "preferences": session.preferences.dict(),
        "interaction_count": session.interaction_count,
        "history": session.get_history(5)
    }

    response = _capability_manager.process(text, context)

    base_url = get_base_url(request)

    if response.products:
        speech_audio = await _audio_service.text_to_speech(response.reply_text)
        return {
            "recognized_text": text,
            "reply_text": response.reply_text,
            "speech_audio_base64": base64.b64encode(speech_audio).decode('utf-8') if speech_audio else "",
            "products": products_to_dict_list(response.products, base_url),
            "need_more_info": response.need_more_info,
            "questions": response.questions,
            "session_id": session_id
        }

    from rag.prompt import build_prompt
    from utils.category_detector import detect_category
    from utils.product_card_parser import PRODUCT_CARD_PATTERN, strip_product_card_markers

    category = detect_category(text)
    retrieved_products = _retriever.search(text, top_k=5, category_filter=category)

    prompt_context = {
        'original_category': category,
        'interaction_count': session.interaction_count,
        'session': session.dict()
    }
    prompt = build_prompt(text, retrieved_products, prompt_context)
    ai_response = await _doubao_service.generate_response(prompt)
    clean_response = strip_product_card_markers(ai_response)

    card_ids = PRODUCT_CARD_PATTERN.findall(ai_response)
    recommended_ids = [pid.strip() for pid in card_ids] if card_ids else []
    recommended_products = [
        p for p in retrieved_products if p.id in recommended_ids
    ] if recommended_ids else retrieved_products

    _session_manager.update_session(session_id, "assistant", clean_response)

    reply_text = clean_response if clean_response else response.reply_text
    speech_audio = await _audio_service.text_to_speech(reply_text)

    import base64
    return {
        "recognized_text": text,
        "reply_text": reply_text,
        "speech_audio_base64": base64.b64encode(speech_audio).decode('utf-8') if speech_audio else "",
        "products": products_to_dict_list(recommended_products, base_url),
        "need_more_info": response.need_more_info,
        "questions": response.questions,
        "session_id": session_id
    }