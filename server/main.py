import os
from dotenv import load_dotenv
load_dotenv()

# 设置 Hugging Face 镜像
if os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT")
if os.getenv("HF_HUB_DISABLE_SYMLINKS"):
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = os.getenv("HF_HUB_DISABLE_SYMLINKS")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from rag.retriever import ProductRetriever
from rag.prompt import build_prompt
from services.doubao_service import DoubaoService
from services.session_manager import SessionManager
from services.feedback_manager import FeedbackManager
from services.audio_service import AudioService
from services.image_service import ImageService
from utils.product_repo import product_repo
from agent import setup_agents


# 初始化 FastAPI 应用
app = FastAPI(title="Ecommerce AI Agent API", version="1.0.0")

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "data", "ecommerce_agent_dataset")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化服务"""
    # 🆕 初始化数据库（会话和消息持久化）
    from db.relational import init_db
    await init_db()

    # 初始化商品仓库（数据层，最先加载）
    product_repo.load()

    # 初始化检索器
    retriever = ProductRetriever()
    retriever.initialize()
    
    # 初始化其他服务
    doubao_service = DoubaoService()
    session_manager = SessionManager()
    feedback_manager = FeedbackManager()
    # 初始化多模态服务
    audio_service = AudioService()
    image_service = ImageService()

    # 为商品图片建立向量索引（后台异步，不阻塞启动）
    if image_service.image_collection and image_service.image_collection.count() == 0:
        import os as _os, asyncio as _asyncio
        static_dir = _os.path.join(_os.path.dirname(__file__), "data", "ecommerce_agent_dataset")
        image_products = []
        for p in product_repo.all():
            if p.image_path:
                full_path = _os.path.join(static_dir, p.image_path)
                if _os.path.exists(full_path):
                    image_products.append({
                        "id": p.id,
                        "title": p.title,
                        "brand": p.brand,
                        "category": p.category,
                        "image_url": full_path,
                    })
        if image_products:
            async def _index_in_background():
                try:
                    count = await image_service.index_product_images_async(image_products)
                    print(f"[startup] 图像索引完成: {count} 张")
                except Exception as e:
                    print(f"[startup] 图像索引跳过（需配置 DOUBAO_EMBEDDING_VISION_MODEL 为有效 endpoint ID）: {e}")
            _asyncio.create_task(_index_in_background())
        else:
            print("[startup] 无可索引的商品图片")

    # 导入并注册路由
    from routers.chat import set_services as set_chat_services, router as chat_router
    from routers.products import set_retriever as set_product_retriever, router as products_router
    from routers.session import set_session_manager as set_session_mgr, router as session_router
    from routers.feedback import set_feedback_manager as set_feedback_mgr, router as feedback_router
    from routers.multimodal import set_services as set_multimodal_services, router as multimodal_router
    
    # 设置服务实例
    set_chat_services(retriever, doubao_service, session_manager, image_service)
    set_product_retriever(retriever)
    set_session_mgr(session_manager)
    set_feedback_mgr(feedback_manager)
    set_multimodal_services(audio_service, image_service, retriever, session_manager, doubao_service)

    # 设置 Agent 依赖注入
    setup_agents(retriever, doubao_service, session_manager)
    
    # 注册路由
    app.include_router(chat_router)
    app.include_router(products_router)
    app.include_router(session_router)
    app.include_router(feedback_router)
    app.include_router(multimodal_router)
    
    print("所有服务初始化完成，路由已注册")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
