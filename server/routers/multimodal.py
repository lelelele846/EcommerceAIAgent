"""
多模态交互 API — 支持语音识别、语音合成和图像搜索。

核心功能：
    1. 语音识别（ASR）：将语音转为文字，进入正常对话流程
    2. 语音合成（TTS）：将文本转为语音音频
    3. 拍照找货：通过图像向量化检索相似商品
    4. VLM 降级模式：图像向量化失败时，使用 VLM 识别物体属性后文本检索

技术亮点：
    - Doubao-embedding-vision 将文本和图像映射到同一 2048 维向量空间
    - 图搜和文搜结果可直接关联商品 ID，无需额外跨模态映射
    - 端侧等比缩放（800px 上限）+ JPEG 压缩（quality=80）减少传输量
"""
import os
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, Response
from utils.product_repo import products_to_dict_list

router = APIRouter(prefix="/api", tags=["multimodal"])

_audio_service = None
_image_service = None
_retriever = None
_session_manager = None
_doubao_service = None


def set_services(audio_service, image_service, retriever, session_manager, doubao_service):
    global _audio_service, _image_service, _retriever, _session_manager, _doubao_service
    _audio_service = audio_service
    _image_service = image_service
    _retriever = retriever
    _session_manager = session_manager
    _doubao_service = doubao_service


def _check_services_initialized():
    if None in [_audio_service, _image_service, _retriever, _session_manager, _doubao_service]:
        raise HTTPException(status_code=503, detail="服务正在初始化中，请稍后重试")


def get_base_url(http_request: Request) -> str:
    env_url = os.getenv("SERVER_BASE_URL")
    if env_url:
        return env_url.rstrip("/")
    host = http_request.headers.get("host", "localhost:8080")
    scheme = http_request.headers.get("x-forwarded-proto", "http")
    return f"{scheme}://{host}"


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

